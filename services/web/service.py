"""User-facing workbench. Tools own facts; the model only narrates their results."""
import json
import re
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from services.common.models import (AnswerSubmission, DiagnosticRequest, ErrorReviewEvent,
    MasterInteractionRequest, PlanRequest, QARequest, SubjectiveGradingRequest, TrustTier, UserIntent)
from services.diagnostic.agent import DiagnosticAgent
from services.grader.agent import SubjectiveGraderAgent
from services.knowledge.completeness import audit_ntce
from services.knowledge.repository import get_repository
from services.knowledge.retrieval import get_retrieval_service
from services.knowledge.trust import TrustGate
from services.master.agent import TutorMasterAgent
from services.master.intent_router import IntentRouter
from services.memory.agent import MemoryReviewAgent
from services.memory.receipt import ReceiptConflict, verify_receipt
from services.planner.agent import CurriculumPlannerAgent
from services.practice.agent import PracticeEngineAgent
from services.qa.agent import TutorQAAgent
from services.web.models import DEFAULT_BASE_URL, DEFAULT_MODEL, WebPracticeRequest
from services.web.provider import client_for, narrate
from services.web.store import WorkbenchStore, submission_fingerprint


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
        self._audit = None
        self._audit_generation = -1

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
            raise HTTPException(409, '该内容当前处于隔离、缺答案或待发布核定状态')
        return record

    def practice(self, req):
        data = self.practice_agent.assemble_paper(req).model_dump(mode='json')
        # Distinct attempts have distinct identities even if deterministic sampling repeats.
        data['paper_id'] = 'web-' + uuid.uuid4().hex
        data['created_at'] = datetime.now(timezone.utc).isoformat()
        data['school_level'], data['subject'] = req.school_level, req.subject
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
                raise HTTPException(409, '练习卷与当前内容档位不一致，请在当前档位重新组卷。')
            if req.question_id not in {q['question_id'] for q in paper['questions']}:
                raise HTTPException(400, '提交的题目不属于这份练习卷')
            try:
                receipt = self.store.submission_receipt(req.paper_id, req.question_id)
                if receipt is not None:
                    # 已经记下的这次作答只按原参数回放。参数改过就不是同一次作答：把旧的"答错了"
                    # 交还给一份新答案，页面会同时写着答对、记着答错；重跑又把同一题计成两次。
                    verify_receipt(event_id, receipt[1], fp)
                    return receipt[0]
                record = self.question(req.question_id, paper['trust_tier'])
                if self.repo.has_unavailable_figure(req.question_id):
                    raise HTTPException(409, '题干依赖图示，当前缺少原图，暂不接受作答。')
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
                return response
            except ReceiptConflict as conflict:
                raise HTTPException(409, str(conflict)) from conflict

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
                'latest_paper_submissions': self.store.paper_submissions(latest['paper_id']) if latest else []}

    def chat(self, req):
        if req.trust_tier == TrustTier.PUBLISHED:
            return {'reply': TrustGate('published').fail_closed()['message'],
                    'sources': [], 'tool_result': {}, 'intent': 'general_chat', 'trace': [],
                    'session_id': req.session_id or 'web-chat-' + uuid.uuid4().hex,
                    'notices': [], 'trust_tier': 'published',
                    'model': {'mode': 'rule_only', 'ok': False, 'errors': ['当前无具名签署题，不请求模型。']}}
        payload = dict(req.action_payload or {})
        payload.update(school_level=req.school_level, subject=req.subject)
        intent = IntentRouter.classify(req.message, payload)
        sources = []
        notices = []
        tools = {}
        trace = []
        reply = ''
        if req.question_id:
            self.question(req.question_id, req.trust_tier.value)
            tools = self.qa.answer_query(QARequest(user_id=req.user_id, question_id=req.question_id,
                         user_query=req.message, trust_tier=req.trust_tier)).model_dump(mode='json')
            record = self.repo.load_question(req.question_id)
            sources = self._sources([req.question_id], req.trust_tier.value)
            tools['question'] = {k: v for k, v in (record.get('content') or {}).items() if k in ('stem', 'answer', 'reference_answer')}
            reply = tools.get('explanation_summary', '')
        elif intent == UserIntent.PLAN:
            tools = self.planner.generate_plan(PlanRequest(user_id=req.user_id, exam_type=req.exam_type,
                school_level=req.school_level, subject=req.subject, trust_tier=req.trust_tier,
                days_until_exam=payload.get('days_until_exam', 30),
                daily_available_minutes=payload.get('daily_available_minutes', 60))).model_dump(mode='json')
            reply = f"已生成 {tools['total_days']} 天学习计划，可到“学习计划”查看并执行。"
        elif intent == UserIntent.PRACTICE:
            tools = self.practice(WebPracticeRequest(user_id=req.user_id, exam_type=req.exam_type,
                school_level=req.school_level, subject=req.subject, trust_tier=req.trust_tier,
                practice_mode=payload.get('practice_mode', 'daily_practice'), item_count=payload.get('item_count', 5)))
            reply = f"已组好 {tools['total_items']} 道题，可到“练习与模考”继续作答。"
        elif intent == UserIntent.DIAGNOSTIC:
            tools = self.profile(req)['diagnostic']
            reply = tools['disclaimer']
        elif req.action_payload and intent in (UserIntent.INTERVIEW_PRACTICE, UserIntent.SUBMIT_SUBJECTIVE, UserIntent.ERROR_REVIEW):
            result = self.master.handle_interaction(MasterInteractionRequest(user_id=req.user_id, message=req.message,
                exam_type=req.exam_type, trust_tier=req.trust_tier, session_id=req.session_id, action_payload=payload))
            tools = result.card_data
            reply, trace = result.reply_text, result.trace
        else:
            retrieval = get_retrieval_service().search(req.message, exam=req.exam_type,
                tier=req.trust_tier.value, user_id=req.user_id, k=20,
                levels=[req.school_level] if req.school_level else None)
            qids = [c['question_id'] for c in retrieval.get('candidates', []) if
                    (not req.subject or self.repo.get_meta(c['question_id']).subject == req.subject)][:4]
            sources = self._sources(qids, req.trust_tier.value)
            # Exact syllabus clauses outrank weak lexical card matches for concept questions.
            clause_sources = self._concept_clauses(req)
            sources = clause_sources + [s for s in sources if s['id'] not in {c['id'] for c in clause_sources}]
            tools = {'retrieval_backend': retrieval['backend'], 'evidence': sources}
            notices += retrieval.get('notices', [])
            if clause_sources:
                reply = '当前考纲中的相关要求：\n' + '\n'.join(s['text'] for s in clause_sources[:3]) + '\n\n当前为规则检索，未配置模型时先展示原文依据；可连接 DeepSeek 进一步解释。'
            elif sources:
                reply = '找到以下相关材料：\n' + '\n'.join(s['title'] for s in sources[:3]) + '\n\n当前为规则检索，这些材料需要结合你的问题辨析，不把某一道题的解析直接当作概念问题的答案。'
            else:
                reply = '当前范围没有召回可用证据。可换一个具体考点、扩大科目范围，或先完成练习。'
        notices += tools.get('notices', [])
        allowed = {s['id'] for s in sources}
        # Keep tool summaries bounded; no Key or visitor-supplied authority fields enter facts.
        context = {'exam_type': req.exam_type, 'school_level': req.school_level, 'subject': req.subject,
                   'tool_result': json.dumps(tools, ensure_ascii=False, default=str)[:24000],
                   'sources': sources, 'history': [{'role': h.get('role'), 'content': str(h.get('content', ''))[:2000]}
                                                 for h in req.history[-6:]]}
        model, generated = narrate(client_for(req.model_config_input), req.message, context, allowed, user_id=req.user_id)
        return {'reply': generated or reply, 'model': model, 'sources': sources, 'tool_result': tools,
                'intent': intent.value, 'trace': trace, 'session_id': req.session_id or 'web-chat-' + uuid.uuid4().hex,
                'notices': list(dict.fromkeys(notices)), 'trust_tier': req.trust_tier.value}

    def _concept_clauses(self, req):
        core = re.sub(r'^(什么是|请解释|解释一下|如何理解|怎么理解|讲讲|介绍一下)', '', req.message).strip('？?。！! ')
        core = re.split(r'[？?。；;]', core)[0]
        core = re.sub(r'(有什么区别|是什么意思|是什么)$', '', core)
        if len(core) < 2 or len(core) > 30:
            return []
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
            matching = {n['id'] for n in nodes if n['id'] in node_ids
                        and core in (n.get('name') or n.get('title') or '')}
            matched_node_requirements = {e['src'] for e in edges if e.get('type') == 'aligned_to_requirement'
                                        and e['dst'] in matching}
        gate = TrustGate(req.trust_tier.value)
        rows = []
        for rid in sorted(scope_ids):
            record = self.repo.get_requirement(rid)
            text = (record or {}).get('content') or (record or {}).get('text') or (record or {}).get('title', '')
            if (core in text or rid in matched_node_requirements) and gate.classify_requirement(record).citable:
                rows.append({'id': rid, 'kind': 'requirement', 'title': text[:100], 'text': text[:2500],
                             'standard_id': record.get('standard_id'), 'locator': record.get('locator'),
                             'source_url': record.get('source_url')})
        return rows[:4]

    def _sources(self, qids, tier):
        sources = []
        seen = set()
        gate = TrustGate(tier)
        for qid in qids:
            record = self.repo.load_question(qid)
            if not record or not gate.classify_record(record).servable_in_paper:
                continue
            meta = self.repo.get_meta(qid)
            content = record.get('content') or {}
            explanation = record.get('analysis') or {}
            if isinstance(explanation, dict):
                explanation = explanation.get('explanation') or explanation.get('trace_back') or ''
            sources.append({'id': qid, 'kind': 'question', 'title': content.get('stem', '')[:110],
                'stem': content.get('stem', '')[:3500], 'answer': content.get('answer') or content.get('reference_answer'),
                'explanation': str(explanation)[:2500], 'review_status': meta.review_status,
                'answer_status': meta.answer_status, 'source': record.get('source'), 'node_ids': list(meta.node_ids)})
            for rid in meta.requirement_ids[:5]:
                req = self.repo.get_requirement(rid)
                if rid in seen or not req or not gate.classify_requirement(req).citable:
                    continue
                seen.add(rid)
                sources.append({'id': rid, 'kind': 'requirement', 'title': req.get('title') or req.get('text', '')[:100],
                    'text': (req.get('content') or req.get('text') or req.get('title', ''))[:2500], 'standard_id': req.get('standard_id'),
                    'locator': req.get('locator'), 'source_url': req.get('source_url')})
        return sources
