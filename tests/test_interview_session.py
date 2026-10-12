"""One durable interview training session built only from library scenario resources.

题面、追问依据与阶段任务都必须能回指库内资产；量规未签署时整场会话不出分数，这是验收重点。
"""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


PARTIAL_ANSWER = '我会先冷静下来，不在当众场合激化矛盾，然后把事情解释清楚。'
FULLER_ANSWER = ('先冷静客观地面对，换位思考理解家长和学生，私下充分沟通，'
                 '查明事实原委，协同商定对策，并长效跟踪防范复发。')
TRANSCRIPT = (
    '一、导入：同学们，今天我们先来看一段生活中的现象，请大家说说自己的经历。'
    '二、新授：我们围绕教学重难点展开，先自主朗读，再小组讨论，教师相机点拨。'
    '三、巩固：请大家完成练习题并互相交流思路。四、小结：请同学谈今天的收获。'
    '五、作业：课后观察身边的一个现象并写下记录。')
PLAN_TEXT = ('教学目标：知识与技能、过程与方法、情感态度与价值观三维目标。'
             '教学重点：理解概念的形成过程。教学难点：把概念用于解释新情境。'
             '教学过程：导入采用生活情境，新授安排自主探究与小组交流，'
             '巩固设计分层练习，小结由学生复述要点，作业布置实践任务。'
             '板书呈现知识结构，并预设学生错误与纠偏方式。')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_MAP_STATE_DIR', str(tmp_path))
    from services.web.service import Workbench
    from services.learning import build_router
    wb = Workbench()
    app = FastAPI()
    app.include_router(build_router(wb))
    scope = {'user_id': 'interview-' + uuid.uuid4().hex, 'exam_type': 'NTCE',
             'school_level': 'xiaoxue', 'subject': None, 'trust_tier': 'research_internal'}
    yield TestClient(app), wb, scope
    wb.store.db.close()


def post(client, path, body, *, expect=200):
    response = client.post('/learning/interview/' + path, json=body)
    assert response.status_code == expect, response.text
    return response.json()


def start(client, scope, request_id='start-1'):
    return post(client, 'session', {**scope, 'request_id': request_id})


def stage(session, key):
    return next(item for item in session['stages'] if item['key'] == key)


def qa_tasks(session):
    return stage(session, 'structured_qa')['tasks']


def answer(client, scope, session, task, text, request_id, duration=None):
    return post(client, 'session/answer', {**scope, 'session_id': session['session_id'],
        'task_id': task['task_id'], 'answer_text': text, 'request_id': request_id,
        **({'duration_seconds': duration} if duration else {})})


def stored_document(wb, scope, session_id):
    from services.web.models import WebContext
    return wb.learning.store.get(WebContext(**scope), 'interview', session_id)


def test_session_tasks_all_trace_back_to_library_assets(setup):
    client, wb, scope = setup
    from services.knowledge.learning_resources import LearningResources
    scenarios = {row['resource_id']: row for row in LearningResources(repository=wb.repo).list_scenarios('NTCE')}
    session = start(client, scope)
    assert session['status'] == 'in_progress' and session['completed_at'] is None
    assert [item['key'] for item in session['stages']] == ['structured_qa', 'trial_teaching', 'lesson_plan']
    document = stored_document(wb, scope, session['session_id'])
    stored = {item['task_id']: item for stage in document['stages'] for item in stage['tasks']}

    for task in qa_tasks(session):
        source = stored[task['task_id']]
        row = scenarios[source['evidence']['resource_id']]
        assert source['prompt'].split('。请现场作答')[0] in row['summary'], '题面必须是库内资源自己的话'
        assert source['reference_framework'], '参考框架应来自资源里的「」框架原文'
        assert source['evidence']['requirement_ids'], '面试题面要绑定权威条款'
        for rid in source['evidence']['requirement_ids']:
            assert wb.repo.get_requirement(rid), f'绑定的条款 {rid} 不在权威索引内'
        assert source['points'], '框架应能切出可比对的分步'
        assert all(point in row['summary'] for point in source['points']), '采分步只能是框架原文的片段'
        # 作答前不能透题：框架、切出的分步与未命中步骤都不出现在待作答任务里
        assert not {'points', 'missed_points', 'reference_framework', 'points_from'} & set(task)

    design = stage(session, 'lesson_plan')['tasks'][0]
    record = wb.repo.load_question(design['evidence']['question_id'])
    assert record and design['topic'] in (record['content']['stem'] or ''), '简案选题只能是库内题面'
    assert design['evidence']['review_status'] == (record.get('review') or {}).get('status')


