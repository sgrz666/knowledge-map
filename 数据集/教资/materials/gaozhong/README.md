# 数据集/教资/materials/gaozhong/ —— 这里放高中的共享长材料（L5），build_kb+sync_materials 生成，图谱/repository/卡片消费

八层体系 L5_shared_material 在高中的切片：110 个材料 jsonl + 1 份本 README；共 176 行，一行一条材料，逐条过 数据集/教资/schemas/material.json。目录 = 科目（与 ../questions/gaozhong 的部分科目同名），科目下文件与题卷面同名 `<session>.jsonl`。
生成：`kb_tools/build_kb.py` 按卷落盘 → `kb_tools/ntce_repair.sync_materials()` 回填 kind/word_count/used_by_questions/source → `kb_tools/ntce_material_repair.py` 补录 `…material.recovered`。消费：`kb_tools/build_graph.py`（L5 节点）、`services/knowledge/repository.py` 的 `load_material()`（先图谱后磁盘）、`services/web/service.py`（卷面详情）、`../../cards/**` 的 `**材料:**` 块。
改这里必须跑：`python -m pytest tests/test_ntce_hierarchy_contract.py -q`（全库 586 条被 assertEqual 钉死）、`python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`。

13 个学科目录与 ../questions/gaozhong 同名。yingyu 13 个文件里 9 个为 0 行；dili、shengwu、yuwen 各有 0 行卷（材料被复核回退，题面引用同步清掉或改指 recovered 记录）。

## 文件清单（逐个现算，含 0 行文件）

