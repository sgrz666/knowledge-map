# 数据集/四六级/manifest/ —— 构建清单与流水线各阶段报告；build_stats.py 等脚本生成，审查门禁与服务读取

这里放四六级知识库构建流水线的统计数据与每一步骤的修复/诊断报告：题库解析（papers.jsonl / parse_report.json）、答案回填与 OCR（answers_fill_report.json / answers_fill_ocr_report.json）、听力与阅读恢复（listening_recovery_report.json / reading_resource_recovery_report.json）、图谱与词库统计（stats.json）、审查验收引用的幂等快照（idempotency_report.json）。
生成者主要是 `数据集/四六级/scripts/` 下的 `build_stats.py`（写 `manifest/papers.jsonl`、`manifest/stats.json`、`manifest/ingest_log.md` 与 `数据集/四六级/README.md`）、`build_questions.py`（papers/parse）、`recover_listening.py`、`recover_reading_resources.py`、`restore_original_stems.py`、`fill_answers.py` / `fill_answers_ocr.py`、`repair_kb.py`、`repair_passage_references.py`、`generate_paper_specs.py`、`build_writing_translation.py`、`scan_audio_assets.py`、`cet_difficulty.py` 及各 `diag_*.py`/`*_backfill.py`。
读取方：`services/knowledge/repository.py` 读 `paper_specs.jsonl`；`审查/build_repair_summary.py` 读 `idempotency_report.json`、`passage_reference_idempotency_report.json`；`审查/validate_kb.py` 与各 `tests/test_cet_*.py` 以 `stats.json` / `review_baseline.json` 为对账基准；`数据集/四六级/scripts/diag_*.py`、`gen_alignment_report.py`、`verify_source_trust.py` 等互为读/写 `answer_source_inventory.json`、`source_trust_report.json`。
改动需过的门禁：`tests/test_cet_eight_layer_contract.py`、`tests/test_cet_repair.py`、`tests/test_cet_passage_references.py`、`tests/test_cet_official_examples.py`、`审查/validate_kb.py`、`tests/test_status_vocabulary.py`。
本目录 `README.md` 为手维护文件（不是 build_stats.py 产物；build_stats.py 的产物是 `数据集/四六级/README.md`，绝对不可手改）。`*.log` 与 `source_evidence/` 之外的 JSON/JSONL 报告均入 git；`*.log` 被 `.gitignore` 第 28 行 `数据集/**/*.log` 忽略，是执行时的控制台捕获，非门禁读取项。

## 文件清单（63 个数据/日志文件逐个列出；行数用 `wc -l` 现算，2026-10-09）

### 试卷/题库解析类
- `_ocr_eval.json`（1050001B, 8180L）—— OCR 文字层与原 PDF 的一致性评测明细；由 `ocr_backfill.py` 写；harness 产物，重跑脚本覆盖。
- `_scan_classify.json`（66142B, 1808L）—— 源 PDF 分类（可解码 / 扫描件 / 字体损坏）扫描结果；由 `scan_classify.py` 写；注意 `数据集/数据集/四六级/manifest/` 下有一份 135B 的空跑副本（见该处说明）。
- `papers.jsonl`（46058B, 126L）—— 126 套试卷的解析清单，字段 exam/year/paper/listening_qs/reading_qs/has_writing/has_translation/has_passages/warnings/source_file/parse/paper_id/reading_ref（47 行带 listening_ref）；由 `build_questions.py` 初次写、`build_stats.py`（第 70 行）重生成；手改无效，重跑覆盖。
- `parse_report.json`（16903B, 804L）—— `build_questions.py` 的逐卷解析告警/缺口记录；由 `build_questions.py` 写；诊断快照。
- `paper_specs.jsonl`（616342B, 126L）—— 逐卷规格（题型/题号区间/材料绑定）；由 `generate_paper_specs.py` 写，`services/knowledge/repository.py` 读取；是服务侧消费的关键清单，改动须与题库一致。
- `original_stem_recovery_report.json`（781B, 26L）—— 原始题干恢复（PDF 文本层→活动稿）计数；由 `restore_original_stems.py` 写、`build_stats.py` 汇总读取。
- `listening_recovery_report.json`（603B, 18L）—— 听力文本恢复计数；由 `recover_listening.py` 写、`build_stats.py` 读。
- `reading_resource_recovery_report.json`（669B, 20L）—— 阅读段落资源恢复计数；由 `recover_reading_resources.py` 写、`build_stats.py` 读。
- `source_transcript_audit.jsonl`（3357428B, 753L）—— 逐源听力转写审计，标注 `extraction_status`（损坏文字层=提取失败，不代表源缺失）；由 `recover_listening.py` 写、`build_stats.py` 读；活动稿/留存稿口径的依据。