def test_structured_answer_advances_through_one_grounded_follow_up(setup):
    client, wb, scope = setup
    session = start(client, scope)
    first = qa_tasks(session)[0]
    answered = answer(client, scope, session, first, PARTIAL_ANSWER, 'answer-1')
    task = next(item for item in qa_tasks(answered) if item['task_id'] == first['task_id'])

    assert task['state'] == 'awaiting_follow_up'
    assert task['feedback']['total_score'] is None and task['feedback']['score_basis'] == 'none'
    assert task['feedback']['rubric_signed'] is False
    assert task['feedback']['points'], '点级比对应逐条给出命中状态与重合表述'
    assert task['follow_up']['question'] and any(point in task['follow_up']['basis']
                                                 for point in task['points']), '追问要钉在框架的某一步上'
    done = answer(client, scope, answered, task, FULLER_ANSWER, 'answer-2')
    task = next(item for item in qa_tasks(done) if item['task_id'] == first['task_id'])
    assert task['state'] == 'done' and task['follow_up_answer'] == FULLER_ANSWER
    assert task['follow_up_feedback']['coverage_ratio'] > task['feedback']['coverage_ratio']
    assert done['answered_tasks'] == 1 and done['status'] == 'in_progress'


def test_full_session_completes_and_keeps_every_stage_evidence(setup):
    client, wb, scope = setup
    session = start(client, scope)
    for task in qa_tasks(session):
        session = answer(client, scope, session, task, PARTIAL_ANSWER, 'qa-' + task['task_id'])
        session = answer(client, scope, session, task, FULLER_ANSWER, 'follow-' + task['task_id'])
    session = answer(client, scope, session, stage(session, 'trial_teaching')['tasks'][0],
                     TRANSCRIPT, 'speech-1', duration=480)
    session = answer(client, scope, session, stage(session, 'lesson_plan')['tasks'][0], PLAN_TEXT, 'plan-1')

    assert session['status'] == 'completed' and session['completed_at']
    assert session['answered_tasks'] == session['total_tasks']
    assert all(item['completed'] for item in session['stages'])
    speech = stage(session, 'trial_teaching')['tasks'][0]
    assert speech['feedback']['measured']['words_per_minute'] > 0
    assert speech['feedback']['measured']['phase_coverage_rate'] > 0
    assert speech['feedback']['total_score'] is None and speech['feedback']['rubric_signed'] is False
    plan = stage(session, 'lesson_plan')['tasks'][0]
    assert plan['feedback']['dimensions'] and plan['feedback']['missed_elements'] is not None
    assert plan['feedback']['total_score'] is None and plan['feedback']['score_basis'] == 'none'
    # 整场会话不出通过概率，也不出正式分数
    assert 'pass_probability' not in str(session)
    assert all(item['feedback']['total_score'] is None for item in qa_tasks(session))

    restored = post(client, 'session/current', scope)['session']
    assert restored['session_id'] == session['session_id'] and restored['status'] == 'completed'
    assert restored['stages'] == session['stages']


