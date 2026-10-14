# -*- coding: utf-8 -*-
"""四六级八层契约回归：图谱导出、附录 A Schema 合规、先修关系未核定不得进入学习路径。"""
import json
from pathlib import Path
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CET = ROOT / "数据集" / "四六级"
NTCE_SCHEMAS = ROOT / "数据集" / "教资" / "schemas"
LAYERS = ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7")
CONTRACT_EDGES = {"assesses", "supports_ability", "aligned_to_requirement", "prerequisite_of",
                  "refers_to_material", "has_rubric", "contains", "has_child", "specifies"}


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


class CetEightLayerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes = {n["id"]: n for n in rows(CET / "graph" / "nodes.jsonl")}
        cls.edges = rows(CET / "graph" / "edges.jsonl")
        cls.questions = [q for path in sorted((CET / "questions").glob("*/*.jsonl")) for q in rows(path)]
        cls.schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in NTCE_SCHEMAS.glob("*.json")}

    def test_graph_exports_all_eight_layers(self):
        for layer in LAYERS:
            self.assertGreater(sum(1 for n in self.nodes.values() if n["layer"] == layer), 0, f"{layer} 层为空")
        self.assertLessEqual({n["layer"] for n in self.nodes.values()}, set(LAYERS))

    def test_question_record_types_and_edge_contract(self):
        types = {n["type"] for n in self.nodes.values()}
        for expected in ("standard", "exam_requirement", "exam", "module", "ability", "knowledge_node",
                         "material", "question", "rubric", "resource"):
            self.assertIn(expected, types)
        used = {e["type"] for e in self.edges}
        self.assertTrue(CONTRACT_EDGES <= used, f"缺失契约边：{CONTRACT_EDGES - used}")

    def test_question_foreign_keys_resolve_and_directions_are_canonical(self):
        knowledge = {nid for nid, n in self.nodes.items() if n["type"] == "knowledge_node"}
        abilities = {nid for nid, n in self.nodes.items() if n["type"] == "ability"}
        questions = {nid for nid, n in self.nodes.items() if n["type"] == "question"}
        assesses = {(e["src"], e["dst"]) for e in self.edges if e["type"] == "assesses"}
        supports = {(e["src"], e["dst"]) for e in self.edges if e["type"] == "supports_ability"}
        for question in self.questions:
            qid = question["question_id"]
            self.assertIn(qid, self.nodes)
            for node_id in question["knowledge_node_ids"]:
                self.assertIn(node_id, knowledge, qid)
                self.assertIn((node_id, qid), assesses, f"知识点→题目 assesses 边缺失：{node_id}->{qid}")
            for ability_id in question["ability_ids"]:
                self.assertIn(ability_id, abilities, qid)
                self.assertIn((ability_id, qid), supports, f"能力→题目 supports_ability 边缺失：{ability_id}->{qid}")

    def test_unreviewed_prerequisite_claims_cannot_enter_learning_paths(self):
        prereqs = [e for e in self.edges if e["type"] == "prerequisite_of"]
        self.assertTrue(prereqs, "先修候选边应保留可核定队列")
        for edge in prereqs:
            if edge.get("status") == "verified":
                self.assertTrue(edge.get("reviewed_by"), edge)
            else:
                self.assertFalse(edge.get("active_for_learning_path"), edge)

    def test_all_cet_questions_conform_to_shared_question_schema(self):
        validator = jsonschema.Draft202012Validator(self.schemas["question"])
        for question in self.questions:
            errors = list(validator.iter_errors(question))
            self.assertEqual([], errors, f"{question['question_id']}: {[e.message for e in errors][:2]}")

    def test_no_record_claims_expert_review_without_a_reviewer(self):
        for question in self.questions:
            review = question["review"]
            if review["status"] in ("checked", "expert_reviewed"):
                self.assertTrue(review.get("reviewed_by") or review.get("checked_by"), question["question_id"])
            if question["content"]["answer_status"] == "source_conflict":
                self.assertIsNone(question["content"]["answer"], question["question_id"])

    def test_research_scope_is_declared_without_claiming_authorization(self):
        for question in self.questions:
            rights = question["source"]["copyright"]
            self.assertEqual("research_non_commercial", rights["use_scope"], question["question_id"])
            if rights["authorization_status"] in ("authorized", "public_domain"):
                self.assertTrue(rights.get("evidence") or rights.get("holder"), question["question_id"])

    def test_cet_knowledge_nodes_conform_to_schema(self):
        validator = jsonschema.Draft202012Validator(self.schemas["knowledge_node"])
        knowledge = rows(CET / "ontology" / "knowledge_nodes.jsonl")
        self.assertEqual(48, len(knowledge))
        for kn in knowledge:
            errors = list(validator.iter_errors(kn))
            self.assertEqual([], errors, f"CET知识点 {kn.get('id')} 不符合Schema: {[e.message for e in errors]}")
        cet_graph_kn = [n for n in self.nodes.values() if n.get("type") == "knowledge_node"]
        self.assertEqual(48, len(cet_graph_kn))
        for kn in cet_graph_kn:
            errors = list(validator.iter_errors(kn))
            self.assertEqual([], errors, f"CET图谱知识点 {kn.get('id')} 不符合Schema: {[e.message for e in errors]}")

    def test_cet_ability_nodes_conform_to_schema(self):
        validator = jsonschema.Draft202012Validator(self.schemas["ability_node"])
        abilities = rows(CET / "ontology" / "ability_nodes.jsonl")
        self.assertEqual(28, len(abilities))
        for ab in abilities:
            errors = list(validator.iter_errors(ab))
            self.assertEqual([], errors, f"CET能力 {ab.get('id')} 不符合Schema: {[e.message for e in errors]}")
        cet_graph_ab = [n for n in self.nodes.values() if n.get("type") == "ability"]
        self.assertEqual(28, len(cet_graph_ab))
        for ab in cet_graph_ab:
            errors = list(validator.iter_errors(ab))
            self.assertEqual([], errors, f"CET图谱能力 {ab.get('id')} 不符合Schema: {[e.message for e in errors]}")

    def test_cet_rubrics_conform_to_schema(self):
        validator = jsonschema.Draft202012Validator(self.schemas["rubric"])
        holistic_validator = jsonschema.Draft202012Validator(self.schemas["holistic_rubric"])
        rubrics = rows(CET / "ontology" / "scoring_rubrics.jsonl")
        self.assertEqual(2, len(rubrics))
        for r in rubrics:
            errors = list(validator.iter_errors(r))
            self.assertEqual([], errors, f"CET量规 {r.get('rubric_id')} 不符合 rubric.json: {[e.message for e in errors]}")
            h_errors = list(holistic_validator.iter_errors(r))
            self.assertEqual([], h_errors, f"CET量规 {r.get('rubric_id')} 不符合 holistic_rubric.json: {[e.message for e in h_errors]}")


if __name__ == "__main__":
    unittest.main()
