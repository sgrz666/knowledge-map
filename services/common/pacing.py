"""服务侧的配速口径：分钟数的来源只有两种，库内说得出的和库内说不出来的。

库里能说出用时的地方有两处：模考卷面按 `paper_specs` 的逐节用时（见
`services.knowledge.repository.timed_stages` / `mock_minutes`），单题按题面约束
（`extra.task_constraints.time_limit_minutes`，见 `item_time_limit`）。两处都说不出时，
服务只能按本文件这一个配速数折算——它是估计，不是官方题均用时，必须随结果一起说明。
排课与组卷共用这一份，避免两个层各抄一个"每题几分钟"再互相打架。
"""

import math
from typing import Iterable, Optional

#: 库内没有题面用时约束时，服务给一题估的分钟数。
MINUTES_PER_QUESTION: float = 2.0


def pace_minutes(items: int) -> int:
    """把若干道「库里说不出用时」的题折成分钟数；零题不编时间。"""
    return int(math.ceil(max(0, int(items)) * MINUTES_PER_QUESTION))


def paper_minutes(library_limits: Iterable[Optional[int]]) -> dict:
    """按「先问库内题面约束，库里没有的才估」合成一份限时。

    返回 ``{"total": Optional[int], "declared_items": N, "declared_minutes": X,
    "estimated_items": M, "estimated_minutes": Y}``；题量为零时 ``total`` 为 None。
    """
    records = list(library_limits)
    limits = [int(v) for v in records if v]
    estimated_items = len(records) - len(limits)
    estimated_minutes = pace_minutes(estimated_items)
    declared_minutes = sum(limits)
    total = declared_minutes + estimated_minutes
    return {
        "total": total or None,
        "declared_items": len(limits),
        "declared_minutes": declared_minutes,
        "estimated_items": estimated_items,
        "estimated_minutes": estimated_minutes,
    }


def pacing_notice(breakdown: dict) -> str:
    """把限时拆开说清：多少来自库内题面约束，多少是服务估的。"""
    if breakdown["declared_items"] and breakdown["estimated_items"]:
        return (
            f"限时 {breakdown['total']} 分钟：其中 {breakdown['declared_items']} 题按库内题面约束"
            f"（extra.task_constraints.time_limit_minutes）合计 {breakdown['declared_minutes']} 分钟，"
            f"另外 {breakdown['estimated_items']} 题库内没有题面用时，按服务配速每题 "
            f"{MINUTES_PER_QUESTION:g} 分钟估 {breakdown['estimated_minutes']} 分钟——后者不是官方题均用时。"
        )
    if breakdown["declared_items"]:
        return (
            f"限时 {breakdown['total']} 分钟，全部按库内题面约束"
            "（extra.task_constraints.time_limit_minutes）合计；服务未添加任何估时。"
        )
    return (
        f"限时 {breakdown['total']} 分钟：库内这些题没有题面用时约束，"
        f"分钟数按服务配速每题 {MINUTES_PER_QUESTION:g} 分钟估出，不是官方题均用时；"
        "要按卷面限时请由教研把题面约束补齐。"
    )
