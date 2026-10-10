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


class TrustTier(str, Enum):
    """Runtime tier declared by the caller and enforced by TrustGate."""
    RESEARCH_INTERNAL = "research_internal"
    PUBLISHED = "published"


class AuthContext(BaseModel):
    """User and request authentication context."""
    user_id: str
    role: UserRole = UserRole.STUDENT
    exam: ExamType = ExamType.NTCE


class GeneratedBy(BaseModel):
    """Provenance stamp every agent message must carry."""
    agent: str
    version: str = "1.1.0"
    requested_model: Optional[str] = None
    mode: Literal["rule_only", "llm", "deterministic"] = "deterministic"
    prompt_sha256: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EvidenceItem(BaseModel):
    """One pointer back to library text, so no claim travels without its source."""
    question_id: Optional[str] = None
    node_id: Optional[str] = None
    requirement_id: Optional[str] = None
    standard_id: Optional[str] = None
    edge: Optional[str] = None
    locator: Optional[dict] = None
    source: Optional[str] = None
    verified: Optional[bool] = None
    notices: List[str] = Field(default_factory=list)


class AgentMessageEnvelope(BaseModel, Generic[T]):
    """Unified RPC / Message envelope for agent-to-agent communication.

    ``docs/agent_architecture.md`` §3.4 makes this the only message shape between orchestrator
    nodes: every hop must declare the tier it served, the evidence behind it, and who generated
    it. Nothing may assert a review status the gate did not clear.
    """
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sender: str
    recipient: str
    action: str
    auth_context: AuthContext
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    evidence: List[EvidenceItem] = Field(default_factory=list)
    generated_by: GeneratedBy = Field(default_factory=GeneratedBy)
    notices: List[str] = Field(default_factory=list)
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
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class HolisticDimensionFeedback(BaseModel):
    """Qualitative diagnostic feedback per dimension for CET holistic grading."""
    dimension_name: str
    feedback_comment: str
    evidence_quote: str = ""


class HolisticDetails(BaseModel):
    """Details for CET official holistic band selection.

    ``selected_band`` stays null while the rubric is unsigned: a band is a raw-score claim, and
    §10 forbids auto-scoring on unsigned rubrics. Feedback without a band is still allowed, which
    is exactly what the library's own ``score_use`` field says these bands may be used for.
    """
    selected_band: Optional[int] = Field(None, description="Band level 14/11/8/5/2; null when unsigned")
    band_range: Optional[List[float]] = Field(
        None, min_length=2, max_length=2, description="Score range [min, max]; null when unsigned"
    )
    band_reference: Optional[str] = Field(
        None, description="Transcribed official band descriptor quoted as feedback, not a reported score"
    )
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
    dimension_feedback: List[HolisticDimensionFeedback] = Field(
        default_factory=list,
        description="Per-dimension qualitative feedback; the only form allowed on an unsigned rubric",
    )


class UnifiedSubjectiveGradingResponse(BaseModel):
    """Unified subjective grading output schema.

    Acceptance A4: an unsigned rubric may never produce a score. ``total_score`` is therefore
    optional and ``feedback_only`` is the honest answer for everything the reviewer has not
    signed — the response says so instead of dressing a heuristic up as a grade.
    """
    question_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    grading_mode: Literal["holistic_band", "analytic_criteria"]
    total_score: Optional[float] = Field(
        None, description="Awarded score; null unless the rubric is 教研签署"
    )
    max_score: Optional[float] = Field(
        None, gt=0.0, description="Rubric total from the library; null when no rubric exists"
    )
    feedback_only: bool = False
    score_basis: Literal["signed_rubric", "unsigned_framework", "none"] = "unsigned_framework"
    rubric_signed: Optional[bool] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    holistic_details: Optional[HolisticDetails] = None
    analytic_details: Optional[AnalyticDetails] = None
    evaluation_summary: str
    revision_advice: str
    confidence_score: float = Field(default=0.85, ge=0.0, le=1.0)
    review_status: Literal[
        "llm_graded",
        "heuristic_graded",
        "expert_reviewed",
        "quarantined_for_human",
        # 题面本身立不住（未命中索引 / 库内只剩套名）：既不出分也不落待复核队列，
        # 因为待复核队列收的是"这条判分需要教研看一眼"，而输入缺口没有判分可看。
        "refused_ungradable_input",
    ] = "llm_graded"
    notices: List[str] = Field(default_factory=list)
    review_queue_entry: Optional[dict] = None


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
    is_correct: bool = Field(
        ..., description="Caller's claim; MemoryReviewAgent reconciles it against the library answer key (A10)"
    )
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
    attribution: Optional[ErrorAttributionResult] = None
    updated_mastery: Optional[UserMasteryRecord] = None
    fsrs_rating: Optional[int] = Field(None, ge=1, le=4, description="FSRS rating: 1=Again, 2=Hard, 3=Good, 4=Easy")
    retrievability: float = Field(default=0.0, ge=0.0, le=1.0, description="Predicted retrievability R")
    next_review_interval_days: float = 0.0
    followup_plan: str
    # 对错是谁定的必须写出来：库内答案键核对，还是只是采信了调用方的申报（A4 同一条口径）。
    verdict_source: Optional[str] = None
    attributable: bool = True
    notices: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Diagnostic Agent Models (F3)
