"""Scope-aware study browser over the existing graph, evidence and learner records."""
from collections import Counter

from fastapi import APIRouter, HTTPException
from pydantic import Field

from services.common.models import TrustTier
from services.knowledge.graph_index import MISCONCEPTION_EDGES, UNREVIEWED_MAPPING_NOTICE, get_graph_index
from services.knowledge.trust import TrustGate
from services.web.models import WebContext

RELATED_EDGE_TYPES = ("prerequisite_of",) + MISCONCEPTION_EDGES


class NodeRequest(WebContext):
    node_id: str = Field(min_length=1, max_length=200)


class KnowledgeBrowser:
    def __init__(self, workbench):
        self.workbench = workbench
        self.repo = workbench.repo

    def _index(self, ctx):
        return get_graph_index('ntce' if ctx.exam_type == 'NTCE' else 'cet')

    def _scope(self, ctx):
        library = 'ntce' if ctx.exam_type == 'NTCE' else 'cet'
        nodes, edges = self.repo.graph_records(library)
        prefix = ('ntce.' if ctx.exam_type == 'NTCE' else
                  ('cet4.' if ctx.exam_type == 'CET-4' else 'cet6.'))
        selected = {}
        for node in nodes:
            nid = node['id']
            if node.get('type') != 'knowledge_node' or not nid.startswith(prefix):
                continue
            if ctx.exam_type == 'NTCE':
                parts = nid.split('.')
                if ctx.school_level and parts[1] != ctx.school_level:
                    continue
                if ctx.subject and parts[2] != ctx.subject:
                    continue
            selected[nid] = node
        return selected, edges

    def tree(self, ctx):
        if ctx.trust_tier == TrustTier.PUBLISHED:
            return {'nodes': [], 'notices': ['当前没有已签署的学习内容。']}
        from services.knowledge.learning_resources import LearningResources
        selected, edges = self._scope(ctx)
        guides = {g['node_id'] for g in LearningResources(repository=self.repo).list_guides()}
        counts, usable = Counter(), Counter()
        gate = TrustGate(ctx.trust_tier.value)
        for meta in self.repo.find_questions(exams=ctx.exam_type, school_level=ctx.school_level,
                                             subject=ctx.subject):
            counts.update(meta.node_ids)
            if gate.classify_meta(meta).servable_in_paper and meta.has_answerable_text:
                usable.update(meta.node_ids)
        parents = {e['dst']: e['src'] for e in edges
                   if e.get('type') == 'has_child' and e['src'] in selected and e['dst'] in selected}
        children = Counter(parents.values())
        index = self._index(ctx)
        # 条款挂载走门面 helper：方向是 条款 -> 考点，自己按 dst 筛会得到全 0 的假口径。
        requirements = {nid: len(index.requirement_links(nid)) for nid in selected}
        requirements_unreviewed = {nid: sum(1 for _, edge in index.requirement_links(nid)
                                            if not edge.get('verified')) for nid in selected}
        rows = []
        for nid, node in sorted(selected.items()):
            mastery = self.workbench.memory.get_user_mastery(ctx.user_id, nid)
            rows.append({'id': nid, 'name': node.get('name') or node.get('title') or nid,
                         'parent_id': parents.get(nid), 'children_count': children[nid],
                         'description': node.get('description') or '', 'question_count': counts[nid],
                         'usable_question_count': usable[nid], 'requirement_count': requirements[nid],
                         'requirement_count_unreviewed': requirements_unreviewed[nid],
                         'guide_available': nid in guides,
                         'mastery': mastery.model_dump(mode='json') if mastery else None})
        notices = ['未作答的考点显示“未练习”；层级包含不等于已核定的先修关系。',
                   '题数为研究档文本题池口径；缺图等媒体限制在组卷时另行检查。']
        if any(row['requirement_count_unreviewed'] for row in rows):
            # 考点条数全部来自未核对的挂载边，光给一个数字会被读成"考纲已核定覆盖到这个考点"。
            notices.append(UNREVIEWED_MAPPING_NOTICE)
        return {'nodes': rows, 'notices': notices}

    def detail(self, ctx):
        if ctx.trust_tier == TrustTier.PUBLISHED:
            raise HTTPException(409, '当前没有已签署的学习内容')
        from services.knowledge.learning_resources import LearningResources
        selected, edges = self._scope(ctx)
        if ctx.node_id not in selected:
            raise HTTPException(404, '该知识点不在当前备考范围')
        node = selected[ctx.node_id]
        guide = LearningResources(repository=self.repo).get_guide(ctx.node_id)
        rids = [c['requirement_id'] for c in guide.get('citations', [])] if guide else []
        rids += [rid for rid, _ in self._index(ctx).requirement_links(ctx.node_id)]
        gate = TrustGate(ctx.trust_tier.value)
        sources = []
        for rid in dict.fromkeys(rids):
            record = self.repo.get_requirement(rid)
            if record and gate.classify_requirement(record).citable:
                sources.append({'id': rid, 'kind': 'requirement', 'title': record.get('content', '')[:100],
                                'text': record.get('content', ''), 'locator': record.get('locator'),
                                'standard_id': record.get('standard_id'), 'source_url': record.get('source_url')})
        candidates = [m for m in self.repo.find_questions(exams=ctx.exam_type, school_level=ctx.school_level,
                      subject=ctx.subject) if ctx.node_id in m.node_ids and gate.classify_meta(m).servable_in_paper]
        examples = []
        for m in candidates:
            # 卡片命中但题索引已无此题时跳过：出空题干卡只会让"请助手讲解此题"必然 404。
            record = self.repo.load_question(m.question_id)
            if not record:
                continue
            examples.append({'question_id': m.question_id, 'question_type': m.question_type,
                             'stem': (record.get('content') or {}).get('stem', ''),
                             'review_status': m.review_status})
            if len(examples) == 5:
                break
        related = [{'id': e['dst'] if e['src'] == ctx.node_id else e['src'], 'relation': e['type'],
                    'verified': bool(e.get('verified')), 'active_for_learning_path': bool(e.get('active_for_learning_path'))}
                   for e in edges if e.get('type') in ('prerequisite_of', 'confused_with', 'misconception_lead_to')
                   and (e['src'] == ctx.node_id or e['dst'] == ctx.node_id)]
        return {'node': node, 'guide': guide, 'sources': sources, 'examples': examples, 'related': related,
                'notices': ['研究草稿、自测参考要点与正式题库分别标识；自测不写入真实题目掌握度。']}


def build_router(workbench):
    router = APIRouter(prefix='/knowledge', tags=['知识点学习'])
    browser = KnowledgeBrowser(workbench)

    @router.post('/tree')
    def tree(ctx: WebContext):
        return browser.tree(ctx)

    @router.post('/node')
    def node(req: NodeRequest):
        return browser.detail(req)

    return router
