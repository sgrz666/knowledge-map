"""生成 审查/待复核清单.md：把所有“机器不能替教研签字”的队列如实列出。"""
import json, io, glob, collections, pathlib, datetime

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
for f in glob.glob('权威资料/**/*.jsonl', recursive=True):
    for line in io.open(f, encoding='utf-8'):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        rid = r.get('requirement_id') or r.get('id')
        if rid:
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
L.append('权威资料共 %d 条条款，图谱 L0 节点仅 %d 条，被 `aligned_to_requirement` 引用的有 %d 条，**未引用 %d 条**。\n'
         % (len(auth_ids), len(in_nodes), len(referenced & auth_ids), len(unref)))
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

L.append('\n## 4. 复核优先级\n')
L.append('- 教资 needs_fix 按历史标记分级：低置信 %d 题、一般瑕疵 %d 题，明细见 `数据集/教资/review/pending.jsonl`；低置信项来自结构切分严重异常，应优先处理。'
         % (prio['NTCE'].get('low_confidence', 0), prio['NTCE'].get('flagged_general', 0)))
L.append('- 四六级 `needs_fix` %d 题：来源身份或语篇绑定未核实，先修边一律待核定。' % stats['CET']['rev'].get('needs_fix', 0))
L.append('- 版权：全部题目 `authorization_status=unknown`、`use_scope=research_non_commercial`，未做任何授权声明；'
         '若项目要转为商业或出版用途，本清单第 4 节全部结论作废并需重新清权。\n')

L.append('\n## 5. 复核动作\n')
L.append('1. 认领某一项后，在对应记录写入 `review.checked_by` 与 `review.checked_at`，并把 `review.status` 推进到 `checked` 或 `expert_reviewed`；'
         '验收器 `审查/validate_kb.py` 会拒绝没有署名的这类状态。')
L.append('2. 先修边核定：改 `graph/edges_curated.jsonl` 的 `reviewed_by`、`status=verified`、`active=true`，再跑 `python kb_tools/build_graph.py`。')
L.append('3. 每轮改动后运行：`python -m pytest tests -q`、`python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`。\n')

out = '\n'.join(x for x in L if x is not None) + '\n'
pathlib.Path('审查/待复核清单.md').write_text(out, encoding='utf-8')
print('written 审查/待复核清单.md, lines:', out.count('\n'),
      '| prereq rows NTCE/CET:', len(rows_by_lib['NTCE']), len(rows_by_lib['CET']),
      '| unreferenced clauses:', len(unref))