# ---------------------------------------------------------------------------

class AnswerSubmission(BaseModel):
    """Individual item answering submission for diagnostic evaluation."""
    question_id: str
    user_answer: str
    #: 申报，不是判据：库内有可核对答案键且 ``user_answer`` 能取出选项时，以答案键为准（§8 A10）。
    #: 允许不填——没有可核对的判据时诊断宁可把这条挡在外面，也不替学习者编一个对错。
    is_correct: Optional[bool] = None
    time_spent_seconds: float
    #: 考点与模块由索引 ``knowledge_node_ids``/``module`` 投影，请求里这两个字段只是提示（§3.3 diagnostic）。
    #: 原来它们必填，等于让调用方自称"这题属于哪个考点"，而答案并不会被用到。
    node_id: Optional[str] = None
    module_id: Optional[str] = None


class ModuleAbility(BaseModel):
    """Performance evaluation per syllabus module in radar chart."""
    module_id: str
    module_name: str
    mastery_rate: float = Field(..., ge=0.0, le=1.0)
    question_count: int
    correct_count: int


class DiagnosticRequest(BaseModel):
    """Request for running cold-start or coverage-oriented diagnostic probing."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    stage: Literal["cold_start", "coverage_probe"] = "cold_start"
    submissions: Optional[List[AnswerSubmission]] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class DiagnosticReport(BaseModel):
    """Diagnostic output. §10 forbids IRT/CAT claims, so the numbers are coverage heuristics."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    raw_score: float
    max_raw_score: float
    point_estimate: Optional[float] = None
    predicted_score_interval: Optional[List[float]] = Field(None, min_length=2, max_length=2)
    pass_probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    radar_chart: List[ModuleAbility]
    weak_points_top5: List[str]
    recommended_actions: List[str]
    estimate_basis: str = "coverage_heuristic"
    publishable: bool = False
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    notices: List[str] = Field(default_factory=list)
    #: submissions the gate or the index refused, each with its reason, so the notice that counts
    #: them points at something the caller can actually read.
    blocked_submissions: List[dict] = Field(default_factory=list)
    disclaimer: str = (
        "本结果基于库内知识覆盖度与当前作答表现计算，难度为教研初估且未用真实作答数据校准，"
        "仅供备考内部参考，不构成能力测量结论，也不代表官方考试结果。"
    )


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
    days_until_exam: int = Field(default=30, ge=1, le=180)
    daily_available_minutes: int = Field(default=60, ge=15, le=360)
    current_mastery: Optional[List[UserMasteryRecord]] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class CurriculumPlanResponse(BaseModel):
    """Adaptive study path response."""
    user_id: str
    exam_type: Literal["CET-4", "CET-6", "NTCE"]
    total_days: int
    daily_plans: List[DailyPlan]
    milestones: List[str]
    prerequisite_note: str = ""
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    notices: List[str] = Field(default_factory=list)


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
    """一格模考时序状态：小节名、用时与收卡/封锁语义全部来自库内 paper_specs 的 parts[]。

    以前这里的 ``stage`` 是一个 ``Literal["writing","listening","reading_translation"]``——那份三段
    时间表是服务代码里手抄的卷面，与 ``数据集/四六级/manifest/paper_specs.jsonl`` 的四节并不一致。
    """
    #: 卷面小节名（库内 ``parts[].name``），终局为 ``completed``
    stage: str
    module: Optional[str] = None
    sheet_submission: Optional[str] = None
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
    weak_node_ids: List[str] = Field(default_factory=list)
    wrong_question_ids: List[str] = Field(default_factory=list)
    spec_id: Optional[str] = None
    school_level: Optional[str] = None
    subject: Optional[str] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class PracticePaperResponse(BaseModel):
    """Structured assembled test paper entity."""
    paper_id: str
    title: str
    exam_type: str
    practice_mode: PracticeMode
    questions: List[dict]
    total_items: int
    #: 模考必须来自库内卷面；库里没给用时就是 ``None``，而不是服务替官方考试编一个数。
    time_limit_minutes: Optional[int] = None
    stage_state: Optional[ExamStageState] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    pool_size: int = 0
    shortfall: int = 0
    spec_id: Optional[str] = None
    structure: List[dict] = Field(default_factory=list)
    notices: List[str] = Field(default_factory=list)


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
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class SparksThreeChainResponse(BaseModel):
    """Sparks 3-Chain Explanation (题眼定位, 选项对比, 考点溯源)."""
    question_id: str
    key_clue_localization: str
    option_discrimination: dict
    knowledge_provenance: dict
    explanation_summary: str
    answer_visibility: Literal["letter", "reference", "none"] = "none"
    grounded_in_library: bool = False
    notices: List[str] = Field(default_factory=list)


