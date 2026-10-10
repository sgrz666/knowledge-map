"""Unit and schema validation tests for MemoryReviewAgent, attribution, and FSRS scheduler."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
import jsonschema

from services.common.models import (
    ErrorAttributionCategory,
    ErrorReviewEvent,
)
from services.memory.agent import MemoryReviewAgent
from services.memory.attribution import ErrorAttributionEngine
from services.memory.fsrs import FSRSModel
from services.memory.store import InMemoryMasteryStore

ROOT = Path(__file__).resolve().parents[1]
USER_MASTERY_SCHEMA_PATH = ROOT / "数据集" / "教资" / "schemas" / "user_mastery.json"


class TestMemoryReviewService(unittest.TestCase):
    def setUp(self):
        # Per-test volatile store keeps FSRS counters independent of .local_state/.
        self.agent = MemoryReviewAgent(store=InMemoryMasteryStore())
        self.user_mastery_schema = json.loads(
            USER_MASTERY_SCHEMA_PATH.read_text(encoding="utf-8")
        )

    def test_five_dimensional_attribution_scenarios(self):
        # 1. Careless (Super quick answering <= 5s)
        event_careless = ErrorReviewEvent(
            user_id="u01",
            question_id="q01",
            node_id="ntce.xiaoxue.jiaoxue.m1.k01",
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=4.2,
            has_negation_in_stem=True,
            question_difficulty=0.4,
            current_node_mastery=0.7,
        )
        res1 = ErrorAttributionEngine.attribute(event_careless)
        self.assertEqual(res1.category, ErrorAttributionCategory.CARELESS)

        # 2. Time Pressure (Spent over 160s on single objective question)
        event_pressure = ErrorReviewEvent(
            user_id="u01",
            question_id="q02",
            node_id="ntce.xiaoxue.jiaoxue.m1.k01",
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=175.0,
            question_difficulty=0.6,
            current_node_mastery=0.6,
        )
        res2 = ErrorAttributionEngine.attribute(event_pressure)
        self.assertEqual(res2.category, ErrorAttributionCategory.TIME_PRESSURE)

        # 3. Misconception (Typical distractor / option flipping)
        event_misconception = ErrorReviewEvent(
            user_id="u01",
            question_id="q03",
            node_id="ntce.xiaoxue.jiaoxue.m1.k01",
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=25.0,
            is_typical_distractor=True,
            option_flip_count=2,
            question_difficulty=0.5,
            current_node_mastery=0.6,
        )
        res3 = ErrorAttributionEngine.attribute(event_misconception)
        self.assertEqual(res3.category, ErrorAttributionCategory.MISCONCEPTION)

        # 4. Blindspot (Node historical mastery < 0.35)
        event_blindspot = ErrorReviewEvent(
            user_id="u01",
            question_id="q04",
            node_id="ntce.xiaoxue.jiaoxue.m1.k01",
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=30.0,
            question_difficulty=0.5,
            current_node_mastery=0.25,
        )
        res4 = ErrorAttributionEngine.attribute(event_blindspot)
        self.assertEqual(res4.category, ErrorAttributionCategory.BLINDSPOT)

        # 5. Expression Deficit (Subjective rubric misses)
        event_expr = ErrorReviewEvent(
            user_id="u01",
            question_id="q05",
            node_id="ntce.xiaoxue.jiaoxue.m1.k01",
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=120.0,
            is_subjective=True,
            subjective_rubric_misses=["以人为本学生观", "因材施教原则"],
        )
        res5 = ErrorAttributionEngine.attribute(event_expr)
        self.assertEqual(res5.category, ErrorAttributionCategory.EXPRESSION_DEFICIT)

    def test_fsrs_mathematical_properties(self):
        # 1. Check exact cognitive retention target R(S, S) = 0.90
        stability = 5.0
        retrievability = FSRSModel.retrievability(stability, stability)
        self.assertAlmostEqual(retrievability, 0.90, places=4)

        # 2. Check initial step on Again vs Good
        state_again, int_again = FSRSModel.step(None, rating=1)
        self.assertEqual(state_again.reps, 1)
        self.assertEqual(state_again.lapses, 1)
        self.assertLessEqual(state_again.stability, 1.0)

        state_good, int_good = FSRSModel.step(None, rating=3)
        self.assertEqual(state_good.reps, 1)
        self.assertEqual(state_good.lapses, 0)
        self.assertGreater(state_good.stability, state_again.stability)

        # 3. Subsequent review expands stability
        state_good_2, int_good_2 = FSRSModel.step(state_good, rating=3)
        self.assertGreater(state_good_2.stability, state_good.stability)
        self.assertGreater(int_good_2, int_good)

    def test_user_mastery_record_conforms_to_schema(self):
        event = ErrorReviewEvent(
            user_id="student_1001",
            question_id="ntce.zhongxue.jiaoyuzhishi.2023a.q05",
            node_id="ntce.zhongxue.jiaoyuzhishi.m4.k01",
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=4.5,
            has_negation_in_stem=True,
            current_node_mastery=0.45,
        )

        bundle = self.agent.process_event(event)
        mastery = bundle.updated_mastery

        # Convert Pydantic model to dict for jsonschema validation
        mastery_dict = json.loads(mastery.model_dump_json())

        # Validate against official user_mastery.json schema (must not throw ValidationError)
        jsonschema.validate(instance=mastery_dict, schema=self.user_mastery_schema)

        self.assertEqual(mastery.user_id, "student_1001")
        self.assertGreaterEqual(mastery.mastery_score, 0.0)
        self.assertLessEqual(mastery.mastery_score, 1.0)
        self.assertIn("复习计划已生成", bundle.followup_plan)


if __name__ == "__main__":
    unittest.main()
