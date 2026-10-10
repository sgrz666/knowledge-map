"""One rubric engine for both modes, reading the library's own rubric entities.

Replaces the two older engines, each of which shipped a copy of the rubric inside service code
(``DEFAULT_CET_BANDS`` held the transcribed CET band descriptors, ``ntce_analytic`` held a
four-dimension template and a list of pedagogy keywords used when the library had none). Both
were shadow data, and both produced a numeric score even though every rubric in the library is
unsigned — the two things A1 and A4 forbid.

The contract now:

* rubrics come from ``KnowledgeRepository.find_rubric`` and nowhere else;
* ``TrustGate.classify_rubric`` decides whether a score may exist at all;
* unsigned rubric ⇒ ``total_score = None``, ``feedback_only = True``, qualitative feedback that
  quotes the library's descriptors and the student's own sentences, and a review-queue row so the
  signature request reaches the single human 教研 reviewer;
* an LLM may only re-word the feedback (mode ``llm_graded``), never sign or re-score it.
"""
from __future__ import annotations

from typing import List, Optional

from services.common.models import (
    AnalyticDetails,
    AnalyticDimensionResult,
    HolisticDetails,
    SubjectiveGradingRequest,
    UnifiedSubjectiveGradingResponse,
)
from services.grader.evidence import (
    coverage,
    dimension_feedback,
    expected_points,
    feedback_dimensions,
    nearest_band_descriptor,
)
from services.knowledge.trust import RubricVerdict

NO_POINTS_NOTICE = (
    "库内该题型量规未录入 question_specific_points，且题内参考原文与本次请求的参考作答都切不出采分点，"
    "系统不内置采分点清单，只按维度描述给出质性反馈。"
)
FEEDBACK_ONLY_NOTICE = (
    "本次结果为反馈（feedback_only），不含分数：分值需要教研先签署量规权重与档位措辞。"
)
PUBLISHED_REFUSAL = (
    "published 档位只允许出具已签署量规的分数，当前量规未签署，已拒绝出分并转人工复核。"
)
UNKNOWN_QUESTION_NOTICE = (
    "该 question_id 未命中知识库索引：采分点只能来自本次请求自带的文本，不代表库内任何判分口径。"
    "面向学习者的判分入口（SubjectiveGraderAgent）对接未命中索引的题直接拒判，不调用本引擎。"
)
BAND_REFERENCE_NOTICE = (
    "档位列名与描述为库内转录原文，仅作练习反馈定位用；未出分，也不是报道分或官方阅卷结果。"
)

#: how many 采分点 a signed analytic rubric may credit per covered dimension at full coverage
DIMENSION_CREDIT = 1.0


def grade(
    req: SubjectiveGradingRequest,
    *,
    mode: str,
    rubric: Optional[dict],
    verdict: RubricVerdict,
    record: Optional[dict] = None,
    llm_payload: Optional[dict] = None,
    tier: str = "research_internal",
) -> UnifiedSubjectiveGradingResponse:
    """Produce the unified response; the score exists only when ``verdict.may_score`` says so."""
    answer = req.student_answer or ""
    points, points_from = expected_points(rubric, req.reference_answer, record)
    hits, ratio = coverage(points, answer)

    notices: List[str] = list(verdict.notices)
    if not points:
        notices.append(NO_POINTS_NOTICE)
    if points_from:
        notices.append(f"采分点来源：{points_from}。")
    if record is None:
        notices.append(UNKNOWN_QUESTION_NOTICE)

    dimensions = feedback_dimensions(rubric, mode)
    bands = (rubric or {}).get("bands") or []
    max_score = req.max_score or (rubric or {}).get("total_score") or (rubric or {}).get("max_raw_score")

    may_score = verdict.may_score
    if tier == "published" and not verdict.signed:
        may_score = False
        notices.append(PUBLISHED_REFUSAL)

    if may_score:
        total, analytic, holistic = _score(ratio, dimensions, bands, max_score, mode, hits, answer)
        score_basis = "signed_rubric"
        review_status = "llm_graded" if llm_payload else "heuristic_graded"
        feedback_only = False
    else:
        total = None
        feedback_only = True
        score_basis = "unsigned_framework" if verdict.found else "none"
        review_status = "quarantined_for_human"
        if mode == "holistic_band":
            band = nearest_band_descriptor(bands, ratio)
            holistic = HolisticDetails(
                selected_band=None,
                band_range=None,
                band_reference=(band or {}).get("descriptor"),
                qualitative_dimensions=dimension_feedback(dimensions, hits, ratio, answer),
            )
            analytic = None
            if band:
                notices.append(BAND_REFERENCE_NOTICE)
        else:
            holistic = None
            analytic = AnalyticDetails(
                dimensions=[],
                rubric_points_hit=hits,
                dimension_feedback=dimension_feedback(dimensions, hits, ratio, answer),
            )
        notices.append(FEEDBACK_ONLY_NOTICE)

    summary = _summary(ratio, hits, llm_payload, verdict)
    advice = _advice(hits, llm_payload, verdict, points_from)

    return UnifiedSubjectiveGradingResponse(
        question_id=req.question_id,
        exam_type=req.exam_type,
        grading_mode=mode,  # type: ignore[arg-type]
        total_score=total,
        max_score=max_score,
        feedback_only=feedback_only,
        score_basis=score_basis,  # type: ignore[arg-type]
        rubric_signed=verdict.signed,
        trust_tier=tier,  # type: ignore[arg-type]
        holistic_details=holistic,
        analytic_details=analytic,
        evaluation_summary=summary,
        revision_advice=advice,
        confidence_score=round(ratio, 4),
        review_status=review_status,  # type: ignore[arg-type]
        notices=notices,
    )


