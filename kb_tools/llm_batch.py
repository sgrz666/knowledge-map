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
  python llm_batch.py upgrade-analysis --limit 20  # 把已有来源解析正文结构化改写,来源文本作输入凭据

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
import hashlib
from datetime import datetime, timezone

from build_kb import OUT, out_file
from ntce_io import atomic_write

sys.stdout.reconfigure(encoding='utf-8')

BATCH_TAG = 8        # 精标每次请求题数
BATCH_ANALYSIS = 4   # 解析每次请求题数
SLEEP = 0.5          # 请求间隔秒
MAX_STEM = 6000
MAX_OPTION = 2500
MAX_MATERIAL = 18000
USAGE = []
LAST_CALL = {}
USAGE_PATH = OUT / 'review/llm_usage.jsonl'


class BudgetLimit(RuntimeError):
    pass


def usage_spent():
    if not USAGE_PATH.exists():
        return 0.0
    with USAGE_PATH.open(encoding='utf-8') as handle:
        return sum(json.loads(line).get('conservative_cost_cny', 0) for line in handle if line.strip())


def read_records(path):
    with path.open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_call(record):
    USAGE_PATH.parent.mkdir(exist_ok=True)
    with USAGE_PATH.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')


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
    global LAST_CALL
    request_body = {'model': cfg['LLM_MODEL'], 'messages': messages, 'temperature': 0.2, 'max_tokens': 4096}
    if cfg['LLM_MODEL'] == 'deepseek-flash':
        request_body['thinking'] = {'type': 'disabled'}
    body = json.dumps(request_body, ensure_ascii=False).encode('utf-8')
    # UTF-8字节数作保守输入token上界，预留最大输出；高峰价且缓存全部按未命中计。
    reserve = (len(body) + 64) * 2 / 1_000_000 + 4096 * 8 / 1_000_000
    if cfg.get('budget_cny') is not None and usage_spent() + reserve > cfg['budget_cny']:
        raise BudgetLimit('累计保守预算不足以预留本次完整请求，停止并保存断点。')
    req = urllib.request.Request(
        cfg['LLM_BASE_URL'].rstrip('/') + '/chat/completions', data=body,
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + cfg['LLM_API_KEY']})
    LAST_CALL = {'created_at': datetime.now(timezone.utc).isoformat(), 'requested_model': cfg['LLM_MODEL'],
                 'method': 'llm', 'prompt_sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode('utf-8')).hexdigest(),
                 'input_bytes': len(body), 'thinking': request_body.get('thinking'), 'status': 'request_pending',
                 'question_ids': cfg.get('question_ids', [])}
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        usage = data.get('usage', {})
        USAGE.append(usage)
        cost = (usage.get('prompt_tokens', 0) * 2 + usage.get('completion_tokens', 0) * 8) / 1_000_000
        LAST_CALL.update({'response_model': data.get('model'), 'response_id': data.get('id'), 'usage': usage,
                         'conservative_cost_cny': cost if usage else reserve, 'status': 'response_received',
                         'finish_reason': data['choices'][0].get('finish_reason')})
        save_call(LAST_CALL)
        return data['choices'][0]['message']['content']
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError) as e:
        LAST_CALL.update({'status': 'provider_error', 'error_type': type(e).__name__, 'conservative_cost_cny': reserve})
        save_call(LAST_CALL)
        raise RuntimeError('LLM 请求失败，已保存错误断点并保守预留费用；未自动重试。') from e


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
    opts = ' '.join('%s.%s' % (o['key'], o['text']) for o in c['options'])
    ans = '答案:%s' % c['answer'] if c['answer'] else ''
    mat = ''
    if mat_text:
        mat = ' | 材料:' + mat_text
    return '%s | %s %s %s%s' % (r['question_id'], c['stem'], opts, ans, mat)


