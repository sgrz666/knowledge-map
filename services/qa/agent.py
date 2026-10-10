"""TutorQAAgent: evidence-grounded 3-chain explanations and Socratic dialogs.

The agent owns no knowledge of its own; it resolves the request's ``question_id`` against
the knowledge library and lets TrustGate decide what may be shown at the requested tier.
"""
from __future__ import annotations

from typing import Optional, Union

from services.common.models import (
    QARequest,
    SocraticHintResponse,
    SparksThreeChainResponse,
)
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate
from services.qa.socratic import SocraticTutorEngine
from services.qa.sparks_chain import SparksChainEngine


class TutorQAAgent:
    """Agent answering student questions with evidence provenance and Socratic guidance."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        gate: Optional[TrustGate] = None,
    ) -> None:
        self.repository = repository or get_repository()
        self._gate = gate

    def _gate_for(self, req: QARequest) -> TrustGate:
        if self._gate is not None and req.trust_tier.value == self._gate.tier:
            return self._gate
        return TrustGate(req.trust_tier.value)

    def answer_query(
        self, req: QARequest
    ) -> Union[SparksThreeChainResponse, SocraticHintResponse]:
        """Dispatch the query to the engine matching the requested mode."""
        gate = self._gate_for(req)
        if req.mode == "socratic_hint":
            return SocraticTutorEngine(self.repository, gate).hint(
                question_id=req.question_id,
                hint_turn=req.hint_turn,
                user_selected_option=req.user_selected_option,
            )
        return SparksChainEngine(self.repository, gate).explain(
            question_id=req.question_id,
            user_selected_option=req.user_selected_option,
        )

    def search_question_id(self, keyword: str, exam: Optional[str] = None, limit: int = 5) -> list:
        """Help callers reach the library with a real question_id instead of an invented one."""
        text = (keyword or "").strip().lower()
        if not text:
            return []
        hits = []
        for meta in self.repository.find_questions(exams=(exam,) if exam else None):
            record = self.repository.load_question(meta.question_id) or {}
            stem = ((record.get("content") or {}).get("stem") or "")
            if text not in meta.question_id.lower() and text not in stem.lower():
                continue
            hits.append(
                {
                    "question_id": meta.question_id,
                    "exam": meta.exam,
                    "module": meta.module,
                    "stem": stem[:80],
                    "review_status": meta.review_status,
                }
            )
            if len(hits) >= limit:
                break
        return hits
