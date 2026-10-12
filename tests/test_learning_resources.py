"""Learning guides are traceable research drafts, separate from the question pool."""
from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path

from services.knowledge.repository import KnowledgeRepository


ROOT = Path(__file__).resolve().parents[1]
GUIDES = "数据集/教资/resources/study_guides.jsonl"
EXPECTED = {
    "ntce.chuzhong.lishi.s3.k01": "ntce.outline.310",
    "ntce.chuzhong.shengwu.s3.k01": "ntce.outline.308",
    "ntce.chuzhong.tiyu.s3.k04": "ntce.outline.313",
    "ntce.chuzhong.wuli.s3.k01": "ntce.outline.306",
    "ntce.chuzhong.xinxi.s3.k01": "ntce.outline.315",
    "ntce.gaozhong.wuli.s3.k01": "ntce.outline.406",
    "ntce.gaozhong.yinyue.s3.k01": "ntce.outline.412",
}


class TestLearningResources(unittest.TestCase):
    def read_guides(self):
        self.assertTrue((ROOT / GUIDES).is_file(), "seven source-backed guides must exist")
        return [json.loads(line) for line in (ROOT / GUIDES).read_text(encoding="utf-8").splitlines() if line.strip()]

    def resources(self, repository=None):
        module = importlib.import_module("services.knowledge.learning_resources")
        return module.LearningResources(repository=repository or KnowledgeRepository(ROOT))

    def test_seven_target_nodes_have_substantive_guides_and_fourteen_self_checks(self):
        guides = self.read_guides()
        self.assertEqual({r["node_id"] for r in guides}, set(EXPECTED))
        self.assertEqual(len(guides), 7)
        nodes, _ = KnowledgeRepository(ROOT).graph_records("ntce")
        known_nodes = {r["id"]: r for r in nodes}
        exercises = []
        for guide in guides:
            node_id = guide["node_id"]
            self.assertEqual(known_nodes[node_id]["type"], "knowledge_node")
            self.assertEqual(guide["school_level"], node_id.split(".")[1])
            self.assertEqual(guide["subject"], node_id.split(".")[2])
            self.assertGreaterEqual(len(guide["concept_explanation"]), 3)
            self.assertGreater(len(guide["subject_context"]), 40)
            self.assertGreaterEqual(len(guide["answer_structure"]), 4)
            self.assertGreaterEqual(len(guide["self_checks"]), 2)
            for exercise in guide["self_checks"]:
                self.assertGreater(len(exercise["prompt"]), 35)
                self.assertGreaterEqual(len(exercise["reference_points"]), 3)
                self.assertGreater(len(exercise["explanation"]), 35)
                exercises.append(exercise["exercise_id"])
        self.assertEqual(len(exercises), 14)
        self.assertEqual(len(set(exercises)), 14)

    def test_all_citations_match_existing_requirements_subject_and_text_location(self):
        repo = KnowledgeRepository(ROOT)
        for guide in self.read_guides():
            self.assertGreaterEqual(len(guide["citations"]), 2)
            for citation in guide["citations"]:
                with self.subTest(node_id=guide["node_id"], citation=citation["requirement_id"]):
                    requirement = repo.get_requirement(citation["requirement_id"])
                    self.assertIsNotNone(requirement)
                    self.assertEqual(citation["standard_id"], EXPECTED[guide["node_id"]])
                    self.assertEqual(citation["standard_id"], requirement["standard_id"])
                    self.assertEqual(citation["locator"], requirement["locator"])
                    self.assertIn(citation["quote"], requirement["content"])
                    self.assertLessEqual(len(citation["quote"]), 90)
                    locator = citation["locator"]
                    lines = repo.path(locator["text_path"]).read_text(encoding="utf-8").splitlines()
                    selected = "\n".join(lines[locator["line_start"] - 1:locator["line_end"]])
                    self.assertIn(citation["quote"], selected)
                    self.assertTrue(citation["scope_note"])

    def test_drafts_have_no_forged_signatures_or_formal_question_identity(self):
        for guide in self.read_guides():
            self.assertEqual(guide["content_status"], "original_research_draft")
            self.assertEqual(guide["review"]["status"], "needs_fix")
            self.assertIsNone(guide["review"]["checked_by"])
            self.assertIsNone(guide["review"]["checked_at"])
            self.assertFalse(guide["formal_question_pool_eligible"])
            self.assertIn("原创研究草稿", guide["notice"])
            self.assertIn("非真题", guide["notice"])
            self.assertIn("未经专家签署", guide["notice"])
            self.assertNotIn("question_id", guide)
            for exercise in guide["self_checks"]:
                self.assertEqual(exercise["answer_status"], "research_draft")
                self.assertNotIn("question_id", exercise)
                self.assertNotIn("score", exercise)

    def test_known_source_boundaries_are_explicit(self):
        guides = {r["node_id"]: r for r in self.read_guides()}
        history_notes = " ".join(guides["ntce.chuzhong.lishi.s3.k01"]["source_audit"]["notes"])
        self.assertIn("316", history_notes)
        self.assertIn("历史与社会", history_notes)
        sport_notes = " ".join(guides["ntce.chuzhong.tiyu.s3.k04"]["source_audit"]["notes"])
        self.assertIn("板书", sport_notes)
        self.assertIn("教学建议", sport_notes)

    def test_loader_filters_returns_detached_json_and_rereads_changes(self):
        guides = self.read_guides()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / GUIDES
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(guides[0], ensure_ascii=False) + "\n", encoding="utf-8")
            resources = self.resources(KnowledgeRepository(root))
            first = resources.get_guide(guides[0]["node_id"])
            self.assertEqual(first, guides[0])
            first["self_checks"].clear()
            self.assertEqual(len(resources.get_guide(guides[0]["node_id"])["self_checks"]), 2)
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in guides) + "\n", encoding="utf-8")
            self.assertEqual(resources.list_guides(guides[2]["node_id"]), [guides[2]])
            self.assertEqual(len(resources.list_guides()), 7)
            self.assertEqual(json.loads(json.dumps(resources.list_guides(), ensure_ascii=False)), guides)
            self.assertIsNone(resources.get_guide("unknown"))

    def test_missing_file_is_empty_and_malformed_or_duplicate_data_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = self.resources(KnowledgeRepository(root))
            self.assertEqual(resources.list_guides(), [])
            path = root / GUIDES
            path.parent.mkdir(parents=True)
            path.write_text("{broken\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "study_guides.jsonl:1"):
                resources.list_guides()
            guide = self.read_guides()[0]
            path.write_text((json.dumps(guide, ensure_ascii=False) + "\n") * 2, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                resources.list_guides()


if __name__ == "__main__":
    unittest.main()
