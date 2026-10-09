"""Topological DAG and Priority-based scheduling algorithms."""
from __future__ import annotations

from typing import Dict, List, Optional
from datetime import date, timedelta

from services.common.models import (
    DailyPlan,
    DailyTaskItem,
    UserMasteryRecord,
)

# Standard default NTCE syllabus nodes with module mapping and weights
DEFAULT_SYLLABUS_NODES = [
    {"node_id": "ntce.m1.student_view", "module": "m1", "title": "以人为本的学生观", "weight": 0.85, "freq": 0.90, "prereq": []},
    {"node_id": "ntce.m1.teacher_view", "module": "m1", "title": "新课程背景下的教师观", "weight": 0.85, "freq": 0.92, "prereq": ["ntce.m1.student_view"]},
    {"node_id": "ntce.m1.education_view", "module": "m1", "title": "素质教育与全面发展观", "weight": 0.80, "freq": 0.88, "prereq": []},
    {"node_id": "ntce.m2.education_law", "module": "m2", "title": "教育法与义务教育法核心法条", "weight": 0.75, "freq": 0.85, "prereq": []},
    {"node_id": "ntce.m2.minors_protection", "module": "m2", "title": "未成年人保护法与预防犯罪法", "weight": 0.70, "freq": 0.80, "prereq": ["ntce.m2.education_law"]},
    {"node_id": "ntce.m2.student_rights", "module": "m2", "title": "学生的受教育权与人身安全保护", "weight": 0.78, "freq": 0.84, "prereq": ["ntce.m2.education_law"]},
    {"node_id": "ntce.m3.ethics_code", "module": "m3", "title": "中小学教师职业道德规范（三爱两人一终身）", "weight": 0.90, "freq": 0.95, "prereq": []},
    {"node_id": "ntce.m3.teacher_behavior", "module": "m3", "title": "教师职业行为准则与师德违规处理", "weight": 0.75, "freq": 0.78, "prereq": ["ntce.m3.ethics_code"]},
    {"node_id": "ntce.m4.culture_history", "module": "m4", "title": "中国古代历史与传统文化常识", "weight": 0.60, "freq": 0.70, "prereq": []},
    {"node_id": "ntce.m4.science_literacy", "module": "m4", "title": "中外科技常识与重大科学成就", "weight": 0.60, "freq": 0.65, "prereq": []},
    {"node_id": "ntce.m5.logical_reasoning", "module": "m5", "title": "逻辑思维能力（概念/推理/论证）", "weight": 0.70, "freq": 0.75, "prereq": []},
    {"node_id": "ntce.m5.reading_comprehension", "module": "m5", "title": "现代文阅读理解主观题解法", "weight": 0.85, "freq": 0.90, "prereq": []},
    {"node_id": "ntce.m5.essay_writing", "module": "m5", "title": "材料作文立意与论说文结构", "weight": 0.95, "freq": 1.00, "prereq": ["ntce.m1.teacher_view", "ntce.m3.ethics_code"]},
]

MODULE_NAME_MAP = {
    "m1": "职业理念",
    "m2": "教育法律法规",
    "m3": "教师职业道德",
    "m4": "文化素养",
    "m5": "基本能力",
}


class AdaptiveScheduler:
    """Computes priority scores and schedules learning calendar satisfying DAG constraints."""

    @staticmethod
    def calculate_priority(
        mastery_rate: float,
        frequency: float,
        syllabus_weight: float,
        w1: float = 0.50,
        w2: float = 0.30,
        w3: float = 0.20,
    ) -> float:
        """Calculate node priority: Priority(k) = w1 * (1 - M_k) + w2 * Freq(k) + w3 * Weight(k)."""
        loss_rate = 1.0 - max(0.0, min(1.0, mastery_rate))
        return round(w1 * loss_rate + w2 * frequency + w3 * syllabus_weight, 4)

    @classmethod
    def schedule_curriculum(
        cls,
        days: int,
        daily_minutes: int,
        mastery_records: Optional[List[UserMasteryRecord]] = None,
        start_date: Optional[date] = None,
    ) -> List[DailyPlan]:
        """Generate day-by-day plan adhering to topological dependencies and priority."""
        if start_date is None:
            start_date = date.today()

        # Build mastery map
        mastery_map: Dict[str, float] = {}
        if mastery_records:
            for rec in mastery_records:
                mastery_map[rec.node_id] = rec.mastery_score

        # 1. Compute priority score for each candidate node
        node_pool = []
        for n in DEFAULT_SYLLABUS_NODES:
            nid = n["node_id"]
            m_score = mastery_map.get(nid, 0.40)  # default new node mastery = 0.40
            prio = cls.calculate_priority(
                mastery_rate=m_score,
                frequency=n["freq"],
                syllabus_weight=n["weight"],
            )
            node_pool.append({**n, "mastery": m_score, "priority": prio})

        # 2. Sort pool by priority descending
        node_pool.sort(key=lambda x: x["priority"], reverse=True)

        daily_plans: List[DailyPlan] = []
        node_idx = 0
        total_nodes = len(node_pool)

        for d in range(1, days + 1):
            curr_date = start_date + timedelta(days=d - 1)
            date_str = curr_date.isoformat()

            # Every 7th day or the last day is a milestone mock sprint
            is_mock_day = (d % 7 == 0) or (d == days)

            day_tasks: List[DailyTaskItem] = []
            focus_module = "综合模考" if is_mock_day else "专项突破"

            if is_mock_day:
                day_tasks.append(
                    DailyTaskItem(
                        task_type="mock_sprint",
                        node_id=None,
                        title=f"第 {d} 天阶段全真模拟冲刺（限时全真模考）",
                        estimated_minutes=min(daily_minutes, 90),
                        target_question_count=35,
                    )
                )
                day_tasks.append(
                    DailyTaskItem(
                        task_type="weakness_drill",
                        node_id=None,
                        title="模考错题回炉与薄弱考点深度归因",
                        estimated_minutes=max(15, daily_minutes - min(daily_minutes, 90)),
                        target_question_count=10,
                    )
                )
            else:
                # Regular study day: FSRS Review (20 mins) + 1-2 New/Weak Nodes
                review_mins = min(20, int(daily_minutes * 0.3))
                learn_mins = daily_minutes - review_mins

                day_tasks.append(
                    DailyTaskItem(
                        task_type="fsrs_review",
                        node_id=None,
                        title="FSRS 到期错题智能回炉复习包",
                        estimated_minutes=review_mins,
                        target_question_count=8,
                    )
                )

                # Pick next node in priority pool
                node = node_pool[node_idx % total_nodes]
                node_idx += 1
                focus_module = MODULE_NAME_MAP.get(node["module"], node["module"])

                day_tasks.append(
                    DailyTaskItem(
                        task_type="new_node_learning",
                        node_id=node["node_id"],
                        title=f"考点攻克: {node['title']}",
                        estimated_minutes=learn_mins,
                        target_question_count=12,
                    )
                )

            plan = DailyPlan(
                day_index=d,
                date_str=date_str,
                focus_module=focus_module,
                tasks=day_tasks,
                total_minutes=daily_minutes,
            )
            daily_plans.append(plan)

        return daily_plans
