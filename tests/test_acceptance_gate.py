"""可执行验收 A1–A9（docs/agent_architecture.md §8），一条验收一个测试。

文档要求"每条都是测试，不是形容词"，所以这里每个测试的 docstring 直接抄文档原文，断言只允许引用两类
证据：`数据集/**` 与 `官方权威资料/**` 里的实体本身，或调用方自己送进来的文本。测试不写死任何题号、
分值或条数——那些都会随库变化，写死就等于把影子数据搬进测试。

回归总闸（文档 §8 最后一行）在测试之外跑：
``python -m pytest tests -q``、``审查/validate_kb.py``、``审查/状态词表检查.py``。
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 学习者的 FSRS 状态绝不能写进仓库的 .local_state/。必须在导入任何 service 之前设好。
os.environ.setdefault("KNOWLEDGE_MAP_STATE_DIR", tempfile.mkdtemp(prefix="km_acceptance_state_"))

from starlette.testclient import TestClient  # noqa: E402

from services.app import app  # noqa: E402
from services.common.models import (  # noqa: E402
    AgentMessageEnvelope,
    ErrorReviewEvent,
    MasterInteractionRequest,
    PlanRequest,
    PracticeMode,
    QARequest,
    SubjectiveGradingRequest,
    TrustTier,
)
from services.grader.agent import SubjectiveGraderAgent  # noqa: E402
from services.knowledge.graph_index import (  # noqa: E402
    ALLOWED_EDGE_TYPES,
    PREREQUISITE_DISABLED_NOTICE,
    GraphIndex,
    UnknownEdgeTypeError,
    get_graph_index,
)
from services.knowledge.naming import exam_values  # noqa: E402
from services.knowledge.repository import QUESTION_DIRS, REQUIREMENT_FILES, get_repository  # noqa: E402
from services.knowledge.retrieval import RESEARCH_ANSWER_STATUSES, RetrievalService  # noqa: E402
from services.knowledge.trust import TrustGate  # noqa: E402
from services.knowledge.vector_index import SearchHit, get_card_index  # noqa: E402
from services.llm.guardrails import scan_banned_claims  # noqa: E402
from services.master.agent import TutorMasterAgent  # noqa: E402
from services.planner.agent import CurriculumPlannerAgent  # noqa: E402
from services.review.queue import ReviewQueue, get_review_queue  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = REPO_ROOT / "services"

# A1 原文点名的两个影子数据常量名。
BANNED_SHADOW_NAMES = ("SAMPLE_QUESTION_BANK", "PROVENANCE_DB")

# "中文题面形态"的可执行判据：只有真题/条文正文才会长这样——填空括号、带序号的并列选项、
# 答案/解析块。运行时里的提示语和 notice 都不含这些形状，所以判据不会误伤文案。
STEM_SHAPES = (
    re.compile(r"（\s*）|\(\s*\)"),
    re.compile(r"[A-D][．.、]\s*\S+.*[A-D][．.、]\s*\S+", re.DOTALL),
    re.compile(r"【答案】|【解析】|答案\s*[:：]\s*\**\s*[A-D](?![A-Za-z])"),
)

#: 卡片正文里的答案行：`**答案:** 未提供` 是合规形状，`**答案:D**` 就是断言了具体答案。
ANSWER_LINE = re.compile(r"^\*\*答案.*$", re.MULTILINE)
ANSWER_LETTER = re.compile(r"[A-D](?![A-Za-z])")


def stem_shape(text: str) -> str:
    for pattern in STEM_SHAPES:
        if pattern.search(text):
            return pattern.pattern
    return ""


def _tmp_queue() -> ReviewQueue:
    return ReviewQueue(root=Path(tempfile.mkdtemp(prefix="km_acceptance_queue_")))


class AcceptanceTestCase(unittest.TestCase):
    """One shared index for every item; ids always come out of the library, never by hand."""

    @classmethod
    def setUpClass(cls):
        cls.repository = get_repository()
        cls.client = TestClient(app)

    def setUp(self):
        self.queue = _tmp_queue()

    # ---------------------------------------------------------------- sources
    @staticmethod
    def service_sources():
        for path in sorted(SERVICES_DIR.rglob("*.py")):
            yield path, path.read_text(encoding="utf-8")

    # ---------------------------------------------------------------- lookups
    def usable_choice(self):
        for meta in self.repository.find_questions(
            exams=("NTCE",), answer_statuses=("letter_only",), require_nodes=True
        ):
            if meta.review_status != "quarantined" and meta.difficulty is not None:
                return meta
        self.skipTest("库内没有可用于验收的单选题")

    def conflicted(self):
        for meta in self.repository.find_questions(answer_statuses=("source_conflict",)):
            return meta
        self.skipTest("库内没有 source_conflict 题")

    def missing_answer(self):
        for meta in self.repository.find_questions(answer_statuses=("missing",), require_nodes=True):
            return meta
        self.skipTest("库内没有 missing 答案题")

    def with_citable_requirement(self):
        for meta in self.repository.find_questions(exams=("NTCE",), require_nodes=True):
            if meta.requirement_ids:
                record = self.repository.load_question(meta.question_id) or {}
                for rid in record.get("exam_requirement_ids") or []:
                    requirement = self.repository.get_requirement(rid)
                    if requirement and TrustGate("research_internal").classify_requirement(requirement).citable:
                        return meta, rid
        self.skipTest("库内没有挂可引用权威条款的题目")


# --------------------------------------------------------------------- A1
class TestA1NoShadowData(AcceptanceTestCase):
    """A1 无影子数据：services/**.py 中不得出现题面/条文常量。"""

    def test_no_shadow_constants_and_no_stem_shaped_literals(self):
        banned, offenders = [], []
        for path, source in self.service_sources():
            relative = path.relative_to(REPO_ROOT).as_posix()
            for name in BANNED_SHADOW_NAMES:
                if name in source:
                    banned.append(f"{relative}: {name}")
            for node in ast.walk(ast.parse(source)):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                text = node.value
                if len(text) > 40:
                    shape = stem_shape(text)
                    if shape:
                        offenders.append(f"{relative}:{node.lineno}: /{shape}/")
        self.assertEqual(banned, [], "影子数据常量名又回来了")
        self.assertEqual(offenders, [], "服务层里出现题面/条文形态的字符串常量")

    def test_the_shape_detector_is_not_vacuous(self):
        """阴性对照：判据必须能抓住真题库里的题面，否则上一条测试是空跑。"""
        caught = 0
        for index, meta in enumerate(self.repository.find_questions(exams=("NTCE",))):
            if index >= 40:
                break
            record = self.repository.load_question(meta.question_id) or {}
            content = record.get("content") or {}
            text = json.dumps({"stem": content.get("stem"), "options": content.get("options")}, ensure_ascii=False)
            if len(text) > 40 and stem_shape(text):
                caught += 1
        self.assertGreater(caught, 0, "题面形态判据对真实题库文本零命中，A1 扫描无效")


# --------------------------------------------------------------------- A2
class TestA2RealReferences(AcceptanceTestCase):
    """A2 真实引用：组卷题号命中题目索引，答疑溯源命中 requirements.jsonl。"""

    def test_assembled_ids_hit_the_byte_offset_question_index(self):
        response = self.client.post(
            "/api/v1/practice/assemble",
            json={
                "user_id": "u_a2",
                "exam_type": "NTCE",
                "practice_mode": PracticeMode.DAILY_PRACTICE.value,
                "item_count": 5,
            },
        )
        self.assertEqual(response.status_code, 200)
        questions = response.json()["questions"]
        self.assertTrue(questions, "research_internal 档必须能组出真题")
        index = self.repository.questions()
        for question in questions:
            question_id = question["question_id"]
            meta = index.get(question_id)
            self.assertIsNotNone(meta, f"{question_id} 不在题目索引里")
            self.assertTrue(
                any(meta.file.startswith(directory) for directory in QUESTION_DIRS),
                f"{meta.file} 不在 数据集/**/questions 之下",
            )
            self.assertGreaterEqual(meta.offset, 0)
            self.assertGreater(meta.length, 0)
            # 偏移量能读回同一条原文，索引才不是摆设。
            record = self.repository.load_question(question_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.get("question_id") or question_id, question_id)
            self.assertEqual(question["stem"], ((record or {}).get("content") or {}).get("stem")
                             or (record or {}).get("text") or question["stem"])

    def test_qa_provenance_resolves_against_the_authoritative_clause_file(self):
        meta, requirement_id = self.with_citable_requirement()
        requirement = self.repository.get_requirement(requirement_id)
        response = self.client.post(
            "/api/v1/qa/query",
            json={
                "user_id": "u_a2",
                "question_id": meta.question_id,
                "mode": "sparks_three_chain",
                "user_selected_option": "A",
            },
        )
        self.assertEqual(response.status_code, 200)
        clauses = response.json()["knowledge_provenance"]["requirements"]
        self.assertTrue(clauses, "答疑溯源必须给出条款级引用")
        cited_ids = {clause["requirement_id"] for clause in clauses}
        self.assertIn(requirement_id, cited_ids)
        for clause in clauses:
            stored = self.repository.get_requirement(clause["requirement_id"])
            self.assertIsNotNone(stored, f"{clause['requirement_id']} 不在权威条款索引内")
            self.assertEqual(clause["content"], stored["content"], "引用文本必须与条款实体逐字一致")
            self.assertEqual(clause["locator"], stored["locator"], "引用必须带回原文定位")
            self.assertTrue(stored["locator"], "条款实体没有 locator")
        self.assertTrue(any(Path(REPO_ROOT / rel).is_file() for rel in REQUIREMENT_FILES))


