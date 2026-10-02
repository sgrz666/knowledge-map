# Ingest Log（来源 → 产物映射）

生成时间：2026-10-02。所有脚本可复跑（幂等覆盖产物）。

## 管线脚本

| 脚本 | 输入（原始资料相对路径） | 产物 |
| --- | --- | --- |
| `scripts/build_vocab.py` | 【4】…四级/六级大纲词汇 xls（正序版）；2026年6月四级/六级1500核心词.pdf；四六级单词/{英语六级高频词组.pdf, 词汇·四六级高频700词.docx, 四六级必背200个高频词.docx, 英语四六级翻译热点词汇.docx} | vocabulary/*.jsonl |
| `scripts/build_questions.py` | 真题 docx：zip 解包（scripts/_staging/cet4|cet6，源自 2015-2021 两份合集 zip 的"真题Word版"）+ 散装 2022.06-2024.06 word 版 | questions/{cet4,cet6}/*.jsonl、passages/reading.jsonl、writing/_prompts.jsonl、translation/_from_papers.jsonl、manifest/papers.jsonl、manifest/parse_report.json |
| `scripts/build_questions_pdf.py` | 真题 PDF（仅 2024.12 / 2025.06 / 2025.12 有文本层场次） | 同上（追加合并，无 docx 冲突） |
| `scripts/fill_answers.py` | zip 解包解析册（_staging/answers）+ 散装解析册 PDF/docx + 阅读专项解析"全N套"PDF（按"第X套"切分） | 回填 questions 的 answer 字段 + manifest/answers_fill_report.json |
| `scripts/build_writing_translation.py` | 【2】写作/翻译专项的真题合集+范文合集 PDF（四/六级）+ 2025.12 作文/翻译"真题及答案"PDF + build_questions 的两个中间产物 | writing/model_essays.jsonl、translation/items.jsonl |
| `scripts/build_templates.py` | 【3】四六级作文模版（高分模板句型 docx + 石雷鹏等 5 份 PDF） | writing/templates.jsonl、writing/md/templates.md |
| `scripts/build_stats.py` | 全库 | manifest/stats.json（含去重、listening_ref 补全） |

## 未入库资产（含原因）

| 资产 | 原因 | 状态 |
| --- | --- | --- |
| 听力 MP3 ×120 | 音频不入向量库；路径可按场次在原始资料中定位 | 登记（见下方映射） |
| 四级/六级《听力原文合集》PDF | 扫描件，无文本层 | 待 OCR 补录 |
| 2026年6月真题册/解析册（三套全） | 扫描件，无文本层 | 待 OCR 补录 |
| 2016.06–2017.06 部分解析册 PDF | 字体映射损坏，文本为乱码 | 答案待 OCR/人工补录 |
| 《赠-词汇词根+联想记忆法》便携版 PDF、236个高频词汇词组.doc（老 Word 格式） | 排版复杂/老格式，性价比低 | 未处理 |
| 老版《真题解析》中按题详解文本 | 未做逐题解析切分（仅提取了答案字母） | analysis 字段待 LLM 增补 |

## 听力音频路径映射规则

音频不逐条入库。场次 → 音频目录：`【2】四六级专项题汇总/.../四级听力音频（2016-2025年6月）/YYYY年MM月四级听力音频第N套.mp3`（六级同理）。文件名即 (year, paper) 索引，Agent 可按 `questions` 记录中的 exam/year/paper 拼路径播放。特别场次：2020.07/2022.06/2022.09/2023.03 为"全1套"。

## 已知数据质量边界

- 每套卷客观题 55 题（听力25 + 阅读30）；`manifest/papers.jsonl` 的 `listening_qs/reading_qs` 与 25/30 的差异即该卷解析偏差，warnings 列明原因。
- 老卷（2015–2017）长篇阅读段落字母在 docx 转换中丢失：题目保留（陈述句=题干），文章以未分段文本入库，段落配对答案依赖解析册。
- 完形填空部分老卷空格编号丢失：题目保留（词库+文章完整），`stem` 为空。
- 答案填充率 16%（788/5056），宁可缺失不给错答案；`analysis_status=answer_from_key` 标记已填来源。

## 复核修正记录（2026-10-02 二次核对）

1. **新增 8 套节选卷**：2022.09（四六级各3套）、2023.03 p2/p3、2020.09 p3、2022.06 p3 等 docx 为"仅写作+翻译"节选卷（听阅与同场次其他套相同），已按 partial paper 解析入库并登记 ref。
2. **题号归一化**：2015.12 四级 p2 源卷仔细阅读错标 56-60，已按题型顺序重编为 26-55（cet4.r.2015-12_p2）。
3. **去重**：删除中间产物 writing/_prompts.jsonl、translation/_from_papers.jsonl（内容已并入正式库）；题库按 id 去重，全局唯一。
4. **质量标记**：178 条客观题选项数异常（老卷字母丢失/PDF 断行导致）标为 `review.status=needs_fix`，可过滤。
5. **正确性抽查结论**：词汇 300/300 与 xls 逐字一致；题干逐字命中（2022-06 四级 16/19，未命中 3 条为完形重构题干属设计内；2023-06 六级 10/10；2024-12 四级 13/13）；答案抽样人工对照解析册 4/4 正确；写作题目/翻译中文与真题册逐字一致。
