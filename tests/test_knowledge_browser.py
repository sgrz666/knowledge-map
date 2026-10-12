from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.knowledge.repository import get_repository
from services.memory.agent import MemoryReviewAgent
from services.memory.store import InMemoryMasteryStore
from services.web.knowledge import KnowledgeBrowser, NodeRequest
from services.web.models import WebContext


def browser():
    repo = get_repository()
    return KnowledgeBrowser(SimpleNamespace(repo=repo, memory=MemoryReviewAgent(
        store=InMemoryMasteryStore(), repository=repo)))


def test_tree_scopes_and_does_not_invent_mastery():
    rows = browser().tree(WebContext(school_level='xiaoxue', subject='zonghe'))['nodes']
    assert rows and all(n['id'].startswith('ntce.xiaoxue.zonghe.') for n in rows)
    assert all(n['mastery'] is None for n in rows)
    ids = {n['id'] for n in rows}
    assert all(n['parent_id'] is None or n['parent_id'] in ids for n in rows)
    assert browser().tree(WebContext(trust_tier='published'))['nodes'] == []


def test_leaf_with_no_questions_has_draft_learning_material_and_real_sources():
    ctx = NodeRequest(node_id='ntce.chuzhong.lishi.s3.k01', school_level='chuzhong', subject='lishi')
    data = browser().detail(ctx)
    assert data['guide'] and len(data['guide']['self_checks']) >= 2
    assert data['sources'] and data['examples'] == []
    assert all(s['locator'] and s['text'] for s in data['sources'])
    with pytest.raises(HTTPException) as err:
        browser().detail(ctx.model_copy(update={'subject': 'wuli'}))
    assert err.value.status_code == 404


def test_cet_tree_keeps_nodes_without_question_bindings():
    rows = browser().tree(WebContext(exam_type='CET-4'))['nodes']
    assert rows and all(n['id'].startswith('cet4.') for n in rows)
    assert any(n['question_count'] == 0 for n in rows)


def test_requirement_counts_follow_the_clause_to_target_direction():
    """aligned_to_requirement 的方向是 条款 -> 考点：按 dst 反着筛会让每个考点的条数都成 0，
    考点页从此连不回考纲原文。计数必须与门面 helper 同口径，且未核对的条数要单独可见。"""
    from services.knowledge.graph_index import get_graph_index

    index = get_graph_index('ntce')
    tree = browser().tree(WebContext(exam_type='NTCE'))
    for row in tree['nodes']:
        links = index.requirement_links(row['id'])
        assert row['requirement_count'] == len(links), row['id']
        assert row['requirement_count_unreviewed'] == sum(1 for _, edge in links if not edge.get('verified'))
    assert any(row['requirement_count'] for row in tree['nodes']), \
        "所有考点的考纲条数都是 0：读边方向又反了，或者 helper 与浏览器再次分家"
    if any(row['requirement_count_unreviewed'] for row in tree['nodes']):
        assert any('未经教研核对' in notice for notice in tree['notices']), \
            "条数来自未核对的挂载边却不带口径说明"