# --------------------------------------------------------------------- A3
class TestA3QuarantineCannotLeak(AcceptanceTestCase):
    """A3 隔离不可漏：quarantined / source_conflict / missing 永不出现在组卷、判分与向量召回。"""

    def _stub_index(self, hits):
        class StubCards:
            backend = "stub"

            def __init__(self, docs):
                self.docs = docs

            def search(self, query, *, libraries, k, filters):
                return [hit for hit in self.docs if hit.library in libraries][:k]

            def notices(self):
                return []

        return StubCards(hits)

    def _hit(self, meta, library="ntce"):
        return SearchHit(
            question_id=meta.question_id,
            library=library,
            score=0.9,
            path=f"数据集/{library}/cards/{meta.question_id}.md",
            metadata={
                "review_status": meta.review_status or "",
                "answer_status": meta.answer_status or "",
                "node_ids": ",".join(meta.node_ids),
                "requirement_ids": ",".join(meta.requirement_ids),
            },
            snippet="",
        )

    def test_conflicted_and_missing_items_never_reach_a_paper(self):
        blocked_ids = [self.conflicted().question_id, self.missing_answer().question_id]
        response = self.client.post(
            "/api/v1/practice/assemble",
            json={
                "user_id": "u_a3",
                "exam_type": "NTCE",
                "practice_mode": PracticeMode.ERROR_ELIMINATION.value,
                "wrong_question_ids": blocked_ids,
                "item_count": 5,
            },
        )
        served = [question["question_id"] for question in response.json()["questions"]]
        for question_id in blocked_ids:
            self.assertNotIn(question_id, served)

    def test_the_recall_gate_refuses_a_similarity_hit_on_isolated_content(self):
        conflicted = self.conflicted()
        usable = self.usable_choice()
        service = RetrievalService(
            repository=self.repository,
            card_index=self._stub_index([self._hit(conflicted), self._hit(usable)]),
            queue=self.queue,
        )
        result = service.search("非洲荒漠化成因", exam="NTCE", use_graph=False, user_id="u_a3")
        candidates = [candidate["question_id"] for candidate in result["candidates"]]
        self.assertNotIn(conflicted.question_id, candidates)
        self.assertIn(usable.question_id, candidates)
        self.assertEqual([row["question_id"] for row in result["blocked"]], [conflicted.question_id])
        # 召回过滤词表本身也不给隔离状态留口子。
        self.assertNotIn("source_conflict", RESEARCH_ANSWER_STATUSES)
        self.assertNotIn("missing", RESEARCH_ANSWER_STATUSES)

    def test_grading_an_isolated_item_refuses_and_asserts_no_answer(self):
        conflicted = self.conflicted()
        record = self.repository.load_question(conflicted.question_id) or {}
        stored_answer = json.dumps((record.get("content") or {}).get("answer"), ensure_ascii=False)
        response = SubjectiveGraderAgent(
            repository=self.repository, review_queue=self.queue
        ).grade(
            SubjectiveGradingRequest(
                question_id=conflicted.question_id,
                exam_type="NTCE",
                task_type="case_analysis",
                stem=((record.get("content") or {}).get("stem") or "")[:120],
                student_answer="该教师的做法值得肯定。",
            )
        )
        self.assertIsNone(response.total_score)
        self.assertTrue(response.feedback_only)
        self.assertEqual(response.score_basis, "none")
        self.assertEqual(response.review_status, "quarantined_for_human")
        dumped = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
        if stored_answer not in ("null", '""', "[]", "{}"):
            self.assertNotIn(stored_answer.strip('"'), dumped, "被隔离题的库内答案不得出现在判分响应里")

    def test_isolated_cards_bodies_carry_no_concrete_answer(self):
        """卡片正文也不确定答案：数据侧同源，运行时才有得可拦。"""
        conflicted_seen = clean_seen = 0
        for card in get_card_index().iter_cards("ntce"):
            lines = ANSWER_LINE.findall(card.text)
            conflicted = card.metadata.get("answer_status") == "source_conflict"
            if conflicted:
                conflicted_seen += 1
                for line in lines:
                    self.assertIsNone(
                        ANSWER_LETTER.search(line),
                        f"{card.path} 的卡片正文断言了具体答案：{line}",
                    )
            elif any(ANSWER_LETTER.search(line) for line in lines):
                clean_seen += 1
            if conflicted_seen >= 5 and clean_seen >= 1:
                break
        self.assertGreaterEqual(conflicted_seen, 1, "库里没有 source_conflict 卡片，检查失去意义")
        self.assertGreaterEqual(clean_seen, 1, "正常卡片也没有答案形状，说明判据已失效")

    def test_the_paper_never_asks_the_learner_to_answer_a_blank_stem(self):
        """组卷池只统计真能作答的题：只剩套名/题号的抽取缺口既不入卷面，也不计入 pool_size。"""
        gate = TrustGate("research_internal")
        for exam_type in ("CET-6", "CET-4", "NTCE"):
            exams = exam_values(exam_type)
            answered = list(self.repository.find_questions(exams=exams, require_answer=True))
            gap = [m for m in answered if not m.has_answerable_text]
            response = self.client.post(
                "/api/v1/practice/assemble",
                json={
                    "user_id": f"u_a3_{exam_type}",
                    "exam_type": exam_type,
                    "practice_mode": PracticeMode.DAILY_PRACTICE.value,
                    "item_count": 10,
                },
            ).json()
            for question in response["questions"]:
                self.assertTrue(
                    (question["stem"] or "").strip(" 　、,，.。0123456789") or question["options"],
                    f"{question['question_id']} 只有套名/题号，却送进了卷面",
                )
            expected = sum(
                1 for m in answered if m.has_answerable_text and gate.classify_meta(m).usable
            )
            self.assertEqual(response["pool_size"], expected, f"{exam_type} 的池子把不可作答的题算进了题量")
            if gap:
                self.assertTrue(
                    any("套名与题号" in notice for notice in response["notices"]),
                    f"{exam_type} 有 {len(gap)} 题只剩套名却没有暴露抽取缺口",
                )

    def test_a_blank_stem_item_is_refused_even_as_a_known_wrong_question(self):
        gap_item = next(
            (
                m
                for m in self.repository.find_questions(exams=exam_values("CET-6"))
                if not m.has_answerable_text
                and m.answer_status in ("letter_only", "reference_only")
            ),
            None,
        )
        if gap_item is None:
            self.skipTest("CET-6 题干抽取缺口已补齐")
        served = [
            question["question_id"]
            for question in self.client.post(
                "/api/v1/practice/assemble",
                json={
                    "user_id": "u_a3_blank",
                    "exam_type": "CET-6",
                    "practice_mode": PracticeMode.ERROR_ELIMINATION.value,
                    "wrong_question_ids": [gap_item.question_id],
                    "item_count": 5,
                },
            ).json()["questions"]
        ]
        self.assertNotIn(gap_item.question_id, served)


