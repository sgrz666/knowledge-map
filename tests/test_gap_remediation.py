"""测试四六级与教资知识库短板补齐全量契约与功能规范 (Gap Remediation Tests)。
覆盖：
1. 四六级 RAG 双轨自包含 Markdown 卡片（卡片轨与题目轨的双向一致，Frontmatter 校验）
2. 写作与翻译试题规整与入库契约 (73 题写译各 4 份文件及评分量规)
3. 卷级模考规格 PaperSpecification (四六级 126 套 710 分制，教资 32 套 120 分制)
4. 多模态听力音频切片与时间对齐 (120 套音频索引及切片验证)
5. 知识图谱万级考纲词汇挂载与认知诊断 DAG 无环验证
"""
import json
import unittest
from pathlib import Path
import jsonschema
import yaml
from collections import defaultdict, deque

ROOT = Path(__file__).resolve().parents[1]
CET_KB = ROOT / "数据集" / "四六级"
NTCE_KB = ROOT / "数据集" / "教资"

# 卡片目录里的说明文档不是知识卡：运行时 services/knowledge/vector_index.py::card_files 同样按文件名排除，
# 门禁若不排除就会把文档当卡片计数、校验甚至改写。
DOC_FILE_NAMES = {"README.md"}
# 写作与翻译题只有题记录与量规，不进 RAG 卡片轨；口径见 数据集/四六级/scripts/generate_cards.py。
UNCARDABLE_MODULES = {"写作", "翻译"}


def data_cards(cards_dir: Path):
    return sorted(p for p in cards_dir.rglob("*.md") if p.name not in DOC_FILE_NAMES)


