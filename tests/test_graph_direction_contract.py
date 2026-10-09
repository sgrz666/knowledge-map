# -*- coding: utf-8 -*-
"""两套库共用的图谱契约：§3.2 单一层级字段 + §3.4 边名词表与"支撑方 -> 被支撑方"方向。

教资与四六级各自有导出脚本，历史上曾把 assesses 写成相反的方向，消费端只能各写一套遍历。
本测试同时跑两库，把方向与层级字段钉成同一个不变式。
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = {"ntce": ROOT / "数据集" / "教资", "cet": ROOT / "数据集" / "四六级"}
LAYERS = ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7")

ALLOWED = {
    "assesses": {("knowledge_node", "question")},
    "supports_ability": {("ability", "knowledge_node"), ("ability", "question")},
    "aligned_to_requirement": {("exam_requirement", "knowledge_node"), ("exam_requirement", "question"),
                               ("exam_requirement", "rubric"), ("exam_requirement", "resource"),
                               ("exam_requirement", "module")},
    "prerequisite_of": {("knowledge_node", "knowledge_node")},
    "refers_to_material": {("question", "material")},
    "has_rubric": {("question", "rubric")},
    "specifies": {("standard", "exam_requirement")},
    "contains": {("exam", "module"), ("exam", "question"), ("module", "question"),
                 ("module", "knowledge_node"), ("module", "material"), ("module", "ability"),
                 ("standard", "exam_requirement"), ("standard", "module")},
    "has_child": {("module", "knowledge_node"), ("knowledge_node", "knowledge_node"),
                  ("module", "ability"), ("ability", "ability"), ("knowledge_node", "material")},
    "comprises": {("literacy", "ability")},
    "targets": {("exam", "literacy"), ("module", "literacy")},
    "basis": {("standard", "module")},
    "supports_resource": {("ability", "resource"), ("knowledge_node", "resource")},
    "supplements_resource": {("knowledge_node", "resource"), ("ability", "resource"),
                             ("question", "resource"), ("material", "resource")},
    "confused_with": {("knowledge_node", "knowledge_node")},
    "misconception_lead_to": {("knowledge_node", "knowledge_node"), ("knowledge_node", "misconception")},
}


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


class GraphContractTests(unittest.TestCase):
    def check_lib(self, dataset):
        base = LIBS[dataset]
        nodes = {n["id"]: n for n in rows(base / "graph" / "nodes.jsonl")}
        edges = rows(base / "graph" / "edges.jsonl")
        self.assertTrue(nodes and edges, dataset)

        for node in nodes.values():
            self.assertIn(node["layer"], LAYERS, f"{dataset}: 层级必须只用 §3.2 的 L0-L7：{node['id']}")
            self.assertNotIn("hierarchy_level", node, f"{dataset}: {node['id']} 仍带第二套层级字段")

        for edge in edges:
            kind = edge.get("type") or edge.get("rel")
            self.assertIn(kind, ALLOWED, f"{dataset}: 边名 {kind} 不在 §3.4 词表内")
            src, dst = nodes.get(edge["src"]), nodes.get(edge["dst"])
            self.assertIsNotNone(src, f"{dataset}: 悬空 src {edge['src']}")
            self.assertIsNotNone(dst, f"{dataset}: 悬空 dst {edge['dst']}")
            pair = (src["type"], dst["type"])
            self.assertIn(pair, ALLOWED[kind], f"{dataset}: {kind} 方向/端点不符 §3.4，实际 {pair} <- {edge}")

        return nodes, edges

    def test_ntce_graph_follows_shared_contract(self):
        self.check_lib("ntce")

    def test_cet_graph_follows_shared_contract(self):
        self.check_lib("cet")

    def test_question_foreign_keys_are_mirrored_as_provider_edges_in_both_libs(self):
        for dataset in LIBS:
            base = LIBS[dataset]
            nodes, edges = self.check_lib(dataset)
            questions = [q for path in sorted((base / "questions").rglob("*.jsonl")) for q in rows(path)]
            assesses = {(e["src"], e["dst"]) for e in edges if (e.get("type") or e.get("rel")) == "assesses"}
            supports = {(e["src"], e["dst"]) for e in edges if (e.get("type") or e.get("rel")) == "supports_ability"}
            aligned = {(e["src"], e["dst"]) for e in edges if (e.get("type") or e.get("rel")) == "aligned_to_requirement"}
            for question in questions:
                qid = question["question_id"]
                self.assertIn(qid, nodes, f"{dataset}: 题目 {qid} 未入图")
                for node_id in question.get("knowledge_node_ids") or []:
                    self.assertIn((node_id, qid), assesses, f"{dataset}: 缺 {node_id} -> {qid} 的 assesses 边")
                for ability_id in question.get("ability_ids") or []:
                    self.assertIn((ability_id, qid), supports, f"{dataset}: 缺 {ability_id} -> {qid} 的 supports_ability 边")
                for requirement_id in question.get("exam_requirement_ids") or []:
                    self.assertIn((requirement_id, qid), aligned, f"{dataset}: 缺 {requirement_id} -> {qid} 的 aligned_to_requirement 边")


if __name__ == "__main__":
    unittest.main()