# --------------------------------------------------------------------- A4
class TestA4NoScoreWithoutSignature(AcceptanceTestCase):
    """A4 判分不冒充：量规无署名时 score=null、feedback_only=true，且状态不得被推进。"""

    def _rubric_from_disk(self, rubric):
        source = rubric["rubric_source"]
        path = REPO_ROOT / source
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        for line in path.read_bytes().splitlines():
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if record.get("rubric_id") == rubric["rubric_id"]:
                return record
        self.fail(f"{rubric['rubric_id']} 在 {source} 里找不到了")

    def test_every_library_rubric_scores_only_after_a_human_signature(self):
        gate = TrustGate("research_internal")
        grader = SubjectiveGraderAgent(repository=self.repository, review_queue=self.queue)
        library_ids = {}
        for exam in ("NTCE", "CET-4"):
            # A4 讲的是"已可判分的题在未签署量规下不出分"，所以选题必须走 A3 那一套可用口径：
            # 有答案状态、有真题面，否则 agent 层会先因输入缺口拒判，测不到签署这道闸。
            for meta in self.repository.find_questions(
                exams=(exam,), require_nodes=True, require_answer=True, require_answerable_text=True
            ):
                library_ids[exam] = meta.question_id
                break
        seen = 0
        for rubric_id, rubric in self.repository.rubrics().items():
            exam = (rubric.get("exams") or ["NTCE"])[0]
            verdict = gate.classify_rubric(rubric)
            response = grader.grade(
                SubjectiveGradingRequest(
                    question_id=library_ids.get(exam) or library_ids["NTCE"],
                    exam_type=exam,
                    task_type=rubric.get("task_type") or "case_analysis",
                    stem="评析材料中教师的做法，并给出改进建议。",
                    student_answer="我从头到尾讲了一遍知识点，没有互动。",
                    rubric_id=rubric_id,
                )
            )
            seen += 1
            if verdict.may_score:
                continue  # 教研签署之后才允许出分；当前库内没有这种量规
            self.assertIsNone(response.total_score, f"{rubric_id} 未签署却出了分")
            self.assertTrue(response.feedback_only, f"{rubric_id} 未签署却不是纯反馈")
            self.assertEqual(response.score_basis, "unsigned_framework")
            self.assertFalse(response.rubric_signed)
            self.assertNotIn(response.review_status, ("checked", "expert_reviewed"))
            self.assertIsNotNone(response.review_queue_entry)
            # 运行时不改库：磁盘上的量规状态不会因为一次判分而推进或被代签。
            on_disk = self._rubric_from_disk(rubric)
            status = (on_disk.get("review") or {}).get("status") or on_disk.get("status")
            self.assertNotIn(status, ("checked", "expert_reviewed"), f"{rubric_id} 被脚本推进了状态")
            self.assertFalse((on_disk.get("review") or {}).get("checked_by") or on_disk.get("checked_by"))
        self.assertEqual(seen, len(self.repository.rubrics()), "并非所有量规都跑过一遍")


