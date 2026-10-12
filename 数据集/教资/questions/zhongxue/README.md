# 数据集/教资/questions/zhongxue/ —— 这里放中学（初高中共用公共科目）真题（L6），build_kb/ntce_repair 生成，repository 索引层消费

中学（初高中共用）公共科目 4 个目录：zonghe（《综合素质》中学）、jiaoyuzhishi（《教育知识与能力》）为国考 1,364 题；jiaoyuxue、jiaoyuxinlixue 为省考 253 题（shengkao 前缀）。
合计：4 个科目目录、54 份卷面 JSONL、1,617 行（一行一题）；审核状态实测 needs_fix 1,543、quarantined 74，本学段同样无具名签核（review.checked_by 全库为 null）。
生成：`kb_tools/build_kb.py` 首次入库（源文件路径存在每题 `source.origin_file`，可回溯到教资原始资料/真题 的 CSV）+ `kb_tools/ntce_repair.repair()` 每次复算重写（同时同步 ../cards 与 ../materials）。消费：`services/knowledge/repository.py` 偏移索引 → practice/diagnostic/qa/grader；`kb_tools/build_graph.py` L6 节点。
改这里必须跑的门禁：`python -m pytest tests/test_status_vocabulary.py tests/test_ntce_hierarchy_contract.py -q`（逐行 Schema、状态词表、卡片镜像、八层契约）、`python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`；全量回归总闸是 `python -m pytest tests -q`（tests/test_acceptance_gate.py 文件头指定的三件套）。

## 卷面文件清单（逐卷现算）

省考卷含 2014m4-a/2014m4-b（四川 A/B 级卷）与 na-p1-jx/na-p2-jx（江西精选拆卷）；jiaoyuzhishi 与 zonghe 各 24 卷，覆盖 2011b–2023b。../materials/zhongxue 只有 jiaoyuzhishi、zonghe 两个目录。

