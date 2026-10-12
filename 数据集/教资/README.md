# 数据集/教资/ —— NTCE 教资交付知识库根目录：八层数据的物理落盘处，由 kb_tools 生成、由 services/knowledge 消费

- **层位**：本目录是教资（NTCE）交付知识库的根，八层体系 L0–L7 全部落在这里（L0 权威条款的正文在 `官方权威资料/`，只以节点与 locator 形式进图）。
- **生成**：`kb_tools/build_kb.py`（首次解析，产 `subject_map.json` / `qa_report.md`）→ `kb_tools/ntce_repair.py`（对齐、打标、量规、卡片、`stats.json`、`MANIFEST.json`）→ `kb_tools/build_graph.py`（`graph/nodes.jsonl`、`graph/edges.jsonl`）。
- **消费**：`services/knowledge/repository.py`（题库 / 图谱 / 量规 / 考务规格的唯一读入口）、`services/knowledge/vector_index.py`（`cards/` → Chroma 集合 `ntce_cards`）、`services/knowledge/graph_index.py`（16 词边名白名单与方向）、`services/grader/rubric_engine.py`（`rubrics/` 加权量规）、`services/knowledge/learning_resources.py`（`resources/` 两类）。
- **门禁**：结构改动过 `审查/validate_kb.py`；状态字段过 `审查/状态词表检查.py` + `tests/test_status_vocabulary.py`；图谱边名与端点过 `tests/test_graph_direction_contract.py`；量规双轨过 `tests/test_rubric_contract.py`；八层层级与全量 Schema 过 `tests/test_ntce_hierarchy_contract.py`；幂等回归过 `python kb_tools/ntce_verify.py --check-idempotence`。

现算总量（读目录与逐行解析得到，非引用自述）：题目 14,500 行 / 622 个 `questions/**/*.jsonl`、卡片 12,882 个 `.md`（其中 1 个是 `cards/README.md`，卡片 12,881）、图节点 22,107 行、图边 96,785 行 + 策展边 23 行、共享材料 586 行 / 324 个 jsonl、大纲 44 份（818 个节点、665 个 `assessable`）、Schema 11 份、量规 7 份、L7 资源 11 行、考务规格 32 行、复核产物 41 份。

---

## 文件清单（顶层 8 个文件）