# --------------------------------------------------------------------- A5
class TestA5StateSurvivesAcrossProcesses(AcceptanceTestCase):
    """A5 状态持久：两个独立进程共享同一状态目录时，GET /memory/mastery/{user}/{node} 必须命中。"""

    CHILD = (
        "import json, sys\n"
        "from starlette.testclient import TestClient\n"
        "from services.app import app\n"
        "client = TestClient(app)\n"
        "event = json.loads(sys.stdin.read())\n"
        "response = client.post('/api/v1/memory/review', json=event)\n"
        "print(json.dumps({'status': response.status_code, "
        "'mastery': response.json().get('updated_mastery', {}).get('mastery_score')}))\n"
    )

    def test_a_write_from_another_process_is_readable_here(self):
        from services.memory.store import default_store

        meta = self.usable_choice()
        node_id = meta.node_ids[0]
        user_id = f"u_a5_{abs(hash(node_id)) % 10_000:04d}"
        self.assertEqual(self.client.get(f"/api/v1/memory/mastery/{user_id}/{node_id}").status_code, 404)
        script = Path(tempfile.mkdtemp(prefix="km_acceptance_child_")) / "child_write.py"
        script.write_text(self.CHILD, encoding="utf-8")
        # 共享的是这个进程真正在用的状态目录，而不是测试模块自己临时生成的那一个。
        store_dir = str(Path(default_store().path).parent)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(REPO_ROOT),
                   KNOWLEDGE_MAP_STATE_DIR=store_dir)
        event = ErrorReviewEvent(
            user_id=user_id,
            question_id=meta.question_id,
            node_id=node_id,
            exam="NTCE",
            is_correct=False,
            time_spent_seconds=12.0,
            selected_option="A",
            correct_option="C",
        ).model_dump(mode="json")
        completed = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(REPO_ROOT),
            timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["status"], 200, "另一个进程没能写入共享状态目录")

        response = self.client.get(f"/api/v1/memory/mastery/{user_id}/{node_id}")
        self.assertEqual(response.status_code, 200, "跨进程写入的画像在本进程读不到")
        record = response.json()
        self.assertEqual(record["user_id"], user_id)
        self.assertEqual(record["node_id"], node_id)
        self.assertEqual(record["practice_count"], 1)
        self.assertIn(record["fsrs_state"]["state"], ("learning", "review", "relearning"))

    def test_the_shared_state_is_a_real_file_not_process_memory(self):
        from services.memory.store import SqliteMasteryStore, default_store

        store = default_store()
        self.assertIsInstance(store, SqliteMasteryStore, "默认画像存储不是 SQLite 实现，跨进程共享无从谈起")
        self.assertTrue(Path(store.path).is_file(), "默认画像存储没有落盘文件，跨进程共享无从谈起")


