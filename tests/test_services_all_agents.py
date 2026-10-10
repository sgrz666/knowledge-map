"""能力层（D 层）回归测试：诊断、规划、组卷、答疑、面试与总控。

The rule every test here follows: an assertion compares against either the library entity
(``数据集/**`` through ``KnowledgeRepository``) or a measurement of the text the caller supplied.
Nothing asserts an invented number, because an invented number is exactly what this layer used to
ship — a 0-100 试讲 composite from weights written in the service, a 40 分 lesson-plan total from a
second copy of the rubric, an IRT 报道分 from a probit in ``score_converter``, and a calendar that
promised a 90-minute mock on a 60-minute day.
"""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest

# Learner state must never leak into the repository's .local_state/ during tests.
os.environ.setdefault("KNOWLEDGE_MAP_STATE_DIR", tempfile.mkdtemp(prefix="km_test_state_"))

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
    TrustTier,
    UserIntent,
)
from services.diagnostic.agent import DiagnosticAgent
from services.interview.agent import InterviewCoachAgent
from services.knowledge.repository import get_repository
from services.knowledge.trust import COPYRIGHT_NOTICE, answer_letter
from services.master.agent import TutorMasterAgent
from services.memory.store import InMemoryMasteryStore
from services.planner.agent import CurriculumPlannerAgent
from services.practice.agent import PracticeEngineAgent
from services.practice.cet_statemachine import CETExamStateMachine
from services.qa.agent import TutorQAAgent
from services.review.queue import ReviewQueue


class LibraryBackedTestCase(unittest.TestCase):
    """Shares one index and picks its ids out of the library instead of naming them by hand."""

    @classmethod
    def setUpClass(cls):
        cls.repository = get_repository()
        cls.choice_ids = []
        for meta in cls.repository.find_questions(
            exams=("NTCE",), answer_statuses=("letter_only",), require_nodes=True
        ):
            if meta.review_status != "quarantined":
                cls.choice_ids.append(meta.question_id)
                if len(cls.choice_ids) == 2:
                    break
        cls.sample_question_id = cls.choice_ids[0]
        cls.sample_node_id = cls.repository.get_meta(cls.sample_question_id).node_ids[0]
        cls.sample_record = cls.repository.load_question(cls.sample_question_id)


