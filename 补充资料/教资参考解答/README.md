# 补充资料/教资参考解答/ —— 幼儿保教主观题的原创参考解答草稿；由 审查/build_reference_drafts.py 生成，供教资库候选答案与主题库维护器消费

## 文件清单（3 个数据文件逐个列名）

| 文件名 | 字节 | 内容与消费 |
| --- | --- | --- |
| `reference_drafts.jsonl` | 96,006 | 16 条候选解答记录、12 个 `draft_id`（4 个主题各 2 题、8 个主题各 1 题，现算）；按完整题干连接既有 `question_id`，字段为 `draft_id/question_id/expected_stem_sha256/original_stem/status/official_exam_answer/answer/scoring_points/score_note/source_files/analysis`；`status` 16/16 为 `original_reference_draft_pending_expert`、`official_exam_answer` 16/16 为 `false`、`scoring_points` 每条 4–5 点。主库 14 个 `数据集/教资/questions/youer/baojiao/*.jsonl` 里的 16 条题目经 `extra.source_repairs[].draft_file` 回指本文件（现算 16 处，另有 16 处 `analysis.draft_id`）。由 `审查/build_reference_drafts.py` 第 59–61 行写出 |
| `reference_seeds.json` | 21,198 | 手写输入，不是产物：`审查/build_reference_drafts.py` 第 16–17 行只读它。顶层键 `schema_version/source_id(moe.preschool_guideline.2012)/notice/drafts/line_convention(physical_LF)`，`drafts` 12 条，每条键 `draft_id/stems/lines/points/answer/key_info/common_error/legacy_logical_line_ranges`；理论原文行号指向 `../教资官方样题/preschool_guideline.2012.txt`。每条草稿的 `analysis.generation.seed_sha256` 记录本文件哈希（现算 `3d61120e1b3139711a0fe5792b287e87647a7f6a091cc8127bcc02271fc85b72`，与当前文件一致） |
| `summary.json` | 216 | `审查/build_reference_drafts.py` 第 62–65 行写出的 6 键摘要：`source=moe.preschool_guideline.2012`、`original_draft_topics=12`、`matched_question_records=16`、`official_exam_answers=0`、`status=draft_pending_expert`、`source_hash_verified=true`。只有布尔校验位，不保存哈希值，也没有缺口计数字段 |

本目录把教育部《3-6岁儿童学习与发展指南》的理论原则应用于完整、可在原料中定位的已有题目。内容由AI辅助编写，属于原创练习参考，未取得考试官方答案或逐点评分标准，保留待学科专家审核状态。

`reference_seeds.json` 保存12个主题的解答、判断依据、常见错误及理论原文行号。`reference_drafts.jsonl` 将完整题干精确连接到既有 `question_id`，保留原题、题干SHA-256、理论文件SHA-256和原文定位。重复卷的题目保留自己的ID，关联记录数不等于新增知识主题数。

候选内容供主题库维护器检查后采用。构建命令只写本目录两个文件，不碰 `数据集/教资/`（仓库里没有 `教资KB` 目录，旧名已废弃）；不得按题号相同、题干前缀相似或主题相同覆盖其它题目，也不得覆盖已有正式答案与人工审核内容。把草稿真正写进题目的是另一个脚本：`kb_tools/ntce_reference_import.py` 第 64 行读本文件，校验后回写 `数据集/教资/questions/youer/baojiao/*.jsonl`，并留 `数据集/教资/review/reference_draft_import.jsonl`（2,422 字节）与 `reference_draft_import_summary.json`（125 字节，现算 `{"candidates":16,"by_status":{"references_refreshed":16},"skip_reasons":{},"expert_verified":false}`）。

每条候选的 `scoring_points` 是练习反馈要点，缺少正式权重；不能按要点个数换算考试成绩。`analysis.option_compare` 在主观题中解释常见错误思路，`trace_back` 说明理论依据与应用推理。引用统一按LF物理行，定位区间另有 `context_sha256`，不将Word内的Unicode分隔符当作文件换行。生成器没有取得会话的具体模型标识，因此记录 `model_id=null` 及明确的未知状态，不伪造模型版本或专家姓名。

在仓库根目录复跑：

```powershell
python 审查/build_reference_drafts.py
```

脚本核对理论原文哈希和所有行号范围，只连接当前库内的完整题干。阅读时先看 `original_stem`，再结合 `answer` 与三段解析；需要复核依据时按 `source_files[].locator` 打开本地指南正文。案例背景不完整、含跨题混入、图像信息缺失或只剩任务代词的题目须先修复原始材料。