def cet_question_records():
    records = []
    for path in sorted((CET_KB / "questions").rglob("*.jsonl")):
        for line in path.read_text("utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def card_frontmatter_id(path: Path):
    with path.open(encoding="utf-8") as handle:
        if handle.readline().strip() != "---":
            return None
        for line in handle:
            if line.strip() == "---":
                return None
            if line.startswith("id:"):
                return line.partition(":")[2].strip()
    return None


class GapRemediationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema_path = NTCE_KB / "schemas" / "card_frontmatter.json"
        cls.card_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        cls.card_validator = jsonschema.Draft202012Validator(cls.card_schema)

    # -------------------------------------------------------------
    # P0: RAG 双轨 Markdown 卡片契约测试
    # -------------------------------------------------------------
    def test_rag_cards_count_and_path_convention(self):
        cards_dir = CET_KB / "cards"
        self.assertTrue(cards_dir.exists(), "CET cards 目录不存在")
        cards = data_cards(cards_dir)
        records = cet_question_records()

        # 卡片数不写死：由题目轨现算——每题一张卡，写作与翻译题不建卡。
        expected = [q for q in records if q.get("module") not in UNCARDABLE_MODULES]
        self.assertEqual(len(expected), len(cards),
                         "卡片张数应等于「题目总数 − 写作/翻译题数」，实际题目 %d 张、可建卡 %d 张、卡片 %d 张"
                         % (len(records), len(expected), len(cards)))

        expected_ids = {q["question_id"] for q in expected}
        card_ids = {card_frontmatter_id(p) for p in cards}
        self.assertEqual(len(card_ids), len(cards), "卡片 frontmatter 的 id 缺失或重复: %s"
                         % sorted(p for p in cards if card_frontmatter_id(p) is None)[:5])
        self.assertEqual(expected_ids, card_ids,
                         "卡片轨与题目轨必须双向一致（缺卡/孤儿卡）: 题有卡无 %s；卡有题无 %s"
                         % (sorted(expected_ids - card_ids)[:5], sorted(card_ids - expected_ids)[:5]))

        for exam_key in ("cet4", "cet6"):
            folder_cards = data_cards(cards_dir / exam_key)
            self.assertTrue(folder_cards, "%s 卡片目录为空" % exam_key)
            in_folder = {card_frontmatter_id(p) for p in folder_cards}
            by_id_prefix = {qid for qid in card_ids if qid.startswith("%s-" % exam_key)}
            self.assertEqual(in_folder, by_id_prefix,
                             "%s 目录必须恰好收纳该考试的卡片（目录归属与 id 前缀不许分叉）" % exam_key)

    def test_rag_cards_frontmatter_schema_and_four_stage_analysis(self):
        cards_dir = CET_KB / "cards"
        all_cards = data_cards(cards_dir)
        # 按卡片全集等距抽样，覆盖各 exam/年份/题型
        sample_cards = all_cards[::90]
        self.assertGreater(len(sample_cards), 50)
        
        for cpath in sample_cards:
            text = cpath.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"缺少 Frontmatter 头部: {cpath}")
            end_idx = text.find("\n---\n", 4)
            self.assertGreater(end_idx, 0, f"Frontmatter 未正常闭合: {cpath}")
            
            fm_text = text[4:end_idx]
            fm_data = yaml.safe_load(fm_text)
            errors = list(self.card_validator.iter_errors(fm_data))
            self.assertEqual([], errors, f"Frontmatter 不符合 Schema 约束: {cpath}: {[e.message for e in errors]}")
            
            # 校验包含自然语言大标题
            self.assertIn("【", text, f"缺失自然语言大标题: {cpath}")
            self.assertIn("】", text, f"缺失自然语言大标题闭合: {cpath}")
            
            # 校验四阶段深度认知解析标记
            self.assertIn("关键信息抓取", text, f"缺失第一阶段关键信息抓取: {cpath}")
            self.assertIn("选项比对演练", text, f"缺失第二阶段选项比对演练: {cpath}")
            self.assertIn("原文证据回溯", text, f"缺失第三阶段原文证据回溯: {cpath}")
            self.assertIn("全篇深度精析", text, f"缺失第四阶段全篇深度精析: {cpath}")

    # -------------------------------------------------------------
    # P0: 写作与翻译试题规整与入库契约
    # -------------------------------------------------------------
    def test_writing_and_translation_question_unification(self):
        c4_w = [json.loads(l) for l in (CET_KB / "questions/cet4/writing.jsonl").read_text("utf-8").splitlines() if l.strip()]
        c4_t = [json.loads(l) for l in (CET_KB / "questions/cet4/translation.jsonl").read_text("utf-8").splitlines() if l.strip()]
        c6_w = [json.loads(l) for l in (CET_KB / "questions/cet6/writing.jsonl").read_text("utf-8").splitlines() if l.strip()]
        c6_t = [json.loads(l) for l in (CET_KB / "questions/cet6/translation.jsonl").read_text("utf-8").splitlines() if l.strip()]
        
        self.assertEqual(73, len(c4_w))
        self.assertEqual(73, len(c4_t))
        self.assertEqual(73, len(c6_w))
        self.assertEqual(73, len(c6_t))
        
        all_wt = c4_w + c4_t + c6_w + c6_t
        all_qids = [q["question_id"] for q in all_wt]
        self.assertEqual(len(all_qids), len(set(all_qids)), "规整后的写译试题 ID 必须全局唯一")
        
        for q in all_wt:
            self.assertIn(q["exam"], ["CET-4", "CET-6"])
            self.assertTrue(q.get("rubric_id"), f"缺失评分量规 rubric_id: {q['question_id']}")
            self.assertTrue(q.get("exam_requirement_ids"), f"缺失大纲条款 exam_requirement_ids: {q['question_id']}")
            rights = q["source"]["copyright"]
            self.assertEqual("unknown", rights["authorization_status"])
            self.assertEqual("research_non_commercial", rights["use_scope"])
            self.assertIsNone(rights["expires_at"])

    # -------------------------------------------------------------
    # P1: L7 卷级模考规格 PaperSpecification 契约
    # -------------------------------------------------------------
    def test_cet_paper_specifications(self):
        spec_file = CET_KB / "manifest" / "paper_specs.jsonl"
        self.assertTrue(spec_file.exists())
        specs = [json.loads(l) for l in spec_file.read_text("utf-8").splitlines() if l.strip()]
        self.assertEqual(126, len(specs), "CET 卷级规格应覆盖 126 套真题")
        
        for sp in specs:
            self.assertEqual(130, sp["total_duration_minutes"])
            self.assertEqual(710, sp["total_score"])
            self.assertEqual("norm_referenced_standardized_score", sp["score_conversion"]["type"])
            self.assertEqual(500, sp["score_conversion"]["mean"])
            self.assertEqual(70, sp["score_conversion"]["sd"])
            
            parts = sp["parts"]
            self.assertEqual(4, len(parts))
            part_keys = [p["part_number"] for p in parts]
            self.assertEqual([1, 2, 3, 4], part_keys)
            
            # 计时锁策略验证
            self.assertTrue(parts[0]["lock_policy"]["locked_forward"])
            self.assertTrue(parts[1]["lock_policy"]["audio_stream_lock"])

    def test_ntce_paper_specifications(self):
        spec_file = NTCE_KB / "paper_specs.jsonl"
        self.assertTrue(spec_file.exists())
        specs = [json.loads(l) for l in spec_file.read_text("utf-8").splitlines() if l.strip()]
        self.assertEqual(32, len(specs), "教资卷级规格应覆盖 32 份科目大纲规格")
        
        for sp in specs:
            self.assertEqual(120, sp["total_duration_minutes"])
            self.assertEqual("criterion_referenced_piecewise_linear", sp["score_conversion"]["type"])
            self.assertEqual(70, sp["score_conversion"]["passing_report_score"])
            self.assertEqual(150, sp["score_conversion"]["raw_scale"])
            self.assertEqual(120, sp["score_conversion"]["report_scale"])

    # -------------------------------------------------------------
    # P1: 听力多模态音频资产目录与时间切片
    # -------------------------------------------------------------
    def test_audio_catalog_and_question_alignment(self):
        catalog_file = CET_KB / "manifest" / "audio_catalog.json"
        self.assertTrue(catalog_file.exists())
        catalog = json.loads(catalog_file.read_text("utf-8"))
        self.assertEqual(120, catalog.get("total_audio_files"), "音频目录应索引 120 个真实 MP3 文件")
        
        # 校验听力题切片时间戳
        q_files = list((CET_KB / "questions").glob("*/*_p*.jsonl"))
        listening_qs_count = 0
        for qf in q_files:
            for l in qf.read_text("utf-8").splitlines():
                if not l.strip():
                    continue
                q = json.loads(l)
                if q.get("module") == "听力理解":
                    listening_qs_count += 1
                    aud = q.get("extra", {}).get("audio", {})
                    self.assertIn("start_seconds", aud)
                    self.assertIn("end_seconds", aud)
                    self.assertGreaterEqual(aud["start_seconds"], 0.0)
                    self.assertGreater(aud["end_seconds"], aud["start_seconds"])
                    
        self.assertGreaterEqual(listening_qs_count, 1900, "听力试题总量应不低于 1,900")

    # -------------------------------------------------------------
    # P2: 知识图谱词汇实体与认知诊断 DAG 验证
    # -------------------------------------------------------------
    def test_vocabulary_entities_expansion(self):
        v_file = CET_KB / "ontology" / "vocabulary_entities.jsonl"
        self.assertTrue(v_file.exists())
        vocabs = [json.loads(l) for l in v_file.read_text("utf-8").splitlines() if l.strip()]
        self.assertEqual(9942, len(vocabs), "考纲词汇实体应精确覆盖 9,942 词")
        
        sample = vocabs[0]
        for field in ("entity_id", "word", "level", "knowledge_node_ids", "ability_ids", "real_exam_examples"):
            self.assertIn(field, sample)

    def test_graph_cognitive_edges_and_acyclic_dag(self):
        cet_edges = [json.loads(l) for l in (CET_KB / "ontology/edges.jsonl").read_text("utf-8").splitlines() if l.strip()]
        cet_types = {e.get("rel") for e in cet_edges}
        # 先修关系在教研核定前只能以候选边存在；核定后才会成为 active 的 prerequisite。
        self.assertIn("prerequisite_candidate", cet_types)
        self.assertIn("confused_with", cet_types)
        self.assertIn("misconception_lead_to", cet_types)
        for edge in cet_edges:
            if edge.get("rel") in ("prerequisite", "prereq_of", "prerequisite_of"):
                self.assertTrue(edge.get("reviewed_by") or edge.get("reviewer") or edge.get("evidence"), edge)
        
        # 校验 CET prerequisite 构成无环 DAG
        prereqs = [(e["src"], e["dst"]) for e in cet_edges if e.get("rel") in ("prerequisite", "prereq_of", "prerequisite_candidate")]
        indegree = defaultdict(int)
        adj = defaultdict(list)
        nodes = set()
        for s, d in prereqs:
            adj[s].append(d)
            indegree[d] += 1
            nodes.add(s)
            nodes.add(d)
            
        queue = deque([n for n in nodes if indegree[n] == 0])
        visited = 0
        while queue:
            curr = queue.popleft()
            visited += 1
            for nxt in adj[curr]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
                    
        self.assertEqual(len(nodes), visited, "CET 先修依赖关系必须严格构成有向无环图 (DAG)")
        
        # 校验 NTCE 认知关系边
        ntce_edges = [json.loads(l) for l in (NTCE_KB / "graph/edges.jsonl").read_text("utf-8").splitlines() if l.strip()]
        ntce_types = {e.get("type") for e in ntce_edges}
        self.assertIn("confused_with", ntce_types)
        self.assertIn("misconception_lead_to", ntce_types)


if __name__ == "__main__":
    unittest.main()
