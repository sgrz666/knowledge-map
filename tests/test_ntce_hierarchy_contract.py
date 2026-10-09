"""教资知识库八层数据层级（L0-L7）、双轨卡片与规范Schema深度契约回归测试。"""
import json
from pathlib import Path
import unittest
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "数据集" / "教资"


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


class NtceHierarchyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((KB / "MANIFEST.json").read_text(encoding="utf-8"))
        cls.nodes = {n["id"]: n for n in rows(KB / "graph/nodes.jsonl")}
        cls.edges = rows(KB / "graph/edges.jsonl")
        cls.question_files = sorted((KB / "questions").glob("*/*/*.jsonl"))
        cls.questions = [q for path in cls.question_files for q in rows(path)]
        cls.material_files = sorted((KB / "materials").glob("*/*/*.jsonl"))
        cls.materials = {m["material_id"]: m for path in cls.material_files for m in rows(path)}
        cls.schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (KB / "schemas").glob("*.json")}

    def test_eight_layer_hierarchy_in_manifest_and_nodes(self):
        self.assertIn("eight_layer_hierarchy", self.manifest)
        eight_layers = self.manifest["eight_layer_hierarchy"]
        expected_keys = [
            "L0_standard_requirement", "L1_exam", "L2_module",
            "L3_competency_ability", "L4_knowledge_node",
            "L5_shared_material", "L6_question_rubric", "L7_learning_resource"
        ]
        for key in expected_keys:
            self.assertIn(key, eight_layers)
            self.assertGreater(eight_layers[key], 0, f"{key} 节点数应大于0")

        # 层级标签只允许规范 §3.2 的一套 L0-L7 编号，不得再并存第二套
        valid_layers = {"L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"}
        layers_in_nodes = {n.get("layer") for n in self.nodes.values()}
        self.assertTrue(layers_in_nodes <= valid_layers, f"存在规范外的层级标签: {layers_in_nodes - valid_layers}")
        self.assertEqual(valid_layers, layers_in_nodes, "nodes.jsonl 中缺失八层分级")
        for node in self.nodes.values():
            self.assertNotIn("hierarchy_level", node, f"节点 {node['id']} 仍带第二套层级字段")
        expected_layer = {
            "standard": "L0", "exam_requirement": "L0", "exam": "L1", "module": "L2",
            "literacy": "L3", "ability": "L3", "knowledge_node": "L4", "material": "L5",
            "question": "L6", "rubric": "L6", "resource": "L7",
        }
        for node in self.nodes.values():
            self.assertEqual(expected_layer[node["type"]], node["layer"], f"节点 {node['id']} 层级与实体类型不符")

        # §3.4 边命名与方向；旧命名不得残留
        edge_types = {e["type"] for e in self.edges}
        for required in ("assesses", "supports_ability", "aligned_to_requirement", "prerequisite_of", "refers_to_material", "has_rubric", "supplements_resource", "supports_resource"):
            self.assertIn(required, edge_types, f"缺失规范 §3.4 核心边: {required}")
        for legacy in ("tagged", "requires_knowledge", "exam_requirement", "prerequisite_candidate"):
            self.assertNotIn(legacy, edge_types, f"残留旧边命名: {legacy}")
        node_type = {nid: n["type"] for nid, n in self.nodes.items()}
        for e in self.edges:
            src_type, dst_type = node_type[e["src"]], node_type[e["dst"]]
            # §3.4 落库方向：支撑方 -> 被支撑方，与四六级导出层同向
            if e["type"] == "assesses":
                self.assertEqual(("knowledge_node", "question"), (src_type, dst_type), e)
            if e["type"] == "supports_ability":
                self.assertEqual("ability", src_type, e)
                self.assertIn(dst_type, ("knowledge_node", "question"), e)
            if e["type"] == "aligned_to_requirement":
                self.assertEqual("exam_requirement", src_type, e)
                self.assertIn(dst_type, ("knowledge_node", "question", "rubric", "resource", "module"), e)
            if e["type"] == "has_rubric":
                self.assertEqual(("question", "rubric"), (src_type, dst_type), e)

    def test_schemas_directory_contains_all_appendix_a_schemas(self):
        expected_schemas = [
            "question", "material", "knowledge_node",
            "ability_node", "requirement", "rubric", "practice_framework",
            "user_mastery", "card_frontmatter"
        ]
        for name in expected_schemas:
            self.assertIn(name, self.schemas, f"缺失核心实体Schema: {name}.json")
            schema_data = self.schemas[name]
            self.assertEqual("object", schema_data.get("type"))
            validator = jsonschema.Draft202012Validator(schema_data)
            validator.check_schema(schema_data)

    def test_materials_fully_conform_to_schema(self):
        mat_schema = self.schemas["material"]
        validator = jsonschema.Draft202012Validator(mat_schema)
        self.assertEqual(586, len(self.materials))
        for m in self.materials.values():
            errors = list(validator.iter_errors(m))
            self.assertEqual([], errors, f"材料 {m.get('material_id')} 不符合Schema: {[e.message for e in errors]}")
            self.assertIn(m["kind"], ["case_material", "lesson_plan_material", "interview_material"])
            self.assertGreater(m["word_count"], 0)
            self.assertIn("source", m)
            self.assertIn("used_by_questions", m)

    def test_rubrics_fully_conform_to_schema(self):
        rub_schema = self.schemas["rubric"]
        validator = jsonschema.Draft202012Validator(rub_schema)
        rubrics_dir = KB / "rubrics"
        rubric_files = [p for p in rubrics_dir.glob("*.json") if p.name != "official_interview.json"]
        self.assertGreaterEqual(len(rubric_files), 6)
        for p in rubric_files:
            data = json.loads(p.read_text(encoding="utf-8"))
            errors = list(validator.iter_errors(data))
            self.assertEqual([], errors, f"量规 {p.name} 不符合Schema: {[e.message for e in errors]}")

    def test_question_entity_schema_enrichment(self):
        q_schema = self.schemas["question"]
        validator = jsonschema.Draft202012Validator(q_schema)

        # 抽检各学段各题型代表性试题，验证 schema 零错误
        sample_questions = self.questions[::70]
        for q in sample_questions:
            errors = list(validator.iter_errors(q))
            self.assertEqual([], errors, f"试题 {q.get('question_id')} Schema验证失败: {[e.message for e in errors]}")
            self.assertIn("school_level", q)
            self.assertIn("module", q)
            self.assertEqual(q["school_level"], q["level"])

        # 难度元数据不得伪造 IRT 校准
        diff_questions = [q for q in self.questions if q.get("difficulty") is not None]
        self.assertGreater(len(diff_questions), 10000)
        for q in diff_questions[:100]:
            self.assertIn("difficulty_meta", q)
            meta = q["difficulty_meta"]
            self.assertIn("heuristic", meta.get("method", ""))
            self.assertNotIn("irt_calibrated", meta.get("method", ""))

        # 主观题必须包含 rubric_id 与 rubric
        subjective = [q for q in self.questions if q["question_type"] in {"材料分析", "教学设计", "简答", "活动设计", "写作"}]
        self.assertGreater(len(subjective), 2000)
        for q in subjective[:100]:
            self.assertTrue(q.get("rubric_id"))
            self.assertTrue(q.get("rubric"))
            self.assertEqual(q["rubric_id"], q["rubric"].get("rubric_id"))

    def test_dual_track_markdown_cards_frontmatter_and_analysis(self):
        card_paths = [p for p in (KB / "cards").rglob("*.md") if p.name != "README.md"]
        self.assertEqual(12881, len(card_paths))
        card_schema = self.schemas["card_frontmatter"]
        validator = jsonschema.Draft202012Validator(card_schema)

        # 抽检卡片头部 YAML Frontmatter 符合 Schema
        sample_cards = card_paths[::100]
        for card_path in sample_cards:
            text = card_path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"卡片缺少Frontmatter头: {card_path}")
            header_end = text.find("\n---\n", 4)
            self.assertGreater(header_end, 0)
            header_text = text[4:header_end]
            data = yaml.safe_load(header_text)
            errors = list(validator.iter_errors(data))
            self.assertEqual([], errors, f"卡片Frontmatter不合规: {card_path}: {[e.message for e in errors]}")

        # 检查有材料关联的试题卡片包含 material_id 与材料正文
        mat_q = next(q for q in self.questions if q.get("material_id") and not q["extra"].get("duplicate_of"))
        mat_card_path = KB / "cards" / mat_q["level"] / mat_q["subject"] / mat_q["source"]["session"] / f"q{mat_q['extra']['paper_order']:02d}.md"
        if mat_card_path.is_file():
            mat_card_text = mat_card_path.read_text(encoding="utf-8")
            self.assertIn(f"material_id: {mat_q['material_id']}", mat_card_text)
            self.assertIn("**材料:**", mat_card_text)

        # 检查三段结构化解析渲染
        q_with_analysis = next(q for q in self.questions if q.get("analysis") and q["analysis"].get("key_info") and not q["extra"].get("duplicate_of"))
        card_with_analysis = KB / "cards" / q_with_analysis["level"] / q_with_analysis["subject"] / q_with_analysis["source"]["session"] / f"q{q_with_analysis['extra']['paper_order']:02d}.md"
        if card_with_analysis.is_file():
            card_text = card_with_analysis.read_text(encoding="utf-8")
            self.assertIn("**【结构化解析】**", card_text)
            self.assertIn("**考点剖析与关键信息:**", card_text)

    def test_learning_resources_layer_seven_compliance_and_graph_connectivity(self):
        res_dir = KB / "resources"
        self.assertTrue(res_dir.is_dir())
        res_files = list(res_dir.glob("*.jsonl"))
        self.assertGreaterEqual(len(res_files), 3)
        all_resources = [r for path in res_files for r in rows(path)]
        self.assertGreaterEqual(len(all_resources), 7)

        # 检查所有资源实体的知识点、能力和考纲外键在图谱中100%存在
        for res in all_resources:
            rid = res.get("resource_id")
            self.assertTrue(rid)
            self.assertTrue(res.get("title"))
            self.assertEqual("research_non_commercial", res.get("copyright", {}).get("use_scope"))

            # 知识点外键必须存在于知识图谱
            for kn in res.get("knowledge_node_ids", []):
                self.assertIn(kn, self.nodes, f"资源 {rid} 的知识点外键 {kn} 在图谱中不存在")

            # 能力外键必须存在于知识图谱
            for aid in res.get("ability_ids", []):
                self.assertIn(aid, self.nodes, f"资源 {rid} 的能力外键 {aid} 在图谱中不存在")

            # 考纲外键必须存在于图谱
            for req in res.get("exam_requirement_ids", []):
                self.assertIn(req, self.nodes, f"资源 {rid} 的考纲要求外键 {req} 在图谱中不存在")

        # 检查图谱中至少包含指向资源的边
        res_ids = {r["resource_id"] for r in all_resources}
        edges_to_res = [e for e in self.edges if e["dst"] in res_ids or e["src"] in res_ids]
        self.assertGreaterEqual(len(edges_to_res), len(all_resources))

    def test_user_mastery_schema_validation(self):
        mastery_schema = self.schemas["user_mastery"]
        validator = jsonschema.Draft202012Validator(mastery_schema)
        mock_record = {
            "user_id": "usr_test_1001",
            "node_id": "ntce.zhongxue.jiaoyuzhishi.m5.k01",
            "mastery_score": 0.85,
            "practice_count": 12,
            "correct_count": 10,
            "fsrs_state": {
                "stability": 4.2,
                "difficulty": 0.3,
                "due_date": "2026-10-15T08:00:00Z",
                "state": "review"
            },
            "last_updated_at": "2026-10-09T08:00:00Z"
        }
        errors = list(validator.iter_errors(mock_record))
        self.assertEqual([], errors, f"UserMastery mock record 不符合Schema: {[e.message for e in errors]}")

    def test_no_corrupted_line_separators_in_corpus(self):
        # 严格验证全库无未转义的 U+2028 / U+2029 行分隔符，防止任何解析器分行破损
        for p in (KB / "questions").glob("*/*/*.jsonl"):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("\u2028", text, f"{p} 包含不规则行分隔符 U+2028")
            self.assertNotIn("\u2029", text, f"{p} 包含不规则行分隔符 U+2029")
            # 验证标准 splitlines() 逐行加载绝不抛出 JSONDecodeError
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)


if __name__ == "__main__":
    unittest.main()