- `MANIFEST.json`（3,677 B / 147 行）—— 库级台账：`generated=2026-10-02`、`source_files=695`、`questions=14500`、`materials=586`、`duplicate_questions_marked=1619`、`folder_duplicates_skipped=72`、`cards=12881`、`schema_version="2.0"`、`by_level` 六学段计数（youer 1315 / xiaoxue 1422 / zhongxiaoxue 273 / zhongxue 1617 / chuzhong 5016 / gaozhong 4857）、`by_level_subject` 38 项、`tagging`（knowledge_mapped 13169 / ability_mapped 13169 / requirement_mapped 10572）、`graph` 整块镜像（`by_layer`、`by_type`、`by_edge_type` 16 项、`eight_layer_hierarchy`）、`known_limitations` 3 条。**不要手改**，重跑 `python kb_tools/ntce_repair.py`（末尾 `atomic_write` 覆盖，且 `kb_tools/build_graph.py` 会回写 `graph` 块）。`kb_tools/ntce_verify.py` 只检查该文件存在。
- `schema.json`（4,489 B / 119 行）—— 题目 Schema 的**历史顶层副本**：`$id` 与 `schemas/question.json` 完全相同（`urn:knowledge-map:ntce-question:3.0`），内容不同——本文件 13 个 `required`（含 `level`、`tags`、`extra`，不含 `school_level`/`module`），`schemas/question.json` 12 个。全仓 `.py` 检索无任何引用；`services/llm/guardrails.py::SCHEMA_GLOBS = ("数据集/*/schemas/*.json",)` 只扫 `schemas/`，够不到本文件。**它是双真相残留，改题目形状时不要在这里改**，权威文件是 `schemas/question.json`；删除需另开一次核对，本次未删。
- `stats.json`（19,403 B / 690 行）—— 生成态全库统计快照（顶层 27 键 + `by_subject` 38 项）。**不要手改**，重跑 `python kb_tools/ntce_repair.py`（第 809 行 `atomic_write`）。注意现算口径已漂：本文件写 `answer_status.source_conflict=1040`、`letter_only=9972`，逐行读 `questions/` 现算是 **845 / 10,167**——差 195 条是 `kb_tools/ntce_conflict_reconcile.py` 落回的（见 `review/` 一节），而 `stats.json` 之后没重跑。运行时**没有**服务读它（`services/knowledge/repository.py::stats()` 是自己扫盘算的），只有 `kb_tools/ntce_verify.py` 检查文件存在。
- `subject_map.json`（10,772 B / 541 行）—— 科目名归一表，`list` 共 77 条，每条 `{raw, level, subject, subject_cn, count}`：把原始文件名/目录名（如《初中语文》《语文学科知识与教学能力》(初级中学)）归一到 `level` + 拼音科目码，科目码与 `graph` 节点 id 段、`questions/{level}/{subject}/` 目录名一致。由 `kb_tools/build_kb.py`（第 763 行）写出，**允许人工修订**（归一漏项就在这里补，再重跑解析）。
- `paper_specs.jsonl`（37,163 B / 32 行）—— L7 卷级考务规格（附录 A.6 `PaperSpecification`），一行一个 `{spec_id, exam, school_level, subject, subject_code, title, sections[], total_raw_score, total_duration_minutes, report_score_max, passing_report_score, score_conversion}`：32 = 学段 × 科目（`school_level` 现算 youer 2 / xiaoxue 2 / zhongxue 2 / chuzhong 13 / gaozhong 13），`sections[]` 合计 126 节，每套 3–5 节，`score_conversion.type` 全部是 `criterion_referenced_piecewise_linear`。生成器在四六级侧：`python 数据集/四六级/scripts/generate_paper_specs.py`（第 279 行同时写本文件），**不要手改**；受 `schemas/paper_spec.json`（11 个 required）约束，被 `services/knowledge/repository.py::PAPER_SPEC_FILES` 首位读入、模考时序由 `services/exam_sessions`/`services/practice` 逐节取分钟数，门禁 `tests/test_gap_remediation.py`（第 123 行）、`tests/test_web_workbench.py`（第 141 行）、`审查/build_review_queue.py`（`SPEC_FILES["NTCE"]`）。规格内部冲突不许机器挑边，核定口径见 `审查/待复核清单.md` §6。
- `qa_report.md`（213,136 B / 665 行）—— 人可读全量质检报告，3 个标题：`# 教资KB 质检报告`、`## 未识别科目的文件(0)`、`## 带标记的试卷(655)`，按卷列出低置信切分与异常题。由 `kb_tools/build_kb.py`（第 802 行）写出，**不要手改**，重跑解析即覆盖。它反映的是首次解析态，不随后续修复刷新；当前题级的真实缺口清单看 `review/pending.jsonl`。文内出现的材料数仍是早期值，以 `materials/` 现算 586 为准。
- `THIRD_PARTY_NOTICES.md`（5,047 B / 106 行）—— 来源与版权署明清单（人工维护）：逐条登记原料汇编出处、4 类 `source_nature` 口径、`authorization_status=unknown` 的含义、面试 61 项官方指标的出处。文中路径写的是退役前的 `教资KB/...`，引用本目录时以现路径为准；另有两处自述数字（隔离题 1,040）已落后于现算 845，改动数据时同步核。**这一份是允许手改的文档**，不是生成物。
- `README.md`（本文件，10,372 B / 111 行）—— 人写的规范说明与入口文档，无脚本覆盖它。

其余顶层条目：`.mimosa/`（工具态空目录 5 个，非知识数据）。

