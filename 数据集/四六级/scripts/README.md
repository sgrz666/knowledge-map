# 数据集/四六级/scripts/ —— 四六级知识库的全量构建/修复管线，脚本为手维护源码，产物落在本知识库各数据目录，验收由 tests 与 审查/validate_kb.py 负责

- 本目录是四六级数据集唯一的生成代码所在处：拆题、词汇、写作/翻译、模板、图谱、OCR 补录、隔离修复、统计共 49 个顶层脚本（47 个 .py + 2 个 .ps1）。
- 总入口 `rebuild.py`：不带 `--extract` 按 migrate_v2_schema → restore_original_stems → recover_reading_resources → recover_listening → fill_answers → repair_kb → migrate_v2_schema（二次绑定 A.1 契约字段）→ build_graph → build_stats 顺序执行；带 `--extract --src <资料合集根>` 时先跑 build_ontology_v2 → build_vocab → build_questions → build_questions_pdf → build_writing_translation → build_templates 六个抽取器。
- 消费端：`services/knowledge/repository.py` 读 questions/graph/manifest/paper_specs/ontology/scoring_rubrics/passages（这些产物均由本目录脚本生成）；`services/knowledge/vector_index.py` 读 cards；本目录被 `tests/test_cet_repair.py` 直接 import 做行为回归。
- 改本目录脚本要过的门禁：`tests/test_cet_repair.py`（fill_answers/build_writing_translation/docx_source/build_graph/repair_kb 等）、`tests/test_cet_passage_references.py`（repair_passage_references 匹配判据）、`tests/test_cet_eight_layer_contract.py`（build_graph 八层导出与附录 A Schema）、`审查/validate_kb.py`（全量验收）、`tests/test_status_vocabulary.py`（写入脚本必须遵守 数据集/教资/schemas/question.json 的六态 review.status / 五态 answer_status 词表）。
- **重要**：上级 `数据集/四六级/README.md` 是 `build_stats.py` 每次运行重写的产物（build_stats.py 第 151/209 行），绝对不要手工编辑它；各数据目录的导航说明写在各子目录 README 里，本文件就是本节说明的落点。

## 文件清单

顶层 50 个文件（README.md + 49 个脚本）；大小以字节计，行数为现算。除 README.md 外脚本均为手维护源码（可改，改后须跑上述门禁）；`_staging/` 与 `__pycache__/` 为产物目录，不在其中新建文件。

