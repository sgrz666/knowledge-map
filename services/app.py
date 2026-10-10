"""FastAPI runtime entrypoint for the H-MAATS agent microservices (layer F).

Three rules the previous version of this file did not have:

1. **Readiness is probed, not declared.** ``/health`` runs each agent once against a throwaway
   review queue and session store; a broken agent reports ``not_ready`` with the exception text
   instead of the service claiming eight healthy agents it never checked. Probing with throwaway
   resources matters: a health check must not append rows to the single human reviewer's queue,
   and it must not write learner state.
2. **The caller cannot pick an answer key.** ``answer_status`` used to be a query parameter, so a
   client could declare a ``source_conflict`` question "normal" and get a grade. Status now comes
   from the knowledge index only.
3. **Tier is authenticated, not free-form.** ``research_internal`` requires the runtime token when
   ``KNOWLEDGE_MAP_RUNTIME_TOKEN`` is configured (the header is resolved by FastAPI per request and
   compared with ``secrets.compare_digest``); ``published`` needs no token precisely because it is
   the tier that currently serves nothing.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import AsyncIterator, Optional, Union

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ValidationError

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
    RetrievalRequest,
    RetrievalResponse,
    SocraticHintResponse,
    SparksThreeChainResponse,
    SpeechAnalysisRequest,
    SpeechAnalysisResponse,
    SubjectiveGradingRequest,
    TrustTier,
    UnifiedSubjectiveGradingResponse,
    UserMasteryRecord,
)
from services.diagnostic.agent import DiagnosticAgent
from services.grader.agent import SubjectiveGraderAgent
from services.interview.agent import InterviewCoachAgent
from services.knowledge.repository import get_repository
from services.knowledge.retrieval import RetrievalService, get_retrieval_service
from services.knowledge.trust import TrustGate
from services.master.agent import TutorMasterAgent
from services.memory.agent import MemoryReviewAgent
from services.orchestrator.session import SessionStore, get_session_store
from services.planner.agent import CurriculumPlannerAgent
from services.practice.agent import PracticeEngineAgent
from services.qa.agent import TutorQAAgent
from services.review.queue import ReviewQueue, get_review_queue

ENV_RUNTIME_TOKEN = "KNOWLEDGE_MAP_RUNTIME_TOKEN"
VERSION = "1.1.0"

app = FastAPI(
    title="H-MAATS Adaptive Exam Agent Services",
    description=(
        "Microservices for adaptive diagnostics, planning, practice, tutoring and interview "
        "coaching over the CET-4/6 and NTCE knowledge library. Every response carries the trust "
        "tier and the review state of the content it quotes."
    ),
    version=VERSION,
)

repository = get_repository()
grader_agent = SubjectiveGraderAgent(repository=repository)
memory_agent = MemoryReviewAgent()
diagnostic_agent = DiagnosticAgent(repository=repository)
planner_agent = CurriculumPlannerAgent(repository=repository)
practice_agent = PracticeEngineAgent(repository=repository)
qa_agent = TutorQAAgent(repository=repository)
interview_agent = InterviewCoachAgent(repository=repository)
master_agent = TutorMasterAgent(repository=repository)
retrieval_service = get_retrieval_service()
review_queue = get_review_queue()


class HealthResponse(BaseModel):
    status: str
    version: str
    agents_ready: list[str]
    agents_not_ready: list[str]
    library: dict
    llm_mode: str
    review_queue_pending: int


class AuthContext:
    """The request's ``Authorization`` header, turned into a tier decision."""

    def __init__(self, authorization: Optional[str]) -> None:
        self.authorization = authorization or ""

    @classmethod
    def from_header(cls, authorization: Optional[str] = Header(default=None)) -> "AuthContext":
        return cls(authorization)

    def require(self, tier: TrustTier) -> TrustTier:
        token = os.environ.get(ENV_RUNTIME_TOKEN, "").strip()
        if tier is TrustTier.RESEARCH_INTERNAL and token:
            supplied = self.authorization.removeprefix("Bearer ").strip()
            if not supplied or not secrets.compare_digest(supplied, token):
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "research_internal 档需要运行时令牌（Authorization: Bearer <"
                        f"{ENV_RUNTIME_TOKEN}>）；未持令牌的调用只能取 published 档，"
                        "而 published 档在教研签署前是空集。"
                    ),
                )
        return tier


# ---------------------------------------------------------------------------
# Readiness probe
# ---------------------------------------------------------------------------

