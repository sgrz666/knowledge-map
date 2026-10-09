"""Heuristic and Semantic Intent Router for student dialogue."""
from __future__ import annotations

from services.common.models import UserIntent

INTENT_KEYWORDS = [
    (UserIntent.DIAGNOSTIC, ["评测", "摸底", "诊断", "水平测验", "我的水平", "摸底考", "查漏补缺"]),
    (UserIntent.PLAN, ["学习计划", "规划", "备考路线", "排课", "课表", "日历", "备考时间"]),
    (UserIntent.PRACTICE, ["刷题", "练习", "做题", "考点专练", "全真模考", "模拟卷", "开始练习"]),
    (UserIntent.SUBMIT_SUBJECTIVE, ["批改", "作文批改", "翻译评分", "材料分析打分", "我的作文", "主观题评分"]),
    (UserIntent.ERROR_REVIEW, ["错题", "错题本", "复习", "回炉", "遗忘复习", "FSRS"]),
    (UserIntent.QA_ASK, ["为什么选", "讲讲这道题", "这题解析", "答疑", "苏格拉底", "我不理解"]),
    (UserIntent.INTERVIEW_PRACTICE, ["面试", "试讲", "试讲演练", "简案", "教学设计", "口头禅"]),
]


class IntentRouter:
    """Classifies user intent from natural language utterance or action payload."""

    @staticmethod
    def classify(message: str, action_payload: dict | None = None) -> UserIntent:
        """Route message to appropriate user intent."""
        if action_payload and "intent" in action_payload:
            try:
                return UserIntent(action_payload["intent"])
            except ValueError:
                pass

        msg_lower = message.lower()
        for intent, kw_list in INTENT_KEYWORDS:
            for kw in kw_list:
                if kw in msg_lower:
                    return intent

        return UserIntent.GENERAL_CHAT
