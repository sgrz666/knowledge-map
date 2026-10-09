"""分层启发式难度标定工具（教资KB）。

为 教资KB/questions/ 下全部题目填充 `difficulty`（0-1 浮点）。

设计约束（来自任务审计）：
- 只写 `difficulty` 与 `tags.difficulty`（方法标识），绝不改动 review / analysis /
  extra / rubric / source / copyright 等任何人工审核相关字段。
- 幂等：已非 null 的 `difficulty` 不重算；同一批数据跑两次，输出逐字节一致。
- 诚实标注：本工具没有作答数据，无法做真 IRT 校准，所有值均为分层启发式估算，
  在 `tags.difficulty.method` 中显式标记 `heuristic_*`，下游可据此区分「估算」与「校准」。
- 无法标定的题保持 null（answer_status=='source_conflict' 或题干残缺），不瞎填。

难度值在被 `ntce_repair.py` 复算时不会被清掉：repair 仅在 refresh_tags 读取
`q.get('difficulty')` 写入 `tags.difficulty.value`，从不回写 `difficulty` 字段本身。

运行（PowerShell）：
  & $kbPython -X utf8 kb_tools/ntce_difficulty.py
  & $kbPython -X utf8 kb_tools/ntce_difficulty.py --dry-run   # 只统计不写盘
"""
import json
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

from ntce_io import atomic_write

OUT = Path(__file__).resolve().parents[1] / '数据集' / '教资'
VERSION = 'heuristic-v1'

# 客观题特征权重（合计 1.0）；更高特征 = 更难。
OBJ_WEIGHTS = {
    'stem_len': 0.35,
    'opt_n': 0.10,
    'opt_len_var': 0.20,
    'max_opt_len': 0.20,
    'kn_n': 0.15,
}
OBJ_LO, OBJ_HI = 0.20, 0.85  # 客观题难度映射区间

# 主观题按题型固有复杂度给粗粒度基准难度
SUBJ_BASE = {
    '写作': 0.82,
    '论述': 0.76,
    '材料分析': 0.70,
    '活动设计': 0.68,
    '教学设计': 0.68,
    '诊断': 0.66,
    '辨析': 0.60,
    '解答': 0.55,
    '简答': 0.52,
    '未标注': 0.60,  # 题型未识别，按中等偏上保守估值并单独标记
}
SUBJ_DEFAULT = 0.60


def read_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding='utf-8') if line.strip()]


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))


def stem_incomplete(q):
    s = (q.get('content') or {}).get('stem', '') or ''
    return len(s.strip()) < 10 or '暂缺' in s


def classify(q):
    """返回 (bucket, reason)。bucket ∈ {'null','objective','subjective'}。"""
    c = q.get('content') or {}
    st = c.get('answer_status')
    qt = q.get('question_type')
    if st == 'source_conflict':
        return 'null', 'source_conflict'
    if stem_incomplete(q):
        return 'null', 'source_stem_incomplete'
    if st == 'letter_only' or qt in ('单选', '多选'):
        return 'objective', None
    return 'subjective', None


def obj_features(q):
    c = q['content']
    stem = c.get('stem', '') or ''
    opts = c.get('options', []) or []
    lens = [len(o.get('text', '') or '') for o in opts]
    if len(lens) >= 2:
        mean = sum(lens) / len(lens)
        var = sum((x - mean) ** 2 for x in lens) / len(lens)
    else:
        var = 0.0
    return {
        'stem_len': len(stem),
        'opt_n': len(opts),
        'opt_len_var': var,
        'max_opt_len': max(lens) if lens else 0,
        'kn_n': len(q.get('knowledge_node_ids') or []),
    }


def pct_ranker(values):
    """返回把特征值映射到 [0,1] 百分位秩的函数（平局取首位置）。"""
    s = sorted(values)
    n = len(s)
    first = {}
    for i, v in enumerate(s):
        first.setdefault(v, i)
    if n <= 1:
        return lambda v: 0.5
    return lambda v: first[v] / (n - 1)


def clamp(x, lo=0.05, hi=0.97):
    return max(lo, min(hi, x))


def round4(x):
    return round(x, 4)


def calibrate(all_questions, dry_run):
    """原地给可标定题目填 difficulty；返回分类统计。"""
    obj_qs = [q for q in all_questions if classify(q)[0] == 'objective']
    subj_qs = [q for q in all_questions if classify(q)[0] == 'subjective']

    # 客观题：先在全量客观题上算百分位秩，再加权合成
    feat_matrix = [obj_features(q) for q in obj_qs]
    rankers = {k: pct_ranker([f[k] for f in feat_matrix]) for k in OBJ_WEIGHTS}
    for q, f in zip(obj_qs, feat_matrix):
        if q.get('difficulty') is not None:
            continue  # 幂等：已标注（含人工）不动
        score = sum(OBJ_WEIGHTS[k] * rankers[k](f[k]) for k in OBJ_WEIGHTS)
        d = OBJ_LO + score * (OBJ_HI - OBJ_LO)
        q['difficulty'] = round4(clamp(d))
        tags = q.setdefault('tags', {})
        td = tags.setdefault('difficulty', {})
        td.update({
            'value': q['difficulty'],
            'status': 'provided',
            'method': 'heuristic_objective_v1',
            'calibration': 'heuristic',
            'version': VERSION,
            'features': {k: round4(f[k]) for k in OBJ_WEIGHTS},
        })

    # 主观题：按题型基准 + 题干长度的确定性微调（粗粒度）
    subj_stem = [len((q['content'].get('stem', '') or '')) for q in subj_qs]
    srank = pct_ranker(subj_stem)
    for q in subj_qs:
        if q.get('difficulty') is not None:
            continue
        qt = q.get('question_type')
        base = SUBJ_BASE.get(qt, SUBJ_DEFAULT)
        method = 'heuristic_subjective_v1' if qt in SUBJ_BASE else 'heuristic_subjective_unlabeled_v1'
        jitter = (srank(len((q['content'].get('stem', '') or ''))) - 0.5) * 0.08
        d = clamp(base + jitter, 0.30, 0.95)
        q['difficulty'] = round4(d)
        tags = q.setdefault('tags', {})
        td = tags.setdefault('difficulty', {})
        td.update({
            'value': q['difficulty'],
            'status': 'provided',
            'method': method,
            'calibration': 'heuristic',
            'version': VERSION,
            'features': {'type_base': base, 'stem_len': len(q['content'].get('stem', '') or '')},
        })

    return obj_qs, subj_qs


