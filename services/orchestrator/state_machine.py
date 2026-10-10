"""In-house orchestration state machine (§3.4) — no external graph framework.

The closed loop from the design document §2.1 is encoded literally:

    IDLE → DIAGNOSE → PROFILE → PLAN → PRACTICE|MOCK → GRADE | FEEDBACK_ONLY
         → ATTRIBUT → REPROFILE → (PLAN | DONE)

Every hop must declare its timeout, its required inputs and a degrade exit. A degrade that
reflects the *content* — the gate refusing it, a node raising, a node with no handler, a session
that never converges — lands on ``REVIEW_QUEUE`` and becomes a record for the 教研 reviewer
instead of a fabricated conclusion. A degrade that only reflects a **missing input from the
caller** ends the turn without a queue row: 教研 cannot sign a learner's answer into existence, and
filling their queue with such rows would bury the items they can actually decide (A9).

The machine touches neither disk nor LLM. Handlers are injected, and the queue write happens
through the ``on_degrade`` callback the runtime supplies, which keeps this module unit-testable
and replayable (acceptance A8).
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from services.common.models import (
    AgentMessageEnvelope,
    AuthContext,
    EvidenceItem,
    GeneratedBy,
    TrustTier,
)

MAX_STEPS = 16


class State(str, Enum):
    IDLE = "IDLE"
    DIAGNOSE = "DIAGNOSE"
    PROFILE = "PROFILE"
    PLAN = "PLAN"
    PRACTICE = "PRACTICE"
    MOCK = "MOCK"
    GRADE = "GRADE"
    FEEDBACK_ONLY = "FEEDBACK_ONLY"
    ATTRIBUT = "ATTRIBUT"
    REPROFILE = "REPROFILE"
    REVIEW_QUEUE = "REVIEW_QUEUE"
    DONE = "DONE"


Handler = Callable[[dict], dict]
DegradeHook = Callable[[dict], None]


@dataclass(frozen=True)
class NodeSpec:
    state: State
    action: str
    recipient: str
    timeout_seconds: float = 20.0
    requires: tuple = ()
    degrade_to: State = State.REVIEW_QUEUE

    def missing_inputs(self, context: dict) -> List[str]:
        # ``is_correct=False`` is an answer, not a missing input: treating falsy values as absent
        # made every wrong-answer attribution degrade.
        return [key for key in self.requires if context.get(key) in (None, "", [], {})]


def node(state: State, action: str, recipient: str, *, timeout: float = 20.0, requires: tuple = ()) -> NodeSpec:
    return NodeSpec(state=state, action=action, recipient=recipient, timeout_seconds=timeout, requires=requires)


DEFAULT_NODES: Dict[State, NodeSpec] = {
    State.IDLE: node(State.IDLE, "intake", "master"),
    State.DIAGNOSE: node(State.DIAGNOSE, "diagnostic.evaluate", "diagnostic", requires=("exam_type",)),
    State.PROFILE: node(State.PROFILE, "memory.profile", "memory", requires=("user_id",)),
    # ``weak_nodes`` is deliberately not required: the planner schedules from the library node pool
    # and reports unseen nodes as unseen, so a learner with no history gets a real calendar (and an
    # honest notice) instead of a degrade row that 教研 could not act on.
    State.PLAN: node(State.PLAN, "planner.generate", "planner", requires=("user_id", "exam_type")),
    State.PRACTICE: node(State.PRACTICE, "practice.assemble", "practice", requires=("user_id", "exam_type")),
    State.MOCK: node(State.MOCK, "practice.mock", "practice", requires=("user_id", "exam_type")),
    State.GRADE: node(State.GRADE, "grader.grade", "grader", requires=("user_id", "answer_text", "question_id")),
    State.FEEDBACK_ONLY: node(
        State.FEEDBACK_ONLY, "grader.feedback", "grader", requires=("user_id", "answer_text", "question_id")
    ),
    # ATTRIBUT is reachable with only a user_id: a learner asking "why did I get this wrong" without
    # ids gets the handler's own due-item lookup, which is a real answer, not a 教研 review item.
    State.ATTRIBUT: node(State.ATTRIBUT, "memory.attribute", "memory", requires=("user_id",)),
    State.REPROFILE: node(State.REPROFILE, "memory.profile", "memory", requires=("user_id",)),
    State.REVIEW_QUEUE: node(State.REVIEW_QUEUE, "review.enqueue", "review", requires=("user_id",)),
    State.DONE: node(State.DONE, "finish", "master"),
}

# Linear spine; branches are decided by the routing function below rather than by a table of
# boolean switches, so the "or" exits (PRACTICE|MOCK, GRADE|FEEDBACK_ONLY, PLAN|DONE) stay readable.
SPINE: List[State] = [
    State.DIAGNOSE,
    State.PROFILE,
    State.PLAN,
    State.PRACTICE,
    State.GRADE,
    State.ATTRIBUT,
    State.REPROFILE,
]


@dataclass
class RunResult:
    session_id: str
    state: State
    context: dict = field(default_factory=dict)
    envelopes: List[AgentMessageEnvelope] = field(default_factory=list)
    degraded: List[dict] = field(default_factory=list)
    finished: bool = False

    def trace_rows(self) -> List[dict]:
        return [envelope.model_dump(mode="json") for envelope in self.envelopes]


def _route(state: State, outcome: dict, context: dict, cycles: int) -> State:
    """One place that decides where a node's result sends the session."""
    if outcome.get("degrade"):
        return State.REVIEW_QUEUE
    if state is State.IDLE:
        return State.DIAGNOSE
    if state is State.DIAGNOSE:
        return State.PROFILE
    if state is State.PROFILE:
        return State.PLAN
    if state is State.PLAN:
        return State.MOCK if context.get("mode") == "mock" or outcome.get("prefer_mock") else State.PRACTICE
    if state in (State.PRACTICE, State.MOCK):
        if context.get("answer_text"):
            return State.GRADE if outcome.get("rubric_signed") else State.FEEDBACK_ONLY
        if context.get("selected_option") and context.get("question_id"):
            # A named question plus a chosen option can be checked against the library key, so the
            # session has a real right/wrong signal to attribute; anything less has none.
            return State.ATTRIBUT
        # Nothing was submitted: the loop pauses honestly instead of inventing an answer.
        return State.DONE
    if state in (State.GRADE, State.FEEDBACK_ONLY):
        # Feedback on an unsigned rubric carries no right/wrong signal, so there is nothing to
        # attribute; pausing here is honest, inventing an is_correct value would not be.
        return State.ATTRIBUT if outcome.get("attributable", True) else State.DONE
    if state is State.ATTRIBUT:
        return State.REPROFILE
    if state is State.REPROFILE:
        if cycles >= 2 or not context.get("replan"):
            return State.DONE
        return State.PLAN
    if state is State.REVIEW_QUEUE:
        return State.DONE
    return State.DONE