### 抽取与建库
- `rebuild.py`（1638B, 32L）—— 管线编排器，subprocess 按顺序调用其余脚本；参数 `--extract` `--src` `--kb`（默认本知识库根）。
- `cet_common.py`（9242B, 135L）—— 共享模块：`load_jsonl`/`jsonl_dumps`（转义 U+0085/U+2028/U+2029 防断行）/`canonical_id`（新旧题号 ID 互认）/`fill_missing`（无损增量合并，生成器不得擦除已存审核/证据/扩展字段）；被各 build/fill 脚本 import，不单独运行。
- `docx_source.py`（5665B, 94L）—— 共享模块：按 Word 编号 XML 读段落/表格并给出源定位器（python-docx）；被 test_cet_repair 直接测试。
- `cet_pdf_columns.py`（7282B, 180L）—— 共享模块：PyMuPDF 按字符 bbox 分栏还原双栏解析册文本流，消除题号/答案串栏。
- `build_questions.py`（31776B, 629L）—— P3 docx 主管线拆题（含 2015-2016 老格式兼容）；参数 `--src --stage --kb`；产出 questions/{cet4,cet6}/{YYYY-MM}_p{n}.jsonl、passages/reading.jsonl、writing/_prompts.jsonl、translation/_from_papers.jsonl、manifest/papers.jsonl、manifest/parse_report.json；输入 docx 来自 `scripts/_staging/cet4|cet6/`（38+38 份）。
- `build_questions_pdf.py`（6363B, 126L）—— P3b PDF 拆题，仅处理无 docx 且有文本层的 2024-12/2025-06/2025-12 场次；参数 `--src --kb`；写入同一批 questions 卷文件。
- `build_vocab.py`（9253B, 203L）—— P2 词汇库：大纲词 xls + 1500 核心词 PDF + 高频词组/高频词 + 翻译热点词；参数 `--src --out`（vocabulary 目录）；覆盖产出 5 个 JSONL。
- `build_writing_translation.py`（15294B, 201L）—— 从源卷恢复带原文边界的写作/翻译任务与来源绑定；参数 `--src --kb`；产出 writing/model_essays.jsonl、translation/items.jsonl、manifest/task_source_bindings.jsonl、manifest/writing_translation_extract_report.json。
- `build_templates.py`（6198B, 135L）—— P5 写作模板库：模板句型 docx + 模板 PDF → writing/templates.jsonl + writing/md/templates.md；参数 `--src --kb`。
- `unify_writing_translation.py`（9345B, 221L）—— 把 writing/model_essays.jsonl 与 translation/items.jsonl 的题面统一规整并入题库：写 questions/{cet4,cet6}/writing.jsonl 与 translation.jsonl（rubric_id 默认 cet.writing.holistic.2016 / cet.translation.holistic.2016）；固定路径运行，无参数。
- `build_ontology_v2.py`（11706B, 141L）—— 本体 v2（规范 §3.2/§3.4）：L0 标准/大纲 → L0.5 素养目标 → L1 能力 → L2 知识点 → 题型 → 试题；产出 ontology/standards.json、ability_nodes.jsonl、knowledge_nodes.jsonl、edges.jsonl；幂等可复跑，无参数。
- `migrate_v2_schema.py`（24400B, 475L）—— v2 Schema 迁移（§3.3 参考数据格式）：补 question_id/source/knowledge_node_ids/ability_ids/content/analysis/tags/extra，细粒度挂载知识点，资源节点挂图谱，产出 ontology/mastery_template.json（L5 运行时模板）；幂等（含 question_id 即视为已迁移）；还负责把历史 `reviewed_by/reviewed_at` 合并进 `review.checked_by/checked_at`。
- `build_graph.py`（12582B, 239L）—— 图谱导出：按 §3.2 八层与 §3.4 边契约生成 graph/nodes.jsonl、graph/edges.jsonl 与 graph/graph_stats.json；未核定先修/易混淆一律候选态（active_for_learning_path=False），自动映射一律 verified=False；无参数（路径由 __file__ 定位）。
- `expand_knowledge_graph.py`（14936B, 304L）—— 扩展图谱：把 vocabulary/*.jsonl 词汇挂成考纲词汇实体并补真题例句关联边，产出 ontology/vocabulary_entities.jsonl（9942 条），同步进 graph L7；无参数。
- `generate_cards.py`（18438B, 394L）—— 从 questions+passages+listening 生成 RAG 双轨自包含 Markdown 题卡：cards/{cet4|cet6}/{YYYY-MM}-p{n}/qNN.md，5340 份（YAML Frontmatter + 原文/音频 + 四阶段解析）；无参数。
- `generate_paper_specs.py`（14249B, 289L）—— 按附录 A.4 生成套卷规格元数据：读 manifest/papers.jsonl 与各题库文件，写 manifest/paper_specs.jsonl（126 条）；同时写 数据集/教资/paper_specs.jsonl；无参数。
- `repair_kb.py`（26030B, 362L）—— v2 产物修复：接官方 2016 大纲要求 ID、可用任务 Schema、rubric；写 ontology/scoring_rubrics.jsonl、standards.json 更新、manifest/repair_report.json、manifest/review_baseline.json；所有自动标签保持初标，不宣称专家审核/难度校准/CSE 对接；无参数；被 test_cet_repair 覆盖。
- `build_stats.py`（29565B, 248L）—— 全库现算统计（v2 字段口径，保留全部记录与缺口）：产出 manifest/stats.json、manifest/ingest_log.md 和上级 `数据集/四六级/README.md`（产物，禁手改）；参数 `--kb`（必填）。

### 答案补录与 OCR 链
- `fill_answers.py`（15539B, 241L）—— 第二轮：从 staging 解析册提取源键与逐题解释，只填缺失、冲突留待处理；参数 `--src --stage --kb`；产 manifest/answers_fill_report.json；被 test_cet_repair import。
- `fill_answers_ocr.py`（35134B, 761L）—— 第三轮：文本层损坏的解析册先经 Windows OCR（zh-Hans-CN, 200dpi，缓存 `scripts/_staging/ocr_cache/`）重建文本再补答案/解析；证据分级 level_a_identity / level_b_dedicated_source_content_crosscheck / level_b_dedicated_source_qa_structure / published_answer_grid（印刷成段答案表），全部保持 pending_expert_review；已有答案不覆盖，冲突只记候选；参数 `--kb --only --no-fa-text --debug-ocr`；产 manifest/answers_fill_ocr_report.json。
- `backfill_answers.py`（12825B, 284L）—— 从官方解析册 PDF/文档补全答案与结构化解析，只搬运已出版原文；参数 `--kb --inventory --out-report --dry-run`；读 manifest/answer_source_inventory.json，写 manifest/answer_backfill_report.json。
- `ocr_backfill.py`（20215B, 453L）—— 方案A：OCR 图片型/损坏解析册回填缺失答案；默认只评估并写 manifest/_ocr_eval.json，`--write` 才入库；信任门：交叉样本≥8 且一致率≥0.95 全量信任，<0.95 隔离，样本<8 走逐题身份匹配保守回填。
- `ocr_key_backfill.py`（7809B, 178L）—— 从 ocr_cache 提取「题号+裸字母」答案键表（41 份官方答案页 OCR），逐套一致率≥0.95 才写入，只填不覆盖；产 manifest/ocr_key_backfill_report.json。
- `ocr_text_backfill.py`（9657B, 249L）—— 从 ocr_cache 去空格归一化后提取「10．C」式答案与〖解析〗/〖解题思路〗段，交叉验证一致率≥阈值才写；默认只验证，`--apply` 执行；产 manifest/ocr_extract_backfill.json。
- `ocr_test_one.py`（1613B, 44L）—— 单份 image_only PDF 渲染前 N 页并 OCR 的验证脚本，只打印不落库。
- `ocr_batch.ps1`（2285B, 47L）—— Windows 内置 OCR（WinRT zh-Hans-CN）批量识别：参数 `-ListFile`（UTF-8 每行一个 PNG 路径），stdout 输出文本、页间 `===PAGE n===` 分隔。
- `ocr_page.ps1`（1927B, 37L）—— 单图版 OCR：参数 `-ImagePath`，stdout 输出识别文本。
- `explainer_answer_extract.py`（11402B, 273L）—— 讲解型解析册「X）【精析】」答案提取可行性验证，只读；产 manifest/explainer_answer_feasibility.json（threshold/papers/summary）。
- `extract_answers_from_analysis.py`（12671B, 305L）—— 从题库已有 analysis.raw 的结论句（「因此，答案为 D）」等）提取答案，处理否定语境/多模式冲突/段落定位干扰三类陷阱；已有答案一致率≥95% 才可用于补缺；产 manifest/analysis_answer_backfill.json。
- `diagnose_answer_sources.py`（5729B, 144L）—— 盘点每套卷本地答案/解析源文本质量三档（good/needs_ocr/broken_font）；产 manifest/answer_source_inventory.json（被 diag_*/verify_source_trust/backfill_answers 消费）。
- `scan_classify.py`（2913B, 79L）—— 只读：128 份 staging 解析册三分类；产 manifest/_scan_classify.json（REPO 由 `__file__` 上溯 3 级定位）。
- `scan_explainer_sources.py`（3850B, 118L）—— 只读扫描全部原始 PDF（344 份答案/解析文件），找含「答案详解 + X）【..】」锚点的册子建立 paper→源 映射；产 manifest/explainer_source_scan.json。
- `verify_source_trust.py`（4279B, 104L）—— 用题库已有答案验证解析册抽取一致率，≥95% 的源才准写入主库，其余进隔离名单；产 manifest/source_trust_report.json。

