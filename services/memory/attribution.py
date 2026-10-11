"""Five-dimensional educational error cause attribution decision tree (F6).

Categories conforming to specification Section 4.5:
1. 审题疏漏 (Careless)
2. 概念混淆 (Misconception)
3. 认知盲区 (Blindspot)
4. 策略不当 (Time Pressure / Strategy)
5. 表述不规范 (Expression Deficit)
"""
from __future__ import annotations

from typing import Optional

from services.common.models import (
    ErrorAttributionCategory,
    ErrorAttributionResult,
    ErrorReviewEvent,
)


class ErrorAttributionEngine:
    """Classifies root cause of an erroneous response using behavioral traces."""

    @classmethod
    def attribute(cls, event: ErrorReviewEvent, *, persisted_mastery: Optional[float]) -> ErrorAttributionResult:
        """Run hierarchical pedagogical classification tree on response trace.

        ``persisted_mastery`` is what this learner's stored record says about the node, or ``None``
        when the node has no record yet. The tree reads the learner's own behaviour plus that record;
        it never reads a number the caller declares about the question or about the learner.
        """
        # Case 5: Subjective expression deficit
        if event.is_subjective:
            if event.subjective_rubric_misses:
                misses_str = "、".join(event.subjective_rubric_misses[:3])
                return ErrorAttributionResult(
                    category=ErrorAttributionCategory.EXPRESSION_DEFICIT,
                    category_name="表述不规范 (踩分点遗漏)",
                    confidence=0.88,
                    rationale=f"主观题作答缺乏专业术语或遗漏核心采分点：【{misses_str}】。",
                    recommended_action="重温采分点量规，采用‘理论总括+材料引证+实践启示’三段式答题模板重构答案。",
                )
            return ErrorAttributionResult(
                category=ErrorAttributionCategory.EXPRESSION_DEFICIT,
                category_name="表述不规范",
                confidence=0.75,
                rationale="主观题逻辑展开层次欠清晰，缺乏师范专业答题规范。",
                recommended_action="强化主观题分条列项作答习惯，先亮明观点，再结合材料论述。",
            )

        # Case 1: Careless reading (Super fast speed or overlooked negation)
        # 只认学习者自己的动作。旧写法还要申报难度 < 0.75：那个浮点既不是库内记录（库内只有 heuristic_*
        # 初估，§10/A7 不许它参与能力推断），方向还能反过来用——同样 4 秒交卷，调用方报 0.8 就判不成疏漏。
        if event.time_spent_seconds <= 6.0 or (
            event.has_negation_in_stem and event.time_spent_seconds < 12.0
        ):
            neg_tip = "且题干含否定/限定词（如‘不正确/不属于’）" if event.has_negation_in_stem else ""
            return ErrorAttributionResult(
                category=ErrorAttributionCategory.CARELESS,
                category_name="审题疏漏",
                confidence=0.85,
                rationale=f"作答耗时极短（仅 {event.time_spent_seconds:.1f} 秒）{neg_tip}，未充分审题即匆忙选择。",
                recommended_action="慢审题、快作答：读题时圈画题干中的否定词与限定修饰语，强化审题自查习惯。",
            )

        # Case 4: Time pressure / test strategy issue
        # Excessively long struggle (> 150s for single objective question) or end-of-exam rush
        if event.time_spent_seconds > 150.0:
            return ErrorAttributionResult(
                category=ErrorAttributionCategory.TIME_PRESSURE,
                category_name="策略不当 (单题过度耗时)",
                confidence=0.80,
                rationale=f"单道选择题犹豫耗时达 {event.time_spent_seconds:.0f} 秒，严重挤占后续题型答题预算。",
                recommended_action="限时自律：客观题超过 60 秒无思路立即标记跳过，保障整卷时间分配平衡。",
            )

        # Case 2: Misconception (Typical distractor or option flipping between top 2)
        if event.is_typical_distractor or event.option_flip_count >= 2:
            return ErrorAttributionResult(
                category=ErrorAttributionCategory.MISCONCEPTION,
                category_name="概念混淆",
                confidence=0.82,
                rationale=f"落入典型高混淆干扰项陷阱（翻转修改 {event.option_flip_count} 次），对相近考点辨析模糊。",
                recommended_action="查看易混概念对比表，梳理概念内涵与外延边界，加练概念辨析双联题。",
            )

        # Case 3: Cognitive Blindspot —— 只认这位学习者在这条考点上的持久化记录。
        # 没有记录就不声称盲区：旧写法在没有记录时退回去读调用方申报的 current_node_mastery，
        # 于是"该考点历史掌握度仅 X%"里的 X 是一个从未存在过的历史。
        if persisted_mastery is not None and persisted_mastery < 0.35:
            return ErrorAttributionResult(
                category=ErrorAttributionCategory.BLINDSPOT,
                category_name="认知盲区",
                confidence=0.90,
                rationale=f"该考点你此前的掌握度记录为 {persisted_mastery*100:.0f}%，尚未建立基础知识框架。",
                recommended_action="回溯考纲对应知识卡片，精读基础理论并完成考点专属基础变式题巩固。",
            )

        # Default fallback: Misconception
        return ErrorAttributionResult(
            category=ErrorAttributionCategory.MISCONCEPTION,
            category_name="理解偏差",
            confidence=0.70,
            rationale="对本题所考查核心概念与题干情境的匹配理解存在偏差。",
            recommended_action="精读题干考点定位解析，重点对比所选选项与标准答案的本质区别。",
        )