# --------------------------------------------------------------------- A6
class TestA6EdgeVocabulary(AcceptanceTestCase):
    """A6 边名白名单：词表外边名即抛错；先修边未核定不得进入 planner 排序。"""

    class _BadRepo:
        def graph_records(self, library):
            return (
                [{"id": "n1", "layer": "L1", "type": "module", "name": "测试模块"}],
                [{"type": "depends_on", "src": "n1", "dst": "n1", "verified": True}],
            )

    def test_an_edge_name_outside_the_16_vocabulary_fails_the_build(self):
        self.assertEqual(len(ALLOWED_EDGE_TYPES), 16, "边名词表长度变了，必须先复核数据契约")
        index = GraphIndex("ntce", repository=self._BadRepo())  # type: ignore[arg-type]
        with self.assertRaises(UnknownEdgeTypeError):
            index.graph

    def test_the_library_itself_only_uses_whitelisted_edges(self):
        for library in ("ntce", "cet"):
            stats = get_graph_index(library).stats()
            self.assertGreater(stats["edges"], 0, f"{library} 图谱为空，白名单检查失去意义")
            self.assertTrue(set(stats["edge_types"]).issubset(set(ALLOWED_EDGE_TYPES)))
            self.assertEqual(stats["allowed_edge_types"], list(ALLOWED_EDGE_TYPES))

    def test_unapproved_prerequisites_cannot_reorder_or_block(self):
        graph = get_graph_index("ntce")
        self.assertFalse(graph.prerequisites_active)
        self.assertEqual(graph.prerequisite_pairs(), [], "有 prerequisite_of 被当作已核定，先修阻断会静默生效")
        wanted = [meta.node_ids[0] for meta in list(self.repository.find_questions(exams=("NTCE",), require_nodes=True))[:4]]
        ordered, notice = graph.topological_order(wanted)
        self.assertEqual(ordered, wanted, "先修未核定时排序必须保持原序")
        self.assertEqual(notice, PREREQUISITE_DISABLED_NOTICE)

        plan = CurriculumPlannerAgent().generate_plan(PlanRequest(user_id="u_a6", exam_type="NTCE"))
        self.assertIn(PREREQUISITE_DISABLED_NOTICE, "".join(plan.notices) + plan.prerequisite_note)


