"""Shared vocabulary that maps request-level ids onto the dataset's own field values.

Kept in one place so agents never invent their own module naming. Aliases that the
dataset cannot honour collapse to the nearest real value and report that through
``ResolutionNotice`` instead of silently widening or narrowing the pool.
"""
from __future__ import annotations

from typing import Optional, Tuple

# Exam ids used by the API -> ``exam`` values present in the dataset.
EXAM_VALUES = {
    "CET-4": ("CET-4",),
    "CET-6": ("CET-6",),
    "NTCE": ("NTCE", "省考"),
}

# Legacy module ids still accepted by the API -> dataset ``module`` values.
# The NTCE five 综合素质 sub-modules are not separate ``module`` values in the
# library, so they all resolve to the whole 综合素质 pool at module granularity.
NTCE_QUALITY_MODULES = ("综合素质",)

MODULE_ALIASES = {
    "m1": NTCE_QUALITY_MODULES,
    "m2": NTCE_QUALITY_MODULES,
    "m3": NTCE_QUALITY_MODULES,
    "m4": NTCE_QUALITY_MODULES,
    "m5": NTCE_QUALITY_MODULES,
    "cet_listening": ("听力理解",),
    "cet_reading": ("阅读理解",),
    "cet_writing": ("写作",),
    "cet_translation": ("翻译",),
    "listening": ("听力理解",),
    "reading": ("阅读理解",),
    "writing": ("写作",),
    "translation": ("翻译",),
}

COARSE_MODULE_NOTICE = (
    "库内未对《综合素质》五个子模块单列 module 字段，已按综合素质整体组卷；"
    "需要子模块精度请改传 target_node（知识点级已建索引）。"
)

# ``section`` / ``question_type`` values that can be machine-checked by option letter.
MC_SECTIONS = ("单项选择题", "多项选择题", "单选题", "多选题")
MC_TYPES = ("单选", "多选")

# Request-side task names -> ``task_type`` values used by 数据集/教资/rubrics/*.json and
# 数据集/四六级/ontology/scoring_rubrics.jsonl. Aliases the library cannot honour stay as-is,
# so the grader reports "no rubric for this task" instead of grading against a made-up one.
TASK_TYPE_ALIASES = {
    "材料分析": "case_analysis",
    "case_analysis": "case_analysis",
    "教学设计": "lesson_plan",
    "活动设计": "lesson_plan",
    "lesson_plan": "lesson_plan",
    "简答": "short_answer",
    "short_answer": "short_answer",
    "作文": "writing",
    "essay": "writing",
    "writing": "writing",
    "short_essay": "short_essay",
    "paragraph_translation": "paragraph_translation",
    "翻译": "paragraph_translation",
    "写作": "short_essay",
    "interview_qa": "interview_qa",
    "结构化问答": "interview_qa",
    "interview_teaching": "interview_teaching",
    "试讲": "interview_teaching",
}


def task_type_value(task_type: Optional[str]) -> Optional[str]:
    if not task_type:
        return None
    key = task_type.strip()
    return TASK_TYPE_ALIASES.get(key, key)


def exam_values(exam: Optional[str]) -> Tuple[str, ...]:
    if not exam:
        return ()
    return EXAM_VALUES.get(exam.upper() if exam.isascii() else exam, (exam,))


def module_values(exam: Optional[str], alias: Optional[str]) -> Tuple[Optional[Tuple[str, ...]], str]:
    """Return ``(values, notice)``; values ``None`` means "do not filter by module"."""
    if not alias:
        return None, ""
    key = alias.strip()
    values = MODULE_ALIASES.get(key)
    if values is None:
        # Already a dataset-native module name (e.g. 语文, 教育知识, 阅读理解).
        return (key,), ""
    notice = COARSE_MODULE_NOTICE if values is NTCE_QUALITY_MODULES and key.startswith("m") else ""
    return values, notice


def is_multiple_choice(section: Optional[str], question_type: Optional[str]) -> bool:
    return section in MC_SECTIONS or question_type in MC_TYPES