### 答案回填/校正类
- `answer_source_inventory.json`（168490B, 3752L）—— 答案来源全量清单；由 `diagnose_answer_sources.py` 写，被 `diag_align.py`/`diag_fingerprint.py`/`diag_offset.py`/`verify_source_trust.py`/`explainer_answer_extract.py`/`gen_alignment_report.py`/`backfill_answers.py`/`scan_explainer_sources.py` 读取；流水线内部对账核心。
- `answers_fill_report.json`（195989B, 3615L）—— 解析式答案回填逐题结果；由 `fill_answers.py` 写、`build_stats.py` 读。
- `answers_fill_ocr_report.json`（386419B, 9122L）—— OCR 补答案逐卷结果与剩余缺口；由 `fill_answers_ocr.py` 写、`build_stats.py` 读；证据分级（level_a/level_b/印刷答案表）记录在此，全部 pending_expert_review。
- `answer_backfill_report.json`（29474B, 698L）—— 批量答案回填结果；由 `backfill_answers.py` 写。
- `answer_correction_report.json`（7748B, 353L）—— 错位答案校正记录（保留原值，可回滚）；由 `correct_misaligned_answers.py` 写。
- `analysis_answer_backfill.json`（5084B, 278L）—— 从解析文本抽答案的结果；由 `extract_answers_from_analysis.py` 写。
- `ocr_extract_backfill.json`（11630B, 449L）—— OCR 文本层回填；由 `ocr_text_backfill.py` 写。
- `ocr_key_backfill_report.json`（89632B, 3750L）—— OCR 关键答案回填逐条结果；由 `ocr_key_backfill.py` 写。
- `alignment_backfill_report.json`（18500B, 885L）—— 题号对齐回填报告；由 `gen_alignment_report.py` 写。
- `longpassage_answer_quarantine.json`（10251B, 773L）—— 长篇阅读答案隔离记录（隔离不删除，保留原值）；由 `quarantine_longpassage_answers.py` 写。
- `placeholder_answer_quarantine.json`（6209B, 274L）—— 占位/伪答案隔离记录；由 `quarantine_placeholder_answers.py` 写。

### 诊断/评测类
- `fingerprint_diagnosis.json`（6892B, 527L）—— 答案指纹错位诊断；由 `diag_fingerprint.py` 写、`gen_alignment_report.py` 读。
- `offset_diagnosis.json`（10880B, 865L）—— 题号偏移诊断；由 `diag_offset.py` 写、`gen_alignment_report.py` 读。
- `explainer_answer_feasibility.json`（18300B, 891L）—— 从讲义抽答案可行性评估；由 `explainer_answer_extract.py` 写。
- `explainer_source_scan.json`（6945B, 143L）—— 讲义来源扫描；由 `scan_explainer_sources.py` 写、`correct_misaligned_answers.py` 读。
- `source_trust_report.json`（22610B, 930L）—— 来源可信度分级（≥0.95 一致性阈值，低于即隔离）；由 `verify_source_trust.py` 写，`diag_fingerprint.py`/`diag_offset.py`/`gen_alignment_report.py` 读。
- `audio_catalog.json`（69618B, 1205L）—— 音频资产清单（total_audio_files 120、mapped_paper_slots 102）；由 `scan_audio_assets.py` 写；听力 audio_ref 的溯源。
- `backfill_feasibility.json`（1269B, 41L）—— 官方解析册回填答案的可行性一次评估：`method` 描述"文本层提取＋坐标分栏＋反向校验一致率≥0.95 判 trusted"，`by_status` 分 trusted/distrusted/unverified/no_readable_source 四档（各带 papers/new_answer_available/checked/agree），`remaining_gap`（questions_total 5340 / missing_answer 1831 / missing_analysis 2934）、`blocking_reasons`（50 份 broken_font＋12 份 image_only 需 OCR；21 套题号口径不一致）、`safe_to_fill_now=12`；`generated=2026-10-07`。repo 内无脚本写入此文件名、亦无脚本读取；一次性诊断留存，未被任何门禁引用（与 `answers_full_volume_rescan` 那轮人工分析同期）。