def input_status(r, mat_text=None):
    reasons = []
    c, review = r['content'], r.get('review', {})
    if review.get('checked_by') or review.get('tagger') == 'expert' or review.get('content_verified'):
        reasons.append('manual_review_protected')
    if is_junk(r):
        reasons.append('source_stem_incomplete')
    if review.get('cross_question_risk'):
        reasons.append('cross_question_risk')
    if r.get('extra', {}).get('source_boundary_verification', {}).get('status') == 'ambiguous_boundary_candidates':
        reasons.append('source_boundary_ambiguous')
    if r.get('source', {}).get('raw_file_verification', {}).get('content_alignment') != 'stem_excerpt_found':
        reasons.append('source_stem_not_located')
    if r.get('material_id') and not mat_text:
        reasons.append('linked_material_missing')
    from ntce_material_repair import case_risks
    if case_risks(r, mat_text or ''):
        reasons.append('case_material_boundary_unresolved')
    if r.get('question_type') in ('单选', '多选') and (len(c['options']) != 4 or any(not o['text'].strip() for o in c['options'])):
        reasons.append('options_incomplete')
    complete_inputs = '\n'.join([c['stem'], mat_text or ''] + [o['text'] for o in c['options']])
    if re.search(r'如图|下图|图示|见图|图\s*\d|图中|下表|表格|公式图像|公式图片|图像如下', complete_inputs) and not r.get('extra', {}).get('visual_source_verified'):
        reasons.append('visual_context_not_verified')
    if re.search(r'划线|画线|加点|加粗|斜体', complete_inputs) and not r.get('extra', {}).get('formatting_source_verified'):
        reasons.append('formatted_context_not_verified')
    oversize = []
    if len(c['stem']) > MAX_STEM:
        oversize.append({'field': 'content.stem', 'length': len(c['stem']), 'limit': MAX_STEM})
    oversize.extend({'field': 'content.options.' + o['key'], 'length': len(o['text']), 'limit': MAX_OPTION} for o in c['options'] if len(o['text']) > MAX_OPTION)
    if len(mat_text or '') > MAX_MATERIAL:
        oversize.append({'field': 'material.text', 'length': len(mat_text), 'limit': MAX_MATERIAL})
    if oversize:
        reasons.append('context_exceeds_reviewed_budget')
    return {'status': 'skipped' if reasons else 'complete', 'reasons': reasons, 'input_truncated': False,
            'truncated_fields': [], 'oversize_fields': oversize, 'material_included': bool(mat_text)}


def is_junk(r):
    return len(r['content']['stem'].strip()) < 10 or '暂缺' in r['content']['stem']


def load_materials(level, subject):
    """material_id → 材料全文(打标时给主观题补充上下文)"""
    out = {}
    for mf in OUT.glob('materials/%s/%s/*.jsonl' % (level, subject)):
        for m in read_records(mf):
            out[m['material_id']] = m['text']
    return out


def load_outline(level, subject):
    p = out_file('outline', '%s.%s.json' % (level, subject))
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding='utf-8'))
    return [(n['node_id'], n['name']) for n in doc['nodes'] if n.get('assessable', True)]


def iter_subject_files():
    for qf in sorted(OUT.glob('questions/*/*/*.jsonl')):
        yield qf.parent.parent.name, qf.parent.name, qf


ANALYSIS_EXCLUSIONS = re.compile(r'疾病|营养|健康|病症|用药|急救|窒息|出血|感染|药物|尿床|骨折|诊断|法律|法规|宪法|民法|教师法|教育法|义务教育|未成年|犯罪|刑法|行政|申诉|赔偿|监护|侵权|处分|罚款|规章|纲要')