## 子目录清单（10 个，各有一份 README 说明逐文件明细）

- [`cards/`](cards/README.md) —— L6 轨 B：12,881 张自包含 Markdown 卡片 + 666 个目录层级；`vector_index.py` 入库时**排除** `README.md`。
- [`graph/`](graph/README.md) —— L0–L7 拓扑：`nodes.jsonl` 22,107 / `edges.jsonl` 96,785 / `edges_curated.jsonl` 23（唯一人工可版本化输入）。
- [`materials/`](materials/README.md) —— L5 共享材料：586 行 / 324 个 jsonl，一材料多小问双向关联。
- [`outline/`](outline/README.md) —— L4 考点树：44 份 `level.subject.json`、818 节点（其中 27 个省考节点因无题未入图，图内 `knowledge_node` 为 791）。
- [`questions/`](questions/README.md) —— L6 轨 A 唯一事实源：14,500 行 / 622 个 jsonl；状态字段词表在此定死后被卡片镜像。
- [`resources/`](resources/README.md) —— L7：4 个 jsonl 共 11 行，含无题考点的「资源外壳」草稿。
- [`review/`](review/README.md) —— 教研复核记录与生成态审计：41 份产物，逐份标了生成脚本与是否可重跑。
- [`rubrics/`](rubrics/README.md) —— 附录 A.6 加权量规实体：6 份（**全部待具名签署**）+ 官方面试 61 项原文。
- [`schemas/`](schemas/README.md) —— Draft 2020-12 全实体契约，11 份，两库共用的唯一 Schema 目录。
- [`sources/`](sources/README.md) —— 来源记录：3 个文件，1 条外部来源，sha256 现算一致。

---

## 1. 完整八层数据模型（L0–L7）

层级编号只有一套，就是规范 §3.2 的 L0–L7，物理计数以 `graph/nodes.jsonl` 现算的 `layer` 分布为准（`tests/test_graph_direction_contract.py` 禁 `hierarchy_level` 第二套字段）：

| 层级 | 实体类型 | 存储位置 | 现算规模 | 职能与约束 |
| :--- | :--- | :--- | :--- | :--- |
| **L0 权威标准层** | `standard` / `exam_requirement` | `官方权威资料/`，入图见 `graph/nodes.jsonl` | 2,320（标准 60 + 条款 2,260） | 条款全量入图、不按是否被引用裁剪，带 `locator` 原文坐标；退休条款只存 `官方权威资料/retired_requirement_records.jsonl`，不入图 |
| **L1 考试学段层** | `exam` | `graph/nodes.jsonl` | 7 | 幼/小/初/高/中学/中小学各学段与省考 |
| **L2 模块科目层** | `module` / `subject` | `graph/nodes.jsonl`、`subject_map.json` | 38 | 综合素质、保教、教育教学、学科知识与教学能力等 |
| **L3 素养能力层** | `literacy` / `ability` | `graph/nodes.jsonl` | 51（literacy 7 + ability 44） | 能力不隐式继承，逐边 `supports_ability` 显式给出 |
| **L4 知识点图谱层** | `knowledge_node` | `outline/*.json` → 入图 791 | 818 节点 / 791 入图 / 665 `assessable` | 先修 31 条边全部 `proposed_pending_review`、`active_for_learning_path=false`、`reviewed_by=null`，未核定 ⇒ 学习路径不做前置阻断 |
| **L5 共享材料层** | `material` | `materials/**/*.jsonl` | 586 | 案例分析材料、教学设计教材节选，`refers_to_material` 586 条 |
| **L6 试题评测层** | `question` / `rubric` | `questions/**/*.jsonl`、`rubrics/*.json`、题内 `q['rubric']` | 14,500 题 + 3,803 量规节点 = 18,303 | 客观题按字母判分；主观题只有无权重题内框架，出分须待 `rubrics/` 签署并绑定 |
| **L7 学习资源层** | `resource` | `resources/*.jsonl` | 11（8 核心 + 3 `study_guide` 草稿） | 指南是原创研究草稿：`review.status=needs_fix`、`checked_by=null`、`formal_question_pool_eligible=false`，不进题池 |

