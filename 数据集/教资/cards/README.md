# 数据集/教资/cards/ —— 这里放什么、谁生成、谁消费

- 本目录是教资 KB 八层体系中 L6（question_rubric 层）的 Markdown 轨（双轨之"轨 B"）：题记录的正本在 `questions/*/*/*.jsonl`，卡片是把同一条题记录投影成一整篇自包含文本，供向量检索直接 embedding；卡片里同时内嵌 L5 材料正文与 L4 知识点 id，检索命中一张卡即拿到答题所需的全部字段。
- 生成者是 `kb_tools`：正文渲染函数 `render_card()`（kb_tools/build_kb.py:539）；落盘由 `kb_tools/ntce_repair.py` 的 `sync_cards()`（ntce_repair.py:653，repair() 在 ntce_repair.py:790 调用它）完成。名字叫 sync，行为是全量重建：每次 `repair()` 对全部非重复题逐张 `render_card` 后 `atomic_write` 覆盖（ntce_repair.py:658-665），不做增量比对。`build_kb.py build` 在 `questions/` 已有 jsonl 时直接转入 `repair()`（build_kb.py:608-611），首次建库时的卡片写入分支在 build_kb.py:727-732。
- 消费者是 `services/knowledge/vector_index.py`：扫描本目录（CARD_DIRS 映射 `ntce → 数据集/教资/cards`，vector_index.py:35-38），入 Chroma 集合 `ntce_cards`（vector_index.py:39）。分块口径是一卡一文档：整张卡去掉 Frontmatter 的正文就是一个 document，不再切块（vector_index.py:425-436），doc id 为 `ntce:{question_id}`（vector_index.py:106-107）。入库指纹 `card_digest = blake2b-16(正文 + 排序后的 metadata)`（vector_index.py:96-103，写入 metadata 在 vector_index.py:454）；重建时只 upsert 指纹变过的卡（vector_index.py:495），消失的卡被 prune（vector_index.py:498-504、199-204）。embedder 是内置 `hash-ngram-384`（vector_index.py:41-42），无模型下载。
- 改卡片要过的门禁：`tests/test_ntce_hierarchy_contract.py` 的卡片镜像断言（`test_dual_track_markdown_cards_frontmatter_and_analysis`，142 行起；144 行硬编码卡片总数 12881）、`tests/test_status_vocabulary.py::test_card_frontmatter_mirrors_authoritative_states`（64-105 行，卡片 frontmatter 必须与题记录逐字段同值）、`审查/validate_kb.py`（作用于题记录正本，卡片是其镜像，隔离态门禁在 validate_kb.py:632-633）。

## 目录组织

三级结构，全部现算：`cards/{level}/{subject}/{试卷目录}/qNN.md`。level 6 个、subject 38 个、试卷目录（session）622 个，合计 6 + 38 + 622 = 666 个子目录，目录树深度到此为止（第 3 层之下无更深层级，现算 0 个）。每个试卷目录与 `questions/{level}/{subject}/{session}.jsonl` 一一对应：622 个 jsonl 对 622 个试卷目录，无单边多余（现算）。

| level | subject 数 | 试卷目录数 | 卡片数 |
|---|---|---|---|
| xiaoxue | 4 | 52 | 1,319 |
| chuzhong | 13 | 227 | 4,544 |
| gaozhong | 13 | 223 | 3,987 |
| youer | 3 | 60 | 1,274 |
| zhongxue | 4 | 54 | 1,517 |
| zhongxiaoxue | 1 | 6 | 240 |
| 合计 | 38 | 622 | 12,881 |

以下按 level 列出全部 666 个子目录名（level 名本身即 6 个一级目录）；试卷目录名逐 subject 全量列出，卡片数为该 subject 现算值。

### xiaoxue（4 subject / 52 试卷目录 / 1,319 卡）

