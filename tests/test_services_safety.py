"""Unit tests for SafetyGuard enforcing score clamping, bounds, and confidence gates."""
from __future__ import annotations

import unittest

from services.common.models import (
    AnalyticDetails,
    AnalyticDimensionResult,
    HolisticDetails,
    UnifiedSubjectiveGradingResponse,
)
from services.common.safety import SafetyGuard


class TestSafetyGuard(unittest.TestCase):
    def test_score_clamping_upper_and_lower_bounds(self):
        # 1. Total score exceeds max_score
        resp_over = UnifiedSubjectiveGradingResponse(
            question_id="q_test_01",
            exam_type="NTCE",
            grading_mode="analytic_criteria",
            total_score=25.0,
            max_score=14.0,
            evaluation_summary="Over-score test",
            revision_advice="None",
            confidence_score=0.9,
        )
        sanitized, quarantined = SafetyGuard.sanitize_grading_response(resp_over)
        self.assertEqual(sanitized.total_score, 14.0)
        self.assertFalse(quarantined)

        # 2. Total score below zero
        resp_neg = UnifiedSubjectiveGradingResponse(
            question_id="q_test_02",
            exam_type="NTCE",
            grading_mode="analytic_criteria",
            total_score=-5.0,
            max_score=14.0,
            evaluation_summary="Negative-score test",
            revision_advice="None",
            confidence_score=0.9,
        )
        sanitized_neg, _ = SafetyGuard.sanitize_grading_response(resp_neg)
        self.assertEqual(sanitized_neg.total_score, 0.0)

    def test_analytic_dimensions_sum_reconciliation(self):
        # Dimension scores: 4.0 + 3.5 = 7.5, but total_score was set to 12.0
        dims = [
            AnalyticDimensionResult(
                dimension_name="Dim1", score=4.0, max_score=5.0, level_name="Good", rationale="ok"
            ),
            AnalyticDimensionResult(
                dimension_name="Dim2", score=3.5, max_score=5.0, level_name="Good", rationale="ok"
            ),
        ]
        resp_mismatch = UnifiedSubjectiveGradingResponse(
            question_id="q_test_03",
            exam_type="NTCE",
            grading_mode="analytic_criteria",
            total_score=12.0,
            max_score=10.0,
            analytic_details=AnalyticDetails(dimensions=dims, rubric_points_hit=[]),
            evaluation_summary="Mismatch test",
            revision_advice="None",
            confidence_score=0.9,
        )
        sanitized, _ = SafetyGuard.sanitize_grading_response(resp_mismatch)
        self.assertEqual(sanitized.total_score, 7.5)

    def test_low_confidence_quarantine_routing(self):
        resp_low = UnifiedSubjectiveGradingResponse(
            question_id="q_test_04",
            exam_type="NTCE",
            grading_mode="analytic_criteria",
            total_score=8.0,
            max_score=14.0,
            evaluation_summary="Low confidence test",
            revision_advice="None",
            confidence_score=0.45,  # Below threshold 0.60
        )
        sanitized, quarantined = SafetyGuard.sanitize_grading_response(resp_low)
        self.assertTrue(quarantined)
        self.assertEqual(sanitized.review_status, "quarantined_for_human")

    def test_disputed_source_conflict_handling(self):
        is_disp, msg = SafetyGuard.check_disputed_question("source_conflict", "q_conflict_01")
        self.assertTrue(is_disp)
        self.assertIn("source_conflict", msg)
        self.assertIn("不出分", msg)
        self.assertIn("不断言正确选项", msg)

        is_missing, missing_msg = SafetyGuard.check_disputed_question("missing", "q_missing_01")
        self.assertTrue(is_missing)
        self.assertIn("不做硬性扣分", missing_msg)

        is_normal, _ = SafetyGuard.check_disputed_question("normal", "q_normal_01")
        self.assertFalse(is_normal)

    def test_unsigned_rubric_score_is_stripped_not_clamped(self):
        """A score on an unsigned rubric is a defect: it disappears, it is not resized to fit."""
        resp = UnifiedSubjectiveGradingResponse(
            question_id="q_test_unsigned",
            exam_type="NTCE",
            grading_mode="analytic_criteria",
            total_score=9.5,
            max_score=14.0,
            evaluation_summary="signed-off? no",
            revision_advice="None",
            confidence_score=0.9,
        )
        sanitized, quarantined = SafetyGuard.sanitize_grading_response(resp, rubric_signed=False)
        self.assertIsNone(sanitized.total_score)
        self.assertTrue(sanitized.feedback_only)
        self.assertEqual(sanitized.score_basis, "unsigned_framework")
        self.assertEqual(sanitized.review_status, "quarantined_for_human")
        self.assertTrue(quarantined)
        self.assertTrue(any("未签署" in n for n in sanitized.notices))

    def test_signed_rubric_is_not_stripped(self):
        resp = UnifiedSubjectiveGradingResponse(
            question_id="q_test_signed",
            exam_type="NTCE",
            grading_mode="analytic_criteria",
            total_score=9.5,
            max_score=14.0,
            feedback_only=False,
            score_basis="signed_rubric",
            evaluation_summary="ok",
            revision_advice="None",
            confidence_score=0.9,
        )
        sanitized, quarantined = SafetyGuard.sanitize_grading_response(resp, rubric_signed=True)
        self.assertEqual(sanitized.total_score, 9.5)
        self.assertFalse(quarantined)

    def test_low_confidence_without_score_does_not_quarantine(self):
        """Feedback-only output has no score to distrust; quarantine is about shipped numbers."""
        resp = UnifiedSubjectiveGradingResponse(
            question_id="q_test_nul",
            exam_type="NTCE",
            grading_mode="analytic_criteria",
            total_score=None,
            max_score=14.0,
            feedback_only=True,
            evaluation_summary="feedback",
            revision_advice="None",
            confidence_score=0.2,
        )
        sanitized, quarantined = SafetyGuard.sanitize_grading_response(resp, rubric_signed=False)
        self.assertFalse(quarantined)
        self.assertIsNone(sanitized.total_score)


if __name__ == "__main__":
    unittest.main()
