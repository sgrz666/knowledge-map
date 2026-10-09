"""NTCE (National Teacher Certification Examination) Analytic Criteria Scoring Engine.

Implements multi-dimensional weighted rubric assessment (Analytic Criteria)
with key scoring points (rubric_points_hit) hit detection conforming to
数据集/教资/rubrics/*.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from services.common.models import (
    AnalyticDetails,
    AnalyticDimensionResult,
    RubricPointHit,
    SubjectiveGradingRequest,
    UnifiedSubjectiveGradingResponse,
)

ROOT = Path(__file__).resolve().parents[2]
NTCE_RUBRICS_DIR = ROOT / "数据集" / "教资" / "rubrics"


class NTCEAnalyticGrader:
    """Evaluates NTCE subjective tasks: case_analysis, lesson_plan, short_answer, essay_writing."""

    # Map task type keywords to rubric json file names
    TASK_FILE_MAP = {
        "case_analysis": "case_analysis.json",
        "材料分析": "case_analysis.json",
        "lesson_plan": "lesson_plan.json",
        "教学设计": "lesson_plan.json",
        "活动设计": "lesson_plan.json",
        "short_answer": "short_answer.json",
        "简答": "short_answer.json",
        "writing": "essay_writing.json",
        "essay": "essay_writing.json",
        "作文": "essay_writing.json",
        "interview_qa": "interview_qa.json",
    }

    @classmethod
    def load_rubric(cls, task_type: str, rubric_id: Optional[str] = None) -> Optional[dict]:
        """Load corresponding rubric json from 数据集/教资/rubrics/."""
        # 1. Try direct rubric_id matching
        if rubric_id:
            for path in NTCE_RUBRICS_DIR.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if data.get("rubric_id") == rubric_id:
                        return data
                except Exception:
                    continue

        # 2. Try task_type map
        fname = cls.TASK_FILE_MAP.get(task_type.lower())
        if not fname:
            for key, val in cls.TASK_FILE_MAP.items():
                if key in task_type.lower():
                    fname = val
                    break

        if fname:
            path = NTCE_RUBRICS_DIR / fname
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        # Fallback to case_analysis if available
        fallback_path = NTCE_RUBRICS_DIR / "case_analysis.json"
        if fallback_path.is_file():
            return json.loads(fallback_path.read_text(encoding="utf-8"))

        return None

    @classmethod
    def extract_expected_points(
        cls,
        reference_answer: Optional[str],
        rubric_data: Optional[dict],
    ) -> List[str]:
        """Extract expected key scoring points from reference answer or rubric."""
        points: List[str] = []

        # 1. From rubric question_specific_points
        if rubric_data and rubric_data.get("question_specific_points"):
            for item in rubric_data["question_specific_points"]:
                if isinstance(item, str):
                    points.append(item)
                elif isinstance(item, dict) and "point" in item:
                    points.append(item["point"])

        # 2. If reference_answer provided, extract numbered clauses (1. 2. 3. or ① ② ③)
        if reference_answer:
            ref_clean = reference_answer.strip()
            # Split by common item markers: 1. (1) ① 第一
            patterns = re.split(r"(?:[0-9]+[、.．]|\([0-9]+\)|[①-⑩]|第[一二三四五六七八九十][、点：:])", ref_clean)
            for seg in patterns:
                seg_s = seg.strip()
                if len(seg_s) >= 4:
                    # Take first sentence or clause as core concept point
                    clause = re.split(r"[，。；\n]", seg_s)[0].strip()
                    if len(clause) >= 3 and clause not in points:
                        points.append(clause[:40])

        # 3. Default foundational pedagogy keywords if still empty
        if not points:
            points = [
                "职业理念（教育观/学生观/教师观）",
                "因材施教与促进全面发展",
                "关爱学生与师德师风要求",
                "理论阐述结合材料具体分析",
            ]

        return points[:5]

    @classmethod
    def evaluate(
        cls,
        req: SubjectiveGradingRequest,
        llm_response: Optional[dict] = None,
    ) -> UnifiedSubjectiveGradingResponse:
        """Perform analytic scoring for NTCE subjective question."""
        rubric = cls.load_rubric(req.task_type, req.rubric_id)
        expected_points = cls.extract_expected_points(req.reference_answer, rubric)

        # Parse LLM response if available
        if llm_response and "dimensions" in llm_response:
            dim_results: List[AnalyticDimensionResult] = []
            total = 0.0
            for d in llm_response["dimensions"]:
                score = float(d.get("score", 0.0))
                max_s = float(d.get("max_score", score))
                score = min(max_s, max(0.0, score))
                total += score
                dim_results.append(
                    AnalyticDimensionResult(
                        dimension_name=d.get("dimension_name", "维度"),
                        score=score,
                        max_score=max_s,
                        level_name=d.get("level_name", "良好"),
                        rationale=d.get("rationale", ""),
                    )
                )

            pts_hit: List[RubricPointHit] = []
            for p in llm_response.get("rubric_points_hit", []):
                pts_hit.append(
                    RubricPointHit(
                        point_text=p.get("point_text", ""),
                        status=p.get("status", "missed"),
                        evidence=p.get("evidence", ""),
                    )
                )

            return UnifiedSubjectiveGradingResponse(
                question_id=req.question_id,
                exam_type=req.exam_type,
                grading_mode="analytic_criteria",
                total_score=round(total, 2),
                max_score=req.max_score or (rubric.get("total_score") if rubric else 14.0) or 14.0,
                analytic_details=AnalyticDetails(
                    dimensions=dim_results,
                    rubric_points_hit=pts_hit,
                ),
                evaluation_summary=llm_response.get("evaluation_summary", "整体作答符合量规基本要求。"),
                revision_advice=llm_response.get("revision_advice", "请针对未命中的考点与材料结合度进行深入阐述。"),
                confidence_score=float(llm_response.get("confidence_score", 0.86)),
                review_status="llm_graded",
            )

        # Calibrated Heuristic Rule Engine
        answer = req.student_answer.strip()
        ans_len = len(answer)

        # 1. Match Rubric Points
        points_hit: List[RubricPointHit] = []
        hit_count = 0
        for pt in expected_points:
            # Check keyword match
            keywords = [k for k in re.split(r"[（）()、/与和的]", pt) if len(k) >= 2]
            matched_kws = [k for k in keywords if k in answer]

            if len(matched_kws) >= max(1, len(keywords) // 2):
                status = "hit"
                hit_count += 1
                evidence = f"命中关键词: {', '.join(matched_kws)}"
            elif matched_kws:
                status = "partial"
                hit_count += 0.5
                evidence = f"部分提及: {', '.join(matched_kws)}"
            else:
                status = "missed"
                evidence = "未见相关概念表述"

            points_hit.append(RubricPointHit(point_text=pt, status=status, evidence=evidence))

        ratio = hit_count / max(len(expected_points), 1)

        # 2. Score dimensions based on rubric or standard 4-dimension template
        dimensions_conf = rubric.get("dimensions", []) if rubric else []
        if not dimensions_conf:
            dimensions_conf = [
                {
                    "dimension_name": "核心要点与知识定位",
                    "weight_score": 4.0,
                    "criteria_levels": [
                        {"level_name": "优秀", "score_range": [3.6, 4.0], "descriptor": "全面准确命中考查要点"},
                        {"level_name": "良好", "score_range": [2.8, 3.5], "descriptor": "命中多数主要考点"},
                        {"level_name": "及格", "score_range": [2.0, 2.7], "descriptor": "仅命中部分考点"},
                        {"level_name": "不及格", "score_range": [0.0, 1.9], "descriptor": "考点遗漏严重或脱靶"},
                    ],
                },
                {
                    "dimension_name": "材料结合与理论阐述",
                    "weight_score": 4.0,
                    "criteria_levels": [
                        {"level_name": "优秀", "score_range": [3.6, 4.0], "descriptor": "结合材料深入细致"},
                        {"level_name": "良好", "score_range": [2.8, 3.5], "descriptor": "有材料结合，分析合理"},
                        {"level_name": "及格", "score_range": [2.0, 2.7], "descriptor": "材料与理论结合牵强"},
                        {"level_name": "不及格", "score_range": [0.0, 1.9], "descriptor": "只抄材料或空洞理论"},
                    ],
                },
                {
                    "dimension_name": "逻辑结构与条理层次",
                    "weight_score": 3.0,
                    "criteria_levels": [
                        {"level_name": "优秀", "score_range": [2.7, 3.0], "descriptor": "层次分明，逻辑严密"},
                        {"level_name": "良好", "score_range": [2.1, 2.6], "descriptor": "结构清晰，有分段条目"},
                        {"level_name": "及格", "score_range": [1.5, 2.0], "descriptor": "分段不明显但尚有次序"},
                        {"level_name": "不及格", "score_range": [0.0, 1.4], "descriptor": "杂乱无章，逻辑混乱"},
                    ],
                },
                {
                    "dimension_name": "语言表达与答题规范",
                    "weight_score": 3.0,
                    "criteria_levels": [
                        {"level_name": "优秀", "score_range": [2.7, 3.0], "descriptor": "师范用语规范流畅"},
                        {"level_name": "良好", "score_range": [2.1, 2.6], "descriptor": "表达通顺，术语准确"},
                        {"level_name": "及格", "score_range": [1.5, 2.0], "descriptor": "语言平淡，有口语化"},
                        {"level_name": "不及格", "score_range": [0.0, 1.4], "descriptor": "语句不通，错别字多"},
                    ],
                },
            ]

        dim_results: List[AnalyticDimensionResult] = []
        total_score = 0.0

        for d in dimensions_conf:
            w = float(d.get("weight_score", 3.0))
            levels = d.get("criteria_levels", [])

            # Quality factor based on hit ratio & length
            if ans_len < 30:
                q_factor = 0.25
            elif ans_len < 80:
                q_factor = 0.5
            else:
                q_factor = max(0.4, min(1.0, ratio * 0.8 + (min(ans_len, 350) / 350.0) * 0.2))

            dim_score = round(w * q_factor, 1)

            # Determine level_name
            selected_level = "及格"
            descriptor = ""
            for lvl in levels:
                rng = lvl.get("score_range", [0, w])
                if rng[0] <= dim_score <= rng[1]:
                    selected_level = lvl.get("level_name", "及格")
                    descriptor = lvl.get("descriptor", "")
                    break

            dim_results.append(
                AnalyticDimensionResult(
                    dimension_name=d.get("dimension_name", ""),
                    score=dim_score,
                    max_score=w,
                    level_name=selected_level,
                    rationale=descriptor or f"基于得分率 {q_factor:.2f} 评定分值 {dim_score}/{w}",
                )
            )
            total_score += dim_score

        # 3. Generate actionable revision advice
        missed_pts = [p.point_text for p in points_hit if p.status == "missed"]
        if missed_pts:
            advice = (
                f"建议强化以下核心考点的提炼与呈现：【{'；'.join(missed_pts[:3])}】。"
                "主观题作答时应先亮出具体理论关键词，再结合材料行为细节印证，末尾点明教师教育启示。"
            )
        else:
            advice = (
                "考点覆盖良好！建议进一步精炼分点序号（如一、二、三），"
                "增强专业术语的规范度与材料关联句的说服力。"
            )

        max_rubric_total = sum(d.get("weight_score", 3.0) for d in dimensions_conf)

        return UnifiedSubjectiveGradingResponse(
            question_id=req.question_id,
            exam_type=req.exam_type,
            grading_mode="analytic_criteria",
            total_score=round(total_score, 1),
            max_score=req.max_score or max_rubric_total,
            analytic_details=AnalyticDetails(
                dimensions=dim_results,
                rubric_points_hit=points_hit,
            ),
            evaluation_summary=f"全题采分点覆盖率约 {ratio*100:.0f}%，结构与结合度评分正常。",
            revision_advice=advice,
            confidence_score=0.85,
            review_status="heuristic_graded",
        )
