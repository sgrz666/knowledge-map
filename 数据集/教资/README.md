# 教资知识库规范与使用说明（v3 标准架构）

本知识库完全遵循《应试考证功能设计与技术支撑：以教资和四六级为例.md》权威标准建设，面向中小学教师资格考试（NTCE），落实八层数据层级（L0–L7）、双轨消费机制（结构化 JSONL + RAG Markdown 自包含卡片）、全实体 JSON Schema 契约、多维主观题评分量规库以及求真务实的测验学边界。

全量题库保留 14,500 条原始记录（含省考及重复标记），不以质量筛选削减分母。`stats.json` 为全库统计快照，`cards/` 保留 12,881 个非重复题独立自包含卡片视图。

---

## 1. 完整八层数据模型（L0–L7）

系统彻底贯彻规范第 3.2 节八层数据层级规范，拓扑网络记录于 `graph/nodes.jsonl` 与 `graph/edges.jsonl`（节点总数 22,104，边数 96,774）：

| 层级 | 实体类型 | 存储位置 | 当前规模 | 职能与约束 |
| :--- | :--- | :--- | :--- | :--- |
| **L0 权威标准层** | `standard` / `exam_requirement` | `权威资料/catalog.json`, `requirements.jsonl` | 2,320 条（标准 60 + 条款 2,260） | 考纲条款与国家标准条目全量入图（不按是否被题目引用裁剪），携带物理 locator 原文定位；142 条退休条款只存 `权威资料/retired_requirement_records.jsonl`，不入图 |
| **L1 考试学段层** | `exam` | `graph/nodes.jsonl` | 7 实体 | NTCE 各学段（幼/小/初/高/中学/中小学）及省考 |
| **L2 模块科目层** | `module` / `subject` | `graph/nodes.jsonl`, `subject_map.json` | 38 模块 | 综合素质、保教、教育教学、学科知识与教学能力等 |
| **L3 素养能力层** | `literacy` / `ability` | `graph/nodes.jsonl` | 51 维度 | 职业理念、教育法律、教师师德、教学设计、案例分析等 |
| **L4 知识点图谱层** | `knowledge_node` | `outline/*.json` | 791 细点 | 考纲细点树；先修依赖 31 条边均带概念依据说明，但全部为 `proposed_pending_review`、`active_for_learning_path = false`，尚未经教研核定，不用于强制前置阻断 |
| **L5 共享材料层** | `material` | `materials/*/*/*.jsonl` | 586 项 | 案例分析材料、教学设计教材节选，支持多小问双向关联 |
| **L6 试题评测层** | `question` | `questions/*/*/*.jsonl` | 14,500 题（另含 3,803 量规节点） | 选择题按选项字母自动判定；主观题只带无权重题内练习框架，自动出分须待 `rubrics/` 加权量规经教研签署并绑定 |
| **L7 学习资源层** | `resource` | `resources/*.jsonl` | 8 核心项 | 教育学核心流派理论、最新教育法规要点对照、面试策略模型 |

---

## 2. 双轨数据消费架构（Dual-Track Architecture）

为了同时满足刷题引擎的高效检索计算与大模型 RAG 的语义向量召回，知识库物理存储采用双轨分离设计：

### 轨 A：结构化关系题库（Structured Track）
* **文件路径**：`questions/*/*/*.jsonl`、`materials/*/*/*.jsonl`、`resources/*.jsonl`。
* **定位**：系统唯一事实源（Source of Truth）。每题仅存自身题干、选项、答案、得分点及关联外键 ID，长材料通过 `material_id` 引用，避免数据冗余。
* **Schema 约束**：`schemas/question.json`、`schemas/material.json`。

### 轨 B：RAG 自包含卡片（Vector / RAG Track）
* **文件路径**：`cards/{level}/{subject}/{session}/q{两位序号}.md`（共 12,881 份）。
* **定位**：一题一卡、自包含。向量检索后大模型无需跨库回表拼接。
* **卡片结构**：
  1. **头部 YAML Frontmatter**：包含 `id`, `exam`, `level`, `school_level`, `subject`, `session`, `section`, `question_type`, `score`, `material_id`, `answer`, `answer_status`, `knowledge_nodes`, `ability_ids`, `exam_requirement_ids`, `rubric_id`, `review_status`, `content_verified`, `copyright_scope`, `source_nature` 等完整元数据（对齐 `schemas/card_frontmatter.json`）；
  2. **自然语言摘要与材料全文**：`【2014a-jx · chuzhong·dili · 单选 · 第1题】`，若关联材料则将材料正文直接嵌入卡片；
  3. **三段结构化解析**：星火三段链条完整渲染（`【考点剖析与关键信息】`、`【选项深度对比/得分点】`、`【考点溯源与理论依据】`）；
  4. **练习评价框架与核验声明**：主观题卡片附带题内练习评价框架 JSON（`name`/`levels`/`max_level`，无分值权重，只能出反馈不能出分），标明版权授权状态与核验范围；选择题卡片不附带任何量规。

---

## 3. 实体规范 Schema 体系（对齐规范附录 A）

在 `schemas/` 目录下提供了完整的 Draft 2020-12 标准 JSON Schema 定义：

