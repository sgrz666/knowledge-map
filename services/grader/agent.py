"""SubjectiveGraderAgent: rubric-resolution front door for the grading engine.

The agent owns three decisions the engines used to fake:

1. **Where the rubric comes from** — ``KnowledgeRepository.find_rubric`` only, so rubric
   signature state has one reader (A1/A2).
2. **Whether a score may exist** — delegated to ``TrustGate.classify_rubric``; today every rubric
   in both libraries is unsigned, so the honest answer is feedback plus a signature request in
   the review queue (A4, §10 不在未签署量规上出分).
3. **What the status fields mean** — ``answer_status`` is read from the question record itself,
   never trusted from a caller-supplied string, and an LLM may only re-word feedback.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from services.common.models import (
    SubjectiveGradingRequest,
    TrustTier,
    UnifiedSubjectiveGradingResponse,
)
from services.common.safety import SafetyGuard
from services.grader.rubric_engine import grade
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate
from services.llm.client import LLMClient, get_llm_client
from services.review.queue import get_review_queue

logger = logging.getLogger("services.grader.agent")

MODE_BY_EXAM = {"CET-4": "holistic_band", "CET-6": "holistic_band", "NTCE": "analytic_criteria"}


class SubjectiveGraderAgent:
    """Resolves library rubrics, applies the trust gate, and never scores an unsigned rubric."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        llm_client: Optional[LLMClient] = None,
        review_queue=None,
    ) -> None:
        self.repository = repository or get_repository()
        self.llm_client = llm_client
        self.review_queue = review_queue or get_review_queue()

    def grade(self, request: SubjectiveGradingRequest) -> UnifiedSubjectiveGradingResponse:
        """Grade a subjective submission: score only on a signed rubric, otherwise feedback.

        ``answer_status`` deliberately has no parameter: the dispute state is read from the
        question record in the index, so a caller cannot declare a conflicted question normal.
        """
        tier = request.trust_tier.value if isinstance(request.trust_tier, TrustTier) else str(request.trust_tier)
        gate = TrustGate(tier)  # type: ignore[arg-type]

        record = self.repository.load_question(request.question_id)
        if record is None:
            logger.info("question %s is not in the knowledge index", request.question_id)

        verdict = gate.classify_rubric(
            self.repository.find_rubric(
                rubric_id=request.rubric_id,
                task_type=request.task_type,
                exam=request.exam_type,
            )
        )
        rubric = self._rubric_record(verdict.rubric_id)
        mode = (
            request.scoring_mode
            if request.scoring_mode in ("holistic_band", "analytic_criteria")
            else MODE_BY_EXAM.get(request.exam_type, "analytic_criteria")
        )

        response = grade(
            request,
            mode=mode,
            rubric=rubric,
            verdict=verdict,
            record=record,
            llm_payload=self._llm_payload(request, rubric, verdict),
            tier=tier,
        )

        # The question's own trust state still governs whether the item may be discussed at all.
        if record is not None:
            question_verdict = gate.classify_record(record)
            response.notices = list(
                dict.fromkeys(list(response.notices) + list(question_verdict.notices))
            )
            if not question_verdict.servable_in_paper:
                response.total_score = None
                response.feedback_only = True
                response.score_basis = "none"
                response.review_status = "quarantined_for_human"
                response.evaluation_summary = (
                    f"该题处于 {question_verdict.review_status}/{question_verdict.answer_status} 状态，"
                    "系统不出分也不给判分反馈，已转入待复核队列。"
                )
                response.revision_advice = "请教研先修复该题的答案来源冲突、缺失答案或隔离状态。"

        sanitized, quarantined = SafetyGuard.sanitize_grading_response(
            response, rubric_signed=verdict.signed
        )
        if not sanitized.review_queue_entry and (
            sanitized.feedback_only or quarantined
        ):
            sanitized.review_queue_entry = self._enqueue(sanitized, verdict)
        return sanitized

    # ---------------------------------------------------------------- helpers
    def _rubric_record(self, rubric_id: Optional[str]) -> Optional[dict]:
        if not rubric_id:
            return None
        return self.repository.rubrics().get(rubric_id)

    def _llm_payload(self, request, rubric, verdict) -> Optional[dict]:
        """Optional wording help from the model; never a score and never a signature."""
        client = self.llm_client or get_llm_client()
        if client.is_rule_only:
            return None
        prompt = (
            "针对下面的作答与库内量规维度，输出 JSON 反馈草稿，字段为 "
            '{"evaluation_summary": str, "revision_advice": str}。'
            "不要输出分数、档位分或任何复核/签署结论。\n"
            f"题干：{request.stem[:400]}\n"
            f"学生作答：{(request.student_answer or '')[:600]}\n"
            f"量规维度：{json.dumps([d.get('dimension_name') for d in (rubric or {}).get('dimensions') or []], ensure_ascii=False)}\n"
            f"量规签署状态：{verdict.review_status}"
        )
        result = client.generate(
            prompt,
            task="subjective_feedback",
            schema_name=None,
            user_id="grader_agent",
            question_id=request.question_id,
        )
        return result.payload if result.ok else None

    def _enqueue(self, response: UnifiedSubjectiveGradingResponse, verdict) -> dict:
        return self.review_queue.add(
            reason="rubric_signature_required" if verdict.found else "rubric_missing_for_task",
            user_id="grader_agent",
            question_id=response.question_id,
            tier=response.trust_tier.value
            if isinstance(response.trust_tier, TrustTier)
            else str(response.trust_tier),
            source="services.grader.agent",
            detail={
                "rubric_id": verdict.rubric_id,
                "review_status": verdict.review_status,
                "score_use": verdict.score_use,
                "task_type": response.grading_mode,
                "max_score": response.max_score,
                "why_queued": "量规权重与档位措辞未签署，运行时不出分；需具名教研核定后 reopen。",
                "next_action": "教研在 审查/待复核清单.md 签署权重，脚本不得代签。",
            },
        )
