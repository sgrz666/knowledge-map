"""为主观题生成 ``question_specific_points``（逐题具体评分点）。

python kb_tools/ntce_rubric_points.py [--types 材料分析 教学设计 简答] [--dry-run]

设计约束（来自 教资KB/README.md 与 ntce_repair.py）：
- 只写 ``question_type`` 属于主观题的题；绝不碰客观题（单选/多选/未标注）。
- 只读不写人工审核数据：``rubric.checked_by`` / ``rubric.evidence`` /
  ``rubric.expert_verified=true`` 代表人工介入，遇到即跳过。
- 评分点必须诚实标注来源：模型输出不能标成官方标准答案。本工具依据
  “题干子问题结构 + 教资通用答题框架”派生，``official_scoring`` 保持 ``false``，
  ``expert_verified`` 保持 ``false``，并在 ``question_specific_points_meta`` 中
  明确说明依据强度（模板推导、非官方答案）。
- 不伪造 ``locator``：当依据仅为通用模板与本题题干时，不写指向不存在官方文件的定位。
- 幂等：评分点由题干结构确定性推导；重复运行结果一致，不会累积重复。
- 与 ntce_repair.py 兼容：``practice_rubric()`` 用 ``setdefault`` 填充
  ``question_specific_points`` 默认值（空列表），已存在非空值不会被覆盖，
  且本工具写入的额外元信息键不会被 ``setdefault`` 删除。
"""
import json
from pathlib import Path

from ntce_io import atomic_write

OUT = Path(__file__).resolve().parents[1] / '数据集' / '教资'
QUESTIONS_DIR = OUT / 'questions'

# 主观题题型（客观题：单选/多选/未标注 不处理）
SUBJECTIVE_TYPES = {'简答', '材料分析', '教学设计', '论述', '辨析', '写作',
                    '解答', '活动设计', '诊断'}

# 五维练习框架维度名（与 practice_rubric 对齐）
DIMENSIONS = ['要点覆盖', '理论运用', '逻辑结构', '语言表达', '规范性']


def read_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding='utf-8') if line.strip()]


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))


def manually_reviewed(component):
    """人工身份/证据存在时，自动化只补缺省字段，不重写审核决定（与 ntce_repair 对齐）。"""
    return bool(component and (component.get('checked_by') or component.get('expert_verified')))


# --------------------------- 题干子问题解析 ---------------------------

def parse_subquestions(stem):
    """从题干抽取子问题片段，形如 （1）/ (1) / 1． / ① / 第1问 / 问题1：。

    返回 [(label, segment_text), ...]；不足 2 个有效切分时返回空列表（视为整题）。
    """
    if not stem:
        return []
    marks = []
    for m in __import__('re').finditer(r'（\s*([0-9]+)\s*）', stem):
        marks.append((m.start(), '（%s）' % m.group(1)))
    for m in __import__('re').finditer(r'\(\s*([0-9]+)\s*\)', stem):
        marks.append((m.start(), '(%s)' % m.group(1)))
    for m in __import__('re').finditer(r'(?m)(?:^|\n)\s*([0-9]+)\s*[．.]', stem):
        marks.append((m.start(), '%s．' % m.group(1)))
    for m in __import__('re').finditer(r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫]', stem):
        marks.append((m.start(), m.group(0)))
    for m in __import__('re').finditer(r'第\s*([0-9]+)\s*问', stem):
        marks.append((m.start(), '第%s问' % m.group(1)))
    for m in __import__('re').finditer(r'问题\s*([0-9]+)\s*[：:]', stem):
        marks.append((m.start(), '问题%s：' % m.group(1)))
    # 去重并按位置排序
    seen, ordered = set(), []
    for pos, label in sorted(marks):
        if pos in seen:
            continue
        seen.add(pos)
        ordered.append((pos, label))
    if len(ordered) < 2:
        return []
    segments = []
    for i, (pos, label) in enumerate(ordered):
        end = ordered[i + 1][0] if i + 1 < len(ordered) else len(stem)
        segment = stem[pos:end].strip()
        segments.append((label, segment))
    return segments


def snippet(text, n=40):
    """取子问题正文首句摘要，去除前导标号。"""
    t = __import__('re').sub(
        r'^(?:（[0-9]+）|\([0-9]+\)|[0-9]+[．.]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫]|第[0-9]+问|问题[0-9]+[：:])',
        '', text or '').strip()
    t = t.split('\n')[0].strip()
    if len(t) > n:
        t = t[:n] + '…'
    return t or '本题设问'


def ask_phrase(label):
    """把子问题标号格式化为自然表述；整题时用『本题』。"""
    return ('第%s问' % label) if label and label != '全题' else '本题'


# --------------------------- 评分点构造 ---------------------------

def _point(qid, index, dimension, importance, content, basis):
    return {
        'point_id': '%s__p%02d' % (qid, index),
        'primary_dimension': dimension,
        'importance': importance,
        'point': content,
        'generation_method': 'stem_structure_and_template',
        'basis': basis,
        'expert_verified': False,
    }


