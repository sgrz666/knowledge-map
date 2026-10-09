"""Unit and integration tests for SubjectiveGraderAgent and dual-mode rubrics."""
from __future__ import annotations

import unittest

from services.common.models import SubjectiveGradingRequest
from services.grader.agent import SubjectiveGraderAgent
from services.grader.cet_holistic import CETHolisticGrader
from services.grader.ntce_analytic import NTCEAnalyticGrader


class TestSubjectiveGrader(unittest.TestCase):
    def setUp(self):
        self.agent = SubjectiveGraderAgent()

    def test_cet_writing_holistic_grading_bands(self):
        # 1. Short essay with very few words -> Band 2 / 5
        req_short = SubjectiveGradingRequest(
            question_id="cet4-2023-writing-q01",
            exam_type="CET-4",
            task_type="short_essay",
            stem="Directions: Write an essay on the importance of digital literacy.",
            student_answer="I think digital literacy is good. People use computer everyday.",
            max_score=15.0,
        )
        resp_short = self.agent.grade(req_short)
        self.assertEqual(resp_short.grading_mode, "holistic_band")
        self.assertIsNotNone(resp_short.holistic_details)
        self.assertIn(resp_short.holistic_details.selected_band, [2, 5])
        self.assertLessEqual(resp_short.total_score, 6.0)
        self.assertEqual(len(resp_short.holistic_details.qualitative_dimensions), 3)

        # 2. Well-developed essay with discourse markers -> Band 11 / 14
        developed_essay = (
            "With the rapid advancement of modern information technology, digital literacy has become "
            "an indispensable competency for contemporary college students in higher education. "
            "Firstly, possessing sound digital literacy enables individuals to efficiently filter, evaluate, and synthesize credible academic resources. "
            "Secondly, it significantly bolsters collaborative productivity and communicative efficiency in remote research settings and future career paths. "
            "However, many undergraduates still struggle with information overload, screen distraction, and complex cybersecurity risks. "
            "Therefore, universities should establish systematic curricula and hands-on workshops to cultivate students' "
            "critical thinking and digital responsibility. In addition, students themselves should proactively practice self-discipline. "
            "In conclusion, actively embracing digital literacy is of paramount significance for our all-round personal growth "
            "and lifelong professional development in this fast-paced modern era."
        )
        req_good = SubjectiveGradingRequest(
            question_id="cet4-2023-writing-q02",
            exam_type="CET-4",
            task_type="short_essay",
            stem="Directions: Write an essay on the importance of digital literacy.",
            student_answer=developed_essay,
            max_score=15.0,
        )
        resp_good = self.agent.grade(req_good)
        self.assertEqual(resp_good.grading_mode, "holistic_band")
        self.assertIn(resp_good.holistic_details.selected_band, [11, 14])
        self.assertGreaterEqual(resp_good.total_score, 10.0)
        self.assertLessEqual(resp_good.total_score, 15.0)

    def test_cet_translation_holistic_dimensions(self):
        req_trans = SubjectiveGradingRequest(
            question_id="cet6-2022-trans-q01",
            exam_type="CET-6",
            task_type="paragraph_translation",
            stem="中国的高铁（high-speed railway）网络已成为世界上最庞大和最先进的铁路网络之一。",
            student_answer=(
                "China's high-speed railway network has become one of the largest and most advanced "
                "railway systems in the world. It not only accelerates regional economic integration, "
                "but also facilitates convenient travel for hundreds of millions of passengers."
            ),
            max_score=15.0,
        )
        resp = self.agent.grade(req_trans)
        self.assertEqual(resp.grading_mode, "holistic_band")
        dim_names = [d.dimension_name for d in resp.holistic_details.qualitative_dimensions]
        self.assertIn("原文信息准确与完整", dim_names)
        self.assertIn("句法与用词", dim_names)
        self.assertIn("语篇清晰与连贯", dim_names)

    def test_ntce_case_analysis_analytic_scoring(self):
        case_stem = "请从教师职业理念（学生观与教师观）的角度评析材料中张老师的教学行为。"
        student_ans = (
            "张老师的教学行为体现了新课程背景下的先进教师职业理念。\n"
            "第一，张老师践行了‘以人为本’的学生观。学生观认为学生是发展中的人、独特的人和具有独立意义的人。"
            "张老师没有因为小明的暂时落后而批评他，而是因材施教，循循善诱，尊重了学生的个体差异。\n"
            "第二，张老师体现了现代教师观的角色转变。教师是学生学习的促进者和引导者。"
            "在教学互动中，张老师启发小明自主探究，构建了良好的师生关系。\n"
            "综上所述，作为人民教师，我们应该向张老师学习，关爱学生，促进学生的全面发展。"
        )
        req = SubjectiveGradingRequest(
            question_id="ntce-xiaoxue-2023-case-q30",
            exam_type="NTCE",
            task_type="case_analysis",
            stem=case_stem,
            student_answer=student_ans,
            reference_answer="1. 践行‘以人为本’的学生观；2. 体现引导者和促进者的教师观；3. 因材施教，关爱学生。",
            max_score=14.0,
        )
        resp = self.agent.grade(req)
        self.assertEqual(resp.grading_mode, "analytic_criteria")
        self.assertIsNotNone(resp.analytic_details)
        self.assertGreaterEqual(len(resp.analytic_details.dimensions), 3)

        # Dimension scores sum should match total_score
        dim_sum = round(sum(d.score for d in resp.analytic_details.dimensions), 1)
        self.assertAlmostEqual(resp.total_score, dim_sum, delta=0.5)

        # Rubric points hit detection
        hit_points = [p for p in resp.analytic_details.rubric_points_hit if p.status == "hit"]
        self.assertGreaterEqual(len(hit_points), 1)

    def test_disputed_question_safety_handling(self):
        req = SubjectiveGradingRequest(
            question_id="ntce-conflict-q01",
            exam_type="NTCE",
            task_type="case_analysis",
            stem="争议材料分析题干",
            student_answer="学生作答内容，提出个人理解。",
            max_score=14.0,
        )
        # Passing answer_status='source_conflict'
        resp = self.agent.grade(req, answer_status="source_conflict")
        self.assertIn("争议题提示", resp.evaluation_summary)
        self.assertEqual(resp.review_status, "quarantined_for_human")
        self.assertGreater(resp.total_score, 0.0)


if __name__ == "__main__":
    unittest.main()