# --------------------------------------------------------------------- A7
class TestA7DifficultyWording(AcceptanceTestCase):
    """A7 难度措辞：heuristic_* 一律标"教研初估"，未校准路径输出里不得出现 IRT/CAT/标准误。"""

    def test_difficulty_labels_and_values_come_from_the_index(self):
        for exam in ("NTCE", "CET-6"):
            response = self.client.post(
                "/api/v1/practice/assemble",
                json={
                    "user_id": "u_a7",
                    "exam_type": exam,
                    "practice_mode": PracticeMode.DAILY_PRACTICE.value,
                    "item_count": 8,
                },
            )
            questions = response.json()["questions"]
            self.assertTrue(questions, f"{exam} research_internal 档应能组卷")
            for question in questions:
                meta = self.repository.get_meta(question["question_id"])
                difficulty = question["difficulty"]
                self.assertEqual(difficulty["value"], meta.difficulty, "难度值必须回读索引，缺失就报缺失")
                self.assertEqual(difficulty["method"], meta.difficulty_method)
                if str(meta.difficulty_method or "").startswith("heuristic"):
                    self.assertEqual(difficulty["calibration"], "heuristic")
                    self.assertEqual(difficulty["label"], "教研初估")

    def test_no_uncalibrated_path_output_claims_a_psychometric_quantity(self):
        from services.common.models import DiagnosticRequest
        from services.diagnostic.agent import DiagnosticAgent
        from services.qa.agent import TutorQAAgent

        meta = self.usable_choice()
        texts = []
        report = DiagnosticAgent(repository=self.repository).evaluate(
            DiagnosticRequest(user_id="u_a7", exam_type="NTCE")
        )
        texts += list(report.notices) + list(report.recommended_actions)
        texts += CurriculumPlannerAgent().generate_plan(PlanRequest(user_id="u_a7", exam_type="NTCE")).notices
        texts += self.client.post(
            "/api/v1/practice/assemble",
            json={"user_id": "u_a7", "exam_type": "NTCE",
                  "practice_mode": PracticeMode.DAILY_PRACTICE.value, "item_count": 3},
        ).json()["notices"]
        texts += self.client.post(
            "/api/v1/qa/query",
            json={"user_id": "u_a7", "question_id": meta.question_id, "mode": "sparks_three_chain"},
        ).json()["notices"]
        master = TutorMasterAgent(queue=self.queue).handle_interaction(
            MasterInteractionRequest(user_id="u_a7", message="先做一次学情摸底再给我计划", exam_type="NTCE")
        )
        texts.append(master.reply_text)
        graded = SubjectiveGraderAgent(repository=self.repository, review_queue=self.queue).grade(
            SubjectiveGradingRequest(
                question_id=meta.question_id, exam_type="NTCE", task_type="case_analysis",
                stem="评析材料。", student_answer="我的作答。",
            )
        )
        texts += list(graded.notices) + [graded.evaluation_summary, graded.revision_advice]
        self.assertTrue([t for t in texts if t], "响应文本为空，扫描等于没跑")
        for text in texts:
            self.assertEqual(scan_banned_claims(str(text)), [], f"未校准路径输出里出现禁用声称：{text[:80]}")


