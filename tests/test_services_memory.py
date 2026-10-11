"""Unit and schema validation tests for MemoryReviewAgent, attribution, and FSRS scheduler."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import jsonschema

from services.common.models import (
    ErrorAttributionCategory,
    ErrorReviewEvent,
)
from services.memory.agent import MemoryReviewAgent
from services.memory.attribution import ErrorAttributionEngine
from services.memory.fsrs import FSRSModel
from services.memory.receipt import LegacyReceipt, ReceiptConflict
from services.memory.store import InMemoryMasteryStore, SqliteMasteryStore

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


class TestEventReceipts(unittest.TestCase):
    """A receipt identifies an attempt by what was submitted, not only by its id."""

    NODE = 'ntce.zhongxue.jiaoyuzhishi.m4.k01'
    QUESTION = 'ntce.zhongxue.jiaoyuzhishi.2023a.q05'

    def setUp(self):
        self.agent = MemoryReviewAgent(store=InMemoryMasteryStore())

    def event(self, **updates):
        base = dict(user_id='u-receipt', question_id=self.QUESTION, node_id=self.NODE,
                    exam='NTCE', is_correct=False, time_spent_seconds=30.0)
        return ErrorReviewEvent(**{**base, **updates})

    def test_same_id_same_inputs_replays_without_a_second_write(self):
        event = self.event(selected_option='Z')
        first = self.agent.process_event(event, event_id='paper-q-node')
        again = self.agent.process_event(event.model_copy(), event_id='paper-q-node')
        self.assertEqual(again.model_dump(), first.model_dump())
        self.assertEqual(self.agent.get_user_mastery('u-receipt', self.NODE).practice_count, 1)

    def test_same_id_changed_inputs_are_refused_before_any_write(self):
        event = self.event(selected_option='Z')
        self.agent.process_event(event, event_id='paper-q-node')
        before = self.agent.get_user_mastery('u-receipt', self.NODE).model_dump()
        for changed in ({'selected_option': 'A'}, {'time_spent_seconds': 20.0}, {'option_flip_count': 2}):
            with self.assertRaises(ReceiptConflict):
                self.agent.process_event(event.model_copy(update=changed), event_id='paper-q-node')
        self.assertEqual(self.agent.get_user_mastery('u-receipt', self.NODE).model_dump(), before)

    def test_clear_drops_receipts_so_a_reset_learner_is_counted_again(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SqliteMasteryStore(Path(folder) / 'memory.sqlite3')
            try:
                agent = MemoryReviewAgent(store=store)
                event = self.event(selected_option='Z')
                agent.process_event(event, event_id='paper-q-node')
                self.assertEqual(agent.get_user_mastery('u-receipt', self.NODE).practice_count, 1)
                store.clear('u-receipt')
                self.assertIsNone(store.get('u-receipt', self.NODE))
                # 收据不跟着掌握度一起清，重练的这次会被当成"这个 id 已经记过"原样回放，计数再也回不来
                agent.process_event(event, event_id='paper-q-node')
                self.assertEqual(agent.get_user_mastery('u-receipt', self.NODE).practice_count, 1)
            finally:
                store.close()

    def test_receipts_written_before_fingerprinting_migrate_and_then_refuse_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'memory.sqlite3'
            conn = sqlite3.connect(path)
            conn.executescript('CREATE TABLE memory_events (event_id TEXT PRIMARY KEY, result_json TEXT NOT NULL);')
            conn.execute('INSERT INTO memory_events VALUES(?,?)',
                         ('paper-q-node', '{"user_id":"u-receipt","node_id":"x"}'))
            conn.commit()
            conn.close()
            store = SqliteMasteryStore(path)
            try:
                probe = sqlite3.connect(path)
                try:
                    columns = {row[1] for row in probe.execute('PRAGMA table_info(memory_events)')}
                finally:
                    probe.close()
                self.assertTrue({'user_id', 'fingerprint'} <= columns)
                self.assertEqual(store.unverifiable_receipts(), 1)
                with self.assertRaises(LegacyReceipt):
                    MemoryReviewAgent(store=store).process_event(self.event(selected_option='Z'),
                                                                 event_id='paper-q-node')
                # 没有指纹就无从证明这次请求就是第一次那次作答：既不回放旧结果，也不重新计一次
                self.assertIsNone(store.get('u-receipt', self.NODE))
                self.assertEqual(store.unverifiable_receipts(), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