def analysis_eligible(r, material_text, cfg):
    c = r['content']
    selected = set(cfg.get('question_ids_filter') or ())
    return (c['answer_status'] == 'letter_only' and not c.get('analysis') and not r.get('analysis')
            and (not selected or r['question_id'] in selected)
            and r.get('review', {}).get('type_source_verification', {}).get('status') == 'verified_choice_task_and_section'
            and input_status(r, material_text)['status'] == 'complete'
            and len(c['options']) == 4 and all(o['text'] for o in c['options'])
            and c['answer'] in [o['key'] for o in c['options']]
            and not ANALYSIS_EXCLUSIONS.search(question_brief(r, material_text))
            and r['extra'].get('llm_analysis_signature') != hashlib.sha256(('analysis-v3|' + cfg['LLM_MODEL'] + '|' + question_brief(r, material_text)).encode('utf-8')).hexdigest())


def analysis_upgrade_eligible(r, material_text, cfg):
    """已有来源解析正文、但结构化解析缺段的客观题；来源正文是改写输入凭据。"""
    c = r['content']
    text = c.get('analysis')
    selected = set(cfg.get('question_ids_filter') or ())
    complete_structured = isinstance(r.get('analysis'), dict) and all(
        isinstance(r['analysis'].get(f), str) and r['analysis'][f].strip()
        for f in ('key_info', 'option_compare', 'trace_back', 'explanation'))
    return (c['answer_status'] == 'letter_only' and isinstance(text, str) and len(text.strip()) >= 20
            and not complete_structured
            and (not selected or r['question_id'] in selected)
            and r.get('review', {}).get('type_source_verification', {}).get('status') == 'verified_choice_task_and_section'
            and input_status(r, material_text)['status'] == 'complete'
            and len(c['options']) == 4 and all(o['text'] for o in c['options'])
            and c['answer'] in [o['key'] for o in c['options']]
            and not ANALYSIS_EXCLUSIONS.search(question_brief(r, material_text))
            and r['extra'].get('llm_analysis_signature') != hashlib.sha256(('analysis-upgrade-v1|' + cfg['LLM_MODEL'] + '|' + question_brief(r, material_text)).encode('utf-8')).hexdigest())


