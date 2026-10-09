"""Comprehensive test suite for newly designed agents: Diagnostic, Planner, Practice, QA, Interview, Master."""
import unittest
from starlette.testclient import TestClient

from services.app import app
from services.common.models import (
    AnswerSubmission,
    AssemblePaperRequest,
    DiagnosticRequest,
    LessonPlanReviewRequest,
    MasterInteractionRequest,
    PlanRequest,
    PracticeMode,
    QARequest,
    SpeechAnalysisRequest,
    UserIntent,
)
from services.diagnostic.agent import DiagnosticAgent
from services.diagnostic.score_converter import ScoreConverter
from services.interview.agent import InterviewCoachAgent
from services.master.agent import TutorMasterAgent
from services.planner.agent import CurriculumPlannerAgent
from services.practice.agent import PracticeEngineAgent
from services.practice.cet_statemachine import CETExamStateMachine
from services.qa.agent import TutorQAAgent


class TestAllNewAgentModules(unittest.TestCase):
    def setUp(self):
        self.diagnostic_agent = DiagnosticAgent()
        self.planner_agent = CurriculumPlannerAgent()
        self.practice_agent = PracticeEngineAgent()
        self.qa_agent = TutorQAAgent()
        self.interview_agent = InterviewCoachAgent()
        self.master_agent = TutorMasterAgent()
        self.client = TestClient(app)

    # -----------------------------------------------------------------------
    # 1. Diagnostic Agent & Score Conversion Tests
    # -----------------------------------------------------------------------
    def test_score_converter_mathematical_properties(self):
        # CET Norm score test: raw 55/100 -> ~500, pass prob ~0.50
        point_est, interval, pass_prob = ScoreConverter.cet_norm_conversion(55.0, 100.0)
        self.assertGreaterEqual(point_est, 480.0)
        self.assertLessEqual(point_est, 520.0)
        self.assertEqual(len(interval), 2)
        self.assertLessEqual(interval[0], point_est)
        self.assertGreaterEqual(interval[1], point_est)

        # NTCE Piecewise score test:
        # At pass cutoff 90 -> exact 70.0 reporting score
        rep_pass, _, prob_pass = ScoreConverter.ntce_piecewise_conversion(90.0, 90.0, 150.0)
        self.assertEqual(rep_pass, 70.0)
        self.assertAlmostEqual(prob_pass, 0.50, delta=0.05)

        # Below cutoff (e.g. 45/90 -> 35.0)
        rep_low, _, _ = ScoreConverter.ntce_piecewise_conversion(45.0, 90.0, 150.0)
        self.assertEqual(rep_low, 35.0)

        # Perfect score 150 -> 120.0
        rep_perf, _, _ = ScoreConverter.ntce_piecewise_conversion(150.0, 90.0, 150.0)
        self.assertEqual(rep_perf, 120.0)

    def test_diagnostic_agent_report_generation(self):
        subs = [
            AnswerSubmission(
                question_id="q1", user_answer="A", is_correct=True, time_spent_seconds=15.0,
                node_id="ntce.m1.k01", module_id="m1"
            ),
            AnswerSubmission(
                question_id="q2", user_answer="B", is_correct=False, time_spent_seconds=20.0,
                node_id="ntce.m2.k02", module_id="m2"
            ),
            AnswerSubmission(
                question_id="q3", user_answer="C", is_correct=False, time_spent_seconds=25.0,
                node_id="ntce.m2.k02", module_id="m2"
            ),
        ]
        req = DiagnosticRequest(
            user_id="user_test_diag",
            exam_type="NTCE",
            stage="cold_start",
            submissions=subs,
        )
        report = self.diagnostic_agent.evaluate(req)
        self.assertEqual(report.user_id, "user_test_diag")
        self.assertGreater(len(report.radar_chart), 0)
        self.assertIn("ntce.m2.k02", report.weak_points_top5)
        self.assertGreater(len(report.recommended_actions), 0)

    # -----------------------------------------------------------------------
    # 2. Curriculum Planner Agent Tests
    # -----------------------------------------------------------------------
    def test_curriculum_planner_generation(self):
        req = PlanRequest(
            user_id="user_plan_01",
            exam_type="NTCE",
            target_score=70.0,
            days_until_exam=14,
            daily_available_minutes=60,
        )
        plan_resp = self.planner_agent.generate_plan(req)
        self.assertEqual(plan_resp.total_days, 14)
        self.assertEqual(len(plan_resp.daily_plans), 14)
        self.assertGreaterEqual(len(plan_resp.milestones), 2)

        # Check day 7 milestone is mock sprint
        day7 = plan_resp.daily_plans[6]
        task_types = [t.task_type for t in day7.tasks]
        self.assertIn("mock_sprint", task_types)

        # Regular day has fsrs_review and new_node_learning
        day1 = plan_resp.daily_plans[0]
        task_types_d1 = [t.task_type for t in day1.tasks]
        self.assertIn("fsrs_review", task_types_d1)
        self.assertIn("new_node_learning", task_types_d1)

    # -----------------------------------------------------------------------
    # 3. Practice Engine & CET 3-Stage State Machine Tests
    # -----------------------------------------------------------------------
    def test_practice_engine_modes_and_cet_statemachine(self):
        # 1. 7 Practice modes assembly
        for mode in [
            PracticeMode.POINT_FOCUS,
            PracticeMode.WEAKNESS_BREAKTHROUGH,
            PracticeMode.ERROR_ELIMINATION,
            PracticeMode.DAILY_PRACTICE,
            PracticeMode.HIGH_FREQUENCY,
            PracticeMode.TIMED_SPRINT,
            PracticeMode.MOCK_EXAM,
        ]:
            req = AssemblePaperRequest(
                user_id="user_prac_01",
                exam_type="NTCE",
                practice_mode=mode,
                item_count=5,
            )
            resp = self.practice_agent.assemble_paper(req)
            self.assertEqual(resp.practice_mode, mode)
            self.assertGreater(resp.total_items, 0)

        # 2. CET 3-Stage Timed State Machine
        init_state = CETExamStateMachine.get_initial_state()
        self.assertEqual(init_state.stage, "writing")
        self.assertFalse(init_state.input_locked)
        self.assertFalse(init_state.sheet_collected)

        # Advance 1800s -> Stage 2: listening
        state_listen = CETExamStateMachine.step_stage(init_state, elapsed_seconds=1800)
        self.assertEqual(state_listen.stage, "listening")

        # Advance 1800s -> Stage 3: reading_translation & Collect Sheet 1
        state_reading = CETExamStateMachine.step_stage(state_listen, elapsed_seconds=1800)
        self.assertEqual(state_reading.stage, "reading_translation")
        self.assertTrue(state_reading.sheet_collected)

        # Advance 4200s -> Completed
        state_comp = CETExamStateMachine.step_stage(state_reading, elapsed_seconds=4200)
        self.assertEqual(state_comp.stage, "completed")
        self.assertTrue(state_comp.input_locked)

    # -----------------------------------------------------------------------
    # 4. Tutor QA Agent Tests (Sparks 3-Chain & Socratic)
    # -----------------------------------------------------------------------
    def test_tutor_qa_sparks_and_socratic(self):
        # Sparks 3-Chain
        req_sparks = QARequest(
            user_id="u_qa",
            question_id="ntce-item-m1-001",
            user_selected_option="A",
            mode="sparks_three_chain",
        )
        resp_sparks = self.qa_agent.answer_query(req_sparks)
        self.assertIn("题眼定位", resp_sparks.key_clue_localization)
        self.assertIn("考生所选[A]错因诊断", resp_sparks.option_discrimination)
        self.assertIn("source", resp_sparks.knowledge_provenance)

        # Socratic Hint Turn 1 -> progressive question, no answer reveal
        req_soc1 = QARequest(
            user_id="u_qa",
            question_id="ntce-item-m1-001",
            mode="socratic_hint",
            hint_turn=1,
        )
        resp_soc1 = self.qa_agent.answer_query(req_soc1)
        self.assertFalse(resp_soc1.is_final_reveal)
        self.assertIsNone(resp_soc1.revealed_answer)

        # Socratic Hint Turn 3 -> reveals answer
        req_soc3 = QARequest(
            user_id="u_qa",
            question_id="ntce-item-m1-001",
            mode="socratic_hint",
            hint_turn=3,
        )
        resp_soc3 = self.qa_agent.answer_query(req_soc3)
        self.assertTrue(resp_soc3.is_final_reveal)
        self.assertEqual(resp_soc3.revealed_answer, "B")

    # -----------------------------------------------------------------------
    # 5. Interview Coach Agent Tests (Speech & Lesson Plan)
    # -----------------------------------------------------------------------
    def test_interview_coach_speech_and_lesson_plan(self):
        # Speech analysis with 5 phases
        transcript = (
            "同学们好，请看大屏幕，创设情境导入新课。今天我们深入剖析自主探究新知识。"
            "接下来大家来做一做课堂练习巩固。最后请哪位同学来做课堂小结梳理收获？"
            "今天的课后作业是完成课后探究题。"
        )
        req_speech = SpeechAnalysisRequest(
            transcript_text=transcript,
            audio_duration_seconds=30.0,
            audio_pauses=[1.0, 1.2],
        )
        resp_speech = self.interview_agent.analyze_speech(req_speech)
        self.assertEqual(resp_speech.phase_coverage_rate, 1.0)
        self.assertGreaterEqual(resp_speech.overall_score, 80.0)

        # Lesson plan review
        plan_text = (
            "一、教学目标：知识与技能、过程与方法、情感态度价值观三维目标完整。\n"
            "二、教学重点与难点：重点是理解课文主旨，难点是探究表现手法。\n"
            "三、教学过程：导入、新课讲授、探究互动、练习巩固、总结作业。\n"
            "四、板书设计：提纲式板书。"
        )
        req_plan = LessonPlanReviewRequest(
            topic="古诗鉴赏",
            plan_text=plan_text,
        )
        resp_plan = self.interview_agent.review_lesson_plan(req_plan)
        self.assertGreaterEqual(resp_plan.total_score, 30.0)
        self.assertEqual(len(resp_plan.missed_elements), 0)

    # -----------------------------------------------------------------------
    # 6. Tutor Master Agent & Router Tests
    # -----------------------------------------------------------------------
    def test_tutor_master_agent_dispatching(self):
        intents_map = [
            ("我想进行一次水平测验查漏补缺", UserIntent.DIAGNOSTIC, "diagnostic_card"),
            ("帮我制定30天备考计划课表", UserIntent.PLAN, "plan_card"),
            ("我要开始做题刷题练习", UserIntent.PRACTICE, "practice_card"),
            ("请帮我批改一下我的材料分析主观题答案", UserIntent.SUBMIT_SUBJECTIVE, "grading_card"),
            ("查看我今天到期的错题本和FSRS复习包", UserIntent.ERROR_REVIEW, "review_card"),
            ("这道题我选了A，请问为什么选B，讲讲这题解析", UserIntent.QA_ASK, "qa_card"),
            ("我想练一下教资面试试讲和简案教学设计", UserIntent.INTERVIEW_PRACTICE, "interview_card"),
            ("你好，你是谁？", UserIntent.GENERAL_CHAT, "text_message"),
        ]
        for msg, expected_intent, expected_card in intents_map:
            req = MasterInteractionRequest(
                user_id="user_master_test",
                message=msg,
                exam_type="NTCE",
            )
            resp = self.master_agent.handle_interaction(req)
            self.assertEqual(resp.detected_intent, expected_intent)
            self.assertEqual(resp.card_type, expected_card)
            self.assertGreater(len(resp.suggested_quick_replies), 0)

    # -----------------------------------------------------------------------
    # 7. FastAPI HTTP Endpoints Integration Tests
    # -----------------------------------------------------------------------
    def test_fastapi_endpoints_across_all_agents(self):
        # Health endpoint
        resp_h = self.client.get("/api/v1/health")
        self.assertEqual(resp_h.status_code, 200)
        self.assertIn("TutorMasterAgent", resp_h.json()["agents_ready"])
        self.assertIn("DiagnosticAgent", resp_h.json()["agents_ready"])

        # Master chat endpoint
        resp_chat = self.client.post("/api/v1/master/chat", json={
            "user_id": "u_api_master",
            "message": "我要进行摸底测验",
            "exam_type": "NTCE",
        })
        self.assertEqual(resp_chat.status_code, 200)
        self.assertEqual(resp_chat.json()["card_type"], "diagnostic_card")

        # Diagnostic evaluate endpoint
        resp_diag = self.client.post("/api/v1/diagnostic/evaluate", json={
            "user_id": "u_api_diag",
            "exam_type": "CET-4",
            "stage": "cold_start",
        })
        self.assertEqual(resp_diag.status_code, 200)
        self.assertEqual(resp_diag.json()["exam_type"], "CET-4")

        # Planner generate endpoint
        resp_plan = self.client.post("/api/v1/planner/generate", json={
            "user_id": "u_api_plan",
            "exam_type": "NTCE",
            "days_until_exam": 7,
            "daily_available_minutes": 45,
        })
        self.assertEqual(resp_plan.status_code, 200)
        self.assertEqual(len(resp_plan.json()["daily_plans"]), 7)

        # Practice assemble endpoint
        resp_prac = self.client.post("/api/v1/practice/assemble", json={
            "user_id": "u_api_prac",
            "exam_type": "NTCE",
            "practice_mode": "mock_exam",
            "item_count": 3,
        })
        self.assertEqual(resp_prac.status_code, 200)
        self.assertGreater(resp_prac.json()["total_items"], 0)

        # QA query endpoint
        resp_qa = self.client.post("/api/v1/qa/query", json={
            "user_id": "u_api_qa",
            "question_id": "ntce-item-m1-001",
            "mode": "sparks_three_chain",
        })
        self.assertEqual(resp_qa.status_code, 200)
        self.assertIn("key_clue_localization", resp_qa.json())

        # Interview speech endpoint
        resp_speech = self.client.post("/api/v1/interview/speech", json={
            "transcript_text": "同学们好，今天我们通过创设情境导入新课。然后进入自主探究新知。接下来进行巩固练习与课堂小结。课后作业是探究思考题。",
            "audio_duration_seconds": 25.0,
        })
        self.assertEqual(resp_speech.status_code, 200)
        self.assertGreater(resp_speech.json()["overall_score"], 0.0)
