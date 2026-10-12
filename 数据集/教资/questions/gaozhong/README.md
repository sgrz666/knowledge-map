# 数据集/教资/questions/gaozhong/ —— 这里放高中真题（L6），build_kb/ntce_repair 生成，repository 索引层消费

高中学段 13 个学科目录与初中同名，全部国考；公共科目同样在 zhongxue/。
合计：13 个科目目录、223 份卷面 JSONL、4,857 行（一行一题）；审核状态实测 needs_fix 4,498、quarantined 359，本学段同样无具名签核（review.checked_by 全库为 null）。
生成：`kb_tools/build_kb.py` 首次入库（源文件路径存在每题 `source.origin_file`，可回溯到教资原始资料/真题 的 CSV）+ `kb_tools/ntce_repair.repair()` 每次复算重写（同时同步 ../cards 与 ../materials）。消费：`services/knowledge/repository.py` 偏移索引 → practice/diagnostic/qa/grader；`kb_tools/build_graph.py` L6 节点。
改这里必须跑的门禁：`python -m pytest tests/test_status_vocabulary.py tests/test_ntce_hierarchy_contract.py -q`（逐行 Schema、状态词表、卡片镜像、八层契约）、`python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`；全量回归总闸是 `python -m pytest tests -q`（tests/test_acceptance_gate.py 文件头指定的三件套）。

## 卷面文件清单（逐卷现算）

shengwu 的 2012b-k2/2013a-k2/2013b-k2、yingyu 的 2016b-k2、2019b-jx-k2 等说明同场次的第二份源文件（多为回忆版双来源）按 -kN 顺延，题目 id 的 session 段与文件名完全一致。

