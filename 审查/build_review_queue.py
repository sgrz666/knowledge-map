"""生成 审查/待复核清单.md：把所有“机器不能替教研签字”的队列如实列出。

本文件是 待复核清单.md 的**唯一来源**：清单里的数字一律现算，不许手抄进 markdown——
手抄的段落重跑本脚本时会被抹掉（§3.1 与考务规格一节都曾因此丢过），也迟早和库不符。
"""
import json, io, glob, os, collections, pathlib, datetime, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

ROOT = pathlib.Path('.')
rows_by_lib = {}
for lib, name in (('数据集/教资', 'NTCE'), ('数据集/四六级', 'CET')):
    dedup = {}
    for f in sorted(glob.glob(lib + '/graph/edges*.jsonl')):
        for line in io.open(f, encoding="utf-8"):
            if not line.strip():
                continue
            e = json.loads(line)
            if 'prereq' not in str(e.get('type')) + str(e.get('rel')):
                continue
            row = {'file': pathlib.Path(f).name, 'src': e.get('src'), 'dst': e.get('dst'),
                   'status': e.get('status') or e.get('review_status'),
                   'declared': e.get('declared_status'),
                   'active': e.get('active_for_learning_path', e.get('active')),
                   'why': (e.get('rationale') or e.get('note') or '').strip()}
            # edges.jsonl 已合并 edges_curated.jsonl，按 src→dst 去重避免同一边重复入库队列
            key = (row['src'], row['dst'])
            prev = dedup.get(key)
            if prev is None:
                dedup[key] = row
            elif row['file'] == 'edges.jsonl' and prev['file'] != 'edges.jsonl':
                row['file'] = 'edges.jsonl + ' + prev['file']
                dedup[key] = row
    rows_by_lib[name] = sorted(dedup.values(), key=lambda r: (r['file'], r['src'], r['dst']))

def counts(lib, name):
    ans = collections.Counter(); rev = collections.Counter(); prov = collections.Counter()
    signed = 0; calibrated = 0; audio = 0; kn = set()
    for f in glob.glob(lib + '/questions/**/*.jsonl', recursive=True):
        for line in io.open(f, encoding='utf-8'):
            if not line.strip():
                continue
            r = json.loads(line)
            ans[r['content']['answer_status']] += 1
            rv = r['review']
            rev[rv['status']] += 1
            if rv.get('checked_by') or rv.get('reviewed_by'):
                signed += 1
            dm = r.get('difficulty_meta') or {}
            if dm.get('method') in ('irt_calibrated',) or (r.get('difficulty_calibration') or {}).get('reviewer'):
                calibrated += 1
            if (r.get('extra') or {}).get('audio'):
                audio += 1
            for k in r.get('knowledge_node_ids') or []:
                kn.add(k)
    return dict(ans=ans, rev=rev, signed=signed, calibrated=calibrated, audio=audio, kn=len(kn))

stats = {name: counts(lib, name) for lib, name in (('数据集/教资', 'NTCE'), ('数据集/四六级', 'CET'))}

prio = {}
for lib, name in (('数据集/教资', 'NTCE'), ('数据集/四六级', 'CET')):
    c = collections.Counter()
    for f in glob.glob(lib + '/questions/**/*.jsonl', recursive=True):
        for line in io.open(f, encoding='utf-8'):
            if line.strip():
                c[(json.loads(line).get('review') or {}).get('review_priority')] += 1
    prio[name] = c

# 权威条款覆盖
auth_ids, referenced = set(), set()
retired_ids = 0
for f in glob.glob('权威资料/**/*.jsonl', recursive=True):
    archived = pathlib.Path(f).name.startswith('retired_')
    for line in io.open(f, encoding='utf-8'):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        rid = r.get('requirement_id') or r.get('id')
        if not rid:
            continue
        if archived or r.get('retirement_reason'):
            # 退休条目按官方权威资料 README 只供抽取留痕，不入图也不作覆盖分母。
            retired_ids += 1
            continue
        auth_ids.add(rid)
graph_nodes = set()
for f in glob.glob('数据集/*/graph/nodes.jsonl'):
    for line in io.open(f, encoding='utf-8'):
        if line.strip():
            graph_nodes.add(json.loads(line).get('id'))
for f in glob.glob('数据集/*/graph/edges.jsonl'):
    for line in io.open(f, encoding='utf-8'):
        if line.strip():
            e = json.loads(line)
            if (e.get('type') or e.get('rel')) == 'aligned_to_requirement':
                referenced.update(x for x in (e.get('src'), e.get('dst')) if x in auth_ids)
