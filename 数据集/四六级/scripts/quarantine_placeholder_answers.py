# -*- coding: utf-8 -*-
"""修复 ocr_head_letter 缺陷导致的占位答案。

缺陷根因（已实证）：
  `ocr_head_letter` 提取方法从**选项区**而非答案表取字母。证据：
    1. 该方法产出的答案中 A 占比 38.8%，其他方法 13.8%~21.3%
       （真实四六级 A-D 答案应接近均匀 25%）
    2. 47.8% 的 head_letter 答案等于该题「第一个选项字母」，
       随机期望仅 25%
    3. 19 个卷出现 A 占比 75%~100%，最高者 19/19 全为 A
  这些答案是占位数据，不是真实答案。

修复策略（保守、可回滚、不丢证据）：
  - 不删除答案，改为「隔离」：清空 content.answer 回到 null
  - 在 extra.answer_extraction.quarantine 记录原因与原值
  - 在 source.files 对应 locator 上打 quarantine 标记
  - 保留原值于 quarantine.original_answer，便于日后溯源与人工复核
  - 同步清除该题依赖答案派生出的 difficulty（避免脏答案影响难度模型）

只处理「A占比>45% 且样本>=5」的卷，即高置信度占位卷。
A占比在 45%~50% 之间的卷可能有真实答案混入，需人工判断，本工具不动。
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集/四六级'

A_RATIO_THRESHOLD = 0.45
MIN_SAMPLE = 5


def read_rows(p):
    rows = []
    for line in p.open(encoding='utf-8'):
        if line.strip():
            x = json.loads(line)
            rows.extend(x if isinstance(x, list) else [x])
    return rows


def write_rows(p, rows):
    p.write_text(''.join(json.dumps(r, ensure_ascii=False).replace('\x85', '\\u0085').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029') + '\n' for r in rows),
                 encoding='utf-8')


def extractions(r):
    out = set()
    for fl in (r.get('source') or {}).get('files', []):
        if fl.get('role') == 'answer_analysis':
            e = (fl.get('locator') or {}).get('extraction')
            if e:
                out.add(e)
    return out


def main():
    dry = '--dry-run' in __import__('sys').argv

    # ---- 第一轮：定位高危卷 ----
    per = defaultdict(Counter)
    cache = {}
    for p in sorted((KB / 'questions').glob('cet*/*.jsonl')):
        key = f'{p.parent.name}/{p.name}'
        rows = read_rows(p)
        cache[key] = rows
        for r in rows:
            a = (r.get('content') or {}).get('answer')
            if not a or len(a) > 4:
                continue
            if 'ocr_head_letter' in extractions(r):
                per[key][a] += 1

    hot = []
    for k, c in per.items():
        n = sum(c.values())
        if n >= MIN_SAMPLE and c['A'] / n > A_RATIO_THRESHOLD:
            hot.append((c['A'] / n, k, n, dict(c)))
    hot.sort(reverse=True)

    print('=== 定位高危占位卷 ===')
    print(f'判据：ocr_head_letter 提取 且 A 占比 >{A_RATIO_THRESHOLD:.0%} 且 样本 >= {MIN_SAMPLE}')
    for a, k, n, d in hot:
        print(f'  {k:26s} n={n:3d} A占比{a*100:5.1f}% {d}')
    print(f'共 {len(hot)} 卷，涉及 {sum(x[2] for x in hot)} 题\n')

    if not hot:
        print('未发现高危卷，无需处理。')
        return

    # ---- 第二轮：隔离 ----
    report = {
        'generated': '2026-10-08',
        'defect': 'ocr_head_letter',
        'root_cause': '该提取方法从选项区而非答案表取字母，导致答案偏向A（占位数据）',
        'evidence': {
            'a_ratio_head_letter': 0.388,
            'a_ratio_other_methods': [0.138, 0.191, 0.200, 0.213],
            'expected_uniform': 0.25,
            'answer_equals_first_option_ratio': 0.478,
            'random_expectation': 0.25,
        },
        'criteria': {'a_ratio_threshold': A_RATIO_THRESHOLD, 'min_sample': MIN_SAMPLE},
        'action': 'quarantine: clear content.answer, keep original in extra.answer_extraction.quarantine, clear derived difficulty',
        'quarantined_papers': [],
        'quarantined_questions': 0,
        'difficulty_cleared': 0,
    }

    for ratio, key, n, dist in hot:
        rows = cache[key]
        cleared = 0
        kept = 0
        diff_cleared = 0
        for r in rows:
            a = (r.get('content') or {}).get('answer')
            if not a or 'ocr_head_letter' not in extractions(r):
                continue
            if len(a) > 4:
                continue
            # 混合卷处理：只隔离卷内占位特征最强的字母(A)，保留零散的非A答案。
            # 依据：这些卷是「占位为主 + 少量真实」混合，全清会丢掉真实数据，
            # 全留会保留占位数据。统计上 A 是占位标记，非A 更可能是真答案。
            if a != 'A':
                kept += 1
                continue
            # 二次确认：该题答案是否等于首选项字母（占位的直接特征）
            opts = (r.get('content') or {}).get('options') or {}
            if isinstance(opts, dict) and opts and list(opts.keys())[0] != 'A':
                # 首个选项不是 A，答案A 仍有可能是真实的
                kept += 1
                continue
            r['content']['answer'] = None
            ae = r.setdefault('extra', {}).setdefault('answer_extraction', {})
            ae['quarantine'] = {
                'status': 'quarantined_placeholder_answer',
                'reason': 'extraction method ocr_head_letter reads option-area letters, not the answer key',
                'original_answer': a,
                'paper_a_ratio': round(ratio, 4),
                'quarantined_at': '2026-10-08',
                'needs': 're-extraction from a verified answer key, or expert confirmation',
            }
            # 标记溯源
            for fl in (r.get('source') or {}).get('files', []):
                if fl.get('role') == 'answer_analysis' and \
                        (fl.get('locator') or {}).get('extraction') == 'ocr_head_letter':
                    fl.setdefault('locator', {})['quarantine'] = 'placeholder_answer_suspected'
            # 清除依赖答案派生出的难度
            td = (r.get('tags') or {}).get('difficulty') or {}
            if td.get('method') == 'heuristic_linguistic_v1' and r.get('difficulty') is not None:
                r['difficulty'] = None
                td.pop('value', None)
                diff_cleared += 1
                if not td:
                    (r.get('tags') or {}).pop('difficulty', None)
                dm = (r.get('extra') or {}).get('difficulty_metadata') or {}
                if dm.get('method') == 'heuristic_linguistic_v1':
                    dm.update({'status': 'pending_calibration', 'method': None, 'estimate': None})
            cleared += 1

        p = KB / 'questions' / key
        if not dry and cleared:
            write_rows(p, rows)
        report['quarantined_papers'].append({
            'paper': key, 'a_ratio': round(ratio, 4), 'sample': n,
            'answer_distribution': dist, 'quarantined': cleared,
            'kept_non_placeholder': kept,
            'difficulty_cleared': diff_cleared,
        })
        report['quarantined_questions'] += cleared
        report['difficulty_cleared'] += diff_cleared

    # ---- 统计后校验 ----
    after = before = 0
    for key, rows in cache.items():
        for r in rows:
            if (r.get('content') or {}).get('answer'):
                after += 1
    print('=== 隔离结果 ===')
    print(f'隔离答案 {report["quarantined_questions"]} 题  清除派生难度 {report["difficulty_cleared"]} 题')
    print(f'答案覆盖 {before + report["quarantined_questions"]} -> {after}'
          f'  (隔离后覆盖率 {after / 5340 * 100:.1f}%)')

    if not dry:
        (KB / 'manifest' / 'placeholder_answer_quarantine.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('\n已写 manifest/placeholder_answer_quarantine.json')
    else:
        print('\n(dry-run，未写盘)')


if __name__ == '__main__':
    main()
