# -*- coding: utf-8 -*-
"""生成 alignment_backfill_report.json：方案B（题号对齐）可行性结论 + 残留缺口。

核心结论（已由两种独立方法实证）：
  - 纯偏移搜索：21 套 distrusted 中没有一套在「常数偏移」或「按题型分段偏移」下
    达到 >=0.95 的一致率；最好的一套 CET-4|2020-12|第1套 仅 0.933。
  - 内容指纹 1:1 对齐（不依赖题号）：最好的一套 CET-6|2022-09|第1套 仅 0.889，
    多数远低于 0.95，且可匹配题数稀少。
  => 方案B 路径不可行，按红线整套隔离，零写入。
"""
import sys, json
from pathlib import Path
from collections import OrderedDict

ROOT = Path(__file__).resolve().parents[3]
M = ROOT / '数据集/四六级/manifest'
INV = json.load(open(M / 'answer_source_inventory.json', encoding='utf-8'))
TRUST = json.load(open(M / 'source_trust_report.json', encoding='utf-8'))
OFF = {r['paper']: r for r in json.load(open(M / 'offset_diagnosis.json', encoding='utf-8'))}
FP = {r['paper']: r for r in json.load(open(M / 'fingerprint_diagnosis.json', encoding='utf-8'))}

DISTRUSTED = [r['paper'] for r in TRUST['papers'] if r.get('status') == 'distrusted']

RED_LINE = 0.95

# 计算每套缺失题号（读 jsonl）
missing_by_paper = OrderedDict()
for paper in DISTRUSTED:
    meta = INV[paper]
    jl = ROOT / meta['jsonl']
    if not jl.exists():
        missing_by_paper[paper] = []
        continue
    miss = []
    for ln in jl.read_text(encoding='utf-8').splitlines():
        if not ln.strip():
            continue
        o = json.loads(ln)
        if not (o.get('content') or {}).get('answer'):
            n = (o.get('extra') or {}).get('number')
            if n is not None:
                miss.append(int(n))
    missing_by_paper[paper] = sorted(miss)

papers_report = []
total_missing = 0
for paper in DISTRUSTED:
    off = OFF.get(paper, {})
    fp = FP.get(paper, {})
    cb = off.get('constant_best')
    const_rate = cb[0] if cb else None
    const_c = cb[1] if cb else None
    const_n = cb[2] if cb else 0
    perqt = off.get('per_qtype_best') or {}
    perqt_best = {qt: (b[0], b[1]) for qt, b in perqt.items() if b}
    fp_rate = fp.get('rate')
    fp_checked = fp.get('checked') or 0
    # 决策：必须同时满足「高一致率」与「足够样本量」才算可写入。
    # 单题/极少数题偶然命中不能证明整套可靠（违背逐套校验红线）。
    MIN_COVERAGE = 10
    const_ok = (const_rate is not None and const_rate >= RED_LINE and const_n >= MIN_COVERAGE)
    fp_ok = (fp_rate is not None and fp_rate >= RED_LINE and fp_checked >= MIN_COVERAGE)
    best_rate = max([r for r in [const_rate, fp_rate] if r is not None] or [0])
    decision = 'ELIGIBLE' if (const_ok or fp_ok) else 'QUARANTINE'
    miss = missing_by_paper[paper]
    total_missing += len(miss)
    papers_report.append({
        'paper': paper,
        'offset_constant_best': {'rate': const_rate, 'C': const_c} if cb else None,
        'offset_per_qtype_best': perqt_best,
        'fingerprint_best_rate': fp_rate,
        'fingerprint_matched': fp.get('n_matched'),
        'best_achievable_rate': round(best_rate, 4),
        'red_line': RED_LINE,
        'decision': decision,
        'reason': ('no offset/fingerprint method reaches the 0.95 red line; '
                   'booklet numbering is incompatible with DB objective 1-55 scheme')
                  if decision == 'QUARANTINE' else '',
        'n_missing_in_this_paper': len(miss),
        'missing_question_numbers': miss,
    })

report = {
    'generated': '2026-10-07',
    'method': 'scheme_B_number_alignment',
    'red_line_per_set': RED_LINE,
    'verdict': 'INFEASIBLE',
    'verdict_summary': (
        '方案B（题号对齐）对 21 套 distrusted 解析册均不可行。'
        '纯偏移搜索与内容指纹 1:1 对齐两种独立方法，没有任何一套达到 >=0.95 的逐套一致率'
        '（最好 0.933 / 0.889）。解析册采用「真题解析」式编号，混排 听力/翻译/阅读，'
        '翻译等非客观题插入了数据库不跟踪的题号，导致编号与数据库 1-55 客观题编号'
        '不存在干净的常数/分段偏移关系；且多数解析册可提取的干净单字母答案块稀少。'
        '按红线整套隔离，零写入。'
    ),
    'offset_law': {
        'simple_constant_offset': False,
        'per_section_offset': False,
        'observed_pattern': (
            '解析册编号遵循「原卷顺序（写作→听力→阅读→翻译）」，在数据库不跟踪的翻译等非客观题'
            '处插入了题号，因此是「分段 + 插入」结构，而非对数据库 1-55 客观题编号的干净常数/分段偏移。'
            '部分解析册疑似章节错配或混合了多套内容（如某套长篇阅读答案整体错位）。'
        ),
        'best_constant_offset_rate': 0.933,
        'best_constant_offset_paper': 'CET-4|2020-12|第1套',
        'best_fingerprint_rate': 0.889,
        'best_fingerprint_paper': 'CET-6|2022-09|第1套',
    },
    'backfilled_answers': 0,
    'backfilled_analyses': 0,
    'quarantined_sets': len(DISTRUSTED),
    'total_remaining_missing_in_distrusted': total_missing,
    'papers': papers_report,
}

out = M / 'alignment_backfill_report.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

# 控制台摘要
print(f"verdict={report['verdict']}  backfilled_answers={report['backfilled_answers']}  "
      f"quarantined_sets={report['quarantined_sets']}  remaining_missing={total_missing}")
for p in papers_report:
    print(f"  {p['paper']:24s} const={p['offset_constant_best']} fp={p['fingerprint_best_rate']} "
          f"best={p['best_achievable_rate']} -> {p['decision']} (missing {p['n_missing_in_this_paper']})")
print("WROTE", out)