# --------------------------------------------------------------------------- 1. 诊断
class TestDiagnosticAgent(LibraryBackedTestCase):
    def setUp(self):
        self.agent = DiagnosticAgent(repository=self.repository)

    def _key(self, question_id: str) -> str:
        record = self.repository.load_question(question_id) or {}
        return answer_letter((record.get("content") or {}).get("answer")) or "A"

    def _other_letter(self, question_id: str) -> str:
        return next(ch for ch in "ABCD" if ch != self._key(question_id))

    def _submission(self, question_id: str, **kw):
        base = {
            "question_id": question_id,
            "user_answer": self._key(question_id),
            "time_spent_seconds": 15.0,
            "node_id": self.repository.get_meta(question_id).node_ids[0],
            "module_id": self.repository.get_meta(question_id).module or "m1",
        }
        base.update(kw)
        return AnswerSubmission(**base)

    def _submissions(self):
        """一条按库内答案键选对、一条按同一把键选错：对错由库说了算，不是测试自己声明。"""
        return [
            self._submission(self.choice_ids[0]),
            self._submission(self.choice_ids[1], user_answer=self._other_letter(self.choice_ids[1])),
        ]

    def test_report_is_coverage_only_and_never_reports_a_scaled_score(self):
        report = self.agent.evaluate(
            DiagnosticRequest(user_id="u_diag", exam_type="NTCE", stage="cold_start",
                              submissions=self._submissions())
        )
        self.assertEqual(report.raw_score, 1.0)
        self.assertEqual(report.max_raw_score, 2.0)
        # §10：没有 IRT/CAT 校准，所以这三个字段必须一直是空，而不是一个看起来像分的数。
        self.assertIsNone(report.point_estimate)
        self.assertIsNone(report.predicted_score_interval)
        self.assertIsNone(report.pass_probability)
        self.assertEqual(report.estimate_basis, "coverage_only")
        self.assertFalse(report.publishable)
        self.assertTrue(any("heuristic" in n for n in report.notices))
        # 两条都是库内答案键核对出来的，没有一条靠申报。
        self.assertFalse(any("采信了调用方申报" in n for n in report.notices))

        # 模块与考点来自索引，不来自请求里自称的 node_id。
        wrong_meta = self.repository.get_meta(self.choice_ids[1])
        self.assertTrue(wrong_meta.node_ids)
        self.assertTrue(any(node in report.weak_points_top5 for node in wrong_meta.node_ids),
                        "答错的考点必须出现在薄弱点里")
        index_modules = {self.repository.get_meta(qid).module for qid in self.choice_ids}
        self.assertTrue({r.module_id for r in report.radar_chart}.issubset(index_modules),
                        "雷达图的模块必须来自索引")
        self.assertTrue(report.recommended_actions)

    def test_a_claimed_correct_never_outweighs_the_library_answer_key(self):
        """申报排在答案键前面时，谁都能报一次"对"把雷达刷满。"""
        report = self.agent.evaluate(
            DiagnosticRequest(
                user_id="u_diag",
                exam_type="NTCE",
                submissions=[
                    self._submission(qid, user_answer=self._other_letter(qid), is_correct=True)
                    for qid in self.choice_ids
                ],
            )
        )
        self.assertEqual(report.max_raw_score, 2.0)
        self.assertEqual(report.raw_score, 0.0)
        self.assertTrue(any("与库内答案键的核对结果相反" in n for n in report.notices))
        self.assertTrue(all(row.mastery_rate == 0.0 for row in report.radar_chart))

    def test_a_claim_the_library_cannot_check_is_counted_but_labelled(self):
        report = self.agent.evaluate(
            DiagnosticRequest(
                user_id="u_diag",
                exam_type="NTCE",
                submissions=[self._submission(self.choice_ids[0], user_answer="", is_correct=True)],
            )
        )
        self.assertEqual(report.raw_score, 1.0)
        self.assertTrue(any("采信了调用方申报" in n and "未独立核验" in n for n in report.notices))

    def test_a_submission_with_no_basis_at_all_is_not_scored_as_wrong(self):
        """既没有可核对的所选选项也没有申报：这条作答什么都没说，不能替它编一个 0 分。"""
        report = self.agent.evaluate(
            DiagnosticRequest(
                user_id="u_diag",
                exam_type="NTCE",
                submissions=[self._submission(self.choice_ids[0], user_answer="", is_correct=None)],
            )
        )
        self.assertEqual(report.raw_score, 0.0)
        self.assertEqual(report.max_raw_score, 0.0)
        self.assertEqual(report.radar_chart, [])
        self.assertEqual(report.blocked_submissions[0]["question_id"], self.choice_ids[0])
        self.assertTrue(any("判据" in n for n in report.notices))

    def test_submissions_outside_the_index_are_reported_not_quietly_dropped(self):
        ghost = AnswerSubmission(
            question_id="ntce-item-m1-001", user_answer="A", is_correct=True,
            time_spent_seconds=10.0, node_id=self.sample_node_id, module_id="m1",
        )
        report = self.agent.evaluate(
            DiagnosticRequest(user_id="u_diag", exam_type="NTCE", submissions=[ghost])
        )
        self.assertEqual(report.raw_score, 0.0)
        self.assertEqual(report.max_raw_score, 0.0)
        self.assertEqual(
            [row["question_id"] for row in report.blocked_submissions], ["ntce-item-m1-001"]
        )
        self.assertTrue(report.blocked_submissions[0]["reason"])
        self.assertTrue(any("未计入诊断" in n for n in report.notices))

    def test_published_tier_refuses_because_the_signed_pool_is_empty(self):
        report = self.agent.evaluate(
            DiagnosticRequest(user_id="u_diag", exam_type="NTCE",
                              submissions=self._submissions(), trust_tier=TrustTier.PUBLISHED)
        )
        self.assertEqual(report.radar_chart, [])
        self.assertFalse(report.publishable)
        self.assertTrue(any("已签署" in n for n in report.notices))

    def test_no_scale_conversion_surface_remains(self):
        # §10 明确不做：报道分 / 量表分 / 通过率换算没有入口。
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("services.diagnostic.score_converter")
        self.assertFalse(hasattr(importlib.import_module("services.diagnostic"), "ScoreConverter"))


