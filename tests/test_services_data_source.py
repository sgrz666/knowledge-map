"""Executable acceptance checks for the knowledge facade (docs/agent_architecture.md §8).

A1 no shadow data · A2 real references · A3 quarantine cannot leak ·
A5 state survives across processes · A7 difficulty wording · A11 facade freshness +
byte-offset integrity.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
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


class TestA11FacadeFreshness(unittest.TestCase):
    """A11 门面缓存与字节偏移：盘上的教研改动要能到达运行中的进程，偏移读回来必须仍是那道题。

    数据集是教研直接编辑的文本，门面把索引缓存在进程里。缓存放着不动，"人工复核"就只在重启后生效；
    偏移不做身份校验，一次删行会让判分拿到别人的答案键。两条都用临时根目录复现，不碰真库。
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="km_facade_fresh_")
        self.root = Path(self._tmp)
        self.qdir = self.root / "数据集" / "教资" / "questions"
        self.qdir.mkdir(parents=True)
        self.qfile = self.qdir / "paper1.jsonl"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, *lines: bytes) -> None:
        self.qfile.write_bytes(b"".join(lines))

    def _repo(self) -> KnowledgeRepository:
        # ttl=0：每次读取都复核指纹，测试不等 TTL 窗口。
        return KnowledgeRepository(root=self.root, ttl_seconds=0.0)

    def test_a_reviewer_signing_on_disk_reaches_the_running_facade(self):
        self._write(_qline("q1", answer="A", status="pending_review"))
        repo = self._repo()
        self.assertEqual(repo.get_meta("q1").review_status, "pending_review")

        self._write(_qline("q1", answer="A", status="checked"))
        self.assertEqual(
            repo.get_meta("q1").review_status, "checked", "运行中的门面没看见盘上的教研签署"
        )
        self.assertGreaterEqual(repo.generation, 1, "换代计数没增加，下游缓存不会重建")
        self.assertEqual(repo.load_question("q1")["review"]["status"], "checked")

    def test_a_rubric_signature_on_disk_reaches_the_running_facade(self):
        rubric_dir = self.root / "数据集" / "教资" / "rubrics"
        rubric_dir.mkdir(parents=True)
        path = rubric_dir / "r-demo.json"
        unsigned = {
            "rubric_id": "r-demo",
            "dimensions": [{"name": "要点覆盖", "weight": 1.0}],
            "review": {"status": "llm_enhanced", "checked_by": None, "expert_verified": False},
        }
        path.write_text(json.dumps(unsigned, ensure_ascii=False), encoding="utf-8")
        repo = self._repo()
        gate = TrustGate("research_internal")
        self.assertFalse(gate.classify_rubric(repo.find_rubric(rubric_id="r-demo")).signed)

        signed = dict(
            unsigned,
            review={"status": "checked", "checked_by": "教研-试用", "expert_verified": True},
        )
        path.write_text(json.dumps(signed, ensure_ascii=False), encoding="utf-8")
        verdict = gate.classify_rubric(repo.find_rubric(rubric_id="r-demo"))
        self.assertTrue(verdict.signed, "教研已签署的量规仍被当作未签署，出分会被永久挡住")

    def test_a_shifted_offset_cannot_pass_another_question_off_as_this_one(self):
        first, second, third = (_qline(f"q{i}", answer=letter) for i, letter in ((1, "A"), (2, "B"), (3, "C")))
        self.assertEqual((len(first), len(second), len(third)), (len(second), len(second), len(second)))
        self._write(first, second, third)
        repo = self._repo()
        stale = repo.get_meta("q2")
        self.assertEqual(stale.offset, len(first))

        # 删掉 q1 那一行（真题库里合并套卷就会这么改）：q2 平移到 0，旧偏移正好读回 q3 的整行。
        self._write(second, third)
        raw = self.qfile.read_bytes()
        self.assertEqual(raw[stale.offset : stale.offset + stale.length], third)
        self.assertIsNone(repo._read_range(stale, "q2"), "读回的不是这道题却返回了内容")

        record = repo.load_question("q2")
        self.assertEqual(record["question_id"], "q2")
        self.assertEqual(record["content"]["answer"], "B", "偏移换代重扫之后必须读回本题的答案键")

    def test_a_line_that_stopped_decoding_never_falls_back_to_a_guess(self):
        self._write(_qline("q1", answer="A"))
        repo = self._repo()
        repo.get_meta("q1")
        self.qfile.write_bytes(b'{"question_id": "q9", "content"')
        self.assertIsNone(repo.load_question("q1"), "读不回原题时宁可报读不到，绝不返回别的记录")
        self.assertTrue(
            any("paper1.jsonl" in issue for issue in repo._scan_errors),
            "坏行没登记成缺口，等于把数据事故咽下去",
        )

    def test_a_stale_offset_is_remmeasured_instead_of_being_trusted(self):
        """TTL 窗口内没复核到改动时，读回来的身份校验要把索引换代补上。"""
        first, second, third = (
            _qline(f"q{i}", answer=letter) for i, letter in ((1, "A"), (2, "B"), (3, "C"))
        )
        self._write(first, second, third)
        repo = KnowledgeRepository(root=self.root, ttl_seconds=3600)
        repo.get_meta("q2")  # 建立指纹基线，之后 TTL 内不再复核

        self._write(second, third)  # 删掉首行：q2 的旧偏移现在整段落在 q3 上
        record = repo.load_question("q2")
        self.assertEqual(record["question_id"], "q2")
        self.assertEqual(record["content"]["answer"], "B", "偏移失效后必须重扫，而不是把 q3 交出去")
        self.assertEqual(repo.get_meta("q2").offset, 0)

    def test_a_malformed_line_does_not_take_the_rest_of_the_file_down(self):
        self._write(
            _qline("q1", answer="A"),
            b'{"question_id": "q2", "content": {"stem": "\n',
            _qline("q3", answer="C"),
        )
        repo = self._repo()
        self.assertEqual(sorted(repo.questions()), ["q1", "q3"])
        self.assertEqual(repo.stats()["scan_issues"], 1, "坏行没登记成缺口，等于把数据事故咽下去")
        self.assertEqual(repo.load_question("q3")["content"]["answer"], "C")


def _qline(question_id: str, *, answer: str, status: str = "llm_enhanced") -> bytes:
    """一条最小可用的真题记录：题面/答案键/复核状态齐备，只用于临时根目录。"""
    record = {
        "question_id": question_id,
        "exam": "NTCE",
        "module": "综合素质",
        "content": {
            "stem": f"{question_id}：下列关于教师职业道德的表述，正确的一项是。",
            "answer": answer,
            "answer_status": "letter_only",
        },
        "review": {"status": status},
        "knowledge_node_ids": ["n-demo"],
        "difficulty": {"value": 0.4, "method": "教研初估"},
    }
    return json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"


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
