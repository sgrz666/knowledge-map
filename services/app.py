"""FastAPI runtime entrypoint for H-MAATS agent microservices."""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.common.models import (
    ErrorReviewEvent,
    ReviewBundle,
    SubjectiveGradingRequest,
    UnifiedSubjectiveGradingResponse,
    UserMasteryRecord,
)
from services.grader.agent import SubjectiveGraderAgent
from services.memory.agent import MemoryReviewAgent

app = FastAPI(
    title="H-MAATS Adaptive Exam Agent Services",
    description="Microservices powering adaptive grading, spaced repetition, and diagnostic tutoring for CET and NTCE.",
    version="1.0.0",
)

# Instantiate singleton agent instances
grader_agent = SubjectiveGraderAgent()
memory_agent = MemoryReviewAgent()


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
        agents_ready=["SubjectiveGraderAgent", "MemoryReviewAgent", "SafetyGuard"],
    )


@app.post("/api/v1/grade/subjective", response_model=UnifiedSubjectiveGradingResponse)
def grade_subjective(request: SubjectiveGradingRequest, answer_status: str = "normal"):
    """Evaluate a subjective question submission using dual-mode rubrics."""
    try:
        response = grader_agent.grade(request, answer_status=answer_status)
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Grading failed: {str(exc)}")


@app.post("/api/v1/memory/review", response_model=ReviewBundle)
def process_review_event(event: ErrorReviewEvent):
    """Process student answering event, update FSRS scheduling, and return error attribution."""
    try:
        bundle = memory_agent.process_event(event)
        return bundle
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Memory review processing failed: {str(exc)}")


@app.get("/api/v1/memory/mastery/{user_id}/{node_id}", response_model=Optional[UserMasteryRecord])
def get_user_mastery(user_id: str, node_id: str):
    """Retrieve user mastery record for a specific knowledge node."""
    record = memory_agent.get_user_mastery(user_id, node_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Mastery record not found")
    return record
