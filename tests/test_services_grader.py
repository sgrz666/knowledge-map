"""Grader tests for the A4 contract: feedback is free, a score needs a 教研 signature.

These tests used to assert numeric scores and band selections produced by engines that carried
their own copy of the rubric (``DEFAULT_CET_BANDS``, a four-dimension NTCE template, a pedagogy
keyword list). That data is gone, so the assertions now compare the response against the library
entity itself — if the service ever invents a descriptor again, the comparison fails.
"""
from __future__ import annotations

import inspect
import unittest

from services.common.models import SubjectiveGradingRequest, TrustTier
from services.grader.agent import SubjectiveGraderAgent
from services.grader.rubric_engine import grade as engine_grade
from services.knowledge.repository import get_repository
from services.knowledge.trust import TrustGate
from services.review.queue import ReviewQueue

import copy
import tempfile
from pathlib import Path


def _first_question(repo, exam: str, types) -> str:
    for meta in repo.find_questions(exams=exam, require_nodes=True, question_types=tuple(types)):
        return meta.question_id
    raise unittest.SkipTest(f"库内没有 {exam} 的 {types} 题目")


class TestGraderUnsigned(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = get_repository()
        cls.cet_writing = _first_question(cls.repo, "CET-4", ("短文写作",))
        cls.cet_translation = _first_question(cls.repo, "CET-6", ("段落翻译",))
        cls.ntce_case = _first_question(cls.repo, "NTCE", ("材料分析", "简答"))

    def setUp(self):
        self.queue_root = Path(tempfile.mkdtemp(prefix="grader-test-"))
        self.queue = ReviewQueue(root=self.queue_root)
        self.agent = SubjectiveGraderAgent(repository=self.repo, review_queue=self.queue)

    def _request(self, question_id, exam, task_type, answer, **kw) -> SubjectiveGradingRequest:
        return SubjectiveGradingRequest(
            question_id=question_id,
            exam_type=exam,
            task_type=task_type,
            stem=kw.pop("stem", "（题干以库内记录为准）"),
            student_answer=answer,
            **kw,
        )

    # ----------------------------------------------------------------- A4 core
    def test_unsigned_rubric_produces_no_score_for_cet_writing(self):
        resp = self.agent.grade(
            self._request(
                self.cet_writing,
                "CET-4",
                "short_essay",
                "Digital literacy matters. Students should learn to judge information carefully.",
            )
        )
        self.assertIsNone(resp.total_score)
        self.assertTrue(resp.feedback_only)
        self.assertFalse(resp.rubric_signed)
        self.assertIn(resp.score_basis, ("unsigned_framework", "none"))
        self.assertEqual(resp.review_status, "quarantined_for_human")
        self.assertIsNone(resp.holistic_details.selected_band)
        self.assertIsNone(resp.holistic_details.band_range)
        self.assertEqual(list(self.queue.recent(limit=5))[0]["reason"], "rubric_signature_required")

    def test_band_reference_is_library_text_not_service_data(self):
        """The quoted band descriptor must exist verbatim in the library rubric."""
        resp = self.agent.grade(
            self._request(
                self.cet_writing,
                "CET-4",
                "short_essay",
                "Nowadays digital literacy is indispensable for college students. Firstly, it helps "
                "students filter credible resources. Secondly, it improves collaborative efficiency. "
                "However, many students still suffer from information overload. Therefore universities "
                "should offer systematic training. In conclusion, digital literacy is of great value.",
            )
        )
        rubric = self.repo.find_rubric(task_type="short_essay", exam="CET-4")
        self.assertIsNotNone(rubric, "CET 写作量规应在库内")
        descriptors = {str(b.get("descriptor") or "") for b in rubric.get("bands") or []}
        quoted = resp.holistic_details.band_reference or ""
        self.assertTrue(quoted, "未签署时仍应引用库内档位描述作为反馈参照")
        self.assertTrue(
            any(quoted and quoted in d for d in descriptors),
            "档位列名/描述必须逐字引自库内量规，不得是服务内置文本",
        )

    def test_feedback_dimensions_come_from_the_library_rubric(self):
        resp = self.agent.grade(self._request(self.cet_translation, "CET-6", "paragraph_translation",
                                              "China's high-speed rail network is one of the largest and most advanced."))
        rubric = self.repo.find_rubric(task_type="paragraph_translation", exam="CET-6") or {}
        rows = rubric.get("feedback_dimensions") or rubric.get("dimensions") or []
        library_names = {d.get("dimension_name") or d.get("name") for d in rows} - {None}
        names = [d.dimension_name for d in resp.holistic_details.qualitative_dimensions]
        self.assertTrue(names)
        self.assertTrue(set(names) <= library_names, f"维度名超出库内量规范围: {names} vs {library_names}")
        # CET 的 feedback_dimensions 自带 aggregation 声明：只能用于反馈，不能加权求分。
        self.assertTrue(all("feedback_only" in str(d.get("aggregation", "")) for d in rows if d.get("aggregation")))

    def test_ntce_unsigned_case_analysis_is_qualitative_feedback(self):
        resp = self.agent.grade(
            self._request(
                self.ntce_case,
                "NTCE",
                "case_analysis",
                "该教师践行了以人为本的学生观，尊重个体差异，因材施教；也体现了引导者促进者的教师观。",
            )
        )
        self.assertIsNone(resp.total_score)
        self.assertTrue(resp.feedback_only)
        self.assertEqual(resp.grading_mode, "analytic_criteria")
        self.assertEqual(resp.analytic_details.dimensions, [])
        self.assertTrue(resp.analytic_details.dimension_feedback)
        self.assertIn("签署", resp.revision_advice)

    def test_conflicted_question_never_scores_even_with_a_reference_answer(self):
        conflict = next(
            (m.question_id for m in self.repo.find_questions(answer_statuses=("source_conflict",))), None
        )
        if conflict is None:
            self.skipTest("库内当前没有 source_conflict 题目")
        resp = self.agent.grade(
            self._request(conflict, "NTCE", "case_analysis", "学生作答", reference_answer="参考作答")
        )
        self.assertIsNone(resp.total_score)
        self.assertEqual(resp.score_basis, "none")
        self.assertEqual(resp.review_status, "quarantined_for_human")

    def test_caller_cannot_supply_answer_status(self):
        """The dispute state is read from the index; a caller-supplied flag would be a spoofing vector."""
        params = inspect.signature(SubjectiveGraderAgent.grade).parameters
        self.assertNotIn("answer_status", params)

    def test_published_tier_refuses_unsigned_score(self):
        resp = self.agent.grade(
            self._request(self.ntce_case, "NTCE", "case_analysis", "学生作答", trust_tier=TrustTier.PUBLISHED)
        )
        self.assertIsNone(resp.total_score)
        self.assertTrue(any("published" in n for n in resp.notices))

    def test_queue_row_never_self_signs(self):
        self.agent.grade(self._request(self.ntce_case, "NTCE", "case_analysis", "学生作答"))
        rows = self.queue.recent(limit=10)
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNone(row["checked_by"])
            self.assertFalse(row["expert_verified"])
            self.assertEqual(row["status"], "pending_human_review")


class TestGraderSignedPath(unittest.TestCase):
    """The scoring branch must work the moment 教研 actually signs — on library weights."""

    @classmethod
    def setUpClass(cls):
        cls.repo = get_repository()
        cls.ntce_case = _first_question(cls.repo, "NTCE", ("材料分析", "简答"))

    def _signed(self, task_type, exam):
        rubric = copy.deepcopy(self.repo.find_rubric(task_type=task_type, exam=exam))
        if not rubric:
            self.skipTest(f"库内没有 {task_type} 量规")
        rubric.setdefault("review", {})
        rubric["review"].update({"status": "checked", "checked_by": "测试教研（人工签署）", "expert_verified": True})
        return rubric

    def test_signed_analytic_rubric_scores_with_library_weights(self):
        rubric = self._signed("case_analysis", "NTCE")
        verdict = TrustGate("research_internal").classify_rubric(rubric)
        self.assertTrue(verdict.signed, "带 checked_by 与 expert_verified 的量规应判为已签署")
        dimensions = rubric.get("dimensions") or []
        self.assertTrue(dimensions)
        req = SubjectiveGradingRequest(
            question_id=self.ntce_case,
            exam_type="NTCE",
            task_type="case_analysis",
            stem="评析材料中教师的做法。",
            student_answer="要点一；要点二；要点三",
            reference_answer="要点一\n要点二\n要点三",
        )
        resp = engine_grade(req, mode="analytic_criteria", rubric=rubric, verdict=verdict, record=None)
        self.assertIsNotNone(resp.total_score)
        self.assertEqual(resp.score_basis, "signed_rubric")
        self.assertFalse(resp.feedback_only)
        weight_sum = round(sum(float(d.get("weight_score") or 0.0) for d in dimensions), 1)
        self.assertLessEqual(round(resp.total_score, 1), weight_sum)
        self.assertEqual(
            round(sum(d.score for d in resp.analytic_details.dimensions), 1),
            round(resp.total_score, 1),
        )

    def test_signed_holistic_band_reports_midpoint_not_ceiling(self):
        rubric = self._signed("short_essay", "CET-4")
        if not rubric.get("bands"):
            self.skipTest("该量规没有档位列")
        verdict = TrustGate("research_internal").classify_rubric(rubric)
        req = SubjectiveGradingRequest(
            question_id="cet.band.test",
            exam_type="CET-4",
            task_type="short_essay",
            stem="Write about digital literacy.",
            student_answer="Firstly, it helps. Secondly, it improves. However, many students. Therefore universities. In conclusion.",
            max_score=float(rubric.get("total_score") or 15.0),
        )
        resp = engine_grade(req, mode="holistic_band", rubric=rubric, verdict=verdict, record=None)
        self.assertIsNotNone(resp.total_score)
        low, high = resp.holistic_details.band_range
        self.assertLessEqual(low, resp.total_score)
        self.assertLessEqual(resp.total_score, high)
        self.assertLess(resp.total_score, high, "档位是区间，报告中值而不是上限")

    def test_missing_rubric_does_not_fall_back_to_a_template(self):
        verdict = TrustGate("research_internal").classify_rubric(None)
        self.assertFalse(verdict.found)
        req = SubjectiveGradingRequest(
            question_id="no.such.question",
            exam_type="NTCE",
            task_type="case_analysis",
            stem="题干",
            student_answer="作答",
        )
        resp = engine_grade(req, mode="analytic_criteria", rubric=None, verdict=verdict, record=None)
        self.assertIsNone(resp.total_score)
        self.assertEqual(resp.score_basis, "none")
        self.assertTrue(any("库内没有该题型的量规" in n for n in resp.notices))
        self.assertEqual(resp.analytic_details.dimensions, [])


if __name__ == "__main__":
    unittest.main()
