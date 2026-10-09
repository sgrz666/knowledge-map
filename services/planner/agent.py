"""CurriculumPlannerAgent generating personalized adaptive study paths."""
from __future__ import annotations

from services.common.models import (
    CurriculumPlanResponse,
    PlanRequest,
)
from services.planner.scheduler import AdaptiveScheduler


class CurriculumPlannerAgent:
    """Agent orchestrating adaptive curriculum scheduling based on mastery and exam countdown."""

    def __init__(self):
        self.scheduler = AdaptiveScheduler()

    def generate_plan(self, request: PlanRequest) -> CurriculumPlanResponse:
        """Create a multi-day study schedule tailored to available time and mastery gaps."""
        days = request.days_until_exam
        daily_mins = request.daily_available_minutes
        mastery_list = request.current_mastery or []

        daily_plans = self.scheduler.schedule_curriculum(
            days=days,
            daily_minutes=daily_mins,
            mastery_records=mastery_list,
        )

        milestones = [
            f"第 1 天: 开启核心高频知识点首轮突破",
            f"第 {min(7, days)} 天: 第一阶段全真模考检验与雷达图校准",
        ]
        if days >= 14:
            milestones.append(f"第 {min(14, days)} 天: 第二阶段薄弱模块专项攻坚")
        if days >= 21:
            milestones.append(f"第 {min(21, days)} 天: 第三阶段限时提速与主观题量规演练")
        milestones.append(f"考前 3 天: 高频错题全面清零与全真考务时序演练")

        return CurriculumPlanResponse(
            user_id=request.user_id,
            exam_type=request.exam_type,
            total_days=days,
            daily_plans=daily_plans,
            milestones=milestones,
        )