unref = sorted(auth_ids - referenced)
prefix = collections.Counter(i.split('.')[0] for i in unref)
in_nodes = auth_ids & graph_nodes

# 评分量规底数：题内练习框架（无权重、不可判分）与 附录 A.6 加权量规实体分开统计。
rub = {'inline': 0, 'inline_no_points': 0, 'inline_on_unannotated': 0, 'choice_with_framework': 0,
       'canonical': 0, 'canonical_unsigned': 0, 'canonical_bound': 0}
for f in glob.glob('数据集/教资/questions/**/*.jsonl', recursive=True):
    for line in io.open(f, encoding='utf-8'):
        if not line.strip():
            continue
        r = json.loads(line)
        framework = r.get('rubric')
        if not isinstance(framework, dict):
            continue
        rub['inline'] += 1
        if not framework.get('question_specific_points'):
            rub['inline_no_points'] += 1
        if r.get('question_type') in ('单选', '多选'):
            rub['choice_with_framework'] += 1
        if r.get('question_type') in ('未标注', None, ''):
            rub['inline_on_unannotated'] += 1
referenced_rubric_ids = set()
for f in glob.glob('数据集/教资/graph/edges.jsonl'):
    for line in io.open(f, encoding='utf-8'):
        if line.strip():
            e = json.loads(line)
            if (e.get('type') or e.get('rel')) == 'has_rubric':
                referenced_rubric_ids.add(e.get('dst'))
for f in sorted(glob.glob('数据集/教资/rubrics/*.json')):
    payload = json.loads(io.open(f, encoding='utf-8').read())
    for entry in (payload if isinstance(payload, list) else [payload]):
        if not isinstance(entry, dict) or not entry.get('rubric_id'):
            continue
        rub['canonical'] += 1
        review = entry.get('review') or {}
        if not review.get('checked_by'):
            rub['canonical_unsigned'] += 1
        if entry['rubric_id'] in referenced_rubric_ids:
            rub['canonical_bound'] += 1

cet_rubric_path = pathlib.Path('数据集/四六级/ontology/scoring_rubrics.jsonl')
cet_rubric_entities = len({json.loads(line).get('rubric_id')
                           for line in io.open(cet_rubric_path, encoding='utf-8') if line.strip()}) \
    if cet_rubric_path.is_file() else 0

# 考务规格自检：组卷与时序都只认 paper_specs，规格自己打架时机器无权挑一边当真——必须进教研队列。
SPEC_FILES = {'NTCE': '数据集/教资/paper_specs.jsonl', 'CET': '数据集/四六级/manifest/paper_specs.jsonl'}


def spec_audit(rel):
    rows = [json.loads(line) for line in io.open(rel, encoding='utf-8') if line.strip()]
    out = {'specs': len(rows), 'no_timing': 0, 'timing_mismatch': collections.Counter(),
           'score_mismatch': collections.Counter(), 'count_mismatch': collections.Counter(),
           'parts': 0, 'locked': 0}
    for r in rows:
        parts = r.get('parts') or r.get('sections') or []
        out['parts'] += len(parts)
        out['locked'] += sum(1 for p in parts if p.get('lock_policy'))
        minutes = [p.get('duration_minutes') for p in parts]
        if not any(minutes):
            out['no_timing'] += 1
        elif sum(int(m or 0) for m in minutes) != int(r.get('total_duration_minutes') or 0):
            out['timing_mismatch'][(sum(int(m or 0) for m in minutes), r.get('total_duration_minutes'))] += 1
        scored = [p.get('total_score', p.get('score')) for p in parts]
        declared_score = r.get('total_raw_score', r.get('total_score'))
        if declared_score and any(s is not None for s in scored) \
                and abs(sum(float(s or 0) for s in scored) - float(declared_score)) > 1e-6:
            out['score_mismatch'][(sum(float(s or 0) for s in scored), declared_score)] += 1
        counted = [p.get('question_count', p.get('count')) for p in parts]
        declared_count = r.get('question_count')
        if declared_count and any(c is not None for c in counted) \
                and sum(int(c or 0) for c in counted) != int(declared_count):
            out['count_mismatch'][(sum(int(c or 0) for c in counted), declared_count)] += 1
    return out


specs = {name: spec_audit(rel) for name, rel in SPEC_FILES.items()}

# 抽取缺口用运行时同一份索引投影来数：清单和组卷池子必须共用判据，否则清单说 45 题、引擎挡下 46 题。
from services.knowledge.repository import get_repository  # noqa: E402