| subject | 卷面文件（去 .jsonl） | 题数=行数 | needs_fix | quarantined | 同名材料 jsonl 行数 | difficulty=null | duplicate_of 非空 | knowledge_node_ids 为空 |
|---|---|---|---|---|---|---|---|---|
| dili | 2013b | 11 | 9 | 2 | — | 9 | 7 | 7 |
| dili | 2014a | 31 | 26 | 5 | — | 7 | 2 | 4 |
| dili | 2014b | 29 | 23 | 6 | — | 14 | 7 | 8 |
| dili | 2015a | 31 | 24 | 7 | — | 8 | 7 | 2 |
| dili | 2015b | 29 | 23 | 6 | — | 12 | 6 | 6 |
| dili | 2017a | 5 | 0 | 5 | 1 | 5 | 1 | 1 |
| dili | 2017b | 31 | 20 | 11 | 1 | 25 | 15 | 14 |
| dili | 2018a | 4 | 0 | 4 | 0 | 4 | 1 | 1 |
| dili | 2018b | 5 | 0 | 5 | 0 | 5 | 0 | 0 |
| dili | 2019a | 31 | 22 | 9 | 1 | 21 | 11 | 12 |
| dili | 2019b | 19 | 16 | 3 | 1 | 9 | 7 | 8 |
| dili | 2020b | 26 | 16 | 10 | 1 | 22 | 13 | 12 |
| dili | 2021b | 29 | 28 | 1 | 2 | 4 | 4 | 5 |
| dili | 2022a | 5 | 0 | 5 | 1 | 5 | 0 | 0 |
| dili | 2022b | 12 | 11 | 1 | 1 | 5 | 3 | 5 |
| dili | 2023a | 31 | 31 | 0 | 1 | 7 | 8 | 9 |
| **dili 小计** | 16 卷 | **329** | 249 | 80 |  | 162 | 92 | 94 |
| huaxue | 2014a | 16 | 10 | 6 | — | 7 | 1 | 2 |
| huaxue | 2014b | 11 | 8 | 3 | — | 6 | 1 | 1 |
| huaxue | 2015a | 25 | 20 | 5 | 1 | 7 | 2 | 6 |
| huaxue | 2015b | 24 | 20 | 4 | — | 6 | 3 | 4 |
| huaxue | 2016a | 23 | 21 | 2 | — | 2 | 1 | 1 |
| huaxue | 2016b | 25 | 23 | 2 | — | 2 | 1 | 1 |
| huaxue | 2017a-k2 | 16 | 15 | 1 | — | 4 | 9 | 4 |
| huaxue | 2017a | 25 | 23 | 2 | — | 3 | 3 | 2 |
| huaxue | 2017b-k2 | 19 | 18 | 1 | — | 7 | 14 | 6 |
| huaxue | 2017b | 24 | 21 | 3 | — | 7 | 7 | 5 |
| huaxue | 2018a | 16 | 14 | 2 | — | 4 | 2 | 3 |
| huaxue | 2018b | 25 | 25 | 0 | 2 | 1 | 2 | 1 |
| huaxue | 2019a | 23 | 22 | 1 | 3 | 4 | 4 | 3 |
| huaxue | 2019b | 17 | 16 | 1 | — | 8 | 7 | 7 |
| huaxue | 2021b | 23 | 23 | 0 | — | 3 | 8 | 3 |
| **huaxue 小计** | 15 卷 | **312** | 279 | 33 |  | 71 | 65 | 49 |
| lishi | 2014a | 21 | 16 | 5 | — | 21 | 0 | 0 |
| lishi | 2014b | 32 | 17 | 15 | 1 | 25 | 15 | 16 |
| lishi | 2015a | 32 | 29 | 3 | — | 25 | 10 | 0 |
| lishi | 2015b-jx | 16 | 11 | 5 | — | 12 | 9 | 6 |
| lishi | 2016a | 30 | 29 | 1 | — | 24 | 6 | 2 |
| lishi | 2016b | 32 | 31 | 1 | — | 25 | 7 | 2 |
| lishi | 2017a-k2 | 29 | 27 | 2 | 2 | 2 | 17 | 2 |
| lishi | 2017a | 32 | 32 | 0 | 1 | 25 | 10 | 1 |
| lishi | 2017b-k2 | 28 | 27 | 1 | 3 | 2 | 13 | 5 |
| lishi | 2017b | 5 | 3 | 2 | — | 2 | 0 | 1 |
| lishi | 2018a | 31 | 30 | 1 | 4 | 1 | 16 | 1 |
| lishi | 2018b | 30 | 28 | 2 | 3 | 2 | 10 | 4 |
| lishi | 2019a | 30 | 29 | 1 | 3 | 1 | 11 | 0 |
| lishi | 2019b | 25 | 23 | 2 | 4 | 3 | 2 | 1 |
| lishi | 2020b | 30 | 30 | 0 | 2 | 1 | 22 | 4 |
| lishi | 2022b | 6 | 2 | 4 | — | 4 | 4 | 1 |
| lishi | 2023a | 19 | 16 | 3 | 4 | 3 | 10 | 0 |
| **lishi 小计** | 17 卷 | **428** | 380 | 48 |  | 178 | 162 | 46 |
| meishu | 2013b | 22 | 21 | 1 | — | 2 | 0 | 1 |
| meishu | 2014a | 32 | 32 | 0 | — | 3 | 3 | 4 |
| meishu | 2014b | 30 | 30 | 0 | — | 1 | 1 | 1 |
| meishu | 2015a | 32 | 32 | 0 | — | 2 | 2 | 4 |
| meishu | 2015b | 33 | 33 | 0 | — | 0 | 0 | 0 |
| meishu | 2016a | 31 | 31 | 0 | — | 2 | 1 | 4 |
| meishu | 2016b | 32 | 32 | 0 | — | 0 | 0 | 2 |
| meishu | 2017a | 33 | 33 | 0 | — | 0 | 0 | 4 |
| meishu | 2017b | 33 | 33 | 0 | — | 0 | 0 | 2 |
| meishu | 2019a | 30 | 30 | 0 | 2 | 0 | 0 | 0 |
| meishu | 2019b | 22 | 21 | 1 | 3 | 4 | 3 | 4 |
| meishu | 2020b | 30 | 29 | 1 | 2 | 1 | 1 | 4 |
| meishu | 2021a | 32 | 32 | 0 | 2 | 0 | 0 | 0 |
| meishu | 2021b | 32 | 32 | 0 | 3 | 1 | 1 | 3 |
| meishu | 2022a | 33 | 33 | 0 | 2 | 4 | 4 | 8 |
| meishu | 2022b | 33 | 33 | 0 | 2 | 0 | 0 | 5 |
| meishu | 2023a | 31 | 29 | 2 | — | 4 | 3 | 4 |
| meishu | 2023b | 32 | 32 | 0 | 2 | 0 | 0 | 0 |
| **meishu 小计** | 18 卷 | **553** | 548 | 5 |  | 24 | 19 | 50 |
| shengwu | 2012b-k2 | 27 | 26 | 1 | 1 | 1 | 15 | 1 |
| shengwu | 2012b | 29 | 28 | 1 | — | 1 | 1 | 1 |
| shengwu | 2013a-k2 | 30 | 30 | 0 | 2 | 0 | 16 | 0 |
| shengwu | 2013a | 30 | 30 | 0 | — | 0 | 0 | 0 |
| shengwu | 2013b-k2 | 30 | 30 | 0 | 1 | 0 | 14 | 1 |
| shengwu | 2013b | 30 | 30 | 0 | — | 0 | 0 | 1 |
| shengwu | 2014a | 30 | 30 | 0 | — | 0 | 1 | 0 |
| shengwu | 2014b | 29 | 28 | 1 | — | 3 | 3 | 2 |
| shengwu | 2015a | 30 | 30 | 0 | — | 9 | 9 | 9 |
| shengwu | 2017b | 29 | 29 | 0 | — | 0 | 2 | 2 |
| shengwu | 2018a | 29 | 28 | 1 | 0 | 1 | 0 | 3 |
| shengwu | 2018b | 20 | 18 | 2 | 0 | 5 | 2 | 4 |
| shengwu | 2019a | 29 | 28 | 1 | 3 | 1 | 0 | 0 |
| shengwu | 2019b | 30 | 28 | 2 | 3 | 2 | 0 | 2 |
| shengwu | 2020b | 20 | 20 | 0 | 3 | 5 | 4 | 5 |
| shengwu | 2021b | 28 | 27 | 1 | — | 10 | 9 | 10 |
| shengwu | 2022b | 30 | 30 | 0 | 2 | 15 | 16 | 15 |
| shengwu | 2023a | 29 | 27 | 2 | 3 | 3 | 1 | 2 |
| **shengwu 小计** | 18 卷 | **509** | 497 | 12 |  | 56 | 93 | 58 |
| shuxue | 2013a | 15 | 13 | 2 | — | 2 | 0 | 0 |
| shuxue | 2013b | 16 | 15 | 1 | — | 1 | 0 | 2 |
| shuxue | 2014a | 16 | 13 | 3 | — | 6 | 2 | 4 |
| shuxue | 2014b | 15 | 15 | 0 | — | 1 | 2 | 1 |
| shuxue | 2015a | 17 | 16 | 1 | — | 4 | 3 | 4 |
| shuxue | 2015b | 17 | 16 | 1 | — | 4 | 5 | 5 |
| shuxue | 2016a | 15 | 13 | 2 | — | 5 | 4 | 4 |
| shuxue | 2016b | 15 | 14 | 1 | — | 4 | 5 | 3 |
| shuxue | 2017a | 16 | 14 | 2 | — | 5 | 6 | 3 |
| shuxue | 2017b | 17 | 17 | 0 | — | 1 | 3 | 1 |
| shuxue | 2019a | 14 | 12 | 2 | 1 | 2 | 5 | 1 |
| shuxue | 2019b | 8 | 4 | 4 | — | 4 | 0 | 1 |
| shuxue | 2020b | 11 | 9 | 2 | — | 3 | 0 | 1 |
| shuxue | 2021a | 14 | 12 | 2 | 1 | 3 | 5 | 2 |
| shuxue | 2021b | 16 | 14 | 2 | 2 | 3 | 1 | 2 |
| shuxue | 2022a | 14 | 12 | 2 | 1 | 4 | 2 | 2 |
| shuxue | 2022b | 15 | 13 | 2 | 1 | 5 | 2 | 3 |
| shuxue | 2023a | 17 | 15 | 2 | 2 | 3 | 0 | 2 |
| shuxue | 2023b | 14 | 13 | 1 | 2 | 1 | 2 | 1 |
| **shuxue 小计** | 19 卷 | **282** | 250 | 32 |  | 61 | 47 | 42 |
| tiyu | 2017a | 19 | 16 | 3 | 2 | 5 | 1 | 3 |
| tiyu | 2017b | 2 | 0 | 2 | — | 2 | 0 | 0 |
| tiyu | 2018a | 5 | 0 | 5 | 1 | 5 | 1 | 1 |
| tiyu | 2018b | 31 | 31 | 0 | 2 | 3 | 3 | 3 |
| tiyu | 2019a | 24 | 23 | 1 | 3 | 1 | 0 | 1 |
| tiyu | 2019b | 26 | 24 | 2 | 3 | 4 | 1 | 3 |
| tiyu | 2021a | 40 | 40 | 0 | 2 | 0 | 0 | 0 |
| tiyu | 2021b | 4 | 0 | 4 | — | 4 | 0 | 0 |
| tiyu | 2022a | 40 | 40 | 0 | 3 | 0 | 0 | 0 |
| tiyu | 2022b | 37 | 35 | 2 | — | 2 | 0 | 3 |
| tiyu | 2023a | 39 | 39 | 0 | 1 | 0 | 0 | 3 |
| **tiyu 小计** | 11 卷 | **267** | 248 | 19 |  | 26 | 6 | 17 |
| wuli | 2014a | 12 | 12 | 0 | — | 0 | 0 | 0 |
| wuli | 2014b | 12 | 12 | 0 | — | 3 | 3 | 5 |
| wuli | 2015a-k2 | 13 | 12 | 1 | 1 | 2 | 3 | 2 |
| wuli | 2015a | 10 | 8 | 2 | 1 | 4 | 1 | 2 |
| wuli | 2015b-k2 | 11 | 9 | 2 | 1 | 3 | 4 | 1 |
| wuli | 2015b | 13 | 11 | 2 | 1 | 3 | 1 | 2 |
| wuli | 2016a | 13 | 13 | 0 | — | 0 | 2 | 0 |
| wuli | 2016b | 13 | 12 | 1 | — | 3 | 1 | 2 |
| wuli | 2017a-k2 | 8 | 8 | 0 | 1 | 1 | 1 | 3 |
| wuli | 2017a | 12 | 10 | 2 | 1 | 3 | 1 | 1 |
| wuli | 2017b-jx | 12 | 11 | 1 | 1 | 3 | 2 | 2 |
| wuli | 2017b | 6 | 4 | 2 | 1 | 2 | 0 | 0 |
| wuli | 2018a | 5 | 2 | 3 | 1 | 3 | 0 | 0 |
| wuli | 2018b | 13 | 13 | 0 | — | 1 | 1 | 1 |
| wuli | 2019a | 12 | 10 | 2 | — | 3 | 1 | 1 |
| wuli | 2020b | 13 | 13 | 0 | — | 0 | 0 | 0 |
| wuli | 2021b | 2 | 2 | 0 | — | 0 | 0 | 2 |
| wuli | 2022b | 4 | 2 | 2 | 1 | 2 | 0 | 0 |
| **wuli 小计** | 18 卷 | **184** | 164 | 20 |  | 36 | 21 | 24 |
| xinxi | 2014a | 21 | 20 | 1 | — | 6 | 5 | 7 |
| xinxi | 2014b-k2 | 19 | 18 | 1 | — | 1 | 8 | 0 |
| xinxi | 2014b | 21 | 20 | 1 | — | 2 | 1 | 1 |
| xinxi | 2015a-k2 | 21 | 20 | 1 | — | 2 | 5 | 1 |
| xinxi | 2015a | 17 | 15 | 2 | — | 4 | 3 | 2 |
| xinxi | 2016a | 7 | 2 | 5 | — | 5 | 0 | 0 |
| xinxi | 2016b | 7 | 5 | 2 | — | 2 | 0 | 0 |
| xinxi | 2017a-k2 | 5 | 0 | 5 | 1 | 5 | 0 | 1 |
| xinxi | 2017a | 8 | 6 | 2 | — | 2 | 0 | 1 |
| xinxi | 2017b-k2 | 8 | 2 | 6 | — | 8 | 2 | 3 |
| xinxi | 2017b | 15 | 13 | 2 | — | 4 | 2 | 3 |
| xinxi | 2018a | 7 | 3 | 4 | — | 5 | 0 | 1 |
| xinxi | 2018b | 18 | 15 | 3 | 3 | 5 | 2 | 3 |
| xinxi | 2019a | 19 | 17 | 2 | — | 5 | 3 | 5 |
| xinxi | 2019b | 9 | 7 | 2 | — | 2 | 1 | 1 |
| xinxi | 2020b | 13 | 11 | 2 | 3 | 2 | 0 | 0 |
| xinxi | 2021a | 13 | 8 | 5 | 3 | 6 | 0 | 3 |
| xinxi | 2021b | 10 | 6 | 4 | 3 | 4 | 0 | 0 |
| xinxi | 2022a | 6 | 2 | 4 | — | 4 | 0 | 1 |
| xinxi | 2023a | 11 | 9 | 2 | — | 5 | 2 | 4 |
| **xinxi 小计** | 20 卷 | **255** | 199 | 56 |  | 79 | 34 | 37 |
| yingyu | 2013a | 32 | 31 | 1 | 1 | 1 | 10 | 0 |
| yingyu | 2013b-jx | 22 | 21 | 1 | 0 | 1 | 6 | 0 |
| yingyu | 2014a | 33 | 33 | 0 | 1 | 1 | 2 | 1 |
| yingyu | 2014b | 33 | 33 | 0 | — | 0 | 8 | 0 |
| yingyu | 2015a | 33 | 33 | 0 | — | 0 | 7 | 1 |
| yingyu | 2015b | 33 | 33 | 0 | — | 0 | 1 | 0 |
| yingyu | 2016a | 33 | 33 | 0 | — | 0 | 4 | 0 |
| yingyu | 2016b-k2 | 32 | 32 | 0 | 0 | 0 | 11 | 0 |
| yingyu | 2016b | 33 | 33 | 0 | — | 0 | 6 | 0 |
| yingyu | 2017a | 33 | 33 | 0 | — | 0 | 10 | 1 |
| yingyu | 2017b | 33 | 33 | 0 | — | 0 | 3 | 0 |
| yingyu | 2019a-jx | 30 | 30 | 0 | 0 | 0 | 8 | 0 |
| yingyu | 2019b-jx-k2 | 32 | 31 | 1 | 0 | 11 | 30 | 11 |
| yingyu | 2019b-jx | 21 | 20 | 1 | 0 | 1 | 4 | 2 |
| yingyu | 2020b | 33 | 33 | 0 | 1 | 0 | 9 | 0 |
| yingyu | 2021a | 33 | 33 | 0 | 0 | 0 | 8 | 0 |
| yingyu | 2021b | 3 | 0 | 3 | 0 | 3 | 0 | 1 |
| yingyu | 2022b | 32 | 32 | 0 | 0 | 13 | 13 | 13 |
| yingyu | 2023a | 32 | 32 | 0 | 0 | 0 | 10 | 0 |
| yingyu | 2023b | 33 | 33 | 0 | 1 | 2 | 9 | 2 |
| **yingyu 小计** | 20 卷 | **599** | 592 | 7 |  | 33 | 159 | 32 |
| yinyue | 2014b | 10 | 8 | 2 | — | 2 | 0 | 0 |
| yinyue | 2015a | 34 | 34 | 0 | — | 1 | 1 | 1 |
| yinyue | 2016a | 34 | 34 | 0 | — | 0 | 0 | 1 |
| yinyue | 2016b | 34 | 32 | 2 | — | 3 | 1 | 2 |
| yinyue | 2017a | 35 | 35 | 0 | — | 0 | 1 | 1 |
| yinyue | 2017b | 35 | 33 | 2 | — | 4 | 1 | 4 |
| yinyue | 2019a | 8 | 4 | 4 | — | 4 | 0 | 1 |
| yinyue | 2019b | 7 | 3 | 4 | 1 | 5 | 2 | 2 |
| yinyue | 2020b | 8 | 4 | 4 | — | 4 | 0 | 0 |
| yinyue | 2021a | 35 | 31 | 4 | 1 | 7 | 3 | 4 |
| yinyue | 2021b | 29 | 26 | 3 | 1 | 3 | 4 | 4 |
| yinyue | 2023a | 17 | 17 | 0 | 1 | 3 | 3 | 3 |
| yinyue | 2023b | 35 | 35 | 0 | 2 | 1 | 1 | 1 |
| **yinyue 小计** | 13 卷 | **321** | 296 | 25 |  | 37 | 17 | 24 |
| yuwen | 2012a-jx | 8 | 8 | 0 | — | 1 | 0 | 1 |
| yuwen | 2012b-jx | 12 | 12 | 0 | — | 0 | 0 | 0 |
| yuwen | 2013a | 21 | 21 | 0 | — | 1 | 2 | 1 |
| yuwen | 2013b | 21 | 21 | 0 | — | 1 | 1 | 1 |
| yuwen | 2015a | 21 | 21 | 0 | 3 | 0 | 0 | 0 |
| yuwen | 2015b | 21 | 21 | 0 | 2 | 0 | 0 | 0 |
| yuwen | 2016a | 21 | 21 | 0 | 3 | 0 | 0 | 0 |
| yuwen | 2016b | 20 | 20 | 0 | 2 | 0 | 2 | 0 |
| yuwen | 2017a | 21 | 20 | 1 | 3 | 1 | 2 | 0 |
| yuwen | 2017b | 21 | 21 | 0 | 3 | 0 | 3 | 0 |
| yuwen | 2019a | 21 | 21 | 0 | — | 1 | 2 | 1 |
| yuwen | 2019b | 21 | 21 | 0 | — | 0 | 0 | 0 |
| yuwen | 2020b | 8 | 4 | 4 | 0 | 4 | 0 | 0 |
| yuwen | 2021a | 23 | 23 | 0 | — | 4 | 4 | 4 |
| yuwen | 2021b | 21 | 21 | 0 | 0 | 3 | 5 | 4 |
| yuwen | 2022a | 21 | 21 | 0 | — | 5 | 6 | 6 |
| yuwen | 2022b | 9 | 8 | 1 | — | 2 | 2 | 3 |
| yuwen | 2023a | 10 | 10 | 0 | — | 3 | 4 | 8 |
| yuwen | 2023b | 7 | 6 | 1 | 0 | 2 | 2 | 2 |
| **yuwen 小计** | 19 卷 | **328** | 321 | 7 |  | 28 | 35 | 31 |
| zhengzhi | 2014a-jx | 32 | 31 | 1 | 1 | 2 | 1 | 1 |
| zhengzhi | 2014b | 35 | 35 | 0 | — | 0 | 0 | 0 |
| zhengzhi | 2015a-jx | 17 | 17 | 0 | 1 | 1 | 2 | 1 |
| zhengzhi | 2015b-jx | 11 | 11 | 0 | — | 0 | 3 | 1 |
| zhengzhi | 2016a | 34 | 33 | 1 | — | 1 | 2 | 0 |
| zhengzhi | 2016b | 11 | 9 | 2 | — | 2 | 2 | 1 |
| zhengzhi | 2017a-k2 | 2 | 0 | 2 | — | 2 | 0 | 0 |
| zhengzhi | 2017a | 35 | 35 | 0 | — | 0 | 7 | 0 |
| zhengzhi | 2017b-k2 | 34 | 33 | 1 | 3 | 1 | 19 | 0 |
| zhengzhi | 2017b | 35 | 34 | 1 | — | 1 | 7 | 0 |
| zhengzhi | 2018a | 1 | 0 | 1 | — | 1 | 0 | 0 |
| zhengzhi | 2018b | 3 | 0 | 3 | 1 | 3 | 0 | 0 |
| zhengzhi | 2019a | 35 | 35 | 0 | 2 | 0 | 0 | 0 |
| zhengzhi | 2019b | 34 | 33 | 1 | 2 | 9 | 9 | 8 |
| zhengzhi | 2021b | 34 | 34 | 0 | 2 | 0 | 8 | 0 |
| zhengzhi | 2022a | 34 | 34 | 0 | 3 | 0 | 24 | 0 |
| zhengzhi | 2022b | 34 | 33 | 1 | 3 | 1 | 24 | 0 |
| zhengzhi | 2023a | 35 | 35 | 0 | 2 | 0 | 12 | 0 |
| zhengzhi | 2023b | 34 | 33 | 1 | 1 | 1 | 0 | 0 |
| **zhengzhi 小计** | 19 卷 | **490** | 475 | 15 |  | 25 | 120 | 12 |

