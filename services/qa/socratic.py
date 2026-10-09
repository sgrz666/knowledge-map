"""Socratic progressive multi-turn scaffolding engine."""
from __future__ import annotations

from typing import Optional

from services.common.models import SocraticHintResponse


class SocraticTutorEngine:
    """Provides progressive Socratic hints without immediate spoiler."""

    @classmethod
    def generate_hint(
        cls,
        question_id: str,
        hint_turn: int = 1,
        user_selected_option: Optional[str] = None,
    ) -> SocraticHintResponse:
        """Deliver stage-appropriate scaffold question."""
        if hint_turn <= 1:
            return SocraticHintResponse(
                question_id=question_id,
                hint_turn=1,
                guiding_question="请重新观察题干中的主语行为以及限定条件，教师这一举措的核心出发点是关注学生的分数，还是关注学生的全面发展过程？",
                scaffold_prompt="思考方向：新课程理念倡导的评价方式是单一量化，还是多元过程性评价？",
                is_final_reveal=False,
                revealed_answer=None,
            )
        elif hint_turn == 2:
            return SocraticHintResponse(
                question_id=question_id,
                hint_turn=2,
                guiding_question="我们现在可以先排除明显违背常理的 A 和 C 选项。请在 B 和 D 中进一步辨析：这项举措的真正价值究竟是‘减轻教师负担’还是‘促进学生发展’？",
                scaffold_prompt="思考方向：以学生为主体的教育观中，评价的最终落脚点永远应当是促进谁的发展？",
                is_final_reveal=False,
                revealed_answer=None,
            )
        else:
            # Turn 3+: Final reveal
            return SocraticHintResponse(
                question_id=question_id,
                hint_turn=hint_turn,
                guiding_question="正确答案是 B。李老师的做法恰恰体现了以人为本的学生观，强调对学生成长过程的动态关照与多元激励。",
                scaffold_prompt="考点总结：以人为本的学生观要求树立全面发展的学生观与多元发展性评价观。",
                is_final_reveal=True,
                revealed_answer="B",
            )
