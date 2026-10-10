"""Socratic progressive scaffolding built from the real question, not a template.

Each turn only ever quotes fields that exist in the library record (stem, options, node
titles, requirement titles). The reference answer stays hidden until the final turn, and
even then it is emitted only when TrustGate clears it and it is labelled as unsigned.
"""
from __future__ import annotations

from typing import List, Optional

from services.common.models import SocraticHintResponse
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import COPYRIGHT_NOTICE, TrustGate

NOT_IN_LIBRARY = "该 question_id 不在知识库索引内，系统不会凭空引导作答。"
REFUSAL = "该题参考答案缺失或处于隔离状态，系统不做揭晓引导，请改做同考点其他题目。"


class SocraticTutorEngine:
    """Provides progressive Socratic hints without an immediate spoiler."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        gate: Optional[TrustGate] = None,
    ) -> None:
        self.repository = repository or get_repository()
        self.gate = gate or TrustGate("research_internal")

    @classmethod
    def generate_hint(
        cls,
        question_id: str,
        hint_turn: int = 1,
        user_selected_option: Optional[str] = None,
        repository: Optional[KnowledgeRepository] = None,
        tier: str = "research_internal",
    ) -> SocraticHintResponse:
        engine = cls(repository, TrustGate(tier))
        return engine.hint(question_id, hint_turn, user_selected_option)

    # ------------------------------------------------------------------ main
    def hint(
        self, question_id: str, hint_turn: int, user_selected_option: Optional[str]
    ) -> SocraticHintResponse:
        record = self.repository.load_question(question_id)
        if record is None:
            return self._refuse(question_id, hint_turn, NOT_IN_LIBRARY, grounded=False)

        verdict = self.gate.classify_record(record)
        if not verdict.usable:
            return self._refuse(
                question_id,
                hint_turn,
                "该内容已被隔离或未达当前展示档位，系统不渲染引导。",
                grounded=True,
            )

        content = record.get("content") or {}
        stem = (content.get("stem") or record.get("text") or "").strip()
        options = [o.get("key") for o in content.get("options") or [] if isinstance(o, dict)]
        scaffold = self._scaffold_hint(record)

        turn = max(1, int(hint_turn or 1))
        notices: List[str] = [COPYRIGHT_NOTICE, *verdict.notices]

        if turn == 1:
            guiding = (
                f"先只看题干：「{self._clip(stem)}」。请回答——限定作答范围的那半句是哪一处？"
                "把主语、条件和设问词分别划出来再往下读选项。"
            )
            return SocraticHintResponse(
                question_id=question_id,
                hint_turn=1,
                guiding_question=guiding,
                scaffold_prompt=scaffold,
                is_final_reveal=False,
                grounded_in_library=True,
                notices=notices,
            )

        if turn == 2:
            letter_list = "、".join([k for k in options if k]) or "（本题无选项列表，请简述作答要点）"
            challenge = ""
            if user_selected_option:
                challenge = (
                    f"你已倾向 {user_selected_option}，先别确认：请用题干那处限定条件反过来检验它，"
                    "看是否有一项只满足表面表述、不满足限定条件。"
                )
            return SocraticHintResponse(
                question_id=question_id,
                hint_turn=2,
                guiding_question=(
                    f"现在只比较选项 {letter_list}。请找出两个与题干限定条件直接冲突的干扰项并说明冲突点。"
                    + (" " + challenge if challenge else "")
                ),
                scaffold_prompt=scaffold,
                is_final_reveal=False,
                grounded_in_library=True,
                notices=notices,
            )

        # Final turn: reveal only what the gate cleared.
        if not verdict.may_assert_answer:
            return self._refuse(question_id, turn, REFUSAL, grounded=True, notices=notices)

        explanation = self._explanation(record)
        reveal = (
            f"参考答案为 {content.get('answer')}"
            f"（answer_status={verdict.answer_status}，review_status={verdict.review_status}，"
            "未经教研签署，以复核结论为准）。"
        )
        return SocraticHintResponse(
            question_id=question_id,
            hint_turn=turn,
            guiding_question=reveal,
            scaffold_prompt=explanation or scaffold,
            is_final_reveal=True,
            revealed_answer=content.get("answer"),
            grounded_in_library=True,
            notices=notices,
        )

    # -------------------------------------------------------------- helpers
    def _scaffold_hint(self, record: dict) -> str:
        """Name the assessed node / cited clause so the hint points at real scope."""
        for rid in record.get("exam_requirement_ids") or []:
            requirement = self.repository.get_requirement(rid)
            if requirement and requirement.get("title"):
                return f"设问指向：{requirement['title']}（条款 {rid}，mapping_status={requirement.get('mapping_status')}）。"
        nodes = record.get("knowledge_node_ids") or []
        if nodes:
            return f"设问指向考点 {nodes[0]}；该考点的知识点名称需在图谱索引中就位后才可展示。"
        return "本题未标注考点，请先按题干的限定条件归类后再作答。"

    @staticmethod
    def _explanation(record: dict) -> str:
        extra = record.get("extra") or {}
        lar = extra.get("llm_analysis_result") or {}
        inner = (lar.get("result") or {}).get("analysis") if isinstance(lar, dict) else None
        if isinstance(inner, dict):
            return str(inner.get("explanation") or inner.get("raw") or "").strip()
        content = record.get("content") or {}
        for candidate in (content.get("analysis"), record.get("analysis")):
            if isinstance(candidate, dict):
                return str(candidate.get("raw") or candidate.get("explanation") or "").strip()
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""

    @staticmethod
    def _clip(text: str, limit: int = 120) -> str:
        flat = " ".join(text.split())
        return flat if len(flat) <= limit else flat[:limit] + "……"

    def _refuse(
        self,
        question_id: str,
        hint_turn: int,
        reason: str,
        grounded: bool,
        notices: Optional[List[str]] = None,
    ) -> SocraticHintResponse:
        return SocraticHintResponse(
            question_id=question_id,
            hint_turn=max(1, int(hint_turn or 1)),
            guiding_question=reason,
            scaffold_prompt="",
            is_final_reveal=False,
            revealed_answer=None,
            grounded_in_library=grounded,
            notices=list(notices or [COPYRIGHT_NOTICE]),
        )
