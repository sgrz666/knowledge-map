"""知识库验收的行为回归：阻止完整率掩盖错误关系和虚假可判分状态。"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class KnowledgeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "审查" / "validate_kb.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location("validate_kb", path)
            cls.validator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.validator)
        else:
            cls.validator = None

    def inspect(self, record, context):
        self.assertIsNotNone(self.validator, "缺少统一知识库验收器")
        return {i["rule"] for i in self.validator.inspect_question(record, context)}

    def context(self):
        return {
            "dataset": "cet",
            "knowledge": {
                "cet4.read.locate": {"id": "cet4.read.locate", "exam": "CET-4", "module": "阅读理解", "ability_ids": ["ab.read"], "exam_requirement_ids": ["cet.read.r001"]},
                "cet4.listen.detail": {"id": "cet4.listen.detail", "exam": "CET-4", "module": "听力理解", "ability_ids": ["ab.listen"]},
                "cet4.read": {"id": "cet4.read", "exam": "CET-4", "module": "阅读理解", "parent": "root", "ability_ids": []},
                "cet4.listen": {"id": "cet4.listen", "exam": "CET-4", "module": "听力理解", "parent": "root", "ability_ids": []},
            },
            "abilities": {"ab.read": {}, "ab.listen": {}},
            "requirements": {"cet.read.r001": {"standard_id": "cet.content.cet4"}},
            "standards": {"cet.content.cet4": {}},
            "passages": {}, "materials": {}, "base_paths": [ROOT],
        }

    def record(self):
        return {
            "question_id": "cet4-test-reading-1", "exam": "CET-4", "module": "阅读理解", "question_type": "仔细阅读",
            "knowledge_node_ids": ["cet4.read.locate"], "ability_ids": ["ab.read"], "exam_requirement_ids": ["cet.read.r001"],
            "content": {"stem": "What does the author say about the plan?", "options": {"A": "first", "B": "second", "C": "third", "D": "fourth"}, "answer": "A", "answer_status": "letter_only"},
            "source": {"origin_file": "应试考证功能设计与技术支撑：以教资和四六级为例.md", "verified": False},
            "analysis": {"key_info": "作者在第二段提出计划。", "option_compare": "A复述原意，其他选项无依据。", "trace_back": "第二段第一句。"},
            "difficulty": None, "review": {"status": "auto_parsed"},
            "extra": {},
        }

    def test_root_ids_do_not_make_reading_question_semantically_complete(self):
        record = self.record()
        record["knowledge_node_ids"] = ["cet4.read", "cet4.listen"]
        record["ability_ids"] = []
        rules = self.inspect(record, self.context())
        self.assertIn("Q_KNOWLEDGE_TOO_BROAD", rules)
        self.assertIn("Q_MODULE_MISMATCH", rules)
        self.assertIn("Q_ABILITY_MISSING", rules)

    def test_answer_reference_without_text_is_not_a_usable_answer(self):
        record = self.record()
        record["content"]["answer"] = None
        record["content"]["answer_status"] = "reference_only"
        self.assertIn("Q_ANSWER_MISSING", self.inspect(record, self.context()))

    def test_listening_answer_outside_real_choices_is_rejected(self):
        record = self.record()
        record.update(module="听力理解", question_type="短篇新闻", knowledge_node_ids=["cet4.listen.detail"], ability_ids=["ab.listen"])
        record["content"]["answer"] = "J"
        self.assertIn("Q_ANSWER_INVALID", self.inspect(record, self.context()))

    def test_cloze_can_resolve_options_from_linked_passage(self):
        record = self.record()
        record["question_type"] = "选词填空"
        record["content"]["options"] = {}
        record["content"]["answer"] = "O"
        record["extra"]["passage_id"] = "passage-1"
        context = self.context()
        context["passages"]["passage-1"] = {"text": "A complete source passage.", "extra": {"word_bank": {"O": "volunteering"}}}
        self.assertNotIn("Q_ANSWER_INVALID", self.inspect(record, context))

    def test_existing_ability_id_must_agree_with_knowledge(self):
        record = self.record()
        record["ability_ids"] = ["ab.listen"]
        self.assertIn("Q_ABILITY_MISMATCH", self.inspect(record, self.context()))

    def test_missing_requirement_target_is_not_accepted_as_complete(self):
        record = self.record()
        record["exam_requirement_ids"] = ["made-up-requirement"]
        self.assertIn("Q_REQUIREMENT_DANGLING", self.inspect(record, self.context()))

    def test_standard_name_only_cannot_replace_specific_requirement(self):
        record = self.record()
        record["exam_requirement_ids"] = []
        record["standard_ids"] = ["cet.content.cet4"]
        self.assertIn("Q_REQUIREMENT_MISSING", self.inspect(record, self.context()))

    def test_teacher_subjective_score_is_not_a_rubric(self):
        record = self.record()
        record.update(exam="NTCE", question_type="教学设计", score=20)
        record["content"]["options"] = []
        context = self.context()
        context["dataset"] = "ntce"
        self.assertIn("Q_RUBRIC_MISSING", self.inspect(record, context))

    def test_unresolved_origin_is_reported_despite_verified_flag(self):
        record = self.record()
        record["source"] = {"origin_file": "不完整/.../原料.pdf", "verified": True}
        self.assertIn("Q_SOURCE_UNRESOLVED", self.inspect(record, self.context()))

    def test_generated_analysis_stays_pending_content_review(self):
        record = self.record()
        record["analysis"]["method"] = "llm"
        record["review"] = {"status": "expert_reviewed", "checked_by": None}
        self.assertIn("Q_REVIEW_EVIDENCE_MISSING", self.inspect(record, self.context()))

    def test_rule_difficulty_is_not_misreported_as_calibrated(self):
        record = self.record()
        record["difficulty"] = 0.5
        record["difficulty_method"] = "heuristic"
        self.assertIn("Q_DIFFICULTY_UNCALIBRATED", self.inspect(record, self.context()))

    def test_foreign_exam_requirement_is_rejected(self):
        record = self.record()
        context = self.context()
        context["requirements"]["cet.read.r001"]["exam_scope"] = ["CET-6"]
        self.assertIn("Q_REQUIREMENT_SCOPE_MISMATCH", self.inspect(record, context))

    def test_requirement_level_overrides_document_wide_scope(self):
        record = self.record()
        context = self.context()
        context["requirements"]["cet.read.r001"].update(exam_scope=["CET-4", "CET-6"], level=["CET-6"])
        self.assertIn("Q_REQUIREMENT_SCOPE_MISMATCH", self.inspect(record, context))

    def test_module_only_requirement_mapping_remains_pending(self):
        record = self.record()
        record["review"]["requirement_mapping_status"] = "module_fallback"
        self.assertIn("Q_REQUIREMENT_MAPPING_COARSE", self.inspect(record, self.context()))

    def test_reading_without_source_passage_is_not_ready(self):
        record = self.record()
        self.assertIn("Q_PASSAGE_UNLINKED", self.inspect(record, self.context()))

    def test_official_locator_must_resolve_real_text(self):
        self.assertIsNotNone(self.validator)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "outline.txt").write_text("阅读理解\n理解主旨和细节。\n", encoding="utf-8")
            requirement = {"requirement_id": "real.r001", "content": "不存在的原文", "locator": {"text_path": "outline.txt", "line_start": 2, "line_end": 2}}
            inspector = getattr(self.validator, "inspect_requirement", None)
            self.assertIsNotNone(inspector, "缺少官方条目定位核验")
            rules = {i["rule"] for i in inspector(requirement, [base])}
            self.assertIn("REQUIREMENT_CONTENT_NOT_AT_LOCATOR", rules)

    def test_standalone_percentage_is_not_an_exam_requirement(self):
        self.assertIsNotNone(self.validator)
        inspector = getattr(self.validator, "inspect_requirement", None)
        self.assertIsNotNone(inspector, "缺少官方条目内容核验")
        requirement = {"requirement_id": "weak.r001", "content": "15%", "title": "15%", "locator": {"text_path": "missing.txt", "line_start": 1, "line_end": 1}}
        self.assertIn("REQUIREMENT_CONTENT_FRAGMENT", {i["rule"] for i in inspector(requirement, [ROOT])})

    def test_html_table_row_preserves_inherited_module_context(self):
        self.assertIsNotNone(self.validator)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            html = '<table><tr><th>结构</th><th>内容</th><th>题型</th><th>题数</th><th>分值</th><th>时间</th></tr><tr><td rowspan="2">阅读理解</td><td>词汇理解</td><td>选词填空</td><td>10</td><td>5%</td><td rowspan="2">40分钟</td></tr><tr><td>长篇阅读</td><td>匹配</td><td>10</td><td>10%</td></tr></table>'
            (base / "content.html").write_text(html, encoding="utf-8")
            requirement = {"exam_scope": ["CET-4"], "content": "CET-4：试卷部分阅读理解；测试内容长篇阅读；题型匹配；题数10；分值比例10%；考试时间40分钟。", "locator": {"html_path": "content.html", "table": 1, "row": 3}}
            self.assertEqual(self.validator.inspect_requirement(requirement, [base]), [])

    def test_official_json_descriptor_requires_exact_pointer_and_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "ability.json").write_text(json.dumps({"data": {"item": [{"id": 7, "remark": "能理解熟悉话题的主要信息。"}]}}), encoding="utf-8")
            requirement = {"content": "能理解熟悉话题的主要信息。", "locator": {"json_path": "ability.json", "json_pointer": "/data/item/0/remark", "official_descriptor_id": 7}}
            self.assertEqual(self.validator.inspect_requirement(requirement, [base]), [])
            requirement["locator"]["official_descriptor_id"] = 8
            rules = {i["rule"] for i in self.validator.inspect_requirement(requirement, [base])}
            self.assertIn("REQUIREMENT_DESCRIPTOR_ID_MISMATCH", rules)
            requirement["locator"]["official_descriptor_id"] = 7
            requirement["content"] = "不存在的能力要求。"
            rules = {i["rule"] for i in self.validator.inspect_requirement(requirement, [base])}
            self.assertIn("REQUIREMENT_CONTENT_NOT_AT_LOCATOR", rules)

    def test_provincial_exam_uses_its_own_subject_namespace(self):
        record = self.record()
        record.update(exam="省考", level="xiaoxue", subject="jiaoyuxue", knowledge_node_ids=["shengkao.xiaoxue.jiaoyuxue.basic"])
        context = self.context()
        context["dataset"] = "ntce"
        context["knowledge"]["shengkao.xiaoxue.jiaoyuxue.basic"] = {}
        self.assertNotIn("Q_SUBJECT_MISMATCH", self.inspect(record, context))
        record["knowledge_node_ids"] = ["shengkao.xiaoxue.jiaoyuxinlixue.basic"]
        context["knowledge"]["shengkao.xiaoxue.jiaoyuxinlixue.basic"] = {}
        self.assertIn("Q_SUBJECT_MISMATCH", self.inspect(record, context))

    def test_non_assessable_group_cannot_be_used_as_question_knowledge(self):
        context = self.context()
        context["knowledge"]["cet4.read.locate"]["assessable"] = False
        self.assertIn("Q_KNOWLEDGE_TOO_BROAD", self.inspect(self.record(), context))

    def test_automatic_official_alignment_remains_pending_review(self):
        context = self.context()
        context["knowledge"]["cet4.read.locate"]["mapping_status"] = "derived_from_official_scope_pending_review"
        self.assertIn("Q_REQUIREMENT_MAPPING_PENDING_REVIEW", self.inspect(self.record(), context))

    def test_empty_audio_metadata_is_not_a_playable_resource(self):
        record = self.record()
        record.update(module="听力理解", question_type="短篇新闻")
        record["extra"]["audio"] = {"files": [], "status": "missing_exact_paper_audio"}
        self.assertIn("Q_AUDIO_UNLINKED", self.inspect(record, self.context()))

    def test_rubric_reference_resolves_official_holistic_bands(self):
        record = self.record()
        record["question_type"] = "短文写作"
        record["rubric_id"] = "writing-official"
        context = self.context()
        context["rubrics"] = {"writing-official": {"bands": [{"descriptor": "准确表达题意"}], "feedback_dimensions": [{"name": "信息表达"}], "review_status": "pending_application_expert_review"}}
        rules = self.inspect(record, context)
        self.assertNotIn("Q_RUBRIC_MISSING", rules)
        self.assertIn("Q_RUBRIC_PENDING_REVIEW", rules)

    def test_teacher_requirement_cannot_cross_subject_or_school_stage(self):
        record = self.record()
        record.update(exam="NTCE", level="chuzhong", subject="dili", knowledge_node_ids=["ntce.chuzhong.dili.atmosphere"])
        context = self.context()
        context["dataset"] = "ntce"
        context["knowledge"][record["knowledge_node_ids"][0]] = {}
        context["requirements"]["cet.read.r001"] = {"standard_id": "ntce.outline.310", "subject": "历史学科知识与教学能力", "level": "初级中学"}
        self.assertIn("Q_REQUIREMENT_SCOPE_MISMATCH", self.inspect(record, context))
        context["requirements"]["cet.read.r001"].update(subject="地理学科知识与教学能力", level="高级中学")
        self.assertIn("Q_REQUIREMENT_SCOPE_MISMATCH", self.inspect(record, context))
        context["requirements"]["cet.read.r001"]["level"] = "初级中学"
        self.assertNotIn("Q_REQUIREMENT_SCOPE_MISMATCH", self.inspect(record, context))

    def test_learning_resource_requires_ability_and_specific_requirement(self):
        resource = {"resource_id": "word-1", "knowledge_node_ids": ["cet4.read.locate"], "source": self.record()["source"]}
        inspector = getattr(self.validator, "inspect_resource", None)
        self.assertIsNotNone(inspector, "学习资源也必须纳入全量引用验收")
        rules = {i["rule"] for i in inspector(resource, self.context())}
        self.assertIn("R_ABILITY_MISSING", rules)
        self.assertIn("R_REQUIREMENT_MISSING", rules)

    def test_translation_resource_cannot_reference_missing_rubric(self):
        resource = self.record()
        resource.update(resource_id="translation-1", task_type="paragraph_translation", rubric_id="unknown-rubric")
        resource["content"] = {"prompt": "原文", "reference_answer": "Translation"}
        inspector = getattr(self.validator, "inspect_resource", None)
        self.assertIsNotNone(inspector)
        self.assertIn("R_RUBRIC_DANGLING", {i["rule"] for i in inspector(resource, self.context())})

    def test_politics_subject_accepts_official_morality_and_law_name(self):
        record = self.record()
        record.update(exam="NTCE", level="chuzhong", subject="zhengzhi", knowledge_node_ids=["ntce.chuzhong.zhengzhi.law"])
        context = self.context()
        context["dataset"] = "ntce"
        context["knowledge"][record["knowledge_node_ids"][0]] = {}
        context["requirements"]["cet.read.r001"] = {"standard_id": "ntce.outline.309", "subject": "道德与法治学科知识与教学能力", "level": "初级中学"}
        self.assertNotIn("Q_REQUIREMENT_SCOPE_MISMATCH", self.inspect(record, context))

    def test_teacher_exam_requirement_cannot_substitute_cet_requirement(self):
        context = self.context()
        context["requirements"]["cet.read.r001"] = {"standard_id": "ntce.outline.305", "subject": "英语", "level": "初级中学"}
        self.assertIn("Q_REQUIREMENT_SCOPE_MISMATCH", self.inspect(self.record(), context))

    def test_source_conflict_is_not_a_usable_scoring_answer(self):
        record = self.record()
        record["content"]["answer_status"] = "source_conflict"
        self.assertIn("Q_ANSWER_SOURCE_CONFLICT", self.inspect(record, self.context()))

    def test_known_cross_question_risk_remains_in_acceptance_queue(self):
        record = self.record()
        record["review"]["cross_question_risk"] = ["multiple_complete_choice_sequences"]
        self.assertIn("Q_SOURCE_BOUNDARY_AMBIGUOUS", self.inspect(record, self.context()))

    def test_teacher_material_resolves_source_files_and_checks_question_links(self):
        resource = {"material_id": "ntce.chuzhong.dili.test.m01", "text": "材料正文", "source_files": [{"path": self.record()["source"]["origin_file"]}], "question_ids": ["missing-question"], "knowledge_node_ids": [], "ability_ids": [], "exam_requirement_ids": []}
        context = self.context()
        context.update(dataset="ntce", question_ids=set())
        inspector = getattr(self.validator, "inspect_resource", None)
        rules = {i["rule"] for i in inspector(resource, context)}
        self.assertNotIn("R_SOURCE_UNRESOLVED", rules)
        self.assertNotIn("R_ID_MISSING", rules)
        self.assertIn("R_QUESTION_DANGLING", rules)

    def test_unreviewed_content_cannot_pass_full_acceptance(self):
        record = self.record()
        record["review"] = {"status": "待复核", "content_verified": False}
        self.assertIn("Q_CONTENT_PENDING_REVIEW", self.inspect(record, self.context()))

    def test_pending_official_alignment_is_not_completed_alignment(self):
        context = self.context()
        context["knowledge"]["cet4.read.locate"]["mapping_status"] = "pending_official_alignment"
        self.assertIn("Q_REQUIREMENT_MAPPING_PENDING_REVIEW", self.inspect(self.record(), context))

    def test_extra_requirement_from_another_skill_is_rejected(self):
        context = self.context()
        context["requirements"]["cet.listen.r001"] = {"standard_id": "cet.syllabus.2016", "module": "听力", "level": ["CET-4"]}
        record = self.record()
        record["exam_requirement_ids"].append("cet.listen.r001")
        self.assertIn("Q_REQUIREMENT_MODULE_MISMATCH", self.inspect(record, context))

    def test_json_quote_preserves_english_word_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "ability.json").write_text(json.dumps({"id": 1, "remark": "A small bird"}), encoding="utf-8")
            requirement = {"content": "Asmallbird", "locator": {"json_path": "ability.json", "json_pointer": "/remark", "official_descriptor_id": 1}}
            self.assertIn("REQUIREMENT_CONTENT_NOT_AT_LOCATOR", {i["rule"] for i in self.validator.inspect_requirement(requirement, [base])})

    def test_html_table_locator_requires_positive_one_based_indices(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "content.html").write_text('<table><tr><td>总计</td><td>总计</td><td>总计</td><td>57</td><td>100%</td><td>125分钟</td></tr></table>', encoding="utf-8")
            requirement = {"exam_scope": ["CET-4"], "content": "CET-4：题数总计57；总分值比例100%；总考试时间125分钟。", "locator": {"html_path": "content.html", "table": 0, "row": 0}}
            self.assertIn("REQUIREMENT_TABLE_LOCATOR_INVALID", {i["rule"] for i in self.validator.inspect_requirement(requirement, [base])})

    def test_three_choices_do_not_make_a_four_choice_exam_item_complete(self):
        record = self.record()
        del record["content"]["options"]["D"]
        self.assertIn("Q_OPTIONS_INCOMPLETE", self.inspect(record, self.context()))

    def test_cloze_without_shared_word_bank_cannot_be_scored(self):
        record = self.record()
        record["question_type"] = "选词填空"
        record["content"]["options"] = {}
        record["extra"]["passage_id"] = "cloze"
        context = self.context()
        context["passages"]["cloze"] = {"text": "A passage with a numbered blank."}
        self.assertIn("Q_OPTIONS_INCOMPLETE", self.inspect(record, context))

    def test_placeholder_analysis_is_not_substantive_analysis(self):
        record = self.record()
        record["analysis"] = {"key_info": "缺", "option_compare": "ABCDE", "trace_back": "略"}
        self.assertIn("Q_ANALYSIS_INCOMPLETE", self.inspect(record, self.context()))

    def test_subjective_letter_placeholder_is_not_reference_answer(self):
        record = self.record()
        record["question_type"] = "教学设计"
        record["content"]["answer"] = "ABCDE"
        self.assertIn("Q_ANSWER_MISSING", self.inspect(record, self.context()))

    def test_numeric_difficulty_requires_calibration_evidence(self):
        record = self.record()
        record["difficulty"] = 0.62
        self.assertIn("Q_DIFFICULTY_UNCALIBRATED", self.inspect(record, self.context()))

    def test_existing_file_does_not_imply_a_copyright_license(self):
        record = self.record()
        record["source"]["copyright"] = {"authorization_status": "unknown", "use_scope": None}
        self.assertIn("Q_COPYRIGHT_UNRESOLVED", self.inspect(record, self.context()))

    def test_audio_end_before_start_is_rejected(self):
        record = self.record()
        record.update(module="听力理解", question_type="短篇新闻")
        record["extra"]["audio"] = {"url": "https://example.invalid/listening.mp3", "start_seconds": 60, "end_seconds": 30}
        self.assertIn("Q_AUDIO_SEGMENT_INVALID", self.inspect(record, self.context()))

    def test_prerequisite_cycles_cannot_support_learning_path(self):
        inspector = getattr(self.validator, "inspect_prerequisites", None)
        self.assertIsNotNone(inspector)
        edges = [{"src": "a", "dst": "b", "rel": "prereq_of"}, {"src": "b", "dst": "a", "rel": "prereq_of"}]
        self.assertIn("GRAPH_PREREQUISITE_CYCLE", {i["rule"] for i in inspector(edges)})

    def test_proposed_prerequisite_is_not_a_reviewed_dependency(self):
        inspector = getattr(self.validator, "inspect_prerequisites", None)
        self.assertIsNotNone(inspector)
        edges = [{"src": "a", "dst": "b", "type": "prerequisite_candidate", "status": "proposed_pending_subject_expert"}]
        self.assertIn("GRAPH_PREREQUISITE_PENDING_REVIEW", {i["rule"] for i in inspector(edges)})

    def test_question_file_hash_mismatch_is_not_hidden_by_file_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "source.txt").write_text("原始题目", encoding="utf-8")
            record = self.record()
            record["source"] = {"files": [{"path": "source.txt", "sha256": "0" * 64}]}
            context = self.context()
            context["base_paths"] = [base]
            self.assertIn("Q_SOURCE_HASH_MISMATCH", self.inspect(record, context))

    def test_reference_context_hash_detects_wrong_physical_lines(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "source.txt").write_text("尊重差异\v学习方式\n别的段落\n", encoding="utf-8")
            record = self.record()
            record["source"] = {"files": [{"path": "source.txt", "locator": {"line_start": 2, "line_end": 2, "line_convention": "physical_LF", "context_sha256": hashlib.sha256("学习方式".encode()).hexdigest()}}]}
            context = self.context()
            context["base_paths"] = [base]
            self.assertIn("Q_SOURCE_CONTEXT_MISMATCH", self.inspect(record, context))

    def test_empty_option_values_cannot_supply_four_choices(self):
        record = self.record()
        record["content"]["options"] = dict.fromkeys("ABCD", " ")
        self.assertIn("Q_OPTIONS_INCOMPLETE", self.inspect(record, self.context()))
        self.assertNotIn("Q_ANSWER_INVALID", self.inspect(record, self.context()))

    def test_single_choice_cannot_have_multiple_answer_letters(self):
        record = self.record()
        record["content"]["answer"] = "AD"
        self.assertIn("Q_ANSWER_INVALID", self.inspect(record, self.context()))

    def test_answer_status_object_is_not_answer_text(self):
        record = self.record()
        record["content"]["answer"] = {"status": "missing"}
        self.assertIn("Q_ANSWER_MISSING", self.inspect(record, self.context()))

    def test_reading_question_needs_task_even_with_full_passage(self):
        record = self.record()
        record["content"]["stem"] = ""
        record["extra"]["passage_id"] = "p"
        context = self.context()
        context["passages"]["p"] = {"text": "A complete passage."}
        self.assertIn("Q_STEM_EMPTY", self.inspect(record, context))

    def test_passage_from_other_exam_or_paper_is_not_a_valid_link(self):
        record = self.record()
        record["source"].update(year="2024-06", paper="第一套")
        record["extra"]["passage_id"] = "p"
        context = self.context()
        context["passages"]["p"] = {"text": "A complete passage.", "exam": "CET-6",
                                     "source": {"year": "2023-12", "paper": "第三套"}}
        self.assertIn("Q_PASSAGE_IDENTITY_MISMATCH", self.inspect(record, context))

    def test_explicit_passage_backlink_must_include_question(self):
        record = self.record()
        record["extra"]["passage_id"] = "p"
        context = self.context()
        context["passages"]["p"] = {"text": "A complete passage.", "question_ids": ["another-question"]}
        self.assertIn("Q_PASSAGE_IDENTITY_MISMATCH", self.inspect(record, context))

    def test_published_answer_needs_separate_source_role(self):
        record = self.record()
        record["source"]["files"] = [{"path": record["source"]["origin_file"], "role": "original_content"}]
        self.assertIn("Q_ANSWER_SOURCE_UNLOCATED", self.inspect(record, self.context()))

    def test_answer_locator_cannot_name_another_question(self):
        record = self.record()
        record["extra"]["number"] = 1
        record["source"]["files"] = [{"path": record["source"]["origin_file"], "role": "answer_analysis",
                                      "locator": {"question_number": 2}}]
        self.assertIn("Q_ANSWER_IDENTITY_MISMATCH", self.inspect(record, self.context()))
        self.assertFalse(self.validator.usable_answer_field(record, self.validator.inspect_question(record, self.context())))

    def test_extra_requirement_outside_knowledge_mapping_is_reported(self):
        record = self.record()
        record["exam_requirement_ids"].append("cet.read.r002")
        context = self.context()
        context["requirements"]["cet.read.r002"] = {"standard_id": "cet.content.cet4"}
        self.assertIn("Q_REQUIREMENT_BINDING_UNSUPPORTED", self.inspect(record, context))

    def test_ambiguous_boundary_remains_pending_without_cross_question_terms(self):
        record = self.record()
        record["review"].update(source_boundary_status="ambiguous_boundary_candidates", cross_question_risk=[])
        self.assertIn("Q_SOURCE_BOUNDARY_AMBIGUOUS", self.inspect(record, self.context()))

    def test_unlabelled_type_is_a_visible_gap(self):
        record = self.record()
        record["question_type"] = "未标注"
        self.assertIn("Q_TYPE_UNVERIFIED", self.inspect(record, self.context()))

    def test_checked_control_with_bound_answer_can_pass_mechanical_contract(self):
        record = self.record()
        record["extra"].update(number=1, passage_id="p")
        record["source"]["files"] = [{"path": record["source"]["origin_file"], "role": "answer_key", "locator": {"question_number": 1}}]
        record["source"]["copyright"] = {"authorization_status": "authorized", "holder": "test publisher", "use_scope": "research_non_commercial"}
        record["review"] = {"status": "expert_reviewed", "checked_by": "test reviewer", "checked_at": "2026-10-04"}
        record["content"]["answer_status"] = "verified"
        record["difficulty"] = 0.5
        record["difficulty_calibration"] = {"method": "expert_rating", "reviewer": "test reviewer", "reviewed_at": "2026-10-04"}
        context = self.context()
        context["passages"]["p"] = {"text": "A complete source passage.", "exam": "CET-4", "question_ids": [record["question_id"]]}
        self.assertEqual(set(), self.inspect(record, context))
        self.assertTrue(self.validator.usable_answer_field(record, self.validator.inspect_question(record, context)))

    def test_declared_research_scope_is_accepted_without_claiming_authorization(self):
        record = self.record()
        record["source"]["copyright"] = {"authorization_status": "unknown", "use_scope": "research_non_commercial"}
        codes = self.inspect(record, self.context())
        self.assertNotIn("Q_COPYRIGHT_UNRESOLVED", codes)
        self.assertNotIn("Q_COPYRIGHT_CLAIM_UNSUPPORTED", codes)
        self.assertNotIn("Q_COPYRIGHT_SCOPE_OUT_OF_BOUNDS", codes)

    def test_copyright_boundaries_are_explicit(self):
        record = self.record()
        record["source"]["copyright"] = {"authorization_status": "authorized", "use_scope": "research_non_commercial"}
        self.assertIn("Q_COPYRIGHT_CLAIM_UNSUPPORTED", self.inspect(record, self.context()))
        record["source"]["copyright"] = {"authorization_status": "unknown", "use_scope": "commercial"}
        self.assertIn("Q_COPYRIGHT_SCOPE_OUT_OF_BOUNDS", self.inspect(record, self.context()))
        record["source"]["copyright"] = {"authorization_status": "unknown"}
        self.assertIn("Q_COPYRIGHT_UNRESOLVED", self.inspect(record, self.context()))

    def test_listening_transcript_reference_must_resolve(self):
        record = self.record()
        record["extra"]["listening_transcript_ids"] = ["missing-transcript"]
        self.assertIn("Q_TRANSCRIPT_DANGLING", self.inspect(record, self.context()))

    def test_listening_transcript_group_must_include_original_question(self):
        record = self.record()
        record["extra"].update(number=4, listening_transcript_ids=["transcript"])
        context = self.context()
        context["transcripts"] = {"transcript": {"exam": "CET-4", "text": "A complete listening script.", "extra": {"question_numbers": [8, 9]}}}
        self.assertIn("Q_TRANSCRIPT_IDENTITY_MISMATCH", self.inspect(record, context))

    def test_retained_parser_artifact_is_visible_and_cannot_be_scored(self):
        record = self.record()
        record["extra"].update(active=False, scoring_eligible=False,
                               source_discovery={"status": "parser_artifact_outside_CET_number_range"})
        self.assertIn("Q_PARSER_ARTIFACT_INACTIVE", self.inspect(record, self.context()))
        self.assertFalse(self.validator.usable_answer_field(record, []))

    def test_missing_stem_markers_are_not_actual_question_tasks(self):
        for marker in ("缺", "略", "\u200b缺", "****"):
            with self.subTest(marker=marker):
                record = self.record()
                record["content"]["stem"] = marker
                self.assertIn("Q_STEM_EMPTY", self.inspect(record, self.context()))
        for operator in ("*", "**", "+"):
            self.assertTrue(self.validator.substantive_text(operator))


if __name__ == "__main__":
    unittest.main()
