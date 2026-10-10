"""TutorMasterAgent: the §2.1 closed loop, actually driven.

The previous version of this file answered with marketing copy and invented numbers ("30 道分层
自适应试题", "due_today_count: 8") while calling no sub-agent at all. This version runs the
orchestrator state machine against the real capability agents and renders cards from what those
agents returned, so every count in a reply comes from the library or the learner's own state.

Anything the machine degrades goes to the review queue: the single 教研 reviewer stays in the
loop, and the reply says plainly that no conclusion was produced.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

from services.common.models import (
    AssemblePaperRequest,
    DiagnosticRequest,
    ErrorReviewEvent,
    LessonPlanReviewRequest,
    MasterInteractionRequest,
    MasterInteractionResponse,
    PlanRequest,
    QARequest,
    SpeechAnalysisRequest,
    SubjectiveGradingRequest,
    TrustTier,
    UserIntent,
)
from services.common.weakness import WEAK_MASTERY_BAR
from services.diagnostic.agent import DiagnosticAgent
from services.grader.agent import SubjectiveGraderAgent
from services.interview.agent import InterviewCoachAgent
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate
from services.master.intent_router import IntentRouter
from services.memory.agent import MemoryReviewAgent
from services.memory.store import default_store
from services.orchestrator.session import SessionStore, get_session_store
from services.orchestrator.state_machine import Orchestrator, State
from services.planner.agent import CurriculumPlannerAgent
from services.practice.agent import PracticeEngineAgent
from services.qa.agent import TutorQAAgent
from services.review.queue import ReviewQueue, get_review_queue

CARD_BY_STATE = {
    State.DIAGNOSE: "diagnostic_card",
    State.PROFILE: "review_card",
    State.PLAN: "plan_card",
    State.PRACTICE: "practice_card",
    State.MOCK: "practice_card",
    State.GRADE: "grading_card",
    State.FEEDBACK_ONLY: "grading_card",
    State.ATTRIBUT: "review_card",
    State.REPROFILE: "review_card",
    State.REVIEW_QUEUE: "text_message",
}

# Which context key each state's handler writes its card under. ``card_<state>`` cannot be derived
# by naming convention: REPROFILE reuses the profile card, an unsigned grade lands on the
# feedback-only card, and MOCK reuses the practice card — a derived key silently produced empty cards.
CARD_KEY_BY_STATE = {
    State.DIAGNOSE: ("card_diagnose",),
    State.PROFILE: ("card_profile",),
    State.REPROFILE: ("card_profile",),
    State.PLAN: ("card_plan",),
    State.PRACTICE: ("card_practice",),
    State.MOCK: ("card_practice",),
    State.GRADE: ("card_grade", "card_feedback_only"),
    State.FEEDBACK_ONLY: ("card_feedback_only",),
    State.ATTRIBUT: ("card_attribut",),
    State.REVIEW_QUEUE: ("card_review",),
}

STATE_LABELS = {
    State.IDLE.value: "接待",
    State.DIAGNOSE.value: "摸底",
    State.PROFILE.value: "画像",
    State.PLAN.value: "日历",
    State.PRACTICE.value: "练习",
    State.MOCK.value: "模考",
    State.GRADE.value: "讲评",
    State.FEEDBACK_ONLY.value: "反馈",
    State.ATTRIBUT.value: "归因",
    State.REPROFILE.value: "画像回写",
    State.REVIEW_QUEUE.value: "待复核",
}

INTENT_ENTRY = {
    UserIntent.DIAGNOSTIC: State.DIAGNOSE,
    UserIntent.PLAN: State.PLAN,
    UserIntent.PRACTICE: State.PRACTICE,
    UserIntent.SUBMIT_SUBJECTIVE: State.GRADE,
    UserIntent.ERROR_REVIEW: State.ATTRIBUT,
    UserIntent.GENERAL_CHAT: State.IDLE,
}

NO_DATA_REPLY = (
    "本次会话没有产生可呈现的结论：{reason}。相关条目已进入待复核队列（审查/待复核清单.md 同源流程），"
    "由教研复核后再开放。"
)
GENERAL_HELP = (
    "我可以串起这条闭环：摸底诊断 → 学情画像 → 备考日历 → 组卷练习/模考 → 讲评或框架反馈 → 错因归因 → 回写画像。"
    "当前所有响应都会标注运行档位（research_internal / published）与内容复核状态；published 档在教研签署前是空集。"
)


ATTRIBUT_NOTICE = (
    "错因分类由作答特征启发式判定（选项改动次数、用时、题干否定词），未接入真实作答校准数据，"
    "不构成能力或分数结论；复习间隔来自本机 FSRS 调度记录。"
)


class TutorMasterAgent:
    """Coordinates the capability agents through the state machine."""

    def __init__(
        self,
        *,
        diagnostic_agent: Optional[DiagnosticAgent] = None,
        planner_agent: Optional[CurriculumPlannerAgent] = None,
        practice_agent: Optional[PracticeEngineAgent] = None,
        grader_agent: Optional[SubjectiveGraderAgent] = None,
        memory_agent: Optional[MemoryReviewAgent] = None,
        qa_agent: Optional[TutorQAAgent] = None,
        interview_agent: Optional[InterviewCoachAgent] = None,
        repository: Optional[KnowledgeRepository] = None,
        queue: Optional[ReviewQueue] = None,
        session_store: Optional[SessionStore] = None,
    ) -> None:
        self.repository = repository or get_repository()
        self.store = default_store()
        self.diagnostic = diagnostic_agent or DiagnosticAgent(repository=self.repository)
        self.planner = planner_agent or CurriculumPlannerAgent(repository=self.repository)
        self.practice = practice_agent or PracticeEngineAgent(repository=self.repository)
        self.grader = grader_agent or SubjectiveGraderAgent(repository=self.repository)
        self.memory = memory_agent or MemoryReviewAgent(store=self.store, repository=self.repository)
        self.qa = qa_agent or TutorQAAgent(repository=self.repository)
        self.interview = interview_agent or InterviewCoachAgent(repository=self.repository)
        self.queue = queue or get_review_queue()
        self.sessions = session_store or get_session_store()

    # ------------------------------------------------------------------ public
    def handle_interaction(self, req: MasterInteractionRequest) -> MasterInteractionResponse:
        session_id = req.session_id or f"sess-{uuid.uuid4().hex[:8]}"
        intent = IntentRouter.classify(req.message, req.action_payload)

        if intent is UserIntent.GENERAL_CHAT:
            return MasterInteractionResponse(
                session_id=session_id,
                detected_intent=intent,
                reply_text=GENERAL_HELP,
                card_type="text_message",
                card_data={"capabilities": [intent.value for intent in UserIntent]},
                suggested_quick_replies=["进行学情摸底", "生成备考计划", "开启今日练习", "批改主观题"],
                state=State.IDLE.value,
                trust_tier=req.trust_tier,
            )

        if intent is UserIntent.QA_ASK:
            return self._qa_turn(session_id, req, intent)

        if intent is UserIntent.INTERVIEW_PRACTICE:
            return self._interview_turn(session_id, req, intent)

        context = self._context_for(req, intent)
        result = self._orchestrator(session_id).run(
            session_id=session_id,
            user_id=req.user_id,
            exam_type=req.exam_type,
            tier=req.trust_tier,
            context=context,
            entry=INTENT_ENTRY.get(intent, State.IDLE),
        )
        self.sessions.save(
            session_id=session_id,
            user_id=req.user_id,
            exam=req.exam_type,
            state=result.state.value,
            context=_serialisable(result.context),
        )

        card_state, card_data = self._card_from(result, INTENT_ENTRY.get(intent))
        notices = list(result.context.get("notices_seen") or [])
        if result.degraded:
            row = result.degraded[-1]
            reason = row["reason"]
            if row.get("kind") == "input_gap":
                # The gap is on the caller's side, so the reply asks for the missing field instead of
                # claiming a queue row that 教研 could not act on.
                gap = "、".join(row.get("missing_inputs") or [])
                note = (
                    f"本次会话停在「{STATE_LABELS.get(row['state'], row['state'])}」，还需要 {gap}；"
                    "补齐后重发同一请求即可继续，这类缺口不进入教研的待复核队列。"
                )
                reply = (self._reply_for(result) + f"（{note}）") if card_data else note
                if not card_data:
                    # No stage produced a card: the hint must not be rendered under the stopped
                    # stage's card type (a "讲评" card with no 讲评 in it).
                    card_state = None
                    card_data = {
                        "missing_inputs": row.get("missing_inputs") or [],
                        "next_action": f"补齐 {gap or reason} 后重试。",
                    }
            else:
                # A card that the machine did produce stays visible; the degrade note is appended, not
                # swapped in, so a partially useful turn is not thrown away.
                reply = (
                    self._reply_for(result) + f"（本回合另有降级：{reason}，已进入待复核队列。）"
                    if card_data
                    else NO_DATA_REPLY.format(reason=reason)
                )
        else:
            reply = self._reply_for(result)

        return MasterInteractionResponse(
            session_id=session_id,
            detected_intent=intent,
            reply_text=reply,
            card_type=CARD_BY_STATE.get(card_state, "text_message"),  # type: ignore[arg-type]
            card_data=card_data,
            suggested_quick_replies=self._quick_replies(card_state, result),
            state=result.state.value,
            trace=result.trace_rows(),
            trust_tier=req.trust_tier,
            notices=notices,
        )

    def trace_of(self, session_id: str) -> list:
        """Replay the envelope trace of a finished session (acceptance A8)."""
        return self.sessions.trace(session_id)

    # --------------------------------------------------------------- sub-turns
    def _qa_turn(self, session_id: str, req: MasterInteractionRequest, intent: UserIntent) -> MasterInteractionResponse:
        payload = req.action_payload or {}
        question_id = payload.get("question_id") or req.message.strip()
        qa_request = QARequest(
            user_id=req.user_id,
            question_id=question_id,
            user_selected_option=payload.get("user_selected_option"),
            user_query=req.message,
            mode=payload.get("mode", "sparks_three_chain"),
            hint_turn=int(payload.get("hint_turn", 1)),
            trust_tier=req.trust_tier,
        )
        answer = self.qa.answer_query(qa_request)
        grounded = getattr(answer, "grounded_in_library", False)
        card = {
            "question_id": answer.question_id,
            "grounded_in_library": grounded,
            "answer_visibility": getattr(answer, "answer_visibility", "none"),
            "notices": list(getattr(answer, "notices", []) or []),
            "evidence": (answer.knowledge_provenance if hasattr(answer, "knowledge_provenance") else {}),
        }
        reply = (
            getattr(answer, "explanation_summary", None)
            or getattr(answer, "guiding_question", "")
            or "该题不在知识库索引内，系统不生成解析。"
        )
        return MasterInteractionResponse(
            session_id=session_id,
            detected_intent=intent,
            reply_text=reply,
            card_type="qa_card",
            card_data=card,
            suggested_quick_replies=["苏格拉底式引导我", "查看条款原文定位"],
            state=State.IDLE.value,
            trust_tier=req.trust_tier,
            notices=card["notices"],
        )

    # -------------------------------------------------------------- interview
    def _interview_turn(
        self, session_id: str, req: MasterInteractionRequest, intent: UserIntent
    ) -> MasterInteractionResponse:
        """Route 试讲/简案 to InterviewCoachAgent; a score still needs the 教研 rubric signature."""
        payload = dict(req.action_payload or {})
        plan_text = str(payload.get("plan_text") or "")
        transcript = str(payload.get("transcript_text") or "")

        if plan_text:
            review = self.interview.review_lesson_plan(
                LessonPlanReviewRequest(
                    subject=str(payload.get("subject") or "教育教学知识与能力"),
                    grade_level=str(payload.get("grade_level") or "小学"),
                    topic=str(payload.get("topic") or req.message.strip()[:60] or "未提供课题"),
                    plan_text=plan_text,
                    trust_tier=req.trust_tier,
                )
            )
            card = review.model_dump(mode="json")
            head = (
                f"简案反馈（{review.max_score or '量规未录入'} 分制，签署状态：{review.rubric_signed}）："
                if review.total_score is None
                else f"简案得分 {review.total_score}/{review.max_score}："
            )
            reply = head + review.improvement_suggestions
            quick = ["补写缺失环节后重新提交", "提交试讲转写文本"]
        elif transcript:
            analysis = self.interview.analyze_speech(
                SpeechAnalysisRequest(
                    transcript_text=transcript,
                    audio_duration_seconds=float(payload.get("audio_duration_seconds") or 600.0),
                    audio_pauses=payload.get("audio_pauses"),
                    lesson_title=payload.get("lesson_title"),
                    trust_tier=req.trust_tier,
                )
            )
            card = analysis.model_dump(mode="json")
            head = (
                "试讲测算（语速/口头禅/停顿/五环节覆盖，均为转写文本测算，不含评分权重）："
                if analysis.overall_score is None
                else f"试讲总分 {analysis.overall_score}："
            )
            reply = head + analysis.coaching_feedback
            quick = ["提交我的教案简案", "查看试讲量规签署状态"]
        else:
            topic = self._trial_teaching_topic()
            card = {"needs": ["transcript_text 或 plan_text"], "topic": topic}
            reply = (
                "试讲演练需要你的转写文本（含时长）或简案原文，系统不虚构表现数据；"
                "库里可用作选题的课题如下，也可自行指定："
                + json.dumps(topic, ensure_ascii=False)
            )
            quick = ["这是我的试讲转写：", "这是我的简案："]

        return MasterInteractionResponse(
            session_id=session_id,
            detected_intent=intent,
            reply_text=reply,
            card_type="interview_card",
            card_data=card,
            suggested_quick_replies=quick,
            state=State.IDLE.value,
            trust_tier=req.trust_tier,
            notices=list(card.get("notices") or []),
        )

    def _trial_teaching_topic(self, tier: str = "research_internal") -> dict:
        """Offer a real library 教学设计 stem as a practice topic, with its id and review state."""
        gate = TrustGate(tier)
        for meta in self.repository.find_questions(
            exams="NTCE", question_types=("教学设计", "活动设计"), require_nodes=True
        ):
            if not gate.classify_meta(meta).usable:
                continue
            record = self.repository.load_question(meta.question_id) or {}
            stem = ((record.get("content") or {}).get("stem") or "").strip()
            return {
                "question_id": meta.question_id,
                "stem": stem[:160],
                "review_status": meta.review_status,
                "source": meta.file,
            }
        return {"question_id": None, "notice": "当前档位内没有可用于试讲选题的教学设计题。"}

    # ------------------------------------------------------------- orchestrator
    def _orchestrator(self, session_id: str) -> Orchestrator:
        return Orchestrator(
            self._handlers(),
            on_degrade=self._enqueue,
            trace_sink=lambda envelope: self.sessions.append_trace(session_id, envelope),
        )

    def _enqueue(self, row: dict) -> None:
        self.queue.add(
            reason=str(row.get("reason", "编排降级")),
            user_id=str(row.get("user_id", "")),
            question_id=row.get("question_id"),
            node_id=row.get("node_id"),
            tier=row.get("trust_tier"),
            detail={"state": row.get("state"), "path": "orchestrator"},
        )

    def _handlers(self) -> Dict[State, Any]:
        return {
            State.IDLE: self._h_idle,
            State.DIAGNOSE: self._h_diagnose,
            State.PROFILE: self._h_profile,
            State.PLAN: self._h_plan,
            State.PRACTICE: self._h_practice,
            State.MOCK: self._h_practice,
            State.GRADE: self._h_grade,
            State.FEEDBACK_ONLY: self._h_grade,
            State.ATTRIBUT: self._h_attribut,
            State.REPROFILE: self._h_profile,
            State.REVIEW_QUEUE: self._h_review,
        }

    # ------------------------------------------------------------------ handlers
    def _h_idle(self, ctx: dict) -> dict:
        return {"summary": "会话已建立，进入摸底诊断。", "data": {"user_id": ctx["user_id"]}}

    def _h_diagnose(self, ctx: dict) -> dict:
        submissions = ctx.get("submissions") or []
        request = DiagnosticRequest(
            user_id=ctx["user_id"],
            exam_type=ctx["exam_type"],  # type: ignore[arg-type]
            stage="cold_start" if submissions else "coverage_probe",
            submissions=submissions,
            trust_tier=TrustTier(ctx["trust_tier"]),
        )
        report = self.diagnostic.evaluate(request)
        evidence = [{"node_id": n, "source": "诊断输入"} for n in (report.weak_points_top5 or [])]
        ctx.setdefault("weak_nodes", list(report.weak_points_top5 or []))
        return {
            "summary": report.disclaimer,
            "data": report.model_dump(mode="json"),
            "evidence": evidence,
            "notices": report.notices,
            "card_diagnose": {"radar": report.radar_chart, "weak_points": report.weak_points_top5},
            "context": {
                "weak_nodes": report.weak_points_top5,
                "card_diagnose": _serialisable({
                    "publishable": report.publishable,
                    "raw_score": report.raw_score,
                    "max_raw_score": report.max_raw_score,
                    "estimate_basis": report.estimate_basis,
                    "radar_chart": report.model_dump(mode="json")["radar_chart"],
                    "weak_points_top5": report.weak_points_top5,
                }),
            },
        }

    def _h_profile(self, ctx: dict) -> dict:
        user_id = ctx["user_id"]
        diagnosed = list(ctx.get("weak_nodes") or [])
        # 诊断给的是"低于薄弱线"的考点；记忆里的只是掌握度相对最低的前几名，全都已掌握时照样给出名字。
        # 两种来源不能叫同一个名字，否则画像一句"薄弱考点 5 个"就把相对排序说成了能力结论。
        weak = diagnosed or list(self.memory.weak_node_ids(user_id, limit=5))
        due = list(self.memory.due_question_ids(user_id, limit=20))
        mastery = [self.memory.get_user_mastery(user_id, node) for node in weak]
        records = [m.model_dump(mode="json") for m in mastery if m]
        ctx["weak_nodes"] = weak
        if diagnosed:
            weak_summary = f"低于薄弱线（{WEAK_MASTERY_BAR:.2f}）的考点 {len(weak)} 个（诊断给出）"
            weak_source = "诊断（按考点作答正确率与薄弱线比对）"
        else:
            weak_summary = f"掌握度相对最低的考点 {len(weak)} 个（相对排序，不代表低于薄弱线）"
            weak_source = "memory store（按掌握度相对排序）"
        return {
            "summary": f"画像：{weak_summary}，FSRS 到期错题 {len(due)} 道（读自持久化存储）。",
            "data": {"weak_nodes": weak, "due_question_ids": due, "mastery": records},
            "evidence": [{"node_id": node, "source": weak_source} for node in weak],
            "context": {
                "weak_nodes": weak,
                "due_question_ids": due,
                "card_profile": _serialisable({
                    "weak_nodes": weak,
                    "due_count": len(due),
                    "due_sample": due[:5],
                    "mastery": records,
                    "source": "services/memory/store.py（SQLite，跨进程可读）",
                }),
            },
        }

    def _h_plan(self, ctx: dict) -> dict:
        request = PlanRequest(
            user_id=ctx["user_id"],
            exam_type=ctx["exam_type"],  # type: ignore[arg-type]
            days_until_exam=int(ctx.get("days_until_exam", 30)),
            daily_available_minutes=int(ctx.get("daily_available_minutes", 60)),
            current_mastery=None,
            trust_tier=TrustTier(ctx["trust_tier"]),
        )
        plan = self.planner.generate_plan(request)
        return {
            "summary": f"已生成 {plan.total_days} 天日历；{plan.prerequisite_note or '路径排序已启用'}",
            "data": plan.model_dump(mode="json"),
            "evidence": [
                {"node_id": task.node_id, "source": "planner"}
                for day in plan.daily_plans
                for task in day.tasks
                if task.node_id
            ],
            "notices": plan.notices,
            "context": {
                "plan_generated": True,
                "card_plan": _serialisable({
                    "total_days": plan.total_days,
                    "milestones": plan.milestones,
                    "prerequisite_note": plan.prerequisite_note,
                    "first_day": plan.daily_plans[0].model_dump(mode="json") if plan.daily_plans else {},
                    "node_source": plan.model_dump(mode="json").get("node_source", "library graph"),
                }),
            },
        }

    def _h_practice(self, ctx: dict, *, force_mock: bool = False) -> dict:
        from services.common.models import PracticeMode

        state_mock = force_mock or ctx.get("mode") == "mock"
        request = AssemblePaperRequest(
            user_id=ctx["user_id"],
            exam_type=ctx["exam_type"],  # type: ignore[arg-type]
            practice_mode=PracticeMode.MOCK_EXAM if state_mock else PracticeMode.DAILY_PRACTICE,
            target_node=(ctx.get("weak_nodes") or [None])[0],
            item_count=int(ctx.get("item_count", 10)),
            weak_node_ids=list(ctx.get("weak_nodes") or []),
            wrong_question_ids=list(ctx.get("due_question_ids") or []),
            trust_tier=TrustTier(ctx["trust_tier"]),
        )
        paper = self.practice.assemble_paper(request)
        first = paper.questions[0] if paper.questions else {}
        # An empty pool at research_internal is a content gap 教研 should see. An empty pool at
        # published is the designed fail-closed answer, so it must not queue a review item.
        blocked = (
            [{"reason": "当前档位没有可组卷的题目", "question_id": None}]
            if not paper.total_items and ctx["trust_tier"] == TrustTier.RESEARCH_INTERNAL.value
            else []
        )
        return {
            "summary": (
                f"组卷 {paper.total_items} 题（池 {paper.pool_size}，缺 {paper.shortfall}），"
                + (
                    f"限时 {paper.time_limit_minutes} 分钟。"
                    if paper.time_limit_minutes is not None
                    else (
                        "这一卷没有组出题，也就没有用时可报。"
                        if not paper.total_items
                        else "库内卷面与题面约束都说不出用时，因此不限时（不编分钟数）。"
                    )
                )
            ),
            "data": paper.model_dump(mode="json"),
            "evidence": [
                {
                    "question_id": q.get("question_id"),
                    "node_id": (q.get("node_ids") or [None])[0],
                    "requirement_id": (q.get("requirement_ids") or [None])[0],
                    "source": q.get("card_path") or "repository",
                }
                for q in paper.questions
            ],
            "notices": paper.notices,
            "blocked": blocked,
            "rubric_signed": False,
            "context": {
                # The caller's own ids survive the assembly; the paper's first question only fills a
                # gap. Attribution must never be written against a question the learner did not name.
                "question_id": ctx.get("question_id") or first.get("question_id"),
                "node_id": ctx.get("node_id") or (first.get("node_ids") or [None])[0],
                "card_practice": _serialisable({
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "total_items": paper.total_items,
                    "pool_size": paper.pool_size,
                    "shortfall": paper.shortfall,
                    "time_limit_minutes": paper.time_limit_minutes,
                    "trust_tier": paper.trust_tier.value,
                    "sample": paper.questions[:3],
                    "structure": paper.structure,
                }),
            },
        }

    def _h_grade(self, ctx: dict) -> dict:
        request = SubjectiveGradingRequest(
            question_id=ctx["question_id"] or "",
            exam_type=ctx["exam_type"],  # type: ignore[arg-type]
            task_type=ctx.get("task_type", "case_analysis"),
            stem=ctx.get("stem", ""),
            student_answer=ctx.get("answer_text", ""),
            reference_answer=ctx.get("reference_answer"),
            rubric_id=ctx.get("rubric_id"),
            max_score=ctx.get("max_score"),
            trust_tier=TrustTier(ctx["trust_tier"]),
        )
        graded = self.grader.grade(request)
        signed = bool(graded.rubric_signed)
        meta = self.repository.get_meta(request.question_id)
        evidence = [
            {
                "question_id": request.question_id,
                "node_id": (meta.node_ids or (None,))[0] if meta else None,
                "requirement_id": (meta.requirement_ids or (None,))[0] if meta else None,
                "source": (meta.file if meta else None) or "题面未命中库内索引：已拒判，调用方文本不作为判分依据",
                "locator": {"offset": meta.offset, "length": meta.length} if meta else None,
            }
        ]
        return {
            "summary": graded.evaluation_summary,
            "data": graded.model_dump(mode="json"),
            "evidence": evidence,
            "notices": graded.notices,
            "rubric_signed": signed,
            # Attribution needs a right/wrong signal. Feedback-only grading has none, so the loop
            # stops after the feedback instead of inventing an is_correct to attribute.
            "attributable": signed and ctx.get("is_correct") is not None,
            "context": {
                "grading_feedback_only": graded.feedback_only,
                "card_grade" if signed else "card_feedback_only": _serialisable({
                    "score": graded.total_score,
                    "feedback_only": graded.feedback_only,
                    "score_basis": graded.score_basis,
                    "rubric_signed": graded.rubric_signed,
                    "review_status": graded.review_status,
                    "revision_advice": graded.revision_advice,
                    "review_queue_entry": graded.review_queue_entry,
                }),
            },
        }

    def _h_attribut(self, ctx: dict) -> dict:
        question_id = ctx.get("question_id")
        node_id = ctx.get("node_id") or ((ctx.get("weak_nodes") or [None])[0])
        if not question_id or not node_id:
            # No ids in the message: fall back to the learner's own due list rather than
            # degrading, because "the store has nothing yet" is a learner state, not a 教研 item.
            due = list(self.memory.due_question_ids(ctx["user_id"], limit=1))
            meta = self.repository.get_meta(due[0]) if due else None
            question_id = question_id or (due[0] if due else None)
            node_id = node_id or ((meta.node_ids or (None,))[0] if meta else None)
        if not question_id or not node_id:
            return {
                "summary": "错题本里还没有可归因的作答：先做一组练习或提交一次作答，系统只按真实作答归因，不虚构错因。",
                "data": {"attributable": False, "due_question_ids": []},
                "context": {
                    "card_attribut": _serialisable({
                        "attributable": False,
                        "reason": "没有真实作答记录",
                    })
                },
            }
        correct, verdict_source, verdict_notices = self._verdict_with_provenance(ctx, question_id)
        if correct is None:
            # No checkable judgement exists: the library answer is unverified and the caller
            # submitted no option. Writing "wrong" here would poison the learner's own FSRS queue.
            return {
                "summary": "这次作答无法核对：该题在库内的答案未经校验，或请求里没有可核对的所选选项。"
                           "系统不虚构对错，因此本次不写入记忆，也不给出错因。",
                "data": {"attributable": False, "question_id": question_id, "node_id": node_id},
                "notices": [ATTRIBUT_NOTICE],
                "context": {
                    "card_attribut": _serialisable({
                        "attributable": False,
                        "reason": "没有可核对的对错判据（库内答案未校验或未提交所选选项）",
                        "question_id": question_id,
                        "node_id": node_id,
                    })
                },
            }
        event = ErrorReviewEvent(
            user_id=ctx["user_id"],
            question_id=question_id,
            node_id=node_id,
            exam=ctx["exam_type"],  # type: ignore[arg-type]
            is_correct=correct,
            time_spent_seconds=float(ctx.get("time_spent_seconds", 30.0)),
            option_flip_count=int(ctx.get("option_flip_count", 0)),
            selected_option=ctx.get("selected_option"),
            correct_option=ctx.get("correct_option"),
            question_difficulty=float(ctx.get("question_difficulty", 0.5)),
            has_negation_in_stem=bool(ctx.get("has_negation_in_stem", False)),
        )
        bundle = self.memory.process_event(event)
        notices = [ATTRIBUT_NOTICE, f"对错判据：{verdict_source}。" if verdict_source else "", *verdict_notices]
        notices += list(getattr(bundle, "notices", []) or [])
        return {
            "summary": bundle.followup_plan,
            "data": bundle.model_dump(mode="json"),
            "evidence": [{"question_id": question_id, "node_id": node_id, "source": "memory store"}],
            "notices": [n for n in dict.fromkeys(notices) if n],
            "context": {
                "attributed": True,
                "card_attribut": _serialisable({
                    "attribution": bundle.attribution.model_dump(mode="json") if bundle.attribution else None,
                    "fsrs_rating": bundle.fsrs_rating,
                    "retrievability": bundle.retrievability,
                    "next_review_interval_days": bundle.next_review_interval_days,
                    "followup_plan": bundle.followup_plan,
                    "is_correct": correct,
                    "verdict_source": bundle.verdict_source or verdict_source,
                }),
            },
        }

    def _verdict(self, ctx: dict, question_id: str) -> Optional[bool]:
        return self._verdict_with_provenance(ctx, question_id)[0]

    def _verdict_with_provenance(self, ctx: dict, question_id: str):
        """判据优先级：库内答案键核对 > 调用方申报 > 学习者自己的错题日志。

        申报排在前面的旧写法意味着任何人报一次"对"就能永久改写这个学习者的掌握度与复习队列，
        哪怕库里那道题的答案键说的是反的（与 A4 的判分依据同一条口径）。
        """
        gate = TrustGate(TrustTier.RESEARCH_INTERNAL)
        record = self.repository.load_question(question_id) if question_id else None
        checked, provenance, notices = gate.reconcile_verdict(
            record, ctx.get("selected_option"), ctx.get("is_correct")
        )
        if checked is not None:
            return checked, provenance, notices
        if question_id:
            logged = self.memory.store.error_entries(ctx["user_id"])
            if any(entry.get("question_id") == question_id for entry in logged):
                return False, "学习者自己的错题日志", notices
        return None, "", notices

    def _h_review(self, ctx: dict) -> dict:
        return {"summary": "已转入待复核队列，本次会话不输出结论。", "data": {"queued": True}}

    # -------------------------------------------------------------------- utils
    def _context_for(self, req: MasterInteractionRequest, intent: UserIntent) -> dict:
        payload = dict(req.action_payload or {})
        context = {k: v for k, v in payload.items() if v is not None}
        if "submissions" in context:
            context["submissions"] = [dict(s) for s in context["submissions"]]
        if intent is UserIntent.PRACTICE and "mock" in req.message:
            context["mode"] = "mock"
        return context

    @staticmethod
    def _card_from(result, prefer: Optional[State] = None):
        """Stage card to render: the one the learner asked for, else the last one with data."""
        found = []
        for envelope in reversed(result.envelopes):
            payload = envelope.payload if isinstance(envelope.payload, dict) else {}
            try:
                state = State(str(payload.get("state", "")))
            except ValueError:
                continue
            for key in CARD_KEY_BY_STATE.get(state, ()):
                data = result.context.get(key)
                if data:
                    found.append((state, data))
                    break
        if prefer is not None:
            for state, data in found:
                if state is prefer:
                    return state, data
        return found[0] if found else (result.state, {})

    def _reply_for(self, result) -> str:
        tier_note = f"（运行档位：{result.context['trust_tier']}）"
        # The card renders the final stage; the text names every stage the machine actually ran, so
        # a "摸底 → 日历 → 组卷" turn is visible as a turn instead of only its last card.
        ran: list[str] = []
        seen_states: set[str] = set()
        for envelope in result.envelopes:
            payload = envelope.payload if isinstance(envelope.payload, dict) else {}
            state = str(payload.get("state", ""))
            summary = str(payload.get("summary", "")).strip()
            if not state or not summary or state in seen_states:
                continue
            seen_states.add(state)
            ran.append(f"{STATE_LABELS.get(state, state)}：{summary}")
        if not ran:
            return f"闭环已完成，无额外结论。{tier_note}"
        return "；".join(ran[-4:]) + tier_note

    @staticmethod
    def _quick_replies(card_state: State, result) -> list:
        if card_state in (State.PRACTICE, State.MOCK):
            return ["提交我的作答", "换一套同考点题", "只看错题"]
        if card_state in (State.GRADE, State.FEEDBACK_ONLY):
            return ["查看待复核队列条目", "重做本题"]
        if card_state in (State.ATTRIBUT, State.REPROFILE, State.PROFILE):
            return ["按新画像重排计划", "开启每日一练"]
        return ["进行学情摸底", "生成备考计划", "开启今日练习"]


def _serialisable(value):
    """Best-effort JSON-safe copy for card payloads and persisted context."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        return {str(k): _serialisable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialisable(v) for v in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)
