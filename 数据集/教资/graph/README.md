# 数据集/教资/graph — 八层知识图谱拓扑数据

本目录存储教资全库构建后的图数据库导入格式（22,104 节点，96,774 条关系边；由 `kb_tools/build_graph.py` 从题目、材料、量规与 `权威资料/` 全量重导，可整目录删除后重建）。

## 核心文件

- **nodes.jsonl**：图节点实体集合，`layer` 只使用规范 §3.2 的 L0–L7 一套编号（L0 标准与条款 2,320、L1 考试 7、L2 模块 38、L3 素养与能力 51、L4 知识点 791、L5 材料 586、L6 试题与量规 18,303、L7 资源 8）。
- **edges.jsonl**：图关系边集合，边名限定在规范 §3.4 的 16 个词表内（`assesses`、`supports_ability`、`aligned_to_requirement`、`prerequisite_of`、`refers_to_material`、`has_rubric`、`specifies`、`contains`、`has_child`、`comprises`、`targets`、`basis`、`supports_resource`、`supplements_resource`、`confused_with`、`misconception_lead_to`），方向一律是"支撑方 → 被支撑方"。
- **edges_curated.jsonl**：可版本化的策展源边（当前是先修候选 13 条，含概念依据原文）；导出时并入 `edges.jsonl`，未经教研核定不进入学习路径。

## 消费约束

- L0 条款节点全部 `verified = false`：条款已全量入图，但"条款 → 知识点/题目"的映射仍需教研逐项判定，图谱只保证可查，不保证已核对。
- 先修边一律 `proposed_pending_review` + `active_for_learning_path = false`，具名审核人为 0。
- L6 的 3,803 个 `rubric` 节点分三类：3,736 个题内练习框架（`rubric.<question_id>`，有 `has_rubric` 边，**无分值权重故不可自动出分**）、6 个 `rubrics/*.json` 加权量规实体（`review_status = needs_fix`、`reviewed_by = null`、`expert_verified = false`，暂无题目绑定）、61 个官方面试细则参照节点（`official = true`、`review_status = question_task_mapping_pending_review`）。选择题没有 `has_rubric` 边。
- 状态字段与题记录同表（`review.status` 六态、`content.answer_status` 五态），由 `tests/test_graph_direction_contract.py` 与 `tests/test_status_vocabulary.py` 钉住。
