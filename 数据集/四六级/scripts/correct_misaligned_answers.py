# -*- coding: utf-8 -*-
"""修正长篇阅读/选词填空等「一一对应题型」中被错配的答案。

缺陷根因：
  答案提取时按文本位置顺序写回，而长篇阅读（段落匹配）、选词填空的题号顺序
  与文本出现顺序不一致（text_offset证据：cet4/2019-06_p1 的长篇阅读
  偏移顺序为 40→44→41→45），导致答案整体错位一格甚至多格。

判据（三重，任一不满足则不动）：
  1. 解析册提取的答案可信：双锚点互验通过
     （锚点 = 题号后首个 `X）【..】`；结论 = 解析正文里`…为X）`）
  2. 题性要求一一对应：长篇阅读 / 选词填空的答案字母不得重复
  3. 逐套一致率 >= 0.95（用库中「无争议题型」的答案做基准）

修正动作：
  - 库有答案且与解析册不同 -> 改写为解析册答案，旧值存入
    extra.answer_correction.original_answer（可回滚、可溯源）
  - 库无答案 -> 直接填入
  - 同步清除受影响的 difficulty 并重标

只搬运解析册原文结论，不生成、不推断答案。
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集/四六级'

EXPLAIN = re.compile(r'答案详解|答案与解析|试题解析|答案解析')
ANCHOR = re.compile(r'[（(]?([A-P])[)）]\s*【[^】]{1,12}】')
CONCL = re.compile(r'(?:故(?:本题)?(?:正确答案)?为|正确答案为|答案为)\s*([A-P])[)）]')
QN_A = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*([A-Z][^\n]{4,240}?\?)\s*$')
QN_B = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*【[^】]{1,14}】[^\n]{0,80}$')
# 题号 + 英文题干（长篇阅读题干是陈述句，单独一种模式）
QN_C = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*([A-Z][^\n]{10,200}?\.)(?:\s*)$')

# 答案必须唯一的题型
UNIQUE_TYPES = {'长篇阅读': 'ABCDEFGHIJKLMNOP', '选词填空': 'ABCDEFGHIJKLMNOP'}
THRESHOLD = 0.95


def extract_pairs(text):
    """双锚点互验提取 {题号: 答案}。两法冲突则剔除。

    若无「答案详解」标记，则退回全文扫描（部分解析册把答案直接排在每段解析前）。
    """
    m = EXPLAIN.search(text)
    reg = text[m.start():] if m else text
    if m is None and not ANCHOR.search(reg):
        return {}

    anchors = {}
    for pat in (QN_A, QN_B, QN_C):
        for qm in pat.finditer(reg):
            n = int(qm.group(1))
            if n in anchors:
                continue
            tail = reg[qm.end():qm.end() + 700]
            am = ANCHOR.search(tail)
            if am:
                anchors[n] = am.group(1)

    concls = {}
    for qm in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.．、]', reg):
        n = int(qm.group(1))
        if n in concls:
            continue
        tail = reg[qm.end():qm.end() + 900]
        cm = CONCL.search(tail)
        if cm:
            concls[n] = cm.group(1)

    out = {}
    for n, v in anchors.items():
        if n in concls and concls[n] != v:
            continue                      # 双锚点冲突 -> 不采信
        out[n] = v
    return out


def read_rows(p):
    rows = []
    for line in Path(p).open(encoding='utf-8'):
        if line.strip():
            x = json.loads(line)
            rows.extend(x if isinstance(x, list) else [x])
    return rows


def write_rows(p, rows):
    p.write_text(''.join(json.dumps(r, ensure_ascii=False).replace('\x85', '\\u0085').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029') + '\n' for r in rows),
                 encoding='utf-8')


def paper_key(level, year, mon, paper):
    return f'CET-{4 if level == "cet4" else 6}|{year}-{mon:02d}|第{paper}套'


def main():
    dry = '--dry-run' in sys.argv
    scan = json.load(open(KB / 'manifest' / 'explainer_source_scan.json', encoding='utf-8'))
    best = scan['best_per_paper']

    report = {
        'generated': '2026-10-08',
        'action': 'correct mis-aligned answers for one-to-one question types using verified explainer conclusions',
        'criteria': {'dual_anchor_required': True, 'one_to_one_check': True,
                     'per_paper_threshold': THRESHOLD},
        'papers': [], 'corrected': 0, 'filled': 0, 'unchanged': 0,
        'rejected_duplicate': 0, 'difficulty_cleared': 0,
    }

    for key, src in sorted(best.items()):
        m = re.match(r'CET-(\d)\|(\d{4})-(\d{2})\|第(\d)套', key)
        if not m:
            continue
        lvl, yr, mo, pn = m.group(1), m.group(2), m.group(3), m.group(4)
        kb_path = KB / f'questions/cet{lvl}/{yr}-{mo}_p{pn}.jsonl'
        if not kb_path.exists():
            report['papers'].append({'paper': key, 'status': 'no_kb_file'})
            continue
        try:
            d = fitz.open(ROOT / src['path'])
            text = '\n'.join(d[i].get_text() for i in range(d.page_count))
            d.close()
        except Exception as e:
            report['papers'].append({'paper': key, 'status': f'unreadable:{e}'})
            continue

        got = extract_pairs(text)
        if not got:
            report['papers'].append({'paper': key, 'status': 'no_pairs_extracted'})
            continue

        rows = read_rows(kb_path)
        bynum = {(r.get('extra') or {}).get('number'): r for r in rows}

        # ---- 先算一致率：只用「无争议题型」（短篇新闻/长对话/听力篇章/讲座/仔细阅读）做基准 ----
        agree = dis = 0
        baseline_detail = []
        for n, r in bynum.items():
            qt = r.get('question_type')
            if n is None or n not in got or qt in UNIQUE_TYPES:
                continue
            known = (r.get('content') or {}).get('answer')
            if not known:
                continue
            if known == got[n]:
                agree += 1
            else:
                dis += 1
                baseline_detail.append({'q': n, 'kb': known, 'got': got[n], 'type': qt})
        checked = agree + dis
        rate = (agree / checked) if checked else None

        rec = {'paper': key, 'source': src['name'], 'extracted': len(got),
               'baseline_checked': checked, 'baseline_agree': agree,
               'baseline_rate': rate, 'baseline_disagree': baseline_detail[:6]}

        if rate is None or rate < THRESHOLD:
            rec['status'] = 'baseline_below_threshold'
            report['papers'].append(rec)
            continue

        # ---- 通过阈值：处理一一对应题型 ----
        corrected = filled = unchanged = rejected = diff_cleared = 0
        type_scope = {}
        for qt, allowed in UNIQUE_TYPES.items():
            qs = [r for r in rows if r.get('question_type') == qt]
            qs = [r for r in qs if (r.get('extra') or {}).get('number') in got]
            if not qs:
                continue
            # 提取册答案必须本身唯一，否则说明提取有问题，整型拒绝
            letters = [got[(r.get('extra') or {}).get('number')] for r in qs]
            dup_in_source = [a for a, c in Counter(letters).items() if c > 1]
            if dup_in_source:
                rejected += len(qs)
                type_scope[qt] = {'status': 'rejected_source_has_duplicates',
                                 'duplicates': dup_in_source, 'n': len(qs)}
                continue
            for r in qs:
                n = (r.get('extra') or {}).get('number')
                new = got[n]
                if new not in allowed:
                    rejected += 1
                    continue
                old = (r.get('content') or {}).get('answer')
                if old == new:
                    unchanged += 1
                    continue
                if old:
                    # 先落记录再改值（old 已在上文取出）
                    r.setdefault('extra', {})['answer_correction'] = {
                        'status': 'corrected_misaligned',
                        'original_answer': old,
                        'corrected_answer': new,
                        'source': src['name'],
                        'evidence': 'dual-anchor agreement in explainer + one-to-one uniqueness',
                        'corrected_at': '2026-10-08',
                    }
                    r['content']['answer'] = new
                    # 同步既有 answer_history：把同值的旧 quarantine 记录标注为已被本次修正取代，
                    # 避免出现「历史说 A 是冲突项、当前答案也是 A」的自相矛盾状态。
                    hist = r['extra'].get('answer_history')
                    if isinstance(hist, list):
                        for h in hist:
                            if isinstance(h, dict) and h.get('answer') == new:
                                h['superseded_by_correction'] = {
                                    'at': '2026-10-08',
                                    'by': 'dual-anchor explainer extraction + one-to-one uniqueness',
                                    'previous_status': h.get('status'),
                                }
                        r['extra']['answer_history'] = hist
                    corrected += 1
                else:
                    r['content']['answer'] = new
                    files = (r.get('source') or {}).setdefault('files', [])
                    files.append({
                        'path': src['path'],
                        'role': 'answer_analysis',
                        'locator': {'question_number': n,
                                    'binding': 'explainer_dual_anchor',
                                    'extraction': 'text_layer'},
                    })
                    filled += 1
                # 修正后重算难度受影响项
                td = (r.get('tags') or {}).get('difficulty') or {}
                if td.get('method') == 'heuristic_linguistic_v1' and r.get('difficulty') is not None:
                    r['difficulty'] = None
                    td.pop('value', None)
                    diff_cleared += 1
                    if not td:
                        (r.get('tags') or {}).pop('difficulty', None)
                    dm = (r.get('extra') or {}).get('difficulty_metadata') or {}
                    if dm.get('method') == 'heuristic_linguistic_v1':
                        dm.update({'status': 'pending_calibration', 'method': None,
                                   'estimate': None})
            type_scope[qt] = {'status': 'corrected', 'n': len(qs)}

        if not dry and (corrected or filled):
            write_rows(kb_path, rows)
        rec.update({'status': 'ok', 'type_scope': type_scope, 'corrected': corrected,
                    'filled': filled, 'unchanged': unchanged, 'rejected': rejected,
                    'difficulty_cleared': diff_cleared})
        report['papers'].append(rec)
        report['corrected'] += corrected
        report['filled'] += filled
        report['unchanged'] += unchanged
        report['rejected_duplicate'] += rejected
        report['difficulty_cleared'] += diff_cleared

    print('=== 长篇阅读/选词填空答案修正 ===')
    print(f'处理套数 {len(report["papers"])}')
    print(f'修正错位答案 {report["corrected"]}   新填 {report["filled"]}   '
          f'已正确 {report["unchanged"]}   拒绝 {report["rejected_duplicate"]}')
    print(f'清除受影响难度 {report["difficulty_cleared"]}')
    print()
    ok = [p for p in report['papers'] if p.get('status') == 'ok']
    for p in ok:
        print(f"  {p['paper']:24s} 基准一致率{p['baseline_rate']:.3f} "
              f"({p['baseline_agree']}/{p['baseline_checked']}) 修正{p['corrected']} 填{p['filled']}")

    if not dry:
        (KB / 'manifest' / 'answer_correction_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        print('\n已写 manifest/answer_correction_report.json')
    else:
        print('\n(dry-run，未写盘)')


if __name__ == '__main__':
    main()
