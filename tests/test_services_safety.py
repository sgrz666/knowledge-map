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
        self.assertIn("开放讨论题", msg)

        is_normal, _ = SafetyGuard.check_disputed_question("normal", "q_normal_01")
        self.assertFalse(is_normal)


if __name__ == "__main__":
    unittest.main()
