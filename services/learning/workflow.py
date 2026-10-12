"""Learning workflows over library questions, durable submissions, and real Memory.

The scheduler supplies the original calendar. Replanning swaps only pending tasks when both
days' budgets permit it; completed/running tasks and all task identities remain unchanged.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import uuid

from fastapi import HTTPException
from services.common.models import AnswerSubmission, DiagnosticRequest, PlanRequest, TrustTier
from services.common.weakness import is_weak
from services.knowledge.graph_index import library_for_exam
from services.knowledge.trust import TrustGate
from services.learning.interview import InterviewTrainer
from services.learning.store import LearningStore, scope_data
from services.planner.agent import CurriculumPlannerAgent
from services.web.models import WebPracticeRequest


def now():
    return datetime.now(timezone.utc).isoformat()


class LearningWorkflow:
    def __init__(self, workbench):
        self.wb = workbench
        self.store = LearningStore(workbench)
        self.interview = InterviewTrainer(workbench, self.store)

    @staticmethod
    def _internal(ctx):
        if ctx.trust_tier == TrustTier.PUBLISHED:
            raise HTTPException(409, '发布档尚无可用签署题，学习闭环按可信门禁停止；请使用内部研究档。')

    def _metas(self, ctx):
        return list(self.wb.repo.find_questions(exams=ctx.exam_type,
                    school_level=ctx.school_level, subject=ctx.subject))

    def _pool(self, ctx, *, objective=False):
        gate = TrustGate(ctx.trust_tier.value)
        pool = []
        for meta in self._metas(ctx):
            if not meta.has_answerable_text or not gate.classify_meta(meta).servable_in_paper:
                continue
            if objective and (meta.question_type not in ('单选', '多选') or not meta.node_ids):
                continue
            if self.wb.repo.has_unavailable_figure(meta.question_id):
                continue
            record = self.wb.repo.load_question(meta.question_id)
            if not record or not gate.classify_record(record).servable_in_paper:
                continue
            # A visible listening item without its source audio is not a fair diagnostic.
            if (record.get('extra') or {}).get('audio') and not self.wb.repo.audio_path(meta.question_id):
                continue
            if objective:
                answer = str((record.get('content') or {}).get('answer') or '')
                if gate.reconcile_verdict(record, answer, None)[0] is None:
                    continue
            pool.append(meta)
        return pool

    def _scope_nodes(self, ctx):
        nodes = {node for meta in self._metas(ctx) for node in meta.node_ids}
        library = library_for_exam(ctx.exam_type)
        if library:
            graph_nodes, _ = self.wb.repo.graph_records(library)
            for record in graph_nodes:
                if record.get('type') != 'knowledge_node':
                    continue
                nid = record['id']
                if ctx.exam_type == 'NTCE':
                    if ctx.school_level and not nid.startswith('ntce.' + ctx.school_level + '.'):
                        continue
                    if ctx.subject and ('.' + ctx.subject + '.') not in nid:
                        continue
                elif ctx.school_level or ctx.subject:
                    # CET graph is shared. Arbitrary NTCE-style filters must not widen an empty scope.
                    continue
                nodes.add(nid)
        return nodes

    @staticmethod
    def _spread(pool, count):
        selected, seen = [], Counter()
        remaining = {meta.question_id: meta for meta in pool}
        while remaining and len(selected) < count:
            meta = min(remaining.values(), key=lambda m: (
                -sum(seen[n] == 0 for n in m.node_ids), sum(seen[n] for n in m.node_ids), m.question_id))
            selected.append(meta)
            seen.update(meta.node_ids)
            del remaining[meta.question_id]
        return selected

    def _coverage(self, ctx, pool, paper, submissions, requested):
        available = {node for meta in pool for node in meta.node_ids}
        scoped = self._scope_nodes(ctx)
        selected = {node for q in paper['questions'] for node in (self.wb.repo.get_meta(q['question_id']).node_ids)}
        covered = {node for s in submissions for node in (self.wb.repo.get_meta(s['question_id']).node_ids)}
        return {'scope_node_ids': sorted(scoped), 'available_node_ids': sorted(available),
                'selected_node_ids': sorted(selected), 'covered_node_ids': sorted(covered),
                'uncovered_node_ids': sorted(scoped - covered), 'unavailable_node_ids': sorted(scoped - available),
                'requested_items': requested, 'available_items': len(pool),
                'scope_node_count': len(scoped), 'covered_node_count': len(covered)}

    def _paper(self, ctx, paper_id):
        paper = self.wb.store.paper(ctx.user_id, paper_id)
        if paper is None or any(paper.get(key) != value for key, value in scope_data(ctx).items() if key != 'user_id'):
            raise HTTPException(404, '当前学习范围没有这份练习卷。')
        return paper

    def _evidence(self, paper):
        qids = {q['question_id'] for q in paper['questions'] if not q.get('input_blocked')}
        return [s for s in self.wb.store.paper_submissions(paper['paper_id'])
                if s.get('question_id') in qids and s.get('submitted_at') and s.get('user_answer')]

    def _issue_selected(self, ctx, selected, title):
        if not selected:
            raise HTTPException(409, '当前范围没有可作答的真实题目，请调整范围或补齐题库内容。')
        paper = self.wb.practice(WebPracticeRequest(**scope_data(ctx), practice_mode='error_elimination',
                                wrong_question_ids=[m.question_id for m in selected], item_count=min(100, len(selected))))
        if not paper['total_items']:
            raise HTTPException(409, '可信门禁未允许题目发卷，未启动学习任务。')
        paper['title'] = title
        # Workbench owns paper identity/materials/answer redaction; change only the display title.
        with self.wb.store.lock:
            self.wb.store.db.execute('UPDATE papers SET data=? WHERE id=? AND user=?',
                (json.dumps(paper, ensure_ascii=False), paper['paper_id'], ctx.user_id))
            self.wb.store.db.commit()
        return paper

    def _diagnostic_view(self, ctx, document, *, include_paper=False):
        paper = self._paper(ctx, document['paper_id'])
        submissions = self._evidence(paper)
        pool = self._pool(ctx, objective=True)
        coverage = self._coverage(ctx, pool, paper, submissions, document['requested_items'])
        complete = len(submissions) == paper['total_items'] and bool(submissions)
        report = self.wb.diagnostic.evaluate(DiagnosticRequest(user_id=ctx.user_id, exam_type=ctx.exam_type,
            trust_tier=ctx.trust_tier, submissions=[AnswerSubmission(question_id=s['question_id'],
                user_answer=s['user_answer'], time_spent_seconds=s.get('time_spent_seconds', 0)) for s in submissions]))
        notices = ['摸底仅统计本次实际提交的题目与考点覆盖，不提供正式分数、能力估计或通过概率。',
                   f"当前范围 {coverage['scope_node_count']} 个库内考点，已作答覆盖 {coverage['covered_node_count']} 个；未覆盖部分不作掌握度判断。",
                   '初始摸底只选可核对答案且题面资源完整的客观题；主观题与无可用题考点未纳入本次摸底。']
        result = {'diagnostic_id': document['diagnostic_id'], 'status': 'completed' if complete else 'in_progress',
                  'paper_id': paper['paper_id'], 'submitted_count': len(submissions), 'total_items': paper['total_items'],
                  'diagnostic': report.model_dump(mode='json'), 'coverage': coverage,
                  'notices': list(dict.fromkeys(notices + paper.get('notices', [])))}
        if include_paper:
            result['paper'] = paper
        return result

    def start_diagnostic(self, req):
        self._internal(req)
        with self.store.transaction():
            identity = self.store.replay(req, 'diagnostic/start')
            if identity:
                return self._diagnostic_view(req, self.store.get(req, 'diagnostic', identity), include_paper=True)
            selected = self._spread(self._pool(req, objective=True), req.item_count)
            paper = self._issue_selected(req, selected, '【初始摸底】' + req.exam_type + ' · 考点覆盖练习')
            identity = 'diagnostic-' + uuid.uuid4().hex
            document = {'diagnostic_id': identity, 'paper_id': paper['paper_id'],
                        'requested_items': req.item_count, 'created_at': now(), **scope_data(req)}
            self.store.save(req, 'diagnostic', identity, document)
            self.store.receipt(req, 'diagnostic/start', identity)
            return self._diagnostic_view(req, document, include_paper=True)

    def diagnostic_result(self, req):
        self._internal(req)
        document = self.store.get(req, 'diagnostic', req.diagnostic_id)
        if document is None:
            raise HTTPException(404, '当前学习范围没有这次摸底。')
        return self._diagnostic_view(req, document)

    @staticmethod
    def _tasks(plan):
        return [task for day in plan['daily_plans'] for task in day['tasks']]

    def _load_plan(self, req):
        plan = self.store.get(req, 'plan', req.plan_id)
        if plan is None:
            raise HTTPException(404, '当前学习范围没有这份计划。')
        return plan

    def _load_task(self, plan, task_id):
        task = next((t for t in self._tasks(plan) if t['task_id'] == task_id), None)
        if task is None:
            raise HTTPException(404, '这份计划没有该学习任务。')
        return task

    def _refresh_counts(self, ctx, plan):
        for task in self._tasks(plan):
            if task.get('paper_id'):
                task['submitted_count'] = len(self._evidence(self._paper(ctx, task['paper_id'])))
        return plan

    def _mastery(self, ctx, nodes):
        return [record for node in sorted(nodes)
                if (record := self.wb.memory.get_user_mastery(ctx.user_id, node)) is not None]

    def create_plan(self, req):
        self._internal(req)
        with self.store.transaction():
            identity = self.store.replay(req, 'plan')
            if identity:
                return {'plan': self._refresh_counts(req, self.store.get(req, 'plan', identity))}
            pool = self._pool(req)
            nodes = {node for meta in pool for node in meta.node_ids}
            if not nodes:
                raise HTTPException(409, '当前范围没有可用于计划的真实题目与考点。')
            planner = CurriculumPlannerAgent(repository=self.wb.repo, store=self.wb.memory.store)
            plan = planner.generate_plan(PlanRequest(**scope_data(req), days_until_exam=req.days_until_exam,
                daily_available_minutes=req.daily_available_minutes, current_mastery=self._mastery(req, nodes))).model_dump(mode='json')
            by_node = Counter(node for meta in pool for node in meta.node_ids)
            for day in plan['daily_plans']:
                day['tasks'] = [task for task in day['tasks'] if not task['node_id'] or by_node[task['node_id']]]
                for task in day['tasks']:
                    task.update(task_id='task-' + uuid.uuid4().hex, status='pending', paper_id=None,
                                required_submission_count=0, submitted_count=0, completed_at=None, mastery_score=None)
                day['total_minutes'] = sum(t['estimated_minutes'] for t in day['tasks'])
            if not self._tasks(plan):
                raise HTTPException(409, '当前可用时长无法安排可完成的真实题目，请增加每日时长或调整范围。')
            identity = 'plan-' + uuid.uuid4().hex
            stamp = now()
            plan.update(plan_id=identity, **scope_data(req), status='active', revision=1, created_at=stamp,
                        updated_at=stamp, days_until_exam=req.days_until_exam,
                        daily_available_minutes=req.daily_available_minutes,
                        budget_minutes=req.days_until_exam * req.daily_available_minutes,
                        scheduled_minutes=sum(d['total_minutes'] for d in plan['daily_plans']), completed_minutes=0)
            self._rank_pending(req, plan)
            self.store.save(req, 'plan', identity, plan)
            self.store.receipt(req, 'plan', identity)
            return {'plan': plan}

    def current_plan(self, ctx):
        if ctx.trust_tier == TrustTier.PUBLISHED:
            return {'plan': None}
        plan = self.store.latest(ctx, 'plan')
        return {'plan': self._refresh_counts(ctx, plan) if plan else None}

    def _rank_pending(self, ctx, plan):
        """Swap pending tasks under both daily caps; never recreate or mutate completed tasks."""
        days = plan['daily_plans']
        positions = [(di, ti) for di, day in enumerate(days) for ti, task in enumerate(day['tasks'])
                     if task['status'] == 'pending']
        def task_at(pos):
            return days[pos[0]]['tasks'][pos[1]]
        def priority(task):
            score = task.get('mastery_score')
            if task['task_type'] == 'fsrs_review':
                return (-1, 0, task['task_id'])
            return ((0, score, task['task_id']) if score is not None and is_weak(score)
                    else (1, 0, task['task_id']) if score is None else (2, score, task['task_id']))
        for pos in positions:
            task = task_at(pos)
            record = self.wb.memory.get_user_mastery(ctx.user_id, task['node_id']) if task.get('node_id') else None
            task['mastery_score'] = record.mastery_score if record is not None else None
        cap = plan['daily_available_minutes']
        for index, position in enumerate(positions):
            current = task_at(position)
            best = position
            for candidate in positions[index + 1:]:
                other = task_at(candidate)
                if priority(other) >= priority(task_at(best)):
                    continue
                delta = other['estimated_minutes'] - current['estimated_minutes']
                if position[0] != candidate[0] and (days[position[0]]['total_minutes'] + delta > cap
                                                   or days[candidate[0]]['total_minutes'] - delta > cap):
                    continue
                best = candidate
            if best != position:
                other = task_at(best)
                delta = other['estimated_minutes'] - current['estimated_minutes']
                days[position[0]]['tasks'][position[1]], days[best[0]]['tasks'][best[1]] = other, current
                days[position[0]]['total_minutes'] += delta
                days[best[0]]['total_minutes'] -= delta
        plan['completed_minutes'] = sum(t['estimated_minutes'] for t in self._tasks(plan) if t['status'] == 'completed')
        plan['status'] = 'completed' if all(t['status'] == 'completed' for t in self._tasks(plan)) else 'active'
        notice = '未完成任务按真实学习记忆重排，并受每日时间预算约束；无记录考点不设默认掌握度，已完成与进行中任务保留。'
        plan['notices'] = list(dict.fromkeys(plan.get('notices', []) + [notice]))

    def replan(self, req):
        self._internal(req)
        with self.store.transaction():
            identity = self.store.replay(req, 'plan/replan')
            plan = self._load_plan(req)
            if not identity:
                self._rank_pending(req, plan)
                plan['revision'] += 1
                plan['updated_at'] = now()
                self.store.save(req, 'plan', req.plan_id, plan)
                self.store.receipt(req, 'plan/replan', req.plan_id)
            return {'plan': self._refresh_counts(req, plan)}

    def _task_response(self, ctx, plan, task, paper=None):
        self._refresh_counts(ctx, plan)
        result = {'plan': plan, 'task': task, 'submitted_count': task['submitted_count'],
                  'required_submission_count': task['required_submission_count']}
        if paper is not None:
            result['paper'] = paper
        return result

    def start_task(self, req):
        self._internal(req)
        with self.store.transaction():
            plan = self._load_plan(req)
            task = self._load_task(plan, req.task_id)
            if task.get('paper_id'):
                return self._task_response(req, plan, task, self._paper(req, task['paper_id']))
            if task['task_type'] == 'mock_sprint':
                paper = self.wb.practice(WebPracticeRequest(**scope_data(req), practice_mode='mock_exam', item_count=100))
                if not paper['total_items'] or any(q.get('input_blocked') for q in paper['questions']):
                    raise HTTPException(409, '模考卷题面资源不完整，尚不能开始该任务。')
            else:
                pool = self._pool(req)
                if task.get('node_id'):
                    pool = [m for m in pool if task['node_id'] in m.node_ids]
                if task['task_type'] == 'fsrs_review':
                    due = set(self.wb.memory.due_question_ids(req.user_id, limit=100))
                    pool = [m for m in pool if m.question_id in due]
                selected = self._spread(pool, max(1, min(task['target_question_count'], 100)))
                paper = self._issue_selected(req, selected, '【计划任务】' + task['title'])
            required = len([q for q in paper['questions'] if not q.get('input_blocked')])
            if not required:
                raise HTTPException(409, '当前任务没有可实际提交的题目，未标记开始。')
            task.update(status='in_progress', paper_id=paper['paper_id'], required_submission_count=required,
                        started_at=now())
            if required < task['target_question_count']:
                task['shortfall_notice'] = f'实际可用题 {required} 道，少于原计划 {task["target_question_count"]} 道；完成条件按实际发卷题数。'
            plan['revision'] += 1
            plan['updated_at'] = now()
            self.store.save(req, 'plan', req.plan_id, plan)
            return self._task_response(req, plan, task, paper)

    def complete_task(self, req):
        self._internal(req)
        with self.store.transaction():
            plan = self._load_plan(req)
            task = self._load_task(plan, req.task_id)
            if not task.get('paper_id'):
                raise HTTPException(409, '请先开始任务，并提交任务练习卷。')
            paper = self._paper(req, task['paper_id'])
            task['submitted_count'] = len(self._evidence(paper))
            required = task['required_submission_count']
            if required <= 0 or task['submitted_count'] < required:
                raise HTTPException(409, f'当前已提交 {task["submitted_count"]}/{required} 题，请完成实际答题后再结束任务。')
            if task['status'] != 'completed':
                task.update(status='completed', completed_at=now())
                self._rank_pending(req, plan)
                plan['revision'] += 1
                plan['updated_at'] = now()
                self.store.save(req, 'plan', req.plan_id, plan)
            return self._task_response(req, plan, task)
