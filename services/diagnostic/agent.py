"""DiagnosticAgent for psychometric diagnosis, radar chart generation, and weak-point localization."""
from __future__ import annotations

from typing import Dict, List

from services.common.models import (
    DiagnosticReport,
    DiagnosticRequest,
    ModuleAbility,
)
from services.diagnostic.score_converter import ScoreConverter

# Default module names mapped by module_id prefix
MODULE_NAME_MAP = {
    "m1": "职业理念与学生观",
    "m2": "教育法律法规与政策",
    "m3": "教师职业道德规范",
    "m4": "文化素养与通识常识",
    "m5": "基本能力（逻辑/信息/阅读/写作）",
    "cet_listening": "听力理解（Listening）",
    "cet_reading": "阅读理解（Reading）",
    "cet_writing": "短文写作（Writing）",
    "cet_translation": "段落翻译（Translation）",
}


class DiagnosticAgent:
    """Agent diagnosing student baseline capability and converting scale scores."""

    def __init__(self):
        pass

    def evaluate(self, request: DiagnosticRequest) -> DiagnosticReport:
        """Process answer submissions and compute psychometric diagnostic report."""
        submissions = request.submissions or []
        is_cet = "CET" in request.exam_type

        # Default max raw score
        max_raw = 100.0 if is_cet else 150.0

        if not submissions:
            # Baseline report if no submissions provided
            point_est = 425.0 if is_cet else 70.0
            return DiagnosticReport(
                user_id=request.user_id,
                exam_type=request.exam_type,
                raw_score=0.0,
                max_raw_score=max_raw,
                point_estimate=point_est,
                predicted_score_interval=[point_est - 30.0, point_est + 30.0],
                pass_probability=0.50,
                radar_chart=[],
                weak_points_top5=[],
                recommended_actions=["请先完成冷启动 30 题摸底自适应测验以建立学情档案。"],
            )

        # 1. Aggregate statistics across modules and knowledge nodes
        module_stats: Dict[str, Dict[str, int]] = {}
        node_fails: Dict[str, int] = {}
        total_raw_score = 0.0

        for sub in submissions:
            mod_id = sub.module_id or "m1"
            if mod_id not in module_stats:
                module_stats[mod_id] = {"total": 0, "correct": 0}
            module_stats[mod_id]["total"] += 1

            if sub.is_correct:
                module_stats[mod_id]["correct"] += 1
                total_raw_score += (max_raw / len(submissions))
            else:
                node_fails[sub.node_id] = node_fails.get(sub.node_id, 0) + 1

        # 2. Build ModuleAbility radar chart
        radar_chart: List[ModuleAbility] = []
        for mod_id, st in module_stats.items():
            tot = st["total"]
            corr = st["correct"]
            rate = round(corr / tot, 3) if tot > 0 else 0.0
            mod_name = MODULE_NAME_MAP.get(mod_id, f"模块 {mod_id}")
            radar_chart.append(
                ModuleAbility(
                    module_id=mod_id,
                    module_name=mod_name,
                    mastery_rate=rate,
                    question_count=tot,
                    correct_count=corr,
                )
            )

        # 3. Scale score conversion
        if is_cet:
            point_est, interval, pass_prob = ScoreConverter.cet_norm_conversion(
                raw_score=total_raw_score,
                max_raw_score=max_raw,
            )
        else:
            point_est, interval, pass_prob = ScoreConverter.ntce_piecewise_conversion(
                raw_score=total_raw_score,
                pass_cutoff_raw=90.0,
                max_raw_score=max_raw,
            )

        # 4. Top 5 weak knowledge points
        sorted_weak = sorted(node_fails.items(), key=lambda x: x[1], reverse=True)
        weak_points = [k for k, _ in sorted_weak[:5]]

        # 5. Targeted instructional recommendations
        recommendations = []
        if pass_prob < 0.60:
            recommendations.append("当前预测分接近及格线临界区，建议优先针对薄弱模块进行基础概念强化。")
        else:
            recommendations.append("整体基础扎实，建议转入高频考点强化与真题全真模考冲刺。")

        if weak_points:
            recommendations.append(f"重点突破前序知识薄弱项: {', '.join(weak_points[:3])}。")
        recommendations.append("已自动将错题同步至 FSRS 空间间隔复习队列，建议于明天完成首轮复习。")

        return DiagnosticReport(
            user_id=request.user_id,
            exam_type=request.exam_type,
            raw_score=round(total_raw_score, 1),
            max_raw_score=max_raw,
            point_estimate=point_est,
            predicted_score_interval=interval,
            pass_probability=pass_prob,
            radar_chart=radar_chart,
            weak_points_top5=weak_points,
            recommended_actions=recommendations,
        )