---

## 2. 双轨数据消费架构

同一个事实源写两遍形状，两轨各由不同模块读，字段不许互相发明。

### 轨 A：结构化关系题库
* 路径：`questions/*/*/*.jsonl`（14,500 行）、`materials/*/*/*.jsonl`（586 行）、`resources/*.jsonl`（11 行）。
* 角色：唯一事实源。每题只带自身题干/选项/答案/解析与外键 ID，长材料经 `material_id` 引用。
* 契约：`schemas/question.json`（`$id=urn:knowledge-map:ntce-question:3.0`，12 required）、`schemas/material.json`。
* 读入口：`services/knowledge/repository.py`（字节偏移索引 + `generation` 换代失效，缓存只跟踪 questions/requirements/paper_specs/graph 两端 + `rubrics/*.json`，**不跟踪** `cards/`、`outline/`、`review/`、`edges_curated.jsonl`）。

### 轨 B：RAG 自包含卡片
* 路径：`cards/{level}/{subject}/{session}/q{NN}.md`，12,881 张（现算 14,500 − 1,619 `duplicate_of`）。
* 结构：20 个 frontmatter 键（18 个必现；`rubric_id` 3,343、`material_id` 568）+ `【场次 · 学段·科目 · 题型 · 第N题】` 摘要行 + 题干选项 + `**答案:X**` + `**【结构化解析】**` 三段（12,875 张带）+ `**核验与使用:**` + `待补项:`；3,343 张附「**主观题练习评价量规（建议稿）:**」段，568 张内嵌 `**材料:**` 全文。均 3,371 B / 71 行（区间 34–564 行）。
* 入库：`services/knowledge/vector_index.py` 以 `CARD_DIRS["ntce"]="数据集/教资/cards"` 递归 `rglob("*.md")`，**两处显式跳过 `README.md`**（`card_files()` 第 395 行、`iter_cards()` 第 426 行），文档体是卡片正文，metadata 只搬运 frontmatter 的 `review_status` / `answer_status` / `knowledge_nodes` / `exam_requirement_ids` / `rubric_id` / `copyright_scope` 等（召回后 `services/knowledge/retrieval.py` 按状态过滤，隔离题不许漏进答案）。embedder 是 `hash-ngram-384` 词法哈希（不是语义模型），Chroma 集合 `ntce_cards`，按 blake2b-16 内容指纹增量重建并 prune，目录指纹 TTL 60 s（`KNOWLEDGE_MAP_CARD_TTL`）。

---

## 3. 实体规范 Schema 体系

`schemas/` 是全库唯一 Schema 目录（Draft 2020-12），四六级不设副本；逐文件字段与门禁见 [`schemas/README.md`](schemas/README.md)。现算 11 份：`question`、`material`、`knowledge_node`、`ability_node`、`requirement`、`rubric`、`practice_framework`、`user_mastery`、`card_frontmatter`、`paper_spec`、`tutor_reply`。校验入口：`tests/test_ntce_hierarchy_contract.py`（全量逐条过 jsonschema）、`tests/test_status_vocabulary.py`（两库题记录）、`tests/test_gap_remediation.py`（卡片头）、`tests/test_cet_eight_layer_contract.py`（借同一套校验 CET）、`services/llm/guardrails.py`（LLM 输出形状）。

---

## 4. 主观题评分量规（两套形状，只有一套能出分）

**加权量规实体**在 `rubrics/`（`schemas/rubric.json` 约束：维度只认 `dimension_name`/`weight_score`/`criteria_levels`，权重之和必须等于 `total_score`）。现算 6 份满分与维度权重：

