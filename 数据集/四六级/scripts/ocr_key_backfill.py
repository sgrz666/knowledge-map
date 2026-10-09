# -*- coding: utf-8 -*-
"""从 ocr_cache 的 OCR 文本中提取答案键并补全题库。

发现：397 份 OCR 内容文本中，41 份含「题号+裸字母」格式的答案键表，
这些是官方答案解析册的答案页 OCR，可靠性高。

流程：
  1. 正则提取 (题号 -> 答案字母)，按题型做字母范围校验
  2. 与题库已有答案交叉验证，逐套算一致率
  3. 一致率 >= 0.95 才写入，只填缺失不覆盖
"""
import json, os, re, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cet_common import jsonl_dumps, load_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OCR = ROOT / '数据集/四六级/scripts/_staging/ocr_cache'

KEY_SETS = {'短篇新闻': 'ABCD', '长对话': 'ABCD', '听力篇章': 'ABCD', '讲座/讲话': 'ABCD',
            '选词填空': 'ABCDEFGHIJKLMNOP', '长篇阅读': 'ABCDEFGHIJKLMNOP', '仔细阅读': 'ABCD'}

# 题号+字母：允许 . ． 、 ， 等分隔，字母后必须行尾
ANS_LINE = re.compile(r'(?m)^[\s　]*(\d{1,2})\s*[.．、,，]\s*([A-P])\s*$')

# OCR 文本文件名 -> 试卷标识
# 例：2024年6月四级真题解析_第二套_.200dpi.txt-> CET-4|2024-06|第2套
KIND = [('四级', 'CET-4'), ('六级', 'CET-6')]


def guess_paper(name):
    """从 OCR 文件名推断 exam|年份|套数。识别不了返回 None。"""
    m = re.match(r'([0-9]{4})[.\-年]?\s*0?(\d{1,2})', name)
    if not m:
        return None
    year, mon = int(m.group(1)), int(m.group(2))
    if mon == 7:
        mon = 6                      # 2020.07 考试在 6 月举行
    level = None
    if '四级' in name or'4级' in name:
        level = 'CET-4'
    elif '六级' in name or '6级' in name:
        level = 'CET-6'
    if not level:
        return None
    # 套数
    p = None
    if re.search(r'第\s*1\s*套|卷\s*1|卷一|第一套', name):
        p = '第1套'
    elif re.search(r'第\s*2\s*套|卷\s*2|卷二|第二套', name):
        p = '第2套'
    elif re.search(r'第\s*3\s*套|卷\s*3|卷三|第三套', name):
        p = '第3套'
    if not p:
        return None
    return f'{level}|{year}-{mon:02d}|{p}'


def read_rows(path):
    """读 jsonl 为题目对象列表。

    注意：cet_common.load_jsonl 返回嵌套结构 [[行]]，且要求 Path 对象，
    这里直接用标准库读取，避免踩坑。
    """
    return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').split('\n') if l.strip()]


def write_rows(path, rows):
    """逐行 json.dumps，格式与现有题库文件保持一致。

    不用 cet_common.jsonl_dumps：它会对每行再包一层列表，
    反复调用会导致嵌套累积、并让整文件产生无意义 diff。
    """
    out = '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n'
    Path(path).write_text(out, encoding='utf-8')


