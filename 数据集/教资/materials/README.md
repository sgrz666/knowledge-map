# 数据集/教资/materials/ —— 这里放共享长材料（L5），build_kb+sync_materials 生成，图谱/repository/卡片消费

八层体系里这里是 **L5_shared_material**：材料分析/教学设计/案例题引用的长材料正文。一份材料存一次，题目用 `material_id` 指过来。
生成：`kb_tools/build_kb.py` 首次入库时按卷写同名 `<session>.jsonl`（该卷解析出材料才建文件）；`kb_tools/ntce_repair.sync_materials()` 每次复算回填 `kind/word_count/used_by_questions/source`；`kb_tools/ntce_material_repair.py` 从原始 CSV 的题干前区间补录 `<question_id>.material.recovered` 型材料。
消费：`kb_tools/build_graph.py` 把每条材料写成 graph/nodes.jsonl 里 layer=L5、type=material 的节点（并连 refers_to_material 边）；运行时 `services/knowledge/repository.py` 的 `load_material()` 先查图谱节点 text、再回磁盘 rglob 本目录；`services/web/service.py` 出卷详情时附材料正文；`../cards/**` 卡片正文的 `**材料:**` 块。
改这里必须跑：`python -m pytest tests/test_ntce_hierarchy_contract.py -q`——其中 `test_materials_fully_conform_to_schema` 把全库材料数钉死为 `assertEqual(586, len(materials))`，增删材料必须同步改该断言并复跑全闸；外加 `python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`。

## 数量与分布（现算）

本目录共 330 个文件 = 324 个 `*.jsonl` + 6 个 `README.md`（本文件 + 5 份学段 README）。324 个 jsonl 共 586 行，一行一条材料 JSON，逐条过 数据集/教资/schemas/material.json（required: material_id/kind/text/source；NTCE 侧 kind 三枚举里实测只有两值出现）。`kind` 实测：case_material 462、lesson_plan_material 124、interview_material 0 条（schema 允许但当前无数据）。36 个 jsonl 为 0 行（材料经边界复核未存活，见各学段 README 的逐文件表）。

| level | 科目目录数 | 材料 jsonl 数 | 材料条数(行) | 其中 0 行文件 |
|---|---|---|---|---|
| youer | 2 | 39 | 84 | 0 |
| xiaoxue | 2 | 30 | 70 | 0 |
| chuzhong | 13 | 107 | 177 | 19 |
| gaozhong | 13 | 110 | 176 | 16 |
| zhongxue | 2 | 38 | 79 | 1 |
| **合计** | **32** | **324** | **586** | **36** |

命名规律：材料文件与题卷面**同名**（`<session>.jsonl`，含 `-jx/-kN` 等后缀；每个材料文件在 ../questions 下都有同名卷面，0 例外），但只覆盖有共享材料的卷——622 份卷面里 324 份有材料文件。`material_id` 两种形状：`ntce.<level>.<subject>.<session>.m<NN>`（入库时按卷内顺序编号，build_kb.py:656）与 `<完整question_id>.material.recovered`（ntce_material_repair.py 补录）；全 586 条前缀均为 ntce（省考卷无材料）。引用关系是可反向核对的：586 条材料的 `used_by_questions` 合计恰为 586 个引用——当前每条材料恰好被 1 道题引用，且与题目行的 `material_id` 一一互指。

## 每条材料行的字段

`material_id` / `text`（正文全文）/ `kind`（由引用题题型决定：教学设计、活动设计→lesson_plan_material，面试类→interview_material，其余→case_material，ntce_repair.py:562-568）/ `word_count`（=len(text)，契约测试断言 >0）/ `used_by_questions` 与 `question_ids`（同值，sync_materials 由题目反向重算）/ `level`、`subject` / `knowledge_node_ids`、`ability_ids`、`exam_requirement_ids`（并集取自引用题）/ `source`（origin_file、files、copyright，默认 research_non_commercial）/ `review`（content_verified=false、status=auto_parsed、extraction_status 记录抽料来源待人工核对）。0 行文件不产生物料记录，因此不存在 word_count=0 的材料。