# --------------------------------------------------------------------------- 2. 备考日历
class TestCurriculumPlanner(LibraryBackedTestCase):
    def setUp(self):
        self.store = InMemoryMasteryStore()
        self.agent = CurriculumPlannerAgent(repository=self.repository, store=self.store)

    def _plan(self, user_id, days, minutes):
        return self.agent.generate_plan(
            PlanRequest(user_id=user_id, exam_type="NTCE", days_until_exam=days,
                        daily_available_minutes=minutes)
        )

    def test_a_day_only_holds_what_a_day_can_fit(self):
        plan = self._plan("u_plan_60", 14, 60)
        self.assertEqual(plan.total_days, 14)
        self.assertEqual(len(plan.daily_plans), 14)
        for day in plan.daily_plans:
            self.assertLessEqual(sum(t.estimated_minutes for t in day.tasks), 60)
        # 90 分钟的模考塞不进 60 分钟的一天：日历不许承诺它做不到事。
        self.assertFalse(
            any(t.task_type == "mock_sprint" for day in plan.daily_plans for t in day.tasks)
        )

    def test_mock_sprint_appears_only_on_a_day_big_enough_for_it(self):
        plan = self._plan("u_plan_120", 14, 120)
        for index in (6, 13):
            types = [t.task_type for t in plan.daily_plans[index].tasks]
            self.assertIn("mock_sprint", types, f"第 {index + 1} 天应有模考")
            self.assertLessEqual(sum(t.estimated_minutes for t in plan.daily_plans[index].tasks), 120)

    def test_review_tasks_come_from_the_learners_own_due_items(self):
        # 没有作答记录就没有到期项，也就没有复习任务 —— 而不是凭空排一轮"FSRS 复习"。
        fresh = self._plan("u_new", 3, 60)
        self.assertFalse(
            any(t.task_type == "fsrs_review" for day in fresh.daily_plans for t in day.tasks)
        )

        self.store.log_error({
            "user_id": "u_returning", "question_id": self.sample_question_id,
            "node_id": self.sample_node_id, "exam": "NTCE", "error_category": "concept_lapse",
            "incorrect_count": 1, "due_at": "2000-01-01T00:00:00+00:00",
        })
        again = self._plan("u_returning", 3, 60)
        review_tasks = [
            t for day in again.daily_plans for t in day.tasks if t.task_type == "fsrs_review"
        ]
        self.assertTrue(review_tasks)
        self.assertEqual(review_tasks[0].target_question_count, 1)

    def test_milestones_are_read_back_out_of_the_calendar(self):
        plan = self._plan("u_plan_ms", 14, 120)
        self.assertTrue(plan.milestones)
        joined = " ".join(plan.milestones)
        self.assertTrue(any(word in joined for word in ("模考", "考点", "新考点", "覆盖")), joined)