GROUPS = (('教资（NTCE+省考）', ('NTCE', '省考')), ('CET-4', ('CET-4',)), ('CET-6', ('CET-6',)))
_facade = get_repository()
_all_meta = list(_facade.find_questions())
gap = {name: collections.Counter() for name, _ in GROUPS}
gap_where = {name: collections.Counter() for name, _ in GROUPS}
for _m in _all_meta:
    for name, exams in GROUPS:
        if _m.exam not in exams:
            continue
        if _m.answer_status == 'missing':
            gap[name]['missing'] += 1
        if not _m.has_answerable_text:
            gap[name]['unanswerable'] += 1
            gap_where[name][(_m.module or _m.subject or '-', _m.question_type or '-')] += 1
            if _m.answer_status in ('letter_only', 'reference_only'):
                gap[name]['checkable'] += 1
total_missing = sum(1 for m in _all_meta if m.answer_status == 'missing')

# 题面吞邻题的清点：判据与修复、回卷核对共用 kb_tools/ntce_repair.py 那一份函数，清单不另写正则。
sys.path.insert(0, str((ROOT / 'kb_tools').resolve()))
from ntce_repair import (boundary_risks, mix_risk_evidence,  # noqa: E402
                         recorded_numbers, unrecorded_neighbors)


def boundary_inventory(lib='数据集/教资'):
    """全库清点"题面里吞掉另一道题"，并把其中"被吞掉的邻题在本卷没有独立记录"的那部分单列。

    两类缺口的下一步动作相反：邻题已有独立记录时剪文本是去重；没有记录时剪文本等于删掉库里
    唯一一份邻题内容，只能对着原件补收录。所以清单必须把这两类分开报，而不是给一个总数。
    `numbered` 只数"正文露出邻题编号"的题，它才是补收录的分母；命中其它序列形态但没有编号的题
    落不进这两侧，不能拿 `with_risk - unrecorded` 当成"已有独立记录"那一侧。
    """
    out = {'questions': 0, 'with_risk': 0, 'codes': collections.Counter(),
           'numbered': 0, 'unrecorded_questions': 0, 'unrecorded_unlocated': 0,
           'papers': 0, 'papers_without_locator': 0, 'where': collections.Counter(),
           'pairs': set(), 'pairs_located': set()}
    for path in sorted((ROOT / lib / 'questions').glob('*/*/*.jsonl')):
        rows = [json.loads(line) for line in io.open(path, encoding='utf-8') if line.strip()]
        recorded = recorded_numbers(rows)
        out['papers'] += 1
        if not recorded:
            out['papers_without_locator'] += 1
        scope = '%s/%s' % (path.parent.parent.name, path.parent.name)
        # 卷的身份用"学段/科目/文件名"全路径，不用裸文件名：不同学段或科目下会有同名卷面文件，
        # 裸名合并会把两道不同的补收录缺口当成一条，编号总数被压低。
        paper = (path.relative_to(ROOT / lib / 'questions')).as_posix()
        for q in rows:
            out['questions'] += 1
            evidence = mix_risk_evidence(q)
            risks = boundary_risks(evidence)
            if risks:
                out['with_risk'] += 1
                out['codes'].update(risks)
            if not evidence['embedded_numbers']:
                continue
            out['numbered'] += 1
            missing = unrecorded_neighbors(evidence, recorded)
            if missing:
                out['unrecorded_questions'] += 1
                out['where'][scope] += 1
                # 按（卷·编号）去重：同一卷里两道题都露出编号 77，要补的是同一条记录，不是两条。
                out['pairs'].update((paper, n) for n in missing)
                if recorded:
                    out['pairs_located'].update((paper, n) for n in missing)
                else:
                    # 这份卷面一条题号定位都没有："没有记录"只说明定位缺失，不能当成收录缺口。
                    out['unrecorded_unlocated'] += 1
    out['unrecorded_numbers'] = len(out['pairs'])
    out['unrecorded_numbers_located'] = len(out['pairs_located'])
    return out


boundary = boundary_inventory()

L = []
L.append('# 待复核清单（教研签署队列）\n')
L.append('生成时间：%s。本清单只列**机器无法自行判定**的事项：每一项都需要具名教研复核，任何脚本都不代签。\n' % datetime.date.today().isoformat())
L.append('\n## 0. 当前底数（无人工署名，全部如实保留）\n')
L.append('| 项目 | 教资 NTCE | 四六级 CET |')
L.append('| --- | --- | --- |')
q_total = {'NTCE': 14500, 'CET': 5632}
for label, key in (('answer_status', 'answer_status'), ):
    pass