| subject | 试卷目录数 | 卡片数 | 试卷目录名 |
|---|---|---|---|
| jiaoxue | 22 | 565 | 2011b, 2012a, 2012b, 2013a, 2013b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| jiaoyuxinlixue | 3 | 36 | 2014-jx, na-p1-jx, na-p2-jx |
| jiaoyuxue | 5 | 169 | 2014, 2014m4-a, 2014m4-b, na-p1-jx, na-p2-jx |
| zonghe | 22 | 549 | 2011b, 2012a, 2012b, 2013a, 2013b, 2014a, 2014b, 2015a, 2016a, 2016b, 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |

### chuzhong（13 subject / 227 试卷目录 / 4,544 卡）

| subject | 试卷目录数 | 卡片数 | 试卷目录名 |
|---|---|---|---|
| dili | 18 | 325 | 2014a-jx, 2014a-jx-k2, 2014b-jx, 2014b-jx-k2, 2015a, 2015b-jx, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2018a, 2018b, 2019a-jx, 2020b, 2021b, 2022a, 2023a |
| huaxue | 14 | 230 | 2015a, 2015b, 2016a-jx, 2016b-jx, 2017a, 2017a-k2, 2017b-jx, 2017b-jx-k2, 2018a, 2018b, 2019a, 2019b, 2021b, 2022a |
| lishi | 16 | 386 | 2015a, 2015b, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018b, 2019a, 2019b, 2020b, 2021b, 2022b, 2023a |
| meishu | 21 | 587 | 2013a, 2013b, 2014a, 2014a-jx, 2014b, 2014b-jx, 2015a-jx, 2015b-jx, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| shengwu | 15 | 388 | 2014a, 2014b, 2015a, 2015b, 2016a, 2016b-jx, 2017a, 2017b, 2018b, 2019a, 2019b, 2020b, 2021a, 2021b, 2023a |
| shuxue | 19 | 244 | 2012b, 2013b, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| tiyu | 11 | 215 | 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b |
| wuli | 16 | 155 | 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-jx, 2018a, 2018b, 2019a, 2021b, 2022a, 2023a |
| xinxi | 20 | 266 | 2014a-jx, 2014b-jx, 2015a, 2015b, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a |
| yingyu | 22 | 607 | 2013a-jx, 2013b, 2014a, 2014a-jx, 2014b, 2014b-jx, 2015a, 2015a-jx, 2015b, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b-jx, 2020b, 2021a, 2021b, 2021b-k2, 2022a, 2023a, 2023b |
| yinyue | 13 | 311 | 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021b, 2022a, 2023a, 2023b |
| yuwen | 22 | 346 | 2012b, 2013a-jx, 2013b, 2014a, 2014a-jx, 2014b, 2014b-k2, 2015a-jx, 2015b-jx, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| zhengzhi | 20 | 484 | 2012b, 2014a-jx, 2014b, 2015a, 2015b, 2016a, 2016b, 2016b-k2, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018b, 2019a, 2019b, 2021b, 2022a, 2022b, 2023a |

### gaozhong（13 subject / 223 试卷目录 / 3,987 卡）

