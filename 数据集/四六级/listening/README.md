# 数据集/四六级/listening/ —— 听力录音文字稿（648 段 JSONL），recover_listening.py 生成，题目按 transcript_id 关联、卡片与图谱 L7 消费

- 角色：听力题组的活动文字稿源；题目本身在 `questions/`，本目录只存被题目引用的原文段与音频锚点，不含独立事实。
- 生成：`scripts/recover_listening.py`（argparse `--src --kb --audit-only`；`extraction_version=4`），从全源 PDF/DOCX 文字层恢复。改数据要重跑该脚本，不手改 JSONL。
- 消费：`scripts/generate_cards.py`（把稿嵌进听力卡的「### 听力录音文本」）、`scripts/build_stats.py`（统计活动/留存稿）、`scripts/build_graph.py`（L7 听力稿节点 648）、`scripts/infer_candidate_answers.py`、`scripts/batch_upgrade_analysis.py`、`审查/validate_kb.py`（第 777 行按 `listening/transcripts.jsonl` 校验题面引用）。
- 门禁：`tests/test_cet_repair.py`（听力稿与题面引用完整性）、`审查/validate_kb.py`（transcript 引用/孤悬挂校验）。`services/knowledge/` 运行时不读此文件（题目通过 `extra.listening_transcript_ids` 已在生成阶段解析进卡片）。

## 文件清单

- `transcripts.jsonl`（6023794B, 648L，648 条记录）—— 每行一段听力稿。关键字段：`resource_id`（命名 `cet{4|6}-{YYYY-MM}-p{N}-listening-transcript-{题号区间}-{内容哈希}`，如 `cet4-2017-12-p1-listening-transcript-3-4-971df59f2ef4`）、`kind`（恒为 `listening_transcript`）、`module`、`exam`、`text`（口述原文）、`audio_ref`/`extra.audio`（音频切片：`start_seconds`/`end_seconds`/`filename`）、`extra.question_numbers`、`extra.spoken_question_candidates`（口述问题原文与绑定证据）、`extra.extraction_status`、`knowledge_node_ids`/`ability_ids`/`exam_requirement_ids`、`review.status`（648 条全为 `auto_parsed`）。活动/留存口径：`extra.extraction_status` 分两值——`current_source_extraction_pending_expert_review` 616 条（活动稿，`extra.active` 不为 False）、`superseded_text_order_retained_for_audit` 32 条（`extra.active=false`，旧 PDF 排序提取稿只留审计不作活动稿）。由 recover_listening.py 重生成，不手改。被同场次听力题通过 `extra.listening_transcript_ids` 引用。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- 活动稿 vs superseded 留存稿是两套语义：32 条 superseded 稿文本层是旧排序提取的错位结果，仅供审计，不能当活动稿喂检索或组卷；判分/召回只认 `active!=false` 的 616 条。
- 音频切片时间区间（`extra.audio`）待校对；`extraction_status` 标的是"文本层提取状态"，扫描件/损坏字体是 `extraction_failure`，不代表源不存在（依据见 `manifest/source_transcript_audit.jsonl` 与 `manifest/source_evidence/`）。
- 稿件内容全部 `pending_expert_review`（`review.status=auto_parsed`），未过专家审核前不得当 verified 原文对外。
- 生成依赖 `scripts/_staging/` 下的 OCR/文字层中间件——`_staging/` 不入库（约 734MB），删了要重新 OCR 才能重跑 recover_listening.py。