def _probe_resources():
    """Isolated queue + session store so probing never writes the real reviewer queue."""
    root = Path(tempfile.mkdtemp(prefix="hm-probe-"))
    queue = ReviewQueue(root=root / "review_queue")
    sessions = SessionStore(root / "orchestrator.sqlite3")
    agents = {
        "SubjectiveGraderAgent": SubjectiveGraderAgent(repository=repository, review_queue=queue),
        "InterviewCoachAgent": InterviewCoachAgent(repository=repository, review_queue=queue),
        "DiagnosticAgent": DiagnosticAgent(repository=repository, queue=queue),
        "TutorMasterAgent": TutorMasterAgent(
            repository=repository, queue=queue, session_store=sessions
        ),
        "RetrievalService": RetrievalService(repository=repository, queue=queue),
    }
    return root, agents


def _probe(name: str, call) -> tuple[str, Optional[str]]:
    try:
        call()
        return (name, None)
    except Exception as exc:  # readiness must report the failure, not hide it
        return (name, f"{type(exc).__name__}: {exc}")


def _readiness() -> tuple[list[str], list[str]]:
    root, agents = _probe_resources()
    gate = TrustGate("research_internal")
    # Probe against real library ids: a probe that only runs on a made-up id proves the wiring
    # exists, not that the agent can still reach the index.
    sample = next(iter(repository.find_questions(exams="NTCE", require_nodes=True)), None)
    subjective = next(
        iter(
            repository.find_questions(
                exams="NTCE", require_nodes=True, question_types=("材料分析", "简答")
            )
        ),
        sample,
    )
    question_id = sample.question_id if sample else "healthcheck-missing-question"
    subjective_id = subjective.question_id if subjective else question_id
    checks: dict[str, object] = {
        "KnowledgeRepository": lambda: _require(repository.stats()["question_records"] > 0, "题目索引为空"),
        "GraphIndex": lambda: agents["RetrievalService"].repository.stats(),
        "VectorCardIndex": lambda: retrieval_service.cards.notices(),
        "TrustGate": lambda: gate.classify(
            question_id=question_id, review_status="needs_fix", answer_status="reference_only"
        ),
        "TutorQAAgent": lambda: qa_agent.answer_query(
            QARequest(user_id="healthcheck", question_id=question_id)
        ),
        "SubjectiveGraderAgent": lambda: agents["SubjectiveGraderAgent"].grade(
            SubjectiveGradingRequest(
                question_id=subjective_id,
                exam_type="NTCE",
                task_type="case_analysis",
                stem="healthcheck",
                student_answer="healthcheck",
                trust_tier=TrustTier.RESEARCH_INTERNAL,
            )
        ),
        "PracticeEngineAgent": lambda: practice_agent.assemble_paper(
            AssemblePaperRequest(
                user_id="healthcheck",
                exam_type="NTCE",
                practice_mode="daily_practice",
                item_count=1,
            )
        ),
        "CurriculumPlannerAgent": lambda: planner_agent.generate_plan(
            PlanRequest(
                user_id="healthcheck",
                exam_type="NTCE",
                days_until_exam=2,
                daily_available_minutes=15,
            )
        ),
        "DiagnosticAgent": lambda: agents["DiagnosticAgent"].evaluate(
            DiagnosticRequest(user_id="healthcheck", exam_type="NTCE", submissions=[])
        ),
        "MemoryReviewAgent": lambda: memory_agent.weak_node_ids("healthcheck"),
        "InterviewCoachAgent": lambda: agents["InterviewCoachAgent"].analyze_speech(
            SpeechAnalysisRequest(transcript_text="导入，新授，巩固，小结，布置作业。", audio_duration_seconds=600)
        ),
        "TutorMasterAgent": lambda: agents["TutorMasterAgent"].handle_interaction(
            MasterInteractionRequest(user_id="healthcheck", message="进行学情摸底")
        ),
        "RetrievalService": lambda: agents["RetrievalService"].search(
            "健康检查", k=1, user_id="healthcheck"
        ),
        "ReviewQueue": lambda: _require(review_queue.stats()["queue_dir"] != "", "队列目录不可用"),
    }
    try:
        ready: list[str] = []
        broken: list[str] = []
        for name, call in checks.items():
            checked, error = _probe(name, call)
            if error:
                broken.append(f"{checked}: {error}")
            else:
                ready.append(checked)
    finally:
        agents.get("TutorMasterAgent").sessions.close()  # type: ignore[union-attr]
        shutil.rmtree(root, ignore_errors=True)
    return ready, broken


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


