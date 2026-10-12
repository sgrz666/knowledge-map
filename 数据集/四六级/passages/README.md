# 数据集/四六级/passages/ —— 阅读共享语篇库（449 篇 JSONL），build_questions.py 生成，题目按 passage_id 绑定、repository 与图谱 L5 消费

- 角色：阅读题组（选词填空/长篇匹配/仔细阅读）共享的原文语料；一篇文章被同题组的多个题号共用，是"题面挂原文"的中间层，本身不含题目或答案。
- 生成：`scripts/build_questions.py`（从解析卷抽 `passages/reading.jsonl`）；引用修复由 `scripts/repair_passage_references.py` 维护题目侧 `extra.passage_id` 指向。重跑脚本覆盖，不手改。
- 消费：`services/knowledge/repository.py`（第 590 行按 `resource_id` 取语篇回填题面，是运行时直接读的库内数据文件）、`scripts/generate_cards.py`（嵌进「### 语篇材料」，含选词填空 word_bank）、`scripts/build_graph.py`（L5 material 节点 449）、`scripts/batch_upgrade_analysis.py`、`审查/validate_kb.py`、`kb_tools/cet_official_examples.py`。
- 门禁：`tests/test_cet_passage_references.py`（每题的 `extra.passage_id` 必须命中本库 `resource_id`）、`tests/test_cet_repair.py`、`审查/validate_kb.py`（引用完整性）。

## 文件清单

- `reading.jsonl`（5045464B, 449L，449 条）—— 每行一篇语篇。关键字段：`resource_id`（命名 `cet{4|6}-{YYYY-MM}-p{N}-reading-{cloze|matching|reading}`，如 `cet4-2015-06-p1-reading-cloze`）、`kind`（三值：`reading` 仔细阅读 223、`matching` 长篇匹配 114、`cloze` 选词填空 112，合计 449）、`text`（全文）、`extra.paragraphs`（段落数组，matching 用 A–K/字母段落定位）、`extra.question_ids`（本篇服务的题号列表，即题组绑定）、`extra.word_bank`（cloze 的 A–O 备选词库）、`extra.title`/`theme`/`word_count`、`exam`/`year`/`paper`、`knowledge_node_ids`/`ability_ids`/`exam_requirement_ids`、`review.status`、`source`。由 build_questions.py 重生成，不手改。被同卷阅读题通过 `extra.passage_id` 引用（test_cet_passage_references 校验）。
- `README.md`（本文件）—— 手维护说明（旧版误称本目录含 `listening_transcripts.jsonl`；听力稿实际在 `../listening/transcripts.jsonl`，本目录只有 `reading.jsonl`）。

## 改这里之前要知道的

- passage_id 与题组是强绑定：删除/改名一篇会让引用它的题号成悬挂引用，`tests/test_cet_passage_references.py` 立即失败；重排题号要用 `repair_passage_references.py` 而不是手改。
- 语篇全文来自扫描/解析卷的文字层，仍有 `pending_expert_review`；`审查/validate_kb.py` 会跑引用与结构校验。
- 听力原文不在此目录；旧 README 把两者混为一谈是错的，已在上方标注。