# --------------------------------------------------------------------------- 3. 组卷
class TestPracticeEngine(LibraryBackedTestCase):
    def setUp(self):
        self.agent = PracticeEngineAgent(repository=self.repository)

    def test_every_mode_draws_from_the_real_library(self):
        cases = {
            PracticeMode.POINT_FOCUS: {"target_node": self.sample_node_id},
            PracticeMode.WEAKNESS_BREAKTHROUGH: {"weak_node_ids": [self.sample_node_id]},
            PracticeMode.ERROR_ELIMINATION: {"wrong_question_ids": [self.sample_question_id]},
            PracticeMode.DAILY_PRACTICE: {},
            PracticeMode.HIGH_FREQUENCY: {},
            PracticeMode.TIMED_SPRINT: {},
        }
        for mode, extra in cases.items():
            resp = self.agent.assemble_paper(
                AssemblePaperRequest(user_id="u_prac", exam_type="NTCE", practice_mode=mode,
                                     item_count=5, **extra)
            )
            with self.subTest(mode=mode.value):
                self.assertEqual(resp.practice_mode, mode)
                self.assertGreater(resp.total_items, 0)
                self.assertGreater(resp.pool_size, 1000)
                for payload in resp.questions:
                    self.assertIsNotNone(self.repository.get_meta(payload["question_id"]),
                                         "组卷只能出真库内的 question_id")
                    self.assertTrue(payload["stem"])
                    self.assertEqual(payload["difficulty"]["calibration"], "heuristic")
                self.assertIn(COPYRIGHT_NOTICE, resp.notices)

    def test_mock_paper_follows_the_official_blueprint(self):
        mock = self.agent.assemble_paper(
            AssemblePaperRequest(user_id="u_prac", exam_type="NTCE",
                                 practice_mode=PracticeMode.MOCK_EXAM, item_count=200,
                                 school_level="xiaoxue", subject="zonghe")
        )
        self.assertTrue(mock.spec_id)
        self.assertEqual(mock.time_limit_minutes, 120)
        self.assertTrue(all(s["issued_count"] <= s["planned_count"] for s in mock.structure))
        self.assertEqual([s["name"] for s in mock.structure], ["单项选择题", "材料分析题", "写作题"])

    def test_published_tier_is_an_empty_set_by_design(self):
        gated = self.agent.assemble_paper(
            AssemblePaperRequest(user_id="u_prac", exam_type="NTCE",
                                 practice_mode=PracticeMode.DAILY_PRACTICE, item_count=5,
                                 trust_tier=TrustTier.PUBLISHED)
        )
        self.assertEqual((gated.total_items, gated.pool_size), (0, 0))
        self.assertTrue(gated.notices)

    def test_error_elimination_names_unknown_ids_instead_of_inventing_items(self):
        ghost = self.agent.assemble_paper(
            AssemblePaperRequest(user_id="u_prac", exam_type="NTCE",
                                 practice_mode=PracticeMode.ERROR_ELIMINATION, item_count=5,
                                 wrong_question_ids=["ntce-item-m1-001"])
        )
        self.assertEqual(ghost.total_items, 0)
        self.assertTrue(any("不在库内" in n for n in ghost.notices))

    def test_cet_three_stage_clock(self):
        state = CETExamStateMachine.get_initial_state()
        self.assertEqual(state.stage, "writing")
        self.assertFalse(state.input_locked)
        state = CETExamStateMachine.step_stage(state, elapsed_seconds=1800)
        self.assertEqual(state.stage, "listening")
        state = CETExamStateMachine.step_stage(state, elapsed_seconds=1800)
        self.assertEqual(state.stage, "reading_translation")
        self.assertTrue(state.sheet_collected)
        state = CETExamStateMachine.step_stage(state, elapsed_seconds=4200)
        self.assertEqual(state.stage, "completed")
        self.assertTrue(state.input_locked)


# --------------------------------------------------------------------------- 4. 答疑
class TestTutorQA(LibraryBackedTestCase):
    def setUp(self):
        self.agent = TutorQAAgent(repository=self.repository)

    def test_sparks_chain_quotes_the_items_own_stored_evidence(self):
        record_answer = (self.sample_record.get("content") or {}).get("answer")
        resp = self.agent.answer_query(
            QARequest(user_id="u_qa", question_id=self.sample_question_id,
                      user_selected_option="A", mode="sparks_three_chain")
        )
        self.assertTrue(resp.grounded_in_library)
        self.assertEqual(resp.option_discrimination["reference_answer"], record_answer)
        self.assertEqual(len(resp.option_discrimination["options"]),
                         len(self.sample_record["content"]["options"]))
        self.assertIn(COPYRIGHT_NOTICE, resp.notices)
        self.assertTrue(any("复核" in n for n in resp.notices), "未签署内容必须带复核提示")
        self.assertTrue(resp.key_clue_localization)

    def test_socratic_hint_only_reveals_the_library_answer_on_the_last_turn(self):
        record_answer = (self.sample_record.get("content") or {}).get("answer")
        for turn in (1, 2):
            hinted = self.agent.answer_query(
                QARequest(user_id="u_qa", question_id=self.sample_question_id,
                          mode="socratic_hint", hint_turn=turn, user_selected_option="A")
            )
            with self.subTest(turn=turn):
                self.assertFalse(hinted.is_final_reveal)
                self.assertIsNone(hinted.revealed_answer)
                self.assertNotIn("参考答案", hinted.guiding_question or "")
                self.assertTrue(hinted.grounded_in_library)

        revealed = self.agent.answer_query(
            QARequest(user_id="u_qa", question_id=self.sample_question_id,
                      mode="socratic_hint", hint_turn=3)
        )
        self.assertTrue(revealed.is_final_reveal)
        self.assertEqual(revealed.revealed_answer, record_answer)

    def test_unknown_id_and_disputed_item_never_assert_an_answer(self):
        ghost = self.agent.answer_query(QARequest(user_id="u_qa", question_id="ntce-item-m1-001"))
        self.assertFalse(ghost.grounded_in_library)
        self.assertEqual(ghost.answer_visibility, "none")
        self.assertIsNone(ghost.option_discrimination.get("reference_answer"))

        conflicted = next(m for m in self.repository.questions().values()
                          if m.answer_status == "source_conflict")
        blocked = self.agent.answer_query(QARequest(user_id="u_qa", question_id=conflicted.question_id))
        self.assertEqual(blocked.answer_visibility, "none")
        self.assertFalse(blocked.option_discrimination)
        self.assertIsNone(blocked.option_discrimination.get("reference_answer"))

    def test_published_tier_refuses_the_answer_research_tier_gives(self):
        published = self.agent.answer_query(
            QARequest(user_id="u_qa", question_id=self.sample_question_id,
                      trust_tier=TrustTier.PUBLISHED)
        )
        self.assertIsNone(published.option_discrimination.get("reference_answer"))
        self.assertEqual(published.answer_visibility, "none")


