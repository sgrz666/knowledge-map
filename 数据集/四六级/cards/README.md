# 数据集/四六级/cards/ —— RAG 检索用自包含 Markdown 题卡（5340 张，126 个卷次目录），generate_cards.py 从 questions 全量派生，vector_index.py 入库为 cet_cards 集合

- 角色：题卡的派生产物目录，不含独立事实：每张卡的题面、答案、解析、原文/听力稿、音频引用全部来自 `questions/`+`passages/`+`listening/` 三个源目录。
- 生成：`scripts/generate_cards.py`（无 argparse，路径由 `__file__` 上溯定位 `ROOT=parents[3]`、`CARDS_DIR=数据集/四六级/cards`）；源数据变化后重跑该脚本全量重生成，卡本身不手改。
- 消费：`services/knowledge/vector_index.py`（`LIBRARY_PATHS['cet'] = 数据集/四六级/cards`，Chroma 持久集合 `cet_cards` 首次使用时从卡片重建）；每张卡 YAML Frontmatter 的 `review_status`/`answer_status` 作向量元数据，检索层据此拒答隔离/不可判分卡片（配合 `services/knowledge/retrieval.py` 的 fail-closed 状态过滤）。
- 门禁：卡片一致性靠重跑 `generate_cards.py` 保证，无专属卡片测试；源头数据受 `tests/test_cet_eight_layer_contract.py`、`tests/test_status_vocabulary.py`（三层状态词表）、`审查/validate_kb.py` 约束。手改卡片会在 vector_index 重建的内容哈希比较中被发现并覆盖。
- 组织：`cards/{cet4|cet6}/{YYYY-MM}-p{N}/q{NN}.md` —— 2 个级别目录 + 126 个卷次目录（cet4 58、cet6 68），目录名用连字符（区别于 `questions/` 用下划线），`qNN.md` 两位补零。共 5340 张 = questions 客观题 5632 − 写作 146 − 翻译 146。空占位卷目录 12 个（见下），保留目录结构、0 张卡。

## 文件清单

顶层只有 `cet4/`、`cet6/` 两个级别目录与两份说明（`README.md` 本文件、原目录内 `README.md`）。全部 126 个卷次子目录名与每组卡片数（现算，`generate_cards.py` 派生）：

### cet4/ —— 四级 58 个卷次目录，合计 2445 张

- `2015-06-p1`(55) `2015-06-p2`(55) `2015-12-p1`(55) `2015-12-p2`(59) `2015-12-p3`(55)
- `2016-06-p2`(55) `2016-06-p3`(30) `2016-12-p1`(55) `2016-12-p2`(55) `2016-12-p3`(30)
- `2017-06-p1`(55) `2017-06-p2`(55) `2017-06-p3`(29) `2017-12-p1`(55) `2017-12-p3`(30)
- `2018-12-p1`(55) `2018-12-p2`(55) `2018-12-p3`(30)
- `2019-06-p1`(55) `2019-06-p2`(55) `2019-06-p3`(30) `2019-12-p1`(55) `2019-12-p2`(55) `2019-12-p3`(30)
- `2020-09-p1`(55) `2020-09-p2`(30) `2020-09-p3`(0) `2020-12-p1`(55) `2020-12-p2`(55) `2020-12-p3`(30)
- `2021-06-p1`(47) `2021-06-p2`(55) `2021-06-p3`(30) `2021-12-p3`(55)
- `2022-06-p1`(55) `2022-06-p2`(30) `2022-06-p3`(0) `2022-09-p1`(55) `2022-09-p2`(0) `2022-09-p3`(0) `2022-12-p1`(55) `2022-12-p2`(55) `2022-12-p3`(30)
- `2023-03-p1`(55) `2023-03-p2`(0) `2023-03-p3`(0) `2023-06-p1`(55) `2023-06-p2`(55) `2023-06-p3`(30)
- `2024-12-p1`(55) `2024-12-p2`(47) `2024-12-p3`(30) `2025-06-p1`(55) `2025-06-p2`(55) `2025-06-p3`(30) `2025-12-p1`(55) `2025-12-p2`(53) `2025-12-p3`(30)

cet4 空占位目录 6 个：`2020-09-p3`、`2022-06-p3`、`2022-09-p2`、`2022-09-p3`、`2023-03-p2`、`2023-03-p3`。

### cet6/ —— 六级 68 个卷次目录，合计 2895 张