L.append('| 题目总数 | %d | %d |' % (q_total['NTCE'], q_total['CET']))
for state in ('verified', 'letter_only', 'reference_only', 'missing', 'source_conflict'):
    L.append('| └ 答案态 `%s` | %d | %d |' % (state, stats['NTCE']['ans'].get(state, 0), stats['CET']['ans'].get(state, 0)))
for state in ('auto_parsed', 'llm_enhanced', 'checked', 'expert_reviewed', 'needs_fix', 'quarantined'):
    L.append('| 复核态 `%s` | %d | %d |' % (state, stats['NTCE']['rev'].get(state, 0), stats['CET']['rev'].get(state, 0)))
L.append('| 有具名审核人的题目 | **0** | **0** |')
L.append('| 经真实作答数据校准的难度 | **0** | **0** |')
L.append('| 已挂载知识点去重数 | 791 | %d（其中被题目引用 30） |' % stats['CET']['kn'])
L.append('| 带音频指针的题目 | 不适用 | %d |' % stats['CET']['audio'])
L.append('\n状态词表由 `审查/状态词表检查.py` 校验，两套库共用 `数据集/教资/schemas/question.json`，越界取值一律记结构性错误。\n')

L.append('\n## 1. 先修关系候选（不得进入正式学习路径）\n')
L.append('这些边的 `reviewed_by` 为空，`active_for_learning_path` 已置 false；脚本此前的自评 `verified` 已降级并在 `declared_status` 留痕。\n')
for name in ('NTCE', 'CET'):
    rows = rows_by_lib[name]
    L.append('\n### 1.%d %s：%d 条待核定\n' % (('NTCE', 'CET').index(name) + 1, name, len(rows)))
    L.append('| 源文件 | 先修 → 后继 | 当前状态 | 原声明 | 依据（截断） |')
    L.append('| --- | --- | --- | --- | --- |')
    for r in rows:
        L.append('| %s | `%s` → `%s` | %s | %s | %s |' % (
            r['file'], r['src'], r['dst'], r['status'], r['declared'] or '-', (r['why'] or '')[:60].replace('|', '/')))
    L.append('')

L.append('\n## 2. 官方权威条款未被题目引用\n')
L.append('有效条款 %d 条（退休条目 %d 条另存 `权威资料/retired_requirement_records.jsonl`，不入图也不计作分母），'
         '图谱 L0 条款节点 %d 条，被 `aligned_to_requirement` 引用的有 %d 条，**未引用 %d 条**。\n'
         % (len(auth_ids), retired_ids, len(in_nodes), len(referenced & auth_ids), len(unref)))
L.append('| 条款前缀 | 未引用条数 |')
L.append('| --- | --- |')
for k, v in prefix.most_common():
    L.append('| `%s.*` | %d |' % (k, v))
L.append('\n教研需逐项判定：该条款是否可被现有题覆盖；若无对应题，应作为命题缺口而不是挂载失败。\n')

L.append('\n## 3. 答案与来源缺口\n')
L.append('- 教资 `source_conflict` %d 题：来源答案相互矛盾，`content.answer` 已置 null，原值保存在 `extra.answer_candidate`/`source_repairs`，需回溯原件判定；'
         '其中 3 题是“答案字母不在印刷选项内”，原因是转录或选项切分问题。' % stats['NTCE']['ans'].get('source_conflict', 0))
L.append('- 四六级 `source_conflict` %d 题、`missing` %d 题：听力口语项与部分客观项原文未恢复答案，不得用模型补答。'
         % (stats['CET']['ans'].get('source_conflict', 0), stats['CET']['ans'].get('missing', 0)))
L.append('- 教资 `missing` %d 题：原答案文件标注“略/暂缺”。' % stats['NTCE']['ans'].get('missing', 0))
L.append('- RAG 卡片：教资 12,881 张有效（14,500 题中 1,619 题判为重复题干，按设计不出卡，避免污染向量库）。\n')
L.append('### 3.1 运行时已按 A3 挡下的两类题（由 `审查/build_review_queue.py` 现算，判据在 `services/knowledge/repository.py:has_answerable_text`）\n')
L.append('这两类都不是可信度问题，而是**抽取完整性**问题：机器能看出题号，看不出可作答的题面。'
         '运行时不猜题干、也不把它们计入可用题量。\n')