class SocraticHintResponse(BaseModel):
    """Socratic multi-turn progressive guidance response."""
    question_id: str
    hint_turn: int
    guiding_question: str
    scaffold_prompt: str
    is_final_reveal: bool = False
    revealed_answer: Optional[str] = None
    grounded_in_library: bool = False
    notices: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Interview Coach Agent Models (F7 Interview)
# ---------------------------------------------------------------------------

class SpeechAnalysisRequest(BaseModel):
    """Input audio metrics / transcript for trial teaching evaluation."""
    transcript_text: str
    audio_duration_seconds: float = Field(..., gt=0.0)
    audio_pauses: Optional[List[float]] = None
    lesson_title: Optional[str] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class TeachingPhaseMatch(BaseModel):
    """Match status for five essential instructional phases."""
    phase_name: Literal["导入", "新授", "巩固", "小结", "作业"]
    covered: bool
    evidence_snippet: str


class SpeechAnalysisResponse(BaseModel):
    """Diagnostic report for trial teaching speech.

    Only measured quantities here; ``overall_score`` needs a signed 试讲 rubric, which the
    library does not have yet, so it stays null instead of shipping invented weights.
    """
    words_per_minute: float
    speed_evaluation: Literal["too_fast", "optimal", "too_slow"]
    filler_words_count: dict
    hesitation_pause_count: int
    teaching_phases: List[TeachingPhaseMatch]
    phase_coverage_rate: float
    overall_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    rubric_signed: Optional[bool] = None
    coaching_feedback: str
    notices: List[str] = Field(default_factory=list)
    review_queue_entry: Optional[dict] = None


class LessonPlanReviewRequest(BaseModel):
    """20-minute timed lesson plan drafting evaluation."""
    subject: str = "教育教学知识与能力"
    grade_level: str = "小学"
    topic: str
    plan_text: str
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class LessonPlanReviewResponse(BaseModel):
    """Lesson plan review. Feedback is always available; a score needs a signed rubric."""
    total_score: Optional[float] = Field(None, ge=0.0)
    max_score: Optional[float] = Field(None, gt=0.0)
    feedback_only: bool = True
    rubric_signed: Optional[bool] = None
    rubric_id: Optional[str] = None
    dimensions: List[dict]
    missed_elements: List[str]
    improvement_suggestions: str
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    notices: List[str] = Field(default_factory=list)
    review_queue_entry: Optional[dict] = None


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
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


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
    state: str = "IDLE"
    trace: List[dict] = Field(default_factory=list)
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    notices: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Retrieval Endpoint Models (§5)
# ---------------------------------------------------------------------------

class RetrievalRequest(BaseModel):
    """Three-path retrieval input, shared by qa, the frontend and the orchestrator."""
    query: str
    user_id: str = "anonymous"
    exam_type: Optional[Literal["CET-4", "CET-6", "NTCE"]] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    top_k: int = Field(default=8, ge=1, le=50)
    modules: List[str] = Field(default_factory=list)
    levels: List[str] = Field(default_factory=list)
    question_types: List[str] = Field(default_factory=list)
    use_graph: bool = True


class RetrievalResponse(BaseModel):
    """Recall results already passed through TrustGate, with pointers back to source text."""
    trust_tier: TrustTier
    query: str
    backend: str
    libraries: List[str] = Field(default_factory=list)
    candidates: List[dict] = Field(default_factory=list)
    candidate_count: int = 0
    evidence: List[dict] = Field(default_factory=list)
    blocked: List[dict] = Field(default_factory=list)
    review_queued: int = 0
    notices: List[str] = Field(default_factory=list)
    code: Optional[str] = None
    message: Optional[str] = None

