# 数据集/教资/questions/ —— 这里放 NTCE 结构化真题（L6 题面层），build_kb/ntce_repair 生成，repository 索引层消费

八层体系（MANIFEST.json 的 eight_layer_hierarchy，L0–L7）里这里是 **L6_question_rubric** 的题目侧：622 份卷面 JSONL、共 14,500 行（一行一题，逐行过 数据集/教资/schemas/question.json 的 Draft2020-12 校验），按 `学段/科目/卷面.jsonl` 摆放。
生成：`kb_tools/build_kb.py build` 首次解析 `教资原始资料/真题/**.csv`（经符号链接 `教资` 读取）落库；此后每次 build 检测到 jsonl 已存在会直接转 `kb_tools/ntce_repair.repair()` 安全复算（build_kb.py:608），状态由 repair 与 `ntce_difficulty.py`（难度）、`batch_upgrade_ntce_analysis.py`（结构化解析）、`ntce_conflict_reconcile.py`（答案冲突调解）等脚本推进。
消费：`services/knowledge/repository.py` 把本目录（QUESTION_DIRS 的两个入口之一）建成字节偏移题目索引，供 services/practice 组卷、diagnostic 诊断、qa 答疑、grader 判分读取；`kb_tools/build_graph.py` 由此生成 L6 节点与 assesses/has_rubric 边；`审查/build_review_queue.py` 从这里现算 `审查/待复核清单.md`。
改这里必须跑的门禁：`python -m pytest tests/test_status_vocabulary.py tests/test_ntce_hierarchy_contract.py -q`（逐行 Schema、状态词表、卡片镜像、八层契约）、`python 审查/状态词表检查.py 数据集/教资`、`python 审查/validate_kb.py`；全量回归总闸是 `python -m pytest tests -q`（tests/test_acceptance_gate.py 文件头指定的三件套）。

## level 分布（现算）

| level | 学段 | subject 目录数 | 卷面数 | 题数 | needs_fix | quarantined | duplicate_of | 无考点 |
|---|---|---|---|---|---|---|---|---|
| youer | 幼儿园 | 3 | 60 | 1,315 | 1,276 | 39 | 41 | 77 |
| xiaoxue | 小学 | 4 | 52 | 1,422 | 1,351 | 71 | 103 | 134 |
| chuzhong | 初中 | 13 | 227 | 5,016 | 4,714 | 302 | 472 | 489 |
| gaozhong | 高中 | 13 | 223 | 4,857 | 4,498 | 359 | 870 | 516 |
| zhongxue | 中学（初高中共用公共科目） | 4 | 54 | 1,617 | 1,543 | 74 | 100 | 109 |
| zhongxiaoxue | 中小学面试 | 1 | 6 | 273 | 273 | 0 | 33 | 6 |
| **合计** |  | **38** | **622** | **14,500** | **13,655** | **845** | **1,619** | **1,331** |

## subject 目录清单（38 个目录，逐个列出；每个目录内只有若干 `<session>.jsonl`，没有其它文件）