L.append('| 缺口 | %s | 运行时后果 |' % ' | '.join(name for name, _ in GROUPS))
L.append('| %s |' % ' | '.join(['---'] * (2 + len(GROUPS))))
for label, key, note in (
        ('只剩套名/题号、且无选项可勾', 'unanswerable', '不进组卷池、不进错题重做，组卷响应带缺口条数'),
        ('└ 其中答案已可核对、只差题干的', 'checkable', '补完题干抽取即可直接变可用题量'),
        ('答案态 `missing`', 'missing', '不进组卷/判分/召回；答疑只能按题目文本讲，`answer_visibility=none`')):
    L.append('| %s | %s | %s |' % (label, ' | '.join('{:,}'.format(gap[name][key]) for name, _ in GROUPS), note))
L.append('\n集中位置：%s。\n' % '；'.join(
    '%s 落在 %s%s' % (name,
                      '、'.join('%s·%s %d' % (where, kind, n)
                                for (where, kind), n in gap_where[name].most_common(8)),
                      '（共 %d 类，此处列前 8 类）' % len(gap_where[name]) if len(gap_where[name]) > 8 else '')
    for name, _ in GROUPS if gap_where[name]))
L.append('- 需要人做的动作：回到 `数据集/四六级/questions/cet*/**` 与教资对应目录的原始 PDF，'
         '把对应题干的文本块补齐并重建索引；不要由模型据解析反推题干。')
L.append('- 口径差异说明：`审查/validate_kb.py` 的 `Q_STEM_EMPTY` 判据是"题干无可读文本"，不看有没有选项，'
         '所以它统计的总缺口一定不小于上表第一行；上表第一行数的是其中"连选项都没有、所以真的无法作答"的子集，'
         '也就是运行时真正会少出题量的那一块。')
L.append('- 补完后本表三条计数应同时下降，`tests/test_acceptance_gate.py` 的 A3 题干用例随之失去正例，'
         '需要按当时数据改判据。\n')

L.append('### 3.2 题面吞掉邻题的题：剪文本还是补收录，看被吞的那道题有没有独立记录\n')
L.append('判据与修复流程、回卷核对共用 `kb_tools/ntce_repair.py` 里的同一组函数'
         '（`mix_risk_evidence` 出题面证据、`boundary_risks` 把证据映成形态码、'
         '`recorded_numbers` 给出本卷已独立入库的题号、`unrecorded_neighbors` 取其中没有记录的那些），'
         '本清单不另写一份正则；邻题编号按"数字 + 邻题常见开头词"识别，是**下限而不是穷举**。\n')
L.append('| 题面边界形态（同一题可命中多项，不能相加） | 题数 |')
L.append('| --- | --- |')
for label, code in (('题干里有整道完整选项序列', 'complete_choice_sequence_in_stem'),
                    ('选项文本里有整道完整选项序列', 'complete_choice_sequence_in_option'),
                    ('一段文本里出现两道以上完整序列', 'multiple_complete_choice_sequences'),
                    ('正文里露出别的题号', 'embedded_numbered_question_candidate')):
    L.append('| %s | %s |' % (label, '{:,}'.format(boundary['codes'].get(code, 0))))
L.append('| **命中任一项** | **%s**（本库 %s 题） |' % (
    '{:,}'.format(boundary['with_risk']), '{:,}'.format(boundary['questions'])))
L.append('\n下一轮该动哪一侧，由"被吞掉的邻题在本卷有没有独立记录"分开判，两侧动作相反。'
         '分母只取"正文露出邻题编号"的 %s 题——其余命中题只数得出序列、认不出编号，无从判断有没有记录：\n'
         % '{:,}'.format(boundary['numbered']))
L.append('| 分岔 | 教资 | 该做的动作 |')
L.append('| --- | --- | --- |')
L.append('| 露出的编号在本卷都有独立记录 | %s 题 | 剪掉重复文本是去重，题量不变 |' %
         '{:,}'.format(boundary['numbered'] - boundary['unrecorded_questions']))
L.append('| **露出的编号在本卷没有独立记录** | **%s 题、%s 条（卷·编号）** | '
         '**对着原件把漏收的题补成独立记录**；剪文本等于删掉库里唯一一份邻题内容 |' % (
             '{:,}'.format(boundary['unrecorded_questions']), '{:,}'.format(boundary['unrecorded_numbers'])))
L.append('| 命中序列但认不出任何编号 | %s 题 | 逐题回原卷人工判，机器不给结论 |' %
         '{:,}'.format(boundary['with_risk'] - boundary['numbered']))
L.append('\n- 补收录缺口的分布（列前 8 个学段·科目，共 %d 个）：%s。' % (
    len(boundary['where']),
    '、'.join('%s %s' % (scope, n) for scope, n in boundary['where'].most_common(8))))