# --------------------------------------------------------------------- scoring
def _score(
    ratio: float,
    dimensions: List[dict],
    bands: List[dict],
    max_score,
    mode: str,
    hits,
    answer: str,
):
    """Weighted analytic total, or holistic band selection — only reachable on a signed rubric."""
    qualitative = dimension_feedback(dimensions, hits, ratio, answer)

    if mode == "holistic_band" and bands:
        band = nearest_band_descriptor(bands, ratio) or {}
        rng = band.get("raw_score_range") or [band.get("raw_score_min"), band.get("raw_score_max")]
        low, high = float(rng[0]), float(rng[1])
        details = HolisticDetails(
            selected_band=int(band.get("band") or 0),
            band_range=[low, high],
            band_reference=band.get("descriptor"),
            qualitative_dimensions=qualitative,
        )
        # A band is an interval; the midpoint is reported rather than the ceiling.
        return round(min((low + high) / 2.0, float(max_score or high)), 1), None, details

    analytic = AnalyticDetails(dimensions=[], rubric_points_hit=hits, dimension_feedback=[])
    total = 0.0
    for dimension in dimensions:
        weight = float(dimension.get("weight_score") or 0.0)
        awarded = round(weight * min(1.0, ratio * DIMENSION_CREDIT), 1)
        levels = dimension.get("criteria_levels") or []
        analytic.dimensions.append(
            AnalyticDimensionResult(
                dimension_name=dimension.get("dimension_name") or "未命名维度",
                score=awarded,
                max_score=weight,
                level_name=_level_for_score(levels, awarded),
                rationale=f"按已签署权重 {weight} 分与要点覆盖率 {ratio:.2f} 折算。",
            )
        )
        total += awarded
    return round(total, 1), analytic, None


def _level_for_score(levels: List[dict], awarded: float) -> str:
    for level in levels:
        rng = level.get("score_range") or []
        if len(rng) == 2 and float(rng[0]) <= awarded <= float(rng[1]):
            return str(level.get("level_name") or "未命名档位")
    return "未落入库内档位区间"


# ------------------------------------------------------------------- wording
def _summary(ratio: float, hits, llm_payload: Optional[dict], verdict: RubricVerdict) -> str:
    hit_count = sum(1 for h in hits if h.status == "hit")
    partial = sum(1 for h in hits if h.status == "partial")
    head = (
        f"与库内量规比对：采分点 {len(hits)} 项，完全比对 {hit_count} 项、部分比对 {partial} 项，"
        f"覆盖度 {ratio * 100:.0f}%。"
        if hits
        else "库内无可比对的采分点，仅按量规维度描述给出质性反馈。"
    )
    rubric_state = "已签署" if verdict.signed else f"未签署（review.status={verdict.review_status}）"
    extra = (llm_payload or {}).get("evaluation_summary")
    body = f"模型反馈草稿（未复核）：{extra}" if extra else ""
    return f"{head}量规状态：{rubric_state}。{body}".strip()


def _advice(hits, llm_payload: Optional[dict], verdict: RubricVerdict, points_from: str) -> str:
    missed = [h.point_text for h in hits if h.status == "missed"]
    partial = [h.point_text for h in hits if h.status == "partial"]
    parts: List[str] = []
    if missed:
        parts.append("作答中未比对到以下要点表述：" + "；".join(missed[:4]) + "。")
    if partial:
        parts.append("以下要点只比对到部分表述，建议补全完整措辞：" + "；".join(partial[:4]) + "。")
    if hits and not missed and not partial:
        parts.append("已比对到全部采分点表述，建议进一步展开每项的理论内涵与材料印证。")
    if not verdict.signed:
        parts.append("该分数需教研签署量规权重后才会出具；当前只给反馈。")
    if not points_from:
        parts.append("如需要点级比对，请补充库内 question_specific_points 或随请求提供参考作答。")
    extra = (llm_payload or {}).get("revision_advice")
    if extra:
        parts.append(f"模型建议草稿（未复核）：{extra}")
    return " ".join(parts)
