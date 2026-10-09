# 四六级知识库

已修复 v2 迁移、重复资源与来源指针，并接入官方 CET 2016 大纲和题型表。全库仍是待教研审核的学习资料，未宣称已完成专家审核、难度校准或 CET/CSE 等级对接。

统计日期：2026-10-09；实际口径见 `manifest/stats.json`，所有缺陷记录计入总数。

| 数据 | 当前数量 | 内容覆盖 |
| --- | ---: | --- |
| 客观题 | 5632 | 答案 1577，原始逐题解析 652 |
| 阅读语篇 | 449 | 独立资源 ID |
| 听力文字稿 | 648 | 当前源提取 616，唯一绑定题目 20 |
| 写作任务 | 146 | 范文 146，题目 146 |
| 翻译任务 | 146 | 译文 146，中文原文 146 |
| 写作模板 | 69 | 功能标签与原始文件引用 |
| 知识点 / 能力 | 48 / 28 | 官方要求 ID、原文定位与初标方法 |
| 主观题量规 | 2 | 官方整体印象五档评分，原始分 1–15 |

基线 5294 个题目 ID 全部保留（缺失 0）。新增保留记录 338，其中 4 条是原解析器的伪题，已停用且不可判分；其余 334 条源编号恢复记录仍待专家确认，不能将新增行数称为已核定真题数量。全量 5632 条，活动源题记录 5628 条。

较审查基线 835 个答案、0 条解析，原来空白的题目新增答案 769，原有答案隔离 27，答案净变化 742，活动原始解析新增 652。现有答案中 0 条有本次明确源答案支持、1577 条仍为历史来源待核；全部保留待专家审核状态。此前过宽规则生成的字母与错误题号关联的解析已撤回；旧解析完整保存在 189 条题目的 `extra.analysis_history`，不计为可用解析。重复资源 ID 为 0；不丢文本，重复内容合并，释义不同的词条保留稳定 variant ID。

题目读取 `question_id/exam/module/question_type/content/analysis/knowledge_node_ids/ability_ids/exam_requirement_ids`。答案在 `content.answer`；原始解析在 `analysis.raw`，提取方法、定位、状态同时保留。未从来源得到的三段解析仍为空，不把知识点标签或占位文案计为解析。

三层状态分离与教资共用同一张词表（单一权威 Schema 目录是 `数据集/教资/schemas/`，四六级不放副本）：`review.status` 六态、`content.answer_status` 五态且必填、抽取形状只留在 `extra.answer_provenance` 供教研取证；审核人键统一为 `review.checked_by`/`review.checked_at`（历史 `reviewed_by`/`reviewed_at` 由 `scripts/migrate_v2_schema.py` 合并），无署名的 `checked`/`expert_reviewed` 一律降回 `needs_fix`，`answer_status = source_conflict` 的题目一律 `review.status = quarantined` 且 `content.answer = null`。图谱侧 `graph/nodes.jsonl` 只保留规范 §3.2 的 L0–L7 一套 `layer`，`graph/edges.jsonl` 的 `assesses`/`supports_ability`/`aligned_to_requirement` 一律"支撑方 → 被支撑方"（知识点/能力/条款 → 题目），与教资同向，由 `tests/test_graph_direction_contract.py` 逐条校验。

资源读取 `resource_id/text/extra`。范文在 `extra.model_essay`，译文在 `extra.reference`。写译任务另有 `task_id/task_type/content.prompt/content.reference_answer/rubric_id/task_constraints`；量规见 `ontology/scoring_rubrics.jsonl`。评分先选择官方档次，再在该档分值范围内提出练习建议；维度反馈不冒充官方加权分数，正式评分仍需当次样卷与训练过的阅卷员。

语篇引用通过原卷内完整题干、全部选项（匹配题为完整陈述）及明确语篇边界核对。此次修复原有 23 个双向引用错误：19 条恢复题补齐经原文证明的反向关联，4 条停用伪题的活动关联撤回。另将同卷核验发现的 9 条混合题干/选项记录撤回活动语篇关联，并标为 `source_identity_review.status=pending/scoring_eligible=false`；原 ID、全文及旧关联完整保留。详见 `manifest/passage_reference_repair_report.json`。保留 ID 与 `extra.number` 是历史解析身份，不能据此推断原题号；经内容唯一证明的原题号在 `extra.source_question_number`。2015-12 第 2 套 reading-51 实际对应源题号 46，源卷提示 56–60 与实际编号 46–50 冲突已显式留存，历年原卷认证仍待核。