### 对齐诊断（题号错位专题，只读）
- `diag_align.py`（4901B, 145L）—— 题干指纹对齐诊断「解析册题号→题库题号」；参数 `--paper --pdf`。
- `diag_dump.py`（582B, 18L）—— 打印解析册分块 raw 文本（argv: PDF 路径 + 可选块号），调试用不落库。
- `diag_fingerprint.py`（4910B, 125L）—— 不依赖题号的内容指纹 1:1 匹配并回验一致率；产 manifest/fingerprint_diagnosis.json。
- `diag_offset.py`（4981B, 145L）—— 常数偏移/分段偏移搜索；产 manifest/offset_diagnosis.json。
- `gen_alignment_report.py`（5869B, 125L)—— 汇总两法结论：21 套 distrusted 无一达 0.95（最好 0.933/0.889），方案B 不可行、整套隔离零写入；产 manifest/alignment_backfill_report.json。

### 修复/隔离/恢复
- `correct_misaligned_answers.py`（12042B, 277L）—— 修正长篇阅读/选词填空按文本位置写回导致的整体错格：双锚点互验 + 一一对应约束 + 逐套一致率≥0.95 三判据齐备才改，旧值存 extra.answer_correction，同步清 difficulty；产 manifest/answer_correction_report.json。
- `quarantine_longpassage_answers.py`（5097B, 122L）—— 长篇阅读（段落匹配字母必须互异）答案有重复的卷整体清回 null，原值存 extra.answer_quarantine，保留 difficulty；明确排除选词填空（15 选 10 可重复）；产 manifest/longpassage_answer_quarantine.json。
- `quarantine_placeholder_answers.py`（8083B, 194L）—— 隔离 `ocr_head_letter` 从选项区取字母造成的占位答案（只处理 A 占比>45% 且样本≥5 的卷），extra.answer_extraction.quarantine 留原值，可回滚；产 manifest/placeholder_answer_quarantine.json。
- `restore_original_stems.py`（4848B, 74L）—— 仅从唯一原卷编号块恢复空题干/空题面，不生成；产 manifest/original_stem_recovery_report.json。
- `recover_reading_resources.py`（4612B, 82L）—— 只恢复原文明确给出的词库/段落字母标识，不做推断；产 manifest/reading_resource_recovery_report.json。
- `repair_passage_references.py`（19314B, 326L）—— 用有界原文内容同一性对账过期 passage 链接：保留 ID/解析器编号不能建立原始题号，只有完整题干+四选项或完整匹配陈述可以；写 extra.passage_reference_history/Review；产 manifest/passage_reference_repair_report.json；判据由 tests/test_cet_passage_references.py 回归。
- `recover_listening.py`（15642B, 210L）—— 审计全部本地 PDF/DOCX，恢复有界听力文字稿与题目绑定（要求明确卷次+题号区间+实际口述题目+四选项全等匹配，不生成任何文本）；参数 `--src --kb [--audit-only]`；产 listening/transcripts.jsonl、manifest/listening_recovery_report.json、manifest/source_transcript_audit.jsonl。
- `scan_audio_assets.py`（9886B, 257L）—— 扫描资料合集 120 个 MP3，建套卷映射（manifest/audio_catalog.json，102 个卷槽位成功映射），并把音频切片引用回写题目 extra.audio 与 transcripts 的 audio_ref。
- `cet_difficulty.py`（18870B, 445L）—— 难度标定 heuristic-linguistic-v1（题型基准/词汇/句法/认知负荷/篇章/级别六特征）；无作答数据，一律 calibration='heuristic'，证据不足保持 null，只写 difficulty 与 tags.difficulty，幂等（非 null 不重算）；参数 `--dry-run`；产 manifest/cet_difficulty_report.json。当前全库 1618 题有值、4014 题 null 待实测校准，不得据此跑 IRT。
- `batch_upgrade_analysis.py`（9643B, 252L）—— 调 DashScope（env `DASHSCOPE_API_KEY`，默认 qwen-plus，`--model` 可换）把题目 analysis.raw 改写为结构化三段式解析并写回 analysis；参数 `--limit N/--all --workers N`；产出 method 标 `*_structured_v1`，属模型生成，不代表人工核定。
- `infer_candidate_answers.py`（14166B, 324L）—— 对缺答案题（含隔离存根）基于语篇/听力稿证据让 LLM 推导候选答案与四段式解析，结果只落 extra.candidate_inference 与 analysis，绝不写 content.answer；参数 `--limit/--all --workers`，同样依赖 DashScope 环境变量。

