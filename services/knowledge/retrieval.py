"""Three-path retrieval with the trust gate in the middle, per §5 of the architecture doc.

    query ─┬─ card vector recall (self-contained card bodies)
           ├─ metadata filters (exam / module / level / question_type / status)
           └─ graph neighbourhood (assesses, supports_ability, aligned_to_requirement)
                        ↓
                TrustGate filter  ← quarantine, unsigned content, over-scope copyright die here
                        ↓
                evidence[] {question_id, node_id, requirement_id, locator}

Filtering happens **after recall and before generation**, and it is the only path agents use to
reach library content, so a similarity hit can never smuggle a quarantined card into an answer.
Anything the gate blocks is also written to the review queue: a blocked request must leave a
record a human can act on (acceptance A9), not just an empty result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from services.knowledge.graph_index import get_graph_index, library_for_exam
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import (
    COPYRIGHT_NOTICE,
    SERVABLE_ANSWER_STATUSES,
    TrustGate,
    TrustTier,
)
from services.knowledge.vector_index import CardIndex, SearchHit, get_card_index
from services.review.queue import get_review_queue

# Statuses that may ever be served. Anything absent here is treated as unusable, so an unknown
# status value fails closed rather than open — and it is the same vocabulary the gate uses for
# 组卷 (``TrustVerdict.servable_in_paper``), so 召回 and 组卷 cannot disagree about a question.
RESEARCH_ANSWER_STATUSES = SERVABLE_ANSWER_STATUSES
RESEARCH_REVIEW_STATUSES = ("needs_fix", "auto_parsed", "llm_enhanced", "checked", "expert_reviewed")
PUBLISHED_REVIEW_STATUSES = ("checked", "expert_reviewed")

DUAL_TRUTH_NOTICE = (
    "卡片与题目索引状态不一致（{question_id}：card={card_status} / index={index_status}），"
    "以题目索引为准，差异已入待复核队列。"
)


@dataclass
class Evidence:
    question_id: Optional[str] = None
    node_id: Optional[str] = None
    requirement_id: Optional[str] = None
    edge: Optional[str] = None
    locator: Optional[dict] = None
    verified: Optional[bool] = None
    source: Optional[str] = None
    standard_id: Optional[str] = None
    title: Optional[str] = None
    notices: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], {})}


@dataclass
class Candidate:
    question_id: str
    library: str
    score: float
    path: str
    review_status: Optional[str]
    answer_status: Optional[str]
    answer_visibility: str
    node_ids: Tuple[str, ...]
    requirement_ids: Tuple[str, ...]
    notices: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "library": self.library,
            "score": self.score,
            "card_path": self.path,
            "review_status": self.review_status,
            "answer_status": self.answer_status,
            "answer_visibility": self.answer_visibility,
            "node_ids": list(self.node_ids),
            "requirement_ids": list(self.requirement_ids),
            "notices": self.notices,
        }


class RetrievalService:
    """Recall + graph expansion, then the gate, then evidence assembly."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        card_index: Optional[CardIndex] = None,
        queue=None,
    ) -> None:
        self.repository = repository or get_repository()
        self.cards = card_index or get_card_index()
        self.queue = queue or get_review_queue()

    # ------------------------------------------------------------------ main
    def search(
        self,
        query: str,
        *,
        exam: Optional[str] = None,
        tier: TrustTier = "research_internal",
        k: int = 8,
        user_id: str = "anonymous",
        modules: Optional[Sequence[str]] = None,
        question_types: Optional[Sequence[str]] = None,
        levels: Optional[Sequence[str]] = None,
        use_graph: bool = True,
    ) -> dict:
        gate = TrustGate(tier)
        libraries = self._libraries(exam)
        filters = self._filters(tier, modules=modules, question_types=question_types, levels=levels)

        hits: List[SearchHit] = []
        index_errors: List[str] = []
        for library in libraries:
            try:
                hits.extend(self.cards.search(query, libraries=(library,), k=k * 3, filters=filters))
            except Exception as exc:  # rebuildable index: degrade, never fabricate
                index_errors.append(f"{library} 向量召回不可用：{exc}")
        hits.sort(key=lambda h: h.score, reverse=True)

        candidates: List[Candidate] = []
        blocked: List[dict] = []
        evidence: List[Evidence] = []
        queue = self.queue

        for hit in hits:
            meta = self.repository.get_meta(hit.question_id)
            review_status, answer_status = self._reconcile(hit, meta, blocked, queue, user_id, tier)
            if review_status is None:
                continue
            verdict = gate.classify(
                question_id=hit.question_id,
                review_status=review_status,
                answer_status=answer_status,
                difficulty_method=meta.difficulty_method if meta else None,
            )
            if not verdict.usable:
                row = {
                    "question_id": hit.question_id,
                    "reason": "；".join(verdict.notices) or "TrustGate 拒绝",
                    "review_status": verdict.review_status,
                    "answer_status": verdict.answer_status,
                }
                blocked.append(row)
                queue.add(
                    reason=row["reason"],
                    user_id=user_id,
                    question_id=hit.question_id,
                    tier=tier,
                    source=hit.path,
                    detail={"path": "retrieval", "score": hit.score},
                )
                continue

            node_ids = tuple(meta.node_ids) if meta and meta.node_ids else tuple(hit.node_ids())
            requirement_ids = tuple(meta.requirement_ids) if meta and meta.requirement_ids else tuple(hit.requirement_ids())
            candidates.append(
                Candidate(
                    question_id=hit.question_id,
                    library=hit.library,
                    score=hit.score,
                    path=hit.path,
                    review_status=verdict.review_status,
                    answer_status=verdict.answer_status,
                    answer_visibility=verdict.answer_visibility,
                    node_ids=node_ids,
                    requirement_ids=requirement_ids,
                    notices=list(verdict.notices),
                )
            )
            evidence.append(
                Evidence(question_id=hit.question_id, source=hit.path, edge="vector_recall", verified=None)
            )
            for rid in requirement_ids:
                evidence.append(self._requirement_evidence(rid, question_id=hit.question_id))

        if use_graph:
            evidence.extend(self._graph_evidence(candidates, gate, blocked, queue, user_id, tier))

        notices = [COPYRIGHT_NOTICE, *self.cards.notices(), *index_errors]
        if tier == "published" and not candidates:
            return {
                **gate.fail_closed(),
                "query": query,
                "backend": self.cards.backend,
                "libraries": list(libraries),
                "candidates": [],
                "candidate_count": 0,
                "evidence": [],
                "blocked": blocked,
                "review_queued": len(blocked),
                "notices": notices,
            }

        for notice in self._candidate_notices(candidates, tier):
            if notice not in notices:
                notices.append(notice)

        return {
            "trust_tier": tier,
            "query": query,
            "backend": self.cards.backend,
            "libraries": list(libraries),
            "candidates": [c.as_dict() for c in candidates[:k]],
            "candidate_count": len(candidates),
            "evidence": [e.as_dict() for e in self._dedupe(evidence)],
            "blocked": blocked,
            "review_queued": len(blocked),
            "notices": notices,
        }

    # -------------------------------------------------------------- internals
    @staticmethod
    def _libraries(exam: Optional[str]) -> Tuple[str, ...]:
        library = library_for_exam(exam)
        return (library,) if library else ("ntce", "cet")

    @staticmethod
    def _filters(
        tier: TrustTier,
        *,
        modules: Optional[Sequence[str]],
        question_types: Optional[Sequence[str]],
        levels: Optional[Sequence[str]],
    ) -> Dict[str, set]:
        filters: Dict[str, set] = {
            "answer_status": set(RESEARCH_ANSWER_STATUSES),
            "review_status": set(RESEARCH_REVIEW_STATUSES if tier == "research_internal" else PUBLISHED_REVIEW_STATUSES),
        }
        if modules:
            filters["module"] = set(modules)
        if question_types:
            filters["question_type"] = set(question_types)
        if levels:
            filters["level"] = set(levels)
        return filters

    def _reconcile(
        self,
        hit: SearchHit,
        meta,
        blocked: List[dict],
        queue,
        user_id: str,
        tier: TrustTier,
    ) -> Tuple[Optional[str], Optional[str]]:
        """The question index is authoritative; a disagreeing card is a data defect, not a second truth."""
        card_review = hit.metadata.get("review_status") or None
        card_answer = hit.metadata.get("answer_status") or None
        if meta is None:
            blocked.append({"question_id": hit.question_id, "reason": "卡片命中但题目索引无此 question_id"})
            queue.add(
                reason="检索命中孤儿卡片：题目索引无此 question_id",
                user_id=user_id,
                question_id=hit.question_id,
                tier=tier,
                source=hit.path,
                detail={"path": "retrieval/orphan_card"},
            )
            return None, None
        if card_review and card_review != meta.review_status:
            notice = DUAL_TRUTH_NOTICE.format(
                question_id=hit.question_id, card_status=card_review, index_status=meta.review_status
            )
            blocked.append({"question_id": hit.question_id, "reason": notice})
            queue.add(
                reason=notice,
                user_id=user_id,
                question_id=hit.question_id,
                tier=tier,
                source=hit.path,
                detail={"path": "retrieval/state_mismatch"},
            )
        return meta.review_status, meta.answer_status

    def _graph_evidence(
        self,
        candidates: Iterable[Candidate],
        gate: TrustGate,
        blocked: List[dict],
        queue,
        user_id: str,
        tier: TrustTier,
    ) -> List[Evidence]:
        rows: List[Evidence] = []
        seen: set = set()
        for candidate in candidates:
            graph = get_graph_index(candidate.library)
            for node_id in candidate.node_ids:
                for requirement_id in graph.requirements_for(node_id):
                    key = (node_id, requirement_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        self._requirement_evidence(
                            requirement_id, question_id=candidate.question_id, node_id=node_id
                        )
                    )
            for requirement_id in graph.requirements_for_question(candidate.question_id):
                key = (candidate.question_id, requirement_id)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(self._requirement_evidence(requirement_id, question_id=candidate.question_id))
        return rows

    def _requirement_evidence(
        self,
        requirement_id: str,
        *,
        question_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> Evidence:
        requirement = self.repository.get_requirement(requirement_id)
        verdict = TrustGate("research_internal").classify_requirement(requirement)
        if requirement is None:
            return Evidence(
                question_id=question_id,
                node_id=node_id,
                requirement_id=requirement_id,
                edge="aligned_to_requirement",
                notices=("条款不在权威索引内，禁止引用。",),
            )
        return Evidence(
            question_id=question_id,
            node_id=node_id,
            requirement_id=requirement_id,
            standard_id=requirement.get("standard_id"),
            title=requirement.get("title") or requirement.get("name"),
            locator=requirement.get("locator"),
            verified=bool(requirement.get("source_verified")),
            edge="aligned_to_requirement",
            source="官方权威资料/requirements.jsonl",
            notices=list(verdict.notices) if verdict else [],
        )

    @staticmethod
    def _candidate_notices(candidates: Sequence[Candidate], tier: TrustTier) -> List[str]:
        out: List[str] = []
        if not candidates:
            out.append(
                "当前档位没有可用命中：published 需要教研签署（当前 0 条），"
                "research_internal 仍会排除隔离题与答案缺失题。"
            )
        heuristic = any(c.review_status in ("needs_fix", "auto_parsed", "llm_enhanced") for c in candidates)
        if heuristic and tier == "research_internal":
            out.append("命中内容多为 needs_fix/auto_parsed，仅供教研自测，不可对外声称已审核。")
        return out

    @staticmethod
    def _dedupe(rows: Sequence[Evidence]) -> List[Evidence]:
        seen: set = set()
        out: List[Evidence] = []
        for row in rows:
            key = (row.question_id, row.node_id, row.requirement_id, row.edge)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    return RetrievalService()
