"""Intent routing for the master agent.

Two exits, in this order:

1. an explicit ``intent`` in the action payload always wins (the frontend already know what the
   button it pressed meant);
2. otherwise match the utterance against keyword groups, and only fall back to *payload shape*
   when the utterance carries no signal at all.

The keyword groups are ordered by specificity rather than alphabetically: "批改我错题本里的作文"
is a submission, not an error-review request, and "这道题为什么错了" is a question, not a plan.
Payload-shape inference exists because learners paste an answer without saying much; guessing an
intent from ``answer_text`` is still honest, since the graded result is gated by TrustGate anyway.
"""
from __future__ import annotations

from services.common.models import UserIntent

# Ordered: the first group whose keyword appears in the utterance wins.
INTENT_KEYWORDS = [
    (
        UserIntent.SUBMIT_SUBJECTIVE,
        [
            "批改", "评分", "打分", "给我分", "看看我写的", "我写的答案", "我的答案如", "答案如下",
            "作文批改", "翻译评分", "主观题评分", "帮我改这篇", "检查一下我的作答",
        ],
    ),
    (
        UserIntent.INTERVIEW_PRACTICE,
        ["面试", "试讲", "答辩", "简案", "教案", "教学设计", "结构化问答", "口头禅", "说课", "板书"],
    ),
    (
        UserIntent.DIAGNOSTIC,
        ["摸底", "诊断", "评测", "测评", "水平测验", "我的水平", "查漏补缺", "学情", "查缺补漏", "先测我"],
    ),
    (
        UserIntent.QA_ASK,
        ["为什么选", "为什么是", "为何选", "讲讲这道题", "这题解析", "解析一下", "答疑", "苏格拉底",
         "我不理解", "没懂", "是什么意思", "怎么理解", "为什么", "什么是"],
    ),
    (
        UserIntent.ERROR_REVIEW,
        ["错题", "归因", "错了", "做错", "答错", "为什么错", "失分", "回炉", "遗忘复习",
         "fsrs", "错题本"],
    ),
    (
        UserIntent.PLAN,
        ["计划", "规划", "备考路线", "排课", "课表", "日历", "备考时间", "安排", "时间表", "多少天",
         "倒计时", "怎么复习才"],
    ),
    (
        UserIntent.PRACTICE,
        ["刷题", "练习", "做题", "组卷", "模考", "模拟卷", "全真", "考点专练", "每日一练", "今日练习",
         "来几道题", "做题"],
    ),
]


class IntentRouter:
    """Classifies user intent from a natural-language utterance or an action payload."""

    @staticmethod
    def classify(message: str, action_payload: dict | None = None) -> UserIntent:
        payload = dict(action_payload or {})
        explicit = str(payload.get("intent") or "")
        if explicit:
            try:
                return UserIntent(explicit)
            except ValueError:
                pass  # an unknown label is not a reason to fabricate an intent

        text = (message or "").lower()
        for intent, keywords in INTENT_KEYWORDS:
            if any(keyword.lower() in text for keyword in keywords):
                return intent

        return IntentRouter._from_payload(text, payload)

    @staticmethod
    def _from_payload(text: str, payload: dict) -> UserIntent:
        """No keyword matched: infer only from payload *shape*, never from message vibes."""
        if payload.get("plan_text") or payload.get("transcript_text"):
            return UserIntent.INTERVIEW_PRACTICE
        if payload.get("answer_text") or payload.get("student_answer"):
            return UserIntent.SUBMIT_SUBJECTIVE
        if payload.get("is_correct") is not None and payload.get("question_id"):
            return UserIntent.ERROR_REVIEW
        if payload.get("question_id"):
            return UserIntent.QA_ASK
        if any(word in text for word in ("练", "题", "卷")):
            return UserIntent.PRACTICE
        return UserIntent.GENERAL_CHAT