| subject | 材料文件（去 .jsonl；=同名卷面） | 材料条数=行数 | kind 分布 |
|---|---|---|---|
| dili | 2017a | 1 | case_material×1 |
| dili | 2017b | 1 | lesson_plan_material×1 |
| dili | 2018a | 0 | —（0 行） |
| dili | 2018b | 0 | —（0 行） |
| dili | 2019a | 1 | lesson_plan_material×1 |
| dili | 2019b | 1 | lesson_plan_material×1 |
| dili | 2020b | 1 | lesson_plan_material×1 |
| dili | 2021b | 2 | case_material×1、lesson_plan_material×1 |
| dili | 2022a | 1 | lesson_plan_material×1 |
| dili | 2022b | 1 | lesson_plan_material×1 |
| dili | 2023a | 1 | lesson_plan_material×1 |
| **dili 小计** | 11 个文件 | **10**（0 行文件 2 个） |  |
| huaxue | 2015a | 1 | case_material×1 |
| huaxue | 2018b | 2 | case_material×1、lesson_plan_material×1 |
| huaxue | 2019a | 3 | case_material×2、lesson_plan_material×1 |
| **huaxue 小计** | 3 个文件 | **6**（0 行文件 0 个） |  |
| lishi | 2014b | 1 | case_material×1 |
| lishi | 2017a-k2 | 2 | case_material×2 |
| lishi | 2017a | 1 | case_material×1 |
| lishi | 2017b-k2 | 3 | case_material×2、lesson_plan_material×1 |
| lishi | 2018a | 4 | case_material×4 |
| lishi | 2018b | 3 | case_material×3 |
| lishi | 2019a | 3 | case_material×2、lesson_plan_material×1 |
| lishi | 2019b | 4 | case_material×3、lesson_plan_material×1 |
| lishi | 2020b | 2 | case_material×2 |
| lishi | 2023a | 4 | case_material×3、lesson_plan_material×1 |
| **lishi 小计** | 10 个文件 | **27**（0 行文件 0 个） |  |
| meishu | 2019a | 2 | case_material×2 |
| meishu | 2019b | 3 | case_material×2、lesson_plan_material×1 |
| meishu | 2020b | 2 | case_material×2 |
| meishu | 2021a | 2 | case_material×2 |
| meishu | 2021b | 3 | case_material×2、lesson_plan_material×1 |
| meishu | 2022a | 2 | case_material×2 |
| meishu | 2022b | 2 | case_material×2 |
| meishu | 2023b | 2 | case_material×2 |
| **meishu 小计** | 8 个文件 | **18**（0 行文件 0 个） |  |
| shengwu | 2012b-k2 | 1 | lesson_plan_material×1 |
| shengwu | 2013a-k2 | 2 | case_material×1、lesson_plan_material×1 |
| shengwu | 2013b-k2 | 1 | lesson_plan_material×1 |
| shengwu | 2018a | 0 | —（0 行） |
| shengwu | 2018b | 0 | —（0 行） |
| shengwu | 2019a | 3 | case_material×2、lesson_plan_material×1 |
| shengwu | 2019b | 3 | case_material×2、lesson_plan_material×1 |
| shengwu | 2020b | 3 | case_material×2、lesson_plan_material×1 |
| shengwu | 2022b | 2 | case_material×2 |
| shengwu | 2023a | 3 | case_material×2、lesson_plan_material×1 |
| **shengwu 小计** | 10 个文件 | **18**（0 行文件 2 个） |  |
| shuxue | 2019a | 1 | lesson_plan_material×1 |
| shuxue | 2021a | 1 | case_material×1 |
| shuxue | 2021b | 2 | case_material×1、lesson_plan_material×1 |
| shuxue | 2022a | 1 | case_material×1 |
| shuxue | 2022b | 1 | lesson_plan_material×1 |
| shuxue | 2023a | 2 | case_material×1、lesson_plan_material×1 |
| shuxue | 2023b | 2 | case_material×1、lesson_plan_material×1 |
| **shuxue 小计** | 7 个文件 | **10**（0 行文件 0 个） |  |
| tiyu | 2017a | 2 | case_material×2 |
| tiyu | 2018a | 1 | case_material×1 |
| tiyu | 2018b | 2 | case_material×2 |
| tiyu | 2019a | 3 | case_material×2、lesson_plan_material×1 |
| tiyu | 2019b | 3 | case_material×2、lesson_plan_material×1 |
| tiyu | 2021a | 2 | case_material×2 |
| tiyu | 2022a | 3 | case_material×2、lesson_plan_material×1 |
| tiyu | 2023a | 1 | case_material×1 |
| **tiyu 小计** | 8 个文件 | **17**（0 行文件 0 个） |  |
| wuli | 2015a-k2 | 1 | case_material×1 |
| wuli | 2015a | 1 | case_material×1 |
| wuli | 2015b-k2 | 1 | case_material×1 |
| wuli | 2015b | 1 | case_material×1 |
| wuli | 2017a-k2 | 1 | case_material×1 |
| wuli | 2017a | 1 | case_material×1 |
| wuli | 2017b-jx | 1 | lesson_plan_material×1 |
| wuli | 2017b | 1 | case_material×1 |
| wuli | 2018a | 1 | case_material×1 |
| wuli | 2022b | 1 | lesson_plan_material×1 |
| **wuli 小计** | 10 个文件 | **10**（0 行文件 0 个） |  |
| xinxi | 2017a-k2 | 1 | case_material×1 |
| xinxi | 2018b | 3 | case_material×2、lesson_plan_material×1 |
| xinxi | 2020b | 3 | case_material×2、lesson_plan_material×1 |
| xinxi | 2021a | 3 | case_material×2、lesson_plan_material×1 |
| xinxi | 2021b | 3 | case_material×2、lesson_plan_material×1 |
| **xinxi 小计** | 5 个文件 | **13**（0 行文件 0 个） |  |
| yingyu | 2013a | 1 | lesson_plan_material×1 |
| yingyu | 2013b-jx | 0 | —（0 行） |
| yingyu | 2014a | 1 | case_material×1 |
| yingyu | 2016b-k2 | 0 | —（0 行） |
| yingyu | 2019a-jx | 0 | —（0 行） |
| yingyu | 2019b-jx-k2 | 0 | —（0 行） |
| yingyu | 2019b-jx | 0 | —（0 行） |
| yingyu | 2020b | 1 | lesson_plan_material×1 |
| yingyu | 2021a | 0 | —（0 行） |
| yingyu | 2021b | 0 | —（0 行） |
| yingyu | 2022b | 0 | —（0 行） |
| yingyu | 2023a | 0 | —（0 行） |
| yingyu | 2023b | 1 | case_material×1 |
| **yingyu 小计** | 13 个文件 | **4**（0 行文件 9 个） |  |
| yinyue | 2019b | 1 | case_material×1 |
| yinyue | 2021a | 1 | case_material×1 |
| yinyue | 2021b | 1 | lesson_plan_material×1 |
| yinyue | 2023a | 1 | lesson_plan_material×1 |
| yinyue | 2023b | 2 | case_material×1、lesson_plan_material×1 |
| **yinyue 小计** | 5 个文件 | **6**（0 行文件 0 个） |  |
| yuwen | 2015a | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2015b | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2016a | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2016b | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2017a | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2017b | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2020b | 0 | —（0 行） |
| yuwen | 2021b | 0 | —（0 行） |
| yuwen | 2023b | 0 | —（0 行） |
| **yuwen 小计** | 9 个文件 | **16**（0 行文件 3 个） |  |
| zhengzhi | 2014a-jx | 1 | case_material×1 |
| zhengzhi | 2015a-jx | 1 | case_material×1 |
| zhengzhi | 2017b-k2 | 3 | case_material×2、lesson_plan_material×1 |
| zhengzhi | 2018b | 1 | case_material×1 |
| zhengzhi | 2019a | 2 | case_material×2 |
| zhengzhi | 2019b | 2 | case_material×1、lesson_plan_material×1 |
| zhengzhi | 2021b | 2 | case_material×1、lesson_plan_material×1 |
| zhengzhi | 2022a | 3 | case_material×2、lesson_plan_material×1 |
| zhengzhi | 2022b | 3 | case_material×2、lesson_plan_material×1 |
| zhengzhi | 2023a | 2 | case_material×1、lesson_plan_material×1 |
| zhengzhi | 2023b | 1 | lesson_plan_material×1 |
| **zhengzhi 小计** | 11 个文件 | **21**（0 行文件 0 个） |  |

## 每行内容与状态语义

- `material_id` 形状：`ntce.gaozhong.<subject>.<session>.m<NN>`（卷内顺序编号）或 `<question_id>.material.recovered`（原文区间补录，`review.extraction_status=source_interval_recovered_pending_expert`）。
- `kind` 三枚举中本目录实测值见上表（case=案例分析类材料，lesson_plan=教学设计题所用的教材/教案片段；interview_material 全库当前 0 条）。
- `used_by_questions`/`question_ids`：由题目行 `material_id` 反向重算，非人工填写；每条材料当前恰好 1 道引用题。引用断了不会静默——图谱 refers_to_material 边与 validate_kb 外键检查都以这两个字段对账。
- 0 行文件：该卷材料经 `ntce_material_repair.py` 复核后未存活（自动关联回退/原文未达边界规则），题目行对应 `material_id` 已置 null，文件保留以维持与卷面的同名对应。