1. `short_answer.json`：满分 10 = 核心得分要点覆盖率 5 / 各要点内涵解释与理论展开 3 / 分点序号与专业表达 2（`rubric_type=analytic`）；
2. `case_analysis.json`：满分 14 = 要点覆盖与知识点准确定位 4 / 材料分析与理论阐述结合度 4 / 答题框架层次与总分总逻辑 2.5 / 专业术语规范与文字流畅度 2 / 书写卷面与答题格式规范 1.5；
3. `lesson_plan.json`：满分 40 = 核心素养三维教学目标制定 10 / 教学重点与难点分析及突破策略 6 / 导入·新授·巩固·小结·作业各环节实施 16 / 板书提纲挈领与多媒体辅助有效性 4 / 现代教学理念与设计意图理论支撑 4；
4. `essay_writing.json`：满分 50 = 立意高度与教育结合度 18 / 论据充实度与典型性 14 / 篇章布局与论证递进关系 10 / 文字修辞、错别字与字数要求 8（唯一 `rubric_type=hybrid`，档位名写成「一等…五等分档归因」）；
5. `interview_qa.json`：满分 20 = 立德树人与教师职业价值观 6 / 问题定性、原因剖析与多维思考 6 / 应对策略切实可行性与教育智慧 5 / 教态自然沉着与普通话表达流畅 3；
6. `interview_teaching.json`：满分 50 = 核心概念讲授清晰度与重难点突破 15 / 模拟无生教学中的师生双边互动 15 / 板书规范美观与提纲性 10 / 教师仪态得体度与试讲节奏（10分钟）10。

6 份的 `review` 块现算**完全同形**：`status="needs_fix"`、`checked_by=null`、`checked_at=null`、`pending_reasons=["rubric_dimension_weights_pending_subject_expert","rubric_descriptor_wording_pending_subject_expert"]`，且 `official_scoring=false`、`expert_verified=false`、`question_specific_points=[]`。待签署状态就体现在这五个字段上，队列见 `审查/待复核清单.md` 第 4 节；签署前不得当作自动出分依据（`services/knowledge/trust.py::TrustGate.classify_rubric` 判据是 `review.status ∈ {checked, expert_reviewed}` 且 `checked_by` 非空且 `expert_verified` 为真，现算全部不满足）。

第 7 份 `official_interview.json` 是官方 61 项面试指标**原文引用**（`source`/`scope`/`criteria` + 逐条 `locator` 指向 `官方权威资料/text/*.tables.json` 的表格坐标），不是可计算实体；`kb_tools/build_graph.py` 第 124 行把它单独跳过、另建成 61 个 L6 参照节点（`official=true`、`review_status=question_task_mapping_pending_review`），`tests/test_rubric_contract.py::canonical_rubrics()` 也显式排除它并断言份数为 6。

**题内练习框架**在各题记录的 `q['rubric']`（`schemas/practice_framework.json` 约束）：现算 3,736 份，形状是 `{rubric_id="rubric."+question_id, status, official_scoring=false, expert_verified=false, dimensions[5]{name,max_level,levels[4]}, question_specific_points, question_specific_points_meta, exam_requirement_ids}`，全部 5 个维度、**无 `weight_score` 与 `criteria_levels`**，状态一律 `practice_framework_pending_subject_expert`；其中 2,588 份有具体得分点、1,148 份为空（对应 `pending.jsonl` 的 `question_specific_scoring_points_needed`）。它们经 `has_rubric` 边（3,736 条）挂在题上，只能出反馈清单不能判分。

双轨不许混写：同一维度同时带两套字段 ⇒ `Q_RUBRIC_DUAL_TRUTH`；客观题携带量规 ⇒ `Q_RUBRIC_ON_OBJECTIVE`；无署名却写 `expert_verified: true` ⇒ `Q_RUBRIC_EXPERT_CLAIM`。三条都由 `审查/validate_kb.py::rubric_shape_issues()` 报为结构错误，回归入口 `python -m pytest tests/test_rubric_contract.py -q`。