| subject | 试卷目录数 | 卡片数 | 试卷目录名 |
|---|---|---|---|
| dili | 16 | 237 | 2013b, 2014a, 2014b, 2015a, 2015b, 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2020b, 2021b, 2022a, 2022b, 2023a |
| huaxue | 15 | 247 | 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018b, 2019a, 2019b, 2021b |
| lishi | 17 | 266 | 2014a, 2014b, 2015a, 2015b-jx, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018b, 2019a, 2019b, 2020b, 2022b, 2023a |
| meishu | 18 | 534 | 2013b, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| shengwu | 18 | 416 | 2012b, 2012b-k2, 2013a, 2013a-k2, 2013b, 2013b-k2, 2014a, 2014b, 2015a, 2017b, 2018a, 2018b, 2019a, 2019b, 2020b, 2021b, 2022b, 2023a |
| shuxue | 19 | 235 | 2013a, 2013b, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| tiyu | 11 | 261 | 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2021a, 2021b, 2022a, 2022b, 2023a |
| wuli | 18 | 163 | 2014a, 2014b, 2015a, 2015a-k2, 2015b, 2015b-k2, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-jx, 2018a, 2018b, 2019a, 2020b, 2021b, 2022b |
| xinxi | 20 | 221 | 2014a, 2014b, 2014b-k2, 2015a, 2015a-k2, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2023a |
| yingyu | 20 | 440 | 2013a, 2013b-jx, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2016b-k2, 2017a, 2017b, 2019a-jx, 2019b-jx, 2019b-jx-k2, 2020b, 2021a, 2021b, 2022b, 2023a, 2023b |
| yinyue | 13 | 304 | 2014b, 2015a, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021a, 2021b, 2023a, 2023b |
| yuwen | 19 | 293 | 2012a-jx, 2012b-jx, 2013a, 2013b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| zhengzhi | 19 | 370 | 2014a-jx, 2014b, 2015a-jx, 2015b-jx, 2016a, 2016b, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018b, 2019a, 2019b, 2021b, 2022a, 2022b, 2023a, 2023b |

### youer（3 subject / 60 试卷目录 / 1,274 卡）

| subject | 试卷目录数 | 卡片数 | 试卷目录名 |
|---|---|---|---|
| baojiao | 29 | 392 | 2011b, 2012a, 2012b, 2013a, 2013b, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2016b-k2, 2017a, 2017a-k2, 2017b, 2017b-k2, 2018a, 2018a-k2, 2018b, 2018b-k2, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| mianshi | 6 | 152 | 2018, 2018-k2, 2018-k3, 2018-k4, 2018-k5, 2018-k6 |
| zonghe | 25 | 730 | 2011b, 2012a, 2012b, 2013a, 2013b, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2020b, 2020b-k2, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |

### zhongxue（4 subject / 54 试卷目录 / 1,517 卡）

| subject | 试卷目录数 | 卡片数 | 试卷目录名 |
|---|---|---|---|
| jiaoyuxinlixue | 4 | 180 | 2014m4-a, 2014m4-b, na-p1-jx, na-p2-jx |
| jiaoyuxue | 2 | 70 | na-p1-jx, na-p2-jx |
| jiaoyuzhishi | 24 | 660 | 2011b, 2012a, 2012b, 2013a, 2013b, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |
| zonghe | 24 | 607 | 2011b, 2012a, 2012b, 2013a, 2013b, 2014a, 2014b, 2015a, 2015b, 2016a, 2016b, 2017a, 2017b, 2018a, 2018b, 2019a, 2019b, 2020b, 2021a, 2021b, 2022a, 2022b, 2023a, 2023b |

### zhongxiaoxue（1 subject / 6 试卷目录 / 240 卡）

| subject | 试卷目录数 | 卡片数 | 试卷目录名 |
|---|---|---|---|
| mianshi | 6 | 240 | 2018, 2018-k2, 2018-k3, 2018-k4, 2018-k5, 2018-k6 |

试卷目录名后缀口径（由 build_kb.py:643-651 生成）：`2012a`/`2012b` = 上半年/下半年场次；`-jx` = 吉林卷变体；`-k2`、`-k3`… = 同场次撞名后按出现序号追加的目录；`na-p1-jx`、`2014m4-a` 为无法归年场次的来源卷名兜底。

## 单张卡片的结构

正文骨架由 `render_card()`（build_kb.py:539-602）渲染，`sync_cards()` 再追加核验尾（ntce_repair.py:661-664）。Frontmatter 必填字段与类型由 `数据集/教资/schemas/card_frontmatter.json` 约束（required 共 12 项：id、exam、level、subject、session、section、question_type、knowledge_nodes、ability_ids、exam_requirement_ids、answer_status、review_status），抽检口径见 test_ntce_hierarchy_contract.py:148-158。

