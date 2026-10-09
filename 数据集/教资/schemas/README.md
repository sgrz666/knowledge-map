# 教资/schemas — Draft 2020-12 标准 JSON Schema

本目录是全库**唯一**的 Schema 目录（规范 附录 A）。四六级不设副本，由 `tests/test_cet_eight_layer_contract.py`
与 `tests/test_status_vocabulary.py` 直接加载本目录校验两库记录，避免两套 Schema 各自漂移。

## Schema 文件清单（9 份）
- **question.json**：试题实体（`$id` 为 `urn:knowledge-map:ntce-question:3.0`，两库共用）。
- **material.json**：共享长材料。
- **knowledge_node.json**：L4 知识点节点。
- **ability_node.json**：L3 能力维度节点。
- **requirement.json**：L0 考纲条款。
- **rubric.json**：**附录 A.6 可计算加权量规实体**（`rubrics/*.json` 用）。维度只认
  `dimension_name`/`weight_score`/`criteria_levels`，权重之和必须等于 `total_score`；
  `expert_verified: true` 必须有 `review.checked_by`。
- **practice_framework.json**：**题内练习评价框架**（`q['rubric']` 用）。只有 `name`/`levels`/`max_level`，
  **没有分值权重**，只能出反馈不能出分；出现 `weight_score`/`criteria_levels` 即不符合本 Schema。
- **user_mastery.json**：L7 之外的用户掌握度与 FSRS 状态（应用层运行时数据形状）。
- **card_frontmatter.json**：Markdown 卡片头部元数据（状态字段镜像题记录，不得自造枚举）。

> 两套量规 Schema 的分工是刻意的：权重的唯一真相只在 `rubric.json` 一侧。同一维度同时带两套字段就是双真相，
> `审查/validate_kb.py` 会以 `Q_RUBRIC_DUAL_TRUTH` 记结构性错误；选择题携带量规则由 `Q_RUBRIC_ON_OBJECTIVE` 拒绝。
> 校验入口：`python -m pytest tests/test_rubric_contract.py -q`。