def test_answer_retries_replay_and_changed_inputs_conflict_before_any_write(setup):
    client, wb, scope = setup
    session = start(client, scope)
    task = qa_tasks(session)[0]
    body = {**scope, 'session_id': session['session_id'], 'task_id': task['task_id'],
            'answer_text': PARTIAL_ANSWER, 'request_id': 'retry-1'}
    first = post(client, 'session/answer', body)
    replayed = post(client, 'session/answer', body)
    assert first == replayed, '同 request_id 同参数是重试：返回现状，不重复推进状态机'

    changed = {**body, 'answer_text': FULLER_ANSWER}
    post(client, 'session/answer', changed, expect=409)
    awaiting = next(item for item in qa_tasks(post(client, 'session/current', scope)['session'])
                    if item['task_id'] == task['task_id'])
    assert awaiting['state'] == 'awaiting_follow_up', '被拒的重试不能把任务推到追问之后的状态'
    assert awaiting['answer'] == PARTIAL_ANSWER, '同 request_id 改答案要在任何写入之前被拒，原作答不能被动过'
    assert post(client, 'session/current', scope)['session']['answered_tasks'] == 0

    # 换新 request_id 等于把这句话作为追问的回答：只填 follow_up_answer，第一次作答与追问依据都不重写
    follow = post(client, 'session/answer', {**body, 'request_id': 'retry-2'})
    done_task = next(item for item in qa_tasks(follow) if item['task_id'] == task['task_id'])
    assert done_task['state'] == 'done' and done_task['answer'] == PARTIAL_ANSWER
    assert done_task['follow_up_answer'] == PARTIAL_ANSWER and done_task['follow_up'] == awaiting['follow_up']
    post(client, 'session/answer', {**body, 'request_id': 'retry-3'}, expect=409)
    assert next(item for item in qa_tasks(post(client, 'session/current', scope)['session'])
                if item['task_id'] == task['task_id']) == done_task, '已完成任务再提交不能改动任何记录'

    other = qa_tasks(session)[1] if len(qa_tasks(session)) > 1 else stage(session, 'trial_teaching')['tasks'][0]
    post(client, 'session/answer', {**scope, 'session_id': 'interview-unknown', 'task_id': other['task_id'],
                                    'answer_text': PARTIAL_ANSWER, 'request_id': 'x-1'}, expect=404)
    post(client, 'session/answer', {**scope, 'session_id': session['session_id'], 'task_id': 'task-unknown',
                                    'answer_text': PARTIAL_ANSWER, 'request_id': 'x-2'}, expect=404)


def test_start_retry_issues_one_session_and_every_scope_dimension_stays_isolated(setup):
    client, wb, scope = setup
    session = start(client, scope, 'same-id')
    assert start(client, scope, 'same-id')['session_id'] == session['session_id'], '同 request_id 重试不能再开一场会话'
    documents = wb.learning.store.db.execute("SELECT COUNT(*) FROM learning_documents WHERE kind='interview'").fetchone()[0]
    assert documents == 1, '重放不能多写一份会话文档'
    for widened in ({**scope, 'user_id': 'other-' + uuid.uuid4().hex}, {**scope, 'school_level': 'chuzhong'},
                    {**scope, 'subject': 'yuwen'}):
        assert post(client, 'session/current', widened)['session'] is None, '换学习者、学段或科目都读不到别人的会话'
    assert start(client, {**scope, 'user_id': 'third-' + uuid.uuid4().hex}, 'same-id')['session_id'] != session['session_id']


def test_published_and_cet_scopes_never_fabricate_a_session(setup):
    client, wb, scope = setup
    post(client, 'session', {**scope, 'trust_tier': 'published', 'request_id': 'p-1'}, expect=409)
    assert post(client, 'session/current', {**scope, 'trust_tier': 'published'})['session'] is None
    response = client.post('/learning/interview/session',
                          json={**scope, 'exam_type': 'CET-4', 'school_level': None, 'request_id': 'c-1'})
    assert response.status_code == 409 and '面试' in response.json()['detail']
