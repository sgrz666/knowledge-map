# -*- coding: utf-8 -*-
"""从官方解析册 PDF/文档补全题目答案与结构化解析。

原则（与既有 fill_answers.py 一致）：
  * 只搬运已出版解析册中的原文，不生成、推断或改写答案与解析。
  * 每条补全都记录 source.files 溯源（文件路径 + 页码/字符偏移）。
  * 答案按题型做合法性校验，冲突与低置信条目隔离，不写入主库。
  * 幂等：只填补缺失字段，已有的答案/解析保持不变。
"""
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cet_common import jsonl_dumps, load_jsonl  # noqa: E402
from fill_answers import pdf_text, docx_text  # noqa: E402
from cet_pdf_columns import parse_booklet  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

# 各题型合法答案字母集合
KEY_SETS = {
    '短篇新闻': 'ABCD', '长对话': 'ABCD', '听力篇章': 'ABCD', '讲座/讲话': 'ABCD',
    '选词填空': 'ABCDEFGHIJKLMNOP', '长篇阅读': 'ABCDEFGHIJKLMNOP', '仔细阅读': 'ABCD',
}
LISTENING = {'短篇新闻', '长对话', '听力篇章', '讲座/讲话'}

ANS_PATTERNS = [
    re.compile(r'^[（(]?([A-O])[)）]\s*【(?:精析|解析|详解)】'),
    re.compile(r'^[（(]?([A-O])[)）]\s*$', re.M),
    re.compile(r'答案\s*[:：]\s*([A-O])\b'),
    re.compile(r'正确答案\s*[:：是]?\s*([A-O])\b'),
]
# 「答案详解/答案解析」区块标记
BLOCK_MARK = re.compile(r'(?:^|\n)\s*(?:答案详解|答案解析|详解|试题解析|参考答案)')
# 题号行：1. / 1、/ (1) / 1．
QNUM = re.compile(r'(?:^|\n|\s)(?:[(（]\s*(\d{1,2})\s*[)）]|(\d{1,2})\s*[.．、])\s')
# 解析正文起始：X）【精析】/【语法判断】等—— 答案字母紧跟题号，是最可靠的锚点
EXP_START = re.compile(r'[（(]?([A-O])[)）]\s*【[^】]{1,12}】')
# 「N. 题干文字… X）【精析】」—— 题号与答案字母在同一段内的模式
PAIR = re.compile(
    r'(?:^|[\n\r])\s*(?:[(（]\s*(\d{1,2})\s*[)）]|(\d{1,2})\s*[.．、])'   # 1) 题号
    r'([^\n]{0,400}?)'                                              # 2) 题干
    r'[（(]?([A-O])[)）]\s*【[^】]{1,12}】'                          # 3) 答案 + 标签
    r'(.*?)'                                                        # 4) 解析正文（非贪婪）
    r'(?=(?:[\n\r]\s*(?:[(（]\d{1,2}[)）]|\d{1,2}\s*[.．、])[^\n]{0,400}?[（(][A-O][)）]\s*【)|$)',
    re.S)


def source_quality(path: Path):
    """粗判源可用性：good / broken_font / image_only。"""
    try:
        text = pdf_text(path) if path.suffix.lower() == '.pdf' else docx_text(path)
    except Exception:
        return 'unreadable', ''
    if len(text) < 500:
        return 'image_only', text
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    weird = len(re.findall(r'[\u0080-\u024f]', text))
    if cjk and weird / cjk > 0.3:
        return 'broken_font', text
    return 'good', text


def clean_columns(raw: str):
    """清理双栏排版造成的串栏噪声。

    同一物理行的左右两栏会被 PyMuPDF 拼成一行，中间常有大段空白或另一栏的碎片。
    规则：把「连续 6 个以上空格」视为栏间断点，丢弃断点右侧碎片；
    并丢弃从下一题题号/答案锚点起的内容。
    """
    if not raw:
        return raw
    # 截断到下一个答案锚点（下一题的 X）【…】 或 N. ）
    cut = re.search(r'\n\s*(?:[(（]?\d{1,2}[)）]|\d{1,2}\s*[.．、])[^\n]{0,200}?[（(][A-O][)）]\s*【', raw)
    if cut:
        raw = raw[:cut.start()]
    lines = []
    for ln in raw.split('\n'):
        # 栏间断点：右侧若为另一栏的英文/答案碎片则丢弃
        m = re.search(r'\S[ \t　]{6,}\S', ln)
        if m:
            # 保留左栏，过长的英文串（>=12 连续英文词）视为他栏内容
            right = ln[m.end() - 1:]
            if len(re.findall(r'[A-Za-z]{3,}', right)) >= 4:
                ln = ln[:m.start() + 1]
        lines.append(ln)
    out = '\n'.join(lines)
    return re.sub(r'[ \t　]{4,}', ' ', out).strip()