* [`schemas/question.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/question.json)：试题实体规范（包含 `school_level`, `module`, `rubric_id`, `difficulty_meta` 等）；
* [`schemas/material.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/material.json)：共享长材料与语篇规范；
* [`schemas/knowledge_node.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/knowledge_node.json)：细粒度知识点规范；
* [`schemas/ability_node.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/ability_node.json)：能力维度规范；
* [`schemas/requirement.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/requirement.json)：官方考纲要求规范；
* [`schemas/rubric.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/rubric.json)：多维评分量规规范；
* [`schemas/user_mastery.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/user_mastery.json)：用户掌握度与 FSRS 调度规范；
* [`schemas/card_frontmatter.json`](file:///d:/codeplus/knowledge_map/数据集/教资/schemas/card_frontmatter.json)：Markdown 卡片元数据规范。

---

## 4. 主观题评分量规（两套形状，只有一套能出分）

**加权量规实体**位于 `rubrics/`（`schemas/rubric.json` 约束，维度权重之和等于满分，可计算得分）。
维度名与分值以文件为准，2026-10-09 起每个维度只保留一套名称与一套档位：

1. `official_interview.json`：教育部官方 61 项面试评价指标原文（`source`/`scope`/`criteria` + 逐条 `locator`），不是可计算实体；
2. `short_answer.json`：简答题量规，满分 10 = 核心得分要点覆盖率 5 / 各要点内涵解释与理论展开 3 / 分点序号与专业表达 2；
3. `case_analysis.json`：材料分析题量规，满分 14 = 要点覆盖与知识点准确定位 4 / 材料分析与理论阐述结合度 4 / 答题框架层次与总分总逻辑 2.5 / 专业术语规范与文字流畅度 2 / 书写卷面与答题格式规范 1.5；
4. `lesson_plan.json`：教学设计题量规，满分 40 = 核心素养三维教学目标制定 10 / 教学重点与难点分析及突破策略 6 / 「导入、新授、巩固、小结、作业」各环节实施 16 / 板书提纲挈领与多媒体辅助有效性 4 / 现代教学理念与设计意图理论支撑 4；
5. `essay_writing.json`：综合素质大作文量规，满分 50 = 立意高度与教育结合度 18 / 论据充实度与典型性 14 / 篇章布局与论证递进关系 10 / 文字修辞、错别字与字数要求 8；
6. `interview_qa.json`：结构化问答量规，满分 20 = 立德树人与教师职业价值观 6 / 问题定性、原因剖析与多维思考 6 / 应对策略切实可行性与教育智慧 5 / 教态自然沉着与普通话表达流畅 3；
7. `interview_teaching.json`：试讲量规，满分 50 = 核心概念讲授清晰度与重难点突破 15 / 模拟无生教学中的师生双边互动 15 / 板书规范美观与提纲性 10 / 教师仪态得体度与试讲节奏（10分钟）10。

> 6 套实体的权重与档位措辞**均未经具名教研签署**：`review.status = needs_fix`、`review.checked_by = null`、
> `expert_verified = false`，`review.pending_reasons` 记有 `rubric_dimension_weights_pending_subject_expert`。
> 队列见 `审查/待复核清单.md` 第 4 节。签署前它们只作参照，不得当作自动出分依据。

**题内练习框架**位于各题记录的 `q['rubric']`（`schemas/practice_framework.json` 约束）：只有
`name`/`levels`/`max_level` 三个字段、**没有分值权重**，状态一律 `practice_framework_pending_subject_expert`，
用于生成自评反馈清单而不能判分。当前 3,736 份，全部经 `rubric.<question_id>` 与题目建立 `has_rubric` 边。
选择题不携带任何量规（`Q_RUBRIC_ON_OBJECTIVE` 拒绝）；两套字段在同一维度混写由 `Q_RUBRIC_DUAL_TRUTH` 拒绝。

---

## 5. 真实性边界与合规说明

1. **难度标注原则**：
   在缺乏真实考生大样本作答数据前，所有难度如实标注为启发式冷启动初估（`difficulty_meta.method = heuristic`），严禁标造为 IRT 真实校准；门禁脚本据此识别并阻止虚假校准。
2. **争议答案隔离原则**：
   全库 1,040 道因版本矛盾产生争议的试题全部标记为 `answer_status = source_conflict`，答案置为 `null`，原值保存在 `extra.answer_candidate` 中，杜绝争议答案错误扣除考生能力分。
3. **版权科研非商业使用原则**：
   严格遵循《著作权法》第二十四条第一款第（六）项合理使用规定，标注 `copyright_scope = research_non_commercial`，并在 `source.copyright.source_nature` 中细分 `official_exam`、`exam_recall`、`compiled_selection` 与 `provincial_exam` 四类来源性质。

---

## 6. 工具链与验证指令

```powershell
# 1. 运行安全复算流水线（对齐大纲、映射、量规、卡片、图谱）
python kb_tools/ntce_repair.py --skip-outline

# 2. 幂等性校验（执行两次全量构建，确保 13,898 个产物文件哈希逐字节一致）
python kb_tools/ntce_verify.py --check-idempotence

# 3. 运行八层体系与 Schema 契约回归测试
python -m pytest tests/test_ntce_hierarchy_contract.py
python -m pytest tests/test_ntce_repair.py

# 4. 全库质量验收门禁检查
python 审查/validate_kb.py
```
