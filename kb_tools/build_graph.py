"""可遍历的考试→模块→细知识点→题目；层级标签与边命名对齐规范 §3.2/§3.4，先修候选须专家审核后激活。"""
import json
from collections import Counter
from build_kb import OUT, ROOT
from kb_scope import select as scope_select
from ntce_io import atomic_write
from ntce_ontology import ABILITY_NAMES

LEVEL_CN = {'youer': '幼儿园', 'xiaoxue': '小学', 'chuzhong': '初级中学', 'gaozhong': '高级中学', 'zhongxue': '中学', 'zhongxiaoxue': '中小学'}
SUBJECT_CN = {'zonghe': '综合素质', 'baojiao': '保教知识与能力', 'jiaoxue': '教育教学知识与能力', 'jiaoyuzhishi': '教育知识与能力', 'mianshi': '结构化面试', 'jiaoyuxue': '教育学(省考)', 'jiaoyuxinlixue': '教育心理学(省考)', 'yuwen': '语文', 'shuxue': '数学', 'yingyu': '英语', 'zhengzhi': '思想品德/思想政治', 'lishi': '历史', 'dili': '地理', 'wuli': '物理', 'huaxue': '化学', 'shengwu': '生物', 'meishu': '美术', 'yinyue': '音乐', 'tiyu': '体育与健康', 'xinxi': '信息技术'}

# §3.4 核心边；方向即语义，消费方不得反查。
EDGE_ASSESSMENT = 'assesses'                        # knowledge_node -> question
EDGE_ABILITY = 'supports_ability'                  # ability -> knowledge_node|question
EDGE_REQUIREMENT = 'aligned_to_requirement'        # requirement -> knowledge_node|question|rubric|resource
EDGE_PREREQ = 'prerequisite_of'                    # knowledge_node -> knowledge_node
EDGE_MATERIAL = 'refers_to_material'                # question -> material
EDGE_RUBRIC = 'has_rubric'                         # question -> rubric
PREREQ_VERIFIED = 'verified'
PREREQ_PENDING = 'proposed_pending_review'


def rows(path):
    return [json.loads(line) for line in path.open(encoding='utf-8') if line.strip()]


def scan_modules():
    counts, systems = Counter(), {}
    for path in sorted((OUT / 'questions').glob('*/*/*.jsonl')):
        key = path.parent.parent.name, path.parent.name
        records = rows(path)
        counts[key] += len(records)
        if records:
            systems[key] = records[0]['exam']
    modules = {}
    for (level, subject), count in sorted(counts.items()):
        province = systems[(level, subject)] == '省考'
        prefix = 'shengkao' if province else 'ntce'
        eid = 'shengkao' if province else 'ntce.' + level
        modules[(level, subject)] = {'module_id': prefix + '.' + level + '.' + subject,
            'exam_id': eid, 'exam_name': '教师资格省考' if province else 'NTCE-' + LEVEL_CN[level],
            'name': SUBJECT_CN.get(subject, subject), 'count': count}
    return modules, counts


DEPENDENCIES = {
 'shuxue': [('s1.k07', 's1.k06', '导数由函数差商的极限定义，需要先理解极限。'), ('s1.k03', 's1.k06', '导数描述函数局部变化率，需要函数及其定义域概念。'), ('s1.k06', 's1.k08', '原函数由求导关系定义；不定积分学习依赖导数。')],
 'wuli': [('s1.k01', 's1.k02', '牛顿第二定律使用加速度；需先理解运动学中的加速度。'), ('s1.k07', 's1.k08', '电压是电势差，电路分析需使用电势差概念。')],
 'huaxue': [('s1.k01', 's1.k02', '价电子和电子结构用于解释化学键形成。'), ('s1.k03', 's1.k06', '酸碱平衡计算需要物质的量与溶液浓度。')],
 'shengwu': [('s1.k01', 's1.k02', '细胞代谢过程发生于具体细胞结构和细胞器。')],
 'xinxi': [('s1.k03', 's1.k04', '栈队列等数据结构的操作通常用算法表达。')],
}