## 命名规律

卷面文件命名规律（由 kb_tools/build_kb.py 的 parse_meta/paper_session 决定，源 CSV 文件名→session 标识）：
- `YYYYa`/`YYYYb`：年份 + 半年。a=上半年场、b=下半年场（CN_HALF 字典 {'上':'a','下':'b'}，build_kb.py:84）——**这里的 a/b 不是 A/B 卷**。
- `-jx`：原始文件名含“精选”，即汇编精选卷而非全卷（variant=精选）。
- `-kN`（N≥2）：同一 level+subject 下解析出同名场次的第二份及以后卷面，按出现顺序避让（build_kb.py:646-649，qa flag 记“场次冲突改用 …”）；面试各章真题卷同年、学科卷同年双来源最常见。
- `YYYYm<m>-a`/`-b`（如 `2014m4-a`）：源文件只有年份+月份时 session=`YYYYm<月>`；末尾 a/b 才是卷级，取自文件名 `(A级)/(B级)`，仅四川省考卷使用。
- `na-p1`/`na-p2`（可叠 `-jx`）：无年份卷，`-p1/-p2` 来自源文件名结尾 `(1)/(2)`。
全库 622 份卷面的形状分布：`YYYYb`×277、`YYYYa`×245、`YYYYb-k2`×19、`YYYYb-jx`×18、`YYYYa-jx`×17、`YYYYa-k2`×16、`na-p1-jx`×4、`na-p2-jx`×4、`YYYY`×3、`YYYYb-jx-k2`×3、`YYYY-k2`×2、`YYYY-k3`×2、`YYYY-k4`×2、`YYYY-k5`×2、`YYYY-k6`×2、`YYYYm4-a`×2、`YYYYm4-b`×2、`YYYY-jx`×1、`YYYYa-jx-k2`×1。

