"""CET 3-Stage strict timed exam state machine simulating authentic testing protocols."""
from __future__ import annotations

from services.common.models import ExamStageState


class CETExamStateMachine:
    """Simulates CET-4/6 official exam protocol:

    Phase 1: Writing (30m) -> Hard Lock
    Phase 2: Listening (30m) -> Collect Sheet 1 (Writing + Listening sealed)
    Phase 3: Reading + Translation (70m) -> Final Auto-submit
    """

    @staticmethod
    def get_initial_state() -> ExamStageState:
        """Start exam in Phase 1: Writing."""
        return ExamStageState(
            stage="writing",
            stage_time_limit_minutes=30,
            time_remaining_seconds=1800,
            input_locked=False,
            sheet_collected=False,
            can_switch_modules=False,
        )

    @staticmethod
    def step_stage(current_state: ExamStageState, elapsed_seconds: int = 0) -> ExamStageState:
        """Advance exam state machine to the next phase or update timer."""
        stage = current_state.stage

        if stage == "writing":
            rem = current_state.time_remaining_seconds - elapsed_seconds
            if rem <= 0:
                # 30 mins over: lock writing, transition to listening
                return ExamStageState(
                    stage="listening",
                    stage_time_limit_minutes=30,
                    time_remaining_seconds=1800,
                    input_locked=False,
                    sheet_collected=False,
                    can_switch_modules=False,
                )
            else:
                return ExamStageState(
                    stage="writing",
                    stage_time_limit_minutes=30,
                    time_remaining_seconds=rem,
                    input_locked=False,
                    sheet_collected=False,
                    can_switch_modules=False,
                )

        elif stage == "listening":
            rem = current_state.time_remaining_seconds - elapsed_seconds
            if rem <= 0:
                # Listening audio ends: Collect Sheet 1! Seal Writing and Listening
                return ExamStageState(
                    stage="reading_translation",
                    stage_time_limit_minutes=70,
                    time_remaining_seconds=4200,
                    input_locked=False,
                    sheet_collected=True,
                    can_switch_modules=False,
                )
            else:
                return ExamStageState(
                    stage="listening",
                    stage_time_limit_minutes=30,
                    time_remaining_seconds=rem,
                    input_locked=False,
                    sheet_collected=False,
                    can_switch_modules=False,
                )

        elif stage == "reading_translation":
            rem = current_state.time_remaining_seconds - elapsed_seconds
            if rem <= 0:
                # 70 mins over: Auto submit complete paper
                return ExamStageState(
                    stage="completed",
                    stage_time_limit_minutes=0,
                    time_remaining_seconds=0,
                    input_locked=True,
                    sheet_collected=True,
                    can_switch_modules=False,
                )
            else:
                return ExamStageState(
                    stage="reading_translation",
                    stage_time_limit_minutes=70,
                    time_remaining_seconds=rem,
                    input_locked=False,
                    sheet_collected=True,
                    can_switch_modules=False,
                )

        # completed
        return current_state
