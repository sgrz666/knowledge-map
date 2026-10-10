"""Executable acceptance checks for the knowledge facade (docs/agent_architecture.md §8).

A1 no shadow data · A2 real references · A3 quarantine cannot leak ·
A5 state survives across processes · A7 difficulty wording.
"""
from __future__ import annotations

import ast
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ["KNOWLEDGE_MAP_STATE_DIR"] = tempfile.mkdtemp(prefix="km_test_dsrc_")

from services.common.models import (
    AssemblePaperRequest,
    ErrorReviewEvent,
    PracticeMode,
    QARequest,
    TrustTier,
    UserMasteryRecord,
)
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate
from services.memory.agent import MemoryReviewAgent
from services.memory.store import SqliteMasteryStore
from services.practice.agent import PracticeEngineAgent
from services.qa.agent import TutorQAAgent

SERVICES_DIR = Path(__file__).resolve().parents[1] / "services"
STEM_MARKER = re.compile(r"（\s*）|\(\s*\)|选项[A-D]")
FORBIDDEN_IDENTIFIERS = ("SAMPLE_QUESTION_BANK", "PROVENANCE_DB")
UNCALIBRATED_WORDS = ("IRT", "CAT", "标准误", "信度系数")


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


class TestA1NoShadowData(unittest.TestCase):
    def test_no_hardcoded_banks(self):
        offenders = []
        for py in SERVICES_DIR.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for name in FORBIDDEN_IDENTIFIERS:
                if name in text:
                    offenders.append(f"{py.name}:{name}")
            for literal in _string_literals(py):
                if len(literal) > 40 and STEM_MARKER.search(literal):
                    offenders.append(f"{py.name}: embedded stem {literal[:24]!r}")
        self.assertEqual(offenders, [], "services/ 不得内嵌题面或题库常量")

    def test_repository_sees_the_whole_library(self):
        repo = get_repository()
        stats = repo.stats()
        self.assertGreaterEqual(stats["question_records"], 20000)
        self.assertGreaterEqual(stats["requirement_records"], 6000)
        self.assertEqual(stats["scan_issues"], 0)
        self.assertGreaterEqual(stats["paper_specs"], 150)


class TestA2RealReferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository: KnowledgeRepository = get_repository()
        cls.practice = PracticeEngineAgent(repository=cls.repository)
        cls.qa = TutorQAAgent(repository=cls.repository)

    def test_assembled_ids_all_hit_the_index(self):
        for exam, mode, count in [
            ("NTCE", PracticeMode.DAILY_PRACTICE, 8),
            ("NTCE", PracticeMode.MOCK_EXAM, 200),
            ("CET-4", PracticeMode.MOCK_EXAM, 200),
            ("CET-6", PracticeMode.TIMED_SPRINT, 8),
        ]:
            resp = self.practice.assemble_paper(
                AssemblePaperRequest(
                    user_id="u_accept", exam_type=exam, practice_mode=mode, item_count=count
                )
            )
            with self.subTest(exam=exam, mode=mode.value):
                self.assertGreater(resp.total_items, 0)
                for payload in resp.questions:
                    self.assertIsNotNone(self.repository.get_meta(payload["question_id"]))
                    record = self.repository.load_question(payload["question_id"])
                    content = record.get("content") or {}
                    stored = content.get("stem") or record.get("text") or ""
                    self.assertEqual(stored[:20], payload["stem"][:20])
                    self.assertTrue(payload["stem"].strip() or payload["options"], "送进卷面的题必须有题面或选项")

    def test_provenance_clauses_hit_the_requirement_index(self):
        cited = 0
        for meta in self.repository.find_questions(exams=("NTCE",), answer_statuses=("letter_only",)):
            if not meta.requirement_ids:
                continue
            resp = self.qa.answer_query(QARequest(user_id="u_accept", question_id=meta.question_id))
            clauses = resp.knowledge_provenance["requirements"]
            if not clauses:
                continue
            for clause in clauses:
                self.assertIsNotNone(self.repository.get_requirement(clause["requirement_id"]))
                self.assertTrue(clause["content"])
                cited += 1
            if cited >= 5:
                break
        self.assertGreaterEqual(cited, 5, "溯源必须能命中权威条款")


