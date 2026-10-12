# 数据集/四六级/ontology/ —— 四六级知识本体（标准、素养目标、能力、知识点、量规、本体层边、词汇实体），build_ontology_v2/migrate_v2_schema/repair_kb/expand_knowledge_graph 生成，repository.py 与 build_graph.py 消费

- 角色：官方标准引用与 L1–L4 语义骨架的存放处；图谱目录 graph/ 是它的导出投影，这里是源。
- 生成：`scripts/build_ontology_v2.py`（standards.json、ability_nodes.jsonl、knowledge_nodes.jsonl、edges.jsonl，幂等可复跑）、`scripts/migrate_v2_schema.py`（mastery_template.json）、`scripts/repair_kb.py`（scoring_rubrics.jsonl）、`scripts/expand_knowledge_graph.py`（vocabulary_entities.jsonl）。`exam_tree.json` 无脚本写入点（全目录 grep 无命中），为手维护源数据，改动过 `审查/validate_kb.py`。
- 消费：`services/knowledge/repository.py`（`CET_RUBRIC_FILE = ontology/scoring_rubrics.jsonl`；official 要求引用经 `权威资料/requirements.jsonl`）、`services/knowledge/trust.py`（量规 `official_scoring` 提示语）、`scripts/build_graph.py`（L1 能力/L2 知识点/L4 题型节点）。
- 门禁：`tests/test_cet_eight_layer_contract.py`（八层与先修候选状态）、`审查/validate_kb.py`（cet.* 条款 ID 与模块映射校验）、`tests/test_status_vocabulary.py` 不查本体文件但要求引用它的题面状态词表一致。所有自动标注保持初标：脚本不生成专家姓名、审核日期或"已审核"。

## 文件清单

- `standards.json`（6297B, 141L）—— 顶层 `standards`（3 条）+ `素养目标`（2 条）。CSE 字段的分法：`std.cse` 的现行编号是 `code: GF0018-2024`，`historical_code: GF0018-2018` 保留旧版号，`versions[]` 两条分别登记 `cse.gf0018-2018` 与 `cse.gf0018-2024` 的官方原文链接、权威资料本地 PDF、sha256 与核验方法；CET 分数↔CSE 等级对接标注"尚未核验"，不做数值换算。`std.cet.syllabus` 指向 2016 修订版考试大纲（本地 `权威资料/originals/cet.syllabus.2016.pdf`，sha256 记录，verified=true 仅指字节核验）。重建：build_ontology_v2.py。
- `ability_nodes.jsonl`（53630B, 28L）—— L3 能力节点 `ab.{cet4|cet6}.{模块}.{技能}`；字段 id/name/module/parent/supports/knowledge_node_ids/exam_requirement_ids/requirement_mappings。CSE 口径：`cse_level=null` + `cse_alignment.status=pending_official_CET_CSE_linking_evidence`；原先把 CET-4/6 直接写成 CSE 4/5 的数字移入历史初标字段 `_legacy_unverified_cse_level`，只作留档不作等级。`extra.content_review.expert_review.status=pending`，`difficulty_metadata.status=pending_calibration`。由 build_ontology_v2.py 重生成。
- `knowledge_nodes.jsonl`（95420B, 48L）—— L2/L4 知识点 `cet{4|6}.{模块}.{考点}`（含 parent/prereq/question_types/ability_ids）；正式 `prereq` 保持空数组，先修只以候选形式存在（见 edges）。由 build_ontology_v2.py 重生成。
- `edges.jsonl`（32004B, 147L）—— 本体层内部边（字段 src/dst/rel/说明）；rel 分布（现算）：exemplifies 38、prerequisite_candidate 64、supports 26、confused_with 10、anchored_by 3、misconception_lead_to 4、sub_ability 2。`prerequisite_candidate` 即"proposed_rel=prereq_of、active=false"的候选先修，知识点侧留 `candidate_prereq` 待审列表；`confused_with`/`misconception_lead_to` 同样未经教研核定。由 build_ontology_v2.py 重生成。
- `scoring_rubrics.jsonl`（7798B, 2L）—— 写作与翻译各 1 条官方整体印象五档量规：`cet.writing.holistic.2016`、`cet.translation.holistic.2016`，method=official_holistic_band_selection，max_raw_score=15，bands 含 raw_score_range 与 NFKC 归一化官方原文 descriptor；转述自官方文档仍待专家复核（trust.py 对 `official_scoring` 字段挂提示语）。由 repair_kb.py 重生成。
- `mastery_template.json`（645B, 20L）—— L5 用户掌握度运行时记录模板（user_id×knowledge_node_id、mastery、status、evidence、FSRS/SM-2 计划），明确"掌握度是运行时数据，不入静态知识库"，供学习 Agent 落库。由 migrate_v2_schema.py 重生成。
- `vocabulary_entities.jsonl`（15996726B, 9942L）—— 考纲词汇图谱实体 `{entity_id, word, phonetic, level, tier, pos_meaning, knowledge_node_ids, ability_ids, exam_requirement_ids, real_exam_examples, source}`；tier 区分大纲词/核心词等来源层；real_exam_examples 为空的多，真题例句关联是本脚本目标但受源限制。由 expand_knowledge_graph.py 重生成（输入 vocabulary/*.jsonl）。
- `exam_tree.json`（1584B, 75L）—— CET-4/CET-6 → 模块 → 题型层级树（占比/时长/题型清单，如写作 15% 30min、听力 35% 25/30min、阅读 35% 40min、翻译 15% 30min）；手维护，无生成脚本，`cet_overview.md` 的分值口径引用它。
- `README.md`（本文件）—— 手维护说明。
