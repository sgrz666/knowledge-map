# 数据集/四六级/vocabulary/ —— 分级词库（4 个 JSONL，共 14478 词/短语/主题项），build_vocab.py 生成，expand_knowledge_graph 与图谱 L7 消费

- 角色：四六级大纲词、核心词、高频词组与翻译主题词的分级词库，是"资源型"知识资产（供检索/背词/图谱资源层），不含题目与答案。
- 生成：`scripts/build_vocab.py`（argparse `--src --out`，路径须落在 `knowledge_map` 内），从大纲/讲义源解析产出 `words_cet4.jsonl`、`words_cet6.jsonl`、`core_words.jsonl`、`phrases_highfreq.jsonl`；`translation_topic_words.jsonl` 同属词库抽取。重跑覆盖，不手改 JSONL。
- 消费：`scripts/expand_knowledge_graph.py`（读 vocabulary/*.jsonl 生成 `ontology/vocabulary_entities.jsonl` 9942 实体）、`scripts/build_graph.py`（L7 资源节点里"词汇 14478"就是本目录 5 个词库之和）、`审查/validate_kb.py`。`services/knowledge/` 运行时不直接读本目录（词项经图谱/卡片间接进入检索）。
- 门禁：`tests/test_cet_repair.py`（第 396 行校验 `words_cet4.jsonl`、`phrases_highfreq.jsonl` 等资源计数与字段）、`tests/test_status_vocabulary.py`（要求引用它们的题面状态词表一致；本目录自身记录用 `tier`/`content_review` 而非 answer_status）。

## 文件清单

- `words_cet4.jsonl`（14568290B, 4424L，4424 条）—— 四级大纲词汇。字段 `text`（词 + 音标 + 释义拼成的可读串）、`extra.{word, phonetic, level, tier, pos_meaning, cse_level, content_review}`、`resource_id`（命名 `cet4.w.{word}`）、`cse_alignment.{status=cse_level_pending_official_CET_CSE_linking_evidence, cse_level=null}`、`knowledge_node_ids`/`ability_ids`/`exam_requirement_ids`、`review`。`tier=outline`、`cse_level=null`（大纲未给 CET↔CSE 换算，非缺漏）。
- `words_cet6.jsonl`（17959547B, 5518L，5518 条）—— 六级大纲词汇，结构同上，`resource_id` 前缀 `cet6.`。
- `core_words.jsonl`（8802643B, 3123L，3123 条）—— 核心词层（`tier=core`），`resource_id` 命名 `cet4.core.{word}` 等。旧 README 写"1500 核心词汇"已过时，现算 3123 条。
- `phrases_highfreq.jsonl`（3920789B, 1405L，1405 条）—— 高频词组搭配（`tier=phrase`），字段 `extra.{phrase, variant, meaning, level}`，`resource_id` 命名 `cet{4|6}.phr.{NNN}`（三位补零）。
- `translation_topic_words.jsonl`（56540B, 8L，8 条）—— 翻译主题词分组表，`extra.{theme, terms[{cn,en}]}`（文化/社会等类），`resource_id` 命名 `mix.trans_topic.{NN}`；供翻译题主题词标注参考。
- `md/`（空目录，0 文件）—— 预留人读词表出口，当前无内容；不要在遗留空目录里新建非 README 文件。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- CSE 等级一律 `null` 且标注 `pending_official_CET_CSE_linking_evidence`：官方没有 CET↔CSE 的数值对接证据，词库不擅自换算等级。
- 每条词都是 `content_review.initial_label.status=auto_labeled` + `expert_review.status=pending`：属自动标注，未经教研核定，重跑 build_vocab.py 会覆盖手改。
- 5 个词库计数（4424+5518+3123+1405+8=14478）被 `build_graph.py` 直接写成 L7 词汇节点数；改了词库必须重跑 build_graph 与 expand_knowledge_graph，否则图谱与词库数量不一致。
- `expand_knowledge_graph.py` 产的 `ontology/vocabulary_entities.jsonl` 只有 9942 条（去重/可挂实体的子集），与本目录 14478 词不是同一口径，勿混淆。
