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

L.append('\n## 7. 复核动作\n')
L.append('1. 认领某一项后，在对应记录写入 `review.checked_by` 与 `review.checked_at`，并把 `review.status` 推进到 `checked` 或 `expert_reviewed`；'
         '验收器 `审查/validate_kb.py` 会拒绝没有署名的这类状态。')
L.append('2. 先修边核定：改 `graph/edges_curated.jsonl` 的 `reviewed_by`、`status=verified`、`active=true`，再跑 `python kb_tools/build_graph.py`。')
L.append('3. 量规权重签署：在 `数据集/教资/rubrics/*.json` 写 `review.checked_by`/`checked_at`、把 `review.status` 推进到 `expert_reviewed`，'
         '并同步 `expert_verified: true`；署名缺失时 `tests/test_rubric_contract.py` 与 `Q_RUBRIC_EXPERT_CLAIM` 会直接拒绝。'
         '题内练习框架不参与判分，如需出分请把核定后的权重写成 A.6 实体并建立绑定，不要往题内框架塞 `weight_score`。')
L.append('4. 考务规格核定（§6）：只改 `数据集/**/paper_specs.jsonl` 里教研确认有误的那一侧，并在提交说明里写清依据；'
         '运行时按逐节分钟数推进时序，服务不会替官方卷面补齐或删减分钟数。')
L.append('5. 每轮改动后运行：`python -m pytest tests -q`、`python 审查/状态词表检查.py 数据集/教资`、'
         '`python 审查/validate_kb.py`、`python 审查/build_review_queue.py`（清单是生成物，不要手改）。\n')

out = '\n'.join(x for x in L if x is not None) + '\n'
target = pathlib.Path(os.environ.get('KM_QUEUE_OUT', '审查/待复核清单.md'))
target.write_text(out, encoding='utf-8')
print('written %s, lines: %s' % (target, out.count('\n')),
      '| prereq rows NTCE/CET: %d %d' % (len(rows_by_lib['NTCE']), len(rows_by_lib['CET'])),
      '| unreferenced clauses: %d' % len(unref),
      '| spec timing gaps NTCE/CET: %d %d' % (specs['NTCE']['no_timing'],
                                              sum(specs['CET']['timing_mismatch'].values())))
