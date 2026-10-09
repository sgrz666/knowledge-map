"""TutorQAAgent providing evidence-grounded 3-chain explanations and Socratic dialogs."""
from __future__ import annotations

from typing import Union

from services.common.models import (
    QARequest,
    SocraticHintResponse,
    SparksThreeChainResponse,
)
from services.qa.socratic import SocraticTutorEngine
from services.qa.sparks_chain import SparksChainEngine


class TutorQAAgent:
    """Agent answering student questions with evidence provenance and Socratic guidance."""

    def __init__(self):
        pass

    def answer_query(
        self, req: QARequest
    ) -> Union[SparksThreeChainResponse, SocraticHintResponse]:
        """Dispatch query according to requested mode."""
        if req.mode == "socratic_hint":
            return SocraticTutorEngine.generate_hint(
                question_id=req.question_id,
                hint_turn=req.hint_turn,
                user_selected_option=req.user_selected_option,
            )
        else:
            return SparksChainEngine.generate(
                question_id=req.question_id,
                user_selected_option=req.user_selected_option,
            )
