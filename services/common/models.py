"""Common Pydantic data models for the H-MAATS adaptive multi-agent system."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Generic, List, Literal, Optional, TypeVar, Union

from pydantic import BaseModel, Field

T = TypeVar("T")


class ExamType(str, Enum):
    CET4 = "CET-4"
    CET6 = "CET-6"
    NTCE = "NTCE"


class UserRole(str, Enum):
    STUDENT = "student"
    RESEARCHER = "researcher"
    ADMIN = "admin"


class AuthContext(BaseModel):
    """User and request authentication context."""
    user_id: str
    role: UserRole = UserRole.STUDENT
    exam: ExamType = ExamType.NTCE


class AgentMessageEnvelope(BaseModel, Generic[T]):
    """Unified RPC / Message envelope for agent-to-agent communication."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sender: str
    recipient: str
    action: str
    auth_context: AuthContext
    payload: T
    error: Optional[dict] = None


# ---------------------------------------------------------------------------
# Subjective Grader Models
# ---------------------------------------------------------------------------

class SubjectiveGradingRequest(BaseModel):
    """Input payload for SubjectiveGraderAgent."""
    question_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    task_type: str = Field(
        ...,
        description="Task type: writing, paragraph_translation, case_analysis, lesson_plan, short_answer, interview_qa, essay"
    )
    stem: str
    material_text: Optional[str] = None
    student_answer: str
    reference_answer: Optional[str] = None
    rubric_id: Optional[str] = None
    max_score: Optional[float] = None
    scoring_mode: Literal["auto", "holistic_band", "analytic_criteria"] = "auto"


class HolisticDimensionFeedback(BaseModel):
    """Qualitative diagnostic feedback per dimension for CET holistic grading."""
    dimension_name: str
    feedback_comment: str
    evidence_quote: str = ""


class HolisticDetails(BaseModel):
    """Details for CET official holistic band selection."""
    selected_band: int = Field(..., description="Selected band level: 14, 11, 8, 5, 2")
    band_range: List[float] = Field(..., min_length=2, max_length=2, description="Score range [min, max]")
    qualitative_dimensions: List[HolisticDimensionFeedback] = Field(default_factory=list)


class AnalyticDimensionResult(BaseModel):
    """Grading result for an analytic dimension (NTCE)."""
    dimension_name: str
    score: float
    max_score: float
    level_name: str
    rationale: str


class RubricPointHit(BaseModel):
    """Key scoring point hit detection."""
    point_text: str
    status: Literal["hit", "partial", "missed"]
    evidence: str = ""


class AnalyticDetails(BaseModel):
    """Details for NTCE analytic criteria-based grading."""
    dimensions: List[AnalyticDimensionResult] = Field(default_factory=list)
    rubric_points_hit: List[RubricPointHit] = Field(default_factory=list)


class UnifiedSubjectiveGradingResponse(BaseModel):
    """Unified subjective grading output schema conforming to Section 4.2 of the specification."""
    question_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    grading_mode: Literal["holistic_band", "analytic_criteria"]
    total_score: float = Field(..., description="Total awarded score")
    max_score: float = Field(..., gt=0.0)
    holistic_details: Optional[HolisticDetails] = None
    analytic_details: Optional[AnalyticDetails] = None
    evaluation_summary: str
    revision_advice: str
    confidence_score: float = Field(default=0.85, ge=0.0, le=1.0)
    review_status: Literal["llm_graded", "heuristic_graded", "expert_reviewed", "quarantined_for_human"] = "llm_graded"


# ---------------------------------------------------------------------------
# Error Attribution & FSRS Memory Models
# ---------------------------------------------------------------------------

class ErrorAttributionCategory(str, Enum):
    CARELESS = "careless"                  # 审题疏漏
    MISCONCEPTION = "misconception"        # 概念混淆
    BLINDSPOT = "blindspot"                # 认知盲区
    TIME_PRESSURE = "time_pressure"        # 策略不当 (时间分配/随机猜选)
    EXPRESSION_DEFICIT = "expression_deficit"  # 表述不规范 (主观题踩分点遗漏)


class ErrorAttributionResult(BaseModel):
    """Educational attribution classification for an erroneous response."""
    category: ErrorAttributionCategory
    category_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    recommended_action: str


class FSRSState(BaseModel):
    """Free Spaced Repetition Scheduler (FSRS-v4) memory state."""
    stability: float = Field(..., ge=0.01, description="Memory stability S in days")
    difficulty: float = Field(..., ge=1.0, le=10.0, description="Item difficulty D [1, 10]")
    due_date: str = Field(..., description="ISO 8601 next review date")
    state: Literal["learning", "review", "relearning"] = "learning"
    reps: int = 0
    lapses: int = 0
    last_review: Optional[str] = None


class UserMasteryRecord(BaseModel):
    """User mastery entity conforming to 数据集/教资/schemas/user_mastery.json."""
    user_id: str
    node_id: str
    mastery_score: float = Field(..., ge=0.0, le=1.0, description="Mastery score [0, 1]")
    practice_count: int = 0
    correct_count: int = 0
    fsrs_state: FSRSState
    last_updated_at: str


class ErrorReviewEvent(BaseModel):
    """Input event when a user answers a question."""
    user_id: str
    question_id: str
    node_id: str
    exam: Literal["CET-4", "CET-6", "NTCE"]
    is_correct: bool
    time_spent_seconds: float
    option_flip_count: int = 0
    selected_option: Optional[str] = None
    correct_option: Optional[str] = None
    question_difficulty: float = 0.5
    current_node_mastery: float = 0.5
    is_subjective: bool = False
    subjective_rubric_misses: Optional[List[str]] = None
    has_negation_in_stem: bool = False
    is_typical_distractor: bool = False


class ReviewBundle(BaseModel):
    """Response returned by MemoryReviewAgent after processing an answer event."""
    user_id: str
    node_id: str
    attribution: ErrorAttributionResult
    updated_mastery: UserMasteryRecord
    fsrs_rating: int = Field(..., ge=1, le=4, description="FSRS rating: 1=Again, 2=Hard, 3=Good, 4=Easy")
    retrievability: float = Field(..., ge=0.0, le=1.0, description="Predicted retrievability R")
    next_review_interval_days: float
    followup_plan: str
