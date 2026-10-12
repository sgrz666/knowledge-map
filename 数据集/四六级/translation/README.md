# 数据集/四六级/translation/ —— 段落汉译英真题库（146 条 items + 126 条卷级中间件），build_writing_translation.py 生成，图谱 L7 与判分量规消费

- 角色：四级/六级段落翻译的题干、参考译文与中国传统文化主题词标注；每题绑定整体印象量规，不含客观答案。
- 生成：`scripts/build_writing_translation.py`（把 `manifest/` 与 `_from_papers.jsonl` 的抽取合并、标准化成 `items.jsonl`）；`_from_papers.jsonl` 由 `scripts/build_questions.py` 初次写（逐卷中间抽取）。重跑覆盖，不手改。
- 消费：`scripts/build_graph.py`（L7 翻译项节点 146）、`scripts/generate_cards.py` 无关（翻译不进卡片：卡片只含客观题）、`审查/validate_kb.py`；判分口径经 `ontology/scoring_rubrics.jsonl` 的 `cet.translation.holistic.2016`。
- 门禁：`tests/test_cet_repair.py`（校验 `items.jsonl` 的题干与参考译文成对存在、task_status 正确）。

## 文件清单

- `items.jsonl`（2920333B, 146L，146 条 = CET-4 73 + CET-6 73）—— 每行一道翻译题。关键字段：`resource_id`、`exam`/`year`/`paper`/`module`、`task_id`/`task_type`、`task_status`（恒为 `reference_available_pending_expert_review`：有参考译文但未过专家审核，非 verified）、`content.prompt`（中文原段 + 词数说明）、`content.reference_answer`（官方/整理参考译文）、`annotations`（`themes` 中国文化主题词 + `syntax_features` 长难句特征）、`rubric_id`=`cet.translation.holistic.2016`（指向 `ontology/scoring_rubrics.jsonl` 五档 15 分量规）、`task_constraints`（`time_limit_minutes=30`、`source_language=zh`/`response_language=en`、`constraints_status=official_general_rule`）、`difficulty=null`（全部 146 条无实测校准）、`review.status`=`auto_parsed`、`knowledge_node_ids`/`ability_ids`/`exam_requirement_ids`。由 build_writing_translation.py 重生成，不手改。
- `_from_papers.jsonl`（284399B, 126L，126 条）—— 逐卷翻译抽取中间件，字段 `id`/`exam`/`paper`/`year`/`source_text`（中文原段）/`reference`（参考译文）/`key_phrases`/`theme`/`notes`/`review`/`source`/`text`。是 build_writing_translation.py 合并 items.jsonl 前的原料，不是最终判分依据；由 build_questions.py 写。可被脚本重生成，一般不手改。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- 翻译题没有客观答案：判分走 15 分整体印象五档量规（14/11/8/5/2），`content.reference_answer` 只是参考，`task_status` 停在 pending_expert_review 前不得当标准答案对学员公布。
- `difficulty` 全为 null、无作答样本，不得据此跑 IRT 或难度排序组卷。
- `_from_papers.jsonl` 是历史中间件（126 卷口径），改了它不会自动改 `items.jsonl`，须重跑 build_writing_translation.py。
