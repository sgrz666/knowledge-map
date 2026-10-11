"""Reproducible NTCE completeness facts read exclusively through KnowledgeRepository."""
from collections import Counter, defaultdict
from services.knowledge.repository import get_repository
from services.knowledge.trust import TrustGate


def audit_ntce(repository=None):
    repo = repository or get_repository()
    gate = TrustGate('research_internal')
    groups = defaultdict(Counter)
    counts = Counter()
    used_nodes = set()
    for meta in repo.find_questions(exams='NTCE'):
        row = groups[(meta.school_level or 'unknown', meta.subject or 'unknown')]
        metrics = {
            'total': 1, 'usable': int(gate.classify_meta(meta).servable_in_paper and meta.has_answerable_text),
            'missing_knowledge': int(not meta.node_ids), 'missing_requirement': int(not meta.requirement_ids),
            'missing_answer': int(meta.answer_status == 'missing'),
            'answer_conflict': int(meta.answer_status == 'source_conflict'),
            'missing_stem': int(not meta.has_answerable_text),
            'signed_questions': int(meta.review_status in ('checked', 'expert_reviewed') and bool(
                ((repo.load_question(meta.question_id) or {}).get('review') or {}).get('checked_by'))),
        }
        counts.update(metrics)
        row.update(metrics)
        used_nodes.update(meta.node_ids)
    nodes, edges = repo.graph_records('ntce')
    knowledge = [n for n in nodes if n.get('type') == 'knowledge_node']
    specs = repo.paper_specs('NTCE')
    unpractised = sorted({n['id'] for n in knowledge} - used_nodes)
    requirements_by_node = defaultdict(list)
    for edge in edges:
        if edge.get('type') == 'aligned_to_requirement':
            requirements_by_node[edge['dst']].append(edge['src'])
    node_names = {n['id']: n.get('name') or n.get('title') or n['id'] for n in knowledge}
    parents = {e['src'] for e in edges if e.get('type') == 'has_child'}
    return {
        **dict(counts), 'knowledge_nodes': len(knowledge), 'used_knowledge_nodes': len(used_nodes),
        'unpractised_knowledge_nodes': len(unpractised),
        'unpractised_leaf_nodes': sum(nid not in parents for nid in unpractised),
        'unpractised_nodes': [{'id': nid, 'name': node_names[nid],
                              'is_leaf': nid not in parents,
                              'requirement_ids': sorted(requirements_by_node[nid])} for nid in unpractised],
        'graph_layers': dict(sorted(Counter(n.get('layer', 'unknown') for n in nodes).items())),
        'graph_edges': len(edges), 'materials': sum(n.get('type') == 'material' for n in nodes),
        'paper_specs': len(specs),
        'unsigned_rubrics': sum(not gate.classify_rubric(r).signed for r in repo.rubrics().values() if r.get('library') == 'ntce'),
        'scopes': [dict(school_level=k[0], subject=k[1], **v) for k, v in sorted(groups.items())],
        'notices': ['可练计数按研究档门禁和文本统计，不表示已由教研签署或配图、听力素材齐全；网页另行限制缺图题提交。',
                    '缺口是独立维度，可在同一题重复出现；不能相加当作缺题数。',
                    '缺失答案、来源冲突与人工审核无法由机器自动补成已核定。'],
    }