逐节说明（真实取值取自下面三张卡）：

1. **YAML Frontmatter**：`id` = question_id 全串；`exam: NTCE`；`level`/`subject`/`session` = 三级目录名；`section` = 卷面大题名（如 `单项选择题`、`简答题`）；`question_type` = 判型结果（单选/简答等，兜底 `未标注`）；`score` 无分值时写 `null`；`material_id` 仅关联材料的题出现；`answer` 客观题写字母、主观题写 `有` 或 `null`、答案被隔离时写 `未提供`；`answer_status` ∈ letter_only/reference_only/missing/source_conflict；`knowledge_nodes`/`ability_ids`/`exam_requirement_ids` 为行内数组（L4 知识点、L3 能力、L0 考纲外键）；`review_status` 当前库内只有 needs_fix 与 quarantined 两种；`content_verified: false`；`copyright_scope: research_non_commercial`；`source_nature: official_exam`；`rubric_id` 仅主观题出现。重复题不落卡，所以现存 12,881 张卡的 Frontmatter 键集合里没有 `duplicate_of`（全量扫描现算，实际出现过的键共 20 个）。
2. **摘要行**：`【{session} · {level}·{subject} · {question_type} · 第{paper_order}题】`（build_kb.py:573-575）。
3. **`**材料:**` 段**：仅 `material_id` 题出现，L5 共享材料全文内嵌（build_kb.py:577-578）。
4. **题干 + 选项列表**：题干一段，选项按 `- A. 文本` 逐行列出（build_kb.py:579-580）。
5. **`**答案: …**` 行**（build_kb.py:583）。
6. **`**【结构化解析】**` 段**：`考点剖析与关键信息:` / `选项深度对比/得分点:` / `考点溯源与理论依据:` 三小节，缺项时以 `**补充说明:**` 或整段 `**解析:**` 兜底（build_kb.py:585-601）。
7. **核验尾**（仅 sync_cards 追加）：`**核验与使用:**` 行 + 版权授权状态（ntce_repair.py:661）、`待补项:` 列表 = `review.pending_reasons`（ntce_repair.py:662）、主观题的 `**主观题练习评价量规（建议稿）:**` + rubric JSON 全文（ntce_repair.py:663-664）。

三张真卡（覆盖两个学段、两种题型，含一张隔离卡、一张空考点卡）：

- `zhongxue/zonghe/2012a/q18.md` —— 隔离卡：`review_status: quarantined`、`answer_status: source_conflict`、`answer: 未提供`，正文答案行是 `**答案:未提供**`，不出现任何选项字母；待补项含 `source_answer_conflict_review_needed`、`cross_question_boundary_review_needed`。另一张 `chuzhong/zhengzhi/2015b/q10.md` 同型（题干还带有邻题串入痕迹，正是 boundary 复核项存在的原因）。
- `youer/zonghe/2012a/q28.md` —— 空考点卡：`knowledge_nodes: []`、`ability_ids: []`、`exam_requirement_ids: []` 三线皆空，同时 `answer: C`、`answer_status: letter_only`；待补项含 `knowledge_alignment_needed`（挂点未做的标记）。
- `xiaoxue/jiaoxue/2012a/q24.md` —— 主观题卡（简答题）：`answer: null`、`answer_status: reference_only`、`rubric_id: rubric.ntce.xiaoxue.jiaoxue.2012a.q24`，正文尾部带 5 维度 + 5 条 `question_specific_points` 的量规 JSON，生成器标注 `ntce_rubric_points.py`、`official_scoring: false`。

