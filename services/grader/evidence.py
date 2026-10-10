"""Evidence helpers shared by both grading modes.

Everything here quotes either the student's own text or a rubric field that exists in the
library. Nothing invents 采分点: when the library holds none for a task, the answer is
"no points on record", not a built-in keyword list (that fallback used to live in
``ntce_analytic.py`` and is exactly the shadow data A1 forbids).
"""
from __future__ import annotations

import difflib
import re
from typing import List, Optional, Tuple

from services.common.models import HolisticDimensionFeedback, RubricPointHit

_SEGMENTED = re.compile(r"(?:[0-9]+\s*[、.．)]|\([0-9]+\)|[①-⑩]|第[一二三四五六七八九十]+[、点：:])")


def overlap(point: str, answer: str) -> Tuple[float, str]:
    """How much of a 采分点's own wording the answer reproduces, plus the longest shared run.

    Contiguous overlap rather than a keyword list: the library stores no per-point keywords, and
    splitting a clause into tokens produced matches that depended on our own tokenizer.
    """
    point = (point or "").strip()
    if not point or not (answer or "").strip():
        return (0.0, "")
    matcher = difflib.SequenceMatcher(a=point, b=answer, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size >= 2]
    matched_chars = sum(block.size for block in blocks)
    longest = max(blocks, key=lambda b: b.size, default=None)
    snippet = point[longest.a : longest.a + longest.size] if longest else ""
    return (matched_chars / len(point), snippet)


def match_point(point: str, answer: str) -> Tuple[str, str]:
    """Classify a scoring point against the answer: hit / partial / missed, with the shared run."""
    ratio, snippet = overlap(point, answer)
    if ratio >= 0.5:
        return ("hit", snippet)
    if ratio >= 0.2:
        return ("partial", snippet)
    return ("missed", snippet)


def quote_answer(answer: str, tokens: List[str], *, limit: int = 80) -> str:
    """Quote the student's own sentence that contains the matched tokens, or the opening line."""
    sentences = [s.strip() for s in re.split(r"[。；;\n]", answer or "") if s.strip()]
    if tokens:
        for sentence in sentences:
            if any(token in sentence for token in tokens):
                return sentence[:limit]
    return (sentences[0][:limit] if sentences else (answer or "").strip()[:limit])


def expected_points(
    rubric: Optional[dict],
    reference_answer: Optional[str],
    record: Optional[dict] = None,
) -> Tuple[List[str], str]:
    """采分点只认库内记录；调用方自带的参考作答排在最后，且来源必须写清是"调用方自备"。

    Returns ``(points, provenance)`` where provenance names the field the points were read from,
    so the response can say where its own checklist came from. 顺序即口径：库内 ``content.answer``
    与 ``content.reference_answer`` 先于调用方文本——否则任何人传一份自定参考答案，就能顶掉教研
    核定的判分依据，而响应仍挂着库内的 ``question_id``。
    """
    points: List[str] = []
    provenance = ""

    for item in (rubric or {}).get("question_specific_points") or []:
        text = item if isinstance(item, str) else (item.get("point") if isinstance(item, dict) else None)
        if text and text not in points:
            points.append(text)
    if points:
        provenance = "库内量规 question_specific_points 原文"

    content = (record or {}).get("content") or {}
    candidates = (
        (content.get("answer"), "库内 content.answer 分点切分"),
        (content.get("reference_answer"), "库内 content.reference_answer 分点切分"),
        (reference_answer, "调用方自备 reference_answer 分点切分（库内该题没有参考原文，不代表教研核定的判分口径）"),
    )
    for candidate, label in candidates:
        if points or not candidate:
            continue
        segments = [s.strip() for s in _SEGMENTED.split(str(candidate)) if len(s.strip()) >= 4]
        for segment in segments:
            clause = re.split(r"[，。；,;.]", segment)[0].strip()
            if len(clause) >= 3 and clause not in points:
                points.append(clause[:40])
        if points:
            provenance = label

    framework = (record or {}).get("rubric") or content.get("rubric") or {}
    if isinstance(framework, dict):
        for item in framework.get("key_points") or framework.get("points") or []:
            text = item if isinstance(item, str) else (item.get("point") if isinstance(item, dict) else None)
            if text and text not in points:
                points.append(text)
        if points and not provenance:
            provenance = "库内题目内嵌练习框架 key_points"

    return points[:8], provenance


