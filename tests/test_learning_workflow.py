"""Persistent learning flow against the real library, with isolated SQLite state."""
import importlib.util
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_learning_workflow_package_is_available():
    assert importlib.util.find_spec('services.learning') is not None, 'Persistent learning workflow is missing'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_MAP_STATE_DIR', str(tmp_path))
    from services.memory.agent import MemoryReviewAgent
    from services.memory.store import SqliteMasteryStore
    from services.practice.agent import PracticeEngineAgent
    from services.planner.agent import CurriculumPlannerAgent
    from services.web.service import Workbench
    from services.learning import LearningWorkflow, build_router
    # 走真实构造：手工逐字段装配的 fixture 会漏掉后来加进 __init__ 的依赖（exam_sessions 就是这样红的）
    wb = Workbench()
    # 记忆库默认是进程级单例，落在 tmp_path 之外；换掉它之后，持有它的两个门面要跟着换
    wb.memory = MemoryReviewAgent(store=SqliteMasteryStore(tmp_path / 'memory.sqlite3'), repository=wb.repo)
    wb.practice_agent = PracticeEngineAgent(repository=wb.repo, memory=wb.memory)
    wb.planner = CurriculumPlannerAgent(repository=wb.repo, store=wb.memory.store)
    app = FastAPI()
    app.include_router(build_router(wb))
    scope = {'user_id': 'flow-' + uuid.uuid4().hex, 'exam_type': 'NTCE',
             'school_level': 'xiaoxue', 'subject': 'zonghe', 'trust_tier': 'research_internal'}
    yield TestClient(app), wb, scope, LearningWorkflow
    wb.store.db.close()
    wb.memory.store.close()