| level | subject 目录（逐个） | 中文科目 | 卷数 | 题数 |
|---|---|---|---|---|
| youer | baojiao | 保教知识与能力 | 29 | 429 |
| youer | mianshi | 结构化面试 | 6 | 153 |
| youer | zonghe | 综合素质 | 25 | 733 |
| xiaoxue | jiaoxue | 教育教学知识与能力 | 22 | 596 |
| xiaoxue | jiaoyuxinlixue | 教育心理学（省考） | 3 | 36 |
| xiaoxue | jiaoyuxue | 教育学（省考） | 5 | 170 |
| xiaoxue | zonghe | 综合素质 | 22 | 620 |
| chuzhong | dili | 地理 | 18 | 422 |
| chuzhong | huaxue | 化学 | 14 | 267 |
| chuzhong | lishi | 历史 | 16 | 428 |
| chuzhong | meishu | 美术 | 21 | 648 |
| chuzhong | shengwu | 生物 | 15 | 420 |
| chuzhong | shuxue | 数学 | 19 | 269 |
| chuzhong | tiyu | 体育 | 11 | 225 |
| chuzhong | wuli | 物理 | 16 | 174 |
| chuzhong | xinxi | 信息科技 | 20 | 292 |
| chuzhong | yingyu | 英语 | 22 | 643 |
| chuzhong | yinyue | 音乐 | 13 | 327 |
| chuzhong | yuwen | 语文 | 22 | 415 |
| chuzhong | zhengzhi | 道德与法治/思想政治 | 20 | 486 |
| gaozhong | dili | 地理 | 16 | 329 |
| gaozhong | huaxue | 化学 | 15 | 312 |
| gaozhong | lishi | 历史 | 17 | 428 |
| gaozhong | meishu | 美术 | 18 | 553 |
| gaozhong | shengwu | 生物 | 18 | 509 |
| gaozhong | shuxue | 数学 | 19 | 282 |
| gaozhong | tiyu | 体育 | 11 | 267 |
| gaozhong | wuli | 物理 | 18 | 184 |
| gaozhong | xinxi | 信息科技 | 20 | 255 |
| gaozhong | yingyu | 英语 | 20 | 599 |
| gaozhong | yinyue | 音乐 | 13 | 321 |
| gaozhong | yuwen | 语文 | 19 | 328 |
| gaozhong | zhengzhi | 道德与法治/思想政治 | 19 | 490 |
| zhongxue | jiaoyuxinlixue | 教育心理学（省考） | 4 | 181 |
| zhongxue | jiaoyuxue | 教育学（省考） | 2 | 72 |
| zhongxue | jiaoyuzhishi | 教育知识与能力 | 24 | 664 |
| zhongxue | zonghe | 综合素质 | 24 | 700 |
| zhongxiaoxue | mianshi | 结构化面试 | 6 | 273 |

## 每个目录里有什么

- `questions/<level>/<subject>/<session>.jsonl`：一行一题。`question_id = <ntce|shengkao>.<level>.<subject>.<session>.q<NN>`，NN 从 1 起、等于 `extra.paper_order`；同 session 内题号撞车的兜底是 id 加 `_N` 后缀（build_kb.py:681-682）；现库实测 0 条这种 id。
- 卷面级**没有**独立的答案文件/材料文件：答案在每题 `content.answer/answer_status` 内；共享材料在兄弟目录 `../materials/<level>/<subject>/<session>.jsonl`（同名，仅当该卷有材料时存在）。
- `questions/<level>/README.md`×6：该学段逐卷明细表；本文件不重复它们。

## 命名规律与每行内容

卷面文件命名规律（由 kb_tools/build_kb.py 的 parse_meta/paper_session 决定，源 CSV 文件名→session 标识）：
- `YYYYa`/`YYYYb`：年份 + 半年。a=上半年场、b=下半年场（CN_HALF 字典 {'上':'a','下':'b'}，build_kb.py:84）——**这里的 a/b 不是 A/B 卷**。
- `-jx`：原始文件名含“精选”，即汇编精选卷而非全卷（variant=精选）。
- `-kN`（N≥2）：同一 level+subject 下解析出同名场次的第二份及以后卷面，按出现顺序避让（build_kb.py:646-649，qa flag 记“场次冲突改用 …”）；面试各章真题卷同年、学科卷同年双来源最常见。
- `YYYYm<m>-a`/`-b`（如 `2014m4-a`）：源文件只有年份+月份时 session=`YYYYm<月>`；末尾 a/b 才是卷级，取自文件名 `(A级)/(B级)`，仅四川省考卷使用。
- `na-p1`/`na-p2`（可叠 `-jx`）：无年份卷，`-p1/-p2` 来自源文件名结尾 `(1)/(2)`。
全库 622 份卷面的形状分布：`YYYYb`×277、`YYYYa`×245、`YYYYb-k2`×19、`YYYYb-jx`×18、`YYYYa-jx`×17、`YYYYa-k2`×16、`na-p1-jx`×4、`na-p2-jx`×4、`YYYY`×3、`YYYYb-jx-k2`×3、`YYYY-k2`×2、`YYYY-k3`×2、`YYYY-k4`×2、`YYYY-k5`×2、`YYYY-k6`×2、`YYYYm4-a`×2、`YYYYm4-b`×2、`YYYY-jx`×1、`YYYYa-jx-k2`×1。

## 省考范围

459 题 `exam=省考`、id 前缀 `shengkao`（辽宁/四川/江西卷）：xiaoxue/jiaoyuxinlixue（3 卷 36 题，全部 36 行皆为省考），xiaoxue/jiaoyuxue（5 卷 170 题，全部 170 行皆为省考），zhongxue/jiaoyuxinlixue（4 卷 181 题，全部 181 行皆为省考），zhongxue/jiaoyuxue（2 卷 72 题，全部 72 行皆为省考）——即上述目录内**全部**行皆为省考；其余 34 个科目目录全部为国考 `ntce` 前缀。

