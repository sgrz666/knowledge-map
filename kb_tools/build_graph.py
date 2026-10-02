# -*- coding: utf-8 -*-
"""按《应试考证功能设计与技术支撑》3.2/3.4 的层级标准构建知识图谱导出层。

L1 考试(exam) → L2 模块(module) → L3 知识点(knowledge_node,含先修关系)
  → L4 题目(question) → L5 掌握度(运行时按 用户×知识点 更新,不在静态库内)。
另含 3.4 图谱模型的支撑层:国家标准/考试大纲 → 素养目标 → 能力维度 → 知识点。

输出:
  教资KB/graph/nodes.jsonl  全部图节点(L1/L2/L3/L4 + 标准/素养/能力支撑层)
  教资KB/graph/edges.jsonl  全部图边(contains/has_child/prerequisite/supports/basis/tagged)

所有由本脚本生成的语义(先修顺序、能力映射、素养划分)均为建议稿,
verified=false,待教研审核;题目标签沿用 questions 内的 review.tagger。
"""
import json
import sys
from collections import Counter, defaultdict

from build_kb import OUT, out_file

sys.stdout.reconfigure(encoding='utf-8')

SUBJECT_CN = {'zonghe': '综合素质', 'baojiao': '保教知识与能力', 'jiaoxue': '教育教学知识与能力',
              'jiaoyuzhishi': '教育知识与能力', 'mianshi': '结构化面试',
              'jiaoyuxue': '教育学(省考)', 'jiaoyuxinlixue': '教育心理学(省考)',
              'yuwen': '语文', 'shuxue': '数学', 'yingyu': '英语', 'zhengzhi': '思想品德/思想政治',
              'lishi': '历史', 'dili': '地理', 'wuli': '物理', 'huaxue': '化学', 'shengwu': '生物',
              'meishu': '美术', 'yinyue': '音乐', 'tiyu': '体育与健康', 'xinxi': '信息技术'}

LEVEL_CN = {'youer': '幼儿园', 'xiaoxue': '小学', 'chuzhong': '初级中学', 'gaozhong': '高级中学',
            'zhongxue': '中学', 'zhongxiaoxue': '中小学'}

# 素养/能力层(建议稿,verified=false):依据文档 3.4 教资示例
ABILITY_MAP = [
    ('a1', '教育理论理解能力', ['教育基础', '学前教育原理', '教育心理学概述', '学习心理', '学生指导', '发展与教育']),
    ('a2', '教学设计能力', ['教学设计', '活动设计', '教育活动的组织与实施', '学科专业知识']),
    ('a3', '课堂组织与管理能力', ['班级管理', '游戏', '教学实施', '环境创设', '课堂']),
    ('a4', '学习评价能力', ['评价', '教学评价与反思', '教育评价', '诊断']),
    ('a5', '教育反思与职业道德能力', ['职业道德', '师德', '教学反思', '职业理念', '德育']),
]

WRITTEN_SUBJECTS = ('zonghe', 'baojiao', 'jiaoxue', 'jiaoyuzhishi')

_MODULE_KW_CACHE = {}


def _module_keywords(level, subject):
    """取该模块 L3 节点名称(用于能力映射),缓存"""
    key = (level, subject)
    if key in _MODULE_KW_CACHE:
        return _MODULE_KW_CACHE[key]
    kws = []
    p = out_file('outline', '%s.%s.json' % (level, subject))
    if p.exists():
        doc = json.loads(p.read_text(encoding='utf-8'))
        kws = [n['name'] for n in doc['nodes']]
    _MODULE_KW_CACHE[key] = kws
    return kws


def scan_modules():
    """从 questions 目录扫描 (level, subject) → 模块表与题量"""
    modules = {}
    q_count = Counter()
    for qf in OUT.glob('questions/*/*/*.jsonl'):
        level, subject = qf.parent.parent.name, qf.parent.name
        n = 0
        exam_sys = 'NTCE'
        for line in qf.open(encoding='utf-8'):
            r = json.loads(line)
            n += 1
            if n == 1:
                exam_sys = r['exam']
        q_count[(level, subject)] = n
        if subject in ('jiaoyuxue', 'jiaoyuxinlixue') or exam_sys == '省考':
            exam_id = 'shengkao'
            exam_name = '教师资格省考(四川/辽宁/江西)'
            prefix = 'shengkao'
        else:
            exam_id = 'ntce.' + level
            exam_name = 'NTCE-' + LEVEL_CN.get(level, level)
            prefix = 'ntce'
        modules[(level, subject)] = {
            'module_id': '%s.%s.%s' % (prefix, level, subject),
            'exam_id': exam_id, 'exam_name': exam_name,
            'name': SUBJECT_CN.get(subject, subject),
            'count': n,
        }
    return modules, q_count


