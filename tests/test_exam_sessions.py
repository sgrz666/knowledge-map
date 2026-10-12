"""Server clocks and durable admissions, using real library papers and temporary SQLite."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from services.common.models import TrustTier
from services.web.models import SubmitRequest, WebContext


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def add(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def exam(tmp_path, monkeypatch):
    from services.exam_sessions import ExamSessions
    from services.memory.agent import MemoryReviewAgent
    from services.memory.store import SqliteMasteryStore
    from services.web.service import Workbench
    monkeypatch.setenv('KNOWLEDGE_MAP_STATE_DIR', str(tmp_path))
    wb = Workbench()
    wb.memory = MemoryReviewAgent(store=SqliteMasteryStore(tmp_path / 'memory.sqlite3'), repository=wb.repo)
    clock = Clock()
    wb.exam_sessions = ExamSessions(wb, clock=clock)
    yield wb.exam_sessions, wb, clock
    wb.store.db.close()
    wb.memory.store.close()


def start(exam, *, exam_type='CET-4', request_id='start-1'):
    from services.exam_sessions.models import ExamStartRequest
    kwargs = {'user_id': 'learner', 'exam_type': exam_type, 'request_id': request_id}
    if exam_type == 'CET-4':
        kwargs['spec_id'] = 'spec.cet4-2015-12-p1'
    else:
        kwargs.update(school_level='xiaoxue', subject='zonghe')
    req = ExamStartRequest(**kwargs)
    state = exam[0].start(req)
    ctx = WebContext(**state['scope'], user_id='learner', trust_tier=state['trust_tier'])
    return state, ctx, req


def submission(state, question_id, **changes):
    data = dict(user_id='learner', paper_id=state['paper_id'], question_id=question_id,
                answer='A', time_spent_seconds=20)
    data.update(changes)
    return SubmitRequest(**data)


def expect_status(code, action):
    with pytest.raises(HTTPException) as caught:
        action()
    assert caught.value.status_code == code


def test_start_uses_real_spec_and_idempotency(exam):
    service, wb, clock = exam
    state, ctx, req = start(exam)
    spec = next(s for s in wb.repo.paper_specs('CET-4') if s['spec_id'] == req.spec_id)
    assert len(state['stages']) == len(spec['parts'])
    assert state['paper']['spec_id'] == req.spec_id
    assert state['current_stage']['module'] == spec['parts'][0]['module']
    assert (datetime.fromisoformat(state['ends_at']) - clock.value).total_seconds() == sum(
        p['duration_minutes'] * 60 for p in spec['parts'])
    assert any('130' in notice and '125' in notice for notice in state['notices'])
    clock.add(10)
    replay = service.start(req)
    assert replay['session_id'] == state['session_id']
    assert replay['started_at'] == state['started_at']
    assert wb.store.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 1
    expect_status(409, lambda: service.start(req.model_copy(update={'spec_id': 'another-spec'})))
    assert service.latest(ctx)['session']['session_id'] == state['session_id']


def test_stage_boundaries_catch_up_and_refresh_survive_reopening(exam):
    from services.exam_sessions import ExamSessions
    from services.web.store import WorkbenchStore
    service, wb, clock = exam
    state, ctx, _ = start(exam)
    sid = state['session_id']
    assert service.advance(sid, ctx)['stage_index'] == 0  # no arbitrary fast-forward
    clock.add(30 * 60 - 1)
    assert service.state(sid, ctx)['current_stage']['time_remaining_seconds'] == 1
    clock.add(1)
    state = service.advance(sid, ctx)
    assert state['stage_index'] == 1
    assert state['stages'][0]['status'] == 'collected'
    assert state['stages'][0]['question_ids'][0] in state['locked_question_ids']
    clock.add((25 + 40) * 60 + 5)
    resumed = ExamSessions(wb, clock=clock).state(sid, ctx)
    assert resumed['stage_index'] == 3
    assert resumed['current_stage']['time_remaining_seconds'] == 30 * 60 - 5
    assert len(resumed['collected_stages']) == 3
    database_path = wb.store.db.execute('PRAGMA database_list').fetchone()[2]
    wb.store.db.close()
    wb.store = WorkbenchStore(database_path)
    wb.exam_sessions = ExamSessions(wb, clock=clock)
    assert wb.exam_sessions.state(sid, ctx)['ends_at'] == state['ends_at']
    clock.add(30 * 60)
    completed = wb.exam_sessions.state(sid, ctx)
    assert completed['status'] == 'completed'
    assert completed['allowed_question_ids'] == []
    assert completed['results']['official_score'] is None


def test_direct_workbench_submit_cannot_bypass_stage_guard_or_leak_feedback(exam):
    service, wb, clock = exam
    state, ctx, _ = start(exam)
    sid = state['session_id']
    qid = state['stages'][1]['question_ids'][0]
    req = submission(state, qid)
    expect_status(409, lambda: wb.submit(req))
    assert wb.store.paper_submissions(state['paper_id']) == []
    assert wb.memory.store.error_entries('learner') == []
    clock.add(30 * 60)
    response = wb.submit(req)
    assert response['accepted'] is True
    assert 'is_correct' not in response and 'explanation' not in response and 'review' not in response
    assert wb.store.submission(state['paper_id'], qid)['explanation']
    clock.add(25 * 60)
    replay = service.submit(sid, req)
    assert replay['submission'] == response
    expect_status(409, lambda: wb.submit(req.model_copy(update={'answer': 'B'})))
    unseen = state['stages'][1]['question_ids'][1]
    expect_status(409, lambda: wb.submit(submission(state, unseen)))
    assert wb.store.submission(state['paper_id'], unseen) is None
    assert all('explanation' not in s for s in service.state(sid, ctx)['submissions'])
    finished = service.finish(sid, ctx)
    assert finished['status'] == 'completed'
    assert finished['submissions'][0]['explanation']
    assert finished['results']['submitted_count'] == 1


def test_ntce_uses_whole_paper_clock_and_refuses_expired_answers(exam):
    service, wb, clock = exam
    state, ctx, _ = start(exam, exam_type='NTCE')
    assert len(state['stages']) == 1
    assert state['current_stage']['time_remaining_seconds'] == 120 * 60
    assert set(state['allowed_question_ids']) == {q['question_id'] for q in state['paper']['questions']
                                                if not q.get('input_blocked')}
    clock.add(120 * 60)
    expect_status(409, lambda: wb.submit(submission(state, state['allowed_question_ids'][0])))
    assert wb.memory.store.error_entries('learner') == []


def test_owner_tier_scope_and_session_paper_are_validated(exam):
    service, wb, _ = exam
    state, ctx, _ = start(exam)
    sid = state['session_id']
    expect_status(404, lambda: service.state(sid, ctx.model_copy(update={'user_id': 'stranger'})))
    expect_status(409, lambda: service.state(sid, ctx.model_copy(update={'trust_tier': TrustTier.PUBLISHED})))
    expect_status(409, lambda: service.state(sid, ctx.model_copy(update={'exam_type': 'CET-6'})))
    qid = state['allowed_question_ids'][0]
    expect_status(404, lambda: service.submit(sid, submission(state, qid, user_id='stranger')))
    expect_status(409, lambda: service.submit(sid, submission(state, qid, paper_id='different-paper')))


def test_audio_truthfully_degrades_to_source_audio(exam):
    state, _, _ = start(exam)
    audio = state['stages'][1]['audio']
    assert audio['mode'] in ('source_audio', 'unavailable')
    assert audio['verified_timing'] is False
    assert audio['strict_playback'] is False
    assert audio['notice']


def test_new_session_refuses_unknown_spec_and_tier_with_no_usable_content(exam):
    from services.exam_sessions.models import ExamStartRequest
    service, wb, _ = exam
    expect_status(404, lambda: service.start(ExamStartRequest(user_id='learner', exam_type='CET-4',
                  request_id='missing', spec_id='missing')))
    expect_status(409, lambda: service.start(ExamStartRequest(user_id='learner', exam_type='NTCE',
                  request_id='published', trust_tier='published', school_level='xiaoxue', subject='zonghe')))
    assert wb.store.db.execute('SELECT COUNT(*) FROM exam_sessions').fetchone()[0] == 0
