"""Trial teaching speech acoustics and discourse structure analyzer.

Everything here is a *measurement of the transcript the caller supplied*: characters per minute,
filler counts, long pauses, and which of the five instructional phases have a marker in the text.
The composite 0-100 score the previous version returned was built from weights invented in this
file (20/20/20/40) and had no counterpart in the library — the 试讲 rubric
(``数据集/教资/rubrics/interview_teaching.json``, 50 分) is unsigned, so per §10 nothing is scored
and ``overall_score`` stays null.
"""
from __future__ import annotations

import re
from typing import Dict, List

from services.common.models import (
    SpeechAnalysisRequest,
    SpeechAnalysisResponse,
    TeachingPhaseMatch,
)

FILLER_WORDS = ["然后", "那个", "就是", "这个", "嗯", "啊"]

# Marker cues only: they say "the transcript appears to contain this phase", not "this phase scores X".
PHASE_KEYWORDS = {
    "导入": ["导入", "同学们请看", "上课", "创设情境", "回顾上节课", "大家看看大屏幕"],
    "新授": ["自主探究", "小组讨论", "讲解", "请同学们读", "大家齐读", "深入剖析", "新课学习"],
    "巩固": ["巩固练习", "做一做", "课堂练习", "拓展延伸", "角色扮演", "连线"],
    "小结": ["课堂小结", "总结", "这节课我们学到了", "谁能说一说收获", "梳理"],
    "作业": ["布置作业", "课后作业", "家庭作业", "回家后", "下节课分享", "必做题和选做题"],
}

NO_TRANSCRIPT = SpeechAnalysisResponse(
    words_per_minute=0.0,
    speed_evaluation="optimal",
    filler_words_count={},
    hesitation_pause_count=0,
    teaching_phases=[],
    phase_coverage_rate=0.0,
    overall_score=None,
    coaching_feedback="未收到转写文本，系统不做任何测算，也不给出印象分。",
    notices=("transcript_text 为空：语速、口头禅与环节覆盖全部不可计算。",),
)

PAUSE_HESITATION_SECONDS = 3.0
COMFORTABLE_WPM = (180.0, 270.0)


class SpeechAnalyzer:
    """Measures speech pacing, hesitation and phase coverage without inventing a score."""

    @classmethod
    def evaluate(cls, req: SpeechAnalysisRequest) -> SpeechAnalysisResponse:
        text = (req.transcript_text or "").strip()
        if not text:
            return NO_TRANSCRIPT

        dur_min = max(1.0, req.audio_duration_seconds) / 60.0
        char_count = len(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text))
        wpm = round(char_count / dur_min, 1)

        low, high = COMFORTABLE_WPM
        if wpm < low:
            speed_eval = "too_slow"
        elif wpm > high:
            speed_eval = "too_fast"
        else:
            speed_eval = "optimal"

        filler_counts: Dict[str, int] = {}
        for filler in FILLER_WORDS:
            count = len(re.findall(re.escape(filler), text))
            if count:
                filler_counts[filler] = count
        total_fillers = sum(filler_counts.values())

        pauses = req.audio_pauses or []
        hesitations = sum(1 for pause in pauses if pause >= PAUSE_HESITATION_SECONDS)

        matches: List[TeachingPhaseMatch] = []
        covered = 0
        for phase, cues in PHASE_KEYWORDS.items():
            cue = next((keyword for keyword in cues if keyword in text), None)
            if cue:
                covered += 1
                index = text.find(cue)
                snippet = text[max(0, index - 10) : index + len(cue) + 15]
                matches.append(
                    TeachingPhaseMatch(phase_name=phase, covered=True, evidence_snippet=snippet)  # type: ignore[arg-type]
                )
            else:
                matches.append(
                    TeachingPhaseMatch(
                        phase_name=phase,  # type: ignore[arg-type]
                        covered=False,
                        evidence_snippet="转写文本内未出现该环节的标志语",
                    )
                )

        return SpeechAnalysisResponse(
            words_per_minute=wpm,
            speed_evaluation=speed_eval,  # type: ignore[arg-type]
            filler_words_count=filler_counts,
            hesitation_pause_count=hesitations,
            teaching_phases=matches,
            phase_coverage_rate=round(covered / len(PHASE_KEYWORDS), 4),
            overall_score=None,
            coaching_feedback=cls._feedback(
                wpm, speed_eval, total_fillers, filler_counts, hesitations, matches, dur_min
            ),
            notices=[
                f"语速/停顿/环节覆盖为对转写文本的直接测算（时长 {round(dur_min, 2)} 分钟），不含任何评分权重。",
                "面试试讲总分需依据 数据集/教资/rubrics/interview_teaching.json（50 分）签署后才能出具。",
            ],
        )

    @staticmethod
    def _feedback(wpm, speed_eval, total_fillers, filler_counts, hesitations, matches, dur_min) -> str:
        parts: List[str] = [
            {
                "too_slow": f"转写测算语速 {wpm} 字/分，低于舒适区间（{COMFORTABLE_WPM[0]:.0f}–{COMFORTABLE_WPM[1]:.0f}）。",
                "too_fast": f"转写测算语速 {wpm} 字/分，高于舒适区间（{COMFORTABLE_WPM[0]:.0f}–{COMFORTABLE_WPM[1]:.0f}）。",
                "optimal": f"转写测算语速 {wpm} 字/分，落在舒适区间（{COMFORTABLE_WPM[0]:.0f}–{COMFORTABLE_WPM[1]:.0f}）。",
            }[speed_eval]
        ]
        if total_fillers:
            parts.append(
                f"口头禅共 {total_fillers} 次（{'、'.join(filler_counts)}），环节切换处可用停顿替代。"
            )
        if hesitations:
            parts.append(f"检测到 {hesitations} 处 ≥{PAUSE_HESITATION_SECONDS:.0f} 秒的停顿。")
        missing = [m.phase_name for m in matches if not m.covered]
        if missing:
            parts.append("标志语未覆盖的环节：" + "、".join(missing) + "。")
        else:
            parts.append("五个环节均检测到标志语，请核对是否与教案设计一致。")
        parts.append(f"以上为 {round(dur_min, 1)} 分钟文本的测算结果，不构成等级或分数。")
        return " ".join(parts)
