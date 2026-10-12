# 数据集/四六级/questions/ —— 四六级题库 JSONL 源（客观题/写作/翻译逐题记录），由 scripts 抽取与修复管线生成，services/knowledge/repository.py 消费，受四个契约测试与 validate_kb 门禁

- 角色：整个四六级知识库唯一的题目事实源；cards、graph L6、paper_specs 都从这里派生。
- 生成：`scripts/build_questions.py`（docx 管线，2015-2023 场次）与 `scripts/build_questions_pdf.py`（PDF 管线，2024-12/2025-06/2025-12 场次）写卷文件；`scripts/unify_writing_translation.py` 写各层的 writing.jsonl 与 translation.jsonl；fill_answers / repair_kb / migrate_v2_schema / correct_misaligned_answers / quarantine_* / restore_original_stems 等修复脚本按幂等规则就地增补字段，不重排记录。
- 消费：`services/knowledge/repository.py` 以 `QUESTION_ROOTS` 装载本目录（判分、检索、学情统计的题面都经此门面）；`scripts/generate_cards.py` 读它出 cards；`scripts/build_graph.py` 读它出 L6 题目节点。
- 门禁：`tests/test_cet_eight_layer_contract.py`（逐题必须符合 `数据集/教资/schemas/question.json` 附录 A.1 共享 Schema）、`tests/test_status_vocabulary.py`（review.status 六态 / content.answer_status 五态词表校验，answer_status 必填）、`tests/test_cet_passage_references.py`（阅读题与 passage 绑定判据）、`tests/test_cet_repair.py`（修复脚本行为）、`审查/validate_kb.py`（阅读题必须有语篇、来源指针、要求 ID 映射等全量验收）。改数据必须重跑相应 scripts 脚本再过关，不手改 JSONL。

## 文件清单

- `README.md`（本文件）—— 手维护目录说明。
- `cet4/` —— 四级题库，60 个数据文件（58 个卷文件 + writing.jsonl + translation.jsonl），详见 `cet4/README.md`。
- `cet6/` —— 六级题库，70 个数据文件（68 个卷文件 + writing.jsonl + translation.jsonl），详见 `cet6/README.md`。

全库现算（126 个 jsonl 合计 5632 条记录）：
- 客观题 5340 条（= cards 5340 张）、写作 146 条（73+73）、翻译 146 条（73+73）。
- 活动源题 5628 条；`extra.active=false` 的伪题 4 条全部在 `cet4/2015-12_p2.jsonl`（reading-56..59，原解析器把段落尾注当题，停用且不可判分）。
- `review.status`：auto_parsed 5354、needs_fix 177、quarantined 101 —— 全部为待专家审核状态，没有任何 checked/expert_reviewed 记录。
- `content.answer_status`（五态词表）：missing 3954、letter_only 1285、reference_only 292、source_conflict 101；有答案 1577、answer 为 null/空 4055。source_conflict 题一律 `review.status=quarantined` 且 `content.answer=null`（隔离历史保留在 extra，不生效于判分）。
- `difficulty`：有值 1618（全部 `difficulty_meta.calibration_status=heuristic_estimated`，即 heuristic-linguistic-v1 估算）、null 4014（`difficulty_metadata.status=pending_calibration`），无实测校准，不得据此运行 IRT 诊断。

逐条字段口径：读取 `question_id/exam/module/question_type/content/analysis/knowledge_node_ids/ability_ids/exam_requirement_ids`；答案在 `content.answer`，原始解析在 `analysis.raw`（提取方法/定位/状态并存），来源多入口在 `source.files[].path/role/locator`。判分前必须排除 `extra.active=false`、`extra.scoring_eligible=false`、source_conflict、缺答案、选项不完整记录。
