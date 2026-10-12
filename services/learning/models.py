"""Only context and user intent enter these APIs; progress is read from storage."""
from typing import Optional
from pydantic import ConfigDict, Field
from services.web.models import WebContext


class LearningRequest(WebContext):
    model_config = ConfigDict(extra='forbid')


class DiagnosticStartRequest(LearningRequest):
    request_id: str = Field(min_length=1, max_length=120)
    item_count: int = Field(default=8, ge=1, le=30)


class DiagnosticResultRequest(LearningRequest):
    diagnostic_id: str = Field(min_length=1, max_length=120)


class PlanCreateRequest(LearningRequest):
    request_id: str = Field(min_length=1, max_length=120)
    days_until_exam: int = Field(default=30, ge=1, le=180)
    daily_available_minutes: int = Field(default=60, ge=15, le=360)


class PlanReplanRequest(LearningRequest):
    request_id: str = Field(min_length=1, max_length=120)
    plan_id: str = Field(min_length=1, max_length=120)


class TaskRequest(LearningRequest):
    plan_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=120)


class InterviewStartRequest(LearningRequest):
    request_id: str = Field(min_length=1, max_length=120)


class InterviewAnswerRequest(LearningRequest):
    request_id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=120)
    answer_text: str = Field(min_length=1, max_length=20000)
    duration_seconds: Optional[float] = Field(default=None, gt=0, le=7200)
