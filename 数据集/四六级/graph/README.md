# 数据集/四六级/graph/ —— 四六级知识图谱导出（25659 节点 / 86688 边 JSONL + 统计快照），build_graph.py 生成，repository.py 与 graph_index.py 消费，八层与方向契约测试门禁

- 角色：把题库、本体、语篇、资源挂成八层（L0–L7）图谱的导出目录；单一生成器是 `scripts/build_graph.py`（依据《应试考证功能设计与技术支撑》§3.2 八层分级 + §3.4 边契约），数据变化后重跑覆盖，不手改。
- 消费：`services/knowledge/repository.py`（`GRAPH_FILES['cet']`）与 `services/knowledge/graph_index.py`（NetworkX 视图；边名走运行时契约）。
- 门禁：`tests/test_cet_eight_layer_contract.py`（八层必须齐全、题目节点与逐题字段一致、先修未核定不得进学习路径）、`tests/test_graph_direction_contract.py`（`assesses`/`supports_ability`/`aligned_to_requirement` 一律"支撑方 → 被支撑方"，即知识点/能力/条款 → 题目，与教资同向）、`审查/validate_kb.py`（standard_id 与 requirements 引用校验）。

## 文件清单

- `nodes.jsonl`（7190524B, 25659L）—— 节点，字段 `id/layer/type/name/exam/verified/...`；层分布（现算，与 graph_stats 一致）：L0 4001（standard 6 + exam_requirement 3995）、L1 2（exam）、L2 8（module）、L3 30（ability 28 + literacy 2）、L4 48（knowledge_node）、L5 449（material=共享语篇）、L6 5634（question 5632 + rubric 2）、L7 15487（resource：词汇 14478 + 模板 69 + 范文 146 + 翻译项 146 + 听力稿 648）。自动映射与条款引用一律 `verified=false`。
- `edges.jsonl`（10478211B, 86688L）—— 边，字段 `src/dst/type(+verified/mapping_status 或 active_for_learning_path 等)`；边类型分布（现算）：supplements_resource 18703、supports_resource 18557、aligned_to_requirement 14706、assesses 11741、contains 5650、supports_ability 9548、specifies 3995、refers_to_material 3358、prerequisite_of 56、has_child 38、comprises 28、has_rubric 292、confused_with 10、misconception_lead_to 4、targets 2。共 15 种边名，全部落在 `services/knowledge/graph_index.py` 的 16 词封闭白名单内（与教资共用同一个 `ALLOWED_EDGE_TYPES` 常量、同一口径；四六级未用到 `basis`）；白名单增名属数据契约变更，需教研评审。
- `graph_stats.json`（1106B, 50L 现算）—— build_graph.py 写出的快照：nodes/edges 总数、by_layer/by_type/by_edge_type、`prerequisite_verified: 0 / prerequisite_pending: 56`、note（自动映射一律 verified=false，无审核人的先修自评已降为候选）。

口径：`prerequisite_of` 56 条在导出侧全部 `active_for_learning_path=false`（候选先修，源数据里记为 `rel=prerequisite_candidate`/`proposed_rel=prereq_of`），学习路径只能用专家核定并激活的正式边；`confused_with`/`misconception_lead_to` 同理未经核定只作线索。图谱消费端遇到白名单外边名会抛 `UnknownEdgeTypeError`（fail-closed）。