def main():
    dry = '--dry-run' in sys.argv
    files = sorted(OUT.glob('questions/*/*/*.jsonl'))
    batches = [(p, read_rows(p)) for p in files]
    all_q = [q for _, rows in batches for q in rows]

    before = sum(1 for q in all_q if q.get('difficulty') is not None)
    obj_qs, subj_qs = calibrate(all_q, dry)

    # 写回（仅当非 dry-run 且确有变化）；已标注题目跳过保证幂等
    written = 0
    if not dry:
        for path, rows in batches:
            write_rows(path, rows)
            written += 1

    after = sum(1 for q in all_q if q.get('difficulty') is not None)
    null_q = [q for q in all_q if q.get('difficulty') is None]
    reasons = Counter(classify(q)[1] for q in null_q)

    # 报告
    print('=== 难度标定报告 (heuristic-v1) ===')
    print('题目总数: %d' % len(all_q))
    print('标定前已有 difficulty: %d' % before)
    print('标定后已有 difficulty: %d' % after)
    print('本次新填: %d' % (after - before))
    print('保持 null: %d  (原因: %s)' % (len(null_q), dict(reasons)))
    print('客观题标定: %d' % len(obj_qs))
    print('主观题标定: %d' % len(subj_qs))

    # 分布
    filled = [q['difficulty'] for q in all_q if q.get('difficulty') is not None]
    bins = Counter()
    for d in filled:
        b = min(9, int(d * 10))
        bins[b] += 1
    print('\n难度分布直方图 (区间 0.0-1.0, 每 0.1 一档):')
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        bar = '#' * round(bins.get(b, 0) / max(1, max(bins.values())) * 40)
        print('  %4.1f-%4.1f | %5d %s' % (lo, hi, bins.get(b, 0), bar))

    def stats(vals):
        if not vals:
            return 'n=0'
        vals2 = sorted(vals)
        n = len(vals2)
        return 'n=%d min=%.3f med=%.3f mean=%.3f max=%.3f' % (
            n, vals2[0], vals2[n // 2], sum(vals2) / n, vals2[-1])

    print('\n客观题难度: ' + stats([q['difficulty'] for q in obj_qs]))
    print('主观题难度: ' + stats([q['difficulty'] for q in subj_qs]))
    # 学段/题型分布
    by_type = defaultdict(list)
    for q in all_q:
        if q.get('difficulty') is not None:
            by_type[q['question_type']].append(q['difficulty'])
    print('\n各题型难度:')
    for t in sorted(by_type, key=lambda k: -len(by_type[k])):
        print('  %-6s %s' % (t, stats(by_type[t])))
    by_level = defaultdict(list)
    for q in all_q:
        if q.get('difficulty') is not None:
            by_level[q['level']].append(q['difficulty'])
    print('\n各学段难度:')
    for lv in sorted(by_level):
        print('  %-10s %s' % (lv, stats(by_level[lv])))

    # 落盘机器可读报告
    report = {
        'version': VERSION,
        'total': len(all_q),
        'filled_total': after,            # 全库当前带 difficulty 值的题数（幂等重跑后仍为该总数）
        'new_this_run': after - before,   # 本次新填数量（幂等重跑应为 0）
        'kept_null': len(null_q),
        'null_reasons': dict(reasons),
        'objective_n': len(obj_qs),
        'subjective_n': len(subj_qs),
        'method_legend': {
            'heuristic_objective_v1': '客观题(letter/单选/多选) 基于题干长度/选项数/选项长度方差/最长选项/知识点数的百分位秩加权',
            'heuristic_subjective_v1': '主观题 按题型固有复杂度基准 + 题干长度微调',
            'heuristic_subjective_unlabeled_v1': '题型未识别的主观题 按中等估值',
        },
        'note': '全部为分层启发式估算，非 IRT 校准；无作答数据。下游应以 tags.difficulty.method/calibration 区分估算与真实校准。',
    }
    if not dry:
        (OUT / 'review').mkdir(exist_ok=True)
        (OUT / 'review' / 'difficulty_calibration_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n(dry-run=%s, 写回文件数=%d)' % (dry, written))


if __name__ == '__main__':
    main()