# --------------------------------------------------------------------- A8
class TestA8ClosedLoop(AcceptanceTestCase):
    """A8 编排闭环：一条会话跑完 诊断→画像→规划→刷题→归因→回写，每步消息都是 AgentMessageEnvelope。"""

    SPINE = [
        "diagnostic.evaluate",
        "memory.profile",
        "planner.generate",
        "practice.assemble",
        "memory.attribute",
        "memory.profile",
    ]

    def test_one_session_runs_six_stages_and_every_hop_is_an_envelope(self):
        meta = self.usable_choice()
        record = self.repository.load_question(meta.question_id) or {}
        key = ((record.get("content") or {}).get("answer") or "A").strip().upper()[:1]
        wrong = "B" if key != "B" else "C"
        user_id = f"u_a8_{abs(hash(meta.question_id)) % 10_000:04d}"
        agent = TutorMasterAgent(queue=self.queue)

        response = agent.handle_interaction(
            MasterInteractionRequest(
                user_id=user_id,
                message="先做一次学情摸底，然后给我计划和练习",
                exam_type="NTCE",
                action_payload={
                    "question_id": meta.question_id,
                    "node_id": meta.node_ids[0],
                    "selected_option": wrong,
                },
            )
        )
        actions = [row["action"] for row in response.trace]
        self.assertEqual(actions, self.SPINE, "六阶段闭环没有跑满")

        rows = agent.trace_of(response.session_id)
        self.assertEqual([row["envelope"]["action"] for row in rows], actions)
        self.assertEqual([row["seq"] for row in rows], list(range(1, len(actions) + 1)))
        for row in rows:
            envelope = AgentMessageEnvelope.model_validate(row["envelope"])
            self.assertEqual(envelope.sender, "orchestrator")
            self.assertIn(envelope.trust_tier, ("research_internal", "published"))

        # 回写是真的回写：这个用户在这个考点上有了一条记录，且来自库内答案键的判错。
        mastery = agent.memory.get_user_mastery(user_id, meta.node_ids[0])
        self.assertIsNotNone(mastery, "归因之后没有写回学习者状态")
        self.assertEqual(mastery.practice_count, 1)
        attribut_card = response.card_data
        self.assertTrue(attribut_card)
        self.assertEqual(self.queue.stats()["pending_records"], 0,
                         "闭环本身不产生内容缺陷，不该占用教研队列")