# --------------------------------------------------------------------------- 5. 面试教练
class TestInterviewCoach(LibraryBackedTestCase):
    def setUp(self):
        self.queue = ReviewQueue(root=self._queue_root)
        self.agent = InterviewCoachAgent(repository=self.repository, review_queue=self.queue)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._queue_root = tempfile.mkdtemp(prefix="km_test_interview_queue_")

    def test_speech_is_measured_and_never_scored_from_invented_weights(self):
        resp = self.agent.analyze_speech(
            SpeechAnalysisRequest(
                transcript_text=(
                    "同学们好，请看大屏幕，创设情境导入新课。今天我们深入剖析自主探究新知识。"
                    "接下来大家来做一做课堂练习巩固。最后请哪位同学来做课堂小结梳理收获？"
                    "今天的课后作业是完成课后探究题。"
                ),
                audio_duration_seconds=30.0,
                audio_pauses=[1.0, 4.0],
            )
        )
        self.assertEqual(resp.phase_coverage_rate, 1.0)
        self.assertEqual(len(resp.teaching_phases), 5)
        self.assertGreater(resp.hesitation_pause_count, 0)
        # 综合分需要试讲量规签署；库内那份是未签署的，所以只能是 null。
        self.assertIsNone(resp.overall_score)
        self.assertFalse(resp.rubric_signed)
        self.assertTrue(resp.coaching_feedback)

        entry = resp.review_queue_entry
        self.assertIsNotNone(entry, "不出分必须转成一条教研可办的复核记录")
        self.assertIsNone(entry["checked_by"])
        self.assertFalse(entry["expert_verified"])

    def test_empty_transcript_produces_no_measurement(self):
        resp = self.agent.analyze_speech(
            SpeechAnalysisRequest(transcript_text="", audio_duration_seconds=1.0)
        )
        self.assertEqual(resp.phase_coverage_rate, 0.0)
        self.assertIsNone(resp.overall_score)

    def test_lesson_plan_dimensions_are_the_library_rubrics_own(self):
        rubric = self.repository.find_rubric(task_type="lesson_plan", exam="NTCE")
        library_dims = {
            d["dimension_name"]: (d["weight_score"],
                                  {l["level_name"]: l["descriptor"] for l in d["criteria_levels"]})
            for d in rubric["dimensions"]
        }
        resp = self.agent.review_lesson_plan(
            LessonPlanReviewRequest(
                topic="古诗鉴赏",
                plan_text=(
                    "一、教学目标：知识与技能、过程与方法、情感态度价值观三维目标完整。\n"
                    "二、教学重点与难点：重点是理解课文主旨，难点是探究表现手法。\n"
                    "三、教学过程：导入、新课讲授、探究互动、练习巩固、总结作业。\n"
                    "四、板书设计：提纲式板书。"
                ),
            )
        )
        self.assertEqual(resp.rubric_id, rubric["rubric_id"])
        self.assertEqual([d["dimension_name"] for d in resp.dimensions], list(library_dims))
        self.assertEqual(resp.max_score, rubric["total_score"])
        for d in resp.dimensions:
            self.assertEqual(d["weight_score"], library_dims[d["dimension_name"]][0])
            self.assertIn(d["descriptor"], library_dims[d["dimension_name"]][1].values())
        self.assertIsNone(resp.total_score)
        self.assertTrue(resp.feedback_only)
        self.assertFalse(resp.rubric_signed)
        self.assertTrue(any("签署" in n or "不出分" in n for n in resp.notices + [resp.improvement_suggestions]))

    def test_published_tier_refuses_interview_scores(self):
        resp = self.agent.review_lesson_plan(
            LessonPlanReviewRequest(topic="古诗鉴赏", plan_text="教学目标：略。",
                                    trust_tier=TrustTier.PUBLISHED)
        )
        self.assertIsNone(resp.total_score)
        self.assertEqual(resp.trust_tier, TrustTier.PUBLISHED)


