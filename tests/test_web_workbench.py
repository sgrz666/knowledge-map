"""User-visible web contracts over the actual library, with an isolated learner."""
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from services.app import app

client = TestClient(app)


def test_web_entry_and_bootstrap():
    assert client.get('/').status_code == 200
    data = client.get('/api/v1/web/bootstrap').json()
    assert data['defaults']['model']
    assert data['defaults']['base_url'] == 'https://api.deepseek.com'
    assert data['library']['total'] == 14500
    assert data['library']['missing_knowledge'] == 1331
    assert data['library']['signed_questions'] == 0
    assert data['scopes']
    assert len(data['library']['unpractised_nodes']) == 160
    assert data['cet_nodes']


def test_web_requires_runtime_token():
    with patch.dict('os.environ', {'KNOWLEDGE_MAP_RUNTIME_TOKEN': 'web-test-token'}):
        assert client.get('/api/v1/web/bootstrap').status_code == 401
        assert client.get('/api/v1/web/bootstrap', headers={'Authorization': 'Bearer web-test-token'}).status_code == 200


def test_scoped_paper_submission_is_idempotent_and_library_owned():
    from services.knowledge.repository import get_repository
    from services.knowledge.trust import TrustGate
    repo = get_repository()
    ids = [m.question_id for m in repo.find_questions(exams='NTCE', school_level='xiaoxue',
           subject='zonghe', require_nodes=True, require_answer=True, question_types=['单选'])
           if TrustGate('research_internal').classify_meta(m).servable_in_paper
           and not repo.has_unavailable_figure(m.question_id)][:2]
    user = 'web-test-' + uuid.uuid4().hex
    result = client.post('/api/v1/web/practice', json={
        'user_id': user, 'exam_type': 'NTCE', 'practice_mode': 'error_elimination', 'wrong_question_ids': ids,
        'school_level': 'xiaoxue', 'subject': 'zonghe', 'item_count': 2,
    })
    assert result.status_code == 200, result.text
    paper = result.json()
    assert paper['total_items'] == 2
    assert all('answer' not in q for q in paper['questions'])
    assert all(q['question_id'].startswith('ntce.xiaoxue.zonghe.') for q in paper['questions'])
    q = paper['questions'][0]
    body = {'user_id': user, 'paper_id': paper['paper_id'], 'question_id': q['question_id'],
            'answer': 'A', 'time_spent_seconds': 20}
    response = client.post('/api/v1/web/submit', json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert 'verdict_source' in data
    assert data['review']['attributable']
    again = client.post('/api/v1/web/submit', json=body)
    assert again.status_code == 200
    assert again.json() == data
    assert client.post('/api/v1/web/submit', json={**body, 'user_id': user + '-other'}).status_code == 404
    assert client.post('/api/v1/web/submit', json={**body, 'question_id': 'not-in-paper'}).status_code == 400


def test_config_key_is_not_returned_or_shared():
    from services.llm.client import ProviderResponse
    def generate(provider, messages, **kwargs):
        assert provider.api_key == 'private-test-key'
        return ProviderResponse(text='{"reply":"连接成功","citation_ids":[]}', model=provider.model)
    with patch('services.llm.client.OpenAICompatibleProvider.generate', generate):
        response = client.post('/api/v1/web/model/test', json={
            'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash', 'api_key': 'private-test-key'})
    assert response.status_code == 200, response.text
    assert response.json()['ok']
    assert 'private-test-key' not in response.text
    assert client.get('/api/v1/health?probe=false').json()['llm_mode'] == 'rule_only'


def test_published_is_empty_and_bad_scope_does_not_fall_back():
    for scope in ({'trust_tier': 'published'}, {'school_level': 'nonexistent'}):
        response = client.post('/api/v1/web/practice', json={
            'user_id': 'web-test-empty', 'exam_type': 'NTCE',
            'practice_mode': 'daily_practice', 'item_count': 2, **scope})
        assert response.status_code == 200, response.text
        assert response.json()['total_items'] == 0


def test_rule_chat_and_scoped_plan():
    response = client.post('/api/v1/web/chat', json={
        'user_id': 'web-test-chat', 'message': '什么是因材施教', 'exam_type': 'NTCE',
        'school_level': 'xiaoxue', 'subject': 'zonghe'})
    assert response.status_code == 200, response.text
    assert response.json()['model']['mode'] == 'rule_only'
    assert response.json()['sources']
    assert '因材施教' in response.json()['reply']
    response = client.post('/api/v1/planner/generate', json={
        'user_id': 'web-test-plan', 'exam_type': 'NTCE', 'days_until_exam': 2,
        'school_level': 'xiaoxue', 'subject': 'zonghe'})
    assert response.status_code == 200, response.text
    nodes = [t['node_id'] for d in response.json()['daily_plans'] for t in d['tasks'] if t.get('node_id')]
    assert nodes and all(n.startswith('ntce.xiaoxue.zonghe.') for n in nodes)


def test_provider_failure_and_out_of_scope_citations_are_explicit():
    from services.llm.client import LLMUnavailableError, ProviderResponse
    body = {'user_id': 'web-llm-guard', 'message': '什么是因材施教',
            'model_config_input': {'api_key': 'guard-test-key'}}
    with patch('services.llm.client.OpenAICompatibleProvider.generate', side_effect=LLMUnavailableError('连接失败 guard-test-key')):
        response = client.post('/api/v1/web/chat', json=body)
    assert response.status_code == 200
    assert not response.json()['model']['ok']
    assert 'guard-test-key' not in response.text
    with patch('services.llm.client.OpenAICompatibleProvider.generate', return_value=ProviderResponse(
        text='{"reply":"错误的引用","citation_ids":["made-up-source"]}', model='test')):
        response = client.post('/api/v1/web/chat', json=body)
    assert not response.json()['model']['ok']
    assert response.json()['reply'] != '错误的引用'


def test_published_chat_never_calls_model_without_signed_evidence():
    with patch('services.llm.client.OpenAICompatibleProvider.generate') as model:
        response = client.post('/api/v1/web/chat', json={
            'user_id': 'web-published', 'trust_tier': 'published', 'message': '什么是因材施教',
            'model_config_input': {'api_key': 'should-not-be-used'}})
    assert response.status_code == 200
    model.assert_not_called()
    assert response.json()['sources'] == []


def test_invalid_model_config_never_echoes_a_key():
    response = client.post('/api/v1/web/model/test', json={
        'base_url': 'http://127.0.0.1:8000', 'api_key': 'invalid-config-secret'})
    assert response.status_code == 422
    assert 'invalid-config-secret' not in response.text


def test_all_ntce_specs_match_new_schema():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    from services.knowledge.repository import get_repository
    repo = get_repository()
    schema = json.loads((repo.root / '数据集/教资/schemas/paper_spec.json').read_text(encoding='utf-8'))
    validator = Draft202012Validator(schema)
    specs = repo.paper_specs('NTCE')
    assert len(specs) == 32
    for spec in specs:
        assert list(validator.iter_errors(spec)) == []


def test_missing_figure_submission_is_refused():
    from services.web.service import Workbench
    from services.web.models import SubmitRequest
    from services.knowledge.repository import get_repository
    from fastapi import HTTPException
    import pytest
    repo = get_repository()
    qid = next(m.question_id for m in repo.find_questions(exams='NTCE', require_answer=True)
               if repo.has_unavailable_figure(m.question_id))
    workbench = Workbench()
    user = 'web-figure-' + uuid.uuid4().hex
    paper = 'figure-' + uuid.uuid4().hex
    workbench.store.save_paper(user, {'paper_id': paper, 'trust_tier': 'research_internal',
                                    'exam_type': 'NTCE', 'questions': [{'question_id': qid}]})
    with pytest.raises(HTTPException) as exc:
        workbench.submit(SubmitRequest(user_id=user, paper_id=paper, question_id=qid, answer='A'))
    assert exc.value.status_code == 409
    assert workbench.store.submission(paper, qid) is None


def test_plan_due_reviews_stay_in_selected_scope():
    from services.planner.scheduler import AdaptiveScheduler
    from services.knowledge.repository import get_repository
    repo = get_repository()
    other = next(repo.find_questions(exams='CET-4')).question_id
    class Store:
        def weak_node_ids(self, *args, **kwargs): return []
        def due_question_ids(self, *args, **kwargs): return [other]
    days, _, _ = AdaptiveScheduler(repository=repo, store=Store()).schedule(
        user_id='scoped-review', exam='NTCE', days=1, daily_minutes=60,
        school_level='xiaoxue', subject='zonghe')
    assert days
    assert not any(t.task_type == 'fsrs_review' for day in days for t in day.tasks)

    ntce = next(repo.find_questions(exams='NTCE')).question_id
    class CrossExamStore(Store):
        def due_question_ids(self, *args, **kwargs): return [ntce]
    days, _, _ = AdaptiveScheduler(repository=repo, store=CrossExamStore()).schedule(
        user_id='cet-review', exam='CET-4', days=1, daily_minutes=60)
    assert not any(t.task_type == 'fsrs_review' for day in days for t in day.tasks)


def test_multinode_submission_counts_one_attempt_and_keeps_all_mastery():
    from services.web.service import Workbench
    from services.web.models import SubmitRequest
    from services.knowledge.repository import get_repository
    from services.knowledge.trust import TrustGate
    repo = get_repository()
    q = next(m for m in repo.find_questions(exams='NTCE', require_nodes=True, require_answer=True,
               question_types=['单选']) if len(m.node_ids) > 1
               and TrustGate('research_internal').classify_meta(m).servable_in_paper
               and not repo.has_unavailable_figure(m.question_id))
    workbench = Workbench()
    user = 'web-multinode-' + uuid.uuid4().hex
    paper = 'multinode-' + uuid.uuid4().hex
    workbench.store.save_paper(user, {'paper_id': paper, 'trust_tier': 'research_internal',
                                    'exam_type': 'NTCE', 'questions': [{'question_id': q.question_id}]})
    import pytest
    req = SubmitRequest(user_id=user, paper_id=paper, question_id=q.question_id, answer='Z')
    with patch.object(workbench.store, 'save_submission', side_effect=OSError('simulated disk failure')):
        with pytest.raises(OSError):
            workbench.submit(req)
    from fastapi import HTTPException
    for changed in ({'answer': 'A'}, {'time_spent_seconds': 20}, {'option_flip_count': 2}):
        with pytest.raises(HTTPException) as conflict:
            workbench.submit(req.model_copy(update=changed))
        assert conflict.value.status_code == 409
        assert workbench.store.submission(paper, q.question_id) is None
    data = workbench.submit(req)
    assert not data['is_correct']
    log = next(e for e in workbench.memory.store.error_entries(user) if e['question_id'] == q.question_id)
    assert log['incorrect_count'] == 1
    assert all(workbench.memory.get_user_mastery(user, n).practice_count == 1 for n in q.node_ids)


def test_saved_submission_replays_only_that_exact_attempt():
    from services.web.service import Workbench
    from services.web.models import SubmitRequest
    from services.knowledge.repository import get_repository
    from services.knowledge.trust import TrustGate
    from fastapi import HTTPException
    import pytest
    repo = get_repository()
    q = next(m for m in repo.find_questions(exams='NTCE', require_nodes=True, require_answer=True,
               question_types=['单选'])
               if TrustGate('research_internal').classify_meta(m).servable_in_paper
               and not repo.has_unavailable_figure(m.question_id))
    workbench = Workbench()
    user = 'web-retry-' + uuid.uuid4().hex
    paper = 'retry-' + uuid.uuid4().hex
    workbench.store.save_paper(user, {'paper_id': paper, 'trust_tier': 'research_internal',
                                      'exam_type': 'NTCE', 'questions': [{'question_id': q.question_id}]})
    req = SubmitRequest(user_id=user, paper_id=paper, question_id=q.question_id, answer='Z')
    data = workbench.submit(req)
    assert workbench.submit(req) == data
    node = q.node_ids[0]
    before = workbench.memory.get_user_mastery(user, node).practice_count
    with pytest.raises(HTTPException) as changed:
        workbench.submit(req.model_copy(update={'answer': 'A'}))
    assert changed.value.status_code == 409
    assert workbench.memory.get_user_mastery(user, node).practice_count == before
    # 指纹上线前存下的提交没有指纹：没有东西能证明这次请求就是第一次那次作答，回放和重写都不做
    legacy = 'legacy-' + uuid.uuid4().hex
    workbench.store.save_paper(user, {'paper_id': legacy, 'trust_tier': 'research_internal',
                                      'exam_type': 'NTCE', 'questions': [{'question_id': q.question_id}]})
    workbench.store.save_submission(legacy, q.question_id, {'paper_id': legacy, 'question_id': q.question_id})
    with pytest.raises(HTTPException) as old_row:
        workbench.submit(req.model_copy(update={'paper_id': legacy}))
    assert old_row.value.status_code == 409


def test_published_context_does_not_resume_or_submit_a_research_paper():
    user = 'web-resume-tier-' + uuid.uuid4().hex
    paper = client.post('/api/v1/web/practice', json={'user_id': user, 'exam_type': 'NTCE',
            'school_level': 'xiaoxue', 'subject': 'zonghe', 'practice_mode': 'daily_practice', 'item_count': 1}).json()
    profile = client.post('/api/v1/web/profile', json={'user_id': user, 'trust_tier': 'published'}).json()
    assert profile['latest_paper'] is None
    assert profile['submissions'] == []
    body = {'user_id': user, 'paper_id': paper['paper_id'], 'question_id': paper['questions'][0]['question_id'],
            'answer': 'A', 'trust_tier': 'published'}
    assert client.post('/api/v1/web/submit', json=body).status_code == 409


def test_cet_passages_and_attempt_specific_resume():
    from services.web.store import WorkbenchStore
    from services.knowledge.repository import get_repository
    import tempfile
    from pathlib import Path
    repo = get_repository()
    qid = next(m.question_id for m in repo.find_questions(exams='CET-4')
               if repo.reading_passage(m.question_id))
    assert repo.reading_passage(qid)['text']
    with tempfile.TemporaryDirectory() as folder:
        store = WorkbenchStore(Path(folder) / 'test.sqlite3')
        store.save_paper('learner', {'paper_id': 'first'})
        store.save_paper('learner', {'paper_id': 'second'})
        store.save_submission('first', qid, {'question_id': qid, 'is_correct': True})
        assert store.paper_submissions('second') == []
        assert len(store.paper_submissions('first')) == 1
        store.db.close()


def test_model_guard_checks_the_endpoint_it_will_actually_dial():
    """代理在场时 fake-ip 解析出的占位地址不是要连的对端，拿它判公网会误拒真实连接。"""
    import json as _json
    from services.llm.client import LLMUnavailableError
    from services.web.provider import PrivateProvider

    provider = PrivateProvider('https://api.deepseek.com', 'private-test-key', 'deepseek-flash', timeout=5)
    canned = _json.dumps({'choices': [{'message': {'content': '{}'}}]}).encode('utf-8')
    fake_ip = [(2, 1, 6, '', ('198.18.0.253', 443))]
    public_ip = [(2, 1, 6, '', ('1.1.1.1', 443))]

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _limit=-1):
            return canned

    def dial(rows, proxies, bypassed):
        with patch('services.web.provider.socket.getaddrinfo', return_value=rows), \
             patch('services.web.provider.urllib.request.getproxies', return_value=proxies), \
             patch('services.web.provider.urllib.request.proxy_bypass', return_value=bypassed), \
             patch('services.web.provider.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = _Response()
            try:
                provider._post({'model': 'deepseek-flash'})
            except LLMUnavailableError as refused:
                return 'refused', str(refused)
            return 'dialed', opener.return_value.open.call_args[0][0].full_url

    assert dial(fake_ip, {}, False)[0] == 'refused'
    assert '198.18.0.253' in dial(fake_ip, {}, False)[1]
    # 免代理名单命中时仍按直连判：代理不在场，解析结果才是要连的对端
    assert dial(fake_ip, {'https': 'http://127.0.0.1:17899'}, True)[0] == 'refused'
    assert dial(public_ip, {}, False)[0] == 'dialed'
    carried = dial(fake_ip, {'https': 'http://127.0.0.1:17899'}, False)
    assert carried[0] == 'dialed' and carried[1] == 'https://api.deepseek.com/chat/completions'


def test_chat_shows_the_route_and_the_gate_it_actually_walked():
    """思考过程里每一步都必须是这一轮工具真正算出来的事实，不是模型的独白。"""
    data = client.post('/api/v1/web/chat', json={'user_id': 'web-test-trace', 'message': '什么是因材施教',
        'exam_type': 'NTCE', 'school_level': 'xiaoxue', 'subject': 'zonghe'}).json()
    actions = [row['action'] for row in data['trace']]
    assert actions[0] == '判定意图' and actions[-1] == '定稿'
    for required in ('划定范围', '向量召回 + 可信门禁', '按当前科目收窄', '锚定考点与考纲条款', '请求模型并校验引用'):
        assert required in actions
    assert all(row['detail'] for row in data['trace'])
    assert '什么是' in data['trace'][0]['detail']
    recall = next(row for row in data['trace'] if row['action'] == '向量召回 + 可信门禁')
    assert recall['data']['candidate_count'] >= len([s for s in data['sources'] if s['kind'] == 'question'])
    model_step = next(row for row in data['trace'] if row['action'] == '请求模型并校验引用')
    assert model_step['data']['mode'] == 'rule_only'


def test_practice_from_chat_rotates_and_avoids_the_previous_batch():
    user = 'web-test-rotate-' + uuid.uuid4().hex
    base = {'user_id': user, 'message': '刷题', 'exam_type': 'NTCE', 'school_level': 'xiaoxue', 'subject': 'zonghe'}
    first = client.post('/api/v1/web/chat', json={**base, 'action_payload': {
        'practice_mode': 'daily_practice', 'item_count': 5, 'rotation': 0}}).json()
    replay = client.post('/api/v1/web/chat', json={**base, 'action_payload': {
        'practice_mode': 'daily_practice', 'item_count': 5, 'rotation': 0}}).json()
    previous = {q['question_id'] for q in first['tool_result']['questions']}
    second = client.post('/api/v1/web/chat', json={**base, 'action_payload': {
        'practice_mode': 'daily_practice', 'item_count': 5, 'rotation': 1,
        'avoid_question_ids': sorted(previous)}}).json()
    assert first['tool_result']['selection_seed'].endswith('|0')
    assert second['tool_result']['selection_seed'].endswith('|1')
    assert {q['question_id'] for q in replay['tool_result']['questions']} == previous
    assert not {q['question_id'] for q in second['tool_result']['questions']} & previous
    assert '已避开上一批' in ' '.join(second['tool_result']['notices'])
    assert '这一批题的来路' in [row['action'] for row in second['trace']]


def test_out_of_range_chat_payload_degrades_instead_of_500():
    response = client.post('/api/v1/web/chat', json={'user_id': 'web-test-bounds', 'message': '刷题',
        'exam_type': 'NTCE', 'school_level': 'xiaoxue', 'subject': 'zonghe',
        'action_payload': {'practice_mode': '不存在的模式', 'item_count': 99999, 'rotation': -5}})
    assert response.status_code == 200, response.text
    step = next(row for row in response.json()['trace'] if row['action'] == '按请求组卷')
    assert '不在库内模式之中' in step['detail']
    assert step['data']['practice_mode'] == 'daily_practice' and step['data']['rotation'] == 0
    assert step['data']['item_count'] == 100


def test_chat_plan_is_idempotent_per_utterance():
    user = 'web-test-chatplan-' + uuid.uuid4().hex
    body = {'user_id': user, 'message': '帮我规划一下备考', 'exam_type': 'NTCE', 'session_id': 'chat-plan-1',
            'school_level': 'xiaoxue', 'subject': 'zonghe',
            'action_payload': {'days_until_exam': 9, 'daily_available_minutes': 45}}
    first = client.post('/api/v1/web/chat', json=body).json()
    second = client.post('/api/v1/web/chat', json=body).json()
    assert first['tool_result']['total_days'] == 9 and first['tool_result']['daily_available_minutes'] == 45
    assert first['tool_result']['plan_id'] == second['tool_result']['plan_id']


def test_concept_anchor_survives_the_sentence_wrapping_the_ui_suggests():
    user = 'web-test-anchor-' + uuid.uuid4().hex
    body = {'user_id': user, 'exam_type': 'NTCE', 'school_level': 'xiaoxue', 'subject': 'zonghe'}
    # 知识点页的"请助手讲解"就是把考点名裹进这样一句诉求里发出去的：整句话不能让考点锚定落空。
    wrapped = client.post('/api/v1/web/chat', json={**body,
        'message': '请解释教师职业道德规范，并说明作答思路'}).json()
    bare = client.post('/api/v1/web/chat', json={**body, 'message': '教师职业道德规范'}).json()
    step = next(row for row in wrapped['trace'] if row['action'] == '锚定考点与考纲条款')
    bare_step = next(row for row in bare['trace'] if row['action'] == '锚定考点与考纲条款')
    assert step['data']['core'] == '教师职业道德规范'
    assert step['data']['matched_nodes'], '逗号后面的诉求把考点名污染成整句话时，锚定就空了'
    assert step['data']['matched_nodes'] == bare_step['data']['matched_nodes']


def test_concept_answer_attaches_node_questions_without_giving_the_answer_away():
    from services.knowledge.repository import get_repository
    from services.knowledge.trust import TrustGate
    repo, gate = get_repository(), TrustGate('research_internal')
    metas = [m for m in repo.find_questions(exams='NTCE', school_level='xiaoxue', subject='zonghe',
             require_nodes=True, require_answer=True)
             if gate.classify_meta(m).servable_in_paper and not repo.has_unavailable_figure(m.question_id)]
    node = metas[0].node_ids[0]
    user = 'web-test-related-' + uuid.uuid4().hex
    body = {'user_id': user, 'message': '请解释这个考点', 'exam_type': 'NTCE',
            'school_level': 'xiaoxue', 'subject': 'zonghe', 'action_payload': {'node_id': node}}
    before = client.post('/api/v1/web/chat', json=body).json()
    rows = before['sources'] + before['related_questions']
    asked = [row for row in rows if row['kind'] == 'question']
    assert asked and any(node in row.get('matched_nodes', []) for row in before['related_questions'])
    # 附真题是为了练：没答过的题只主题面、卷面与考点名，答案与解析都不出现在响应里。
    assert all('answer' not in row and 'explanation' not in row for row in asked)
    assert all(row.get('answer_withheld') for row in asked)
    assert all(row['node_names'] for row in asked)

    qid = asked[0]['id']
    # 走学习者真实的路径作答（组卷 → 提交），不要另开一个 Workbench 连接写库：
    # 应用进程读写走它自己那条连接，测试连接上的提交它看不见，答案解锁就验不真。
    paper = client.post('/api/v1/web/practice', json={
        'user_id': user, 'exam_type': 'NTCE', 'school_level': 'xiaoxue', 'subject': 'zonghe',
        'practice_mode': 'error_elimination', 'wrong_question_ids': [qid], 'item_count': 1}).json()
    submitted = client.post('/api/v1/web/submit', json={
        'user_id': user, 'paper_id': paper['paper_id'], 'question_id': qid, 'answer': 'A',
        'time_spent_seconds': 20})
    assert submitted.status_code == 200, submitted.text
    after = client.post('/api/v1/web/chat', json=body).json()
    row = next(r for r in after['sources'] + after['related_questions'] if r['id'] == qid)
    assert 'answer' in row and not row.get('answer_withheld')


def test_state_conflicts_carry_a_code_the_front_end_can_act_on():
    user = 'web-test-code-' + uuid.uuid4().hex
    paper = client.post('/api/v1/web/practice', json={'user_id': user, 'exam_type': 'NTCE',
        'school_level': 'xiaoxue', 'subject': 'zonghe', 'practice_mode': 'daily_practice', 'item_count': 1}).json()
    body = {'user_id': user, 'paper_id': paper['paper_id'], 'question_id': paper['questions'][0]['question_id'],
            'answer': 'A', 'trust_tier': 'published'}
    response = client.post('/api/v1/web/submit', json=body)
    assert response.status_code == 409
    detail = response.json()['detail']
    assert detail['code'] == 'paper_tier_mismatch' and detail['message']


def _servable_single_choice():
    from services.knowledge.repository import get_repository
    from services.knowledge.trust import TrustGate
    repo, gate = get_repository(), TrustGate('research_internal')
    return repo, next(m for m in repo.find_questions(exams='NTCE', school_level='xiaoxue', subject='zonghe',
        require_nodes=True, require_answer=True, question_types=['单选'])
        if gate.classify_meta(m).servable_in_paper and not repo.has_unavailable_figure(m.question_id))


def test_chat_about_an_unanswered_question_hints_instead_of_revealing():
    repo, meta = _servable_single_choice()
    qid = meta.question_id
    letter = ((repo.load_question(qid) or {}).get('content') or {}).get('answer')
    assert letter
    user = 'web-test-qa-' + uuid.uuid4().hex
    scope = {'user_id': user, 'exam_type': 'NTCE', 'school_level': 'xiaoxue', 'subject': 'zonghe'}
    body = {**scope, 'message': '请结合这道题讲解考点与作答依据。', 'question_id': qid}
    before = client.post('/api/v1/web/chat', json=body).json()
    # 页面在来源那一栏写着"这道题你还没作答"，答疑链路就不能在同一轮把参考答案说出来。
    assert before['tool_result'].get('hint_turn') == 1
    assert 'explanation_summary' not in before['tool_result']
    assert 'option_discrimination' not in before['tool_result']
    assert 'answer' not in before['tool_result']['question']
    assert '参考答案' not in before['reply']
    assert any('还没作答' in n for n in before['notices'])
    paper = client.post('/api/v1/web/practice', json={**scope, 'practice_mode': 'error_elimination',
        'wrong_question_ids': [qid], 'item_count': 1}).json()
    assert client.post('/api/v1/web/submit', json={**scope, 'paper_id': paper['paper_id'],
        'question_id': qid, 'answer': 'A', 'time_spent_seconds': 20}).status_code == 200
    after = client.post('/api/v1/web/chat', json=body).json()
    assert after['tool_result']['question']['answer'] == letter
    assert after['tool_result'].get('explanation_summary')


def test_node_payload_with_an_interview_keyword_still_answers_the_concept():
    user = 'web-test-node-intent-' + uuid.uuid4().hex
    # 库内真有叫"教学设计"的考点，知识点页那句"请解释教学设计…"会被面试关键词抢走。
    data = client.post('/api/v1/web/chat', json={'user_id': user, 'exam_type': 'NTCE',
        'school_level': 'chuzhong', 'subject': 'lishi', 'message': '请解释教学设计，结合学科情境说明作答思路。',
        'action_payload': {'node_id': 'ntce.chuzhong.lishi.s3'}}).json()
    assert data['intent'] == 'general_chat'
    assert 'related_questions' in data
    step = next(row for row in data['trace'] if row['action'] == '判定意图')
    assert '不进 interview_practice' in step['detail']


def test_practice_response_carries_the_node_the_paper_was_built_for():
    _, meta = _servable_single_choice()
    node = meta.node_ids[0]
    user = 'web-test-node-paper-' + uuid.uuid4().hex
    paper = client.post('/api/v1/web/practice', json={'user_id': user, 'exam_type': 'NTCE',
        'school_level': 'xiaoxue', 'subject': 'zonghe', 'practice_mode': 'point_focus',
        'target_node': node, 'item_count': 2}).json()
    # 卷面不回传考点，前端"换一批"就只能退回下拉框的值，考点专练会被换成整池抽题。
    assert paper['target_node'] == node
    assert paper['total_items']


def test_every_chat_branch_produces_a_trace_that_says_who_answered():
    user = 'web-test-branches-' + uuid.uuid4().hex
    scope = {'user_id': user, 'exam_type': 'NTCE', 'school_level': 'xiaoxue', 'subject': 'zonghe'}
    _, meta = _servable_single_choice()
    calls = [
        ('题目答疑', {**scope, 'message': '请讲讲这道题', 'question_id': meta.question_id}),
        ('学习计划', {**scope, 'message': '帮我规划一下备考',
                     'action_payload': {'days_until_exam': 5, 'daily_available_minutes': 30}}),
        ('学情诊断', {**scope, 'message': '先给我做个摸底诊断'}),
        ('编排闭环', {**scope, 'message': '面试简案练习', 'action_payload': {'intent': 'interview_practice'}}),
        ('发布档拒答', {'user_id': user, 'exam_type': 'NTCE', 'trust_tier': 'published', 'message': '什么是因材施教'}),
    ]
    for label, body in calls:
        response = client.post('/api/v1/web/chat', json=body)
        assert response.status_code == 200, (label, response.text)
        trace = response.json()['trace']
        assert trace and all(row['detail'] for row in trace), label
        assert trace[0]['action'] in ('判定意图', '档位判定'), label
        # 最后一步必须说清这一轮是谁答的：模型参与与否，还是发布档直接拒答。
        assert trace[-1]['action'] in ('定稿', '档位判定'), label


def test_module_level_anchor_expands_to_the_nodes_that_carry_questions():
    user = 'web-test-module-' + uuid.uuid4().hex
    module = 'ntce.xiaoxue.zonghe.m3'
    data = client.post('/api/v1/web/chat', json={'user_id': user, 'exam_type': 'NTCE',
        'school_level': 'xiaoxue', 'subject': 'zonghe', 'message': '请解释教师职业道德规范，并说明作答思路',
        'action_payload': {'node_id': module}}).json()
    step = next(row for row in data['trace'] if row['action'] == '锚定考点与考纲条款')
    assert module in step['data']['declared_nodes']
    rows = data['related_questions']
    assert rows
    # 模块级考点名下一道题都不直接挂（库内 139 道全在下级考点上）：只按精确匹配就会退回召回顺带捞的题，
    # 学习者问的那个考点反而没题。附出来的题要真在这个考点子树里，前端也才组得出非空卷。
    for row in rows:
        assert any(n.startswith(module) for n in row['matched_nodes']), row['id']
    node = rows[0]['matched_nodes'][0]
    paper = client.post('/api/v1/web/practice', json={'user_id': user, 'exam_type': 'NTCE',
        'school_level': 'xiaoxue', 'subject': 'zonghe', 'practice_mode': 'point_focus',
        'target_node': node, 'item_count': 2}).json()
    assert paper['target_node'] == node and paper['total_items']


def test_quarantined_question_is_a_coded_conflict_not_a_bare_string():
    from services.knowledge.repository import get_repository
    from services.knowledge.trust import TrustGate
    repo, gate = get_repository(), TrustGate('research_internal')
    qid = next(m.question_id for m in repo.find_questions(exams='NTCE')
               if not gate.classify_meta(m).servable_in_paper)
    response = client.post('/api/v1/web/chat', json={'user_id': 'web-test-quarantine', 'exam_type': 'NTCE',
        'message': '请讲讲这道题', 'question_id': qid})
    assert response.status_code == 409, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'question_not_servable' and detail['message']
