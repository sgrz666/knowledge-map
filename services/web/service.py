"""User-facing workbench. Tools own facts; the model only narrates their results."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from services.common.models import (AnswerSubmission, DiagnosticRequest, ErrorReviewEvent,
    MasterInteractionRequest, PlanRequest, PracticeMode, QARequest, SubjectiveGradingRequest,
    TrustTier, UserIntent)
from services.diagnostic.agent import DiagnosticAgent
from services.grader.agent import SubjectiveGraderAgent
from services.interview.agent import InterviewCoachAgent
from services.knowledge.completeness import audit_ntce
from services.knowledge.graph_index import get_graph_index, library_for_exam
from services.knowledge.repository import get_repository
from services.knowledge.retrieval import get_retrieval_service
from services.knowledge.trust import TrustGate
from services.master.agent import TutorMasterAgent
from services.master.intent_router import IntentRouter
from services.memory.agent import MemoryReviewAgent
from services.memory.receipt import LegacyReceipt, ReceiptConflict, verify_receipt
from services.planner.agent import CurriculumPlannerAgent
from services.practice.agent import PracticeEngineAgent
from services.qa.agent import TutorQAAgent
from services.web.models import DEFAULT_BASE_URL, DEFAULT_MODEL, WebPracticeRequest
from services.web.provider import client_for, narrate
from services.web.store import WorkbenchStore, submission_fingerprint
from services.exam_sessions.service import ExamSessions
from services.learning.workflow import LearningWorkflow
from services.learning.models import PlanCreateRequest


class Workbench:
    def __init__(self):
        self.repo = get_repository()
        self.store = WorkbenchStore()
        self.memory = MemoryReviewAgent(repository=self.repo)
        self.practice_agent = PracticeEngineAgent(repository=self.repo, memory=self.memory)
        self.qa = TutorQAAgent(repository=self.repo)
        self.diagnostic = DiagnosticAgent(repository=self.repo)
        self.planner = CurriculumPlannerAgent(repository=self.repo)
        self.master = TutorMasterAgent(repository=self.repo)
        self.interview_agent = InterviewCoachAgent(repository=self.repo)
        self._audit = None
        self._audit_generation = -1
        self.exam_sessions = ExamSessions(self)
        self.learning = LearningWorkflow(self)

    def bootstrap(self):
        self.repo.stats()
        if self._audit_generation != self.repo.generation:
            self._audit = audit_ntce(self.repo)
            self._audit_generation = self.repo.generation
        specs = self.repo.paper_specs('NTCE')
        names = {(s['school_level'], s['subject']): s['title'].removeprefix('教师资格考试模考规格 - ') for s in specs}
        scopes = [{**s, 'label': names.get((s['school_level'], s['subject']), s['subject'])} for s in self._audit['scopes']]
        graph_nodes, _ = self.repo.graph_records('ntce')
        freq = {}
        for meta in self.repo.find_questions(exams='NTCE'):
            for node in meta.node_ids:
                freq[node] = freq.get(node, 0) + 1
        nodes = [{ 'id': n['id'], 'name': n.get('name') or n.get('title') or n['id'], 'count': freq.get(n['id'], 0)}
                 for n in graph_nodes if n.get('type') == 'knowledge_node']
        cet_graph, _ = self.repo.graph_records('cet')
        exams_by_node = {}
        for meta in self.repo.find_questions(exams=['CET-4', 'CET-6']):
            for nid in meta.node_ids:
                exams_by_node.setdefault(nid, set()).add(meta.exam)
        cet_nodes = [{'id': n['id'], 'name': n.get('name') or n.get('title') or n['id'],
                      'exams': sorted(exams_by_node.get(n['id'], set()))}
                     for n in cet_graph if n.get('type') == 'knowledge_node']
        return {'defaults': {'base_url': DEFAULT_BASE_URL, 'model': DEFAULT_MODEL},
                'library': self._audit, 'scopes': scopes, 'nodes': nodes, 'cet_nodes': cet_nodes,
                'paper_specs': [{'spec_id': s['spec_id'], 'title': s['title'], 'school_level': s.get('school_level'),
                                 'subject': s.get('subject')} for s in specs]}

    def question(self, qid, tier):
        record = self.repo.load_question(qid)
        if record is None:
            raise HTTPException(404, '题目不在库内')
        verdict = TrustGate(tier).classify_record(record)
        if not verdict.servable_in_paper:
            raise HTTPException(409, {'code': 'question_not_servable',
                                      'message': '该内容当前处于隔离、缺答案或待发布核定状态'})
        return record

    def practice(self, req):
        data = self.practice_agent.assemble_paper(req).model_dump(mode='json')
        # Distinct attempts have distinct identities even if deterministic sampling repeats.
        data['paper_id'] = 'web-' + uuid.uuid4().hex
        data['created_at'] = datetime.now(timezone.utc).isoformat()
        data['school_level'], data['subject'] = req.school_level, req.subject
        # 卷面要把考点带回去：前端"换一批"读的是 paper.target_node，读不到就退回下拉框的值（常常是空），
        # 考点专练那一卷会被换成整池抽题，学习者看不到自己还在同一个考点上。
        data['target_node'] = req.target_node
        if req.practice_mode == 'mock_exam':
            data['title'] = '【结构模拟练习】' + req.exam_type + ' · 整卷计时'
            data['notices'].append('网页按真实规格组卷并整卷计时，尚未执行逐节收卡和强制音频播放，不属于严格全真模考。')
        for item in data['questions']:
            item.pop('answer', None)
            material = self.repo.load_material(item.get('material_id'))
            item['material_text'] = (material or {}).get('text', '')
            if not item['material_text'] and req.exam_type.startswith('CET'):
                item['material_text'] = (self.repo.reading_passage(item['question_id']) or {}).get('text', '')
            record = self.repo.load_question(item['question_id']) or {}
            audio = (record.get('extra') or {}).get('audio') or {}
            if audio:
                if self.repo.audio_path(item['question_id']):
                    item['audio_url'] = '/api/v1/web/audio/' + item['question_id']
                    item['audio_notice'] = '提供源音频整段播放；库内切片时间未经逐段核对，不强制按估算切片播放。'
                else:
                    item['audio_notice'] = '该题有听力元数据，但本机未找到音频文件；请先恢复原始音频资料。'
            if self.repo.has_unavailable_figure(item['question_id']):
                item['input_blocked'] = True
                item['media_notice'] = '题干依赖图示，但当前库没有可展示的图像。补齐原图前仅供查看，不提交、不记对错。'
        if data['practice_mode'] == 'mock_exam':
            data['notices'].append('题面抽取或可信门禁可能造成缺题；本卷不提供官方报告分。')
        self.store.save_paper(req.user_id, data)
        return data

    def submit(self, req):
        fp = submission_fingerprint(req)
        event_id = f'{req.paper_id}:{req.question_id}'
        with self.store.lock:
            paper = self.store.paper(req.user_id, req.paper_id)
            if paper is None:
                raise HTTPException(404, '当前学习者没有这份练习卷')
            if req.trust_tier.value != paper['trust_tier']:
                raise HTTPException(409, {'code': 'paper_tier_mismatch',
                    'message': '练习卷与当前内容档位不一致，请在当前档位重新组卷。'})
            if req.question_id not in {q['question_id'] for q in paper['questions']}:
                raise HTTPException(400, '提交的题目不属于这份练习卷')
            self.exam_sessions.guard_submission(req, paper)
            try:
                receipt = self.store.submission_receipt(req.paper_id, req.question_id)
                if receipt is not None:
                    # 已经记下的这次作答只按原参数回放。参数改过就不是同一次作答：把旧的"答错了"
                    # 交还给一份新答案，页面会同时写着答对、记着答错；重跑又把同一题计成两次。
                    verify_receipt(event_id, receipt[1], fp)
                    return self.exam_sessions.mask_submission(req.paper_id, receipt[0])
                record = self.question(req.question_id, paper['trust_tier'])
                if self.repo.has_unavailable_figure(req.question_id):
                    raise HTTPException(409, {'code': 'figure_unavailable',
                        'message': '题干依赖图示，当前缺少原图，暂不接受作答。'})
                meta = self.repo.get_meta(req.question_id)
                checked, source, notices = TrustGate(paper['trust_tier']).reconcile_verdict(record, req.answer, None)
                response = {'paper_id': req.paper_id, 'question_id': req.question_id, 'user_answer': req.answer,
                            'is_correct': checked, 'verdict_source': source, 'notices': list(notices),
                            'time_spent_seconds': req.time_spent_seconds, 'review': None, 'grading': None,
                            'node_ids': list(meta.node_ids), 'exam_type': paper['exam_type']}
                if checked is not None and meta.node_ids:
                    bundles = []
                    for index, node in enumerate(meta.node_ids):
                        event = ErrorReviewEvent(user_id=req.user_id, question_id=req.question_id, node_id=node,
                            exam=paper['exam_type'], is_correct=checked, selected_option=req.answer,
                            time_spent_seconds=req.time_spent_seconds, option_flip_count=req.option_flip_count,
                            has_negation_in_stem=any(word in (record.get('content') or {}).get('stem', '') for word in ('不正确', '不属于', '错误')))
                        bundles.append(self.memory.process_event(event, record_attempt=index == 0,
                            event_id=f'{event_id}:{node}').model_dump(mode='json'))
                    response['review'] = bundles[0]
                    response['reviews'] = bundles
                elif meta.question_type not in ('单选', '多选'):
                    response['grading'] = SubjectiveGraderAgent(repository=self.repo).grade(SubjectiveGradingRequest(
                        question_id=req.question_id, exam_type=paper['exam_type'],
                        task_type=self._task_type(meta.question_type, paper['exam_type']),
                        stem=(record.get('content') or {}).get('stem', ''), student_answer=req.answer,
                        trust_tier=TrustTier(paper['trust_tier']))).model_dump(mode='json')
                response['explanation'] = self.qa.answer_query(QARequest(user_id=req.user_id, question_id=req.question_id,
                    user_selected_option=req.answer if checked is not None else None,
                    trust_tier=TrustTier(paper['trust_tier']))).model_dump(mode='json')
                response['submitted_at'] = datetime.now(timezone.utc).isoformat()
                self.store.save_submission(req.paper_id, req.question_id, response, fp)
                return self.exam_sessions.mask_submission(req.paper_id, response)
            except LegacyReceipt as legacy:
                # 无指纹的旧收据：沿用原参数重试也永远过不去，前端就不该再挂一个"重试提交"。
                raise HTTPException(409, {'code': 'legacy_receipt', 'message': str(legacy)}) from legacy
            except ReceiptConflict as conflict:
                raise HTTPException(409, {'code': 'receipt_conflict', 'message': str(conflict)}) from conflict

    @staticmethod
    def _task_type(qtype, exam):
        if qtype in ('作文', '写作'):
            return 'writing' if exam == 'NTCE' else 'short_essay'
        return {'材料分析': 'case_analysis', '简答': 'short_answer', '教学设计': 'lesson_plan',
                '活动设计': 'lesson_plan', '翻译': 'paragraph_translation'}.get(qtype, 'case_analysis')

    def profile(self, ctx):
        if ctx.trust_tier == TrustTier.PUBLISHED:
            diagnostic = self.diagnostic.evaluate(DiagnosticRequest(user_id=ctx.user_id, exam_type=ctx.exam_type,
                submissions=[], trust_tier=ctx.trust_tier)).model_dump(mode='json')
            return {'mastery': [], 'diagnostic': diagnostic, 'wrong_questions': [], 'due_question_ids': [],
                    'submissions': [], 'latest_paper': None, 'latest_paper_submissions': []}
        nodes = {n for m in self.repo.find_questions(exams=ctx.exam_type, school_level=ctx.school_level,
                    subject=ctx.subject) for n in m.node_ids}
        records = [r.model_dump(mode='json') for n in sorted(nodes)
                   if (r := self.memory.get_user_mastery(ctx.user_id, n)) is not None]
        submissions = [s for s in self.store.submissions(ctx.user_id)
                       if s.get('exam_type') == ctx.exam_type and set(s.get('node_ids', [])) & nodes]
        submissions = [self.exam_sessions.mask_submission(s['paper_id'], s) for s in submissions]
        inputs = [AnswerSubmission(question_id=s['question_id'], user_answer=s['user_answer'],
                  time_spent_seconds=s['time_spent_seconds']) for s in submissions]
        diagnostic = self.diagnostic.evaluate(DiagnosticRequest(user_id=ctx.user_id, exam_type=ctx.exam_type,
                     submissions=inputs, trust_tier=ctx.trust_tier)).model_dump(mode='json')
        wrong = [e for e in self.memory.store.error_entries(ctx.user_id) if e.get('node_id') in nodes]
        due = [qid for qid in self.memory.due_question_ids(ctx.user_id, limit=100)
               if (self.repo.get_meta(qid) and set(self.repo.get_meta(qid).node_ids) & nodes)]
        latest = self.store.latest_paper(ctx.user_id, exam=ctx.exam_type, school_level=ctx.school_level,
                                       subject=ctx.subject, trust_tier=ctx.trust_tier.value)
        return {'mastery': records, 'diagnostic': diagnostic, 'wrong_questions': wrong,
                'due_question_ids': due, 'submissions': submissions, 'latest_paper': latest,
                'latest_paper_submissions': [self.exam_sessions.mask_submission(latest['paper_id'], s)
                    for s in self.store.paper_submissions(latest['paper_id'])] if latest else []}

    def chat(self, req):
        if req.trust_tier == TrustTier.PUBLISHED:
            trace = []
            self._step(trace, '档位判定',
                       '发布档只放行教研具名签署且版权可外发的内容；当前库内签署数为 0，按封版口径直接拒答：不检索、不请求模型。')
            return {'reply': TrustGate('published').fail_closed()['message'],
                    'sources': [], 'tool_result': {}, 'intent': 'general_chat', 'trace': trace,
                    'session_id': req.session_id or 'web-chat-' + uuid.uuid4().hex,
                    'notices': [], 'trust_tier': 'published',
                    'model': {'mode': 'rule_only', 'ok': False, 'errors': ['当前无具名签署题，不请求模型。']}}
        payload = dict(req.action_payload or {})
        payload.update(school_level=req.school_level, subject=req.subject)
        intent, intent_reason = IntentRouter.classify_with_reason(req.message, payload)
        declared_node = str(payload.get('node_id') or payload.get('target_node') or '')
        # 知识点页的"请助手讲解"把考点名嵌进句子里发过来，而库内考点名本身就含"教学设计""教案"这类词，
        # 会被面试关键词抢走，这一轮就进了面试状态机而不是考点问答。载荷带着考点说明问的是考点；
        # 显式声明过 intent 的照旧采信（前端知道自己按的是哪个按钮）。
        if declared_node and not payload.get('intent') and intent in (
                UserIntent.INTERVIEW_PRACTICE, UserIntent.SUBMIT_SUBJECTIVE, UserIntent.ERROR_REVIEW):
            intent_reason += f' 但这一轮带着考点 {declared_node}，按考点问答处理，不进 {intent.value} 那条闭环。'
            intent = UserIntent.GENERAL_CHAT
        sources, related, notices, tools, trace = [], [], [], {}, []
        reply, session_id = '', req.session_id
        self._step(trace, '判定意图', intent_reason, {'intent': intent.value})
        self._step(trace, '划定范围',
                   f"{req.exam_type} · {req.school_level or '全部学段'} · {req.subject or '全部科目'} · 档位 {req.trust_tier.value}；"
                   '检索、组卷与来源装配只在这个范围内取库内记录。')
        # 答案可见性只认学习者自己的作答记录：答过的题才把答案与解析交给前端和模型。
        answered = self.store.answered_question_ids(req.user_id)
        if req.question_id:
            record = self.question(req.question_id, req.trust_tier.value)
            verdict = TrustGate(req.trust_tier.value).classify_record(record)
            self._step(trace, '取出这道题',
                       f'{req.question_id} 通过可信门禁：复核 {verdict.review_status} · 答案 {verdict.answer_status} · 可见性 {verdict.answer_visibility}。')
            is_answered = req.question_id in answered
            # 没提交过的题走苏格拉底引导：Sparks 链的答案可见性只由档位与答案状态决定，
            # 不认学习者有没有作答，直接拿它的讲解文本当回复就等于在练习之前把答案说出来。
            # hint_turn 固定 1：引导链到第 3 轮就自己报参考答案了。
            tools = self.qa.answer_query(QARequest(user_id=req.user_id, question_id=req.question_id,
                         user_query=req.message, trust_tier=req.trust_tier, hint_turn=1,
                         mode='sparks_three_chain' if is_answered else 'socratic_hint')).model_dump(mode='json')
            self._step(trace, '走答疑链路',
                       ('这道题你提交过，Sparks 链按库内答案状态给出完整讲解与参考答案。' if is_answered else
                        '这道题你还没提交，只走苏格拉底引导第 1 步：给题干线索与选项辨析的路子，不给参考答案。'),
                       {'mode': 'sparks_three_chain' if is_answered else 'socratic_hint',
                        'answer_visibility': tools.get('answer_visibility'),
                        'hint_turn': tools.get('hint_turn'),
                        'grounded_in_library': tools.get('grounded_in_library')})
            sources = self._sources([req.question_id], req.trust_tier.value, answered, req.exam_type)
            content = record.get('content') or {}
            keys = ('stem', 'answer', 'reference_answer') if is_answered else ('stem',)
            tools['question'] = {k: v for k, v in content.items() if k in keys}
            if is_answered:
                reply = tools.get('explanation_summary', '')
            else:
                reply = f"{tools.get('guiding_question', '')}\n\n{tools.get('scaffold_prompt', '')}".strip()
                notices.append('这道题你还没作答，所以先给引导不给答案；提交之后再问，就会带上库内参考答案与解析。')
        elif intent == UserIntent.PLAN:
            days = self._bounded(payload.get('days_until_exam'), 30, 1, 180)
            minutes = self._bounded(payload.get('daily_available_minutes'), 60, 15, 360)
            # 幂等号由这句话本身算出：前端没有带 request_id，随机 id 会让同一句话每次点都生成新计划，
            # 新计划立刻成为 latest，学习者已经推进过的那份就在学习计划页消失了。
            request_id = 'chat-' + hashlib.sha256(
                f"{req.session_id or req.user_id}|{req.message}".encode('utf-8')).hexdigest()[:16]
            self._step(trace, '排学习计划',
                       f"距考 {days} 天 · 每天 {minutes} 分钟，取自本次动作载荷（没带就按 30 天 / 60 分钟，并如实说明）。",
                       {'request_id': request_id})
            tools = self.learning.create_plan(PlanCreateRequest(user_id=req.user_id, exam_type=req.exam_type,
                school_level=req.school_level, subject=req.subject, trust_tier=req.trust_tier,
                request_id=request_id, days_until_exam=days, daily_available_minutes=minutes))['plan']
            reply = f"已生成 {tools['total_days']} 天学习计划，可到“学习计划”查看并执行。"
            self._step(trace, '计划结果', f"{tools['total_days']} 天排课完成。",
                       {'plan_id': tools.get('plan_id'), 'total_tasks': tools.get('total_tasks')})
        elif intent == UserIntent.PRACTICE:
            practice_req, mode_note = self._chat_practice(req, payload)
            self._step(trace, '按请求组卷', mode_note,
                       {'practice_mode': practice_req.practice_mode, 'item_count': practice_req.item_count,
                        'rotation': practice_req.rotation})
            tools = self.practice(practice_req)
            reply = f"已组好 {tools['total_items']} 道题，可到“练习与模考”继续作答。"
            self._step(trace, '这一批题的来路',
                       f"批次由种子 {tools.get('selection_seed')} 洗出：同一轮次可原样复现，换一批（轮次 +1）就换题。",
                       {'selection_seed': tools.get('selection_seed'), 'pool_size': tools.get('pool_size'),
                        'notices': tools.get('notices', [])})
        elif intent == UserIntent.DIAGNOSTIC:
            profile_rows = self.profile(req)
            tools = profile_rows['diagnostic']
            reply = tools['disclaimer']
            self._step(trace, '算学情',
                       f"雷达与薄弱项只按本机已有记录算：作答 {len(profile_rows['submissions'])} 条 · "
                       f"掌握度 {len(profile_rows['mastery'])} 项 · 到期错题 {len(profile_rows['due_question_ids'])} 题；"
                       '没有作答时只给说明，不编造水平。',
                       {'weak_points_top5': tools.get('weak_points_top5', [])})
        elif req.action_payload and intent in (UserIntent.INTERVIEW_PRACTICE, UserIntent.SUBMIT_SUBJECTIVE, UserIntent.ERROR_REVIEW):
            result = self.master.handle_interaction(MasterInteractionRequest(user_id=req.user_id, message=req.message,
                exam_type=req.exam_type, trust_tier=req.trust_tier, session_id=req.session_id, action_payload=payload))
            tools = result.card_data
            reply = result.reply_text
            # 编排会话的说明与 session_id 必须一起回到前端：丢掉它们，网页侧既看不到降级原因，也无法回放这一轮。
            notices += [str(n) for n in (result.notices or [])]
            session_id = result.session_id or req.session_id
            self._step(trace, '交给编排状态机',
                       f"意图 {result.detected_intent.value} 进入闭环，本轮停在 {result.state}，会话 {result.session_id}。")
            for row in result.trace:
                body = row.get('payload') or {}
                self._step(trace, '编排 · ' + str(body.get('state') or row.get('action') or ''),
                           str(body.get('summary') or '（该跳没有文字结论）'),
                           {'action': row.get('action'), 'sender': row.get('sender'), 'recipient': row.get('recipient'),
                            'notices': row.get('notices') or [],
                            'generated_by': (row.get('generated_by') or {}).get('mode'),
                            'evidence_count': len(row.get('evidence') or [])})
        else:
            retrieval = get_retrieval_service().search(req.message, exam=req.exam_type,
                tier=req.trust_tier.value, user_id=req.user_id, k=20,
                levels=[req.school_level] if req.school_level else None)
            blocked = retrieval.get('blocked', [])
            self._step(trace, '向量召回 + 可信门禁',
                       f"后端 {retrieval['backend']} · 命中库 {', '.join(retrieval.get('libraries', []))} · "
                       f"可比对 {retrieval.get('candidate_count', 0)} 题，按分数取前 {len(retrieval.get('candidates', []))} 题进入下一步"
                       f" · 被门禁拦下 {len(blocked)} 题。",
                       {'candidate_count': retrieval.get('candidate_count'),
                        'returned': len(retrieval.get('candidates', [])),
                        'blocked': blocked[:5], 'notices': retrieval.get('notices', [])})
            if blocked:
                self._step(trace, '为什么那些题没出现', '；'.join(
                    f"{row.get('question_id')}：{row.get('reason')}" for row in blocked[:3]))
            in_scope = []
            for candidate in retrieval.get('candidates', []):
                meta = self.repo.get_meta(candidate['question_id'])
                if meta is None:
                    continue  # 索引换代竞态：卡片还认这个题号，题索引已经不再收录它
                if req.subject and meta.subject != req.subject:
                    continue
                in_scope.append((candidate, meta))
            self._step(trace, '按当前科目收窄',
                       f"召回 {len(retrieval.get('candidates', []))} 题中，属于「{req.subject or '当前范围'}」的有 {len(in_scope)} 题。")
            qids = [candidate['question_id'] for candidate, _ in in_scope][:4]
            sources = self._sources(qids, req.trust_tier.value, answered, req.exam_type)
            # Exact syllabus clauses outrank weak lexical card matches for concept questions.
            clause_sources, matched_nodes, core = self._concept_clauses(req)
            # 知识点页知道自己打开的是哪个考点；把它带进来，真题就按这个考点装配，而不是只靠话里的词。
            declared_nodes = [str(n) for n in (payload.get('node_id'), payload.get('target_node')) if n]
            sources = clause_sources + [s for s in sources if s['id'] not in {c['id'] for c in clause_sources}]
            self._step(trace, '锚定考点与考纲条款',
                       (f"从「{core}」命中库内考点 {len(matched_nodes)} 个，取到可引用条款 {len(clause_sources)} 条。"
                        if core else '这句话没有提出可锚定的考点词，只按检索命中给依据。')
                       + (f" 页面还带着当前考点 {len(declared_nodes)} 个，按它装配真题。" if declared_nodes else ''),
                       {'core': core, 'matched_nodes': list(matched_nodes)[:8], 'declared_nodes': declared_nodes[:4],
                        'clause_ids': [row['id'] for row in clause_sources]})
            related = self._related_questions(req, list(matched_nodes) + declared_nodes,
                [n for _, meta in in_scope[:4] for n in meta.node_ids],
                {s['id'] for s in sources if s.get('kind') == 'question'}, answered)
            tools = {'retrieval_backend': retrieval['backend'], 'evidence': sources,
                     'related_question_count': len(related)}
            notices += retrieval.get('notices', [])
            if clause_sources:
                reply = '当前考纲中的相关要求：\n' + '\n'.join(s['text'] for s in clause_sources[:3]) + '\n\n当前为规则检索，未配置模型时先展示原文依据；可连接 DeepSeek 进一步解释。'
            elif sources:
                reply = '找到以下相关材料：\n' + '\n'.join(s['title'] for s in sources[:3]) + '\n\n当前为规则检索，这些材料需要结合你的问题辨析，不把某一道题的解析直接当作概念问题的答案。'
            else:
                reply = '当前范围没有召回可用证据。可换一个具体考点、扩大科目范围，或先完成练习。'
            if related:
                # 出处用库内考点名说清楚：只报题号，学习者不知道自己练的是哪一条线索。
                anchored = list(matched_nodes) + declared_nodes
                carried = list(dict.fromkeys(n for row in related for n in row.get('matched_nodes', [])))
                # 锚到考点不等于题挂在那个考点上：模块级考点名下常常没有直接考查题，
                # 这批真题其实是按题目自己挂的叶子考点装配的，报成锚到的那个就是谎报来路。
                names = '、'.join(self._node_names(carried, req.exam_type)[:2]) \
                    or '、'.join(self._node_names(anchored, req.exam_type)[:2])
                origin = '按考点' if set(carried) & set(anchored) else '按这批真题所挂的考点'
                reply += (f"\n\n{origin}「{names or related[0].get('id')}」装配了 {len(related)} 道真题，"
                          '题面与卷面出处已附在下方“相关真题”。')
                if anchored and not set(carried) & set(anchored):
                    notices.append('锚到的考点名下没有直接考查题，这批真题取自它的下级考点；'
                                   '按考点组卷请用下方真题标注的那个考点。')
                if any(row.get('answer_withheld') for row in related):
                    notices.append('相关真题只主题面与出处：这些题你还没作答，答案与解析不会在练习之前给出。')
        notices += [str(n) for n in (tools.get('notices') or [])] if isinstance(tools, dict) else []
        allowed = {s['id'] for s in sources} | {row['id'] for row in related}
        # Keep tool summaries bounded; no Key or visitor-supplied authority fields enter facts.
        context = {'exam_type': req.exam_type, 'school_level': req.school_level, 'subject': req.subject,
                   'tool_result': json.dumps(tools, ensure_ascii=False, default=str)[:24000],
                   'sources': sources, 'history': [{'role': h.get('role'), 'content': str(h.get('content', ''))[:2000]}
                                                 for h in req.history[-6:]]}
        model, generated = narrate(client_for(req.model_config_input), req.message, context, allowed, user_id=req.user_id)
        self._step(trace, '请求模型并校验引用', self._model_note(model, generated),
                   {'mode': model.get('mode'), 'ok': model.get('ok'), 'errors': model.get('errors'),
                    'provenance': model.get('provenance'), 'citable_source_count': len(allowed)})
        self._step(trace, '定稿',
                   '模型答复通过引用校验时展示模型文本；否则展示上面这些工具与依据直接拼出的规则答复，两者都带来源。',
                   {'answered_by': 'model' if generated else 'tools'})
        return {'reply': generated or reply, 'model': model, 'sources': sources, 'tool_result': tools,
                'related_questions': related,
                'intent': intent.value, 'trace': trace,
                'session_id': session_id or 'web-chat-' + uuid.uuid4().hex,
                'notices': list(dict.fromkeys(notices)), 'trust_tier': req.trust_tier.value}

    @staticmethod
    def _step(trace, action, detail, data=None):
        """One readable hop of this turn's reasoning.

        写这一行的只有工具已经算出来的事实：意图判定给出命中的关键词，检索给出候选数与被门禁拦下的原因，
        模型步骤给出实际连上的型号与用时。没有事实支撑的推测不进这一列，前端也就没有可展示的思考过程。
        """
        row = {'action': action, 'detail': detail}
        if data:
            row['data'] = data
        trace.append(row)

    @staticmethod
    def _bounded(value, default, low, high):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return max(low, min(high, number))

    @staticmethod
    def _model_note(model, generated):
        provenance = model.get('provenance') or {}
        head = '模型答复通过引用校验，本次展示模型文本。' if generated else '模型答复未采用，展示工具与依据拼出的规则答复。'
        if model.get('mode') != 'llm':
            return head + ' ' + '；'.join(str(e) for e in (model.get('errors') or ['本机未配置 Key，走规则功能。']))
        parts = [f"模型 {provenance.get('response_model') or model.get('model') or '未回传型号'}"]
        if provenance.get('latency_ms') is not None:
            parts.append(f"用时 {provenance['latency_ms']}ms")
        if provenance.get('retries'):
            parts.append(f"重试 {provenance['retries']} 次")
        if model.get('errors'):
            parts.append('；'.join(str(e) for e in model['errors']))
        return head + ' ' + ' · '.join(parts)

    def _chat_practice(self, req, payload):
        """聊天里的组卷参数交给练习引擎：越界值先夹回允许区间，缺参改走可完成的模式并说明。"""
        mode = str(payload.get('practice_mode') or PracticeMode.DAILY_PRACTICE.value)
        warning = ''
        if mode not in {m.value for m in PracticeMode}:
            warning = f"载荷里的练习模式「{mode}」不在库内模式之中，按每日一练出题。"
            mode = PracticeMode.DAILY_PRACTICE.value
        profile_rows = self.profile(req) if mode in (PracticeMode.WEAKNESS_BREAKTHROUGH.value,
                                                     PracticeMode.ERROR_ELIMINATION.value) else None
        node = str(payload.get('target_node') or '').strip() or None
        if mode == PracticeMode.POINT_FOCUS.value and not node:
            warning = '考点专练需要指定考点，本次没有带上，改按每日一练出题。'
            mode = PracticeMode.DAILY_PRACTICE.value
        weak = [str(n) for n in (payload.get('weak_node_ids') or
                                 ((profile_rows or {}).get('diagnostic') or {}).get('weak_points_top5') or [])][:20]
        wrong = [str(q) for q in (payload.get('wrong_question_ids') or
                                  (profile_rows or {}).get('due_question_ids') or [])][:50]
        avoid = [str(q) for q in (payload.get('avoid_question_ids') or [])][:200]
        practice_req = WebPracticeRequest(user_id=req.user_id, exam_type=req.exam_type,
            school_level=req.school_level, subject=req.subject, trust_tier=req.trust_tier,
            practice_mode=mode, item_count=self._bounded(payload.get('item_count'), 5, 1, 100),
            target_node=node, weak_node_ids=weak, wrong_question_ids=wrong,
            spec_id=str(payload.get('spec_id') or '') or None,
            rotation=self._bounded(payload.get('rotation'), 0, 0, 999), avoid_question_ids=avoid)
        detail = (f"模式 {mode} · {practice_req.item_count} 题"
                  + (f" · 考点 {node}" if node else '') + (f" · 薄弱考点 {len(weak)} 个" if weak else '')
                  + (f" · 待回炉错题 {len(wrong)} 题" if wrong else '') + (f" · 卷面规格 {practice_req.spec_id}" if practice_req.spec_id else '')
                  + f" · 轮次 {practice_req.rotation}" + (f" · 避开上一批 {len(avoid)} 题" if avoid else ''))
        return practice_req, ((warning + ' ' + detail) if warning else detail)

    def _concept_clauses(self, req):
        core = re.sub(r'^(什么是|请解释|解释一下|如何理解|怎么理解|讲讲|介绍一下)', '', req.message).strip('？?。！! ')
        # 学习者常在考点名后面接一句诉求（"教师职业道德规范，并说明作答思路"），逗号不切开就把考点名污染成整句话，
        # 名字匹配永远落空——网页上"请助手讲解"给的正是这个句式。
        core = re.split(r'[？?。；;，,]', core)[0].strip()
        core = re.sub(r'(有什么区别|是什么意思|是什么)$', '', core).strip()
        scope_nodes: set = set()
        if len(core) < 2 or len(core) > 30:
            return [], scope_nodes, core
        scope_ids = {rid for m in self.repo.find_questions(exams=req.exam_type,
                     school_level=req.school_level, subject=req.subject) for rid in m.requirement_ids}
        matched_node_requirements = set()
        # Nodes without questions still have syllabus evidence and can be studied.
        if req.exam_type == 'NTCE':
            nodes, edges = self.repo.graph_records('ntce')
            prefix = 'ntce.' + (req.school_level + '.' if req.school_level else '')
            node_ids = {n['id'] for n in nodes if n.get('type') == 'knowledge_node'
                        and n['id'].startswith(prefix)
                        and (not req.subject or ('.' + req.subject + '.') in n['id'])}
            scope_ids.update(e['src'] for e in edges if e.get('type') == 'aligned_to_requirement'
                             and e['dst'] in node_ids)
            named = [(n['id'], n.get('name') or n.get('title') or '') for n in nodes if n['id'] in node_ids]
            matching = {nid for nid, name in named if core in name}
            if not matching:
                # 考点名被嵌在句子里时（"小学综合素质中的教师职业道德规范"）正向取不到，反过来用名字量这句话。
                # 库内考点名最短 3 字（教育观、教师观），再放短就会把整层节点都捞进来。
                hits = sorted({name for _, name in named if len(name) >= 3 and name in core}, key=len, reverse=True)[:3]
                matching = {nid for nid, name in named if name in hits}
            scope_nodes = matching
            matched_node_requirements = {e['src'] for e in edges if e.get('type') == 'aligned_to_requirement'
                                        and e['dst'] in matching}
        gate = TrustGate(req.trust_tier.value)
        rows = []
        for rid in sorted(scope_ids):
            record = self.repo.get_requirement(rid)
            text = (record or {}).get('content') or (record or {}).get('text') or (record or {}).get('title', '')
            if (core in text or rid in matched_node_requirements) and gate.classify_requirement(record).citable:
                rows.append({'id': rid, 'kind': 'requirement', 'relation': 'syllabus_clause', 'title': text[:100],
                             'text': text[:2500], 'standard_id': record.get('standard_id'),
                             'locator': record.get('locator'), 'source_url': record.get('source_url')})
        return rows[:4], scope_nodes, core

    def _node_names(self, node_ids, exam=None):
        """考点 id → 库内考点名：前端展示真题出处时不能只给一串 id。"""
        node_ids = [n for n in dict.fromkeys(node_ids) if n]
        if not node_ids:
            return []
        index = get_graph_index(library_for_exam(exam) or 'ntce')
        names = []
        for node_id in node_ids[:6]:
            record = index.node(node_id) or {}
            names.append(record.get('name') or record.get('title') or node_id)
        return names

    def _related_questions(self, req, primary_nodes, secondary_nodes, exclude, answered, limit=6):
        """把考点装配成可练真题：同一考点、当前档位可外发、题面可答的那些题。

        题面与出处永远给，答案只在该学习者答过这道题之后才给——附真题是为了练，不是为了剧透。
        """
        weights = {node_id: 1 for node_id in dict.fromkeys(n for n in secondary_nodes if n)}
        primary = list(dict.fromkeys(n for n in primary_nodes if n))
        weights.update({node_id: 2 for node_id in primary})
        if not weights:
            return []
        # 模块级考点名下常常一道题都不直接挂，题挂在它的下级考点上（id 就是父考点再加一段）；
        # 只按精确匹配，学习者问的那个考点就会退化成"向量召回顺带捞到的题"。
        prefixes = tuple(node_id + '.' for node_id in primary)

        def node_weight(node_id):
            if node_id in weights:
                return weights[node_id]
            return 2 if node_id.startswith(prefixes) else 0

        gate = TrustGate(req.trust_tier.value)
        scored = []
        for meta in self.repo.find_questions(exams=req.exam_type, school_level=req.school_level, subject=req.subject):
            if meta.question_id in exclude or not meta.has_answerable_text:
                continue
            hits = [(node_id, node_weight(node_id)) for node_id in meta.node_ids]
            score = sum(weight for _, weight in hits)
            if score and gate.classify_meta(meta).servable_in_paper:
                scored.append((score, meta.question_id, meta, [node_id for node_id, weight in hits if weight]))
        scored.sort(key=lambda row: (-row[0], row[1]))
        rows = []
        for score, question_id, meta, matched in scored:
            if len(rows) >= limit:
                break
            row = self._question_row(question_id, req.trust_tier.value, answered, gate, 'same_node', req.exam_type)
            if row is None:
                continue
            # 前端"按这个考点组一张练习卷"直接拿 matched_nodes[0] 去组卷，所以这里必须是题真挂着的考点。
            row['matched_nodes'] = matched
            row['node_names'] = self._node_names(meta.node_ids, req.exam_type)
            rows.append(row)
        return rows

    def _question_row(self, qid, tier, answered, gate, relation, exam=None):
        record = self.repo.load_question(qid)
        if record is None:
            return None
        verdict = gate.classify_record(record)
        if not verdict.servable_in_paper:
            return None
        meta = self.repo.get_meta(qid)
        content = record.get('content') or {}
        explanation = record.get('analysis') or {}
        if isinstance(explanation, dict):
            explanation = explanation.get('explanation') or explanation.get('trace_back') or ''
        row = {'id': qid, 'kind': 'question', 'relation': relation,
               'title': content.get('stem', '')[:110], 'stem': content.get('stem', '')[:3500],
               'question_type': meta.question_type if meta else None,
               'exam': meta.exam if meta else None, 'section': meta.section if meta else None,
               'school_level': meta.school_level if meta else None, 'subject': meta.subject if meta else None,
               'review_status': meta.review_status if meta else verdict.review_status,
               'answer_status': meta.answer_status if meta else verdict.answer_status,
               'answer_visibility': verdict.answer_visibility,
               'source': record.get('source'),
               'node_ids': list(meta.node_ids) if meta else [],
               'node_names': self._node_names(meta.node_ids if meta else [], exam)}
        if qid in answered:
            row['answer'] = content.get('answer') or content.get('reference_answer')
            row['explanation'] = str(explanation)[:2500]
        else:
            row['answer_withheld'] = True
        return row

    def _sources(self, qids, tier, answered, exam=None):
        sources = []
        seen = set()
        gate = TrustGate(tier)
        for qid in qids:
            row = self._question_row(qid, tier, answered, gate, 'vector_recall', exam)
            if row is None:
                continue
            sources.append(row)
            meta = self.repo.get_meta(qid)
            for rid in (meta.requirement_ids[:5] if meta else []):
                req = self.repo.get_requirement(rid)
                if rid in seen or not req or not gate.classify_requirement(req).citable:
                    continue
                seen.add(rid)
                sources.append({'id': rid, 'kind': 'requirement', 'relation': 'same_requirement',
                    'title': req.get('title') or req.get('text', '')[:100],
                    'text': (req.get('content') or req.get('text') or req.get('title', ''))[:2500], 'standard_id': req.get('standard_id'),
                    'locator': req.get('locator'), 'source_url': req.get('source_url')})
        return sources