### 难度/图谱/统计类
- `cet_difficulty_report.json`（2799B, 113L）—— 难度分布，calibration=heuristic、status=pending_calibration；由 `cet_difficulty.py` 写；difficulty=null 无实测校准的依据。
- `stats.json`（8500B, 251L）—— 全库统计快照，含 generated/counting_rules/questions/resources/vocabulary/passages/listening/writing/translation/ontology/remaining_gaps/quality；由 `build_stats.py` 写（第 148–149 行）、`build_graph.py` 读；counting_rules 明确“未取得作答样本和专家校准，不生成虚假 difficulty”。
- `ingest_log.md`（4771B, 35L）—— 人类可读入库日志；由 `build_stats.py` 写（第 246 行）。
- `repair_report.json`（9833B, 160L）—— `repair_kb.py` 修复结果（隔离/待核计数）；由 `repair_kb.py` 写、`build_stats.py`/`repair_passage_references.py` 读。
- `review_baseline.json`（219608B, 5300L）—— 审查基线快照（source/question_count/with_answer/question_answers）；由 `repair_kb.py` 写、`build_stats.py` 读；净变化对账基准。
- `passage_reference_repair_report.json`（256037B, 7837L）—— 段落引用修复逐条结果；由 `repair_passage_references.py` 写、`build_stats.py` 读。
- `writing_translation_extract_report.json`（17563B, 329L）—— 写作/翻译抽取结果；由 `build_writing_translation.py` 写。
- `task_source_bindings.jsonl`（1477B, 1L）—— 写作/翻译题与原文锚点绑定（from_task/to_task/field/source/text_anchor/binding_evidence）；由 `build_writing_translation.py` 写、`build_stats.py` 读。

### 幂等/验收快照（无写入脚本，人工一次性捕获）
- `idempotency_before.json`（15666B, 150L）—— 幂等重跑前的产物 SHA 快照；repo 内无写入脚本、无外部读取者；一次性诊断留存，未被任何门禁读取。
- `baseline_text_preservation.json`（672B, 19L）—— 内容保全对账：`method`=比较完整基线字符串与当前活动 content 及嵌套保全历史，`files` 逐条记 writing/model_essays.jsonl、translation/items.jsonl、vocabulary/phrases_highfreq.jsonl 的 `baseline_records`/`baseline_content_fields`（各 177/193/1406）与 `fields_without_exact_preserved_string: []`（证明无原文被丢弃）。repo 内无脚本写入此文件名、亦无脚本读取；一次性核验留存，未被任何门禁引用。
- `idempotency_diagnostic_before.json`（2125008B, 1 行无换行符，`wc -l`=0）—— 指定题文件的幂等诊断前像；无写入脚本、无读取者；一次性留存，未被任何门禁读取。
- `idempotency_report.json`（1688B, 39L）—— 幂等重跑对比结论（command/business_artifacts_compared/changed_artifacts/passed 等）；repo 内无写入脚本，由 `审查/build_repair_summary.py` 读取并引用；验收门禁证据项。
- `passage_reference_idempotency_before.json`（15786B, 151L）—— 段落引用幂等重跑前快照；无写入脚本、无外部读取者；一次性留存，未被任何门禁读取。
- `passage_reference_idempotency_report.json`（16876B, 173L）—— 段落引用幂等重跑结论；无写入脚本，由 `审查/build_repair_summary.py` 读取并引用；验收门禁证据项。