命名规律：文件名 `qNN.md` 的 NN = 题记录 `extra.paper_order`（build_kb.py:722 写入 `i + 1`），= question_id 末段 `qNN`（build_kb.py:678 同一 `i + 1` 拼出），= 该题在 `questions/{level}/{subject}/{session}.jsonl` 里的行号。三者在现库全量对齐：14,500 行逐行核 `paper_order == 行号`、`question_id` 后缀与 `q{paper_order:02d}` 一致，0 例外；非重复题按此路径找卡，缺失 0 张。路径拼接口径只写在 `card_path()`（ntce_repair.py:590-592）一处，出卡、回卷核对与测试都调它。build_kb.py:680-682 存在撞号分支（question_id 追加 `_2` 等后缀）；现库未触发，全部 id 末段为纯 `qNN`。

## 现算统计

扫描口径：`cards/` 下 `.md` 共 12,882 个文件，其中根 `README.md` 1 个，卡片（`q*.md`）12,881 个。以下均对 12,881 张卡逐张解析 Frontmatter 现算。

- 按 level：chuzhong 4,544 / gaozhong 3,987 / zhongxue 1,517 / xiaoxue 1,319 / youer 1,274 / zhongxiaoxue 240（合计 12,881）。
- 按 subject（跨学段合并，前 10）：zonghe 1,886 / meishu 1,121 / yingyu 1,047 / zhengzhi 854 / shengwu 804 / jiaoyuzhishi 660 / lishi 652 / yuwen 639 / yinyue 615 / jiaoxue 565；20 个 subject 代码全量列于"目录组织"各表。
- 按 question_type：单选 9,430 / 简答 989 / 材料分析 909 / 未标注 438 / 教学设计 424 / 论述 392 / 多选 108 / 辨析 83 / 写作 39 / 活动设计 32 / 解答 28 / 诊断 9（合计 12,881）。
- `review_status`：needs_fix 12,128 / quarantined 753。`answer_status`：letter_only 9,018 / reference_only 3,017 / source_conflict 753 / missing 93。
- 隔离题卡片：753 张，与 `answer_status: source_conflict` 逐张同集合（both = 753）；按 level：gaozhong 301 / chuzhong 273 / zhongxue 71 / xiaoxue 69 / youer 39 / zhongxiaoxue 0。
- `knowledge_nodes: []` 的卡片：640 张；按 level：chuzhong 207 / gaozhong 166 / zhongxue 105 / xiaoxue 94 / youer 63 / zhongxiaoxue 5。
- 脚本侧对照物：`数据集/教资/stats.json`（repair() 写出，ntce_repair.py:790-809）记录 `questions: 14500, cards: 12881`，与现算一致。

"隔离题卡片正文不得断言具体选项字母"这条约束的出处是 `tests/test_status_vocabulary.py:93-103`：对 `answer_status == source_conflict` 的卡逐行扫正文，`正确答案`/`参考答案` 标记之后出现匹配 `[A-O]` 的单字母即 fail（101 行正则、103 行断言），94 行注释写明理由——防止污染向量库并冒充已核定标答。题记录层面的配套约束在 `审查/validate_kb.py:632-633`（`source_conflict` 必须 `quarantined`，error 级码 `Q_QUARANTINE_STATE_MISSING`）；隔离状态的产生点在 `kb_tools/ntce_repair.py:345-356`（`quarantine_unsafe_answer()` 把越界答案置 null、状态改 source_conflict）与 ntce_repair.py:783-785（repair() 内置 `review.status = 'quarantined'`）。

## 与题库的差集

题目 14,500（`questions/*/*/*.jsonl` 逐行现算，MANIFEST.json `questions` 同值），卡片 12,881，差额 1,619。构成现算如下，逐项对完：

| 规则 | 代码出处 | 现算命中 |
|---|---|---|
| 重复题（`extra.duplicate_of` 非空）不生成卡片 | build_kb.py:728 `if not dup_of:  # 重复题不落卡片,避免污染向量库`（当前管线的等价跳过在 ntce_repair.py:656-657） | 1,619 |
| 其他排除规则 | —— | 0 |

