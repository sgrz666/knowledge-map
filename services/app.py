"""FastAPI runtime entrypoint for H-MAATS agent microservices."""
from __future__ import annotations

from typing import Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.common.models import (
    AssemblePaperRequest,
    CurriculumPlanResponse,
    DiagnosticReport,
    DiagnosticRequest,
    ErrorReviewEvent,
    LessonPlanReviewRequest,
    LessonPlanReviewResponse,
    MasterInteractionRequest,
    MasterInteractionResponse,
    PlanRequest,
    PracticePaperResponse,
    QARequest,
    ReviewBundle,
    SocraticHintResponse,
    SparksThreeChainResponse,
    SpeechAnalysisRequest,
    SpeechAnalysisResponse,
    SubjectiveGradingRequest,
    UnifiedSubjectiveGradingResponse,
    UserMasteryRecord,
)
from services.diagnostic.agent import DiagnosticAgent
from services.grader.agent import SubjectiveGraderAgent
from services.interview.agent import InterviewCoachAgent
from services.master.agent import TutorMasterAgent
from services.memory.agent import MemoryReviewAgent
from services.planner.agent import CurriculumPlannerAgent
from services.practice.agent import PracticeEngineAgent
from services.qa.agent import TutorQAAgent

app = FastAPI(
    title="H-MAATS Adaptive Exam Agent Services",
    description="Microservices powering adaptive grading, spaced repetition, diagnostic testing, and instructional tutoring for CET and NTCE.",
    version="1.0.0",
)

# Instantiate singleton agent instances
grader_agent = SubjectiveGraderAgent()
memory_agent = MemoryReviewAgent()
diagnostic_agent = DiagnosticAgent()
planner_agent = CurriculumPlannerAgent()
practice_agent = PracticeEngineAgent()
qa_agent = TutorQAAgent()
interview_agent = InterviewCoachAgent()
master_agent = TutorMasterAgent()


class HealthResponse(BaseModel):
    status: str
    version: str
    agents_ready: list[str]


@app.get("/api/v1/health", response_model=HealthResponse)
def health_check():
    """Service health and agent readiness check."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        agents_ready=[
            "TutorMasterAgent",
            "DiagnosticAgent",
            "CurriculumPlannerAgent",
            "PracticeEngineAgent",
            "SubjectiveGraderAgent",
            "TutorQAAgent",
            "InterviewCoachAgent",
            "MemoryReviewAgent",
            "SafetyGuard",
        ],
    )


# ---------------------------------------------------------------------------
# Grader Agent Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/grade/subjective", response_model=UnifiedSubjectiveGradingResponse)
def grade_subjective(request: SubjectiveGradingRequest, answer_status: str = "normal"):
    """Evaluate a subjective question submission using dual-mode rubrics."""
    try:
        return grader_agent.grade(request, answer_status=answer_status)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Grading failed: {str(exc)}")


# ---------------------------------------------------------------------------
# Memory & FSRS Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/memory/review", response_model=ReviewBundle)
def process_review_event(event: ErrorReviewEvent):
    """Process student answering event, update FSRS scheduling, and return error attribution."""
    try:
        return memory_agent.process_event(event)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Memory review processing failed: {str(exc)}")


@app.get("/api/v1/memory/mastery/{user_id}/{node_id}", response_model=Optional[UserMasteryRecord])
def get_user_mastery(user_id: str, node_id: str):
    """Retrieve user mastery record for a specific knowledge node."""
    record = memory_agent.get_user_mastery(user_id, node_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Mastery record not found")
    return record


# ---------------------------------------------------------------------------
# Diagnostic Agent Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/diagnostic/evaluate", response_model=DiagnosticReport)
def evaluate_diagnostic(request: DiagnosticRequest):
    """Process answer submissions and compute psychometric report with norm/piecewise scale scores."""
    try:
        return diagnostic_agent.evaluate(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diagnostic evaluation failed: {str(exc)}")


# ---------------------------------------------------------------------------
# Curriculum Planner Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/planner/generate", response_model=CurriculumPlanResponse)
def generate_curriculum_plan(request: PlanRequest):
    """Generate adaptive multi-day calendar satisfying topological and priority constraints."""
    try:
        return planner_agent.generate_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Curriculum planning failed: {str(exc)}")


# ---------------------------------------------------------------------------
# Practice Engine Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/practice/assemble", response_model=PracticePaperResponse)
def assemble_practice_paper(request: AssemblePaperRequest):
    """Assemble practice or mock paper across 7 modalities and timed state protocols."""
    try:
        return practice_agent.assemble_paper(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Paper assembly failed: {str(exc)}")


# ---------------------------------------------------------------------------
# Tutor QA Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/qa/query", response_model=Union[SparksThreeChainResponse, SocraticHintResponse])
def query_tutor_qa(request: QARequest):
    """Answer question with Sparks 3-chain evidence or Socratic progressive scaffolding."""
    try:
        return qa_agent.answer_query(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tutor QA query failed: {str(exc)}")


# ---------------------------------------------------------------------------
# Interview Coach Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/interview/speech", response_model=SpeechAnalysisResponse)
def analyze_trial_speech(request: SpeechAnalysisRequest):
    """Analyze trial teaching speech metrics (WPM, pauses, filler words, five teaching phases)."""
    try:
        return interview_agent.analyze_speech(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Speech analysis failed: {str(exc)}")


@app.post("/api/v1/interview/lesson_plan", response_model=LessonPlanReviewResponse)
def review_lesson_plan(request: LessonPlanReviewRequest):
    """Evaluate 20-minute timed instructional design draft against official rubrics."""
    try:
        return interview_agent.review_lesson_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lesson plan review failed: {str(exc)}")


# ---------------------------------------------------------------------------
# Tutor Master Agent Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/master/chat", response_model=MasterInteractionResponse)
def master_chat_interaction(request: MasterInteractionRequest):
    """Coordinate top-level user conversation and dispatch card payloads."""
    try:
        return master_agent.handle_interaction(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Master interaction failed: {str(exc)}")
