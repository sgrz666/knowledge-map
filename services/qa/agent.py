"""TutorQAAgent: evidence-grounded 3-chain explanations and Socratic dialogs.

The agent owns no knowledge of its own; it resolves the request's ``question_id`` against
the knowledge library and lets TrustGate decide what may be shown at the requested tier.
"""
from __future__ import annotations

from typing import List, Optional, Union

from services.common.models import (
    QARequest,
    SocraticHintResponse,
    SparksThreeChainResponse,
)
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.retrieval import RetrievalService, get_retrieval_service
from services.knowledge.trust import TrustGate
from services.qa.socratic import SocraticTutorEngine
from services.qa.sparks_chain import SparksChainEngine


class TutorQAAgent:
    """Agent answering student questions with evidence provenance and Socratic guidance."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        gate: Optional[TrustGate] = None,
        retrieval_service: Optional[RetrievalService] = None,
    ) -> None:
        self.repository = repository or get_repository()
        self._gate = gate
        self._retrieval_service = retrieval_service

    @property
    def retrieval(self) -> RetrievalService:
        if self._retrieval_service is None:
            self._retrieval_service = get_retrieval_service()
        return self._retrieval_service

    def _gate_for(self, req: QARequest) -> TrustGate:
        if self._gate is not None and req.trust_tier.value == self._gate.tier:
            return self._gate
        return TrustGate(req.trust_tier.value)

    def answer_query(
        self, req: QARequest
    ) -> Union[SparksThreeChainResponse, SocraticHintResponse]:
        """Dispatch the query to the engine matching the requested mode, with RAG query resolution."""
        gate = self._gate_for(req)
        target_qid = req.question_id
        record = self.repository.load_question(target_qid) if target_qid else None

        rag_notices: List[str] = []
        if record is None and req.user_query and req.user_query.strip():
            try:
                retrieval = self.retrieval.search(
                    req.user_query.strip(),
                    tier=req.trust_tier.value,
                    k=3,
                )
                candidates = retrieval.get("candidates", [])
                if candidates:
                    cand_qid = candidates[0]["question_id"]
                    cand_rec = self.repository.load_question(cand_qid)
                    if cand_rec is not None:
                        target_qid = cand_qid
                        record = cand_rec
                        rag_notices.append(
                            f"通过 RAG 向量检索锚定最相关题目：{target_qid}（相似度 {candidates[0]['score']:.2f}）"
                        )
            except Exception:
                pass

        if req.mode == "socratic_hint":
            resp = SocraticTutorEngine(self.repository, gate).hint(
                question_id=target_qid,
                hint_turn=req.hint_turn,
                user_selected_option=req.user_selected_option,
            )
        else:
            resp = SparksChainEngine(
                self.repository, gate, retrieval_service=self.retrieval
            ).explain(
                question_id=target_qid,
                user_selected_option=req.user_selected_option,
            )

        if rag_notices and hasattr(resp, "notices"):
            resp.notices = list(dict.fromkeys(list(resp.notices) + rag_notices))
        return resp

    def search_question_id(self, keyword: str, exam: Optional[str] = None, limit: int = 5) -> list:
        """Help callers reach the library with a real question_id using RAG semantic search."""
        text = (keyword or "").strip()
        if not text:
            return []
        hits = []
        try:
            retrieval = self.retrieval.search(text, exam=exam, k=limit)
            for cand in retrieval.get("candidates", []):
                qid = cand.get("question_id")
                meta = self.repository.get_meta(qid)
                if not meta:
                    continue
                record = self.repository.load_question(qid) or {}
                stem = ((record.get("content") or {}).get("stem") or "")
                hits.append(
                    {
                        "question_id": qid,
                        "exam": meta.exam,
                        "module": meta.module,
                        "stem": stem[:80],
                        "review_status": meta.review_status,
                    }
                )
                if len(hits) >= limit:
                    break
        except Exception:
            hits = []

        if not hits:
            for meta in self.repository.find_questions(exams=(exam,) if exam else None):
                record = self.repository.load_question(meta.question_id) or {}
                stem = ((record.get("content") or {}).get("stem") or "")
                if text.lower() not in meta.question_id.lower() and text.lower() not in stem.lower():
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
