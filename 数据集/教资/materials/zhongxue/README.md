# 数据集/教资/materials/zhongxue/ —— 这里放中学（初高中共用公共科目）的共享长材料（L5），build_kb+sync_materials 生成，图谱/repository/卡片消费

八层体系 L5_shared_material 在中学（初高中共用公共科目）的切片：38 个材料 jsonl + 1 份本 README；共 79 行，一行一条材料，逐条过 数据集/教资/schemas/material.json。目录 = 科目（与 ../questions/zhongxue 的部分科目同名），科目下文件与题卷面同名 `<session>.jsonl`。
生成：`kb_tools/build_kb.py` 按卷落盘 → `kb_tools/ntce_repair.sync_materials()` 回填 kind/word_count/used_by_questions/source → `kb_tools/ntce_material_repair.py` 补录 `…material.recovered`。消费：`kb_tools/build_graph.py`（L5 节点）、`services/knowledge/repository.py` 的 `load_material()`（先图谱后磁盘）、`services/web/service.py`（卷面详情）、`../../cards/**` 的 `**材料:**` 块。
改这里必须跑：`python -m pytest tests/test_ntce_hierarchy_contract.py -q`（全库 586 条被 assertEqual 钉死）、`python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`。

只有 jiaoyuzhishi、zonghe 两个目录；省考目录无材料文件。zonghe 20 个文件中 2020b 为 0 行。

## 文件清单（逐个现算，含 0 行文件）

| subject | 材料文件（去 .jsonl；=同名卷面） | 材料条数=行数 | kind 分布 |
|---|---|---|---|
| jiaoyuzhishi | 2011b | 1 | case_material×1 |
| jiaoyuzhishi | 2012a | 2 | case_material×2 |
| jiaoyuzhishi | 2012b | 2 | case_material×2 |
| jiaoyuzhishi | 2013a | 2 | case_material×2 |
| jiaoyuzhishi | 2013b | 2 | case_material×2 |
| jiaoyuzhishi | 2014b | 1 | case_material×1 |
| jiaoyuzhishi | 2015b | 1 | case_material×1 |
| jiaoyuzhishi | 2017a | 1 | case_material×1 |
| jiaoyuzhishi | 2018b | 1 | case_material×1 |
| jiaoyuzhishi | 2019a | 2 | case_material×2 |
| jiaoyuzhishi | 2019b | 2 | case_material×2 |
| jiaoyuzhishi | 2020b | 2 | case_material×2 |
| jiaoyuzhishi | 2021a | 2 | case_material×2 |
| jiaoyuzhishi | 2021b | 2 | case_material×2 |
| jiaoyuzhishi | 2022a | 2 | case_material×2 |
| jiaoyuzhishi | 2022b | 1 | case_material×1 |
| jiaoyuzhishi | 2023a | 2 | case_material×2 |
| jiaoyuzhishi | 2023b | 2 | case_material×2 |
| **jiaoyuzhishi 小计** | 18 个文件 | **30**（0 行文件 0 个） |  |
| zonghe | 2012a | 4 | case_material×4 |
| zonghe | 2012b | 3 | case_material×3 |
| zonghe | 2013a | 4 | case_material×4 |
| zonghe | 2013b | 2 | case_material×2 |
| zonghe | 2014a | 1 | case_material×1 |
| zonghe | 2014b | 1 | case_material×1 |
| zonghe | 2015a | 1 | case_material×1 |
| zonghe | 2015b | 1 | case_material×1 |
| zonghe | 2016a | 1 | case_material×1 |
| zonghe | 2016b | 1 | case_material×1 |
| zonghe | 2017b | 1 | case_material×1 |
| zonghe | 2018a | 1 | case_material×1 |
| zonghe | 2019a | 4 | case_material×4 |
| zonghe | 2019b | 4 | case_material×4 |
| zonghe | 2020b | 0 | —（0 行） |
| zonghe | 2021a | 4 | case_material×4 |
| zonghe | 2021b | 4 | case_material×4 |
| zonghe | 2022a | 4 | case_material×4 |
| zonghe | 2023a | 4 | case_material×4 |
| zonghe | 2023b | 4 | case_material×4 |
| **zonghe 小计** | 20 个文件 | **49**（0 行文件 1 个） |  |

## 每行内容与状态语义

- `material_id` 形状：`ntce.zhongxue.<subject>.<session>.m<NN>`（卷内顺序编号）或 `<question_id>.material.recovered`（原文区间补录，`review.extraction_status=source_interval_recovered_pending_expert`）。
- `kind` 三枚举中本目录实测值见上表（case=案例分析类材料，lesson_plan=教学设计题所用的教材/教案片段；interview_material 全库当前 0 条）。
- `used_by_questions`/`question_ids`：由题目行 `material_id` 反向重算，非人工填写；每条材料当前恰好 1 道引用题。引用断了不会静默——图谱 refers_to_material 边与 validate_kb 外键检查都以这两个字段对账。
- 0 行文件：该卷材料经 `ntce_material_repair.py` 复核后未存活（自动关联回退/原文未达边界规则），题目行对应 `material_id` 已置 null，文件保留以维持与卷面的同名对应。
