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


# ---------------------------------------------------------------------------
# Diagnostic Agent Models (F3)
# ---------------------------------------------------------------------------

class AnswerSubmission(BaseModel):
    """Individual item answering submission for diagnostic evaluation."""
    question_id: str
    user_answer: str
    is_correct: bool
    time_spent_seconds: float
    node_id: str
    module_id: str
    difficulty: float = 0.5
    option_flips: int = 0


class ModuleAbility(BaseModel):
    """Performance evaluation per syllabus module in radar chart."""
    module_id: str
    module_name: str
    mastery_rate: float = Field(..., ge=0.0, le=1.0)
    question_count: int
    correct_count: int


class DiagnosticRequest(BaseModel):
    """Request for running cold-start or adaptive diagnostic test."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    stage: Literal["cold_start", "adaptive_cat"] = "cold_start"
    submissions: Optional[List[AnswerSubmission]] = None


class DiagnosticReport(BaseModel):
    """Comprehensive diagnostic report with dual-track score conversion."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    raw_score: float
    max_raw_score: float
    point_estimate: float
    predicted_score_interval: List[float] = Field(..., min_length=2, max_length=2)
    pass_probability: float = Field(..., ge=0.0, le=1.0)
    radar_chart: List[ModuleAbility]
    weak_points_top5: List[str]
    recommended_actions: List[str]
    disclaimer: str = "本预测基于知识图谱与当前作答表现测算，仅供考前备考参考，不代表官方正式考试结果。"


# ---------------------------------------------------------------------------
# Curriculum Planner Agent Models (F4)
# ---------------------------------------------------------------------------

class DailyTaskItem(BaseModel):
    """Single actionable study task item in a daily calendar."""
    task_type: Literal["fsrs_review", "new_node_learning", "mock_sprint", "weakness_drill"]
    node_id: Optional[str] = None
    title: str
    estimated_minutes: int
    target_question_count: int


class DailyPlan(BaseModel):
    """Study schedule for a single calendar day."""
    day_index: int
    date_str: str
    focus_module: str
    tasks: List[DailyTaskItem]
    total_minutes: int


class PlanRequest(BaseModel):
    """Request payload for generating adaptive calendar."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    target_score: float = 70.0
    days_until_exam: int = Field(default=30, ge=1, le=180)
    daily_available_minutes: int = Field(default=60, ge=15, le=360)
    current_mastery: Optional[List[UserMasteryRecord]] = None


class CurriculumPlanResponse(BaseModel):
    """Adaptive study path response."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    total_days: int
    daily_plans: List[DailyPlan]
    milestones: List[str]


# ---------------------------------------------------------------------------
# Practice Engine Agent Models (F7)
# ---------------------------------------------------------------------------

class PracticeMode(str, Enum):
    POINT_FOCUS = "point_focus"                    # 考点专练
    WEAKNESS_BREAKTHROUGH = "weakness_breakthrough" # 薄弱突击
    ERROR_ELIMINATION = "error_elimination"        # 错题消灭
    DAILY_PRACTICE = "daily_practice"              # 每日一练
    HIGH_FREQUENCY = "high_frequency"              # 高频冲刺
    TIMED_SPRINT = "timed_sprint"                  # 限时快练
    MOCK_EXAM = "mock_exam"                        # 真题模考


class ExamStageState(BaseModel):
    """CET-4/6 Strict 3-Stage Timed State Machine status."""
    stage: Literal["writing", "listening", "reading_translation", "completed"]
    stage_time_limit_minutes: int
    time_remaining_seconds: int
    input_locked: bool
    sheet_collected: bool
    can_switch_modules: bool = False