同次全文核验在这 5 份既有源卷内恢复了 6 份完整语篇：5 份移除正文尾部混入的题干/选项，1 份补齐截短的文章后半段。旧正文完整保存在 `extra.text_history`，恢复正文在原卷中有明确起止定位。全文、匹配段落字母及完整题干/选项均需等值核验；规范化只处理排版空白、全角 ASCII 与等价引号，保留英文词界、数字小数点及其他标点符号。

`source.files` 是结构化多来源入口，每项含仓库根相对 `path/role/locator`；兼容 `source.origin_file` 仅保留首个原文件，旧值在 `_legacy_origin_file`。解析引用含 PDF 页码或 DOCX 正文块/表格行及题号。词汇与模板保留文本锚点；不会把包含省略号的旧指针当完整路径。

版权状态在 `source.copyright`，未知授权明确为 `authorization_status=unknown`；权利人、允许用途、有效期没有证据时保持空值。存在这些字段不代表已取得使用授权。

官方要求通过 `exam_requirement_ids` 对接仓库根 `权威资料/requirements.jsonl`，`requirement_mappings` 保存官方原文定位、来源 URL、初标方法和待专家审核状态。`source.verified` 与 `extra.content_review.expert_review` 分开；脚本不会生成专家姓名、审核日期或“已审核”。CSE 当前与历史版本均记录在 `ontology/standards.json`，原先把 CET 4/6 直接换成 CSE 4/5 的数值已移到历史初标字段。

图谱先修提议使用 `rel=prerequisite_candidate/proposed_rel=prereq_of/active=false`；知识点的待审列表保存在 `candidate_prereq`，正式 `prereq` 保持空值。学习路径只能使用专家核定且激活的正式先修边。

听力文字稿入口是 `listening/transcripts.jsonl`；题目通过 `extra.listening_transcript_ids` 关联题组，通过 `extra.spoken_question_source` 保存口述问题原文与绑定证据。原文存在但文本层损坏的来源标为提取失败，见 `manifest/source_transcript_audit.jsonl`，不能当成来源缺失。旧 PDF 排序提取的 32 条稿只保留审计，不作为活动稿使用。

听力题组引用 `extra.audio.files` 中的原 MP3，题组 ID 供播放器组织播放；`start_seconds/end_seconds=null` 表示尚未校对片段。只有纸面选项的记录通过 `extra.question_prompt_availability` 记录口述题目可用性；整卷音频有 1648 题关联，仍有 321 题缺少确切音频，口述问题未恢复 1949 题。2015 年资料标题与现代听力题型冲突，历史适用版本通过 `extra.exam_design_applicability` 明确待核验，2016 官方技能只作为学习映射依据。`difficulty=null` 和 `difficulty_metadata.status=pending_calibration` 表示无实测校准，不能据此运行 IRT 诊断。

仍缺答案 4055、逐题解析 4980、完整三段解析 5340；匹配陈述缺失 784，仔细阅读提问缺失 52。待专家审核 5632，待难度校准 4014。其余选项、词库、段落字母、音频缺口完整列在 `manifest/stats.json.remaining_gaps`；原文恢复及剩余边界问题见 `manifest/original_stem_recovery_report.json`、`manifest/reading_resource_recovery_report.json`；扫描件与字体损坏来源清单见 `manifest/answers_fill_report.json.source_diagnostics`。2026-10-06 起由 `fill_answers_ocr.py` 以 Windows OCR 重建损坏源文本并补绑答案/解析(证据分级、全部待审),逐卷结果与剩余缺口见 `manifest/answers_fill_ocr_report.json`。

在仓库根使用 Python 运行以下命令（需要 `pymupdf/python-docx/pandas/xlrd`）：

```powershell
python .\数据集\四六级\scripts\migrate_v2_schema.py
python .\数据集\四六级\scripts\fill_answers.py --src '英语四六级资料合集（2026年最新）(1)' --stage '数据集\四六级\scripts\_staging\answers' --kb '数据集\四六级'
python .\数据集\四六级\scripts\repair_kb.py
python .\数据集\四六级\scripts\build_stats.py --kb '数据集\四六级'
python -m unittest discover -s tests -p test_cet_repair.py
python .\审查\validate_kb.py
```

基础生成器使用增量合并，保留 v2 答案、审核及扩展字段。新增原始资料后可运行 `scripts/rebuild.py --extract` 完整重建，再检查统计与统一验收结果。只做当前数据修复时运行 `scripts/rebuild.py`。系统无 Python 时可把 `python` 换为 Codex 内置运行时 `C:\Users\sg\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。

使用时先按知识点/题型检索，打开 `content` 与共享 `extra.passage_id`，检查原始答案和解析来源。自动判分应排除 `extra.active=false`、`extra.scoring_eligible=false`、来源冲突、缺答案和选项不完整记录；面向正式用户的发布仍需内容专家审核。保留全库用于修订和检索，不以发布筛选掩盖剩余缺口。