## 状态字段口径（全库实测数字）

## 状态字段的实际口径（词表来自 数据集/教资/schemas/question.json 与 审查/状态词表检查.py，约束来自 tests/test_status_vocabulary.py、tests/test_acceptance_gate.py；数字为全库实测）

- 审核状态 `review.status`（六态词表 auto_parsed / llm_enhanced / checked / expert_reviewed / needs_fix / quarantined）：全库 14,500 题实测只有两种值——needs_fix 13,655 题、quarantined 845 题；auto_parsed/llm_enhanced/checked/expert_reviewed 均为 0。全库 `review.checked_by` 非空的记录为 0 条，即当前**没有任何一题拿到具名签核**；规则是标成 checked/expert_reviewed 必须同时有 `checked_by`（test_no_reviewer_less_human_review_stage_claims），运行时不许代签（A9：队列行 checked_by 必须为 None）。needs_fix 内部再按 `review.review_priority` 分 low_confidence（源文件严重异常）/flagged_general（一般瑕疵）两档，配套 `review.pending_reasons` 待补清单（difficulty_calibration_needed、question_specific_explanation_needed 等），只用于复核排序，不影响判分口径。
- 答案可用性 `content.answer_status`（五态词表 verified / letter_only / reference_only / missing / source_conflict）：实测 verified 0、letter_only 10,167、reference_only 3,339、missing 149、source_conflict 845。规则：`letter_only/reference_only` 必须带 `extra.answer_provenance`（letter/reference/brief 等抽取形状记录，不参与判分）；`source_conflict` 即“多来源答案对不上”，此时 `content.answer` 必须为 null 且 `review.status` 必须是 quarantined（test_source_conflict_answers_are_never_scoreable），原答案值留在 `extra.answer_candidate` 等教研裁决；隔离题永不进组卷/判分/向量召回（A3，运行时判定在 services/knowledge/trust.py），其卡片正文也不得断言具体选项字母。`missing` = 答案文件缺失或抽取为空。
- 难度 `difficulty`+`difficulty_meta.method`：实测 heuristic_objective_v1 9,706、heuristic_subjective_v1 3,014、null（未估出）1,780。都是启发式初估（ntce_difficulty.py，百分位秩/题型基准），未经真实作答样本校准前不得标 irt_calibrated；运行时对 heuristic 一律显示“教研初估”，输出里禁用 IRT/CAT/标准误声称（A7）。调用方接口申报的 `question_difficulty`（以及申报掌握度）不得被任何服务层读进判定，仅 services/memory/receipt.py 可拿它算提交指纹（A10）——申报难度不进判定。
- 重复题 `extra.duplicate_of`：题干归一化指纹与更早入库题相同，全库 1,619 题；这类题保留在 jsonl 里做归属证据，但不生成卡片（build_kb.py:728），所以卡集比题集少。
- 无考点题：`knowledge_node_ids=[]`，全库 1,331 题（其中 94 道省考卷题）尚未挂载图谱 L4 知识点，卡片头部 `knowledge_nodes: []`；运行时组卷/诊断走 `find_questions(require_nodes=True)` 时它们被排除——“有题无考点”不影响存在，但不会进考点画像。
- 学段冗余字段：契约测试断言每题 `school_level == level`（schemas 里 school_level 为规范字段、level 为历史兼容字段）。