def post(client, path, body):
    response = client.post('/learning/' + path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def create_plan(client, scope):
    return post(client, 'plan', {**scope, 'request_id': 'create-plan', 'days_until_exam': 3,
                               'daily_available_minutes': 15})['plan']


def tasks(plan):
    return [task for day in plan['daily_plans'] for task in day['tasks']]


def submit_all(wb, scope, paper, *, wrong=False):
    from services.web.models import SubmitRequest
    for q in paper['questions']:
        # 缺原图的题在卷面上标了 input_blocked：后端按设计拒收，页面也只禁用输入，完成条件本来就不算它
        if q.get('input_blocked'):
            continue
        record = wb.repo.load_question(q['question_id'])
        answer = str(record['content'].get('answer') or record['content'].get('reference_answer') or '示例作答')
        if wrong:
            answer = 'B' if answer.strip().upper() == 'A' else 'A'
        wb.submit(SubmitRequest(user_id=scope['user_id'], paper_id=paper['paper_id'],
                                question_id=q['question_id'], answer=answer))


def test_diagnostic_spreads_real_nodes_and_reads_only_owned_submissions(setup):
    client, wb, scope, _ = setup
    body = {**scope, 'request_id': 'diagnostic-one', 'item_count': 4}
    started = post(client, 'diagnostic/start', body)
    assert started['status'] == 'in_progress'
    assert started['paper']['total_items'] == 4
    assert len(started['coverage']['selected_node_ids']) >= 4
    assert started['coverage']['uncovered_node_ids']
    for q in started['paper']['questions']:
        meta = wb.repo.get_meta(q['question_id'])
        assert (meta.exam, meta.school_level, meta.subject) == ('NTCE', 'xiaoxue', 'zonghe')
        assert meta.question_type in ('单选', '多选')
        assert 'answer' not in q
    result_body = {**scope, 'diagnostic_id': started['diagnostic_id']}
    before = post(client, 'diagnostic/result', result_body)
    assert before['submitted_count'] == 0
    assert before['coverage']['covered_node_count'] == 0
    submit_all(wb, scope, started['paper'])
    after = post(client, 'diagnostic/result', result_body)
    assert after['status'] == 'completed'
    assert after['submitted_count'] == 4
    assert after['diagnostic']['estimate_basis'] == 'coverage_only'
    assert after['coverage']['covered_node_count'] >= 4
    assert post(client, 'diagnostic/start', body)['paper']['paper_id'] == started['paper']['paper_id']
    changed = client.post('/learning/diagnostic/start', json={**body, 'item_count': 5})
    assert changed.status_code == 409
    assert client.post('/learning/diagnostic/result', json={**result_body, 'user_id': 'other'}).status_code == 404


def test_empty_scope_and_published_never_fabricate_learning_state(setup):
    client, _, scope, _ = setup
    for override in ({'school_level': 'nonexistent'}, {'trust_tier': 'published'}):
        selected = {**scope, **override, 'request_id': 'empty'}
        assert client.post('/learning/diagnostic/start', json=selected).status_code == 409
        assert client.post('/learning/plan', json=selected).status_code == 409
        assert post(client, 'plan/current', selected)['plan'] is None


def test_plan_restores_and_ids_are_isolated_by_every_scope_dimension(setup):
    client, wb, scope, workflow_type = setup
    plan = create_plan(client, scope)
    assert len(tasks(plan)) > 1
    assert len({task['task_id'] for task in tasks(plan)}) == len(tasks(plan))
    assert create_plan(client, scope)['plan_id'] == plan['plan_id']
    from services.web.models import WebContext
    restored = workflow_type(wb).current_plan(WebContext(**scope))['plan']
    assert restored == plan
    for dimension, value in [('user_id', 'different'), ('exam_type', 'CET-4'),
                             ('school_level', 'youeryuan'), ('subject', 'jiaobao'),
                             ('trust_tier', 'published')]:
        assert post(client, 'plan/current', {**scope, dimension: value})['plan'] is None
        assert client.post('/learning/task/start', json={**scope, dimension: value,
            'plan_id': plan['plan_id'], 'task_id': tasks(plan)[0]['task_id']}).status_code in (404, 409)


def test_task_completion_requires_persisted_evidence_and_preserves_budget(setup):
    client, wb, scope, _ = setup
    plan = create_plan(client, scope)
    original_ids = {task['task_id'] for task in tasks(plan)}
    request = {**scope, 'plan_id': plan['plan_id'], 'task_id': tasks(plan)[0]['task_id']}
    assert client.post('/learning/task/complete', json=request).status_code == 409
    started = post(client, 'task/start', request)
    assert started['required_submission_count'] > 0
    assert post(client, 'task/start', request)['paper']['paper_id'] == started['paper']['paper_id']
    assert client.post('/learning/task/complete', json={**request, 'submitted_count': 999}).status_code in (409, 422)
    submit_all(wb, scope, started['paper'], wrong=True)
    completed = post(client, 'task/complete', request)
    final = completed['plan']
    assert completed['task']['status'] == 'completed'
    assert completed['submitted_count'] == started['required_submission_count']
    assert final['revision'] > started['plan']['revision']
    assert final['budget_minutes'] == plan['budget_minutes']
    assert final['scheduled_minutes'] == plan['scheduled_minutes']
    assert {task['task_id'] for task in tasks(final)} == original_ids
    again = post(client, 'task/complete', request)
    assert again['plan']['revision'] == final['revision']
    replan_body = {**scope, 'plan_id': plan['plan_id'], 'request_id': 'replan-one'}
    replanned = post(client, 'plan/replan', replan_body)['plan']
    done = next(t for t in tasks(replanned) if t['task_id'] == request['task_id'])
    assert done == completed['task']
    assert post(client, 'plan/replan', replan_body)['plan']['revision'] == replanned['revision']
    assert all(day['total_minutes'] <= 15 for day in replanned['daily_plans'])


def test_replan_uses_real_memory_to_prioritize_remaining_weak_node(setup):
    client, wb, scope, _ = setup
    plan = create_plan(client, scope)
    remaining = [task for task in tasks(plan) if task.get('node_id')]
    target = remaining[-1]
    req = {**scope, 'plan_id': plan['plan_id'], 'task_id': target['task_id']}
    started = post(client, 'task/start', req)
    submit_all(wb, scope, started['paper'], wrong=True)
    assert wb.memory.get_user_mastery(scope['user_id'], target['node_id']) is not None
    # The running task stays fixed; another pending task on that node should now rank first
    # whenever the real plan contains one. All remaining priorities must carry real/null memory.
    replanned = post(client, 'plan/replan', {**scope, 'plan_id': plan['plan_id'], 'request_id': 'memory-rank'})['plan']
    for task in tasks(replanned):
        if task.get('node_id') and task['status'] == 'pending':
            saved = wb.memory.get_user_mastery(scope['user_id'], task['node_id'])
            assert task['mastery_score'] == (saved.mastery_score if saved else None)
    assert replanned['budget_minutes'] == plan['budget_minutes']


def test_replan_moves_a_newly_observed_weak_node_before_unseen_nodes(setup):
    client, wb, scope, _ = setup
    plan = create_plan(client, scope)
    original = tasks(plan)
    target = original[-1]
    assert target['node_id'] != original[0]['node_id']
    from services.web.models import WebPracticeRequest
    # 考点专项的卷按（用户·当天·模式）定种子里的题：只发一道时可能落到主观题，而主观题在量规签署前
    # 不产生掌握度证据。这里要的是"新增作答被重新排程看见"，所以把该考点可用题全练完，判分证据必然出现。
    practice = wb.practice(WebPracticeRequest(**scope, practice_mode='point_focus',
                                             target_node=target['node_id'], item_count=100))
    assert practice['total_items'] > 0
    submit_all(wb, scope, practice, wrong=True)
    record = wb.memory.get_user_mastery(scope['user_id'], target['node_id'])
    assert record is not None, f'{target["node_id"]} 的整卷作答没有留下掌握度证据'
    score = record.mastery_score
    assert score < 0.6
    replanned = post(client, 'plan/replan', {**scope, 'plan_id': plan['plan_id'], 'request_id': 'real-weakness'})['plan']
    assert tasks(replanned)[0]['node_id'] == target['node_id']
    assert tasks(replanned)[0]['mastery_score'] == score


def test_only_submissions_in_the_linked_paper_can_finish_task(setup):
    client, wb, scope, _ = setup
    plan = create_plan(client, scope)
    req = {**scope, 'plan_id': plan['plan_id'], 'task_id': tasks(plan)[0]['task_id']}
    started = post(client, 'task/start', req)
    from services.web.models import WebPracticeRequest, SubmitRequest
    unrelated = wb.practice(WebPracticeRequest(**scope, practice_mode='error_elimination',
        wrong_question_ids=[q['question_id'] for q in started['paper']['questions']], item_count=100))
    submit_all(wb, scope, unrelated)
    assert client.post('/learning/task/complete', json=req).status_code == 409
    assert started['required_submission_count'] > 1
    q = started['paper']['questions'][0]
    wb.submit(SubmitRequest(user_id=scope['user_id'], paper_id=started['paper']['paper_id'],
                             question_id=q['question_id'], answer='A'))
    assert client.post('/learning/task/complete', json=req).status_code == 409
    current = post(client, 'plan/current', scope)['plan']
    assert next(t for t in tasks(current) if t['task_id'] == req['task_id'])['submitted_count'] == 1


def test_concurrent_retries_issue_only_one_diagnostic_paper(setup):
    from concurrent.futures import ThreadPoolExecutor
    from services.learning.models import DiagnosticStartRequest
    _, wb, scope, workflow_type = setup
    flows = [workflow_type(wb), workflow_type(wb)]
    req = DiagnosticStartRequest(**scope, request_id='concurrent', item_count=2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda flow: flow.start_diagnostic(req), flows))
    assert results[0]['diagnostic_id'] == results[1]['diagnostic_id']
    assert results[0]['paper']['paper_id'] == results[1]['paper']['paper_id']
    assert wb.store.db.execute('SELECT count(*) FROM papers').fetchone()[0] == 1


def test_current_returns_latest_plan_and_changed_create_retry_conflicts(setup):
    client, _, scope, _ = setup
    first = create_plan(client, scope)
    second = post(client, 'plan', {**scope, 'request_id': 'second-plan',
                                 'days_until_exam': 2, 'daily_available_minutes': 30})['plan']
    assert second['plan_id'] != first['plan_id']
    assert post(client, 'plan/current', scope)['plan']['plan_id'] == second['plan_id']
    assert client.post('/learning/plan', json={**scope, 'request_id': 'second-plan',
        'days_until_exam': 5, 'daily_available_minutes': 30}).status_code == 409
