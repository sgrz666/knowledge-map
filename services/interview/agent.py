"""InterviewCoachAgent: trial-teaching measurements and lesson-plan review.

Both entry points keep the same rule as the grader: measured feedback is available in the
research tier, a score needs a signed rubric, and every refusal to score becomes a review-queue
row instead of an invented number (A4, A9).
"""
from __future__ import annotations

from typing import Optional

from services.common.models import (
    LessonPlanReviewRequest,
    LessonPlanReviewResponse,
    SpeechAnalysisRequest,
    SpeechAnalysisResponse,
    TrustTier,
)
from services.interview.lesson_plan import LessonPlanEvaluator
from services.interview.speech_analyzer import SpeechAnalyzer
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate
from services.review.queue import get_review_queue


class InterviewCoachAgent:
    """Agent coaching NTCE candidates through virtual trial teaching and lesson planning."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        review_queue=None,
    ) -> None:
        self.repository = repository or get_repository()
        self.review_queue = review_queue or get_review_queue()
        self.lesson_plan_evaluator = LessonPlanEvaluator(self.repository)

    def analyze_speech(self, req: SpeechAnalysisRequest) -> SpeechAnalysisResponse:
        """Measure transcribed speech and phase coverage; no score without a signed rubric."""
        response = SpeechAnalyzer.evaluate(req)
        tier = self._tier(req.trust_tier)
        verdict = TrustGate(tier).classify_rubric(
            self.repository.find_rubric(task_type="interview_teaching", exam="NTCE")
        )
        response.rubric_signed = verdict.signed
        response.notices = list(dict.fromkeys(list(response.notices) + list(verdict.notices)))
        if tier == "published" and not verdict.signed:
            response.coaching_feedback = "published 档位不出具任何面试评分，且当前试讲量规未签署；已转人工复核。"
            response.notices.append("published 档位拒绝：试讲量规未签署。")
        if not verdict.signed:
            response.review_queue_entry = self._enqueue(
                verdict,
                detail={"capability": "speech", "phase_coverage_rate": response.phase_coverage_rate},
            )
        return response

    def review_lesson_plan(self, req: LessonPlanReviewRequest) -> LessonPlanReviewResponse:
        """Review a 20-minute design draft against the library rubric, feedback-first."""
        tier = self._tier(req.trust_tier)
        response = self.lesson_plan_evaluator.evaluate(req, tier=tier)
        if response.total_score is None:
            response.review_queue_entry = self._enqueue(
                None,
                detail={
                    "capability": "lesson_plan",
                    "rubric_id": response.rubric_id,
                    "missed_elements": response.missed_elements,
                },
            )
        return response

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _tier(value) -> str:
        return value.value if isinstance(value, TrustTier) else str(value)

    def _enqueue(self, verdict, *, detail: dict) -> dict:
        return self.review_queue.add(
            reason="rubric_signature_required",
            user_id="interview_agent",
            tier=detail.get("tier"),
            source="services.interview.agent",
            detail={
                "rubric_id": getattr(verdict, "rubric_id", None) or detail.get("rubric_id"),
                "review_status": getattr(verdict, "review_status", None),
                **detail,
                "why_queued": "面试/教学设计量规权重未签署，运行时只出反馈。",
                "next_action": "教研签署 数据集/教资/rubrics 下的权重与档位措辞后 reopen。",
            },
        )