class AssemblePaperRequest(BaseModel):
    """Request to assemble dynamic practice or mock exam."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    practice_mode: PracticeMode
    target_module: Optional[str] = None
    target_node: Optional[str] = None
    item_count: int = 10


class PracticePaperResponse(BaseModel):
    """Structured assembled test paper entity."""
    paper_id: str
    title: str
    exam_type: str
    practice_mode: PracticeMode
    questions: List[dict]
    total_items: int
    time_limit_minutes: int
    stage_state: Optional[ExamStageState] = None


# ---------------------------------------------------------------------------
# Tutor QA Agent Models (F5)
# ---------------------------------------------------------------------------

class QARequest(BaseModel):
    """Input query for evidence-based tutor QA."""
    user_id: str
    question_id: str
    user_selected_option: Optional[str] = None
    user_query: Optional[str] = None
    mode: Literal["sparks_three_chain", "socratic_hint"] = "sparks_three_chain"
    hint_turn: int = 1


class SparksThreeChainResponse(BaseModel):
    """Sparks 3-Chain Explanation (题眼定位, 选项对比, 考点溯源)."""
    question_id: str
    key_clue_localization: str
    option_discrimination: dict
    knowledge_provenance: dict
    explanation_summary: str


class SocraticHintResponse(BaseModel):
    """Socratic multi-turn progressive guidance response."""
    question_id: str
    hint_turn: int
    guiding_question: str
    scaffold_prompt: str
    is_final_reveal: bool = False
    revealed_answer: Optional[str] = None


# ---------------------------------------------------------------------------
# Interview Coach Agent Models (F7 Interview)
# ---------------------------------------------------------------------------

class SpeechAnalysisRequest(BaseModel):
    """Input audio metrics / transcript for trial teaching evaluation."""
    transcript_text: str
    audio_duration_seconds: float = Field(..., gt=0.0)
    audio_pauses: Optional[List[float]] = None
    lesson_title: Optional[str] = "小学语文《春》"


class TeachingPhaseMatch(BaseModel):
    """Match status for five essential instructional phases."""
    phase_name: Literal["导入", "新授", "巩固", "小结", "作业"]
    covered: bool
    evidence_snippet: str


class SpeechAnalysisResponse(BaseModel):
    """Diagnostic report for 10-minute trial teaching speech."""
    words_per_minute: float
    speed_evaluation: Literal["too_fast", "optimal", "too_slow"]
    filler_words_count: dict
    hesitation_pause_count: int
    teaching_phases: List[TeachingPhaseMatch]
    phase_coverage_rate: float
    overall_score: float = Field(..., ge=0.0, le=100.0)
    coaching_feedback: str


class LessonPlanReviewRequest(BaseModel):
    """20-minute timed lesson plan drafting evaluation."""
    subject: str = "教育教学知识与能力"
    grade_level: str = "小学"
    topic: str
    plan_text: str


class LessonPlanReviewResponse(BaseModel):
    """Lesson plan rubric scoring evaluation."""
    total_score: float = Field(..., ge=0.0, le=40.0)
    dimensions: List[dict]
    missed_elements: List[str]
    improvement_suggestions: str


# ---------------------------------------------------------------------------
# Tutor Master Agent Models (L1 Gateway / Orchestrator)
# ---------------------------------------------------------------------------

class UserIntent(str, Enum):
    DIAGNOSTIC = "diagnostic"
    PLAN = "plan"
    PRACTICE = "practice"
    SUBMIT_SUBJECTIVE = "submit_subjective"
    ERROR_REVIEW = "error_review"
    QA_ASK = "qa_ask"
    INTERVIEW_PRACTICE = "interview_practice"
    GENERAL_CHAT = "general_chat"


class MasterInteractionRequest(BaseModel):
    """Top-level chat message or UI click dispatching request."""
    user_id: str
    message: str
    session_id: Optional[str] = None
    exam_type: Literal["CET-4", "CET-6", "NTCE"] = "NTCE"
    action_payload: Optional[dict] = None


class MasterInteractionResponse(BaseModel):
    """Card-rendered unified conversational response."""
    session_id: str
    detected_intent: UserIntent
    reply_text: str
    card_type: Literal[
        "diagnostic_card",
        "plan_card",
        "practice_card",
        "grading_card",
        "review_card",
        "qa_card",
        "interview_card",
        "text_message"
    ]
    card_data: dict
    suggested_quick_replies: List[str]

