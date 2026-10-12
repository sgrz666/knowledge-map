# 数据集/教资/materials/chuzhong/ —— 这里放初中的共享长材料（L5），build_kb+sync_materials 生成，图谱/repository/卡片消费

八层体系 L5_shared_material 在初中的切片：107 个材料 jsonl + 1 份本 README；共 177 行，一行一条材料，逐条过 数据集/教资/schemas/material.json。目录 = 科目（与 ../questions/chuzhong 的部分科目同名），科目下文件与题卷面同名 `<session>.jsonl`。
生成：`kb_tools/build_kb.py` 按卷落盘 → `kb_tools/ntce_repair.sync_materials()` 回填 kind/word_count/used_by_questions/source → `kb_tools/ntce_material_repair.py` 补录 `…material.recovered`。消费：`kb_tools/build_graph.py`（L5 节点）、`services/knowledge/repository.py` 的 `load_material()`（先图谱后磁盘）、`services/web/service.py`（卷面详情）、`../../cards/**` 的 `**材料:**` 块。
改这里必须跑：`python -m pytest tests/test_ntce_hierarchy_contract.py -q`（全库 586 条被 assertEqual 钉死）、`python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`。

13 个学科目录与 ../questions/chuzhong 同名同 13 个。注意 yingyu：9 个文件里 8 个为 0 行——英语阅读语篇在材料边界复核中未达规则，目前只剩 2020b 一条材料。

## 文件清单（逐个现算，含 0 行文件）