class TestA3QuarantineCannotLeak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = get_repository()
        cls.practice = PracticeEngineAgent(repository=cls.repository)
        cls.qa = TutorQAAgent(repository=cls.repository)
        cls.quarantined = [
            m for m in cls.repository.questions().values() if m.review_status == "quarantined"
        ]
        cls.conflicted = [
            m for m in cls.repository.questions().values() if m.answer_status == "source_conflict"
        ]

    def test_blocked_ids_never_appear_in_papers(self):
        blocked = {m.question_id for m in self.quarantined} | {m.question_id for m in self.conflicted}
        self.assertTrue(blocked, "库内应存在隔离/冲突题目")
        issued = set()
        for exam in ("NTCE", "CET-4", "CET-6"):
            for mode in (
                PracticeMode.POINT_FOCUS,
                PracticeMode.DAILY_PRACTICE,
                PracticeMode.HIGH_FREQUENCY,
                PracticeMode.MOCK_EXAM,
            ):
                resp = self.practice.assemble_paper(
                    AssemblePaperRequest(
                        user_id="u_accept", exam_type=exam, practice_mode=mode, item_count=40
                    )
                )
                issued |= {q["question_id"] for q in resp.questions}
        self.assertEqual(issued & blocked, set())

    def test_blocked_ids_are_excluded_by_the_index_filter(self):
        gate = TrustGate("research_internal")
        for meta in (self.quarantined + self.conflicted)[:25]:
            verdict = gate.classify_meta(meta)
            self.assertFalse(verdict.usable, meta.question_id)
            self.assertEqual(verdict.answer_visibility, "none")

    def test_qa_card_bodies_do_not_assert_an_answer(self):
        for meta in (self.quarantined + self.conflicted)[:6]:
            resp = self.qa.answer_query(QARequest(user_id="u_accept", question_id=meta.question_id))
            self.assertFalse(resp.option_discrimination.get("reference_answer"))
            self.assertNotIn("正确答案", resp.explanation_summary)
            self.assertEqual(resp.answer_visibility, "none")
            hint = self.qa.answer_query(
                QARequest(
                    user_id="u_accept", question_id=meta.question_id, mode="socratic_hint", hint_turn=3
                )
            )
            self.assertIsNone(hint.revealed_answer)


class TestA5StatePersistence(unittest.TestCase):
    def test_two_instances_share_one_state_dir(self):
        state = tempfile.mkdtemp(prefix="km_state_")
        os.environ["KNOWLEDGE_MAP_STATE_DIR"] = state
        event = ErrorReviewEvent(
            user_id="u_persist",
            question_id="ntce.persist.q1",
            node_id="ntce.xiaoxue.jiaoxue.m1.k01",
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=4.2,
            has_negation_in_stem=True,
        )

        first = MemoryReviewAgent(store=SqliteMasteryStore(Path(state) / "memory.sqlite3"))
        bundle = first.process_event(event)
        self.assertEqual(bundle.updated_mastery.practice_count, 1)

        # A second "process" opens the same file: scheduling must survive.
        second = MemoryReviewAgent(store=SqliteMasteryStore(Path(state) / "memory.sqlite3"))
        reloaded = second.get_user_mastery(event.user_id, event.node_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.fsrs_state.reps, bundle.updated_mastery.fsrs_state.reps)
        self.assertEqual(reloaded.last_updated_at, bundle.updated_mastery.last_updated_at)
        queued = [e["question_id"] for e in second.store.error_entries(event.user_id)]
        self.assertIn(event.question_id, queued)
        self.assertTrue(second.due_question_ids(event.user_id, limit=5) or queued)

        # Weak-node ranking must read back from disk, not from process memory.
        second.process_event(
            ErrorReviewEvent(
                user_id="u_persist",
                question_id="ntce.persist.q2",
                node_id="ntce.xiaoxue.jiaoxue.m1.k02",
                exam="NTCE",
                is_correct=False,
                time_spent_seconds=60.0,
            )
        )
        self.assertTrue(second.weak_node_ids("u_persist"))

    def test_record_round_trips_through_sqlite(self):
        state = tempfile.mkdtemp(prefix="km_state_")
        store = SqliteMasteryStore(Path(state) / "memory.sqlite3")
        record = UserMasteryRecord(
            user_id="u_rt",
            node_id="ntce.gaozhong.yuwen.s1.k05",
            mastery_score=0.42,
            practice_count=3,
            correct_count=1,
            fsrs_state=_sample_state(),
            last_updated_at=datetime.now(timezone.utc).isoformat(),
        )
        store.put(record)
        fetched = store.get(record.user_id, record.node_id)
        self.assertEqual(fetched.mastery_score, 0.42)
        self.assertEqual(fetched.practice_count, 3)


class TestA7DifficultyWording(unittest.TestCase):
    def test_heuristic_difficulty_is_labelled_and_unclaimed(self):
        repo = get_repository()
        practice = PracticeEngineAgent(repository=repo)
        resp = practice.assemble_paper(
            AssemblePaperRequest(
                user_id="u_wording", exam_type="NTCE", practice_mode=PracticeMode.DAILY_PRACTICE, item_count=6
            )
        )
        self.assertTrue(resp.questions)
        for payload in resp.questions:
            self.assertEqual(payload["difficulty"]["label"], "教研初估")
            self.assertEqual(payload["difficulty"]["calibration"], "heuristic")
        joined = " ".join(resp.notices)
        for word in UNCALIBRATED_WORDS:
            self.assertNotIn(word, joined)

    def test_gate_method_is_never_a_measurement_claim(self):
        repo = get_repository()
        meta = next(m for m in repo.questions().values() if m.difficulty_method)
        verdict = TrustGate("research_internal").classify_meta(meta)
        self.assertTrue(any("教研初估" in n for n in verdict.notices))


def _sample_state():
    from services.common.models import FSRSState

    return FSRSState(
        stability=1.5,
        difficulty=6.2,
        state="learning",
        reps=1,
        lapses=1,
        due_date=datetime.now(timezone.utc).isoformat(),
    )


if __name__ == "__main__":
    unittest.main()