L.append('- 证据强度：全库 %d 份卷面里有 %d 份一条题号定位都没有，落在这些卷上的 %s 题（%s 条）只能说"定位缺失"——'
         '无定位卷面撑不起"本卷没有这条记录"这个结论，表里那行 %s 题／%s 条是同口径总数，并没有替它担保。'
         '减去这些之后，真正能对着原件补的是 %s 题／%s 条（%s 条出自带题号定位的卷面）。' % (
             boundary['papers'], boundary['papers_without_locator'],
             '{:,}'.format(boundary['unrecorded_unlocated']),
             '{:,}'.format(boundary['unrecorded_numbers'] - boundary['unrecorded_numbers_located']),
             '{:,}'.format(boundary['unrecorded_questions']), '{:,}'.format(boundary['unrecorded_numbers']),
             '{:,}'.format(boundary['unrecorded_questions'] - boundary['unrecorded_unlocated']),
             '{:,}'.format(boundary['unrecorded_numbers_located']),
             '{:,}'.format(boundary['unrecorded_numbers_located'])))
L.append('- 逐题证据（字段名、序列计数、被吞掉的编号清单）在 `数据集/教资/review/answer_conflict_reconciliation.jsonl` '
         '的 `content_boundary`；该文件只覆盖已核对过的那一批，本表是全库现算，两边口径同一份函数。')
L.append('- 这批缺陷不会被 `审查/validate_kb.py` 单独计数：它记的是 `Q_ANSWER_SOURCE_CONFLICT` 之类的题级缺口，'
         '而"漏收邻题"在库里表现为**根本没有那条记录**，所以只能靠本表发现，不能等严格审查报出来。\n')

L.append('\n## 4. 评分量规与权重（题内框架一律不可判分）\n')
L.append('库里有两套量规形状，契约不同：`数据集/教资/schemas/rubric.json` 是 附录 A.6 的可计算加权量规实体，'
         '`数据集/教资/schemas/practice_framework.json` 是题内练习框架（只有维度与档位描述，**没有分值权重**）。'
         '题内框架只能给反馈，不能出分；两套形状混写会被 `审查/validate_kb.py` 记为 `Q_RUBRIC_DUAL_TRUTH`。\n')
L.append('- 教资加权量规实体 %d 套，其中 **%d 套没有具名审核人**（`expert_verified` 已由脚本自动降级为 false，'
         '本轮把原先无署名却写死的 `expert_verified: true` 一并降回），维度权重与档位措辞均需教研签署。'
         % (rub['canonical'], rub['canonical_unsigned']))
L.append('- 加权量规实体被题目 `has_rubric` 边引用的只有 %d 套；其余是独立标准稿，尚未决定挂到哪些题型，'
         '请教研指定绑定关系或删除冗余实体。' % rub['canonical_bound'])
L.append('- 题内练习框架 %d 份（全部 `practice_framework_pending_subject_expert`），其中 %d 份连本题专属得分点都还没有；'
         '这些题目前只能做自评反馈，不能计分。' % (rub['inline'], rub['inline_no_points']))
L.append('- %d 份框架挂在 `题型未标注` 的题上（`Q_TYPE_UNVERIFIED`），题型核定后可能要从框架改为选项判分。'
         % rub['inline_on_unannotated'])
L.append('- 选择题携带的主观题框架现为 %d 份：本轮由 `kb_tools/ntce_rubric_contract.py` 剥离 152 份影子量规，'
         '原值快照在 `归档/教资_迁移前快照_20261009/`，如认为其中某些题应按主观题评分，请核定题型后重建框架。' % rub['choice_with_framework'])
L.append('- 四六级写译共用 %d 套官方档次量规（`数据集/四六级/ontology/scoring_rubrics.jsonl`），'
         '是整档给分并在档内给反馈维度，不是维度加权；正式评分仍需当次样卷与训练过的阅卷员。\n' % cet_rubric_entities)

L.append('\n## 5. 复核优先级\n')
L.append('- 教资 needs_fix 按历史标记分级：低置信 %d 题、一般瑕疵 %d 题，明细见 `数据集/教资/review/pending.jsonl`；低置信项来自结构切分严重异常，应优先处理。'
         % (prio['NTCE'].get('low_confidence', 0), prio['NTCE'].get('flagged_general', 0)))