# --------------------------------------------------------------------------- 6. 总控与闭环
class TestTutorMaster(LibraryBackedTestCase):
    ROUTED = [
        ("我想进行一次水平测验查漏补缺", UserIntent.DIAGNOSTIC, "diagnostic_card"),
        ("帮我制定30天备考计划课表", UserIntent.PLAN, "plan_card"),
        ("我要开始做题刷题练习", UserIntent.PRACTICE, "practice_card"),
        ("查看我今天到期的错题本和FSRS复习包", UserIntent.ERROR_REVIEW, "review_card"),
        ("这道题我选了A，请问为什么选B，讲讲这题解析", UserIntent.QA_ASK, "qa_card"),
        ("我想练一下教资面试试讲和简案教学设计", UserIntent.INTERVIEW_PRACTICE, "interview_card"),
        ("你好，你是谁？", UserIntent.GENERAL_CHAT, "text_message"),
    ]

    def setUp(self):
        self.queue_root = tempfile.mkdtemp(prefix="km_test_master_queue_")
        self.queue = ReviewQueue(root=self.queue_root)
        self.agent = TutorMasterAgent(queue=self.queue)

    def test_each_intent_lands_on_its_own_card(self):
        for message, intent, card in self.ROUTED:
            resp = self.agent.handle_interaction(
                MasterInteractionRequest(user_id="u_master", message=message, exam_type="NTCE")
            )
            with self.subTest(message=message):
                self.assertEqual(resp.detected_intent, intent)
                self.assertEqual(resp.card_type, card)
                self.assertTrue(resp.card_data, f"{card} 不能是空卡片")
                self.assertTrue(resp.suggested_quick_replies)

    def test_a_grading_request_without_an_answer_asks_for_the_answer(self):
        pending_before = self.queue.stats()["pending_records"]
        resp = self.agent.handle_interaction(
            MasterInteractionRequest(user_id="u_master",
                                     message="请帮我批改一下我的材料分析主观题答案", exam_type="NTCE")
        )
        self.assertEqual(resp.detected_intent, UserIntent.SUBMIT_SUBJECTIVE)
        self.assertEqual(resp.card_type, "text_message")
        self.assertEqual(set(resp.card_data["missing_inputs"]), {"answer_text", "question_id"})
        self.assertTrue(any(k in resp.reply_text for k in ("answer_text", "question_id")))
        # 缺的是使用者的作答，不是教研能裁决的内容缺陷：不许占用唯一的复核队列。
        self.assertEqual(self.queue.stats()["pending_records"], pending_before)

    def test_the_closed_loop_is_recorded_and_replayable(self):
        resp = self.agent.handle_interaction(
            MasterInteractionRequest(user_id="u_replay", message="先做一次学情摸底，然后给我计划和练习",
                                     exam_type="NTCE")
        )
        actions = [row["action"] for row in resp.trace]
        self.assertEqual(actions[:4], [
            "diagnostic.evaluate", "memory.profile", "planner.generate", "practice.assemble",
        ])
        replayed = self.agent.trace_of(resp.session_id)
        self.assertEqual([row["envelope"]["action"] for row in replayed], actions)
        self.assertEqual([row["seq"] for row in replayed], list(range(1, len(actions) + 1)))
        for row in replayed:
            envelope = row["envelope"]
            self.assertEqual(envelope["generated_by"]["mode"], "deterministic")
            self.assertIn(envelope["trust_tier"], ("research_internal", "published"))
            self.assertEqual(envelope["sender"], "orchestrator")

    def test_published_tier_produces_no_fabricated_plan(self):
        resp = self.agent.handle_interaction(
            MasterInteractionRequest(user_id="u_pub", message="生成备考计划并组卷",
                                     exam_type="NTCE", trust_tier=TrustTier.PUBLISHED)
        )
        self.assertIn("0", resp.reply_text)
        self.assertNotIn("30 道", resp.reply_text)


if __name__ == "__main__":
    unittest.main()