def main():
    kb_index = {}          # 'CET-4|2024-06|第2套' -> jsonl path
    for lvl in ('cet4', 'cet6'):
        for f in (ROOT / f'数据集/四六级/questions/{lvl}').glob('*.jsonl'):
            m = re.match(r'([0-9]{4})-([0-9]{2})_p(\d)', f.stem)
            if m:
                key = f'CET-{4 if lvl=="cet4" else 6}|{m.group(1)}-{m.group(2)}|第{m.group(3)}套'
                kb_index[key] = f

    files = [f for f in sorted(os.listdir(OCR))
             if f.endswith('.txt') and not f.startswith('_list_')]
    report = {'generated': '2026-10-07',
              'method': 'OCR answer-key extraction from ocr_cache; cross-validated against existing KB answers; per-set agreement >=0.95 required',
              'ocr_scanned': len(files), 'sets_matched': 0, 'filled_answers': 0,
              'skipped_existing': 0, 'quarantined_invalid_letter': 0, 'quarantined_conflict': 0,
              'sets': [], 'skipped': []}

    for f in files:
        key = guess_paper(f)
        if not key or key not in kb_index:
            report['skipped'].append({'file': f, 'reason': 'unmapped_paper' if not key else 'no_kb_file'})
            continue
        text = (OCR / f).read_text(encoding='utf-8', errors='ignore')
        pairs = {}
        multi = defaultdict(set)
        for m in ANS_LINE.finditer(text):
            n, L = int(m.group(1)), m.group(2)
            multi[n].add(L)
        rows = read_rows(kb_index[key])
        bynum = {(r.get('extra') or {}).get('number'): r for r in rows}
        agree = dis = filled = 0
        detail = []
        for n, Ls in multi.items():
            r = bynum.get(n)
            if r is None:
                continue
            qt = r.get('question_type') or ''
            allowed = KEY_SETS.get(qt)
            ok = [L for L in Ls if allowed and L in allowed]
            if len(ok) != 1:
                report['quarantined_invalid_letter'] += 1
                detail.append({'q': n, 'ocr': sorted(Ls), 'qtype': qt, 'result': 'invalid_letter'})
                continue
            src = ok[0]
            known = (r.get('content') or {}).get('answer')
            if known:
                report['skipped_existing'] += 1
                if known == src:
                    agree += 1
                else:
                    dis += 1
                    detail.append({'q': n, 'kb': known, 'ocr': src, 'result': 'disagree'})
            else:
                filled += 1
                detail.append({'q': n, 'ocr': src, 'qtype': qt, 'result': 'would_fill'})
        checked = agree + dis
        rate = (agree / checked) if checked else None
        report['sets'].append({'paper': key, 'file': f, 'checked': checked, 'agree': agree,
                               'disagree': dis, 'agreement_rate': rate,
                               'new_answer_available': filled, 'detail': detail})
        report['sets_matched'] += 1

    # 只对达标的套执行写入
    trusted = [s for s in report['sets']
               if s['agreement_rate'] is not None and s['agreement_rate'] >= 0.95]
    report['trusted_sets'] = len(trusted)
    if '--apply' in sys.argv:
        for s in trusted:
            kb = kb_index[s['paper']]
            rows = read_rows(kb)
            bynum = {(r.get('extra') or {}).get('number'): r for r in rows}
            for d in s['detail']:
                if d['result'] != 'would_fill':
                    continue
                r = bynum.get(d['q'])
                if r is None or (r.get('content') or {}).get('answer'):
                    continue
                r['content']['answer'] = d['ocr']
                files_list = (r.get('source') or {}).setdefault('files', [])
                files_list.append({
                    'path': f'数据集/四六级/scripts/_staging/ocr_cache/{s["file"]}',
                    'role': 'answer_analysis',
                    'locator': {'question_number': d['q'],
                                'binding': 'official_answer_key_ocr',
                                'extraction': 'ocr_200dpi'}})
                report['filled_answers'] += 1
            write_rows(kb, rows)

    out = ROOT / '数据集/四六级/manifest/ocr_key_backfill_report.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'扫描OCR {report["ocr_scanned"]}份，匹配到题库试卷 {report["sets_matched"]} 套')
    print(f'达标套数 {report["trusted_sets"]}，可新增答案 {sum(s["new_answer_available"] for s in trusted)} 题')
    print(f'非法字母隔离 {report["quarantined_invalid_letter"]}，分歧 {sum(s["disagree"] for s in report["sets"])}')
    for s in sorted(trusted, key=lambda x: -x['new_answer_available'])[:15]:
        print(f"  {s['paper']:24s} 校验{s['checked']:3d} 一致率{s['agreement_rate']:.3f} 可补{s['new_answer_available']:3d}")


if __name__ == '__main__':
    main()
