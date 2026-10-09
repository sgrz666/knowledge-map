"""Lesson plan drafting rubric evaluator for NTCE 20-minute preparation."""
from __future__ import annotations

from typing import List

from services.common.models import (
    LessonPlanReviewRequest,
    LessonPlanReviewResponse,
)


class LessonPlanEvaluator:
    """Evaluates 20-minute timed instructional design drafts according to NTCE rubrics."""

    @classmethod
    def evaluate(cls, req: LessonPlanReviewRequest) -> LessonPlanReviewResponse:
        """Score lesson plan text across 4 core dimensions (total 40 pts)."""
        text = req.plan_text

        # 1. 教学目标 (10 pts)
        has_3d_obj = any(k in text for k in ["教学目标", "三维目标", "核心素养", "知识与技能", "过程与方法", "情感态度"])
        obj_score = 9.0 if has_3d_obj else 4.0

        # 2. 教学重难点 (8 pts)
        has_key_diff = ("重点" in text) and ("难点" in text)
        diff_score = 7.5 if has_key_diff else 3.0

        # 3. 教学过程 (16 pts)
        process_keywords = ["导入", "新课", "探究", "练习", "总结", "作业"]
        hit_proc = sum(1 for kw in process_keywords if kw in text)
        proc_ratio = hit_proc / len(process_keywords)
        proc_score = round(16.0 * proc_ratio, 1)

        # 4. 板书设计与反思 (6 pts)
        has_board = any(k in text for k in ["板书", "板书设计", "提纲式板书"])
        board_score = 5.5 if has_board else 2.0

        total = round(obj_score + diff_score + proc_score + board_score, 1)

        dims = [
            {"dimension_name": "教学目标设置", "score": obj_score, "max_score": 10.0, "status": "达标" if has_3d_obj else "待完善"},
            {"dimension_name": "教学重难点确立", "score": diff_score, "max_score": 8.0, "status": "达标" if has_key_diff else "缺少区分"},
            {"dimension_name": "教学过程活动设计", "score": proc_score, "max_score": 16.0, "status": "结构完整" if proc_ratio >= 0.8 else "环节缺漏"},
            {"dimension_name": "板书设计与书写规范", "score": board_score, "max_score": 6.0, "status": "达标" if has_board else "未撰写板书"},
        ]

        missed = []
        if not has_3d_obj:
            missed.append("教学三维目标/核心素养分条表述")
        if not has_key_diff:
            missed.append("明确标示教学重点与难点")
        if proc_ratio < 0.8:
            missed.append("教学完整五环节活动与师生互动设问")
        if not has_board:
            missed.append("直观规范的板书设计示意图")

        suggestions = (
            "教学简案建议严格按照‘一课时’标准规范书写："
            "1. 教学目标必须体现行为动词（能够说出、体会、掌握）；"
            "2. 教学过程中新授环节应突出‘学生活动’与‘教师引导’的具体对话；"
            "3. 务必保留页面右侧或底部独立预留直观醒目的板书设计。"
        )

        return LessonPlanReviewResponse(
            total_score=total,
            dimensions=dims,
            missed_elements=missed,
            improvement_suggestions=suggestions,
        )