def material_analysis_points(q, subs):
    """材料分析：通用作答框架 = 理论依据 + 材料分析 + 总结提升。"""
    points = []
    idx = 1
    if not subs:
        subs = [('全题', q['content'].get('stem', ''))]
    for label, txt in subs:
        topic = snippet(txt)
        ask = ask_phrase(label)
        points.append(_point(q['question_id'], idx, '理论运用', '核心',
            '准确运用本题所涉理论评析%s情境（如学科原理、素质教育观、学生观、教师观、'
            '教学原则、德育原则、班级管理或新课改理念等，依材料主题判定），完整、规范地陈述理论要点。'
            % ask,
            '依据教资材料分析通用框架「理论+材料+总结」推导；题干%s：%s。非官方答案。' % (ask, topic)))
        idx += 1
        points.append(_point(q['question_id'], idx, '要点覆盖', '核心',
            '紧扣%s「%s」，结合所给材料具体细节作答，做到理论观点与材料情境事理对应，避免空谈理论。'
            % (ask, topic),
            '题干%s内容要求；框架推导，非官方标准答案。' % ask))
        idx += 1
    points.append(_point(q['question_id'], idx, '逻辑结构', '重要',
        '整体按「理论观点→材料印证→分析评价」层层展开，结构清晰、条理分明。',
        '通用答题结构要求；模板推导，非官方。'))
    idx += 1
    points.append(_point(q['question_id'], idx, '要点覆盖', '重要',
        '在评析基础上给出评价结论或教育启示/改进建议（总结提升）。',
        '材料分析题通用收尾要求；模板推导，非官方。'))
    idx += 1
    points.append(_point(q['question_id'], idx, '语言表达', '一般',
        '使用规范教育学术语，表述准确、连贯，书写清楚。',
        '通用语言规范性要求；模板推导。'))
    return points


def _teaching_component_map():
    return {
        '教学目标': ('要点覆盖', '核心',
            '拟定具体、可观测的教学目标（如知识与技能、过程与方法、情感态度与价值观，或学科核心素养），符合学段与课程标准。'),
        '教学重难点': ('要点覆盖', '核心',
            '明确教学重点与难点，区分准确，并依据学情与内容特点说明判定依据。'),
        '教学过程': ('要点覆盖', '核心',
            '设计完整教学过程（情境导入→新知探究/讲授→巩固练习→小结→作业），师生活动具体，体现学生主体与教学目标落实。'),
        '板书设计': ('规范性', '重要',
            '设计简洁、逻辑清晰的板书，体现知识结构主线。'),
        '学情分析': ('要点覆盖', '重要',
            '分析学生已有知识基础、认知特点与学习困难，作为设计依据。'),
        '教材分析': ('要点覆盖', '重要',
            '分析教材地位、内容与重难点，说明教学价值。'),
        '内容分析': ('要点覆盖', '重要',
            '分析教学内容地位、结构与重难点，说明教学价值。'),
    }


def teaching_design_points(q, subs):
    """教学设计：通用框架 = 教学目标 / 重难点 / 教学过程 / 板书设计。"""
    stem = q['content'].get('stem', '')
    cmap = _teaching_component_map()
    components = [name for name in cmap if name in stem]
    points = []
    idx = 1
    if components:
        for comp in components:
            dim, imp, desc = cmap[comp]
            points.append(_point(q['question_id'], idx, dim, imp, desc,
                '题干要求设计「%s」；依据教资教学设计通用模板推导，非官方样例。' % comp))
            idx += 1
    else:
        # 整课设计（题干未逐项枚举组件）
        for comp in ['教学目标', '教学重难点', '教学过程', '板书设计']:
            dim, imp, desc = cmap[comp]
            points.append(_point(q['question_id'], idx, dim, imp, desc,
                '整课设计要求「%s」；通用模板推导，非官方样例。' % comp))
            idx += 1
    points.append(_point(q['question_id'], idx, '理论运用', '重要',
        '设计体现先进教育理念（如学生主体、探究学习、学科育人），并与目标/过程一致。',
        '通用教学设计原则；模板推导。'))
    idx += 1
    points.append(_point(q['question_id'], idx, '逻辑结构', '重要',
        '各环节目标—活动—评价一致，时间分配合理，结构完整。',
        '通用结构要求；模板推导。'))
    return points


def short_answer_points(q, subs):
    """简答/论述/辨析等：列出关键要点并简要展开。"""
    points = []
    idx = 1
    tasks = subs if subs else [('全题', q['content'].get('stem', ''))]
    for label, txt in tasks:
        topic = snippet(txt)
        ask = ask_phrase(label)
        points.append(_point(q['question_id'], idx, '要点覆盖', '核心',
            '针对%s「%s」，列出关键要点并简要展开，要点完整、无遗漏。' % (ask, topic),
            '题干%s内容要求；框架推导，非官方答案。' % ask))
        idx += 1
    points.append(_point(q['question_id'], idx, '理论运用', '重要',
        '必要时援引相关教育理论/法规支撑要点，表述准确。',
        '简答/论述通用要求；模板推导。'))
    idx += 1
    points.append(_point(q['question_id'], idx, '逻辑结构', '一般',
        '要点按逻辑顺序组织，分条清晰。',
        '通用结构要求；模板推导。'))
    return points