### 控制台执行日志（22 个，`*.log`；被 `.gitignore:28 数据集/**/*.log` 忽略、未入 git、非门禁读取）
- `answers_full_volume_rescan.log`（171B, 1L）—— 全量重扫答案的命令输出捕获。
- `build_stats_last_run.log`（3659B, 116L）—— `build_stats.py` 末次运行输出。
- `build_writing_translation_last_run.log`（238B, 1L）—— `build_writing_translation.py` 末次运行输出。
- `migrate_last_run.log`（326B, 8L）—— `migrate_v2_schema.py` 末次运行输出。
- `passage_reference_idempotency_run_1_build_stats.py.log`（3659B, 116L）—— 幂等验证第 1 轮 build_stats 输出。
- `passage_reference_idempotency_run_1_repair_kb.py.log`（10161B, 169L）—— 第 1 轮 repair_kb 输出。
- `passage_reference_idempotency_run_2_build_stats.py.log`（3659B, 116L）—— 第 2 轮 build_stats 输出。
- `passage_reference_idempotency_run_2_repair_kb.py.log`（10161B, 169L）—— 第 2 轮 repair_kb 输出。
- `rebuild_final_source_guard.log`（14739B, 291L）—— rebuild 末次源守卫运行输出。
- `rebuild_freeze.log`（4652B, 63L）—— 冻结式 rebuild 输出。
- `rebuild_freeze_retry.log`（18894B, 356L）—— 冻结 rebuild 重试输出。
- `rebuild_idempotency.log`（17762B, 329L）—— rebuild 幂等验证输出。
- `rebuild_idempotency_final.log`（18818B, 354L）—— rebuild 幂等最终验证输出。
- `rebuild_idempotency_fixed_1.log`（18817B, 354L）—— 修正后 rebuild 幂等第 1 轮输出。
- `rebuild_idempotency_fixed_2.log`（5183B, 77L）—— 修正后 rebuild 幂等第 2 轮输出。
- `rebuild_identity_and_transcripts.log`（17994B, 335L）—— ID 保真与转写重建 rebuild 输出。
- `rebuild_last_run.log`（17762B, 329L）—— rebuild 末次运行输出。
- `rebuild_native_numbering.log`（17941B, 335L）—— 原生题号重建 rebuild 输出。
- `rebuild_stable.log`（14587B, 288L）—— 稳定化 rebuild 输出。
- `repair_kb_last_run.log`（10055B, 167L）—— `repair_kb.py` 末次运行输出。
- `source_transcript_audit_run.log`（246B, 1L）—— 转写审计任务运行输出。
- `word_numbering_reparse.log`（1210B, 19L）—— 词汇编号重解析输出。

### 子目录
- `source_evidence/`（3 个文件，入 git）—— 视觉证据目录，不在其中新建文件：
  - `cet4-2016-font-failure-page-2.png`（260888B）—— 2016-06 四级第 2 页字体损坏渲染图。
  - `cet4-2022-12-p3-answer-page-1.png`（571963B）—— 2022-12 三级套答案页渲染图。
  - `font_failure_locator.json`（602B, 8L 现算，含末行）—— 定位元数据：path / page / rendered_path / extraction_status=`extraction_failure_font_mapping` / expert_review_status=pending / visual_observation / visual_review_method；说明乱码文字层属“提取失败”而非“源缺失”。

## 口径备注
- 三层状态：`answer_status`（verified/letter_only/reference_only/missing/source_conflict）、`review.status`（六态）、`difficulty`（heuristic、pending_calibration）互不等价；本目录报告分别记录其来源。
- `source_conflict` ⇒ `review.status=quarantined` 且 `content.answer=null`；隔离记录（quarantine_*.json）保留原值、可回滚，隔离历史不生效于判分。
- 待专家审核：OCR 补答与源编号恢复均为 pending_expert_review，非 verified。
- 历史不生效：`*_before.json` / `*_diagnostic_before.json` 是一次性幂等前像，不重跑、不参与当前判分。