---

## 5. 真实性边界与合规说明

1. **状态词表只有一套**：`review.status` 六态 `auto_parsed / llm_enhanced / checked / expert_reviewed / needs_fix / quarantined`，`content.answer_status` 五态 `verified / letter_only / reference_only / missing / source_conflict`（取值域见 `schemas/question.json` 与 `tests/test_status_vocabulary.py`）。现算题记录：`review.status` = needs_fix 13,655 + quarantined 845，`answer_status` = letter_only 10,167 / reference_only 3,339 / source_conflict 845 / missing 149，`verified` 出现 0 次。卡片头部两字段必须与题记录逐字节镜像（`tests/test_status_vocabulary.py` 扫卡时跳过 `README.md`）。
2. **LLM 写权限铁律**：`services/llm/guardrails.py` 把 LLM 可写状态锁在 `{auto_parsed, llm_enhanced}`，`checked`/`expert_reviewed`/`needs_fix`/`quarantined` 在禁用清单里，具名字段（`checked_by` 等）只有教研能填。全库 `expert_verified_questions=0`（`stats.json` 与题记录一致）。
3. **争议答案隔离**：因版本矛盾的题标 `answer_status=source_conflict`、答案置 `null`、原候选保全在 `extra.answer_candidate` 与题记录里。现算 **845** 条，全部 `answer` 为 `null`。`stats.json` / `review/pending.jsonl` / `review/verification.json` 里写的 1,040 是核对前口径——`kb_tools/ntce_conflict_reconcile.py` 分 11 批核对 647 题、落回 195 题（`1040 − 195 = 845`），重跑 `ntce_repair.py` 才会把这些快照刷新。
4. **难度不冒充校准**：无作答数据 ⇒ 一律 `difficulty_meta.method = heuristic_*`（12,720 条有值、1,780 条如实为 null），`review/difficulty_calibration_report.json` 与 `审查/validate_kb.py` 一起盯这条线。
5. **版权**：14,500 条题记录的 `source.copyright.authorization_status` 现算全部 `unknown`，`holder` 与授权凭据 0 条；卡片一律 `copyright_scope=research_non_commercial`（12,881/12,881），来源性质 4 类 `official_exam 9263 / exam_recall 2514 / compiled_selection 941 / provincial_exam 163`。依据是《著作权法》第二十四条第一款第（六）项的科研合理使用，署明见 `THIRD_PARTY_NOTICES.md`；对外发布前须逐条清权，当前口径只覆盖库内非商业使用。

---

## 6. 工具链与验证指令

```bash
# 1. 全量复算流水线（大纲对齐 → 打标 → 量规 → 卡片 → MANIFEST/stats）
python kb_tools/ntce_repair.py --skip-outline   # 不带 --skip-outline 时先跑 m5_tag.gen_outline()

# 2. 图谱重导（nodes/edges，回写 MANIFEST.graph）
python kb_tools/build_graph.py

# 3. 结构验收 + 幂等双跑（写 review/verification.json）
python kb_tools/ntce_verify.py
python kb_tools/ntce_verify.py --check-idempotence

# 4. 形式门禁（结构错误与待补内容分开统计）
python 审查/validate_kb.py
python 审查/状态词表检查.py

# 5. 契约回归
python -m pytest tests/test_ntce_hierarchy_contract.py tests/test_status_vocabulary.py \
                 tests/test_graph_direction_contract.py tests/test_rubric_contract.py -q
```

生成物一律不手改：`questions/`、`materials/`、`cards/`、`graph/nodes.jsonl`、`graph/edges.jsonl`、`outline/*.json`、`stats.json`、`MANIFEST.json`、`review/` 里的审计产物都以上述脚本为准；允许人工维护的只有 `graph/edges_curated.jsonl`、`subject_map.json`、`sources/`、`review/answer_conflict_reconciliation.*` 所对应的教研签署动作，以及各 README。