- 差集完全由 `duplicate_of` 一条规则解释：14,500 − 1,619 = 12,881，且逐 level 对平（chuzhong 5,016−472=4,544；gaozhong 4,857−870=3,987；xiaoxue 1,422−103=1,319；youer 1,315−41=1,274；zhongxue 1,617−100=1,517；zhongxiaoxue 273−33=240）。MANIFEST.json `duplicate_questions_marked: 1619` 同值。
- 判重口径是题干归一化指纹 `sha(norm_stem(stem))` 首次占用（build_kb.py:683-688），被指向的规范题出卡、重复题不出卡；这条归属的可核对性由 `dedup_evidence()` 单独审计（ntce_repair.py:595-624，注释在 598 行写明"被认作重复的那道题不出卡"）。
- 隔离题与缺题面/缺答案不产生差集：753 张隔离卡全部在库；`answer_status: missing` 的 93 张卡也全部在库——出卡只受 `duplicate_of` 一个门。
- 另有 72 份跨目录重复整卷在解析前就被跳过（build_kb.py:631-636，MANIFEST `folder_duplicates_skipped: 72`），它们的题从未进入 14,500，不构成题卡差额。

## 改这里之前要知道的

- 卡片是生成物。手改卡片正文会在下一次 `repair()` 跑 `sync_cards()`（ntce_repair.py:653-667、调用点 790）时被整张覆盖。要改卡的内容，改题记录正本 `questions/*.jsonl` 或改渲染器 `render_card()`（build_kb.py:539），再重跑：`python kb_tools/ntce_repair.py`（repair 入口）或 `python kb_tools/build_kb.py build`（检测到已有 jsonl 时转 repair，build_kb.py:608-611）。
- 门禁最小集：`python -m pytest tests/test_ntce_hierarchy_contract.py tests/test_status_vocabulary.py`。卡片数变了必须同步改 test_ntce_hierarchy_contract.py:144 的硬编码 `12881`；卡片 id 与题记录的对账、review/answer 状态逐字段镜像在 test_status_vocabulary.py:87-92；题记录侧的合规由 `python 审查/validate_kb.py` 全量验收（输出 审查/知识库验收结果.json）。
- README.md 被三处扫描逻辑显式排除，别指望它入索引或过卡片断言：`services/knowledge/vector_index.py:395`（`card_files()` 列表推导过滤 `path.name != "README.md"`）与 vector_index.py:426-427（`iter_cards()` 循环内 continue）、`tests/test_ntce_hierarchy_contract.py:143`（rglob 后过滤 README.md）；`tests/test_status_vocabulary.py:75-76` 同样跳过。反过来，本目录下任何其它非 `qNN.md` 的 `.md` 都会被 `rglob("*.md")` 扫进向量库——不要往试卷目录里随手放说明文件。
- 索引是可再生物：`chroma/`（默认在仓库根，vector_index.py:164-167）已 gitignore（文件头注释 vector_index.py:17）。删掉 `chroma/` 即对本目录全量重建：首次 `CardIndex.search()` 触发 `build()`（vector_index.py:482-518），或显式 `get_card_index().build(["ntce"])`。带外改卡后运行期最迟 60 秒（`KNOWLEDGE_MAP_CARD_TTL`，vector_index.py:50-62）按文件 mtime+size 指纹触发增量重建（vector_index.py:397-418），增量比对按 `card_digest` 内容指纹（vector_index.py:495）。
- 数字口径：本 README 全部数字为 2026-10 现算，统计脚本放在仓库外 `D:\tmp\cards_readme\`（stat1-stat7.py），仓库内未落任何工具脚本。

---

*勘误：需求口径中的"12,882 个卡片""差额 1,618"不成立——12,882 是含本 README.md 的 `.md` 文件总数，卡片现算 12,881，题卡差额现算 1,619，全部由 `duplicate_of` 构成。旧 README 写的"12,881 份"与现算一致，沿用无误。*