def build():
    modules, q_count = scan_modules()
    nodes, edges = [], []
    node_ids = set()

    def node(nid, layer, ntype, name, **extra):
        if nid in node_ids:
            return
        node_ids.add(nid)
        n = {'id': nid, 'layer': layer, 'type': ntype, 'name': name}
        n.update(extra)
        nodes.append(n)

    def edge(src, dst, etype, **extra):
        e = {'src': src, 'dst': dst, 'type': etype}
        e.update(extra)
        edges.append(e)

    # ---- L1 考试 + 国家标准层 ----
    exams = {}
    for (level, subject), m in modules.items():
        exams.setdefault(m['exam_id'], m['exam_name'])
    for eid, name in sorted(exams.items()):
        node(eid, 'L1', 'exam', name, verified=True)
        if eid.startswith('ntce'):
            node('standard.' + eid, 'S1', 'standard', '《中小学教师资格考试标准(试行)》与相应学段各科考试大纲',
                 verified=False, note='国家层依据文件占位,待挂接官方原文')
        else:
            node('standard.' + eid, 'S1', 'standard', '省级教师资格考试实施方案(四川/辽宁/江西)', verified=False)
        edge('standard.' + eid, eid, 'basis')

    # ---- L2 模块 + L3 知识点(来自 outline/*.json,含先修链)----
    prereq_total = 0
    for (level, subject), m in sorted(modules.items()):
        mid = m['module_id']
        node(mid, 'L2', 'module', m['name'], exam=m['exam_id'], question_count=m['count'])
        edge(m['exam_id'], mid, 'contains')
        node('standard.%s' % mid, 'S1', 'standard', '《%s》考试大纲' % m['name'], verified=False)
        edge('standard.%s' % mid, mid, 'basis')
        outline_path = out_file('outline', '%s.%s.json' % (level, subject))
        tops = []
        if outline_path.exists():
            doc = json.loads(outline_path.read_text(encoding='utf-8'))
            for n in doc['nodes']:
                node(n['node_id'], 'L3', 'knowledge_node', n['name'],
                     module=mid, keywords=n.get('keywords', []), verified=False)
                if n.get('parent'):
                    edge(n['parent'], n['node_id'], 'has_child')
                else:
                    tops.append(n['node_id'])
            # 先修关系(建议稿):顶层知识点按大纲顺序成链
            for a, b in zip(tops, tops[1:]):
                edge(a, b, 'prerequisite', note='按大纲顺序建议的学习先后,待教研审核', verified=False)
                prereq_total += 1

    # ---- 素养/能力层(仅 NTCE 笔试科目,建议稿)----
    ab_total = 0
    for (level, subject), m in sorted(modules.items()):
        if m['exam_id'] == 'shengkao' or subject not in WRITTEN_SUBJECTS:
            continue
        lit = 'ntce.%s.literacy.s1' % level
        node(lit, 'S2', 'literacy', '教师专业素养', exam='ntce.%s' % level, verified=False,
             note='依据文档 3.4 教资示例,待教研审核')
        edge(lit, 'ntce.%s' % level, 'belongs_to')
        mod_kw = _module_keywords(level, subject)
        mod_nodes = [n for n in nodes if n.get('module') == m['module_id']]
        for aid, aname, hints in ABILITY_MAP:
            abid = 'ntce.%s.ability.%s' % (level, aid)
            node(abid, 'S2', 'ability', aname, exam='ntce.%s' % level, verified=False)
            edge(lit, abid, 'comprises')
            # 能力 → 其支撑的知识点(按知识点名称关键词匹配)
            for n in mod_nodes:
                if n['type'] == 'knowledge_node' and any(h in n['name'] for h in hints):
                    edge(abid, n['id'], 'supports', verified=False)
                    ab_total += 1

    # ---- L4 题目 + 挂载边 ----
    q_total = tag_total = 0
    for qf in sorted(OUT.glob('questions/*/*/*.jsonl')):
        level, subject = qf.parent.parent.name, qf.parent.name
        m = modules[(level, subject)]
        for line in qf.open(encoding='utf-8'):
            r = json.loads(line)
            qid = r['question_id']
            node(qid, 'L4', 'question', None,
                 module=m['module_id'], question_type=r['question_type'],
                 session=r['source']['session'], exam=r['exam'],
                 answer_status=r['content']['answer_status'],
                 review=r['review']['status'],
                 difficulty=r.get('difficulty'))
            edge(m['module_id'], qid, 'contains')
            q_total += 1
            for nid in r['knowledge_node_ids']:
                edge(nid, qid, 'tagged', tagger=r['review']['tagger'],
                     verified=(r['review']['tagger'] == 'expert'))
                tag_total += 1

    # ---- 落盘 ----
    out_file('graph').mkdir(exist_ok=True)
    ntext = '\n'.join(json.dumps(n, ensure_ascii=False) for n in nodes) + '\n'
    out_file('graph', 'nodes.jsonl').write_text(ntext, encoding='utf-8')
    etext = '\n'.join(json.dumps(e, ensure_ascii=False) for e in edges) + '\n'
    out_file('graph', 'edges.jsonl').write_text(etext, encoding='utf-8')

    stat = Counter(n['layer'] for n in nodes)
    etype = Counter(e['type'] for e in edges)
    print('节点 %d:%s' % (len(nodes), dict(sorted(stat.items()))))
    print('边 %d:%s' % (len(edges), dict(sorted(etype.items()))))
    print('其中先修边 %d,能力支撑边 %d,题目挂载边 %d' % (prereq_total, ab_total, tag_total))

    # MANIFEST 更新
    mf = out_file('MANIFEST.json')
    manifest = json.loads(mf.read_text(encoding='utf-8'))
    manifest['graph'] = {
        'standard': 'L1考试→L2模块→L3知识点(含先修)→L4题目;L5掌握度为运行时数据,按(用户,知识点)更新',
        'nodes': len(nodes), 'edges': len(edges),
        'by_layer': dict(sorted(stat.items())),
        'by_edge_type': dict(sorted(etype.items())),
        'files': ['graph/nodes.jsonl', 'graph/edges.jsonl'],
        'note': '先修关系/素养/能力层为建议稿(verified=false,待教研审核);题目标签沿用 review.tagger',
    }
    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print('MANIFEST.graph 已更新')


if __name__ == '__main__':
    build()