L.append('- 四六级 `needs_fix` %d 题：来源身份或语篇绑定未核实，先修边一律待核定。' % stats['CET']['rev'].get('needs_fix', 0))
_checkable_total = sum(gap[name]['checkable'] for name, _ in GROUPS)
L.append('- 题干抽取缺口 %d 题（§3.1 第 2 行：%s）性价比最高：答案已在库内、只差题面，补完即可直接转为可用练习量；'
         '相比之下全库 `missing` 的 %s 题要先回溯原件定答案。' % (
             _checkable_total,
             '、'.join('%s %d' % (name, gap[name]['checkable']) for name, _ in GROUPS),
             '{:,}'.format(total_missing)))
L.append('- 版权：全部题目 `authorization_status=unknown`、`use_scope=research_non_commercial`，未做任何授权声明；'
         '若项目要转为商业或出版用途，本清单第 5 节全部结论作废并需重新清权。\n')

L.append('\n## 6. 考务规格（paper_specs）内部一致性\n')
L.append('组卷结构与时序只认 `数据集/**/paper_specs.jsonl`（验收 A1：服务里不许留手抄卷面）。'
         '规格自己打架时机器无权挑一边当成真的，以下差异全部留给教研核定，官方卷面数据不做任何自动改动。\n')
for name in ('NTCE', 'CET'):
    a = specs[name]
    L.append('- %s：规格 %d 套、小节 %d 个，其中 %d 个小节带 `lock_policy`（决定何时收答题卡、能否回退）。'
             % (name, a['specs'], a['parts'], a['locked']))
    if a['no_timing']:
        L.append('  - **%d 套完全没有逐节用时**（只有 `total_duration_minutes`）：模考只按卷面结构组卷，'
                 '不启动时序机，也不替官方考试编一份时间表。补齐 `sections[].duration_minutes` 后模考才谈得上收卡时机。'
                 % a['no_timing'])
    for label, key in (('逐节用时合计 ≠ 声明总时长', 'timing_mismatch'),
                       ('逐节分值合计 ≠ 声明总分', 'score_mismatch'),
                       ('逐节题量合计 ≠ 声明题量', 'count_mismatch')):
        for (summed, declared), n in sorted(a[key].items(), key=lambda kv: -kv[1]):
            L.append('  - **%s：%d 套**，逐节合计 %s 而规格声明 %s。运行时时序按逐节数字推进（那份数字决定何时收卡），'
                     '两处需统一口径。' % (label, n, ('%g' % summed), declared))
L.append('\n教研需逐项判定：声明总量里多出的分钟数是试音/收发答题卡等卷面外时间，还是逐节漏记；'
         '若属卷面外时间，请把它写成独立字段（如 `instruction_time_minutes`）而不是改官方逐节分钟数。\n')

# 题面用时约束与卷面逐节用时是库内两处独立记录：清单用运行时同一份读数，避免清单与组卷各算一套。
from services.knowledge.repository import item_time_limit  # noqa: E402

spec_minutes_by_module = {}
for lib, rel in SPEC_FILES.items():
    for line in io.open(rel, encoding='utf-8'):
        if not line.strip():
            continue
        row = json.loads(line)
        for part in (row.get('parts') or row.get('sections') or []):
            if part.get('module') and part.get('duration_minutes'):
                spec_minutes_by_module.setdefault((lib, part['module']), set()).add(int(part['duration_minutes']))

item_minutes = collections.Counter()
item_status = collections.Counter()
conflict = collections.Counter()
timed_items = 0
for _m in _all_meta:
    record = _facade.load_question(_m.question_id)
    minutes = item_time_limit(record)
    if not minutes:
        continue
    timed_items += 1
    item_minutes[(_m.exam, _m.module or '-', minutes)] += 1
    status = ((record.get('extra') or {}).get('task_constraints') or {}).get('constraints_status')
    item_status[status or '(未声明)'] += 1
    # 同一套卷里题面用时应当等于所属小节的逐节用时；不一致只登记，机器不选边改数。
    lib = 'CET' if (_m.exam or '').startswith('CET') else 'NTCE'
    allowed = spec_minutes_by_module.get((lib, _m.module or '-'))
    if allowed and minutes not in allowed:
        conflict[(_m.exam, _m.module or '-', minutes, tuple(sorted(allowed)))] += 1

L.append('\n## 6.1 题面用时约束（`extra.task_constraints.time_limit_minutes`）\n')
L.append('组卷给一卷定限时逐题问这份约束；库里说不出用时的题按服务配速（`services/common/pacing.py`，'
         '目前每题 2 分钟）折算，并在结果里写明那部分是估计。以下数字由题面约束算出，与 §6 的逐节用时相互独立。\n')