def build():
    modules, counts = scan_modules()
    nodes, edges, edge_keys = {}, [], set()

    def node(nid, layer, kind, name, **values):
        if nid not in nodes:
            nodes[nid] = {'id': nid, 'layer': layer, 'type': kind, 'name': name, **values}

    def edge(src, dst, kind, **values):
        """§3.4 方向约定：src 是支撑方、dst 是被支撑方，与四六级导出层同向。"""
        key = src, dst, kind
        if key not in edge_keys:
            edge_keys.add(key)
            edges.append({'src': src, 'dst': dst, 'type': kind, **values})

    catalog_path = ROOT / '权威资料/catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else {}
    requirements_path = ROOT / '权威资料/requirements.jsonl'
    requirement_rows = rows(requirements_path) if requirements_path.exists() else []
    # L0 全量入图：按 exam_scope 取 NTCE 侧标准（大纲/法规/师德/规章），不再按 id 前缀硬筛，
    # 否则 CSE 与法规条款在图上根本不存在，aligned_to_requirement 也无从对齐。
    sources, requirements = scope_select(catalog.get('sources', []), requirement_rows, 'ntce')
    for sid, source in sorted(sources.items()):
        node(sid, 'L0', 'standard', source.get('title') or source.get('name') or sid, source_url=source.get('source_url'), local_path=source.get('local_path'), exam_scope=source.get('exam_scope', []), verified=source.get('verified', False), verification_scope='official_source_acquisition')
    for rid, requirement in sorted(requirements.items()):
        node(rid, 'L0', 'exam_requirement', requirement.get('title') or requirement.get('content'), standard_id=requirement['standard_id'], locator=requirement.get('locator'), content=requirement.get('content'), exam_scope=requirement.get('exam_scope', []), verified=False, verification_scope='extracted_clause_pending_review')
        edge(requirement['standard_id'], rid, 'specifies')
    for (level, subject), module in sorted(modules.items()):
        eid, mid = module['exam_id'], module['module_id']
        node(eid, 'L1', 'exam', module['exam_name'])
        node(mid, 'L2', 'module', module['name'], exam=eid, question_count=counts[(level, subject)])
        edge(eid, mid, 'contains')
        path = OUT / 'outline' / (level + '.' + subject + '.json')
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding='utf-8'))
        for sid in doc.get('official_standard_ids', []):
            if sid in nodes:
                edge(sid, mid, 'basis', verified=False, mapping_status='scope_match_pending_review')
        literacy = eid + '.literacy.teacher'
        node(literacy, 'L3', 'literacy', '教师专业素养', exam=eid, verified=False)
        edge(eid, literacy, 'targets')
        for n in doc['nodes']:
            nid = n['node_id']
            node(nid, 'L4', 'knowledge_node', n['name'], module=mid, assessable=n.get('assessable', False), keywords=n.get('keywords', []), exam_requirement_ids=n.get('exam_requirement_ids', []), mapping_status=n.get('mapping_status'), verified=False)
            edge(n.get('parent') or mid, nid, 'has_child' if n.get('parent') else 'contains')
            for rid in n.get('exam_requirement_ids', []):
                if rid in nodes:
                    edge(rid, nid, EDGE_REQUIREMENT, verified=False, mapping_status='automatic_pending_review')
            for code in n.get('ability_codes', []):
                aid = ('shengkao' if eid == 'shengkao' else 'ntce') + '.' + level + '.ability.' + code
                node(aid, 'L3', 'ability', ABILITY_NAMES[code], exam=eid, verified=False, inheritance='none; explicit supports_ability edges and question ability_ids only')
                edge(literacy, aid, 'comprises')
                if n.get('assessable'):
                    edge(aid, nid, EDGE_ABILITY, verified=False, mapping_status='automatic_pending_review')
        for source, target, rationale in DEPENDENCIES.get(subject, []):
            source, target = mid + '.' + source, mid + '.' + target
            if source in nodes and target in nodes:
                edge(source, target, EDGE_PREREQ, status=PREREQ_PENDING, rationale=rationale, reviewed_by=None, active_for_learning_path=False)
    # L5: 共享材料节点
    for mpath in sorted((OUT / 'materials').glob('*/*/*.jsonl')):
        for m in rows(mpath):
            mid_mat = m['material_id']
            node(mid_mat, 'L5', 'material', m.get('title') or mid_mat, word_count=len(m.get('text', '')), used_by_questions=m.get('question_ids', []), level=m.get('level'), subject=m.get('subject'))
    # L6: 量规节点（评分量规是可被多题复用的图谱实体，供 §3.4 has_rubric 遍历）
    for rpath in sorted((OUT / 'rubrics').glob('*.json')):
        if rpath.name == 'README.md':
            continue
        data = json.loads(rpath.read_text(encoding='utf-8'))
        if rpath.name == 'official_interview.json':
            # 官方 61 项面试细则：逐项建可定位到原表的量规节点，尚未核定题项映射，只作参照。
            for index, criterion in enumerate(data.get('criteria', []), start=1):
                rid = 'rubric.ntce.interview.' + str(criterion.get('standard_id')) + '.' + str(criterion.get('project')) + '.' + str(index)
                node(rid, 'L6', 'rubric', criterion.get('criterion'), task_type='interview_teaching', weight_score=criterion.get('weight'), total_score=criterion.get('score'), official=True, review_status='question_task_mapping_pending_review', source='official_interview.json')
                req_id = criterion.get('requirement_id')
                if req_id in nodes:
                    edge(req_id, rid, EDGE_REQUIREMENT, verified=False, mapping_status='official_criterion_locator')
            continue
        rid = data.get('rubric_id')
        if rid:
            # 量规实体的审核态在 review.status 里，不在顶层 status；权重未经签署时必须让消费端看见。
            review = data.get('review') or {}
            node(rid, 'L6', 'rubric', data.get('title') or rid, task_type=data.get('task_type'), total_score=data.get('total_score'), dimension_count=len(data.get('dimensions', [])), official=bool(data.get('official_scoring')), expert_verified=bool(data.get('expert_verified')), review_status=review.get('status') or data.get('status'), pending_reasons=review.get('pending_reasons') or [], reviewed_by=review.get('checked_by'), source=rpath.name)
    # L6: 题目节点
    for path in sorted((OUT / 'questions').glob('*/*/*.jsonl')):
        for q in rows(path):
            module = modules[(q['level'], q['subject'])]
            qid = q['question_id']
            node(qid, 'L6', 'question', None, module=module['module_id'], question_type=q['question_type'], session=q['source']['session'], answer_status=q['content']['answer_status'], review=q['review']['status'], difficulty=q.get('difficulty'))
            edge(module['module_id'], qid, 'contains')
            if q.get('material_id') and q['material_id'] in nodes:
                edge(qid, q['material_id'], EDGE_MATERIAL)
            inline = q.get('rubric')
            if isinstance(inline, dict) and inline.get('rubric_id'):
                brid = inline['rubric_id']
                node(brid, 'L6', 'rubric', brid, task_type=q['question_type'], dimension_count=len(inline.get('dimensions', [])), point_count=len(inline.get('question_specific_points', [])), official=bool(inline.get('official_scoring')), expert_verified=bool(inline.get('expert_verified')), review_status=inline.get('status'), question_id=qid)
                for rid in inline.get('exam_requirement_ids', []):
                    if rid in nodes:
                        edge(rid, brid, EDGE_REQUIREMENT, verified=False, mapping_status='rubric_framework_pending_subject_expert')
            if q.get('rubric_id') and q['rubric_id'] in nodes:
                edge(qid, q['rubric_id'], EDGE_RUBRIC)
            for nid in q.get('knowledge_node_ids', []):
                if nid not in nodes:
                    raise ValueError('Missing knowledge node: ' + nid)
                edge(nid, qid, EDGE_ASSESSMENT, tagger=q['review']['tagger'], verified=q['review']['tagger'] == 'expert')
            for aid in q.get('ability_ids', []):
                if aid not in nodes:
                    raise ValueError('Missing ability node: ' + aid)
                edge(aid, qid, EDGE_ABILITY, verified=False)
            for rid in q.get('exam_requirement_ids', []):
                if rid not in nodes:
                    raise ValueError('Missing official requirement: ' + rid)
                edge(rid, qid, EDGE_REQUIREMENT, verified=False)
    # L7: 学习资源节点
    for rpath in sorted((OUT / 'resources').glob('*.jsonl')):
        for res in rows(rpath):
            rid_res = res['resource_id']
            node(rid_res, 'L7', 'resource', res.get('title') or rid_res, res_type=res.get('type'), exam=res.get('exam'))
            for kn in res.get('knowledge_node_ids', []):
                if kn in nodes:
                    edge(kn, rid_res, 'supplements_resource')
            for aid in res.get('ability_ids', []):
                if aid in nodes:
                    edge(aid, rid_res, 'supports_resource')
            for rid in res.get('exam_requirement_ids', []):
                if rid in nodes:
                    edge(rid, rid_res, EDGE_REQUIREMENT)
    # 人工核定的边（先修/易混/迷思概念）来自可版本化的策展源文件，不由脚本推断生成。
    curated_path = OUT / 'graph' / 'edges_curated.jsonl'
    if curated_path.exists():
        for e in rows(curated_path):
            kind = e.get('type')
            if kind not in {EDGE_PREREQ, 'confused_with', 'misconception_lead_to'}:
                raise ValueError('Unsupported curated edge type: ' + str(kind))
            for endpoint in (e['src'], e['dst']):
                if endpoint not in nodes:
                    raise ValueError('Curated edge endpoint missing: ' + endpoint)
            unsigned_claim = str(e.get('status') or e.get('review_status') or '') in {PREREQ_VERIFIED, 'approved', 'expert_reviewed'}
            if kind == EDGE_PREREQ and unsigned_claim and not (e.get('reviewed_by') or e.get('checked_by') or e.get('reviewer')):
                # 无审核人的 verified 不得进入正式学习路径：降级为候选、关闭生效标记，原始声明只留审计痕迹。
                merged = {**e, 'status': PREREQ_PENDING, 'review_status': PREREQ_PENDING,
                          'declared_status': e.get('status') or e.get('review_status'),
                          'claimed_rel': e.get('claimed_rel') or e.get('rel'),
                          'active': False, 'active_for_learning_path': False}
            else:
                merged = {**e}
            edge(merged['src'], merged['dst'], kind, **{k: v for k, v in merged.items() if k not in ('src', 'dst', 'type')})
    dangling = [e for e in edges if e['src'] not in nodes or e['dst'] not in nodes]
    if dangling:
        raise ValueError('Dangling graph endpoints: ' + str(dangling[:2]))
    for filename, records in [('nodes.jsonl', sorted(nodes.values(), key=lambda n: n['id'])), ('edges.jsonl', sorted(edges, key=lambda e: (e['src'], e['dst'], e['type'])))]:
        path = OUT / 'graph' / filename
        path.parent.mkdir(exist_ok=True)
        atomic_write(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    eight_layers = {
        'L0_standard_requirement': sum(1 for n in nodes.values() if n['layer'] == 'L0'),
        'L1_exam': sum(1 for n in nodes.values() if n['layer'] == 'L1'),
        'L2_module': sum(1 for n in nodes.values() if n['layer'] == 'L2'),
        'L3_competency_ability': sum(1 for n in nodes.values() if n['layer'] == 'L3'),
        'L4_knowledge_node': sum(1 for n in nodes.values() if n['layer'] == 'L4'),
        'L5_shared_material': sum(1 for n in nodes.values() if n['layer'] == 'L5'),
        'L6_question_rubric': sum(1 for n in nodes.values() if n['layer'] == 'L6'),
        'L7_learning_resource': sum(1 for n in nodes.values() if n['layer'] == 'L7'),
    }
    stats = {'nodes': len(nodes), 'edges': len(edges), 'by_layer': dict(Counter(n['layer'] for n in nodes.values())), 'by_type': dict(Counter(n['type'] for n in nodes.values())), 'eight_layer_hierarchy': eight_layers, 'by_edge_type': dict(Counter(e['type'] for e in edges)), 'files': ['graph/nodes.jsonl', 'graph/edges.jsonl', 'graph/edges_curated.jsonl'], 'note': 'layer 取值即规范 §3.2 的 L0-L7，无第二套编号；能力不隐式继承；先修候选未专家审核，不用于正式路径。'}
    manifest_path = OUT / 'MANIFEST.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['graph'] = stats
    manifest['eight_layer_hierarchy'] = eight_layers
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=1))
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == '__main__':
    build()