## 状态字段的实际口径（词表来自 数据集/教资/schemas/question.json 与 审查/状态词表检查.py，约束来自 tests/test_status_vocabulary.py、tests/test_acceptance_gate.py；数字为全库实测）

- 审核状态 `review.status`（六态词表 auto_parsed / llm_enhanced / checked / expert_reviewed / needs_fix / quarantined）：全库 14,500 题实测只有两种值——needs_fix 13,655 题、quarantined 845 题；auto_parsed/llm_enhanced/checked/expert_reviewed 均为 0。全库 `review.checked_by` 非空的记录为 0 条，即当前**没有任何一题拿到具名签核**；规则是标成 checked/expert_reviewed 必须同时有 `checked_by`（test_no_reviewer_less_human_review_stage_claims），运行时不许代签（A9：队列行 checked_by 必须为 None）。needs_fix 内部再按 `review.review_priority` 分 low_confidence（源文件严重异常）/flagged_general（一般瑕疵）两档，配套 `review.pending_reasons` 待补清单（difficulty_calibration_needed、question_specific_explanation_needed 等），只用于复核排序，不影响判分口径。
- 答案可用性 `content.answer_status`（五态词表 verified / letter_only / reference_only / missing / source_conflict）：实测 verified 0、letter_only 10,167、reference_only 3,339、missing 149、source_conflict 845。规则：`letter_only/reference_only` 必须带 `extra.answer_provenance`（letter/reference/brief 等抽取形状记录，不参与判分）；`source_conflict` 即“多来源答案对不上”，此时 `content.answer` 必须为 null 且 `review.status` 必须是 quarantined（test_source_conflict_answers_are_never_scoreable），原答案值留在 `extra.answer_candidate` 等教研裁决；隔离题永不进组卷/判分/向量召回（A3，运行时判定在 services/knowledge/trust.py），其卡片正文也不得断言具体选项字母。`missing` = 答案文件缺失或抽取为空。
- 难度 `difficulty`+`difficulty_meta.method`：实测 heuristic_objective_v1 9,706、heuristic_subjective_v1 3,014、null（未估出）1,780。都是启发式初估（ntce_difficulty.py，百分位秩/题型基准），未经真实作答样本校准前不得标 irt_calibrated；运行时对 heuristic 一律显示“教研初估”，输出里禁用 IRT/CAT/标准误声称（A7）。调用方接口申报的 `question_difficulty`（以及申报掌握度）不得被任何服务层读进判定，仅 services/memory/receipt.py 可拿它算提交指纹（A10）——申报难度不进判定。
- 重复题 `extra.duplicate_of`：题干归一化指纹与更早入库题相同，全库 1,619 题；这类题保留在 jsonl 里做归属证据，但不生成卡片（build_kb.py:728），所以卡集比题集少。
- 无考点题：`knowledge_node_ids=[]`，全库 1,331 题（其中 94 道省考卷题）尚未挂载图谱 L4 知识点，卡片头部 `knowledge_nodes: []`；运行时组卷/诊断走 `find_questions(require_nodes=True)` 时它们被排除——“有题无考点”不影响存在，但不会进考点画像。
- 学段冗余字段：契约测试断言每题 `school_level == level`（schemas 里 school_level 为规范字段、level 为历史兼容字段）。

## 改数据前必读的测试断言

- tests/test_status_vocabulary.py：全行过 schema/question.json；letter_only/reference_only 必须带 answer_provenance；source_conflict ⇒ answer=null + quarantined；checked/expert_reviewed ⇒ checked_by 非空；cards 头部 review_status/answer_status 必须是题记录逐题镜像（改状态不改卡会被抓）。
- tests/test_ntce_hierarchy_contract.py：`school_level==level`；带难度必有 difficulty_meta 且 method 不得含 irt_calibrated；主观题（材料分析/教学设计/简答/活动设计/写作）必须同时有 rubric_id 与内嵌 rubric 且 id 相等；jsonl 内禁止 U+2028/U+2029（防止解析器分行破损）。
- tests/test_acceptance_gate.py：A3 隔离不可漏、A7 难度措辞、A10 申报难度/申报掌握度不进判定——这三条直接把本目录字段语义钉在运行时。