def refine_tag(cfg, limit, untagged_only=False):
    """同科跨文件拼批，保存具体语义证据；已人工审核的题永不覆盖。"""
    from collections import defaultdict
    import hashlib
    groups, files = defaultdict(list), {}
    provider_failures = {}
    if USAGE_PATH.exists():
        for line in USAGE_PATH.open(encoding='utf-8'):
            call = json.loads(line)
            for qid in call.get('question_ids', []):
                if call.get('status') == 'provider_error':
                    provider_failures[qid] = call
                elif call.get('status') == 'response_received':
                    provider_failures.pop(qid, None)
    for level, subject, qf in iter_subject_files():
        records = read_records(qf)
        files[qf] = records
        groups[(level, subject)].extend((record, qf) for record in records)
    attempted = tagged = 0
    exhausted = False
    for (level, subject), group in sorted(groups.items()):
        if limit and attempted >= limit:
            break
        nodes = load_outline(level, subject)
        if not nodes:
            continue
        node_list = '\n'.join('%s = %s' % (nid, name) for nid, name in nodes)
        mats = load_materials(level, subject)
        todo = []
        for r, path in group:
            if untagged_only and r['knowledge_node_ids']:
                continue
            context = input_status(r, mats.get(r.get('material_id')))
            r['extra']['llm_tag_input_status'] = context
            if context['status'] != 'complete':
                continue
            payload = question_brief(r, mats.get(r.get('material_id')))
            signature = hashlib.sha256(('tag-v3|' + cfg['LLM_MODEL'] + '|' + node_list + '|' + payload).encode('utf-8')).hexdigest()
            if r['question_id'] in provider_failures and not r['extra'].get('llm_tag_result'):
                r['extra']['llm_tag_signature'] = signature
                r['extra']['llm_tag_result'] = {'status': 'provider_error', 'nodes': [], 'input_context': context, 'generation': provider_failures[r['question_id']]}
            retry = cfg.get('retry_failed') and r['extra'].get('llm_tag_result', {}).get('status') == 'provider_error'
            if r['extra'].get('llm_tag_signature') != signature or retry:
                todo.append((r, path, signature, context))
        for i in range(0, len(todo), BATCH_TAG):
            if limit and attempted >= limit:
                break
            count = min(BATCH_TAG, limit - attempted) if limit else BATCH_TAG
            batch = todo[i:i + count]
            briefs = '\n'.join('%d. %s' % (j + 1, question_brief(r, mats.get(r.get('material_id'))))
                               for j, (r, _, _, _) in enumerate(batch))
            prompt = ('细知识点ID与名称：\n' + node_list + '\n依据实际题干选择最匹配1-3个细知识点，'
                      '不能只按题型或学科名匹配。证据不足或残片保留nodes=[]，reason写具体题干证据。'
                      '只输出JSON数组：[{"q":序号,"nodes":["ID"],"reason":"题干依据"}]。\n' + briefs)
            try:
                cfg['question_ids'] = [r['question_id'] for r, _, _, _ in batch]
                items = parse_json_array(chat(cfg, [{'role': 'user', 'content': prompt}]))
            except BudgetLimit:
                print('达到累计5元保守预算，保留未尝试队列。', flush=True)
                exhausted = True
                break
            except RuntimeError as error:
                print(str(error), flush=True)
                items = []
                exhausted = True
            by_q = {item.get('q'): item for item in items if isinstance(item, dict)}
            valid = {nid for nid, _ in nodes}
            touched = set()
            for j, (record, path, signature, context) in enumerate(batch):
                item = by_q.get(j + 1)
                ids = [nid for nid in ((item or {}).get('nodes') or []) if nid in valid][:3]
                if record['extra'].get('llm_tag_result'):
                    record['extra'].setdefault('llm_tag_attempts', []).append(record['extra']['llm_tag_result'])
                record['extra']['llm_tag_signature'] = signature
                record['extra']['llm_tag_result'] = {'nodes': ids, 'reason': (item or {}).get('reason'),
                    'status': 'provider_error' if LAST_CALL.get('status') == 'provider_error' else 'draft_pending_expert' if ids else 'unmatched' if item else 'invalid_response',
                    'input_context': context, 'generation': dict(LAST_CALL)}
                if ids:
                    record['knowledge_node_ids'] = ids
                    record['review']['tagger'] = 'llm-v2'
                    record['review']['content_verified'] = False
                    record['extra']['tagging_evidence'] = [{'method': 'llm_semantic_draft',
                        'reason': item.get('reason'), 'expert_verified': False}]
                    tagged += 1
                touched.add(path)
            for path in sorted(touched):
                atomic_write(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in files[path]))
            attempted += len(batch)
            print('%s/%s 尝试%d题，细标%d题' % (level, subject, attempted, tagged), flush=True)
            if exhausted:
                break
            time.sleep(SLEEP)
        # 保存被跳过题的上下文状态，后续只读检查不用再猜测截断情况。
        for path in {path for _, path in group}:
            atomic_write(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in files[path]))
        if exhausted:
            break
    from ntce_repair import repair
    repair(skip_outline=True)
    print('refine-tag：尝试%d题，细标%d题' % (attempted, tagged))


