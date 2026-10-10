"""Lesson-plan review against the library's 教学设计 rubric, feedback-first.

The previous version kept its own four dimensions and weights (10/8/16/6 = 40) inside the
service — a second, contradictory copy of ``数据集/教资/rubrics/lesson_plan.json`` (which splits
the same 40 分 as 10/6/16/4/4) and it emitted a score even though that rubric is unsigned. Now the
element list and the descriptor wording come from the rubric record, and a total only appears if
``TrustGate`` says the rubric has been signed by the 教研 reviewer.
"""
from __future__ import annotations

from typing import List, Optional

from services.common.models import (
    LessonPlanReviewRequest,
    LessonPlanReviewResponse,
    TrustTier,
)
from services.grader.evidence import overlap, pick_level
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate

NO_RUBRIC_NOTICE = (
    "库内没有该题型的教学设计量规，系统只按题目文本列出可自查要素，不内置维度与权重。"
)
FEEDBACK_ONLY_NOTICE = (
    "量规未签署，本结果只出反馈不出分；总分需教研核定维度权重与措辞后才会出具。"
)
ELEMENT_CUE = ("教学目标", "重点", "难点", "导入", "新授", "巩固", "小结", "作业", "板书", "理念", "设计意图")


class LessonPlanEvaluator:
    """Checks a draft against the library rubric's own dimensions and descriptors."""

    def __init__(self, repository: Optional[KnowledgeRepository] = None) -> None:
        self.repository = repository or get_repository()

    def evaluate(
        self,
        req: LessonPlanReviewRequest,
        *,
        tier: str = "research_internal",
    ) -> LessonPlanReviewResponse:
        gate = TrustGate(tier)  # type: ignore[arg-type]
        rubric = self.repository.find_rubric(task_type="lesson_plan", exam="NTCE")
        verdict = gate.classify_rubric(rubric)
        text = req.plan_text or ""

        dimensions: List[dict] = []
        missed: List[str] = []
        for dimension in (rubric or {}).get("dimensions") or []:
            name = dimension.get("dimension_name") or "未命名维度"
            weight = dimension.get("weight_score")
            levels = dimension.get("criteria_levels") or []
            ratio, snippet = self._presence(text, dimension)
            level = pick_level(levels, ratio)
            dimensions.append(
                {
                    "dimension_name": name,
                    "weight_score": weight,
                    "coverage": round(ratio, 4),
                    "evidence_snippet": snippet,
                    "level_reference": (level or {}).get("level_name"),
                    "descriptor": (level or {}).get("descriptor"),
                    "status": "文本内比对到相关表述" if snippet else "文本内未比对到相关表述",
                }
            )
            if not snippet:
                missed.append(name)

        suggestions = (
            f"学科：{req.subject}；学段：{req.grade_level}；课题：{req.topic}。"
            + ("请按上述缺失维度补写，并把每个环节的教师活动与学生活动分开陈述。" if missed else "")
            + "维度名称、分值与档位描述均引自库内量规，未作改写。"
        )

        notices = list(verdict.notices)
        if not verdict.found:
            notices.append(NO_RUBRIC_NOTICE)

        signed_total = self._signed_total(text, rubric) if verdict.may_score else None
        if not verdict.signed:
            notices.append(FEEDBACK_ONLY_NOTICE)

        return LessonPlanReviewResponse(
            total_score=signed_total,
            max_score=(rubric or {}).get("total_score"),
            feedback_only=signed_total is None,
            rubric_signed=verdict.signed,
            rubric_id=verdict.rubric_id,
            dimensions=dimensions,
            missed_elements=missed,
            improvement_suggestions=suggestions,
            trust_tier=req.trust_tier if isinstance(req.trust_tier, TrustTier) else TrustTier(tier),  # type: ignore[arg-type]
            notices=notices,
        )

    @staticmethod
    def _presence(text: str, dimension: dict) -> tuple:
        """How strongly the draft reproduces this dimension's own wording. ``(ratio, snippet)``."""
        chunks = [dimension.get("dimension_name") or ""] + [
            level.get("descriptor") or "" for level in dimension.get("criteria_levels") or []
        ]
        best_ratio, best_snippet = 0.0, ""
        for chunk in filter(None, chunks):
            for cue in ELEMENT_CUE:
                if cue in chunk and cue in text:
                    index = text.find(cue)
                    return (1.0, text[max(0, index - 6) : index + 24])
            ratio, snippet = overlap(chunk, text)
            if ratio > best_ratio:
                best_ratio, best_snippet = ratio, snippet
        return (best_ratio, best_snippet)

    @staticmethod
    def _signed_total(text: str, rubric: dict) -> float:
        """Weighted total, reachable only once the reviewer signs the rubric."""
        total = 0.0
        for dimension in rubric.get("dimensions") or []:
            weight = float(dimension.get("weight_score") or 0.0)
            ratio, _ = LessonPlanEvaluator._presence(text, dimension)
            total += weight * min(1.0, ratio)
        return round(total, 1)
