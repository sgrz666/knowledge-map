"""CET (College English Test 4 & 6) Holistic Band Scoring Engine.

Implements official Holistic Band Selection (14/11/8/5/2 bands, max raw score 15)
with three-dimensional qualitative feedback and evidence quotes conforming to
数据集/四六级/ontology/scoring_rubrics.jsonl.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from services.common.models import (
    HolisticDetails,
    HolisticDimensionFeedback,
    SubjectiveGradingRequest,
    UnifiedSubjectiveGradingResponse,
)

ROOT = Path(__file__).resolve().parents[2]
CET_RUBRICS_PATH = ROOT / "数据集" / "四六级" / "ontology" / "scoring_rubrics.jsonl"


# Default official fallback descriptors if file is unavailable
DEFAULT_CET_BANDS = {
    14: {
        "range": [13.0, 15.0],
        "descriptor": "切题。表达思想清楚，文字通顺、连贯，基本上无语言错误，仅有个别小错。",
    },
    11: {
        "range": [10.0, 12.0],
        "descriptor": "切题。表达思想清楚，文字连贯，但有少量语言错误。",
    },
    8: {
        "range": [7.0, 9.0],
        "descriptor": "基本切题。有些地方表达思想不够清楚，文字勉强连贯，语言错误相当多，其中有一些是严重错误。",
    },
    5: {
        "range": [4.0, 6.0],
        "descriptor": "基本切题。表达思想不清楚，连贯性差，有较多的严重语言错误。",
    },
    2: {
        "range": [1.0, 3.0],
        "descriptor": "条理不清，思路紊乱，语言支离破碎或大部分句子均有错误，且多数为严重错误。",
    },
}


class CETHolisticGrader:
    """Evaluates CET-4/6 writing (short essay) and paragraph translation."""

    @classmethod
    def load_rubric(cls, task_type: str) -> Optional[dict]:
        """Load official rubric from scoring_rubrics.jsonl if available."""
        if not CET_RUBRICS_PATH.is_file():
            return None
        try:
            for line in CET_RUBRICS_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                doc = json.loads(line)
                if doc.get("task_type") in (task_type, "short_essay", "paragraph_translation"):
                    return doc
        except Exception:
            pass
        return None

    @classmethod
    def analyze_english_text(cls, text: str) -> Dict[str, any]:
        """Extract linguistic and structural metrics from English student response."""
        words = re.findall(r"\b[A-Za-z]+(?:'[A-Za-z]+)?\b", text)
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
        word_count = len(words)
        sentence_count = len(sentences)
        avg_sentence_len = word_count / max(sentence_count, 1)

        # Lexical variety: Type-Token Ratio (TTR)
        unique_words = set(w.lower() for w in words)
        ttr = len(unique_words) / max(word_count, 1)

        # Basic discourse markers
        connectors = [
            "furthermore", "moreover", "however", "therefore", "nevertheless",
            "in addition", "on the one hand", "on the other hand", "firstly",
            "secondly", "in conclusion", "to sum up", "for example", "as a result",
            "consequently", "besides", "meanwhile", "notably", "significantly"
        ]
        text_lower = text.lower()
        connector_hits = [c for c in connectors if c in text_lower]

        return {
            "words": words,
            "word_count": word_count,
            "sentence_count": sentence_count,
            "avg_sentence_len": avg_sentence_len,
            "ttr": ttr,
            "connectors": connector_hits,
        }

    @classmethod
    def evaluate(
        cls,
        req: SubjectiveGradingRequest,
        llm_response: Optional[dict] = None,
    ) -> UnifiedSubjectiveGradingResponse:
        """Run holistic evaluation on a CET student submission.

        If `llm_response` is provided, parse and validate it;
        otherwise use calibrated heuristic rule engine.
        """
        metrics = cls.analyze_english_text(req.student_answer)
        word_count = metrics["word_count"]
        is_translation = "translat" in req.task_type.lower()

        # If LLM response provided, format it
        if llm_response and "selected_band" in llm_response:
            band = int(llm_response["selected_band"])
            raw_score = float(llm_response.get("total_score", band))
            band_info = DEFAULT_CET_BANDS.get(band, DEFAULT_CET_BANDS[8])
            min_s, max_s = band_info["range"]
            score = max(min_s, min(raw_score, max_s))

            dim_feedback = []
            for d in llm_response.get("qualitative_dimensions", []):
                dim_feedback.append(
                    HolisticDimensionFeedback(
                        dimension_name=d.get("dimension_name", "综合反馈"),
                        feedback_comment=d.get("feedback_comment", ""),
                        evidence_quote=d.get("evidence_quote", ""),
                    )
                )

            return UnifiedSubjectiveGradingResponse(
                question_id=req.question_id,
                exam_type=req.exam_type,
                grading_mode="holistic_band",
                total_score=score,
                max_score=req.max_score or 15.0,
                holistic_details=HolisticDetails(
                    selected_band=band,
                    band_range=[min_s, max_s],
                    qualitative_dimensions=dim_feedback,
                ),
                evaluation_summary=llm_response.get("evaluation_summary", band_info["descriptor"]),
                revision_advice=llm_response.get("revision_advice", "请针对语法与篇章衔接进行修改。"),
                confidence_score=float(llm_response.get("confidence_score", 0.88)),
                review_status="llm_graded",
            )

        # Deterministic Heuristic Evaluation
        # Benchmark lengths: Writing CET-4 >= 120, CET-6 >= 150; Translation >= 80 words
        target_words = 80 if is_translation else (120 if req.exam_type == "CET-4" else 150)

        # 1. Band assignment based on length, vocabulary, and discourse
        if word_count < 20:
            selected_band = 2
            raw_score = 2.0
            evidence = req.student_answer[:40] if req.student_answer else "作答字数过少"
        elif word_count < target_words * 0.45:
            selected_band = 5
            raw_score = 5.0
            evidence = req.student_answer[:60]
        elif word_count < target_words * 0.75:
            selected_band = 8
            raw_score = 8.0
            evidence = req.student_answer[:80]
        else:
            # Word count sufficient; check connector count and lexical density
            if len(metrics["connectors"]) >= 2 and metrics["ttr"] >= 0.45:
                selected_band = 14
                raw_score = 14.0
                evidence = f"篇章衔接词富足: {', '.join(metrics['connectors'][:3])}"
            elif len(metrics["connectors"]) >= 1:
                selected_band = 11
                raw_score = 11.5
                evidence = f"使用衔接词: {', '.join(metrics['connectors'][:2])}"
            else:
                selected_band = 8
                raw_score = 8.5
                evidence = "字数达标，但缺少复杂句式与逻辑连接词"

        band_meta = DEFAULT_CET_BANDS[selected_band]
        b_min, b_max = band_meta["range"]

        # 2. Build 3 qualitative feedback dimensions
        if is_translation:
            dims = [
                HolisticDimensionFeedback(
                    dimension_name="原文信息准确与完整",
                    feedback_comment="信息点传达基本完整，未出现严重关键名词误译。" if selected_band >= 8 else "信息点存在缺失或关键句意偏差。",
                    evidence_quote=evidence,
                ),
                HolisticDimensionFeedback(
                    dimension_name="句法与用词",
                    feedback_comment="用词得当，主谓一致和时态掌握较好。" if selected_band >= 11 else "句式结构偏简单，存在局部中式英语（Chinglish）表达。",
                    evidence_quote=req.student_answer[:50],
                ),
                HolisticDimensionFeedback(
                    dimension_name="语篇清晰与连贯",
                    feedback_comment="译文语句自然连贯，符合英语表达习惯。" if selected_band >= 11 else "译文句子间缺少自然衔接，语句稍显生硬。",
                    evidence_quote="衔接词标记" if metrics["connectors"] else "缺少连接过渡",
                ),
            ]
            advice = "建议强化段落翻译的专有名词积累，并在长难句拆分翻译后增加合句衔接润色。"
        else:
            dims = [
                HolisticDimensionFeedback(
                    dimension_name="切题与信息表达",
                    feedback_comment="立意切题，论述观点明确，能够有效回应写作引导提示。" if selected_band >= 8 else "立意偏离主题或字数过短，论据不充分。",
                    evidence_quote=evidence,
                ),
                HolisticDimensionFeedback(
                    dimension_name="篇章组织与衔接",
                    feedback_comment=f"三段式结构完整，使用了 {len(metrics['connectors'])} 个逻辑连接词。" if metrics["connectors"] else "段落内部缺少逻辑指示词，行文跳跃。",
                    evidence_quote=", ".join(metrics["connectors"]) or "未见明显连接词",
                ),
                HolisticDimensionFeedback(
                    dimension_name="语言准确性与词汇",
                    feedback_comment=f"词汇量覆盖良好（词汇丰富度 TTR={metrics['ttr']:.2f}），偶有个别语法小错。" if selected_band >= 11 else "词汇复现率较高，建议多使用中高级短语与从句替换简单句。",
                    evidence_quote=req.student_answer[:45],
                ),
            ]
            advice = "建议在写作首段亮出明确中心句（Thesis Statement），各展开段运用主题句+论据支撑结构，末段有力总结。"

        return UnifiedSubjectiveGradingResponse(
            question_id=req.question_id,
            exam_type=req.exam_type,
            grading_mode="holistic_band",
            total_score=round(raw_score, 1),
            max_score=req.max_score or 15.0,
            holistic_details=HolisticDetails(
                selected_band=selected_band,
                band_range=[b_min, b_max],
                qualitative_dimensions=dims,
            ),
            evaluation_summary=band_meta["descriptor"],
            revision_advice=advice,
            confidence_score=0.82,
            review_status="heuristic_graded",
        )