| subject | 卷面文件（去 .jsonl） | 题数=行数 | needs_fix | quarantined | 同名材料 jsonl 行数 | difficulty=null | duplicate_of 非空 | knowledge_node_ids 为空 |
|---|---|---|---|---|---|---|---|---|
| jiaoyuxinlixue | 2014m4-a | 33 | 33 | 0 | — | 1 | 0 | 6 |
| jiaoyuxinlixue | 2014m4-b | 34 | 33 | 1 | — | 1 | 0 | 3 |
| jiaoyuxinlixue | na-p1-jx | 58 | 56 | 2 | — | 3 | 1 | 8 |
| jiaoyuxinlixue | na-p2-jx | 56 | 54 | 2 | — | 2 | 0 | 12 |
| **jiaoyuxinlixue 小计** | 4 卷 | **181** | 176 | 5 |  | 7 | 1 | 29 |
| jiaoyuxue | na-p1-jx | 68 | 47 | 21 | — | 23 | 0 | 12 |
| jiaoyuxue | na-p2-jx | 4 | 1 | 3 | — | 4 | 2 | 2 |
| **jiaoyuxue 小计** | 2 卷 | **72** | 48 | 24 |  | 27 | 2 | 14 |
| jiaoyuzhishi | 2011b | 19 | 18 | 1 | 1 | 4 | 1 | 3 |
| jiaoyuzhishi | 2012a | 30 | 30 | 0 | 2 | 1 | 0 | 1 |
| jiaoyuzhishi | 2012b | 29 | 29 | 0 | 2 | 1 | 0 | 1 |
| jiaoyuzhishi | 2013a | 28 | 27 | 1 | 2 | 1 | 0 | 0 |
| jiaoyuzhishi | 2013b | 31 | 31 | 0 | 2 | 0 | 0 | 0 |
| jiaoyuzhishi | 2014a | 2 | 0 | 2 | — | 2 | 0 | 1 |
| jiaoyuzhishi | 2014b | 29 | 29 | 0 | 1 | 0 | 0 | 1 |
| jiaoyuzhishi | 2015a | 31 | 31 | 0 | — | 0 | 0 | 2 |
| jiaoyuzhishi | 2015b | 30 | 30 | 0 | 1 | 0 | 1 | 4 |
| jiaoyuzhishi | 2016a | 30 | 30 | 0 | — | 0 | 0 | 1 |
| jiaoyuzhishi | 2016b | 30 | 29 | 1 | — | 1 | 0 | 1 |
| jiaoyuzhishi | 2017a | 28 | 27 | 1 | 1 | 2 | 0 | 4 |
| jiaoyuzhishi | 2017b | 29 | 29 | 0 | — | 1 | 0 | 3 |
| jiaoyuzhishi | 2018a | 27 | 25 | 2 | — | 2 | 0 | 1 |
| jiaoyuzhishi | 2018b | 29 | 29 | 0 | 1 | 0 | 0 | 2 |
| jiaoyuzhishi | 2019a | 30 | 29 | 1 | 2 | 1 | 0 | 0 |
| jiaoyuzhishi | 2019b | 30 | 28 | 2 | 2 | 2 | 0 | 0 |
| jiaoyuzhishi | 2020b | 29 | 28 | 1 | 2 | 1 | 1 | 3 |
| jiaoyuzhishi | 2021a | 31 | 31 | 0 | 2 | 0 | 1 | 0 |
| jiaoyuzhishi | 2021b | 28 | 28 | 0 | 2 | 0 | 0 | 2 |
| jiaoyuzhishi | 2022a | 30 | 29 | 1 | 2 | 1 | 0 | 1 |
| jiaoyuzhishi | 2022b | 29 | 28 | 1 | 1 | 3 | 0 | 2 |
| jiaoyuzhishi | 2023a | 27 | 27 | 0 | 2 | 0 | 0 | 0 |
| jiaoyuzhishi | 2023b | 28 | 28 | 0 | 2 | 0 | 0 | 1 |
| **jiaoyuzhishi 小计** | 24 卷 | **664** | 650 | 14 |  | 23 | 4 | 34 |
| zonghe | 2011b | 34 | 34 | 0 | — | 0 | 27 | 0 |
| zonghe | 2012a | 32 | 31 | 1 | 4 | 2 | 0 | 1 |
| zonghe | 2012b | 32 | 31 | 1 | 3 | 1 | 26 | 0 |
| zonghe | 2013a | 32 | 32 | 0 | 4 | 0 | 5 | 3 |
| zonghe | 2013b | 33 | 33 | 0 | 2 | 0 | 30 | 1 |
| zonghe | 2014a | 33 | 33 | 0 | 1 | 0 | 0 | 1 |
| zonghe | 2014b | 32 | 31 | 1 | 1 | 1 | 0 | 0 |
| zonghe | 2015a | 29 | 27 | 2 | 1 | 2 | 0 | 0 |
| zonghe | 2015b | 29 | 26 | 3 | 1 | 3 | 0 | 3 |
| zonghe | 2016a | 31 | 31 | 0 | 1 | 0 | 0 | 1 |
| zonghe | 2016b | 32 | 31 | 1 | 1 | 1 | 0 | 2 |
| zonghe | 2017a | 26 | 24 | 2 | — | 2 | 0 | 2 |
| zonghe | 2017b | 32 | 32 | 0 | 1 | 0 | 0 | 2 |
| zonghe | 2018a | 32 | 31 | 1 | 1 | 1 | 0 | 2 |
| zonghe | 2018b | 29 | 26 | 3 | — | 3 | 0 | 0 |
| zonghe | 2019a | 28 | 24 | 4 | 4 | 4 | 0 | 0 |
| zonghe | 2019b | 20 | 18 | 2 | 4 | 2 | 1 | 1 |
| zonghe | 2020b | 29 | 28 | 1 | 0 | 1 | 0 | 3 |
| zonghe | 2021a | 29 | 28 | 1 | 4 | 1 | 0 | 1 |
| zonghe | 2021b | 28 | 25 | 3 | 4 | 3 | 2 | 1 |
| zonghe | 2022a | 32 | 31 | 1 | 4 | 1 | 1 | 1 |
| zonghe | 2022b | 11 | 8 | 3 | — | 4 | 0 | 2 |
| zonghe | 2023a | 23 | 22 | 1 | 4 | 1 | 1 | 2 |
| zonghe | 2023b | 32 | 32 | 0 | 4 | 0 | 0 | 3 |
| **zonghe 小计** | 24 卷 | **700** | 669 | 31 |  | 33 | 93 | 32 |

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
