"""Stage-based interview training: continuous answers plus one grounded follow-up per question.

题面、参考框架与追问依据都只读库内资产。结构化问答的情境题面取自 interview_scenarios 资源里
「」框架之前那段原文（框架本身要等作答后才揭晓），点级比对用同一份框架原文，维度描述用
interview_qa 量规；试讲与简案走 InterviewCoachAgent 的转写测算与量规复核。量规与先修仍未签署，
所以整场会话只出比对与反馈，不出分数也不出通过概率。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from services.common.models import LessonPlanReviewRequest, SpeechAnalysisRequest, TrustTier
from services.grader.evidence import coverage, dimension_feedback
from services.knowledge.learning_resources import LearningResources
from services.knowledge.trust import TrustGate

_FRAMEWORK = re.compile(r"「([^」]+)」")
_CONNECTORS = ('遵循', '构建', '按照', '依据')
STAGE_TITLES = {'structured_qa': '结构化问答', 'trial_teaching': '试讲', 'lesson_plan': '简案设计'}
# 作答前不能看到的字段：参考框架、切分出的采分步与未命中步骤都会把答案透题。
_HIDDEN_WHILE_PENDING = ('reference_framework', 'points', 'points_from', 'missed_points')


def now():
    return datetime.now(timezone.utc).isoformat()


def framework_of(summary):
    """资源里最长的「」段才是作答框架；短的那是题面里的问句本身。"""
    blocks = [match.group(1) for match in _FRAMEWORK.finditer(summary or '') if len(match.group(1)) >= 12]
    return max(blocks, key=len) if blocks else ''


def scenario_stem(summary):
    """题面 = 框架之前的情境原文，去掉引出框架的「遵循/构建」这类连接词。"""
    text = summary or ''
    framework = framework_of(text)
    head = text[:text.rfind(framework)] if framework else text
    for connector in _CONNECTORS:
        index = head.rfind(connector)
        if index != -1:
            head = head[:index]
    return head.strip('，,、；;。 ')


def framework_points(framework):
    """按框架自己的写法切步：有 + 就分层，没有就按顿号分步；切不出就不做点级比对。"""
    if not framework:
        return ([], '库内该情境资源没有可切分的「」框架，本次不做点级比对，只做库内维度描述比对。')
    parts = re.split(r'\s*\+\s*', framework) if '+' in framework else re.split(r'[、，,；;]', framework)
    points = [point.strip()[:40] for point in parts if len(point.strip()) >= 4]
    label = ('库内面试情境资源「」框架按 + 分层切分' if '+' in framework else '库内面试情境资源「」框架按顿号分步切分')
    return points[:6], (label if points else label + '（本资源框架写法无法切出可比对的分步）')


class InterviewTrainer:
    """Runs one durable session: 结构化问答（含追问）→ 试讲 → 简案，逐阶段留库内证据。"""

    def __init__(self, workbench, store):
        self.wb = workbench
        self.store = store
        self.resources = LearningResources(repository=workbench.repo)

    def start(self, req):
        self._guard(req)
        with self.store.transaction():
            identity = self.store.replay(req, 'interview/start')
            if identity:
                return self._view(req, self.store.get(req, 'interview', identity))
            stages = self._stages(req)
            if not any(stage['tasks'] for stage in stages):
                raise HTTPException(409, '当前范围没有可绑定权威条款的面试情境资源，也没有可用于试讲与简案的库内依据，'
                                         '训练会话不虚构题面。')
            document = {'session_id': 'interview-' + uuid.uuid4().hex, 'created_at': now(),
                        'completed_at': None, 'stages': stages, **self._scope(req)}
            self.store.save(req, 'interview', document['session_id'], document)
            self.store.receipt(req, 'interview/start', document['session_id'])
            return self._view(req, document)

    def current(self, ctx):
        if ctx.trust_tier == TrustTier.PUBLISHED:
            return {'session': None}
        document = self.store.latest(ctx, 'interview')
        return {'session': self._view(ctx, document) if document else None}

    def answer(self, req):
        self._guard(req)
        with self.store.transaction():
            document = self.store.get(req, 'interview', req.session_id)
            if document is None:
                raise HTTPException(404, '当前学习范围没有这场面试训练会话。')
            task = self._task(document, req.task_id)
            # 同 request_id 同参数是重试：返回会话现状，不再写一次；改过参数由 store 直接 409。
            if self.store.replay(req, 'interview/answer'):
                return self._view(req, document)
            if task['state'] == 'done':
                raise HTTPException(409, '这个任务在本次会话里已经作答完成；每个任务只记一次作答，请开始新会话。')
            if task['state'] == 'pending':
                self._grade_first(req, task)
            elif task['state'] == 'awaiting_follow_up':
                self._grade_follow_up(req, task)
            else:
                self._grade_single(req, task)
            if all(item['state'] == 'done' for stage in document['stages'] for item in stage['tasks']):
                document['completed_at'] = now()
            self.store.save(req, 'interview', document['session_id'], document)
            self.store.receipt(req, 'interview/answer', task['task_id'])
            return self._view(req, document)

    # ------------------------------------------------------------- session setup
    def _stages(self, req):
        qa_tasks = [task for task in (self._qa_task(req, row) for row in self.resources.list_scenarios(req.exam_type))
                    if task]
        topic = self._design_topic(req)
        return [
            {'key': 'structured_qa', 'title': STAGE_TITLES['structured_qa'], 'tasks': qa_tasks,
             'notice': ('题面与参考框架都读自库内面试情境资源，作答后先比对再追问；'
                        f"当前范围可绑定权威条款的情境资源 {len(qa_tasks)} 个。" if qa_tasks else
                        '当前范围没有可绑定权威条款的面试情境资源，结构化问答阶段不出题。')},
            {'key': 'trial_teaching', 'title': STAGE_TITLES['trial_teaching'], 'tasks': [{
                'task_id': 'speech-' + uuid.uuid4().hex, 'kind': 'trial_teaching', 'state': 'pending',
                'title': '试讲转写文本测算',
                'prompt': '请粘贴你的试讲转写文本，并填试讲时长；系统按转写文本测算语速、停顿与导入/新授/巩固/小结/作业'
                          '五环节覆盖，不评价仪态、发音与视频表现。',
                'evidence': {'capability': 'speech', 'source': 'services/interview/speech_analyzer.py'},
                'answer': None, 'feedback': None, 'answered_at': None}],
             'notice': '试讲只按你提交的转写文本与时长测算；没有提交就没有测算，系统不虚构表现数据。'},
            {'key': 'lesson_plan', 'title': STAGE_TITLES['lesson_plan'], 'tasks': ([{
                'task_id': 'plan-' + uuid.uuid4().hex, 'kind': 'lesson_plan', 'state': 'pending',
                'title': '20 分钟教学设计简案', 'prompt': topic['prompt'],
                'topic': topic['stem'], 'evidence': topic['evidence'],
                'answer': None, 'feedback': None, 'answered_at': None}] if topic else []),
             'notice': topic['notice'] if topic else '当前范围没有可用于简案选题的库内教学设计题，本阶段不出题。'},
        ]

    def _qa_task(self, req, row):
        """One 结构化问答题：题面、条款绑定与框架切分都来自这一行库内资源。"""
        requirements = [rid for rid in (row.get('exam_requirement_ids') or []) if self.wb.repo.get_requirement(rid)]
        if not requirements:
            return None
        framework = framework_of(row.get('summary'))
        stem = scenario_stem(row.get('summary')) or row.get('title') or '库内面试情境'
        points, provenance = framework_points(framework)
        return {
            'task_id': 'qa-' + uuid.uuid4().hex, 'kind': 'structured_qa', 'state': 'pending',
            'title': row.get('title') or '库内面试情境',
            'prompt': f"{stem}。请现场作答这道结构化面试题；提交后系统再比对你的作答与库内参考框架，并追问一处。",
            'reference_framework': framework, 'exam_focus': row.get('exam_focus') or '',
            'points': points, 'points_from': provenance,
            'evidence': {'resource_id': row.get('resource_id'), 'requirement_ids': requirements,
                         'node_ids': list(row.get('knowledge_node_ids') or []),
                         'ability_ids': list(row.get('ability_ids') or []),
                         'level': row.get('level'), 'subject': row.get('subject'),
                         'source': (row.get('source') or {}).get('origin_file'),
                         'use_scope': (row.get('copyright') or {}).get('use_scope')},
            'answer': None, 'feedback': None, 'follow_up': None, 'follow_up_answer': None,
            'follow_up_feedback': None, 'missed_points': [], 'answered_at': None,
        }

    def _design_topic(self, req):
        """简案选题用库内真实教学设计题面，并绑定该题的审核状态。"""
        gate = TrustGate(req.trust_tier.value)
        for meta in self.wb.repo.find_questions(exams=req.exam_type, question_types=('教学设计', '活动设计'),
                                                require_nodes=True, school_level=req.school_level):
            if not gate.classify_meta(meta).usable or not meta.has_answerable_text:
                continue
            stem = (((self.wb.repo.load_question(meta.question_id) or {}).get('content') or {}).get('stem') or '').strip()
            if not stem:
                continue
            return {'question_id': meta.question_id, 'stem': stem[:160],
                    'prompt': f"请围绕这道库内教学设计题的题面写出 20 分钟简案：{stem[:160]}",
                    'evidence': {'question_id': meta.question_id, 'question_type': meta.question_type,
                                 'review_status': meta.review_status, 'node_ids': list(meta.node_ids),
                                 'source': meta.file},
                    'notice': f"简案选题取自库内 {meta.question_type} 真题题面，绑定该题审核状态 {meta.review_status}。"}
        return None

    # ------------------------------------------------------------------- grading
    def _grade_first(self, req, task):
        if task['kind'] == 'structured_qa':
            self._grade_qa(req, task, req.answer_text, 'feedback')
            task['answer'] = req.answer_text
            task['state'] = 'awaiting_follow_up'
            task['follow_up'] = self._follow_up(task)
            return
        self._grade_single(req, task)

    def _grade_single(self, req, task):
        if task['kind'] == 'trial_teaching':
            result = self.wb.interview_agent.analyze_speech(SpeechAnalysisRequest(
                transcript_text=req.answer_text, audio_duration_seconds=float(req.duration_seconds or 600.0),
                lesson_title=task['title'], trust_tier=req.trust_tier)).model_dump(mode='json')
            task['feedback'] = {
                'measured': {key: result.get(key) for key in
                             ('words_per_minute', 'speed_evaluation', 'hesitation_pause_count',
                              'phase_coverage_rate', 'teaching_phases')},
                'coaching_feedback': result.get('coaching_feedback'),
                'total_score': result.get('overall_score'), 'rubric_signed': result.get('rubric_signed'),
                'score_basis': 'measured_from_transcript' if result.get('overall_score') is None else 'signed_rubric',
                'notices': list(result.get('notices') or [])}
        else:
            result = self.wb.interview_agent.review_lesson_plan(LessonPlanReviewRequest(
                topic=task['topic'], plan_text=req.answer_text, trust_tier=req.trust_tier)).model_dump(mode='json')
            task['feedback'] = {'dimensions': result.get('dimensions') or [],
                                'missed_elements': result.get('missed_elements'),
                                'improvement_suggestions': result.get('improvement_suggestions'),
                                'total_score': result.get('total_score'), 'max_score': result.get('max_score'),
                                'rubric_id': result.get('rubric_id'), 'rubric_signed': result.get('rubric_signed'),
                                'score_basis': 'none' if result.get('total_score') is None else 'signed_rubric',
                                'notices': list(result.get('notices') or [])}
        task['answer'] = req.answer_text
        task['state'] = 'done'
        task['answered_at'] = now()

    def _grade_follow_up(self, req, task):
        if task['kind'] != 'structured_qa':
            raise HTTPException(409, '这个任务没有待回答的追问。')
        self._grade_qa(req, task, req.answer_text, 'follow_up_feedback')
        task['follow_up_answer'] = req.answer_text
        task['state'] = 'done'
        task['answered_at'] = now()

    def _grade_qa(self, req, task, answer, dest):
        rubric = self.wb.repo.find_rubric(task_type='interview_qa', exam='NTCE')
        verdict = TrustGate(req.trust_tier.value).classify_rubric(rubric)
        hits, ratio = coverage(task['points'], answer)
        dimensions = dimension_feedback((rubric or {}).get('dimensions') or [], hits, ratio, answer)
        notices = list(verdict.notices) + (['结构化问答只出点级比对与库内维度反馈：量规未签署，不给分数，'
                                            '也不给通过概率。'] if not verdict.signed else
                                           ['结构化问答按反馈口径出具，不使用正式分数。'])
        task[dest] = {'points': [hit.model_dump(mode='json') for hit in hits], 'coverage_ratio': ratio,
                      'points_from': task['points_from'],
                      'dimensions': [item.model_dump(mode='json') for item in dimensions],
                      'rubric_id': (rubric or {}).get('rubric_id'), 'rubric_signed': verdict.signed,
                      'review_status': verdict.review_status, 'total_score': None, 'score_basis': 'none',
                      'notices': list(dict.fromkeys(notices))}
        if dest == 'feedback':
            task['missed_points'] = [hit.point_text for hit in hits if hit.status == 'missed']

    def _follow_up(self, task):
        """追问只钉在库内框架里没被比对到的那一步；全都命中就收拢到资源标注的考察点。"""
        missed = task.get('missed_points') or []
        if missed:
            return {'question': f"你的作答里没有比对到「{missed[0]}」这一步。请补充这一步你具体怎么做、"
                                f"由谁配合、如何防止复发。",
                    'basis': f"依据：库内面试情境资源参考框架的步骤「{missed[0]}」在本次作答中未命中。",
                    'evidence': task['evidence']}
        focus = task.get('exam_focus') or ''
        return {'question': f"请把作答收拢到这一题型的高频考察点后再说一遍：{focus}",
                'basis': '依据：库内面试情境资源 exam_focus 标注的考察模式。', 'evidence': task['evidence']}

    # --------------------------------------------------------------------- views
    def _view(self, ctx, document):
        if document is None:
            raise HTTPException(404, '当前学习范围没有这场面试训练会话。')
        tasks = [item for stage in document['stages'] for item in stage['tasks']]
        done = [item for item in tasks if item['state'] == 'done']
        current = next((item for item in tasks if item['state'] != 'done'), None)
        stages = [dict(stage, completed=all(item['state'] == 'done' for item in stage['tasks']),
                       task_count=len(stage['tasks']),
                       tasks=[self._task_view(item) for item in stage['tasks']])
                  for stage in document['stages']]
        return {'session_id': document['session_id'],
                'status': 'completed' if document['completed_at'] else 'in_progress',
                'stages': stages, 'current_task': self._task_view(current) if current else None,
                'answered_tasks': len(done), 'total_tasks': len(tasks),
                'created_at': document['created_at'], 'completed_at': document['completed_at'],
                'notices': ['会话按阶段记录题面、作答、追问与反馈；每个任务只记一次作答，全部完成即结束。',
                            '量规与先修关系未签署前不出正式分数或通过概率；试讲只认你粘贴的转写文本，'
                            '仪态、发音与视频表现不在文字反馈能力内。'],
                **{key: document[key] for key in ('user_id', 'exam_type', 'school_level', 'subject', 'trust_tier')}}

    @staticmethod
    def _task_view(task):
        if task['state'] != 'pending':
            return task
        return {key: value for key, value in task.items() if key not in _HIDDEN_WHILE_PENDING}

    @staticmethod
    def _scope(ctx):
        return {key: getattr(ctx, key) for key in ('user_id', 'exam_type', 'school_level', 'subject')} | {
            'trust_tier': ctx.trust_tier.value}

    @staticmethod
    def _task(document, task_id):
        task = next((item for stage in document['stages'] for item in stage['tasks']
                     if item['task_id'] == task_id), None)
        if task is None:
            raise HTTPException(404, '这场会话没有这个任务。')
        return task

    @staticmethod
    def _guard(ctx):
        if ctx.trust_tier == TrustTier.PUBLISHED:
            raise HTTPException(409, '发布档尚无签署的面试量规与情境资源，训练会话按可信门禁停止；请使用内部研究档。')
        if ctx.exam_type != 'NTCE':
            raise HTTPException(409, '面试是教师资格考试的环节，四六级没有面试训练；请切换到 NTCE 范围。')
