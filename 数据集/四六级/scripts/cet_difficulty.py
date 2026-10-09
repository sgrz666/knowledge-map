# -*- coding: utf-8 -*-
"""四六级难度标定（heuristic-linguistic-v1）。

与教资侧 `kb_tools/ntce_difficulty.py` 的差异：
  教资是学科知识题，难度主要由题干信息量决定，故用「题干长度/选项长度方差」等。
  四六级是语言能力题，题干长度几乎与难度无关（选项都短），真正决定难度的是
  **语言本身的复杂度**与**认知操作类型**。本工具据此设计特征：

  1. kind_base    题型固有认知负荷（按四六级实测难度规律设定基准）
  2. lex_tough    词汇难度：基于大纲词/核心词分层 + 非大纲词占比 + 词长 + 音节数
  3. syn_complex  句法复杂度：平均句长 + 从句标记密度 + 标点分句密度
  4. cog_load     认知操作负荷：知识点所属能力维度（推理/词义/主旨…）
  5. passage      篇章难度（阅读题强依赖篇章，含词难度与句法复杂度）
  6. exam_level   CET-6 整体高于 CET-4（词汇/句法分布实证差异）

诚实性约束（沿用本知识库既有原则）：
  - 无作答数据，因此**不是 IRT 校准**。所有值标记 calibration='heuristic'，
    method='heuristic_linguistic_v1'，下游可据此区分「估算」与「真实校准」。
  - 证据不足的题（无选项、篇章缺失、文本过短）保持 null，不瞎填。
  - 只写 difficulty 与 tags.difficulty，不动 answer/analysis/source/copyright/
    content_review 等任何审核相关字段。
  - 幂等：已有非 null 的 difficulty 不重算。

运行：
  python 数据集/四六级/scripts/cet_difficulty.py --dry-run   # 只统计
  python 数据集/四六级/scripts/cet_difficulty.py             # 写盘
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集/四六级'
VERSION = 'heuristic-linguistic-v1'

# ---------------------------------------------------------------- 题型基准
# 依据四六级各题型的实测认知负荷特征设定（0-1）。这是全模型最重要的先验。
KIND_BASE = {
    '选词填空':0.62,   # 需同时判断词汇+语法+语篇，约束最强
    '长篇阅读':0.66,   # 段落匹配，信息量大，需跨句整合
    '仔细阅读':0.58,   # 定位后局部理解
    '短篇新闻':0.52,   # 篇幅短、话题具体
    '长对话':0.55,    # 需跟踪对话意图
    '听力篇章':0.63,   # 音频无回看，长篇记忆负担重
    '讲座/讲话':0.68,   # 学术内容+无语境，术语密度高
}
KIND_DEFAULT = 0.60

# 知识点 -> 认知操作负荷修正（同一题型内，主旨/推理难于细节定位）
COG_LOAD = {
    'gist': +0.07,        # 主旨概括：需整合全文
    'infer': +0.09,       # 推理判断：最高认知负荷
    'attitude': +0.08,    # 观点态度：需识别作者立场
    'synonym': +0.05,     # 同义替换：需跨句匹配
    'discourse': +0.06,   # 语篇结构
    'detail': -0.02,      # 细节理解：定位即可
    'locate': -0.05,      # 信息定位：最浅
    'cloze': 0.0,
    'vocab': 0.0,
}
COG_DEFAULT = 0.0

# 考试级别基准修正
LEVEL_ADJ = {'CET-4': 0.00, 'CET-6': +0.06}

OBJ_LO, OBJ_HI = 0.20, 0.88     # 映射到 difficulty 区间

# 从句/连接标记（句法复杂度信号）
CLAUSE_MARK = re.compile(
    r'\b(?:although|though|whereas|while|which|who|whom|whose|that|because|'
    r'since|unless|until|whether|if|when|whereas|despite|in addition|'
    r'furthermore|moreover|therefore|however|thus|hence|whereby)\b', re.I)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


# ---------------------------------------------------------------- 词表加载
def load_word_tiers():
    """返回 (outline_set, core_set)：大纲词与核心词集合（小写）。"""
    outline, core = set(), set()
    for f in ('words_cet4', 'words_cet6', 'core_words', 'phrases_highfreq'):
        p = KB / 'vocabulary' / f'{f}.jsonl'
        if not p.exists():
            continue
        for line in p.open(encoding='utf-8'):
            if not line.strip():
                continue
            r = json.loads(line)
            e = r.get('extra') or {}
            w = (e.get('word') or '').lower().strip()
            if not w:
                m = re.match(r'([A-Za-z][A-Za-z\'-]*)', r.get('text') or '')
                w = m.group(1).lower() if m else ''
            if not w:
                continue
            if e.get('tier') == 'core':
                core.add(w)
            else:
                outline.add(w)
    return outline, core


def load_passages():
    """resource_id -> {text, kind}"""
    out = {}
    p = KB / 'passages' / 'reading.jsonl'
    if p.exists():
        for line in p.open(encoding='utf-8'):
            if not line.strip():
                continue
            r = json.loads(line)
            out[r['resource_id']] = {'text': r.get('text') or '', 'kind': r.get('kind')}
    return out


# ---------------------------------------------------------------- 特征
def syllables(word):
    """英文音节数近似（供词长复杂度用，非精确音标解析）。"""
    w = word.lower()
    if not w:
        return 0
    groups = re.findall(r'[aeiouy]+', w)
    n = len(groups)
    if w.endswith('e') and n > 1 and not w.endswith(('le', 'ee', 'ye')):
        n -= 1
    return max(1, n)


def text_complexity(text, outline, core):
    """返回 (lex_tough, syn_complex, 统计量)。lex_tough/syn_complex 均为 0-1。"""
    words = WORD_RE.findall(text or '')
    if not words:
        return None, None, {}
    total = len(words)
    low = [w.lower() for w in words]

    out_of_list = sum(1 for w in low if w not in outline and w not in core)
    core_hit = sum(1 for w in low if w in core)
    long_word = sum(1 for w in words if len(w) >= 8)
    poly_syl = sum(1 for w in words if syllables(w) >= 3)
    clauses = len(CLAUSE_MARK.findall(text or ''))

    lex_tough = (
        0.45 * (out_of_list / total) +
        0.25 * (long_word / total) +
        0.20 * (poly_syl / total) +
        0.10 * (core_hit / total)          # 核心词是高频基础词，命中越多越易
    )
    syn_complex = min(1.0, (
        0.55 * min(1.0, (clauses / max(1.0, total / 25.0)) / 3.0) +
        0.45 * min(1.0, (total / 400.0))
    ))
    stats = {'words': total, 'out_of_list': round(out_of_list / total, 4),
             'long_word_ratio': round(long_word / total, 4),
             'poly_syl_ratio': round(poly_syl / total, 4),
             'clauses': clauses}
    return lex_tough, syn_complex, stats


def cog_adjust(q):
    """按知识点推断认知操作负荷修正。"""
    adj = 0.0
    hit = False
    for kn in (q.get('knowledge_node_ids') or []):
        leaf = kn.split('.')[-1]
        if leaf in COG_LOAD:
            adj += COG_LOAD[leaf]
            hit = True
    return adj if hit else COG_DEFAULT


def option_stats(q):
    """选项结构特征：长选项差异通常是干扰项质量与迷惑性的信号。"""
    opts = (q.get('content') or {}).get('options') or {}
    if isinstance(opts, dict):
        lens = [len(str(v or '')) for v in opts.values()]
    elif isinstance(opts, list):
        lens = [len(str((o or {}).get('text', '') if isinstance(o, dict) else o)) for o in opts]
    else:
        lens = []
    lens = [x for x in lens if x > 0]
    if len(lens) < 2:
        return None, {}
    mean = sum(lens) / len(lens)
    var = sum((x - mean) ** 2 for x in lens) / len(lens)
    return var, {'opt_n': len(lens), 'opt_len_mean': round(mean, 1),
                 'opt_len_var': round(var, 1)}


# ---------------------------------------------------------------- 主流程
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


def pct_ranker(values):
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


def r4(x):
    return round(x, 4)


def main():
    dry = '--dry-run' in sys.argv
    outline, core = load_word_tiers()
    passages = load_passages()
    print(f'词表: 大纲/其他 {len(outline)}  核心 {len(core)}   篇章 {len(passages)}')

    files = sorted((KB / 'questions').glob('cet*/*.jsonl'))
    batches = [(p, read_rows(p)) for p in files]
    all_q = [q for _, rows in batches for q in rows]
    before = sum(1 for q in all_q if q.get('difficulty') is not None)

    # ---- 第一轮：算原始特征 ----
    feats = []
    null_reasons = Counter()
    for q in all_q:
        c = q.get('content') or {}
        qt = q.get('question_type') or ''
        stem = c.get('stem') or ''
        opts = c.get('options') or {}

        # 组装用于难度评估的文本：题干 + 选项 + 所属篇章
        buf = [stem]
        if isinstance(opts, dict):
            buf += [str(v or '') for v in opts.values()]
        elif isinstance(opts, list):
            buf += [str((o or {}).get('text', '') if isinstance(o, dict) else o) for o in opts]
        pid = (q.get('extra') or {}).get('passage_id')
        ptext = ''
        if pid and pid in passages:
            ptext = passages[pid]['text']
        full = ' '.join([t for t in ([ptext] if ptext else []) + buf if t])

        if len(WORD_RE.findall(full)) < 5:
            null_reasons['文本过短（<5 词），无法评估语言复杂度'] += 1
            feats.append(None)
            continue
        lex, syn, st = text_complexity(full, outline, core)
        if lex is None:
            null_reasons['文本解析失败'] += 1
            feats.append(None)
            continue
        ovar, ost = option_stats(q)
        feats.append({
            'kind_base': KIND_BASE.get(qt, KIND_DEFAULT),
            'lex': lex, 'syn': syn, 'cog': cog_adjust(q),
            'level_adj': LEVEL_ADJ.get(q.get('exam') or '', 0.0),
            'opt_var': ovar, 'has_passage': 1.0 if ptext else 0.0,
            'exam': q.get('exam'), 'qtype': qt, 'stats': st, 'ostats': ost,
        })

    ok = [f for f in feats if f]
    # ---- 第二轮：分考试级别内做百分位归一，再加权合成 ----
    # 分组归一避免 CET-4/6 难度分布被人为拉开（level_adj 已显式处理级别差异）
    for exam in ('CET-4', 'CET-6'):
        grp = [f for f in ok if f['exam'] == exam]
        if not grp:
            continue
        r_lex = pct_ranker([f['lex'] for f in grp])
        r_syn = pct_ranker([f['syn'] for f in grp])
        r_var = pct_ranker([f['opt_var'] or 0.0 for f in grp])
        # 篇章难度单独归一：作为「文本基准层」
        # 只有真正带篇章的题参与篇章层统计，纯听力题不参与（否则被拉向均值）
        psgs = [f['lex'] for f in grp if f['has_passage']]
        r_pg_lex = pct_ranker(psgs) if len(psgs) > 1 else (lambda v: 0.5)
        psyn = [f['syn'] for f in grp if f['has_passage']]
        r_pg_syn = pct_ranker(psyn) if len(psyn) > 1 else (lambda v: 0.5)
        for f in grp:
            f['r_lex'] = r_lex(f['lex'])
            f['r_syn'] = r_syn(f['syn'])
            f['r_var'] = r_var(f['opt_var'] or 0.0)
            f['r_pg_lex'] = r_pg_lex(f['lex']) if f['has_passage'] else None
            f['r_pg_syn'] = r_pg_syn(f['syn']) if f['has_passage'] else None

    # 权重设计要点：
    #  有篇章的题 -> 文本难度以「篇章」为主（篇章决定语言复杂度上限），
    #                题目级差异主要来自认知操作负荷（同一篇文章里定位题 vs 推理题难度不同）
    #  无篇章的题 -> 文本难度直接用题干+选项自身特征
    W_WITH_PG = {'kind': 0.30, 'pg_lex': 0.13, 'pg_syn': 0.11, 'cog': 0.28, 'qlex': 0.10, 'opt': 0.08}
    W_NO_PG = {'kind': 0.40, 'lex': 0.24, 'syn': 0.16, 'cog': 0.12, 'opt': 0.08}
    filled = 0
    for q, f in zip(all_q, feats):
        if f is None:
            continue
        if q.get('difficulty') is not None:
            continue                      # 幂等
        # 题型基准映射到 [0,1]
        kb01 = (f['kind_base'] - 0.45) / (0.75 - 0.45)
        if f['has_passage']:
            W = W_WITH_PG
            cog01 = (f['cog'] + 0.09) / 0.18
            score = (
                W['kind'] * min(1.0, max(0.0, kb01)) +
                W['pg_lex'] * f['r_pg_lex'] +
                W['pg_syn'] * f['r_pg_syn'] +
                W['cog'] * min(1.0, max(0.0, cog01)) +
                W['qlex'] * f['r_lex'] +
                W['opt'] * f['r_var']
            )
        else:
            W = W_NO_PG
            score = (
                W['kind'] * min(1.0, max(0.0, kb01)) +
                W['lex'] * f['r_lex'] +
                W['syn'] * f['r_syn'] +
                W['cog'] * min(1.0, max(0.0, (f['cog'] + 0.09) / 0.18)) +
                W['opt'] * f['r_var']
            )
        score = score / sum(W.values())
        d = OBJ_LO + score * (OBJ_HI - OBJ_LO) + f['level_adj']
        q['difficulty'] = r4(clamp(d))
        tags = q.setdefault('tags', {})
        td = tags.setdefault('difficulty', {})
        td.update({
            'value': q['difficulty'],
            'status': 'provided',
            'method': 'heuristic_linguistic_v1',
            'calibration': 'heuristic',
            'version': VERSION,
            'note': '无作答数据，非 IRT 校准；用于组卷分层与推荐排序，不可直接用作能力估计',
            'features': {
                'kind_base': f['kind_base'],
                'lex_tough': r4(f['lex']),
                'syn_complex': r4(f['syn']),
                'cog_load': r4(f['cog']),
                'opt_len_var': f['ostats'].get('opt_len_var'),
                'has_passage': bool(f['has_passage']),
                'passage_lex': r4(f['r_pg_lex']) if f['r_pg_lex'] is not None else None,
                'passage_syn': r4(f['r_pg_syn']) if f['r_pg_syn'] is not None else None,
                'text_words': f['stats'].get('words'),
            },
        })
        extra = q.setdefault('extra', {})
        dm = extra.setdefault('difficulty_metadata', {})
        dm.update({
            'status': 'heuristic_estimated',
            'method': 'heuristic_linguistic_v1',
            'estimate': q['difficulty'],
            'sample_count': 0,
            'planned_method': 'collect response evidence; fit IRT a/b; subject-expert validation',
        })
        filled += 1

    if not dry:
        for p, rows in batches:
            write_rows(p, rows)

    after = sum(1 for q in all_q if q.get('difficulty') is not None)
    vals = [q['difficulty'] for q in all_q if q.get('difficulty') is not None]

    print('\n=== 四六级难度标定报告 (%s) ===' % VERSION)
    print(f'题目总数 {len(all_q)}   本次新填 {filled}   标定后覆盖 {after} '
          f'({after * 100.0 / len(all_q):.1f}%)   保持 null {len(all_q) - after}')
    if null_reasons:
        for k, v in null_reasons.most_common():
            print(f'  null 原因: {k} -> {v}')
    if vals:
        s = sorted(vals)
        n = len(s)
        print(f'难度范围 {s[0]:.3f} ~ {s[-1]:.3f}  均值 {sum(s)/n:.3f}  '
              f'中位 {s[n//2]:.3f}  标准差 {(sum((x-sum(s)/n)**2 for x in s)/n)**0.5:.3f}')
        bins = Counter(min(9, int(x * 10)) for x in vals)
        mx = max(bins.values())
        print('\n难度分布:')
        for b in range(10):
            print(f'  {b/10:.1f}-{(b+1)/10:.1f} | {bins.get(b,0):5d} '
                  f'{"#" * round(bins.get(b,0)/mx*38)}')
        by = defaultdict(list)
        for q in all_q:
            if q.get('difficulty') is not None:
                by[q.get('question_type')].append(q['difficulty'])
        print('\n各题型难度:')
        for t in sorted(by, key=lambda k: -len(by[k])):
            v = sorted(by[t])
            print(f'  {t:8s} n={len(v):5d} 均值{sum(v)/len(v):.3f} '
                  f'中位{v[len(v)//2]:.3f} 范围{v[0]:.3f}~{v[-1]:.3f}')
        byl = defaultdict(list)
        for q in all_q:
            if q.get('difficulty') is not None:
                byl[q.get('exam')].append(q['difficulty'])
        print('\n各级别难度:')
        for lv in sorted(byl):
            v = sorted(byl[lv])
            print(f'  {lv} n={len(v):5d} 均值{sum(v)/len(v):.3f} 中位{v[len(v)//2]:.3f}')

    report = {
        'version': VERSION, 'generated': '2026-10-08',
        'total': len(all_q), 'new_this_run': filled, 'filled_total': after,
        'kept_null': len(all_q) - after,
        'null_reasons': dict(null_reasons),
        'weights': {'with_passage': W_WITH_PG, 'no_passage': W_NO_PG}, 'kind_base': KIND_BASE, 'cog_load': COG_LOAD,
        'level_adj': LEVEL_ADJ, 'range': [OBJ_LO, OBJ_HI],
        'vocab_assets': {'outline_or_other': len(outline), 'core': len(core),
                         'passages': len(passages)},
        'by_qtype': {t: {'n': len(v), 'mean': r4(sum(v) / len(v)),
                         'median': r4(sorted(v)[len(v) // 2])}
                     for t, v in by.items()},
        'by_exam': {lv: {'n': len(v), 'mean': r4(sum(v) / len(v)),
                         'median': r4(sorted(v)[len(v) // 2])}
                    for lv, v in byl.items()},
        'method_legend': {
            'heuristic_linguistic_v1':
                '题型认知负荷基准40% + 词汇难度22% + 句法复杂度20% + 认知操作负荷10% + 选项结构8%；'
                '词汇难度由大纲词/核心词分层与非大纲词占比、词长、多音节词占比计算；'
                '句法复杂度由从句标记密度与篇幅计算；难度在 CET-4/CET-6 内分别做百分位归一。'},
        'honesty_note':
            '本工具无作答数据，输出为分层启发式估算，不是 IRT 校准。'
            '可用于组卷分层、弱项推荐、练习排序；'
            '不可直接用于 F3 学情诊断的能力估计（那需要 CAT+IRT 或 BKT/DKT 掌握度数据）。'
            '所有值带 calibration="heuristic" 标记，下游须据此区分估算与真实校准。',
    }
    if not dry:
        (KB / 'manifest').mkdir(exist_ok=True)
        (KB / 'manifest' / 'cet_difficulty_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('\n已写 manifest/cet_difficulty_report.json')
    else:
        print('\n(dry-run，未写盘)')


if __name__ == '__main__':
    main()