# --------------------------------------------------------------------- A9
class TestA9HumanInTheLoop(AcceptanceTestCase):
    """A9 人工不旁路：任何 Verdict.blocked_reasons 非空的请求都要在 /review/queue 留下可复核记录。"""

    class _StubCards:
        backend = "stub"

        def __init__(self, docs):
            self.docs = docs

        def search(self, query, *, libraries, k, filters):
            return [hit for hit in self.docs if hit.library in libraries][:k]

        def notices(self):
            return []

    def _hit(self, meta):
        return SearchHit(
            question_id=meta.question_id,
            library="ntce",
            score=0.8,
            path=f"数据集/教资/cards/{meta.question_id}.md",
            metadata={
                "review_status": meta.review_status or "",
                "answer_status": meta.answer_status or "",
                "node_ids": ",".join(meta.node_ids),
                "requirement_ids": ",".join(meta.requirement_ids),
            },
            snippet="",
        )

    def test_each_gate_refusal_writes_exactly_one_reviewable_row(self):
        conflicted = self.conflicted()
        verdict = TrustGate("research_internal").classify_record(
            self.repository.load_question(conflicted.question_id) or {}
        )
        self.assertFalse(verdict.usable)
        self.assertTrue(verdict.notices, "拒绝却不给理由，队列里就无从复核")

        service = RetrievalService(
            repository=self.repository,
            card_index=self._StubCards([self._hit(conflicted)]),
            queue=self.queue,
        )
        before = self.queue.stats()["pending_records"]
        result = service.search("荒漠化成因", exam="NTCE", use_graph=False, user_id="u_a9")
        self.assertEqual(len(result["blocked"]), 1)
        self.assertEqual(result["review_queued"], len(result["blocked"]))
        rows = [
            row for row in self.queue.recent(limit=50) if row["question_id"] == conflicted.question_id
        ]
        self.assertEqual(len(rows), 1, "一次拒绝留下一条记录，不许多也不许少")
        row = rows[0]
        self.assertEqual(row["status"], "pending_human_review")
        self.assertIsNone(row["checked_by"], "运行时代签 = 旁路人工")
        self.assertFalse(row["expert_verified"])
        self.assertEqual(row["user_id"], "u_a9")
        self.assertTrue(row["reason"])
        self.assertEqual(self.queue.stats()["pending_records"], before + 1)

    def test_the_endpoint_shows_the_row_the_runtime_queued(self):
        """队列可复核：GET /review/queue 必须看得见运行时刚写下的那条。"""
        conflicted = self.conflicted()
        queue = get_review_queue()
        before = queue.stats()["pending_records"]
        service = RetrievalService(
            repository=self.repository,
            card_index=self._StubCards([self._hit(conflicted)]),
            queue=queue,
        )
        service.search("荒漠化成因", exam="NTCE", use_graph=False, user_id="u_a9_view")
        view = TestClient(app).get("/api/v1/review/queue")
        self.assertEqual(view.status_code, 200)
        self.assertEqual(view.json()["stats"]["pending_records"], before + 1)
        pending = view.json()["pending"]
        row = next((item for item in pending if item["question_id"] == conflicted.question_id), None)
        self.assertIsNotNone(row, "拒绝记录没有出现在教研的复核入口里")
        self.assertEqual(row["status"], "pending_human_review")
        self.assertIsNone(row["checked_by"])

    def test_an_unsigned_rubric_refusal_also_queues(self):
        meta = self.usable_choice()
        record = self.repository.load_question(meta.question_id) or {}
        grader = SubjectiveGraderAgent(repository=self.repository, review_queue=self.queue)
        response = grader.grade(
            SubjectiveGradingRequest(
                question_id=meta.question_id,
                exam_type="NTCE",
                task_type="case_analysis",
                stem=((record.get("content") or {}).get("stem") or "评析材料。"),
                student_answer="我的作答文本。",
            )
        )
        self.assertIsNone(response.total_score)
        rows = self.queue.recent(limit=50)
        self.assertTrue(rows, "未签署出反馈没有落队列")
        self.assertEqual(rows[0]["reason"], "rubric_signature_required")
        self.assertIsNone(rows[0]["checked_by"])

    def test_a_caller_input_gap_does_not_implicate_the_reviewer(self):
        """反向不变量：只有教研能裁决的缺陷才进队列，使用者补齐的缺口不算。"""
        before = self.queue.stats()["pending_records"]
        response = TutorMasterAgent(queue=self.queue).handle_interaction(
            MasterInteractionRequest(user_id="u_a9_gap", message="请帮我批改一下我的材料分析主观题答案", exam_type="NTCE")
        )
        self.assertEqual(set(response.card_data["missing_inputs"]), {"answer_text", "question_id"})
        self.assertEqual(self.queue.stats()["pending_records"], before)


if __name__ == "__main__":
    unittest.main()
