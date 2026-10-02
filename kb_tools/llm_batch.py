# -*- coding: utf-8 -*-
"""LLM 批量管线:知识点精标(refine-tag)与六段式解析生成(gen-analysis)

凭据只从环境变量读取,代码与输出中不写入任何密钥:
  LLM_API_KEY    必需,API 密钥
  LLM_BASE_URL   必需,OpenAI 兼容接口根,如 https://api.example.com/v1
  LLM_MODEL      必需,模型名,如 glm-4.6
  LLM_ALLOW_LOCAL 可选,=1 时允许本机/内网推理服务(默认拒绝,防 SSRF)

用法:
  python llm_batch.py refine-tag  --limit 50    # 先小批量试跑
  python llm_batch.py refine-tag                # 全量(可中断重跑,自动跳过已处理)
  python llm_batch.py gen-analysis --limit 20

所有 LLM 产出均标记"自动初标,待专家审核",不覆盖人工标注。
"""
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

from build_kb import OUT, out_file

sys.stdout.reconfigure(encoding='utf-8')

BATCH_TAG = 8        # 精标每次请求题数
BATCH_ANALYSIS = 4   # 解析每次请求题数
SLEEP = 0.5          # 请求间隔秒
MAX_STEM = 400       # 题干截断长度


def validate_base_url(url):
    """协议白名单 + 主机解析校验 + 阻断私网/环回/链路本地地址(SSRF 防护)"""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('https', 'http'):
        raise SystemExit('LLM_BASE_URL 仅支持 http/https: %r' % url)
    host = p.hostname
    if not host:
        raise SystemExit('LLM_BASE_URL 缺少主机名: %r' % url)
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SystemExit('LLM_BASE_URL 主机解析失败: %r' % e)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved \
                or ip.is_multicast or ip.is_unspecified:
            if os.environ.get('LLM_ALLOW_LOCAL') == '1':
                break
            raise SystemExit('LLM_BASE_URL 指向内网/保留地址已拒绝(%s);'
                             '如确需本机推理服务,设置 LLM_ALLOW_LOCAL=1' % ip)
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 禁止跟随重定向


_OPENER = urllib.request.build_opener(_NoRedirect)


def env_config():
    cfg = {k: os.environ.get(k) for k in ('LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL')}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        print('缺少环境变量:%s' % ', '.join(missing))
        print('示例(PowerShell): $env:LLM_API_KEY="..."; $env:LLM_BASE_URL="https://api.example.com/v1"; $env:LLM_MODEL="glm-4.6"')
        sys.exit(1)
    cfg['LLM_BASE_URL'] = validate_base_url(cfg['LLM_BASE_URL'])
    return cfg


def chat(cfg, messages, timeout=120):
    body = json.dumps({'model': cfg['LLM_MODEL'], 'messages': messages,
                       'temperature': 0.2, 'max_tokens': 4096}).encode('utf-8')
    req = urllib.request.Request(
        cfg['LLM_BASE_URL'].rstrip('/') + '/chat/completions', data=body,
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + cfg['LLM_API_KEY']})
    for attempt in range(3):
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content']
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError) as e:
            if attempt == 2:
                raise RuntimeError('LLM 请求失败:%r' % e)
            time.sleep(2 * (attempt + 1))


def parse_json_array(text):
    m = text.find('[')
    n = text.rfind(']')
    if m == -1 or n == -1:
        return []
    try:
        return json.loads(text[m:n + 1])
    except json.JSONDecodeError:
        return []


def question_brief(r, mat_text=None):
    c = r['content']
    opts = ' '.join('%s.%s' % (o['key'], o['text'][:60]) for o in c['options'])
    ans = '答案:%s' % c['answer'] if c['answer'] else ''
    mat = ''
    if mat_text:
        mat = ' | 材料:' + mat_text[:250].replace('\n', ' ')
    return '%s | %s %s %s%s' % (r['question_id'], c['stem'][:MAX_STEM], opts[:300], ans, mat)


def is_junk(r):
    return len(r['content']['stem'].strip()) < 10 or '暂缺' in r['content']['stem']


def load_materials(level, subject):
    """material_id → 材料全文(打标时给主观题补充上下文)"""
    out = {}
    for mf in OUT.glob('materials/%s/%s/*.jsonl' % (level, subject)):
        for line in mf.open(encoding='utf-8'):
            m = json.loads(line)
            out[m['material_id']] = m['text']
    return out


def load_outline(level, subject):
    p = out_file('outline', '%s.%s.json' % (level, subject))
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding='utf-8'))
    return [(n['node_id'], n['name']) for n in doc['nodes']]


def iter_subject_files():
    for qf in sorted(OUT.glob('questions/*/*/*.jsonl')):
        yield qf.parent.parent.name, qf.parent.name, qf