| subject | 材料文件（去 .jsonl；=同名卷面） | 材料条数=行数 | kind 分布 |
|---|---|---|---|
| dili | 2015a | 1 | case_material×1 |
| dili | 2017a-k2 | 0 | —（0 行） |
| dili | 2017b | 4 | case_material×3、lesson_plan_material×1 |
| dili | 2018b | 3 | case_material×2、lesson_plan_material×1 |
| dili | 2019a-jx | 0 | —（0 行） |
| dili | 2020b | 4 | case_material×3、lesson_plan_material×1 |
| dili | 2021b | 1 | case_material×1 |
| dili | 2022a | 1 | case_material×1 |
| dili | 2023a | 4 | case_material×3、lesson_plan_material×1 |
| **dili 小计** | 9 个文件 | **18**（0 行文件 2 个） |  |
| huaxue | 2018a | 3 | case_material×2、lesson_plan_material×1 |
| huaxue | 2018b | 2 | lesson_plan_material×2 |
| huaxue | 2019a | 2 | case_material×2 |
| **huaxue 小计** | 3 个文件 | **7**（0 行文件 0 个） |  |
| lishi | 2017a-k2 | 3 | case_material×2、lesson_plan_material×1 |
| lishi | 2017b-k2 | 4 | case_material×3、lesson_plan_material×1 |
| lishi | 2018a | 3 | case_material×2、lesson_plan_material×1 |
| lishi | 2018b | 3 | case_material×2、lesson_plan_material×1 |
| lishi | 2019a | 4 | case_material×3、lesson_plan_material×1 |
| lishi | 2020b | 1 | case_material×1 |
| lishi | 2023a | 3 | case_material×2、lesson_plan_material×1 |
| **lishi 小计** | 7 个文件 | **21**（0 行文件 0 个） |  |
| meishu | 2013a | 3 | case_material×2、lesson_plan_material×1 |
| meishu | 2013b | 1 | case_material×1 |
| meishu | 2019a | 1 | case_material×1 |
| meishu | 2019b | 2 | case_material×2 |
| meishu | 2020b | 2 | case_material×2 |
| meishu | 2021a | 1 | case_material×1 |
| meishu | 2021b | 2 | case_material×2 |
| meishu | 2022a | 2 | case_material×2 |
| meishu | 2022b | 2 | case_material×2 |
| meishu | 2023b | 2 | case_material×2 |
| **meishu 小计** | 10 个文件 | **18**（0 行文件 0 个） |  |
| shengwu | 2016a | 2 | case_material×1、lesson_plan_material×1 |
| shengwu | 2019a | 1 | case_material×1 |
| shengwu | 2019b | 3 | case_material×2、lesson_plan_material×1 |
| shengwu | 2020b | 2 | case_material×2 |
| shengwu | 2021a | 1 | case_material×1 |
| shengwu | 2021b | 3 | case_material×2、lesson_plan_material×1 |
| **shengwu 小计** | 6 个文件 | **12**（0 行文件 0 个） |  |
| shuxue | 2014b | 1 | case_material×1 |
| shuxue | 2019a | 1 | case_material×1 |
| shuxue | 2019b | 1 | lesson_plan_material×1 |
| shuxue | 2020b | 1 | case_material×1 |
| shuxue | 2021b | 2 | case_material×1、lesson_plan_material×1 |
| shuxue | 2022a | 1 | case_material×1 |
| shuxue | 2022b | 2 | case_material×1、lesson_plan_material×1 |
| shuxue | 2023a | 2 | case_material×1、lesson_plan_material×1 |
| shuxue | 2023b | 1 | lesson_plan_material×1 |
| **shuxue 小计** | 9 个文件 | **12**（0 行文件 0 个） |  |
| tiyu | 2017b | 3 | case_material×2、lesson_plan_material×1 |
| tiyu | 2019a | 2 | case_material×2 |
| tiyu | 2020b | 2 | case_material×2 |
| tiyu | 2021a | 3 | case_material×2、lesson_plan_material×1 |
| tiyu | 2021b | 0 | —（0 行） |
| tiyu | 2022a | 3 | case_material×2、lesson_plan_material×1 |
| tiyu | 2022b | 2 | case_material×2 |
| **tiyu 小计** | 7 个文件 | **15**（0 行文件 1 个） |  |
| wuli | 2015a | 1 | case_material×1 |
| wuli | 2016b | 1 | case_material×1 |
| wuli | 2017b | 1 | case_material×1 |
| wuli | 2018a | 1 | case_material×1 |
| wuli | 2021b | 1 | case_material×1 |
| wuli | 2022a | 2 | case_material×2 |
| **wuli 小计** | 6 个文件 | **7**（0 行文件 0 个） |  |
| xinxi | 2015b | 1 | case_material×1 |
| xinxi | 2017a-k2 | 3 | case_material×2、lesson_plan_material×1 |
| xinxi | 2017b-k2 | 3 | case_material×2、lesson_plan_material×1 |
| xinxi | 2018a | 4 | case_material×3、lesson_plan_material×1 |
| xinxi | 2018b | 3 | case_material×2、lesson_plan_material×1 |
| xinxi | 2019b | 3 | case_material×2、lesson_plan_material×1 |
| xinxi | 2020b | 2 | case_material×2 |
| xinxi | 2021a | 2 | case_material×2 |
| xinxi | 2021b | 3 | case_material×3 |
| **xinxi 小计** | 9 个文件 | **24**（0 行文件 0 个） |  |
| yingyu | 2013a-jx | 0 | —（0 行） |
| yingyu | 2013b | 0 | —（0 行） |
| yingyu | 2019a | 0 | —（0 行） |
| yingyu | 2020b | 1 | lesson_plan_material×1 |
| yingyu | 2021a | 0 | —（0 行） |
| yingyu | 2021b | 0 | —（0 行） |
| yingyu | 2022a | 0 | —（0 行） |
| yingyu | 2023a | 0 | —（0 行） |
| yingyu | 2023b | 0 | —（0 行） |
| **yingyu 小计** | 9 个文件 | **1**（0 行文件 8 个） |  |
| yinyue | 2019b | 1 | case_material×1 |
| yinyue | 2021b | 1 | case_material×1 |
| yinyue | 2022a | 1 | case_material×1 |
| yinyue | 2023a | 0 | —（0 行） |
| yinyue | 2023b | 1 | lesson_plan_material×1 |
| **yinyue 小计** | 5 个文件 | **4**（0 行文件 1 个） |  |
| yuwen | 2012b | 0 | —（0 行） |
| yuwen | 2013b | 1 | lesson_plan_material×1 |
| yuwen | 2014a-jx | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2014a | 1 | lesson_plan_material×1 |
| yuwen | 2014b-k2 | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2014b | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2015a-jx | 1 | case_material×1 |
| yuwen | 2015b-jx | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2016a | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2016b | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2017a | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2017b | 3 | case_material×2、lesson_plan_material×1 |
| yuwen | 2019a | 1 | case_material×1 |
| yuwen | 2019b | 1 | case_material×1 |
| yuwen | 2020b | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2021a | 2 | case_material×1、lesson_plan_material×1 |
| yuwen | 2021b | 0 | —（0 行） |
| yuwen | 2023a | 0 | —（0 行） |
| yuwen | 2023b | 0 | —（0 行） |
| **yuwen 小计** | 19 个文件 | **29**（0 行文件 4 个） |  |
| zhengzhi | 2012b | 1 | lesson_plan_material×1 |
| zhengzhi | 2014a-jx | 0 | —（0 行） |
| zhengzhi | 2018a | 2 | case_material×1、lesson_plan_material×1 |
| zhengzhi | 2019a | 0 | —（0 行） |
| zhengzhi | 2019b | 0 | —（0 行） |
| zhengzhi | 2021b | 3 | case_material×2、lesson_plan_material×1 |
| zhengzhi | 2022a | 2 | case_material×1、lesson_plan_material×1 |
| zhengzhi | 2023a | 1 | lesson_plan_material×1 |
| **zhengzhi 小计** | 8 个文件 | **9**（0 行文件 3 个） |  |

## 每行内容与状态语义

- `material_id` 形状：`ntce.chuzhong.<subject>.<session>.m<NN>`（卷内顺序编号）或 `<question_id>.material.recovered`（原文区间补录，`review.extraction_status=source_interval_recovered_pending_expert`）。
- `kind` 三枚举中本目录实测值见上表（case=案例分析类材料，lesson_plan=教学设计题所用的教材/教案片段；interview_material 全库当前 0 条）。
- `used_by_questions`/`question_ids`：由题目行 `material_id` 反向重算，非人工填写；每条材料当前恰好 1 道引用题。引用断了不会静默——图谱 refers_to_material 边与 validate_kb 外键检查都以这两个字段对账。
- 0 行文件：该卷材料经 `ntce_material_repair.py` 复核后未存活（自动关联回退/原文未达边界规则），题目行对应 `material_id` 已置 null，文件保留以维持与卷面的同名对应。
