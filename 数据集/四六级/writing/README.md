# 数据集/四六级/writing/ —— 短文写作范文库（146 篇 + 69 模板句型 + 126 卷级题干中间件），build_writing_translation/build_templates.py 生成，图谱 L7 与量规消费

- 角色：四六级作文真题题干、高分范文与模板句型；范文是主观题参考，非客观答案，每题挂整体印象五档量规。
- 生成：`scripts/build_writing_translation.py`（合并各源产出 `model_essays.jsonl`）、`scripts/build_templates.py`（模板 docx/PDF → `templates.jsonl` 并同步写 `md/templates.md`）、`scripts/build_questions.py`（初次写 `writing/_prompts.jsonl` 逐卷题干抽取，供前者合并）。重跑覆盖，不手改 JSONL。
- 消费：`scripts/build_graph.py`（L7 资源节点：范文 146、模板 69）、`scripts/generate_paper_specs.py`/`repository.py`（写作时长按 `task_constraints.time_limit_minutes=30`）、`审查/validate_kb.py`；判分口径经 `ontology/scoring_rubrics.jsonl` 的 `cet.writing.holistic.2016`（trust.py 对 `official_scoring` 挂提示语）。
- 门禁：`tests/test_cet_repair.py`（第 346/396 行校验 `model_essays.jsonl` 题干与范文成对、`templates.jsonl` 资源计数）。

## 文件清单

- `model_essays.jsonl`（3346473B, 146L，146 条 = CET-4 73 + CET-6 73）—— 每行一道写作题+范文。字段 `resource_id`、`exam`/`year`/`paper`/`module`、`task_id`/`task_type`、`task_status`（恒 `reference_available_pending_expert_review`）、`content.prompt`（ Directions/题干）、`content.reference_answer`（高分范文全文）、`rubric_id`=`cet.writing.holistic.2016`（15 分五档量规）、`task_constraints.time_limit_minutes=30`、`difficulty=null`（全部 146 无实测校准）、`review.status`=`auto_parsed`、`knowledge_node_ids`/`ability_ids`/`exam_requirement_ids`。由 build_writing_translation.py 重生成。
- `templates.jsonl`（376508B, 69L，69 条）—— 写作模板句型。字段 `extra.{category, function, en, cn, usage}`（如 `category=quote`、`function=名言警句类破题句`）、`resource_id`、`text`（句型串）、`review`、`knowledge_node_ids`/`ability_ids`/`exam_requirement_ids`。由 build_templates.py 重生成，命名与 `md/templates.md` 同源。
- `_prompts.jsonl`（126097B, 126L，126 条）—— 逐卷写作题干抽取中间件，字段 `id`/`exam`/`paper`/`year`/`topic_prompt`/`text`/`review`/`source`。是 build_writing_translation.py 合并 `model_essays.jsonl` 前的原料（126 卷口径），由 build_questions.py 写；不直接判分。
- `md/`—— 人读版模板（`templates.md`），见 `md/README.md`。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- 范文没有客观答案：判分走 15 分整体印象五档（14/11/8/5/2）×权重，`content.reference_answer` 只是参考，`task_status` 停在 pending_expert_review 前不得当标准范文对学员公布。
- `difficulty` 全 null、无作答样本，不得据此跑 IRT 或按难度组卷。
- 模板的 `cn`/`usage` 常为 null（源只有英文句型），别当成缺漏去手补——要补就改 build_templates.py 的源解析。
- `_prompts.jsonl` 改了不会自动同步 `model_essays.jsonl`，须重跑 build_writing_translation.py；`md/templates.md` 是 build_templates.py 一并写出的产物，别单独手改（会被覆盖）。
