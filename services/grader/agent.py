"""SubjectiveGraderAgent: Dual-mode subjective grading orchestrator.

Dispatches to:
- CET Holistic Band Grader (14/11/8/5/2 bands, max score 15)
- NTCE Analytic Criteria Grader (weighted dimensions + rubric points hit, max score 14/40/50)
Integrates with SafetyGuard for anti-hallucination, score bounding, and dispute mitigation.
"""
from __future__ import annotations

import logging
from typing import Optional

from services.common.models import (
    SubjectiveGradingRequest,
    UnifiedSubjectiveGradingResponse,
)
from services.common.safety import SafetyGuard
from services.grader.cet_holistic import CETHolisticGrader
from services.grader.ntce_analytic import NTCEAnalyticGrader

logger = logging.getLogger("services.grader.agent")


class SubjectiveGraderAgent:
    """Agent orchestrating subjective question evaluation across exams."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def grade(
        self,
        request: SubjectiveGradingRequest,
        answer_status: str = "normal",
    ) -> UnifiedSubjectiveGradingResponse:
        """Grade a student subjective submission with dual-mode dispatch and safety guard.

        Args:
            request: The grading request containing stem, student answer, etc.
            answer_status: From question metadata ('normal', 'source_conflict', 'missing').
        """
        logger.info(
            "Grading question %s (exam=%s, task=%s)",
            request.question_id,
            request.exam_type,
            request.task_type,
        )

        # 1. Check disputed or missing answer key status
        is_disputed, dispute_msg = SafetyGuard.check_disputed_question(
            answer_status, request.question_id
        )

        # 2. Route by exam type / scoring mode
        mode = request.scoring_mode
        if mode == "auto":
            mode = "holistic_band" if request.exam_type in ("CET-4", "CET-6") else "analytic_criteria"

        if mode == "holistic_band":
            response = CETHolisticGrader.evaluate(request)
        else:
            response = NTCEAnalyticGrader.evaluate(request)

        # 3. If disputed, append disclaimer to evaluation_summary and avoid zeroing
        if is_disputed:
            response.evaluation_summary = f"[争议题提示] {dispute_msg}\n\n{response.evaluation_summary}"
            response.review_status = "quarantined_for_human"

        # 4. Enforce SafetyGuard verification & score clamping
        sanitized_response, _ = SafetyGuard.sanitize_grading_response(
            response, max_allowed_score=request.max_score
        )

        return sanitized_response