def gen_analysis(cfg, limit, upgrade=False):
    """为仅有字母答案的客观题生成四段式解析(upgrade=把已有来源解析正文结构化改写),标记自动初标"""
    done = attempted = 0
    exhausted = False
    sample = []
    subjects = set(cfg.get('subjects') or ('zonghe', 'jiaoxue', 'jiaoyuzhishi', 'jiaoyuxue', 'jiaoyuxinlixue'))
    for level, subject, qf in iter_subject_files():
        if subject not in subjects:
            continue
        recs = read_records(qf)
        mats = load_materials(level, subject)
        eligible = analysis_upgrade_eligible if upgrade else analysis_eligible
        todo = [r for r in recs if eligible(r, mats.get(r.get('material_id')), cfg)]
        if not todo:
            continue
        for i in range(0, len(todo), BATCH_ANALYSIS):
            if limit and attempted >= limit:
                break
            batch = todo[i:i + min(BATCH_ANALYSIS, (limit - attempted) if limit else BATCH_ANALYSIS)]
            if upgrade:
                briefs = '\n'.join('%d. %s | 来源解析:%s' % (j + 1, question_brief(r, mats.get(r.get('material_id'))),
                                   ' '.join(str(r['content']['analysis']).split())) for j, r in enumerate(batch))
                prompt = ('把以下各题的来源解析整理成待审核的四段结构化解析草稿。来源解析是输入凭据，保留其判断与要点，'
                          '不新增其未给出的论断，不宣称官方答案；来源解析与给定答案矛盾时status=answer_disputed并说明。'
                          '输出每题题干关键信息、每个选项为何对错、判断步骤；只能引用题干、选项和来源解析实际内容。'
                          '若依赖缺失图像，不推断图像内容。每题100-220字。'
                          '仅输出JSON数组:[{"q":序号,"status":"draft","analysis":{"key_info":"具体信息",'
                          '"option_compare":"逐项解释","trace_back":"相关概念与判断步骤","explanation":"逐题解析"}}]。\n\n%s' % briefs)
            else:
                briefs = '\n'.join('%d. %s' % (j + 1, question_brief(r, mats.get(r.get('material_id')))) for j, r in enumerate(batch))
                prompt = ('为以下题目撰写待审核的逐题解析草稿，不宣称官方答案，不编造引文。'
                          '保留给定原始答案，如存疑，status=answer_disputed并解释；无法解释则analysis=null。'
                          '输出每题题干关键信息、每个选项为何对错、判断步骤；只能引用题干和选项实际内容。'
                          '若依赖缺失图像，不推断图像内容。每题100-220字。'
                          '仅输出JSON数组:[{"q":序号,"status":"draft","analysis":{"key_info":"具体信息",'
                          '"option_compare":"逐项解释","trace_back":"相关概念与判断步骤","explanation":"逐题解析"}}]。\n\n%s' % briefs)
            cfg['question_ids'] = [r['question_id'] for r in batch]
            try:
                items = parse_json_array(chat(cfg, [{'role': 'user', 'content': prompt}]))
            except BudgetLimit:
                print('解析样本因累计预算预留不足停止。', flush=True)
                exhausted = True
                break
            except RuntimeError as error:
                print(str(error), flush=True)
                items = []
                exhausted = True
            by_q = {it.get('q'): it for it in items if isinstance(it, dict)}
            for j, r in enumerate(batch):
                item = by_q.get(j + 1) or {}
                a = item.get('analysis')
                source_text = r['content'].get('analysis')
                if item.get('status') == 'draft' and not (isinstance(a, dict) and all(isinstance(a.get(field), str) and a[field].strip() for field in ('key_info', 'option_compare', 'trace_back', 'explanation'))):
                    item['status'] = 'invalid_three_segment_response'
                r['extra']['llm_analysis_signature'] = hashlib.sha256((('analysis-upgrade-v1|' if upgrade else 'analysis-v3|') + cfg['LLM_MODEL'] + '|' + question_brief(r, mats.get(r.get('material_id')))).encode('utf-8')).hexdigest()
                r['extra']['llm_analysis_result'] = {'status': 'provider_error' if LAST_CALL.get('status') == 'provider_error' else item.get('status', 'invalid_response'), 'result': item,
                    'input_context': input_status(r, mats.get(r.get('material_id'))), 'generation': dict(LAST_CALL)}
                if upgrade:
                    r['extra']['llm_analysis_result']['source_analysis_input'] = source_text
                if isinstance(a, dict) and a.get('explanation') and item.get('status') == 'draft':
                    if upgrade and isinstance(r.get('analysis'), dict):
                        r['extra'].setdefault('llm_analysis_attempts', []).append(r['analysis'])
                    r['content']['analysis'] = a['explanation']
                    r['analysis'] = {**a, 'status': 'llm_draft_pending_expert', 'expert_verified': False,
                                     'correct_answer': r['content']['answer'], 'method': 'llm_structured_from_source' if upgrade else 'llm',
                                     'input_evidence_files': r['source'].get('files', []),
                                     'generation': dict(LAST_CALL), 'input_context': input_status(r, mats.get(r.get('material_id'))),
                                     'source_note': '来源解析原文是输入凭据，模型只做结构化改写；改写稿没有已出版来源，需专家比对原文后审核。' if upgrade else '原始答案与题干是输入凭据；模型解析没有已出版来源，考试范围条款不能证明具体答案。',
                                     'knowledge_node_ids': r['knowledge_node_ids'], 'ability_ids': r.get('ability_ids', [])}
                    r['analysis']['exam_requirement_ids'] = r.get('exam_requirement_ids', [])
                    r['extra']['analysis_status'] = 'draft(llm-upgrade-v1)' if upgrade else 'draft(llm-v2)'
                    done += 1
                sample.append({'question_id': r['question_id'], 'source_files': r['source'].get('files', []),
                               'stem': r['content']['stem'], 'options': r['content']['options'], 'source_answer': r['content']['answer'],
                               'source_analysis': source_text if upgrade else None,
                               'analysis': r.get('analysis'), 'result': r['extra']['llm_analysis_result']})
            attempted += len(batch)
            atomic_write(qf, '\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n')
            print('  %s/%s 已处理 %d/%d' % (level, subject, min(i + BATCH_ANALYSIS, len(todo)), len(todo)))
            if LAST_CALL.get('status') == 'provider_error':
                break
            time.sleep(SLEEP)
        sync_cards(level, subject, recs)
        if exhausted or (limit and attempted >= limit):
            break
    print('gen-analysis%s 完成:本次生成 %d 条解析' % ('(升级)' if upgrade else '', done))
    atomic_write(OUT / 'review/llm_analysis_sample.jsonl', ''.join(json.dumps(record, ensure_ascii=False) + '\n' for record in sample))
    from ntce_repair import repair
    repair(skip_outline=True)


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
            atomic_write(card, new)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    limit = None
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    untagged_only = '--untagged-only' in sys.argv
    cfg = env_config()
    if '--model' in sys.argv:
        cfg['LLM_MODEL'] = sys.argv[sys.argv.index('--model') + 1]
    cfg['retry_failed'] = '--retry-failed' in sys.argv
    if '--subjects' in sys.argv:
        cfg['subjects'] = sys.argv[sys.argv.index('--subjects') + 1].split(',')
    if '--question-ids-file' in sys.argv:
        with open(sys.argv[sys.argv.index('--question-ids-file') + 1], encoding='utf-8') as handle:
            cfg['question_ids_filter'] = json.load(handle)
        if not cfg['question_ids_filter']:
            raise SystemExit('题目ID限制文件为空，拒绝启动无限制解析。')
    if '--budget-cny' in sys.argv:
        cfg['budget_cny'] = float(sys.argv[sys.argv.index('--budget-cny') + 1])
        if cfg['LLM_MODEL'] != 'deepseek-flash':
            raise SystemExit('当前人民币预算只配置了deepseek-flash保守价格；其他模型需另核价。')
    if mode == 'refine-tag':
        refine_tag(cfg, limit, untagged_only)
    elif mode == 'gen-analysis':
        gen_analysis(cfg, limit)
    elif mode == 'upgrade-analysis':
        gen_analysis(cfg, limit, upgrade=True)
    else:
        print(__doc__)
    if USAGE:
        usage = {'calls': len(USAGE), 'prompt_tokens': sum(u.get('prompt_tokens', 0) for u in USAGE),
                 'completion_tokens': sum(u.get('completion_tokens', 0) for u in USAGE)}
        print('实际API用量：' + json.dumps(usage, ensure_ascii=False))
