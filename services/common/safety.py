"""Safety and anti-hallucination guard for agent outputs and scoring operations."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from services.common.models import (
    UnifiedSubjectiveGradingResponse,
)

logger = logging.getLogger("services.common.safety")


class SafetyGuard:
    """Quality and security guard enforcing schema consistency, score bounds, and dispute handling."""

    CONFIDENCE_THRESHOLD = 0.60

    @classmethod
    def sanitize_grading_response(
        cls,
        response: UnifiedSubjectiveGradingResponse,
        max_allowed_score: Optional[float] = None,
    ) -> Tuple[UnifiedSubjectiveGradingResponse, bool]:
        """Validate and clamp scores, verify confidence threshold, and check format consistency.

        Returns:
            (sanitized_response, is_quarantined)
        """
        is_quarantined = False

        # 1. Clamp total_score to [0, max_score]
        effective_max = max_allowed_score or response.max_score
        if response.total_score > effective_max:
            logger.warning(
                "total_score %.2f exceeds max_score %.2f for question %s; clamping.",
                response.total_score,
                effective_max,
                response.question_id,
            )
            response.total_score = effective_max

        if response.total_score < 0:
            logger.warning(
                "total_score %.2f is negative for question %s; clamping to 0.",
                response.total_score,
                response.question_id,
            )
            response.total_score = 0.0

        # 2. Check analytic dimension scores sum consistency (for NTCE)
        if response.analytic_details and response.analytic_details.dimensions:
            dims = response.analytic_details.dimensions
            for d in dims:
                if d.score > d.max_score:
                    d.score = d.max_score
                elif d.score < 0:
                    d.score = 0.0

            dim_sum = round(sum(d.score for d in dims), 2)
            # If total_score differs substantially from dimension sum, align it
            if abs(dim_sum - response.total_score) > 0.5:
                logger.info(
                    "Reconciling total_score (%.2f -> %.2f) with dimension sum for %s",
                    response.total_score,
                    dim_sum,
                    response.question_id,
                )
                response.total_score = min(dim_sum, effective_max)

        # 3. Check holistic band boundaries (for CET)
        if response.holistic_details:
            details = response.holistic_details
            min_bound, max_bound = details.band_range
            if response.total_score < min_bound or response.total_score > max_bound:
                logger.warning(
                    "Score %.2f outside holistic band [%.2f, %.2f] for band %d; clamping.",
                    response.total_score,
                    min_bound,
                    max_bound,
                    details.selected_band,
                )
                response.total_score = max(min_bound, min(response.total_score, max_bound))

        # 4. Confidence threshold check
        if response.confidence_score < cls.CONFIDENCE_THRESHOLD:
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
    def check_disputed_question(
        cls,
        answer_status: str,
        question_id: str,
    ) -> Tuple[bool, str]:
        """Check whether a question has version conflicts (source_conflict) or missing answer keys.

        Returns:
            (is_disputed, explanation_message)
        """
        if answer_status == "source_conflict":
            return (
                True,
                f"试题 [{question_id}] 在历年真题版本中存在多方解析与标答争议（source_conflict）。系统在前台已降级为开放讨论题，不扣除考生能力分，请重点研读不同版本分歧与法条沿革。",
            )
        if answer_status == "missing":
            return (
                True,
                f"试题 [{question_id}] 官方参考答案暂缺（missing），系统不进行自动硬性扣分，仅提供参考要点比对。",
            )
        return (False, "")
