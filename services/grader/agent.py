"""SubjectiveGraderAgent: rubric-resolution front door for the grading engine.

The agent owns three decisions the engines used to fake:

1. **Where the rubric comes from** — ``KnowledgeRepository.find_rubric`` only, so rubric
   signature state has one reader (A1/A2).
2. **Whether a score may exist** — delegated to ``TrustGate.classify_rubric``; today every rubric
   in both libraries is unsigned, so the honest answer is feedback plus a signature request in
   the review queue (A4, §10 不在未签署量规上出分).
3. **What the status fields mean** — ``answer_status`` is read from the question record itself,
   never trusted from a caller-supplied string, and an LLM may only re-word feedback.
4. **What the item actually says** — 题干与采分点以库内记录为准。题不在库里、或库里只剩套名没有题干，
   就在 agent 层直接拒判（``review_status = "refused_ungradable_input"``，不出分也不给针对该题的反馈），
   且不落待复核队列——队列收的是"这条判分需要教研看一眼"，输入缺口没有判分可看。
   调用方自带的 ``reference_answer`` 只能在库内没有参考原文时兜底，且来源必须写进 notices
   （否则任何人都能传一份自定答案顶掉教研口径，响应却还挂着库内 question_id）。
"""
from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Optional

from services.common.models import (
    SubjectiveGradingRequest,
    TrustTier,
    UnifiedSubjectiveGradingResponse,
)
from services.common.safety import SafetyGuard
from services.grader.rubric_engine import grade
from services.knowledge.repository import (
    KnowledgeRepository,
    get_repository,
    has_answerable_text,
)
from services.knowledge.trust import TrustGate
from services.llm.client import LLMClient, get_llm_client
from services.review.queue import get_review_queue

logger = logging.getLogger("services.grader.agent")

MODE_BY_EXAM = {"CET-4": "holistic_band", "CET-6": "holistic_band", "NTCE": "analytic_criteria"}

#: 题面立不住时的两种拒判口径：(响应头评, 修改建议)。都是输入缺口，不是学习者的作答问题。
INPUT_GAP_REFUSAL = {
    "not_in_library": (
        "该 question_id 未命中知识库索引：库内没有这道题的题干，也没有教研核定的参考原文。",
        "题面立不住时不出分，也不给针对该题的反馈——调用方自带文本不能顶替库内判分口径。"
        "请改用库内 question_id，或由教研先把该题补入知识库。",
    ),
    "stem_extraction_gap": (
        "库内该题只剩套名与题号（content.stem 为空且无选项可勾），无法确认这道题问了什么。",
        "题干抽取缺口补齐之前不出分、不给针对该题的反馈。该缺口已登记在 审查/待复核清单.md 由教研补抽取；"
        "系统不会据解析反推题干来判分。",
    ),
}

#: 调用方题干与库内题干的相似度下限，低于它就声明"以库内为准"（截断的长题干仍可通过）
STEM_SIMILARITY_FLOOR = 0.6
_WS = re.compile(r"\s+")

REFUSAL_NOTICE = (
    "本次为拒判（refused_ungradable_input）：没有题面就没有判分口径，"
    "因此不出分、不给针对该题的采分反馈，也不落待复核队列——队列只收需要教研查看的判分结果。"
)


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
        gap = self._input_gap(record)
        if gap is not None:
            if record is None:
                logger.info("question %s is not in the knowledge index; grading refused", request.question_id)
            else:
                logger.info("question %s has no answerable stem in the library; grading refused", request.question_id)
            return self._refuse(request, gap, tier)

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
            llm_payload=self._llm_payload(request, rubric, verdict, record),
            tier=tier,
        )
        mismatch = self._stem_mismatch_notice(request, record)
        if mismatch:
            response.notices = [mismatch, *response.notices]

        # The question's own trust state still governs whether the item may be discussed at all.
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

    @staticmethod
    def _library_stem(record: Optional[dict]) -> str:
        content = (record or {}).get("content") or {}
        return str(content.get("stem") or (record or {}).get("text") or "").strip()

    @classmethod
    def _input_gap(cls, record: Optional[dict]) -> Optional[str]:
        """Why the item cannot be graded at all, or ``None`` when it can."""
        if record is None:
            return "not_in_library"
        content = record.get("content") or {}
        if not has_answerable_text(cls._library_stem(record), content.get("options")):
            return "stem_extraction_gap"
        return None

    @classmethod
    def _stem_mismatch_notice(cls, request, record: dict) -> Optional[str]:
        """Say out loud when the caller's stem is not the library's — the library wins."""
        library = cls._library_stem(record)
        caller = (request.stem or "").strip()
        if not library or not caller or caller == library:
            return None
        a, b = _WS.sub("", library)[:600], _WS.sub("", caller)[:600]
        if a in b or b in a:
            return None
        ratio = SequenceMatcher(None, a, b).ratio()
        if ratio >= STEM_SIMILARITY_FLOOR:
            return None
        return (
            f"调用方题干与库内题干不一致（相似度 {ratio:.2f}）：判分与反馈一律以库内记录为准，"
            "调用方文本只用于展示，不参与采分。"
        )

    def _refuse(self, request, gap: str, tier: str) -> UnifiedSubjectiveGradingResponse:
        """Build the refusal without touching the engines: nothing here judges the answer."""
        summary, advice = INPUT_GAP_REFUSAL[gap]
        mode = (
            request.scoring_mode
            if request.scoring_mode in ("holistic_band", "analytic_criteria")
            else MODE_BY_EXAM.get(request.exam_type, "analytic_criteria")
        )
        response = UnifiedSubjectiveGradingResponse(
            question_id=request.question_id,
            exam_type=request.exam_type,
            grading_mode=mode,
            total_score=None,
            max_score=None,
            feedback_only=True,
            score_basis="none",
            rubric_signed=None,
            trust_tier=tier,  # type: ignore[arg-type]
            evaluation_summary=summary,
            revision_advice=advice,
            confidence_score=0.0,
            review_status="refused_ungradable_input",
            notices=[summary, REFUSAL_NOTICE],
        )
        sanitized, _ = SafetyGuard.sanitize_grading_response(response, rubric_signed=None)
        return sanitized

    def _llm_payload(self, request, rubric, verdict, record) -> Optional[dict]:
        """Optional wording help from the model; never a score and never a signature."""
        client = self.llm_client or get_llm_client()
        if client.is_rule_only:
            return None
        stem = self._library_stem(record) or request.stem
        prompt = (
            "针对下面的作答与库内量规维度，输出 JSON 反馈草稿，字段为 "
            '{"evaluation_summary": str, "revision_advice": str}。'
            "不要输出分数、档位分或任何复核/签署结论。\n"
            f"题干（库内原文，判分以此为准）：{stem[:400]}\n"
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
