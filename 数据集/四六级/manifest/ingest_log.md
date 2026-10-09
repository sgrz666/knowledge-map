# CET 来源与构建记录

本文件由 `scripts/build_stats.py` 随当前全库生成。统计日期 2026-10-09；题目 5632，答案 1577，原文逐题解析 652。运行增量合并保留原文本、人工字段与隔离历史；不再使用旧版“幂等覆盖”方式。

| 管线 | 输入 | 产物与证据 |
| --- | --- | --- |
| build_vocab.py | 本地词汇 XLS/PDF/DOCX | vocabulary/*.jsonl，原文件与文本锚点 |
| build_questions.py | 归档内 DOCX 和独立 DOCX | questions、reading passages、写译中间资料、paper/parse manifests |
| build_questions_pdf.py | 2024.12、2025.06、2025.12 有文本层试卷 | 增量题目/语篇；原有字段优先保留 |
| build_writing_translation.py | 写译专项真题/参考 PDF、组合答案 PDF、已收录试卷 | 完整题目边界；候选原文、PDF 页码/区间；错误页眉与混入页脚隔离历史 |
| build_templates.py | 模板 DOCX/PDF | 功能标签、原文件和文本锚点 |
| migrate_v2_schema.py | 全库原有与新增资料 | v2 字段、题型细粒度知识/能力；Unicode 物理行安全 |
| docx_source.py | 原 Word 编号 XML、正文及表格 | 可见题号/选项字母，多级重启和精确段落定位 |
| restore_original_stems.py / recover_reading_resources.py | 独立原题的完整编号块和显式标签 | 原匹配陈述、仔细阅读提问、A-O词库和字母段落；无法唯一恢复则保留缺口 |
| recover_listening.py | 全源 PDF/DOCX | source_transcript_audit、listening/transcripts、严格问题/选项唯一绑定；旧排序稿停用留存 |
| fill_answers.py | 解析册/参考答案 DOCX/PDF | 明确源答案和逐题原文解析；冲突/旧误抽答案隔离；source_diagnostics |
| fill_answers_ocr.py + ocr_batch.ps1 | 文本层损坏/双栏排版的解析 PDF(Windows OCR zh-Hans-CN,200dpi,结果缓存在 scripts/_staging/ocr_cache) | OCR 重建文本后按证据分级绑定(level_a 题干/选项命中、level_b 专用册+题号交叉核验或整册对齐、印刷答案表)；全部 pending_expert_review；报告 manifest/answers_fill_ocr_report.json |
| repair_kb.py | 本地完整文件、权威资料 catalog/requirements/rubrics | 精确路径、官方要求、学习映射、音频题组、待审与版权状态 |
| build_stats.py | 所有正式 JSONL | stats、README、本来源记录；保留全部缺陷计数 |

本次相对基线：保留全部5294基线ID，新增行 338（停用伪题 4，其余待专家确认）；新增空白题答案 769，隔离原有答案 27，净变化 742。活动原文解析 652，完整三段解析 292；旧错关联解析保存在 analysis_history，不计入活动解析。当前数值以 stats 为准。

当前学习资源唯一 ID 15936，重复 ID 0。写作题目 146/146、范文 146/146；翻译原文 146/146、译文 146/146。所有旧混入文本保存在 history/_legacy_text 或完整候选引用中。

仍需处理：答案 4055，原文解析 4980，完整三段解析 5340；选项与词库、匹配段落字母缺口见 stats.remaining_gaps。写作 2022.12 CET4 第三套范文在源专项册中重复标“第二套”，已按独立第三套答案册首页的卷首身份、完整范文和标题纠正关联，证据见 task_source_bindings.jsonl 与 source_evidence，继续待专家复核。

确切音频已关联 1648/1969 道听力题；缺确切音频 321。整卷 MP3 的关联不代表题组起止时间已校对；只有纸面选项、没有口述稿时继续列为内容缺口。源明确共用音频说明存 binding_evidence，不猜跨卷替代。

2026.06 试卷和部分解析册是扫描件或损坏字体，需 OCR/人工转录；逐文件名单见 answers_fill_report.source_diagnostics。2024.06 CET4 原题有文本层，但旧 PDF 生成器遗漏该场次，列排版/题号/选项完整性仍需修正；写译任务已从专项与原题独立恢复，未添加残缺客观题冒充整卷。

2015 标题资料包含现代新闻听力指令，原始来源真实性和历史题型仍待确认，见 repair_report.historical_source_papers_pending_authentication。CSE GF0018-2024 现行、2018 历史版均保留；CET 数字不充当 CSE 等级。官方样卷由独立补充目录维护，不覆盖历年题库。

专家审核、难度校准与版权确认仍待完成；题目授权未知 5632 条，学习资源授权未知 15936 条。目录标签“大纲词汇”仅为本地来源命名，尚未鉴定为官方词汇表。先修边也继续标 proposed_pending_subject_expert。

复跑：在仓库根执行 `python 数据集/四六级/scripts/rebuild.py --extract`；测试 `python -m unittest discover -s tests -p test_cet_repair.py`，再执行 `python 审查/validate_kb.py`。