@app.get("/api/v1/health", response_model=HealthResponse)
def health_check(probe: bool = Query(default=True)):
    """Service health: agents are probed by running them, unless ``?probe=false``."""
    stats = repository.stats()
    if probe:
        ready, broken = _readiness()
    else:
        ready, broken = [], []
    from services.llm.client import get_llm_client

    client = get_llm_client()
    return HealthResponse(
        status="healthy" if not broken else "degraded",
        version=VERSION,
        agents_ready=ready,
        agents_not_ready=broken,
        library={
            "question_records": stats["question_records"],
            "requirement_records": stats["requirement_records"],
            "paper_specs": stats["paper_specs"],
            "scan_issues": stats["scan_issues"],
        },
        llm_mode="rule_only" if client.is_rule_only else "llm",
        review_queue_pending=review_queue.stats()["pending_records"],
    )


# ---------------------------------------------------------------------------
# Retrieval facade
# ---------------------------------------------------------------------------

@app.post("/api/v1/retrieval/search", response_model=RetrievalResponse)
def retrieval_search(
    request: RetrievalRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    """Three-path recall (vector + graph + requirement clauses), already gate-filtered."""
    auth.require(request.trust_tier)
    payload = retrieval_service.search(
        request.query,
        exam=request.exam_type,
        tier=request.trust_tier.value,  # type: ignore[arg-type]
        k=request.top_k,
        user_id=request.user_id,
        modules=request.modules,
        question_types=request.question_types,
        levels=request.levels,
        use_graph=request.use_graph,
    )
    try:
        return RetrievalResponse.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail=f"检索结果不符合契约：{exc}") from exc


# ---------------------------------------------------------------------------
# Review queue (the human 教研 reviewer's only input surface)
# ---------------------------------------------------------------------------

@app.get("/api/v1/review/queue")
def queue_view(
    limit: int = Query(default=50, ge=1, le=500),
    auth: AuthContext = Depends(AuthContext.from_header),
):
    """Runtime degradations awaiting a human decision. Nothing here is ever auto-signed."""
    auth.require(TrustTier.RESEARCH_INTERNAL)
    return {"stats": review_queue.stats(), "pending": review_queue.recent(limit=limit)}


# ---------------------------------------------------------------------------
# Grader
# ---------------------------------------------------------------------------

