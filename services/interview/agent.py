"""InterviewCoachAgent providing trial teaching speech feedback and lesson plan assessment."""
from __future__ import annotations

from services.common.models import (
    LessonPlanReviewRequest,
    LessonPlanReviewResponse,
    SpeechAnalysisRequest,
    SpeechAnalysisResponse,
)
from services.interview.lesson_plan import LessonPlanEvaluator
from services.interview.speech_analyzer import SpeechAnalyzer


class InterviewCoachAgent:
    """Agent coaching NTCE candidates through virtual trial teaching and lesson planning."""

    def __init__(self):
        pass

    def analyze_speech(self, req: SpeechAnalysisRequest) -> SpeechAnalysisResponse:
        """Evaluate transcribed speech and pacing of trial teaching."""
        return SpeechAnalyzer.evaluate(req)

    def review_lesson_plan(self, req: LessonPlanReviewRequest) -> LessonPlanReviewResponse:
        """Evaluate 20-minute timed lesson design draft against official rubrics."""
        return LessonPlanEvaluator.evaluate(req)