def refine_tag(cfg, limit, untagged_only=False):
    """对有大纲科目的题目做 LLM 精标;--untagged-only 只补规则未命中的题。不覆盖已有人工/llm 标注"""
    done = 0
    for level, subject, qf in iter_subject_files():
        nodes = load_outline(level, subject)
        if not nodes:
            continue
        mats = load_materials(level, subject)
        recs = [json.loads(l) for l in qf.open(encoding='utf-8')]
        todo = [r for r in recs if r['review']['tagger'] != 'llm-v1' and not is_junk(r)]
        if untagged_only:
            todo = [r for r in todo if not r['knowledge_node_ids']]
        if not todo:
            continue
        node_list = '\n'.join('%s = %s' % (nid, name) for nid, name in nodes)
        for i in range(0, len(todo), BATCH_TAG):
            if limit and done >= limit:
                break
            batch = todo[i:i + BATCH_TAG]
            briefs = '\n'.join('%d. %s' % (j + 1, question_brief(r, mats.get(r.get('material_id'))))
                               for j, r in enumerate(batch))
            prompt = ('以下是一份知识点大纲(节点ID = 名称):\n%s\n\n'
                      '请为每道题从上述节点中选出最匹配的 1-3 个节点ID。'
                      '只输出 JSON 数组,格式:[{"q": 序号, "nodes": ["节点ID", ...]}],不要输出其他内容。\n\n%s'
                      % (node_list, briefs))
            items = parse_json_array(chat(cfg, [{'role': 'user', 'content': prompt}]))
            by_q = {it.get('q'): it.get('nodes') for it in items if isinstance(it, dict)}
            valid = {nid for nid, _ in nodes}
            for j, r in enumerate(batch):
                ids = by_q.get(j + 1) or []
                ids = [x for x in ids if x in valid][:3]
                if ids:
                    r['knowledge_node_ids'] = [x if x.startswith('ntce.') else
                                               'ntce.%s.%s.%s' % (level, subject, x.split('.')[-1])
                                               for x in ids]
                    r['review']['tagger'] = 'llm-v1'
                    done += 1
            qf.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n', encoding='utf-8')
            print('  %s/%s 已处理 %d/%d' % (level, subject, min(i + BATCH_TAG, len(todo)), len(todo)))
            time.sleep(SLEEP)
    print('refine-tag 完成:本次精标 %d 题' % done)


def gen_analysis(cfg, limit):
    """为仅有字母答案的客观题生成六段式解析,标记自动初标"""
    done = 0
    for level, subject, qf in iter_subject_files():
        recs = [json.loads(l) for l in qf.open(encoding='utf-8')]
        todo = [r for r in recs
                if r['content']['answer_status'] == 'letter' and not r['content'].get('analysis')
                and not is_junk(r)]
        if not todo:
            continue
        for i in range(0, len(todo), BATCH_ANALYSIS):
            if limit and done >= limit:
                break
            batch = todo[i:i + BATCH_ANALYSIS]
            briefs = '\n'.join('%d. %s' % (j + 1, question_brief(r)) for j, r in enumerate(batch))
            prompt = ('请为每道题按固定结构写解析,六个部分依次:①正确答案及依据;②考查知识点;'
                      '③解题步骤;④常见错误选项分析;⑤同类题识别方法;⑥复习提示。'
                      '每题解析 150-250 字,用"①…②…"连接为一段。'
                      '只输出 JSON 数组:[{"q": 序号, "analysis": "…"}],不要输出其他内容。\n\n%s' % briefs)
            items = parse_json_array(chat(cfg, [{'role': 'user', 'content': prompt}]))
            by_q = {it.get('q'): it.get('analysis') for it in items if isinstance(it, dict)}
            for j, r in enumerate(batch):
                a = by_q.get(j + 1)
                if a:
                    r['content']['analysis'] = str(a)
                    r['extra']['analysis_status'] = '自动初标(llm-v1)'
                    done += 1
            qf.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n', encoding='utf-8')
            print('  %s/%s 已处理 %d/%d' % (level, subject, min(i + BATCH_ANALYSIS, len(todo)), len(todo)))
            time.sleep(SLEEP)
        sync_cards(level, subject, recs)
    print('gen-analysis 完成:本次生成 %d 条解析' % done)


def sync_cards(level, subject, recs):
    """把新生成的解析同步进卡片(仅替换解析占位行)"""
    for r in recs:
        if not r['content'].get('analysis') or r['extra'].get('duplicate_of'):
            continue
        card = out_file('cards', level, subject, r['source']['session'],
                        'q%02d.md' % r['extra']['paper_order'])
        if not card.exists():
            continue
        txt = card.read_text(encoding='utf-8')
        new = re.sub(r'\*\*解析:\*\*\(原库未提供,待补充\)',
                     '**解析:** %s\n\n> 自动初标(llm-v1),待专家审核' % r['content']['analysis'],
                     txt, count=1)
        if new != txt:
            card.write_text(new, encoding='utf-8')


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    limit = None
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    untagged_only = '--untagged-only' in sys.argv
    cfg = env_config()
    if mode == 'refine-tag':
        refine_tag(cfg, limit, untagged_only)
    elif mode == 'gen-analysis':
        gen_analysis(cfg, limit)
    else:
        print(__doc__)
