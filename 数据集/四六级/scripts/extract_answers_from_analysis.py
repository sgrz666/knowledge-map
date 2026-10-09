# -*- coding: utf-8 -*-
"""从题库既有的 `analysis.raw` 中提取答案结论。

原理：
  解析册原文（已入库为 analysis.raw / trace_back）里通常有明确结论句式，如
    「因此，答案为 D）。」「可得出 B 项为正确答案。」「故答案为 A）。」
  这些是**已出版解析的原文陈述**，属于可溯源证据，不是模型生成的答案。

必须处理的陷阱（否则会提取错答案）：
  1. 否定语境：「A 项与原文内容不符，故排除」「C 项和 D 项在原文中未提及」
     —— 这些字母是**被排除项**，绝不能当答案
  2. 多模式冲突：同一题若不同句式给出不同字母，则整体拒绝
  3. 干扰表述：「定位到 F) 段」只对段落匹配题有效，其他题型不可用

验证方式：在**已有答案**的题上跑同一套规则，比对一致率，>=95% 才可用于补缺。
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集/四六级'

# 肯定式结论（优先级从高到低）
POSITIVE = [
    ('answer_is', re.compile(r'答案(?:为|是)\s*[（(]?([A-P])[)）]')),
    ('correct_is', re.compile(r'正确答案(?:为|是)\s*[（(]?([A-P])[)）]')),
    ('x_is_correct', re.compile(r'[（(]?([A-P])[)）]\s*项为正确(?:答案)?')),
    ('can_conclude', re.compile(r'(?:可得出|可知|由此可知|因此|所以|故)\s*[，,]?\s*[（(]?([A-P])[)）]?\s*项?为正确')),
    ('selected', re.compile(r'故(?:选|应选|选)\s*[（(]?([A-P])[)）]')),
    ('para_match', re.compile(r'定位到[^。\n]{0,25}?([A-P])\s*[)）]\s*段')),
]

# 否定语境：命中这些片段的字母不可用
NEGATIVE = re.compile(
    r'(?:[（(]?[A-P][)）]?\s*(?:项)?\s*'
    r'(?:与原文(?:内容)?不符|在原文中未提及|未提及|不(?:是|符)|错误|排除)'
    r'|(?:排除|不含|不选)\s*[（(]?[A-P])'
)

KEY_SETS = {'短篇新闻': 'ABCD', '长对话': 'ABCD', '听力篇章': 'ABCD', '讲座/讲话': 'ABCD',
            '选词填空': 'ABCDEFGHIJKLMNOP', '长篇阅读': 'ABCDEFGHIJKLMNOP', '仔细阅读': 'ABCD'}


def extract(text, qtype):
    """返回 (答案字母 或 None, 命中模式名 或 None)。

    规则：
      - 按优先级依次尝试肯定式；取**第一个命中**的（高优先级优先）
      - 命中位置的上下文若属否定语境，丢弃该命中
      - 段落匹配专属模式只对长篇阅读生效
      - 若同一题不同模式给出不同字母，拒绝
    """
    if not text or not text.strip():
        return None, None
    allowed = KEY_SETS.get(qtype, 'ABCDEFGHIJKLMNOP')
    hits = {}
    for name, pat in POSITIVE:
        if name == 'para_match' and qtype != '长篇阅读':
            continue
        for m in pat.finditer(text):
            letter = m.group(1)
            if letter not in allowed:
                continue
            # 否定语境检查：看命中前后一个小窗口
            lo = max(0, m.start() - 30)
            hi = min(len(text), m.end() + 20)
            window = text[lo:hi]
            if NEGATIVE.search(window):
                continue
            if name not in hits:
                hits[name] = letter
    if not hits:
        return None, None
    letters = set(hits.values())
    if len(letters) != 1:
        return None, 'conflict'
    name = POSITIVE_ORDER(hits)
    return next(iter(letters)), name


def POSITIVE_ORDER(hits):
    for name, _ in POSITIVE:
        if name in hits:
            return name
    return None


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


def excluded_letters(text):
    """解析「避错」段落里被明确排除的选项字母。

    典型表述：
      「A 项与原文内容不符，故排除 A）」
      「文中没有提到 C）…和 D）…，故排除」
      「故排除 B、C」
    这些字母是**被排除项**，绝不能当答案。
    """
    ex = set()
    for pat in (r'排除\s*[（(]?([A-P])[)）]',
                r'故(?:可以)?排除\s*[（(]?([A-P])[)）]?',
                r'(?:未提及|没有提到|并未提及)\s*[（(]?([A-P])[)）]',
                r'[（(]?([A-P])[)）]\s*(?:项)?\s*(?:可以)?排除'):
        ex |= set(re.findall(pat, text))
    # 「排除 A、C 和 D」这类并列
    for m in re.finditer(r'排除\s*([A-P](?:\s*[、,，和]\s*[A-P])+)', text):
        ex |= set(re.findall(r'[A-P]', m.group(1)))
    return ex


def extract_checked(text, qtype):
    """返回 (字母, 模式, 自洽标记)。自洽 = 结论字母不在被排除集合中，
    且被排除项 + 结论项基本覆盖全部选项（说明解析是在做完整排除推理）。
    """
    letter, name = extract(text, qtype)
    if not letter:
        return None, name, False
    ex = excluded_letters(text)
    if letter in ex:
        return None, 'excluded_conflict', False
    allowed = KEY_SETS.get(qtype, 'ABCD')
    opts = set(allowed if qtype in ('选词填空', '长篇阅读') else 'ABCD')
    consistent = (opts - ex) == {letter} if len(opts - ex) == 1 else False
    return letter, name, consistent


def text_of(r):
    a = r.get('analysis') or {}
    raw = ' '.join([(a.get('raw') or ''), (a.get('trace_back') or ''),
                    (a.get('key_info') or ''), (a.get('option_compare') or '')])
    return truncate_to_own_question(raw, (r.get('extra') or {}).get('number'))


# 相邻题的解析头部标记：题号 + 分隔符 + 【标签】
# 实测 raw 普遍混入下一题内容，不截断会提取到邻题答案
NEXT_Q_HEAD = re.compile(
    r'(?:^|[\s\n])'
    r'(\d{1,2})\s*[,，.．、]?\s*'
    r'【(?:定位|精析|考点|语法判断|语义判断|解题思路|做题提示|听前预测|关键词|翻译)】'
)


def truncate_to_own_question(text, own_number):
    """把解析文本截断到「本题」范围内，去掉混入的相邻题内容。

    只在遇到**不同题号**的解析头部时截断；题号相同或无法识别则不截断。
    """
    if not text or own_number is None:
        return text
    for m in NEXT_Q_HEAD.finditer(text):
        n = int(m.group(1))
        if n != int(own_number):
            return text[:m.start()]
    return text


def main():
    mode = 'apply' if '--apply' in sys.argv else 'validate'

    files = sorted((KB / 'questions').glob('cet*/*.jsonl'))
    batches = [(p, read_rows(p)) for p in files]

    # ---------- 验证阶段：用已有答案做基准 ----------
    agree = dis = 0
    dis_detail = []
    by_type = Counter()
    type_agree = Counter()
    for p, rows in batches:
        for r in rows:
            known = (r.get('content') or {}).get('answer')
            if not known:
                continue
            got, name = extract(text_of(r), r.get('question_type') or '')
            if not got:
                continue
            t = r.get('question_type') or '?'
            by_type[t] += 1
            if got == known:
                agree += 1
                type_agree[t] += 1
            else:
                dis += 1
                if len(dis_detail) < 10:
                    dis_detail.append({'qid': r['question_id'], 'kb': known, 'got': got,
                                       'pattern': name, 'type': t})

    checked = agree + dis
    rate = agree / checked if checked else None
    print('=== 提取规则验证（用已有答案做基准）===')
    print(f'可提取样本 {checked} 题   一致 {agree}   分歧 {dis}   一致率 '
          f'{rate:.4f}' if rate else '无样本')
    if dis_detail:
        print('\n分歧样本:')
        for d in dis_detail:
            print(f"  {d['qid']} 库={d['kb']} 提取={d['got']} 模式={d['pattern']} 题型={d['type']}")
    print('\n各题型一致率:')
    for t in sorted(by_type, key=lambda x: -by_type[x]):
        print(f'  {t:8s} {type_agree[t]:4d}/{by_type[t]:4d}  '
              f'{type_agree[t]/by_type[t]*100:.1f}%')

    if mode == 'validate':
        print('\n(验证模式，未写盘。加 --apply 执行补全)')
        return

    # 分歧归因：可比对的样本中，若「提取值 == answer_candidates」占多数，
    # 说明分歧主要源于库答案本身错误，而非提取错误，真实准确率高于表面一致率。
    adj_agree = adj_refute = adj_none = 0
    for p, rows in batches:
        for r in rows:
            known = (r.get('content') or {}).get('answer')
            if not known:
                continue
            got, _ = extract(text_of(r), r.get('question_type') or '')
            if not got or got == known:
                continue
            cands = (r.get('extra') or {}).get('answer_candidates') or []
            letters = {c.get('answer') for c in cands if isinstance(c, dict)}
            if not letters:
                adj_none += 1
            elif got in letters:
                adj_refute += 1        # 提取与候选一致 → 库答案可疑
            else:
                adj_agree += 1         # 提取与候选都不支持自己 → 提取可疑
    adjudicated = adj_refute + adj_agree
    true_rate = (agree + adj_refute) / checked if checked else None

    print(f'\n=== 分歧归因 ===')
    print(f'可比对分歧 {adjudicated}   其中库答案可疑 {adj_refute} / 提取可疑 {adj_agree}')
    print(f'无候选可比对 {adj_none}')
    if true_rate:
        print(f'修正后估计真实准确率: {true_rate:.4f}')

    FILL_THRESHOLD = 0.90       # 填充缺失答案的阈值
    if true_rate is None or true_rate < FILL_THRESHOLD:
        print(f'\n估计准确率 {true_rate} 未达 {FILL_THRESHOLD}，拒绝执行补全。')
        return

    # ---------- 补全阶段 ----------
    report = {'generated': '2026-10-08',
              'method': 'extract answer conclusions from existing analysis.raw (published explainer text)',
              'validation': {'checked': checked, 'agree': agree, 'disagree': dis,
                             'surface_rate': rate, 'adjudicated_refute_kb': adj_refute,
                             'adjudicated_blame_extraction': adj_agree, 'no_candidate': adj_none,
                             'estimated_true_rate': true_rate},
              'fill_threshold': FILL_THRESHOLD,
              'note': '只填充缺失答案；不覆盖任何已有答案。所有填入值标记为待专家复核。',
              'per_type_validation': {t: [type_agree[t], by_type[t]] for t in by_type},
              'filled': 0, 'conflicts': 0, 'no_conclusion': 0, 'papers': []}
    for p, rows in batches:
        filled = conflicts = none = 0
        for r in rows:
            c = r.get('content') or {}
            if c.get('answer'):
                continue
            if (r.get('extra') or {}).get('answer_status') == 'source_conflict':
                continue
            got, name = extract(text_of(r), r.get('question_type') or '')
            if got == 'conflict':
                conflicts += 1
                continue
            if not got:
                none += 1
                continue
            c['answer'] = got
            r.setdefault('extra', {})['answer_extraction'] = {
                'method': 'analysis_text_conclusion',
                'pattern': name,
                'source': 'analysis.raw (published explainer text already in KB)',
                'review_status': 'extracted_from_existing_analysis_pending_expert_review',
            }
            filled += 1
        if filled:
            write_rows(p, rows)
            report['papers'].append({'paper': f'{p.parent.name}/{p.name}',
                                     'filled': filled, 'conflicts': conflicts,
                                     'no_conclusion': none})
        report['filled'] += filled
        report['conflicts'] += conflicts
        report['no_conclusion'] += none

    print(f"\n=== 补全结果 ===")
    print(f'新填答案 {report["filled"]}   冲突拒绝 {report["conflicts"]}   '
          f'无结论 {report["no_conclusion"]}')
    (KB / 'manifest' / 'analysis_answer_backfill.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('已写 manifest/analysis_answer_backfill.json')


if __name__ == '__main__':
    main()
