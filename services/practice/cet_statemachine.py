"""模考时序由库内考务规格推进——服务不再另立一份卷面。

旧版把 "写作 30 / 听力 30 / 阅读+翻译 70" 写死在这个文件里，而
``数据集/四六级/manifest/paper_specs.jsonl`` 的 ``parts[]`` 给的是 30 / 25 / 40 / 30。同一条组卷响应
因此带着两套时间表：``structure`` 用库内的分钟数，``stage_state`` 用这里的常数——学习者会按一份教研
从未核定过的时序被收卡（听力晚 5 分钟）。按验收 A1 的口径，卷面规格与题面、条文一样是库内实体，
不许复制进服务代码。逐节读法本身也只在 ``repository.timed_stages`` 里写一遍。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from services.common.models import ExamStageState
from services.knowledge.repository import timed_stages

#: 运行时自己的终局标记，不是卷面上的小节名。
COMPLETED_STAGE = "completed"


class CETExamStateMachine:
    """Advances a mock exam through the timed sections its own blueprint declares."""

    @staticmethod
    def get_initial_state(spec: Optional[dict]) -> Optional[ExamStageState]:
        """Start at the blueprint's first timed section; ``None`` when the library has no timing."""
        stages = timed_stages(spec)
        return CETExamStateMachine._state(stages[0]) if stages else None

    @staticmethod
    def step_stage(
        current_state: ExamStageState, elapsed_seconds: int = 0, spec: Optional[dict] = None
    ) -> Optional[ExamStageState]:
        """Burn the clock, then move to the next section the blueprint lists."""
        stages = timed_stages(spec)
        if not stages:
            return None
        index = next(
            (i for i, stage in enumerate(stages) if stage["name"] == current_state.stage), None
        )
        if index is None:
            if current_state.stage == COMPLETED_STAGE:
                return current_state
            # 状态里的小节不在这份规格里（换了套卷，或教研改了卷面）：宁可不推进，
            # 也不按猜出来的顺序收答题卡。
            return None
        remaining = int(current_state.time_remaining_seconds) - int(elapsed_seconds)
        if remaining > 0:
            return current_state.model_copy(update={"time_remaining_seconds": remaining})
        if index + 1 >= len(stages):
            return ExamStageState(
                stage=COMPLETED_STAGE,
                module=None,
                stage_time_limit_minutes=0,
                time_remaining_seconds=0,
                input_locked=True,
                sheet_collected=True,
                can_switch_modules=False,
                sheet_submission=None,
            )
        finished, nxt = stages[index], stages[index + 1]
        # 只认库内 lock_policy：上一节声明了答题卡就记成已上交。input_locked 留给终局态——
        # 卷面上的 allow_backtrack/locked_forward 说的是"这一节封住，不能再回去作答"，
        # 由 can_switch_modules 表达；把它当成整卷封锁，学习者会在听力刚开始时被锁死输入。
        return CETExamStateMachine._state(nxt, sheet_collected=bool(finished["sheet_submission"]))

    @staticmethod
    def _state(
        stage: Dict[str, object],
        *,
        sheet_collected: bool = False,
        input_locked: bool = False,
    ) -> ExamStageState:
        minutes = int(stage["minutes"])  # type: ignore[arg-type]
        return ExamStageState(
            stage=str(stage["name"]),
            module=stage["module"],  # type: ignore[arg-type]
            stage_time_limit_minutes=minutes,
            time_remaining_seconds=minutes * 60,
            input_locked=input_locked,
            sheet_collected=sheet_collected,
            can_switch_modules=bool(stage["allow_backtrack"]),
            sheet_submission=stage["sheet_submission"],  # type: ignore[arg-type]
        )
