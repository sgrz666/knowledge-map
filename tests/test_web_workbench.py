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
