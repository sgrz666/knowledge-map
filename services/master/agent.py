"""TutorMasterAgent coordinating student interaction, subagents, and card payloads."""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from services.common.models import (
    MasterInteractionRequest,
    MasterInteractionResponse,
    UserIntent,
)
from services.master.intent_router import IntentRouter


class TutorMasterAgent:
    """Central orchestrating agent managing user session and subagent card dispatches."""

    def __init__(self):
        pass

    def handle_interaction(self, req: MasterInteractionRequest) -> MasterInteractionResponse:
        """Process conversational input, route to appropriate agent, and render card response."""
        session_id = req.session_id or f"sess-{uuid.uuid4().hex[:8]}"
        intent = IntentRouter.classify(req.message, req.action_payload)
        exam = req.exam_type

        # Dispatch according to intent
        if intent == UserIntent.DIAGNOSTIC:
            reply = (
                f"已为你初始化【{exam} 学情摸底诊断流程】。系统将按大纲权重自动抽配 30 道分层自适应试题，"
                "精准测算你的当前预测分区间（CET常模分 / NTCE分段报告分）与五维能力雷达图。"
            )
            card_type = "diagnostic_card"
            card_data = {
                "exam_type": exam,
                "stage": "cold_start",
                "recommended_test_id": f"diag-paper-{exam.lower()}-coldstart",
                "item_count": 30,
                "estimated_minutes": 25,
            }
            quick_replies = ["立即开始30题摸底测验", "跳过直接生成课表", "查看往期诊断记录"]

        elif intent == UserIntent.PLAN:
            reply = (
                f"已为你规划【{exam} 知识图谱自适应学习课表】。基于考纲前驱拓扑关系与 FSRS 记忆周期，"
                "科学拆解每日任务，杜绝盲目低效刷题。"
            )
            card_type = "plan_card"
            card_data = {
                "exam_type": exam,
                "days_until_exam": 30,
                "daily_minutes": 60,
                "recommended_focus": "职业理念与法律法规" if exam == "NTCE" else "高频词汇与仔细阅读",
            }
            quick_replies = ["按30天计划执行", "修改每日可用时长", "查看今日学习任务"]

        elif intent == UserIntent.PRACTICE:
            reply = (
                f"已为你打开【{exam} 刷题与组卷中心】。支持 7 种练习模式（考点专练、薄弱突击、错题消灭、每日一练、高频冲刺、限时快练、真题模考）。"
            )
            card_type = "practice_card"
            card_data = {
                "exam_type": exam,
                "modes": [
                    "point_focus", "weakness_breakthrough", "error_elimination",
                    "daily_practice", "high_frequency", "timed_sprint", "mock_exam"
                ],
            }
            quick_replies = ["开启每日一练", "开启薄弱考点突击", "开启真题全真模考"]

        elif intent == UserIntent.SUBMIT_SUBJECTIVE:
            reply = (
                f"主观题评卷通道已就绪。系统已加载【{'CET 5档整体分档定级' if 'CET' in exam else 'NTCE 4维解析式行为锚定量规'}】。"
                "请在下方提交你的作答文本或材料分析简答。"
            )
            card_type = "grading_card"
            card_data = {
                "exam_type": exam,
                "grading_engine": "holistic_band" if "CET" in exam else "analytic_criteria",
                "supported_tasks": ["短文写作", "段落翻译"] if "CET" in exam else ["材料分析题", "教学设计", "简答题"],
            }
            quick_replies = ["粘贴学生作答提交批改", "查看官方量规采分标准"]

        elif intent == UserIntent.ERROR_REVIEW:
            reply = (
                "已调取你的【FSRS-v4 错题智能回炉库】。系统依据五维教育学归因（审题/概念/盲区/策略/表述）与记忆保留率模型，"
                "精确定位当前处于遗忘临界区的高危错题。"
            )
            card_type = "review_card"
            card_data = {
                "exam_type": exam,
                "due_today_count": 8,
                "critical_retrievability_threshold": 0.90,
            }
            quick_replies = ["立即消灭今日到期错题", "查看五维错因归因图谱", "重做昨日错误题目"]

        elif intent == UserIntent.QA_ASK:
            reply = (
                "循证 RAG 答疑专家已接入。支持【星火三段链深度解析（题眼定位、选项对比、法条溯源）】与【苏格拉底式启发答疑】。"
            )
            card_type = "qa_card"
            card_data = {
                "exam_type": exam,
                "features": ["题眼定位", "干扰项逻辑拆解", "法条/考纲定位戳", "启发式提问引导"],
            }
            quick_replies = ["查看三段链完整解析", "苏格拉底式启发引导我", "查看相关法律原文"]

        elif intent == UserIntent.INTERVIEW_PRACTICE:
            reply = (
                "教资面试仿真试讲教练已启动！支持【10分钟试讲音频特征评估（语速/停顿/口头禅/五环节）】与【20分钟教学设计简案打分】。"
            )
            card_type = "interview_card"
            card_data = {
                "features": ["有效语速计算", "3秒以上迟滞检测", "口头禅统计", "教学五环节覆盖率", "三维目标简案核验"],
            }
            quick_replies = ["开始10分钟模拟试讲", "提交20分钟教学简案", "查看面试61项官方细则"]

        else:
            reply = (
                f"你好！我是你的【{exam} 智能备考全流程总控智能体】。我可以为你提供：\n"
                "1. 📊 30题学情摸底与双轨测验学预测（常模分/报告分）\n"
                "2. 🗓️ 拓扑依赖自适应日历学习课表\n"
                "3. 🎯 7种刷题模式与考务时序模拟卷\n"
                "4. 📝 主观题双模量规智能批改与升格建议\n"
                "5. 🧠 FSRS-v4 错题五维归因与空间间隔回炉\n"
                "6. 💡 循证三段链答疑与苏格拉底式启发教学\n"
                "7. 🎙️ 教资面试仿真试讲与教学简案评测"
            )
            card_type = "text_message"
            card_data = {}
            quick_replies = ["进行学情摸底测验", "生成我的备考计划", "开启今日刷题", "批改主观题"]

        return MasterInteractionResponse(
            session_id=session_id,
            detected_intent=intent,
            reply_text=reply,
            card_type=card_type,  # type: ignore
            card_data=card_data,
            suggested_quick_replies=quick_replies,
        )
