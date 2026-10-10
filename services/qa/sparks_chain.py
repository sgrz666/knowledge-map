"""Sparks 3-Chain explanation engine, grounded in the knowledge library.

Chain 1 reads the record's own clue analysis, Chain 2 the recorded option comparison and
the real options, Chain 3 the requirement clauses indexed in ``requirements.jsonl``.
Every chain carries the provenance status of what it quotes: most analyses in the library
are still ``draft(llm-v2)`` and unreviewed, so the engine labels them instead of
presenting them as authority, and it never asserts an answer the gate has not cleared.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from services.common.models import SparksThreeChainResponse
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import (
    COPYRIGHT_NOTICE,
    LETTER_ANSWER_STATUSES,
    TrustGate,
    TrustVerdict,
    answer_letter,
)

NO_RECORD = SparksThreeChainResponse(
    question_id="",
    key_clue_localization="该 question_id 不在知识库索引内，系统不生成任何解析。",
    option_discrimination={},
    knowledge_provenance={"requirements": [], "node_ids": []},
    explanation_summary="无法定位题目原文，已拒绝作答。请先通过检索接口取得真实 question_id。",
    answer_visibility="none",
    grounded_in_library=False,
    notices=("question_id 未命中知识库索引。", COPYRIGHT_NOTICE),
)

UNREVIEWED_ANALYSIS_NOTICE = (
    "以下解析引自库内自动生成的草稿（analysis_status=%s），尚未通过教研复核，"
    "仅可作研究参考，不可作为承诺性讲解。"
)
ANSWER_UNAVAILABLE = (
    "该题参考答案缺失或来源冲突，系统不断言正确选项，请改做同考点其他题目。"
)


class SparksChainEngine:
    """Generates the 3-chain explanation from stored evidence only."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        gate: Optional[TrustGate] = None,
    ) -> None:
        self.repository = repository or get_repository()
        self.gate = gate or TrustGate("research_internal")

    @classmethod
    def generate(
        cls,
        question_id: str,
        user_selected_option: Optional[str] = None,
        node_id: Optional[str] = None,
        repository: Optional[KnowledgeRepository] = None,
        tier: str = "research_internal",
    ) -> SparksThreeChainResponse:
        engine = cls(repository, TrustGate(tier))
        return engine.explain(question_id, user_selected_option, node_id)

    # ------------------------------------------------------------------ main
    def explain(
        self,
        question_id: str,
        user_selected_option: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> SparksThreeChainResponse:
        record = self.repository.load_question(question_id)
        if record is None:
            return NO_RECORD.model_copy(update={"question_id": question_id})

        verdict = self.gate.classify_record(record)
        if not verdict.usable:
            return self._blocked(record, verdict)

        content = record.get("content") or {}
        structured, analysis_status = self._draft_analysis(record)
        notices: List[str] = [COPYRIGHT_NOTICE]
        if analysis_status and analysis_status != "verified":
            notices.append(UNREVIEWED_ANALYSIS_NOTICE % analysis_status)
        notices.extend(verdict.notices)

        clue = (
            structured.get("key_info")
            or self._first_sentence(self._plain_analysis(record))
            or "本题未存有题目专属解析草稿，请依据题干限定条件自行圈画题眼（系统不代拟结论）。"
        )

        discrimination = self._discrimination(record, content, structured, verdict, user_selected_option)
        provenance, prov_notices = self._provenance(record, structured, node_id)
        notices.extend(prov_notices)

        summary = self._summary(structured, content, verdict)
        return SparksThreeChainResponse(
            question_id=question_id,
            key_clue_localization=clue,
            option_discrimination=discrimination,
            knowledge_provenance=provenance,
            explanation_summary=summary,
            answer_visibility=verdict.answer_visibility,
            grounded_in_library=True,
            notices=notices,
        )

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _plain_analysis(record: dict) -> str:
        content = record.get("content") or {}
        for candidate in (content.get("analysis"), record.get("analysis")):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        structured = SparksChainEngine._draft_analysis(record)[0]
        return str(structured.get("raw") or structured.get("explanation") or "").strip()

    @staticmethod
    def _draft_analysis(record: dict) -> Tuple[dict, Optional[str]]:
        """Return ``(fields, provenance_status)`` from whatever analysis the record carries."""
        extra = record.get("extra") or {}
        lar = extra.get("llm_analysis_result") or {}
        inner = (lar.get("result") or {}).get("analysis") if isinstance(lar, dict) else None
        if isinstance(inner, dict) and any(inner.values()):
            return inner, extra.get("analysis_status") or "draft(llm)"

        content = record.get("content") or {}
        for candidate in (content.get("analysis"), record.get("analysis")):
            if isinstance(candidate, dict) and any(v for v in candidate.values()):
                return candidate, candidate.get("status") or "source_extracted"
            if isinstance(candidate, str) and candidate.strip():
                status = extra.get("analysis_status") or "draft(unstructured)"
                return {"explanation": candidate.strip()}, status
        return {}, None

    @staticmethod
    def _first_sentence(text: str) -> str:
        for sep in ("。", "；", ";", "\n"):
            if sep in text:
                return text.split(sep)[0].strip() + ("。" if sep == "。" else "")
        return text.strip()

    def _discrimination(
        self,
        record: dict,
        content: dict,
        structured: dict,
        verdict: TrustVerdict,
        user_selected_option: Optional[str],
    ) -> dict:
        options = content.get("options") or []
        normalised = []
        for opt in options:
            if isinstance(opt, dict):
                normalised.append({"key": opt.get("key"), "text": opt.get("text")})
            else:
                normalised.append({"key": None, "text": str(opt)})

        payload = {
            "options": normalised,
            "comparison": structured.get("option_compare") or "",
            "answer_status": verdict.answer_status,
        }
        if verdict.may_assert_answer:
            payload["reference_answer"] = content.get("answer")
        else:
            payload["reference_answer"] = None
            payload["note"] = ANSWER_UNAVAILABLE

        if user_selected_option:
            payload["candidate_choice"] = user_selected_option
            key = (
                answer_letter(content.get("answer"))
                if verdict.answer_status in LETTER_ANSWER_STATUSES
                else None
            )
            picked = answer_letter(user_selected_option)
            if verdict.may_assert_answer and key and picked:
                same = key == picked
                payload["matches_reference"] = same
                payload["diagnosis"] = (
                    "所选与库内答案键一致。"
                    if same
                    else "所选与库内答案键不一致；差异判据见 comparison，最终以教研复核为准。"
                )
            elif verdict.may_assert_answer:
                # 参考答案是原文而不是字母键时，选项比对没有意义，硬比只会造出一个假结论。
                payload["matches_reference"] = None
                payload["diagnosis"] = (
                    "库内该题的参考答案不是选项键（answer_status=%s），无法与所选字母比对；"
                    "只能按参考原文自评。" % verdict.answer_status
                )
            else:
                payload["diagnosis"] = ANSWER_UNAVAILABLE
        return payload

    def _provenance(
        self, record: dict, structured: dict, node_id: Optional[str]
    ) -> Tuple[dict, List[str]]:
        notices: List[str] = []
        requirement_ids = list(record.get("exam_requirement_ids") or [])
        if node_id:
            requirement_ids.append(node_id)

        clauses = []
        for rid in record.get("exam_requirement_ids") or []:
            requirement = self.repository.get_requirement(rid)
            gate_verdict = self.gate.classify_requirement(requirement)
            if not gate_verdict.citable:
                notices.extend(gate_verdict.notices)
                continue
            clauses.append(
                {
                    "requirement_id": rid,
                    "standard_id": requirement.get("standard_id"),
                    "title": requirement.get("title"),
                    "content": requirement.get("content"),
                    "locator": requirement.get("locator"),
                    "mapping_status": requirement.get("mapping_status"),
                }
            )
            notices.extend(gate_verdict.notices)

        if not clauses:
            notices.append("该题在库内没有可引用的权威条款，解析仅基于题目自身文本。")

        source = record.get("source") or {}
        provenance = {
            "requirements": clauses,
            "node_ids": list(record.get("knowledge_node_ids") or []),
            "requested_node": node_id,
            "trace_back": structured.get("trace_back") or "",
            "analysis_source": structured.get("source"),
            "analysis_method": structured.get("method"),
            "source_files": source.get("files") or [],
            "source_verified": source.get("verified"),
            "review_status": (record.get("review") or {}).get("status"),
        }
        return provenance, notices

    @staticmethod
    def _summary(structured: dict, content: dict, verdict: TrustVerdict) -> str:
        explanation = str(structured.get("explanation") or structured.get("raw") or "").strip()
        if verdict.may_assert_answer:
            return (
                f"参考答案：{content.get('answer')}（answer_status={verdict.answer_status}，"
                f"review_status={verdict.review_status}，未经教研签署）。{explanation}".strip()
            )
        return f"{ANSWER_UNAVAILABLE} {explanation}".strip()

    def _blocked(self, record: dict, verdict: TrustVerdict) -> SparksThreeChainResponse:
        """Quarantined or out-of-tier content: no answer, no explanation, just the reason."""
        reasons = list(verdict.notices) or ["该内容未通过 TrustGate 当前档位校验。"]
        reasons.append(COPYRIGHT_NOTICE)
        return SparksThreeChainResponse(
            question_id=record.get("question_id", ""),
            key_clue_localization="该内容已被隔离或未达展示档位，系统不渲染解析正文。",
            option_discrimination={},
            knowledge_provenance={
                "requirements": [],
                "node_ids": [],
                "review_status": verdict.review_status,
                "answer_status": verdict.answer_status,
            },
            explanation_summary="已转入待复核队列（审查/待复核清单.md），由教研复核后再开放。",
            answer_visibility="none",
            grounded_in_library=True,
            notices=reasons,
        )