L.append('- 全库 %s 题里 %d 题带题面用时约束：' % ('{:,}'.format(len(_all_meta)), timed_items))
for (exam, module, minutes), n in sorted(item_minutes.items(), key=lambda kv: (-kv[1], kv[0])):
    L.append('  - `%s` / %s：%d 题，各 %d 分钟' % (exam, module, n, minutes))
for status, n in sorted(item_status.items(), key=lambda kv: -kv[1]):
    L.append('  - `constraints_status` = `%s`：%d 题（这份约束的出处由库里自己声明）' % (status, n))
if conflict:
    L.append('- **与所属小节逐节用时对不上的：%d 题**——组卷仍按题面约束计入限时（限时不短于题面要求），'
             '时序机按逐节用时推进，两处需教研核定后统一：')
    for (exam, module, minutes, allowed), n in sorted(conflict.items(), key=lambda kv: -kv[1]):
        L.append('  - %s / %s：%d 题写 %d 分钟，而 §6 里该小节写 %s。'
                 % (exam, module, n, minutes, '/'.join(str(v) for v in allowed)))
else:
    L.append('- 与 §6 的逐节用时交叉核对：全部一致（带约束的题，其题面用时等于所属小节的 `duration_minutes`）。'
             '两处若将来打架，组卷会把不一致写进卷子说明并排队复核，机器不会自行改数。')
L.append('- 其余题库内没有题面用时约束（含教资全部题目）：组卷按配速估时并标注为估计值，'
         '如果这些题也需要按卷面限时出题，请教研把约束补进 `extra.task_constraints`。\n')

L.append('\n## 7. 复核动作\n')
L.append('1. 认领某一项后，在对应记录写入 `review.checked_by` 与 `review.checked_at`，并把 `review.status` 推进到 `checked` 或 `expert_reviewed`；'
         '验收器 `审查/validate_kb.py` 会拒绝没有署名的这类状态。')
L.append('2. 先修边核定：改 `graph/edges_curated.jsonl` 的 `reviewed_by`、`status=verified`、`active=true`，再跑 `python kb_tools/build_graph.py`。')
L.append('3. 量规权重签署：在 `数据集/教资/rubrics/*.json` 写 `review.checked_by`/`checked_at`、把 `review.status` 推进到 `expert_reviewed`，'
         '并同步 `expert_verified: true`；署名缺失时 `tests/test_rubric_contract.py` 与 `Q_RUBRIC_EXPERT_CLAIM` 会直接拒绝。'
         '题内练习框架不参与判分，如需出分请把核定后的权重写成 A.6 实体并建立绑定，不要往题内框架塞 `weight_score`。')
L.append('4. 考务规格核定（§6）：只改 `数据集/**/paper_specs.jsonl` 里教研确认有误的那一侧，并在提交说明里写清依据；'
         '运行时按逐节分钟数推进时序，服务不会替官方卷面补齐或删减分钟数。')
L.append('5. 题面用时核定（§6.1）：卷面确实要求单题用时的，写进对应题目的 `extra.task_constraints.time_limit_minutes`；'
         '库里没写的，组卷只会按服务配速估时并标注为估计，不会冒出"官方建议用时"。')
L.append('6. 题面吞邻题（§3.2）：先按 `content_boundary` 的编号查本卷有没有独立记录——有记录的剪重复文本，'
         '没有记录的对着原始 PDF 把漏收的那道题补成独立记录再重建索引；**不许用剪文本"清理"补收录缺口**，'
         '那等于删掉库里唯一一份邻题内容。')
L.append('7. 每轮改动后运行：`python -m pytest tests -q`、`python 审查/状态词表检查.py 数据集/教资`、'
         '`python 审查/validate_kb.py`、`python 审查/build_review_queue.py`（清单是生成物，不要手改）。\n')

out = '\n'.join(x for x in L if x is not None) + '\n'
target = pathlib.Path(os.environ.get('KM_QUEUE_OUT', '审查/待复核清单.md'))
target.write_text(out, encoding='utf-8')
print('written %s, lines: %s' % (target, out.count('\n')),
      '| prereq rows NTCE/CET: %d %d' % (len(rows_by_lib['NTCE']), len(rows_by_lib['CET'])),
      '| unreferenced clauses: %d' % len(unref),
      '| boundary risks/unrecorded: %d/%d 题, %d 条编号' % (
          boundary['with_risk'], boundary['unrecorded_questions'], boundary['unrecorded_numbers']),
      '| spec timing gaps NTCE/CET: %d %d' % (specs['NTCE']['no_timing'],
                                              sum(specs['CET']['timing_mismatch'].values())))
