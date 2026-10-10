"""Safety and anti-hallucination guard for agent outputs and scoring operations.

The guard is a *backstop*, not the primary decision maker: ``TrustGate`` already decides whether
a rubric may produce a score. This module makes sure that decision cannot be undone further down
the pipeline — a score appearing on an unsigned rubric is treated as a defect and removed, not
clamped and shipped.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from services.common.models import (
    UnifiedSubjectiveGradingResponse,
)

logger = logging.getLogger("services.common.safety")

UNSIGNED_SCORE_REMOVED = (
    "安全校验拦截：量规未签署却出现分数，已将 total_score 置空并转为反馈。"
)
DISPUTE_CONFLICT = "试题在历年真题版本中存在多方解析与标答争议（source_conflict），系统不出分、不断言正确选项。"
DISPUTE_MISSING = "试题官方参考答案暂缺（missing），系统不做硬性扣分，仅提供可比对的要点反馈。"


class SafetyGuard:
    """Quality guard: schema consistency, score bounds, dispute handling."""

    CONFIDENCE_THRESHOLD = 0.60

    @classmethod
    def sanitize_grading_response(
        cls,
        response: UnifiedSubjectiveGradingResponse,
        *,
        rubric_signed: Optional[bool] = None,
        max_allowed_score: Optional[float] = None,
    ) -> Tuple[UnifiedSubjectiveGradingResponse, bool]:
        """Clamp what may be scored; strip anything scored that may not be.

        Returns ``(response, quarantined)``.
        """
        is_quarantined = False

        if rubric_signed is False and response.total_score is not None:
            logger.warning(
                "Unsigned rubric produced a score for %s; stripping it instead of clamping.",
                response.question_id,
            )
            response.total_score = None
            response.feedback_only = True
            response.score_basis = "unsigned_framework"
            response.review_status = "quarantined_for_human"
            response.notices = list(dict.fromkeys(list(response.notices) + [UNSIGNED_SCORE_REMOVED]))
            is_quarantined = True

        if response.total_score is not None:
            effective_max = max_allowed_score or response.max_score
            if effective_max is not None:
                if response.total_score > effective_max:
                    logger.warning(
                        "total_score %.2f exceeds max_score %.2f for %s; clamping.",
                        response.total_score,
                        effective_max,
                        response.question_id,
                    )
                    response.total_score = effective_max
                if response.total_score < 0:
                    response.total_score = 0.0

            if response.analytic_details and response.analytic_details.dimensions:
                dims = response.analytic_details.dimensions
                for dim in dims:
                    dim.score = max(0.0, min(dim.score, dim.max_score))
                dim_sum = round(sum(d.score for d in dims), 2)
                if abs(dim_sum - response.total_score) > 0.5:
                    response.total_score = dim_sum

            if response.holistic_details and response.holistic_details.band_range:
                low, high = response.holistic_details.band_range
                response.total_score = max(low, min(response.total_score, high))

        if response.feedback_only and response.total_score is not None:
            # feedback_only and a score cannot travel together.
            response.feedback_only = False if rubric_signed else True
            if rubric_signed is not True:
                response.total_score = None

        if response.total_score is not None and response.confidence_score < cls.CONFIDENCE_THRESHOLD:
            logger.warning(
                "Low grading confidence %.2f (< %.2f) for %s; routing to human review.",
                response.confidence_score,
                cls.CONFIDENCE_THRESHOLD,
                response.question_id,
            )
            response.review_status = "quarantined_for_human"
            is_quarantined = True

        return response, is_quarantined

    @classmethod
    def check_disputed_question(cls, answer_status: str, question_id: str) -> Tuple[bool, str]:
        """Whether a question's answer key is disputed or missing, with the honest wording."""
        if answer_status == "source_conflict":
            return (True, f"[{question_id}] {DISPUTE_CONFLICT}")
        if answer_status == "missing":
            return (True, f"[{question_id}] {DISPUTE_MISSING}")
        return (False, "")
