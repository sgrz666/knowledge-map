"""Persist server deadlines and acceptance receipts before any learner-memory write.

Workbench.submit must call guard_submission after ownership/tier/membership checks,
before its existing receipt lookup or memory writes; then mask_submission on either
return path. Recovery routes must use the same masker for their submission lists.
All operations share WorkbenchStore's reentrant lock and SQLite connection.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from services.common.models import PracticeMode
from services.knowledge.repository import timed_stages
from services.memory.receipt import LegacyReceipt, ReceiptConflict, fingerprint, verify_receipt
from services.web.models import WebPracticeRequest
from services.web.store import submission_fingerprint


class ExamSessions:
    def __init__(self, workbench, *, clock=None):
        self.workbench = workbench
        self.store = workbench.store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with self.store.lock:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS exam_sessions (
                id TEXT PRIMARY KEY, paper TEXT NOT NULL UNIQUE, user TEXT NOT NULL,
                request_id TEXT NOT NULL, request_fingerprint TEXT NOT NULL, data TEXT NOT NULL,
                UNIQUE(user, request_id))''')
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS exam_admissions (
                paper TEXT NOT NULL, question TEXT NOT NULL, fingerprint TEXT NOT NULL,
                accepted_at TEXT NOT NULL, PRIMARY KEY(paper, question))''')
            self.store.db.commit()

    def _now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError('Exam clock must return a timezone-aware datetime')
        return value.astimezone(timezone.utc)

    def _save(self, data):
        self.store.db.execute('UPDATE exam_sessions SET data=? WHERE id=?',
                              (json.dumps(data, ensure_ascii=False), data['session_id']))
        self.store.db.commit()

    def _load(self, session_id, user_id):
        row = self.store.db.execute('SELECT data FROM exam_sessions WHERE id=? AND user=?',
                                   (session_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, '当前学习者没有这次模考')
        return json.loads(row[0])

    def _for_paper(self, paper_id):
        row = self.store.db.execute('SELECT data FROM exam_sessions WHERE paper=?', (paper_id,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _context_matches(data, ctx):
        if ctx.trust_tier.value != data['trust_tier']:
            raise HTTPException(409, '模考与当前内容档位不一致')
        if any(getattr(ctx, key) != value for key, value in data['scope'].items()):
            raise HTTPException(409, '模考与当前考试、学段或科目不一致')

    def _select_spec(self, req):
        specs = self.workbench.repo.paper_specs(req.exam_type)
        if req.spec_id:
            specs = [s for s in specs if s.get('spec_id') == req.spec_id]
            if not specs:
                raise HTTPException(404, '指定的模考规格不在当前考试题库')
        specs = [s for s in specs if all(expected is None or s.get(key) == expected for key, expected in (
            ('school_level', req.school_level), ('subject', req.subject)))]
        if not specs:
            raise HTTPException(409, '当前学段科目没有可用的模考规格')
        if req.exam_type.startswith('CET'):
            specs.sort(key=lambda s: (str(s.get('year') or ''), str(s.get('paper') or '')), reverse=True)
        spec = specs[0]
        if req.exam_type.startswith('CET'):
            if not timed_stages(spec) or any(s['minutes'] <= 0 for s in timed_stages(spec)):
                raise HTTPException(409, '这份 CET 规格缺少完整逐节时长，暂不能开始计时模考')
        elif not isinstance(spec.get('total_duration_minutes'), (float, int)) or spec['total_duration_minutes'] <= 0:
            raise HTTPException(409, '这份教资规格缺少整卷时长，暂不能开始计时模考')
        return spec

    def start(self, req):
        request_fp = fingerprint(req.model_dump(mode='json', exclude={'request_id'}))
        with self.store.lock:
            existing = self.store.db.execute(
                'SELECT data, request_fingerprint FROM exam_sessions WHERE user=? AND request_id=?',
                (req.user_id, req.request_id)).fetchone()
            if existing:
                if existing[1] != request_fp:
                    raise HTTPException(409, '这次开始请求已受理，请使用原参数重试或生成新的请求编号')
                return self._snapshot(json.loads(existing[0]))
            spec = self._select_spec(req)
            scope = {'exam_type': req.exam_type, 'school_level': req.school_level or spec.get('school_level'),
                     'subject': req.subject or spec.get('subject')}
            paper = self.workbench.practice(WebPracticeRequest(user_id=req.user_id, **scope,
                practice_mode=PracticeMode.MOCK_EXAM, trust_tier=req.trust_tier, spec_id=spec['spec_id']))
            if not paper['questions']:
                self.store.db.execute('DELETE FROM papers WHERE id=? AND user=?', (paper['paper_id'], req.user_id))
                self.store.db.commit()
                raise HTTPException(409, '当前档位与规格没有可作答题目，无法开始模考')
            now = self._now()
            stages = self._make_stages(spec, paper, now)
            sid = 'exam-' + uuid.uuid4().hex
            notices = [n for n in paper.get('notices', [])
                       if '尚未执行逐节收卡' not in n and '系统不内置模考时序' not in n]
            notices.append('服务端保存考试起止时间；刷新页面不会重置计时，已结束的小节无法继续作答。')
            notices.append('当前为库内规格模拟，题库缺题和音频时序未核定可能影响还原程度；不提供官方报告分。')
            if req.exam_type == 'NTCE':
                notices.append(f'教资按库内规格整卷 {spec["total_duration_minutes"]} 分钟计时，卷内各题可切换。')
            notices.extend(s['audio']['notice'] for s in stages if s['audio']['mode'] != 'not_applicable')
            paper.update(exam_session_id=sid, notices=notices,
                         title='【服务端计时模考】' + spec.get('title', req.exam_type),
                         time_limit_minutes=sum(s['duration_seconds'] for s in stages) / 60)
            data = {'session_id': sid, 'paper_id': paper['paper_id'], 'user_id': req.user_id,
                    'scope': scope, 'trust_tier': req.trust_tier.value, 'spec_id': spec['spec_id'],
                    'spec_snapshot': spec, 'started_at': now.isoformat(), 'ends_at': stages[-1]['ends_at'],
                    'status': 'active', 'finished_at': None, 'finish_reason': None,
                    'stages': stages, 'notices': notices}
            self.store.db.execute('UPDATE papers SET data=? WHERE id=? AND user=?',
                (json.dumps(paper, ensure_ascii=False), paper['paper_id'], req.user_id))
            self.store.db.execute('INSERT INTO exam_sessions VALUES(?,?,?,?,?,?)',
                (sid, paper['paper_id'], req.user_id, req.request_id, request_fp, json.dumps(data, ensure_ascii=False)))
            self.store.db.commit()
            return self._snapshot(data)

    def _make_stages(self, spec, paper, now):
        questions = paper['questions']
        stages = timed_stages(spec) if paper['exam_type'].startswith('CET') else []
        if not stages:
            stages = [{'name': '整卷作答', 'module': None, 'minutes': spec['total_duration_minutes'],
                       'sheet_submission': 'whole_paper', 'allow_backtrack': True}]
        parts = spec.get('parts') or []
        result, assigned = [], set()
        cursor = now
        for index, stage in enumerate(stages):
            pinned = set((parts[index] if parts else {}).get('question_ids') or [])
            ids = [q['question_id'] for q in questions if q['question_id'] not in assigned and (
                len(stages) == 1 or q['question_id'] in pinned or (not pinned and (
                    q.get('module') == stage['module'] or q.get('section') == stage['name'])))]
            assigned.update(ids)
            duration = int(stage['minutes'] * 60)
            end = cursor + timedelta(seconds=duration)
            result.append({'index': index, 'name': stage['name'], 'module': stage['module'],
                'duration_seconds': duration, 'starts_at': cursor.isoformat(), 'ends_at': end.isoformat(),
                'question_ids': ids, 'sheet_submission': stage['sheet_submission'],
                'allow_backtrack': stage['allow_backtrack'], 'can_submit_early': False,
                'audio': self._audio(stage, ids, questions)})
            cursor = end
        if assigned != {q['question_id'] for q in questions}:
            raise HTTPException(409, '卷内部分题目无法对应规格中的阶段，暂不能开始模考')
        return result

    @staticmethod
    def _audio(stage, ids, questions):
        listening = stage.get('module') == '听力理解' or 'listening' in stage['name'].lower()
        urls = list(dict.fromkeys(q['audio_url'] for q in questions
                                 if q['question_id'] in ids and q.get('audio_url')))
        mode = ('source_audio' if urls else 'unavailable') if listening else 'not_applicable'
        notice = ''
        if listening:
            notice = ('听力提供题库关联的原始整段音频，可手动播放；' if urls else '当前听力节没有可播放的本地音频；')
            notice += '切片及官方播放时序未经逐段核验，本节按库内分钟数计时，不承诺全真音频时序。'
        return {'mode': mode, 'urls': urls, 'verified_timing': False, 'strict_playback': False, 'notice': notice}

    def _refresh(self, data, now):
        changed = False
        if data['status'] == 'active' and now >= datetime.fromisoformat(data['ends_at']):
            data.update(status='completed', finished_at=data['ends_at'], finish_reason='timeout')
            changed = True
        for stage in data['stages']:
            if data['status'] == 'completed' or now >= datetime.fromisoformat(stage['ends_at']):
                status = 'collected'
            elif now >= datetime.fromisoformat(stage['starts_at']):
                status = 'active'
            else:
                status = 'pending'
            if stage.get('status') != status:
                stage['status'] = status
                changed = True
        if changed:
            self._save(data)
        return data

    def _snapshot(self, data):
        now = self._now()
        self._refresh(data, now)
        paper = self.store.paper(data['user_id'], data['paper_id'])
        if paper is None:
            raise HTTPException(409, '模考试卷丢失，无法恢复')
        stages = []
        for stored in data['stages']:
            stage = dict(stored)
            stage['time_remaining_seconds'] = (max(0, math.ceil((datetime.fromisoformat(stage['ends_at']) - now).total_seconds()))
                                               if stage['status'] == 'active' else
                                               stage['duration_seconds'] if stage['status'] == 'pending' else 0)
            stage['input_locked'] = stage['status'] != 'active'
            stages.append(stage)
        current = next((s for s in stages if s['status'] == 'active'), None)
        blocked = {q['question_id'] for q in paper['questions'] if q.get('input_blocked')}
        allowed = [qid for qid in (current or {}).get('question_ids', []) if qid not in blocked]
        completed = data['status'] == 'completed'
        submissions = self.store.paper_submissions(data['paper_id'])
        return {key: data[key] for key in ('session_id', 'paper_id', 'scope', 'trust_tier', 'spec_id',
                                          'started_at', 'ends_at', 'status', 'finished_at', 'finish_reason', 'notices')} | {
            'paper': paper, 'server_now': now.isoformat(), 'stages': stages, 'current_stage': current,
            'stage_index': current['index'] if current else len(stages),
            'allowed_question_ids': allowed,
            'locked_question_ids': [q['question_id'] for q in paper['questions'] if q['question_id'] not in allowed],
            'collected_stages': [s['name'] for s in stages if s['status'] == 'collected'],
            'collected_sheets': sorted({s['sheet_submission'] for s in stages if s['sheet_submission'] and
                all(other['status'] == 'collected' for other in stages if other['sheet_submission'] == s['sheet_submission'])}),
            'submissions': submissions if completed else [self._ack(s, data['session_id']) for s in submissions],
            'results': self._results(paper, submissions) if completed else None}

    @staticmethod
    def _results(paper, submissions):
        objective = [s for s in submissions if isinstance(s.get('is_correct'), bool)]
        correct = sum(s['is_correct'] for s in objective)
        return {'submitted_count': len(submissions), 'issued_count': len(paper['questions']),
                'unanswered_count': len(paper['questions']) - len(submissions),
                'objective_count': len(objective), 'correct_count': correct,
                'objective_accuracy': correct / len(objective) if objective else None,
                'subjective_count': sum(s.get('grading') is not None for s in submissions),
                'official_score': None, 'notice': '仅汇总本次已作答题目；客观题按库内答案核对，主观题为参考评价，不是官方评分。'}

    def state(self, session_id, ctx):
        with self.store.lock:
            data = self._load(session_id, ctx.user_id)
            self._context_matches(data, ctx)
            return self._snapshot(data)

    def latest(self, ctx):
        with self.store.lock:
            for row in self.store.db.execute('SELECT data FROM exam_sessions WHERE user=? ORDER BY rowid DESC', (ctx.user_id,)):
                data = json.loads(row[0])
                if data['trust_tier'] == ctx.trust_tier.value and all(getattr(ctx, k) == v for k, v in data['scope'].items()):
                    return {'session': self._snapshot(data)}
            return {'session': None}

    def advance(self, session_id, ctx):
        """Reconcile elapsed wall time; callers cannot choose or accelerate stages."""
        return self.state(session_id, ctx)

    def finish(self, session_id, ctx):
        with self.store.lock:
            data = self._load(session_id, ctx.user_id)
            self._context_matches(data, ctx)
            now = self._now()
            self._refresh(data, now)
            if data['status'] == 'active':
                data.update(status='completed', finished_at=now.isoformat(), finish_reason='learner_finished')
                self._save(data)
            return self._snapshot(data)

    def guard_submission(self, req, paper):
        """Admit exactly one fingerprint while its stage is open, before memory can change.

        The durable admission also permits a same-input retry after a partial write
        failure and after timeout. It never grants permission to a different answer.
        Legacy structural practice papers have no registered session and pass through.
        """
        with self.store.lock:
            data = self._for_paper(req.paper_id)
            if data is None:
                return
            if data['user_id'] != req.user_id:
                raise HTTPException(404, '当前学习者没有这次模考')
            if req.trust_tier.value != data['trust_tier']:
                raise HTTPException(409, {'code': 'exam_tier_mismatch', 'message': '模考与当前内容档位不一致'})
            if not any(q['question_id'] == req.question_id for q in paper['questions']):
                raise HTTPException(400, '提交题目不属于当前模考')
            fp = submission_fingerprint(req)
            admission = self.store.db.execute('SELECT fingerprint FROM exam_admissions WHERE paper=? AND question=?',
                                             (req.paper_id, req.question_id)).fetchone()
            if admission:
                try:
                    verify_receipt(f'{req.paper_id}:{req.question_id}', admission[0], fp)
                except LegacyReceipt as legacy:
                    raise HTTPException(409, {'code': 'legacy_receipt', 'message': str(legacy)}) from legacy
                except ReceiptConflict as conflict:
                    raise HTTPException(409, {'code': 'receipt_conflict', 'message': str(conflict)}) from conflict
                return
            now = self._now()
            self._refresh(data, now)
            if data['status'] != 'active':
                raise HTTPException(409, {'code': 'exam_closed', 'message': '模考已经结束，不能继续作答'})
            current = next((s for s in data['stages'] if s['status'] == 'active'), None)
            if not current or req.question_id not in current['question_ids']:
                raise HTTPException(409, {'code': 'exam_stage_collected',
                    'message': '该题所属小节尚未开始或已收卡，不能继续作答'})
            if any(q['question_id'] == req.question_id and q.get('input_blocked') for q in paper['questions']):
                raise HTTPException(409, {'code': 'exam_media_missing', 'message': '题目依赖的媒体缺失，暂不能提交'})
            self.store.db.execute('INSERT INTO exam_admissions VALUES(?,?,?,?)',
                                 (req.paper_id, req.question_id, fp, now.isoformat()))
            self.store.db.commit()

    @staticmethod
    def _ack(response, session_id):
        return {key: response[key] for key in ('paper_id', 'question_id', 'user_answer',
                                               'time_spent_seconds', 'submitted_at') if key in response} | {
            'session_id': session_id, 'accepted': True, 'deferred_feedback': True}

    def mask_submission(self, paper_id, response):
        """Suppress grading and explanation until completion on every recovery route."""
        with self.store.lock:
            data = self._for_paper(paper_id)
            if data is None:
                return response
            self._refresh(data, self._now())
            return response if data['status'] == 'completed' else self._ack(response, data['session_id'])

    def submit(self, session_id, req):
        with self.store.lock:
            data = self._load(session_id, req.user_id)
            if req.paper_id != data['paper_id']:
                raise HTTPException(409, '提交的试卷与模考会话不一致')
            paper = self.store.paper(req.user_id, req.paper_id)
            if paper is None:
                raise HTTPException(404, '当前学习者没有这份模考试卷')
            # admission 是 durable 的唯一受理闸，必须在锁内落库；之后的判分与讲解
            # （可能触发 LLM 联网）放到锁外——全程持锁会让模考 /state 轮询在数十秒内
            # 全部冻住，而服务端计时不会因此暂停。
            self.guard_submission(req, paper)
        result = self.workbench.submit(req)
        with self.store.lock:
            return {'submission': self.mask_submission(req.paper_id, result), 'session': self._snapshot(data)}