def parse_sections(text: str):
    """双栏安全的切分。

    解析册为左右双栏，PyMuPDF 按视觉行输出：同一行会先出现左栏内容、
    再出现右栏内容。题号与该题答案字母之间常被换行或另一栏片段隔开，
    因此采用「行扫描 + 状态机」：
      1) 遇到题号 -> 进入新题；
      2) 在该题范围内遇到 `X）【标签】` -> 记录答案字母并截取解析正文；
      3) 遇到下一题号 -> 收尾。
    串栏的英文碎片在写库前由 clean_columns 统一剔除。
    """
    marks = [m.start() for m in BLOCK_MARK.finditer(text)]
    region = text[marks[0]:] if marks else text

    # 逐行扫描，构造「逻辑行」：把被换行拆开的题号与答案重新拼接
    events = []   # (位置, 类型, 值)  类型: 'num' / 'key'
    pos = 0
    for ln in region.split('\n'):
        # 题号（行首，允许全角空格）
        mnum = re.match(r'[\s　]*(?:[(（]\s*(\d{1,2})\s*[)）]|(\d{1,2})\s*[.．、])\s*(.*)$', ln)
        if mnum:
            events.append((pos, 'num', (int(mnum.group(1) or mnum.group(2)), mnum.group(3))))
        else:
            # 行内出现的题号（非行首，排除小数与年份）
            for mm in re.finditer(r'(?:^|[\s　])(?:[(（]\s*(\d{1,2})\s*[)）]|(\d{1,2})\s*[.．、])\s', ln):
                n = int(mm.group(1) or mm.group(2))
                if 1 <= n <= 60:
                    events.append((pos, 'num', (n, ln[mm.end():])))
        # 答案锚点
        for mk in re.finditer(r'[（(]?([A-O])[)）]\s*【[^】]{1,12}】\s*', ln):
            events.append((pos, 'key', (mk.group(1), ln[mk.end():], mk.start())))
        pos += len(ln) + 1

    out = {}
    cur = None
    for off, kind, val in events:
        if kind == 'num':
            cur = val[0]
            if cur not in out:
                out[cur] = {'keys': [], 'raw': None, 'hint': None}
        elif kind == 'key':
            if cur is None:
                continue
            letter, rest, kstart = val
            # 同一题出现多个不同字母时只保留首个（避免跨栏串扰）
            if not out[cur]['keys']:
                out[cur]['keys'].append(letter)
                if rest and rest.strip():
                    out[cur]['raw'] = clean_columns(rest.strip())
            elif letter in out[cur]['keys'] and not out[cur]['raw'] and rest.strip():
                out[cur]['raw'] = clean_columns(rest.strip())
    # 提示标签
    for num, seg in out.items():
        mh = re.search(r'【(?:做题提示|听前预测|题目定位|解题思路|关键词)】\s*(.*?)(?=【[^】]+】|$)', seg.get('raw') or '', re.S)
        if mh:
            seg['hint'] = mh.group(1).strip()
    return out


def build_structured(raw: str, hint: str):
    """只重排已出版句子，绝不生成新的推理内容。"""
    if not raw:
        return None, None
    text = re.sub(r'\s*\n\s*', '', raw)
    text = re.sub(r'(?<=。)\s*', '', text).strip()
    sents = [s for s in re.split(r'(?<=[。；])', text) if s.strip()]
    comp = [s for s in sents if re.search(r'排除|选项|[A-O]\s*(?:项|和|、)', s)]
    return hint, (' '.join(comp) if comp else None)


