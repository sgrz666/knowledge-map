"""PracticeEngineAgent managing paper generation across 7 modes and timed exam protocols."""
from __future__ import annotations

import uuid
from typing import Dict, List

from services.common.models import (
    AssemblePaperRequest,
    PracticeMode,
    PracticePaperResponse,
)
from services.practice.cet_statemachine import CETExamStateMachine

# Sample curated seed questions representing valid ontology items
SAMPLE_QUESTION_BANK = [
    {
        "question_id": "ntce-item-m1-001",
        "exam_type": "NTCE",
        "module_id": "m1",
        "node_id": "ntce.m1.student_view",
        "stem": "某小学班主任李老师在评定学生操行时，不仅看期末考试成绩，还结合学生平时的课堂表现、作业情况和劳动参与进行多元评价。李老师的做法（ ）。",
        "options": {
            "A": "不恰当，违背了以考试成绩为准绳的原则",
            "B": "恰当，体现了关注学生发展过程的评价理念",
            "C": "不恰当，忽视了终结性评价的客观权威性",
            "D": "恰当，有利于减轻教师的教学管理负担",
        },
        "answer": "B",
        "difficulty": 0.35,
        "mode_fit": ["point_focus", "daily_practice", "mock_exam", "high_frequency"],
    },
    {
        "question_id": "ntce-item-m2-002",
        "exam_type": "NTCE",
        "module_id": "m2",
        "node_id": "ntce.m2.education_law",
        "stem": "根据《中华人民共和国义务教育法》，适龄儿童、少年的父母或者其他法定监护人应当依法保证其按时入学接受并完成义务教育。这体现了义务教育的（ ）。",
        "options": {
            "A": "强制性",
            "B": "免费性",
            "C": "普及性",
            "D": "基础性",
        },
        "answer": "A",
        "difficulty": 0.42,
        "mode_fit": ["point_focus", "daily_practice", "mock_exam", "weakness_breakthrough"],
    },
    {
        "question_id": "ntce-item-m3-003",
        "exam_type": "NTCE",
        "module_id": "m3",
        "node_id": "ntce.m3.ethics_code",
        "stem": "张老师利用课余时间给班上有偿补课，还要求全班同学自愿购买其指定的教辅资料。张老师的行为违反了《中小学教师职业道德规范》中的（ ）。",
        "options": {
            "A": "爱国守法与爱岗敬业",
            "B": "关爱学生与教书育人",
            "C": "廉洁从教与为人师表",
            "D": "严谨治学与终身学习",
        },
        "answer": "C",
        "difficulty": 0.30,
        "mode_fit": ["point_focus", "daily_practice", "mock_exam", "high_frequency", "timed_sprint"],
    },
    {
        "question_id": "cet4-item-read-001",
        "exam_type": "CET-4",
        "module_id": "cet_reading",
        "node_id": "cet4.reading.careful",
        "stem": "Which of the following is most likely true according to the passage regarding autonomous vehicles?",
        "options": {
            "A": "They completely eliminate all urban traffic congestion.",
            "B": "They raise significant legal and ethical concerns regarding liability.",
            "C": "They are already universally adopted worldwide.",
            "D": "They require more fossil fuel consumption than conventional cars.",
        },
        "answer": "B",
        "difficulty": 0.55,
        "mode_fit": ["point_focus", "daily_practice", "mock_exam", "timed_sprint"],
    },
]


class PracticeEngineAgent:
    """Agent assembling tailored question sets across 7 practice modalities."""

    def __init__(self):
        pass

    def assemble_paper(self, req: AssemblePaperRequest) -> PracticePaperResponse:
        """Assemble practice paper matching user mode, exam type, and target scope."""
        mode = req.practice_mode
        exam = req.exam_type

        # 1. Filter bank matching exam
        candidates = [q for q in SAMPLE_QUESTION_BANK if q["exam_type"] == exam]
        if not candidates:
            # Fallback if specific exam pool is empty in mock sample
            candidates = SAMPLE_QUESTION_BANK

        # 2. Filter by target scope if specified
        if req.target_node:
            matched = [q for q in candidates if q.get("node_id") == req.target_node]
            if matched:
                candidates = matched
        elif req.target_module:
            matched = [q for q in candidates if q.get("module_id") == req.target_module]
            if matched:
                candidates = matched

        # 3. Mode-specific selection
        selected_questions = candidates[:req.item_count]

        # 4. Mode-specific titles and time limits
        mode_titles = {
            PracticeMode.POINT_FOCUS: f"【考点专练】{req.target_node or '重点考点'} 强化训练",
            PracticeMode.WEAKNESS_BREAKTHROUGH: "【薄弱突击】AI 诊断薄弱考点专项歼灭",
            PracticeMode.ERROR_ELIMINATION: "【错题消灭】FSRS 记忆衰减错题重做",
            PracticeMode.DAILY_PRACTICE: "【每日一练】考点精选通关每日打卡",
            PracticeMode.HIGH_FREQUENCY: "【高频冲刺】历年真题高频核心考点集训",
            PracticeMode.TIMED_SPRINT: "【限时快练】考场极限答题节奏冲刺",
            PracticeMode.MOCK_EXAM: f"【全真模考】{exam} 官方考务时序模拟卷",
        }
        title = mode_titles.get(mode, f"【专项练习】{exam} 练习试卷")

        time_limits = {
            PracticeMode.TIMED_SPRINT: 15,
            PracticeMode.MOCK_EXAM: 130 if "CET" in exam else 120,
            PracticeMode.DAILY_PRACTICE: 20,
        }
        limit_mins = time_limits.get(mode, 30)

        # 5. CET Mock Exam gets official 3-stage timed state machine
        stage_state = None
        if mode == PracticeMode.MOCK_EXAM and "CET" in exam:
            stage_state = CETExamStateMachine.get_initial_state()

        paper_id = f"paper-{exam.lower()}-{mode.value[:4]}-{uuid.uuid4().hex[:6]}"

        return PracticePaperResponse(
            paper_id=paper_id,
            title=title,
            exam_type=exam,
            practice_mode=mode,
            questions=selected_questions,
            total_items=len(selected_questions),
            time_limit_minutes=limit_mins,
            stage_state=stage_state,
        )