@app.post("/api/v1/grade/subjective", response_model=UnifiedSubjectiveGradingResponse)
def grade_subjective(
    request: SubjectiveGradingRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    """Grade a subjective submission. A score appears only if the rubric is 教研签署."""
    auth.require(request.trust_tier)
    try:
        return grader_agent.grade(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Grading failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Memory & FSRS
# ---------------------------------------------------------------------------

@app.post("/api/v1/memory/review", response_model=ReviewBundle)
def process_review_event(
    event: ErrorReviewEvent, auth: AuthContext = Depends(AuthContext.from_header)
):
    """Record an answer, update FSRS scheduling, return the error attribution."""
    auth.require(TrustTier.RESEARCH_INTERNAL)
    try:
        return memory_agent.process_event(event)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Memory review failed: {exc}") from exc


@app.get("/api/v1/memory/mastery/{user_id}/{node_id}", response_model=UserMasteryRecord)
def get_user_mastery(user_id: str, node_id: str, auth: AuthContext = Depends(AuthContext.from_header)):
    # 画像按 user_id 可直接枚举，属于学习者个人数据；与写入侧同一道闸，不设令牌时才是开发默认放行。
    auth.require(TrustTier.RESEARCH_INTERNAL)
    record = memory_agent.get_user_mastery(user_id, node_id)
    if record is None:
        raise HTTPException(status_code=404, detail="该用户在该考点上还没有学习记录")
    return record


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------

@app.post("/api/v1/diagnostic/evaluate", response_model=DiagnosticReport)
def evaluate_diagnostic(
    request: DiagnosticRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    """Coverage-based diagnostics; no IRT/CAT ability estimates exist in this build."""
    auth.require(request.trust_tier)
    try:
        return diagnostic_agent.evaluate(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diagnostic evaluation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Curriculum planner
# ---------------------------------------------------------------------------

@app.post("/api/v1/planner/generate", response_model=CurriculumPlanResponse)
def generate_curriculum_plan(
    request: PlanRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    """Calendar over library nodes; prerequisite edges stay out until they are confirmed."""
    auth.require(request.trust_tier)
    try:
        return planner_agent.generate_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Curriculum planning failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Practice engine
# ---------------------------------------------------------------------------

@app.post("/api/v1/practice/assemble", response_model=PracticePaperResponse)
def assemble_practice_paper(
    request: AssemblePaperRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    """Assemble a practice or mock paper from real indexed questions."""
    auth.require(request.trust_tier)
    try:
        return practice_agent.assemble_paper(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Paper assembly failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Tutor QA
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/qa/query",
    response_model=Union[SparksThreeChainResponse, SocraticHintResponse],
)
def query_tutor_qa(request: QARequest, auth: AuthContext = Depends(AuthContext.from_header)):
    auth.require(request.trust_tier)
    try:
        return qa_agent.answer_query(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tutor QA query failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Interview coach
# ---------------------------------------------------------------------------

@app.post("/api/v1/interview/speech", response_model=SpeechAnalysisResponse)
def analyze_trial_speech(
    request: SpeechAnalysisRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    auth.require(request.trust_tier)
    try:
        return interview_agent.analyze_speech(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Speech analysis failed: {exc}") from exc


@app.post("/api/v1/interview/lesson_plan", response_model=LessonPlanReviewResponse)
def review_lesson_plan(
    request: LessonPlanReviewRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    auth.require(request.trust_tier)
    try:
        return interview_agent.review_lesson_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lesson plan review failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Master agent
# ---------------------------------------------------------------------------

@app.post("/api/v1/master/chat", response_model=MasterInteractionResponse)
def master_chat_interaction(
    request: MasterInteractionRequest, auth: AuthContext = Depends(AuthContext.from_header)
):
    auth.require(request.trust_tier)
    try:
        return master_agent.handle_interaction(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Master interaction failed: {exc}") from exc


# ---------------------------------------------------------------------------
# SSE (streamed cards: status → card → done)
# ---------------------------------------------------------------------------

def _sse(events) -> "StreamingResponse":
    from fastapi.responses import StreamingResponse

    return StreamingResponse(events, media_type="text/event-stream")


async def _stream(run, card_type: str) -> AsyncIterator[str]:
    """Run one synchronous agent call behind SSE; nothing is streamed that the gate did not allow."""

    def emit(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    yield emit("status", {"stage": "running", "card_type": card_type})
    try:
        result = await _run_in_thread(run)
    except Exception as exc:
        yield emit("error", {"detail": f"{type(exc).__name__}: {exc}", "degraded": True})
        yield emit("done", {})
        return
    payload = result.model_dump() if hasattr(result, "model_dump") else result
    yield emit("card", payload)
    notices = payload.get("notices") if isinstance(payload, dict) else None
    yield emit(
        "done",
        {
            "trust_tier": payload.get("trust_tier") if isinstance(payload, dict) else None,
            "notices": notices or [],
        },
    )


async def _run_in_thread(run):
    import anyio

    return await anyio.to_thread.run_sync(run)


@app.get("/api/v1/qa/stream")
async def qa_stream(
    question_id: str,
    user_id: str = "anonymous",
    mode: str = "sparks_three_chain",
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL,
    auth: AuthContext = Depends(AuthContext.from_header),
):
    """SSE delivery of the QA card: status first, then the gated payload, then done."""
    auth.require(trust_tier)
    request = QARequest(
        user_id=user_id,
        question_id=question_id,
        mode=mode,  # type: ignore[arg-type]
        trust_tier=trust_tier,
    )
    return _sse(_stream(lambda: qa_agent.answer_query(request), "qa_card"))


@app.get("/api/v1/master/stream")
async def master_stream(
    message: str,
    user_id: str = "anonymous",
    session_id: Optional[str] = None,
    exam_type: str = "NTCE",
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL,
    auth: AuthContext = Depends(AuthContext.from_header),
):
    """SSE delivery of one orchestrated turn (intent → running → card → done)."""
    auth.require(trust_tier)
    request = MasterInteractionRequest(
        user_id=user_id,
        message=message,
        session_id=session_id,
        exam_type=exam_type,  # type: ignore[arg-type]
        trust_tier=trust_tier,
    )
    return _sse(_stream(lambda: master_agent.handle_interaction(request), "master_card"))