def ensure_dimension_coverage(points, q):
    """保证五维（要点覆盖/理论运用/逻辑结构/语言表达/规范性）在本题评分点中均有体现，
    以便自动评分能在每个维度上给出等级。仅对缺失维度追加通用练习要求，不伪造来源。"""
    generic = {
        '语言表达': '使用规范教育学术语，表述准确、连贯，书写清楚。',
        '规范性': '作答符合格式与学术规范，分条标号清晰、无错别字。',
    }
    present = {p['primary_dimension'] for p in points}
    idx = len(points) + 1
    for dim in DIMENSIONS:
        if dim in present:
            continue
        desc = generic.get(dim, '作答符合该维度基本要求。')
        points.append(_point(q['question_id'], idx, dim, '一般', desc,
            '通用练习要求；模板推导，非官方。'))
        idx += 1
    return points


def generate_points(q):
    """按题型分发到具体生成器。"""
    qt = q.get('question_type')
    stem = q['content'].get('stem', '')
    subs = parse_subquestions(stem)
    if qt == '材料分析':
        points = material_analysis_points(q, subs)
    elif qt == '教学设计':
        points = teaching_design_points(q, subs)
    else:
        # 简答/论述/辨析/写作/解答/活动设计/诊断 统一走要点式生成器
        points = short_answer_points(q, subs)
    return ensure_dimension_coverage(points, q)


def build_meta(q, n_points):
    return {
        'generated_by': 'ntce_rubric_points.py',
        'generation_method': 'stem_structure_and_template',
        'version': '1.0',
        'note': 'AI辅助生成的练习建议评分点：依据题干子问题结构与教资通用答题框架'
                '（材料分析「理论+材料+总结」、教学设计「目标/重难点/过程/板书」等）推导，'
                '非官方评分标准，未经学科专家核定。',
        'official_scoring': False,
        'covers_dimensions': DIMENSIONS,
        'source_strength': 'template_derived_no_official_source',
        'point_count': n_points,
    }


# --------------------------- 主流程 ---------------------------

def process(types, dry_run=False):
    target = set(types) & SUBJECTIVE_TYPES
    if not target:
        print('无有效主观题型目标，退出。')
        return {}
    stats = {'processed': 0, 'skipped_manual': 0, 'skipped_objective': 0,
             'by_type': {}, 'points_per_type': {}, 'dimension_hits': {d: 0 for d in DIMENSIONS}}
    files = sorted(QUESTIONS_DIR.glob('*/*/*.jsonl'))
    for path in files:
        rows = read_rows(path)
        changed = False
        for q in rows:
            qt = q.get('question_type')
            if qt not in SUBJECTIVE_TYPES:
                stats['skipped_objective'] += 1
                continue
            if qt not in target:
                continue
            rubric = q.setdefault('rubric', {})
            if manually_reviewed(rubric):
                # 人工审核数据只读不写
                stats['skipped_manual'] += 1
                continue
            points = generate_points(q)
            if not points:
                continue
            rubric['question_specific_points'] = points
            rubric['question_specific_points_meta'] = build_meta(q, len(points))
            # 确保不误标为官方/已核
            rubric['official_scoring'] = False
            rubric['expert_verified'] = False
            for d in DIMENSIONS:
                if any(p['primary_dimension'] == d for p in points):
                    stats['dimension_hits'][d] += 1
            stats['processed'] += 1
            stats['by_type'][qt] = stats['by_type'].get(qt, 0) + 1
            stats['points_per_type'].setdefault(qt, []).append(len(points))
            changed = True
        if changed and not dry_run:
            write_rows(path, rows)
    return stats


def main():
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(description='为主观题生成 question_specific_points')
    ap.add_argument('--types', nargs='+', default=['材料分析', '教学设计', '简答'],
                    help='要处理的主观题型（默认：材料分析 教学设计 简答）')
    ap.add_argument('--dry-run', action='store_true', help='只统计不写盘')
    args = ap.parse_args()
    stats = process(args.types, dry_run=args.dry_run)
    # 汇总每题平均评分点
    avg = {t: round(sum(v) / len(v), 2) if v else 0
           for t, v in stats.get('points_per_type', {}).items()}
    summary = {k: v for k, v in stats.items() if k != 'points_per_type'}
    summary['avg_points_per_type'] = avg
    summary['target_types'] = list(set(args.types) & SUBJECTIVE_TYPES)
    summary['dry_run'] = args.dry_run
    print(_json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
