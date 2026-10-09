# 教资/rubrics — 附录 A.6 可计算加权量规实体

本目录存放**加权量规实体**（`schemas/rubric.json` 约束）：一个维度只有一套名称、一套档位、一个分值权重，
权重之和等于 `total_score`，因此可以计算得分。它与题目内嵌的**题内练习框架**（`q['rubric']`，
`schemas/practice_framework.json`，无权重、只出反馈）是两套形状，不得混写。

## 量规实体（6 套，权重单位：分）
- **short_answer.json**：简答题通用量规，满分 10 = 核心得分要点覆盖率 5 / 各要点内涵解释与理论展开 3 / 分点序号与专业表达 2。
- **case_analysis.json**：材料分析题通用量规，满分 14 = 要点覆盖与知识点准确定位 4 / 材料分析与理论阐述结合度 4 /
  答题框架层次与总分总逻辑 2.5 / 专业术语规范与文字流畅度 2 / 书写卷面与答题格式规范 1.5。
- **lesson_plan.json**：教学设计题通用量规，满分 40 = 核心素养三维教学目标制定 10 / 教学重点与难点分析及突破策略 6 /
  「导入、新授、巩固、小结、作业」各环节实施 16 / 板书提纲挈领与多媒体辅助有效性 4 / 现代教学理念与设计意图理论支撑 4。
- **essay_writing.json**：《综合素质》大作文量规，满分 50 = 立意高度与教育结合度 18 / 论据充实度与典型性 14 /
  篇章布局与论证递进关系 10 / 文字修辞、错别字与字数要求 8。
- **interview_qa.json**：面试结构化问答量规，满分 20 = 立德树人与教师职业价值观 6 / 问题定性、原因剖析与多维思考 6 /
  应对策略切实可行性与教育智慧 5 / 教态自然沉着与普通话表达流畅 3。
- **interview_teaching.json**：面试试讲量规，满分 50 = 核心概念讲授清晰度与重难点突破 15 / 模拟无生教学中的师生双边互动 15 /
  板书规范美观与提纲性 10 / 教师仪态得体度与试讲节奏（10 分钟）10。
- **official_interview.json**：官方 61 项面试评价细则原文引用（`source`/`scope`/`criteria` + 每条 `locator`）。
  它不是可计算实体，`kb_tools/build_graph.py` 把 61 项逐条建成 L6 参照节点，
  状态一律 `question_task_mapping_pending_review`。

## 使用约束（先读，否则会误判分）
1. **权重尚未签署**：6 套实体的 `review.status` 均为 `needs_fix`、`review.checked_by` 为 null、
   `expert_verified` 为 false，`review.pending_reasons` 记有
   `rubric_dimension_weights_pending_subject_expert` 与 `rubric_descriptor_wording_pending_subject_expert`。
   权重与档位措辞需具名教研核定，见 `审查/待复核清单.md` 第 4 节；脚本不得代签。
2. **`official_scoring` 全为 false**：本目录量规是教研按考纲口径自建的分析型量规，不是官方公布的评分细则原件；
   官方原文只在 `official_interview.json` 与 `权威资料/`。若日后录入官方细则，须同时置
   `official_scoring: true` 并补 `source_locator`，否则 Schema 拒绝。
3. **当前没有题目绑定这些实体**：`has_rubric` 边全部指向题内练习框架（`rubric.<question_id>`），
   这 6 个实体在图里是未绑定的独立标准稿。判分功能要在它们上面出分，需要教研先签署权重并建立题型绑定。
4. 历史纠正（2026-10-09，`kb_tools/ntce_rubric_contract.py`）：25 个维度曾同时带
   `name`/`levels`/`max_level` 与 A.6 字段两套真相（旧 `max_level: 3` 还与四档 `criteria_levels` 矛盾），已删除旧字段；
   6 处无署名却写死的 `expert_verified: true` 已降回 false。迁移前原值在 `归档/教资_迁移前快照_20261009/rubrics/`。
