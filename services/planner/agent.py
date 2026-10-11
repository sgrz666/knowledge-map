"""CurriculumPlannerAgent — adaptive path built only from library facts and persisted state."""
from __future__ import annotations

from typing import List, Optional

from services.common.models import (
    CurriculumPlanResponse,
    PlanRequest,
    UserMasteryRecord,
)
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.memory.store import default_store
from services.planner.scheduler import AdaptiveScheduler


class CurriculumPlannerAgent:
    """Agent orchestrating adaptive curriculum scheduling based on mastery and exam countdown."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        store=None,
    ) -> None:
        self.repository = repository or get_repository()
        self.store = store if store is not None else default_store()
        self.scheduler = AdaptiveScheduler(repository=self.repository, store=self.store)

    def generate_plan(self, request: PlanRequest) -> CurriculumPlanResponse:
        """Create a multi-day study schedule tailored to available time and mastery gaps."""
        daily_plans, notices, prereq_note = self.scheduler.schedule(
            user_id=request.user_id,
            exam=request.exam_type,
            days=request.days_until_exam,
            daily_minutes=request.daily_available_minutes,
            mastery_records=request.current_mastery,
            tier=request.trust_tier.value,
            school_level=request.school_level,
            subject=request.subject,
        )
        return CurriculumPlanResponse(
            user_id=request.user_id,
            exam_type=request.exam_type,
            total_days=len(daily_plans),
            daily_plans=daily_plans,
            milestones=self._milestones(daily_plans, request.current_mastery),
            prerequisite_note=prereq_note,
            trust_tier=request.trust_tier,
            notices=notices,
        )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _milestones(daily_plans: List[object], mastery_records: Optional[List[UserMasteryRecord]]) -> List[str]:
        """Milestone text is read back out of the generated calendar, never pre-written."""
        if not daily_plans:
            return ["当前档位内可用考点为空，未生成日历；请先由教研复核题库挂载关系后重试。"]

        out: List[str] = []
        first = daily_plans[0]
        node_ids = list(
            dict.fromkeys(
                task.node_id
                for task in getattr(first, "tasks", [])
                if getattr(task, "node_id", None)
            )
        )
        if node_ids:
            out.append(
                f"第 1 天：按题池与学习记录安排（{len(node_ids)} 个考点，"
                f"共 {sum(t.target_question_count for t in first.tasks)} 题）"
            )
        mock_days = [
            plan.day_index
            for plan in daily_plans
            if any(t.task_type == "mock_sprint" for t in plan.tasks)
        ]
        if mock_days:
            out.append(
                f"模考节点：第 {'、'.join(str(d) for d in mock_days)} 天安排限时模考，"
                "实际题量以组卷时题池与可信门禁为准"
            )
        drills = [
            plan.day_index
            for plan in daily_plans
            if any(t.task_type == "weakness_drill" for t in plan.tasks)
        ]
        if drills:
            out.append(
                f"薄弱攻坚：第 {drills[0]} 天起对低于薄弱线的考点做专项练习"
                f"（当前传入 {len(mastery_records or [])} 条掌握度）"
            )
        elif mastery_records is None or not mastery_records:
            out.append("完成诊断与作答后，可更新日历，按真实掌握度重排薄弱项")

        last = daily_plans[-1]
        new_nodes = {t.node_id for t in last.tasks if t.task_type == 'new_node_learning' and t.node_id}
        out.append(f"第 {last.day_index} 天（考前）：已安排 {last.total_minutes} 分钟，"
                   f"包含 {len(new_nodes)} 个考点学习任务；具体内容以下方日程为准")
        return out