- `2015-06-p1`(45) `2015-06-p2`(55) `2015-06-p3`(55) `2015-12-p1`(53) `2015-12-p2`(55) `2015-12-p3`(55)
- `2016-12-p1`(55) `2016-12-p2`(55) `2016-12-p3`(30)
- `2017-06-p1`(55) `2017-06-p2`(55) `2017-06-p3`(30) `2017-12-p1`(51) `2017-12-p2`(55) `2017-12-p3`(30)
- `2018-06-p1`(45) `2018-06-p2`(55) `2018-06-p3`(30) `2018-12-p1`(51) `2018-12-p2`(51) `2018-12-p3`(30)
- `2019-06-p1`(55) `2019-06-p2`(55) `2019-06-p3`(30) `2019-12-p1`(55) `2019-12-p2`(55) `2019-12-p3`(20)
- `2020-07-p1`(55) `2020-09-p1`(55) `2020-09-p2`(30) `2020-09-p3`(0) `2020-12-p1`(53) `2020-12-p2`(54) `2020-12-p3`(30)
- `2021-06-p1`(55) `2021-06-p2`(55) `2021-06-p3`(30) `2021-12-p3`(51)
- `2022-06-p1`(55) `2022-06-p2`(30) `2022-06-p3`(0) `2022-09-p1`(55) `2022-09-p2`(0) `2022-09-p3`(0) `2022-12-p1`(55) `2022-12-p2`(55) `2022-12-p3`(30)
- `2023-03-p1`(55) `2023-03-p2`(0) `2023-03-p3`(0) `2023-06-p1`(55) `2023-06-p2`(55) `2023-06-p3`(30)
- `2023-12-p1`(55) `2023-12-p2`(55) `2023-12-p3`(30) `2024-06-p1`(49) `2024-06-p2`(54) `2024-06-p3`(23) `2024-12-p1`(55) `2024-12-p2`(55) `2024-12-p3`(30)
- `2025-06-p1`(55) `2025-06-p2`(55) `2025-06-p3`(30) `2025-12-p1`(55) `2025-12-p2`(55) `2025-12-p3`(30)

cet6 空占位目录 6 个：`2020-09-p3`、`2022-06-p3`、`2022-09-p2`、`2022-09-p3`、`2023-03-p2`、`2023-03-p3`（与 cet4 同名：这些场次该套卷缺可解码真题）。

> 满编 55 张 = 听力 25（q01–q25）+ 阅读 30（q26–q55）；30/29/23 等不满的是纯阅读补齐槽位卷或解析册缺口；53–59 的是含伪题卡/历史缺漏槽位补齐的卷（如 `cet4/2015-12-p2` 59 张含 q56–q59 补齐卡）。逐卷卡数与对应卷文件的题量记录一致。

### 单张卡结构（现读 `cet4/2015-06-p1/q01.md`，68 行；`cet4/2015-12-p2/q59.md` 54 行补齐卡）

1. YAML Frontmatter（`generate_cards.py` 第 188–209 行字段）：`id`（=question_id，如 `cet4-2015-06-p1-listening-1`）、`exam`（CET-4/CET-6）、`level`（cet4/cet6）、`school_level`（college）、`subject`（english）、`session`（考次 YYYY-MM）、`section`（模块，如"听力理解"）、`question_type`（如"短篇新闻"）、`score`（客观题恒 7.1）、`material_id`（指向共享语篇/听力稿 resource_id，短题为 null）、`answer` 与 `answer_status`（五态）、`knowledge_nodes`、`ability_ids`、`exam_requirement_ids`、`rubric_id`（客观题 null）、`review_status`（六态，绝大多数 `auto_parsed`）、`content_verified`（false）、`copyright_scope`（research_non_commercial）、`source_nature`（official_past_paper）。
2. 题头行：【考次 · 级别 · 套卷 · 模块 · 题型 · 第 N 题】。
3. `### 听力录音文本 (Audio Transcript)`（听力题）或 `### 语篇材料 (Reading Passage)`（阅读题，含选词填空 Word Bank）——自包含，命中即带上下文。
4. `### 试题内容 (Question Stem & Options)`——题干 + 选项 + 正确答案（无则"待专家核定"）。
5. `### 结构化深度解析 (Four-Stage Cognitive Analysis)` 四小节：关键信息抓取 / 选项比对演练 / 原文证据回溯 / 全篇深度精析（`batch_upgrade_analysis.py`/`infer_candidate_answers.py` 产出的解析属模型生成，状态仍 pending；证据回溯行会写 `_staging/answers/...解析.pdf` 与 `level_b_dedicated_source` 等 OCR 证据分级）。
6. 尾注「核验与使用说明」标注八层 L6/L7、版权 unknown。

## 改这里之前要知道的

- 卡片是投影不是事实源：隔离题（`review.status=quarantined` 全库 101 题，其中 `content.answer_status=source_conflict` 亦 101）与伪题（`extra.active=false` 4 题）的卡片照常存在，但被检索层按元数据拒绝——不得为发布筛选删卡掩盖缺口。
- 状态词表以 `数据集/教资/schemas/question.json` 为权威：`review.status` 六态 `auto_parsed/llm_enhanced/checked/expert_reviewed/needs_fix/quarantined`（当前数据用到 auto_parsed 5354 / needs_fix 177 / quarantined 101），`content.answer_status` 五态 `verified/letter_only/reference_only/missing/source_conflict`（当前 letter_only 1285 / reference_only 292 / missing 3954 / source_conflict 101，verified 0）。
- `difficulty` 不在卡片口径里做校准：题面难度未取实测校准（heuristic 估计 `sample_size=0`、`calibration_status=heuristic_estimated`，或 null），不得据卡片跑 IRT。
- 手改无效且会被覆盖：重跑 `generate_cards.py`（或 chroma 重建）会抹掉任何在卡上直接改的字段。
- 卡片内嵌的听力稿/语篇原文与 `_staging/` OCR 解析路径同属生成依赖——`scripts/_staging/`（约 734MB OCR 中间件）不入库，删了要重跑抽取才能重生成卡。