def coverage(points: List[str], answer: str) -> Tuple[List[RubricPointHit], float]:
    """Compare the answer with each 采分点 and return the hit list plus the coverage ratio."""
    hits: List[RubricPointHit] = []
    total = 0.0
    for point in points:
        status, snippet = match_point(point, answer)
        hits.append(
            RubricPointHit(
                point_text=point,
                status=status,
                evidence=(f"与作答重合的表述：{snippet}" if snippet else "作答中未比对到该要点的表述"),
            )
        )
        total += {"hit": 1.0, "partial": 0.5, "missed": 0.0}[status]
    return hits, (total / len(points)) if points else 0.0


def feedback_dimensions(rubric: Optional[dict], mode: str) -> List[dict]:
    """The dimension list the library itself provides for this rubric shape.

    CET band rubrics carry ``feedback_dimensions`` (name + required evidence + aggregation) and
    bands; NTCE A.6 rubrics carry weighted ``dimensions``. Neither is ever supplemented here.
    """
    record = rubric or {}
    if mode == "holistic_band":
        declared = [
            {
                "dimension_name": item.get("name") or "未命名反馈维度",
                "criteria_levels": [
                    {
                        "level_name": item.get("aggregation") or "未标注聚合方式",
                        "descriptor": item.get("required_evidence") or "无证据要求",
                    }
                ],
            }
            for item in record.get("feedback_dimensions") or []
        ]
        if declared:
            return declared
        return [
            {
                "dimension_name": f"档位 {band.get('band')}",
                "criteria_levels": [{"level_name": str(band.get("band")), "descriptor": band.get("descriptor")}],
            }
            for band in record.get("bands") or []
        ]
    return record.get("dimensions") or []


def nearest_band_descriptor(bands: List[dict], ratio: float) -> Optional[dict]:
    """The band whose position the coverage ratio is closest to, returned as quoted text only."""
    if not bands:
        return None
    ordered = sorted(bands, key=lambda band: -float(band.get("band") or 0))
    index = min(len(ordered) - 1, max(0, int(round((1.0 - ratio) * (len(ordered) - 1)))))
    return ordered[index]


def pick_level(levels: List[dict], ratio: float) -> Optional[dict]:
    """Map the coverage ratio onto the library's own level list.

    ``criteria_levels`` are stored best-first in every rubric in the library, so full coverage is
    the first entry and zero coverage the last. Nothing is reordered or renamed here.
    """
    if not levels:
        return None
    index = min(len(levels) - 1, max(0, int(round((1.0 - ratio) * (len(levels) - 1)))))
    return levels[index]


def dimension_feedback(
    dimensions: List[dict],
    hits: List[RubricPointHit],
    ratio: float,
    answer: str,
) -> List[HolisticDimensionFeedback]:
    """Qualitative, per-dimension comments that quote the library's descriptors and the student."""
    matched = [h.point_text for h in hits if h.status != "missed"]
    missed = [h.point_text for h in hits if h.status == "missed"]
    tokens: List[str] = []
    if matched:
        tokens.append(matched[0])
    if missed:
        tokens.append(missed[0])
    evidence = quote_answer(answer, tokens)

    out: List[HolisticDimensionFeedback] = []
    for dimension in dimensions:
        name = dimension.get("dimension_name") or "未命名维度"
        levels = dimension.get("criteria_levels") or []
        if not hits:
            level = levels[0] if levels else None
            comment = (
                f"未做点级比对（库内无采分点且未提供参考作答）。量规维度「{name}」首档描述："
                f"{(level or {}).get('descriptor') or '档位未录入'}"
            )
        else:
            level = pick_level(levels, ratio)
            comment = (
                f"按库内维度「{name}」的档位描述（{(level or {}).get('level_name') or '档位未录入'}）"
                f"比对作答：{(level or {}).get('descriptor') or '无描述'}"
            )
        out.append(
            HolisticDimensionFeedback(
                dimension_name=name,
                feedback_comment=comment,
                evidence_quote=evidence,
            )
        )
    return out