def valid_key(key: str, qtype: str):
    if not key:
        return False
    allowed = KEY_SETS.get(qtype)
    if allowed:
        return key in allowed
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kb', default=str(ROOT / '数据集/四六级/questions'))
    ap.add_argument('--inventory', default=str(ROOT / '数据集/四六级/manifest/answer_source_inventory.json'))
    ap.add_argument('--out-report', default=str(ROOT / '数据集/四六级/manifest/answer_backfill_report.json'))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    inv = json.load(open(args.inventory, encoding='utf-8'))
    report = {'generated': '2026-10-07', 'method': 'published official analysis booklet text extraction; no generated answers',
              'filled_answers': 0, 'filled_analyses': 0, 'skipped_existing': 0,
              'quarantined_conflict': 0, 'quarantined_invalid_key': 0, 'papers': {}, 'skipped_list': []}

    for key, meta in sorted(inv.items()):
        jsonl = Path(meta['jsonl'])
        if not jsonl.exists():
            continue
        rows = load_jsonl(jsonl)
        if not rows:
            continue
        need = [r for r in rows if not (r.get('content') or {}).get('answer')]
        if not need:
            continue
        # 选最佳本地源
        pool = []
        for s in meta.get('local_sources') or []:
            p = Path(s['path'])
            if not p.exists():
                continue
            p = p if p.is_absolute() else ROOT / p
            if not p.exists():
                continue
            q, text = source_quality(p)
            pool.append((q, len(text), p, text))
        pool.sort(key=lambda x: (x[0] != 'good', -x[1]))
        if not pool or pool[0][0] != 'good':
            report['skipped_list'].append({'paper': key, 'reason': 'no_readable_local_source',
                                           'best_quality': pool[0][0] if pool else 'none'})
            continue
        q, _, src_path, text = pool[0]
        if src_path.suffix.lower() == '.pdf':
            try:
                secs = parse_booklet(str(src_path))     # 坐标分栏，抗双栏串扰
            except Exception:
                secs = parse_sections(text)               # 回退：行扫描
        else:
            secs = parse_sections(text)

        stat = {'filled': 0, 'analysis_filled': 0, 'skipped': 0, 'quarantine': 0, 'source': str(src_path)}
        for r in rows:
            content = r.get('content') or {}
            if content.get('answer'):
                report['skipped_existing'] += 1
                continue
            num = (r.get('extra') or {}).get('number')
            if num is None:
                stat['skipped'] += 1
                continue
            sec = secs.get(int(num))
            if not sec:
                stat['skipped'] += 1
                continue
            keys = set(sec['keys'])
            # 只保留该题型合法字母
            keys = {k for k in keys if valid_key(k, r.get('question_type') or '')}
            if len(keys) != 1:
                if keys:
                    report['quarantined_conflict'] += 1
                    stat['quarantine'] += 1
                else:
                    stat['skipped'] += 1
                continue
            key_letter = next(iter(keys))
            raw_src = sec.get('raw')
            hint = sec.get('hint')
            if not hint and raw_src:
                mh = re.search(r'【(?:做题提示|听前预测|题目定位|解题思路|关键词)】\s*(.*?)'
                               r'(?=【[^】]+】|$)', raw_src, re.S)
                if mh:
                    hint = mh.group(1).strip()
            hint, comp = build_structured(raw_src, hint)
            r['content']['answer'] = key_letter
            stat['filled'] += 1
            report['filled_answers'] += 1
            an = r.setdefault('analysis', {})
            if raw_src and not an.get("raw"):
                an["raw"] = raw_src
            if hint and not an.get('key_info'):
                an['key_info'] = hint
            if comp and not an.get('option_compare'):
                an['option_compare'] = comp
            if raw_src and not an.get("trace_back"):
                an["trace_back"] = f"官方解析册原文：{Path(src_path).name}"
            if raw_src:
                stat['analysis_filled'] += 1
                report['filled_analyses'] += 1
            # 溯源
            files = (r.get('source') or {}).setdefault('files', [])
            files.append({'path': str(src_path).replace('\\', '/'), 'role': 'answer_analysis',
                          'locator': {'question_number': int(num),
                                      'binding': 'published_analysis_booklet_text_layer',
                                      'extraction': 'text_layer'}})
        if stat['filled'] and not args.dry_run:
            jsonl.write_text(jsonl_dumps(rows), encoding='utf-8')
        report['papers'][key] = stat

    Path(args.out_report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"新增答案 {report['filled_answers']}  新增解析 {report['filled_analyses']}  "
          f"已存在跳过 {report['skipped_existing']}  冲突隔离 {report['quarantined_conflict']}  "
          f"无源跳过套数 {len(report['skipped_list'])}")


if __name__ == '__main__':
    main()