class Orchestrator:
    """Runs the loop against injected handlers; every hop emits one AgentMessageEnvelope."""

    def __init__(
        self,
        handlers: Dict[State, Handler],
        *,
        nodes: Optional[Dict[State, NodeSpec]] = None,
        on_degrade: Optional[DegradeHook] = None,
        trace_sink: Optional[Callable[[dict], None]] = None,
        max_cycles: int = 2,
    ) -> None:
        self.handlers = handlers
        self.nodes = nodes or DEFAULT_NODES
        self.on_degrade = on_degrade
        self.trace_sink = trace_sink
        self.max_cycles = max_cycles

    def run(
        self,
        *,
        session_id: str,
        user_id: str,
        exam_type: str = "NTCE",
        tier: TrustTier = TrustTier.RESEARCH_INTERNAL,
        context: Optional[dict] = None,
        entry: State = State.IDLE,
    ) -> RunResult:
        merged = {
            "user_id": user_id,
            "exam_type": exam_type,
            "trust_tier": tier.value if isinstance(tier, TrustTier) else str(tier),
        }
        merged.update(context or {})
        result = RunResult(session_id=session_id, state=entry, context=merged)
        auth = AuthContext(user_id=user_id, exam=exam_type)  # type: ignore[arg-type]
        cycles = 0
        state = entry
        seen_notices: List[str] = [n for n in (merged.get("notices_seen") or []) if isinstance(n, str)]
        merged["notices_seen"] = seen_notices

        for _ in range(MAX_STEPS):
            spec = self.nodes.get(state)
            if spec is None:
                result.state = state
                result.finished = state is State.DONE
                return result

            missing = spec.missing_inputs(merged)
            handler = self.handlers.get(state)
            if missing:
                # The caller can close this gap by sending the missing field; a reviewer cannot.
                self._degrade(
                    result,
                    state,
                    f"{state.value} 缺少输入：{', '.join(missing)}",
                    auth=auth,
                    spec=spec,
                    merged=merged,
                    kind="input_gap",
                    missing=missing,
                    queue=False,
                )
                result.state = state
                return result
            if handler is None:
                self._degrade(
                    result,
                    state,
                    f"{state.value} 无可用处理器，会话降级为人工复核。",
                    auth=auth,
                    spec=spec,
                    merged=merged,
                    kind="no_handler",
                )
                state = spec.degrade_to
                continue

            outcome = self._invoke(handler, spec, merged, result, state, auth)
            if outcome is None:
                state = spec.degrade_to
                continue

            envelope = self._envelope(spec, state, outcome, merged, auth, tier)
            result.envelopes.append(envelope)
            if self.trace_sink:
                self.trace_sink(envelope.model_dump(mode="json"))
            merged.update({k: v for k, v in (outcome.get("context") or {}).items() if v is not None})
            # Handlers receive a context *copy* (they run in their own thread), so notices can only
            # reach the session through the machine; without this the reply would drop every notice.
            for note in outcome.get("notices") or []:
                if note not in seen_notices:
                    seen_notices.append(note)
            merged["notices_seen"] = seen_notices
            for blocked in outcome.get("blocked") or []:
                self._record_blocked(result, state, blocked, auth, spec, merged)

            if outcome.get("degrade"):
                # A handler that asks for a human must produce the human's row here; otherwise the
                # REVIEW_QUEUE card would report a queue entry that was never written.
                self._degrade(
                    result, state,
                    str(outcome.get("degrade_reason") or outcome.get("summary") or "处理器判定需人工复核。"),
                    auth=auth, spec=spec, merged=merged, kind="handler_degrade",
                )

            state = _route(state, outcome, merged, cycles)
            if state in (State.PLAN, State.DIAGNOSE):
                cycles += 1
            if state is State.DONE:
                result.state = State.DONE
                result.finished = True
                return result
            result.state = state
        result.state = state
        self._degrade(result, state, f"步数预算 {MAX_STEPS} 用尽，会话未收敛，转人工复核。", auth=auth,
                      spec=self.nodes.get(state) or DEFAULT_NODES[State.DONE], merged=merged,
                      kind="budget")
        result.state = State.DONE
        result.finished = True
        return result

    # ---------------------------------------------------------------- internals
    def _invoke(
        self,
        handler: Handler,
        spec: NodeSpec,
        context: dict,
        result: RunResult,
        state: State,
        auth: AuthContext,
    ) -> Optional[dict]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(handler, dict(context))
            try:
                return future.result(timeout=spec.timeout_seconds)
            except concurrent.futures.TimeoutError:
                self._degrade(
                    result, state, f"{state.value} 超时（{spec.timeout_seconds}s），本次不出结论。",
                    auth=auth, spec=spec, merged=context, kind="timeout",
                )
            except Exception as exc:  # a node failure is a review item, never a fabricated result
                self._degrade(
                    result, state, f"{state.value} 执行失败：{type(exc).__name__}: {exc}",
                    auth=auth, spec=spec, merged=context, kind="handler_error",
                )
            return None

    def _envelope(
        self,
        spec: NodeSpec,
        state: State,
        outcome: dict,
        context: dict,
        auth: AuthContext,
        tier: TrustTier,
    ) -> AgentMessageEnvelope:
        evidence = [EvidenceItem.model_validate(row) for row in outcome.get("evidence") or []]
        generated = GeneratedBy(
            agent=f"{spec.recipient}.{state.value.lower()}",
            requested_model=outcome.get("requested_model"),
            mode=outcome.get("mode", "deterministic"),
            prompt_sha256=outcome.get("prompt_sha256"),
        )
        return AgentMessageEnvelope(
            sender="orchestrator",
            recipient=spec.recipient,
            action=spec.action,
            auth_context=auth,
            trust_tier=tier if isinstance(tier, TrustTier) else TrustTier(str(tier)),
            evidence=evidence,
            generated_by=generated,
            notices=list(outcome.get("notices") or []),
            payload={
                "state": state.value,
                "summary": outcome.get("summary", ""),
                "data": outcome.get("data"),
                "user_id": context.get("user_id"),
            },
            error={"blocked": outcome["blocked"]} if outcome.get("blocked") else None,
        )

    def _degrade(
        self,
        result: RunResult,
        state: State,
        reason: str,
        *,
        auth: AuthContext,
        spec: NodeSpec,
        merged: dict,
        kind: str = "review",
        missing: Optional[List[str]] = None,
        queue: bool = True,
    ) -> None:
        row = {
            "state": state.value,
            "reason": reason,
            "kind": kind,
            "user_id": merged.get("user_id", ""),
            "trust_tier": merged.get("trust_tier"),
        }
        if missing:
            row["missing_inputs"] = list(missing)
        result.degraded.append(row)
        if not queue:
            return
        if self.on_degrade:
            self.on_degrade(row)
        result.envelopes.append(
            AgentMessageEnvelope(
                sender="orchestrator",
                recipient="review",
                action="review.enqueue",
                auth_context=auth,
                trust_tier=TrustTier(merged.get("trust_tier", "research_internal")),
                generated_by=GeneratedBy(agent=f"orchestrator.{state.value.lower()}", mode="deterministic"),
                notices=[reason],
                payload={"state": State.REVIEW_QUEUE.value, "summary": reason, "data": row},
                error=row,
            )
        )
        if self.trace_sink:
            self.trace_sink(result.envelopes[-1].model_dump(mode="json"))

    def _record_blocked(
        self,
        result: RunResult,
        state: State,
        blocked: dict,
        auth: AuthContext,
        spec: NodeSpec,
        merged: dict,
    ) -> None:
        row = {"state": state.value, "reason": str(blocked.get("reason", "内容被信任门禁拒绝")), **blocked}
        row.setdefault("user_id", merged.get("user_id", ""))
        row.setdefault("trust_tier", merged.get("trust_tier"))
        row.setdefault("kind", "trust_gate")
        result.degraded.append(row)
        if self.on_degrade:
            self.on_degrade(row)


def replay(session_id: str, store) -> List[dict]:
    """Read the stored envelope trace back out — A8 requires the loop to be replayable."""
    return store.trace(session_id)
