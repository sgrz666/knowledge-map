"""Trial teaching speech acoustics and discourse structure analyzer."""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from services.common.models import (
    SpeechAnalysisRequest,
    SpeechAnalysisResponse,
    TeachingPhaseMatch,
)

FILLER_WORDS = ["然后", "那个", "就是", "这个", "嗯", "啊"]

PHASE_KEYWORDS = {
    "导入": ["导入", "同学们请看", "上课", "创设情境", "回顾上节课", "大家看看大屏幕"],
    "新授": ["自主探究", "小组讨论", "讲解", "请同学们读", "大家齐读", "深入剖析", "新课学习"],
    "巩固": ["巩固练习", "做一做", "课堂练习", "拓展延伸", "角色扮演", "连线", "趁热打铁"],
    "小结": ["课堂小结", "总结", "这节课我们学到了", "谁能说一说收获", "梳理"],
    "作业": ["布置作业", "课后作业", "家庭作业", "回家后", "下节课分享", "必做题和选做题"],
}


class SpeechAnalyzer:
    """Analyzes trial teaching transcript text and duration for pedagogical quality."""

    @classmethod
    def evaluate(cls, req: SpeechAnalysisRequest) -> SpeechAnalysisResponse:
        """Run speech metrics and five-phase instructional coverage checks."""
        text = req.transcript_text.strip()
        dur_sec = max(1.0, req.audio_duration_seconds)
        dur_min = dur_sec / 60.0

        # 1. Words per minute (Chinese characters + English tokens)
        char_count = len(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text))
        wpm = round(char_count / dur_min, 1)

        # Baseline: 200 - 250 wpm (tolerated 180 - 270)
        if wpm < 180.0:
            speed_eval = "too_slow"
            speed_score = 14.0
        elif wpm > 270.0:
            speed_eval = "too_fast"
            speed_score = 15.0
        else:
            speed_eval = "optimal"
            speed_score = 20.0

        # 2. Filler words detection
        filler_counts: Dict[str, int] = {}
        total_fillers = 0
        for f in FILLER_WORDS:
            cnt = len(re.findall(re.escape(f), text))
            if cnt > 0:
                filler_counts[f] = cnt
                total_fillers += cnt

        # Max 20 points for low filler rate
        filler_score = max(5.0, 20.0 - total_fillers * 1.5)

        # 3. Hesitation pauses (>3.0s)
        pauses = req.audio_pauses or []
        hesitations = sum(1 for p in pauses if p >= 3.0)
        hesitation_score = max(5.0, 20.0 - hesitations * 3.0)

        # 4. Five essential teaching phases match
        phase_matches: List[TeachingPhaseMatch] = []
        covered_count = 0

        for phase, keywords in PHASE_KEYWORDS.items():
            matched_kw = None
            for kw in keywords:
                if kw in text:
                    matched_kw = kw
                    break

            if matched_kw:
                covered_count += 1
                idx = text.find(matched_kw)
                snippet = text[max(0, idx - 10) : min(len(text), idx + 25)]
                phase_matches.append(
                    TeachingPhaseMatch(
                        phase_name=phase,  # type: ignore
                        covered=True,
                        evidence_snippet=snippet,
                    )
                )
            else:
                phase_matches.append(
                    TeachingPhaseMatch(
                        phase_name=phase,  # type: ignore
                        covered=False,
                        evidence_snippet="未检测到明确的引导性过渡标志词",
                    )
                )

        phase_coverage_rate = round(covered_count / 5.0, 2)
        # Max 40 points for 5 phases
        phase_score = round(phase_coverage_rate * 40.0, 1)

        # 5. Composite overall score (out of 100)
        overall_score = round(speed_score + filler_score + hesitation_score + phase_score, 1)
        overall_score = max(0.0, min(100.0, overall_score))

        # 6. Actionable feedback
        feedback_parts = []
        if speed_eval == "too_slow":
            feedback_parts.append(f"试讲语速偏慢（{wpm} 字/分），建议适当精炼过渡词，强化课堂生动性与节奏感。")
        elif speed_eval == "too_fast":
            feedback_parts.append(f"试讲语速过快（{wpm} 字/分），易给考官压迫感且不利于学生理解，建议适度留白提问。")
        else:
            feedback_parts.append(f"试讲语速自然从容（{wpm} 字/分），处于考官评判最佳舒适区间。")

        if total_fillers >= 5:
            feedback_parts.append(f"检测到口头禅共计 {total_fillers} 次（高频词: {', '.join(filler_counts.keys())}），建议在环节切换时用沉稳停顿替代口头禅。")

        missing_phases = [pm.phase_name for pm in phase_matches if not pm.covered]
        if missing_phases:
            feedback_parts.append(f"教学五环节中缺少明确的【{'、'.join(missing_phases)}】环节，面试评委重点关注环节完整性，请务必设置清晰标志语。")
        else:
            feedback_parts.append("教学设计五环节（导入、新授、巩固、小结、作业）结构完备，各环节衔接自然顺畅。")

        return SpeechAnalysisResponse(
            words_per_minute=wpm,
            speed_evaluation=speed_eval,
            filler_words_count=filler_counts,
            hesitation_pause_count=hesitations,
            teaching_phases=phase_matches,
            phase_coverage_rate=phase_coverage_rate,
            overall_score=overall_score,
            coaching_feedback=" ".join(feedback_parts),
        )
