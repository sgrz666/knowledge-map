# 数据集/教资/schemas —— 全库唯一的 JSON Schema 目录，两库共用

11 份 Draft 2020-12 Schema（现算，字节数见下表）。四六级不设副本：`tests/test_cet_eight_layer_contract.py:11` 直接把本目录 `schemas/` glob 进来校验 CET 题记录，`tests/test_status_vocabulary.py:15` 也是加载 `数据集/教资/schemas/question.json` 校两库。写这个目录的是人（附录 A 的形状定在这里），读它的全是校验器与 LLM 出参护栏——没有任何运行时把 Schema 当数据源。

## 文件清单

| 文件 | 字节 | `title` | `$id` | required | 谁校验它 |
|---|---|---|---|---|---|
| `question.json` | 8,200 | ExamQuestion | urn:knowledge-map:ntce-question:3.0 | 12：`question_id,exam,school_level,module,subject,question_type,content,knowledge_node_ids,ability_ids,exam_requirement_ids,source,review` | `tests/test_ntce_hierarchy_contract.py:113`（逐题）、`tests/test_cet_eight_layer_contract.py:68`（CET 逐题）、`tests/test_status_vocabulary.py:15`（两库状态字段） |
| `material.json` | 1,675 | SharedMaterialOrPassage | …shared-material:1.0 | 4：`material_id,kind,text,source` | `test_ntce_hierarchy_contract.py:90`（并核 `materials/*/*/*.jsonl` 全量） |
| `knowledge_node.json` | 1,828 | KnowledgeNode | …knowledge-node:1.0 | 4：`node_id,name,module,assessable` | 附录 A 名单内，`test_ntce_hierarchy_contract.py:77-86` 断言存在且 `check_schema` 通过 |
| `ability_node.json` | 1,023 | AbilityDimension | …ability-dimension:1.0 | 3：`ability_id,name,exam` | 同上（只在名单里被断言存在，没有逐条数据校验） |
| `requirement.json` | 1,368 | AuthoritativeRequirement | …authoritative-requirement:1.0 | 4：`requirement_id,standard_id,content,locator` | 同上；`locator` 在 Schema 里只要求是 object（键名 `text_path`+行号 / `table_path`+单元格 / `json_pointer` 写在 description 里，不是 Schema 强制），区间实际有没有落在原文由 `审查/validate_kb.py` 的来源/区间哈希规则核 |
| `rubric.json` | 4,234 | ScoringRubric | …scoring-rubric:2.0 | 8：`rubric_id,task_type,total_score,rubric_type,official_scoring,dimensions,expert_verified,review` | `test_ntce_hierarchy_contract.py:102`、`tests/test_rubric_contract.py:23`（glob 全目录） |
| `practice_framework.json` | 2,403 | PracticeRubricFramework | …practice-framework:1.0 | 7：`rubric_id,status,official_scoring,expert_verified,dimensions,question_specific_points,exam_requirement_ids` | `tests/test_rubric_contract.py`、`审查/build_review_queue.py`（量规底数一节） |
| `user_mastery.json` | 1,127 | UserKnowledgeMastery | …user-mastery:1.0 | 4：`user_id,node_id,mastery_score,last_updated_at` | `tests/test_services_memory.py:22` 直接按路径读它校验 `services/memory/store.py` 写出的画像记录；`services/common/models.py:232` 声明 conform |
| `card_frontmatter.json` | 1,595 | CardFrontmatter | …card-frontmatter:1.0 | 12：`id,exam,level,subject,session,section,question_type,knowledge_nodes,ability_ids,exam_requirement_ids,answer_status,review_status` | `tests/test_gap_remediation.py:55`（逐张卡片头部）、`审查/validate_kb.py` |
| `paper_spec.json` | 1,253 | NTCEPaperSpecification | 无 `$id` | 11：`spec_id,exam,school_level,subject,title,sections,total_duration_minutes,total_raw_score,report_score_max,passing_report_score,score_conversion`；`sections[]` 每项再 required 5：`name,count,score_each,total_score,question_type`；`exam` 是 `const: "NTCE"` | `tests/test_web_workbench.py:141`（拿它校 `数据集/教资/paper_specs.jsonl` 32 行）、`审查/build_review_queue.py`（§6 规格内部一致性） |
| `tutor_reply.json` | 383 | GroundedTutorReply | 无 `$id` | 2：`reply,citation_ids`；`additionalProperties: false`、`reply` ≤16,000 字符、`citation_ids` ≤20 且 `uniqueItems` | `services/web/provider.py:75` 以 `schema_name='tutor_reply'` 请求，经 `services/llm/guardrails.py` 校验 LLM 出参 |

## 两套量规 Schema 的分工（别混写）

权重的唯一真相只在 `rubric.json` 一侧：维度字段是 `dimension_name`/`weight_score`/`criteria_levels`，权重之和必须等于 `total_score`，`expert_verified: true` 必须有 `review.checked_by`。题内评价框架走 `practice_framework.json`，只有 `name`/`levels`/`max_level`，**没有分值权重**，能出反馈不能出分；同一维度同时带两套字段即双真相，`审查/validate_kb.py` 记 `Q_RUBRIC_DUAL_TRUTH` 结构性错误，选择题携带量规则由 `Q_RUBRIC_ON_OBJECTIVE` 拒绝。校验入口：`python -m pytest tests/test_rubric_contract.py -q`。

## 运行时怎么找到这些文件

`services/llm/guardrails.py:37` 的 `SCHEMA_GLOBS = ("数据集/*/schemas/*.json",)` —— 当前只有本目录命中（四六级没有 `schemas/`）。`SchemaRegistry.paths`（`:149-160`）按 `path.stem → path` 建表、`sorted(glob)` 后 `setdefault`，所以**文件名（去 `.json`）就是 `schema_name=` 的取值**；查不到就抛 `SchemaNotFound` 并附 `available()` 清单，注释写明「未定义的 Schema 一律 fail closed，不放行」。新增一份 Schema 等于新增一个可被 `client.generate(..., schema_name='…')` 请求的形状，不需要注册代码。

## 改这里之前要知道的

- `test_ntce_hierarchy_contract.py:77-80` 只断言 9 个附录 A 名字存在并 `check_schema`；`paper_spec`、`tutor_reply` 不在该名单里，它们各自被上面表格「谁校验它」那一列的具体测试覆盖。往本目录加第 12 份文件不会自动进那个名单。
- Schema 收紧会让历史数据报错，不是让数据变干净：`question.json` 现在是 3.0，改 required 或删可选字段前，先跑 `python -m pytest tests/test_ntce_hierarchy_contract.py tests/test_cet_eight_layer_contract.py tests/test_status_vocabulary.py -q`，再用 `python 审查/validate_kb.py` 看结构错误计数相对现基线（`structure_errors = 0`）有没有新增。
- 状态枚举不许在这里自造：`review_status`/`answer_status` 的词表口径由 `审查/状态词表检查.py` 与 `tests/test_status_vocabulary.py` 钉住（六态复核、五态答案），Schema 里若写枚举必须与之逐字一致。
- 本目录 11 份文件都被 `kb_tools/ntce_verify.py:13` 的 `('schemas','*.json')` glob 进快照哈希，参与双次复跑幂等判定（`--idempotence`）。