### 其他顶层文件
- `README.md`（本文件，手维护）—— 本节说明。

## 顶层 1062 个文件中除脚本外还有什么

`find scripts -type f` 现算共 1062：顶层 50 个文件（上表）+ `__pycache__/` 12 个 .pyc + `_staging/` 1000 个文件。

`__pycache__/`（构建缓存，可随时删）：build_questions、build_writing_translation、cet_common、docx_source、fill_answers、infer_candidate_answers、migrate_v2_schema、recover_listening、recover_reading_resources、repair_kb、repair_passage_references、restore_original_stems 各 1 个 cpython-313.pyc。

`_staging/`（中间产物/证据目录，不在其中新建文件）：
- `cet4/` 38 个 docx、`cet6/` 38 个 docx —— 真题原卷（build_questions.py 的输入，如「2015年06月四级真题第1套.docx」）。
- `answers/cet4/` 68 个、`answers/cet6/` 60 个，共 128 份解析册 PDF/DOCX 拷贝（fill_answers、ocr_* 链的答案/解析源）。
- `ocr_cache/` 795 个：794 份「<源文件名>.200dpi.txt」OCR 全文缓存 + 1 份索引 json；fill_answers_ocr/ocr_key_backfill/ocr_text_backfill 复用，不重扫。
- `c/` 5 个空目录（manifest/passages/questions/translation/writing）—— 一次 `--kb` 指错产生的空壳，无文件。
- `ocr_dryrun.log` 1 个 —— OCR 干跑控制台留痕。

## 约定

- 脚本一律从仓库根运行，源资料根为 `英语四六级资料合集（2026年最新）(1)/`，官方 PDF 走 `权威资料/` 归档（仅作只读证据路径）。
- 所有生成器写 JSONL 都经 cet_common 的无损合并：既有审核字段、答案、解析、隔离历史、扩展字段不会被重跑擦除。
- 数据里的三层状态（review.status 六态 / content.answer_status 五态 / 抽取形状只留 extra.answer_provenance）以 `数据集/教资/schemas/question.json` 为单一权威 Schema，四六级不放副本；脚本写入状态值受 `tests/test_status_vocabulary.py` 门禁约束。
