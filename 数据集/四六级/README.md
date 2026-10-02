# 四六级 RAG 知识库

> 状态：**v1 已构建**（2026-10-02）。设计文档：`_方案_知识库设计与格式.md`；质检统计：`manifest/stats.json`；来源映射：`manifest/ingest_log.md`。
> 来源：《英语四六级资料合集（2026年最新）》→ 本库整理，全部记录可回溯原始文件。

## 库存总览

| 库 | 文件 | 条数 | 说明 |
| --- | --- | --- | --- |
| 词汇 | `vocabulary/words_cet4.jsonl` | 4424 | 四级大纲词（含音标/释义；与六级共有词标 `CET-4/6`） |
| 词汇 | `vocabulary/words_cet6.jsonl` | 5518 | 六级大纲词 |
| 词汇 | `vocabulary/core_words.jsonl` | 3123 | 四/六级核心1500词（tier=core） |
| 词汇 | `vocabulary/phrases_highfreq.jsonl` | 1406 | 六级高频词组635 + 高频700词 + 必背200词（含近年频次） |
| 词汇 | `vocabulary/translation_topic_words.jsonl` | 8 | 翻译热点主题词（文化/科技/经济等主题分组） |
| 真题 | `questions/cet4/*.jsonl` `questions/cet6/*.jsonl` | 5294 | 108 套卷（2015.06–2025.12）逐题拆分，客观题答案填充 835（16%），178 条选项不完整已标 `needs_fix` |
| 长语料 | `passages/reading.jsonl` | 431 | 阅读文章/完形（含词库）/长篇阅读（老卷未分段已标注） |
| 写作 | `writing/model_essays.jsonl` | 177 | 真题写作题目+范文（68 条含范文全文） |
| 写作 | `writing/templates.jsonl` | 69 | 模板句（按功能分类：开头/论证/建议/结尾…）+ 人读版 md |
| 翻译 | `translation/items.jsonl` | 193 | 真题中文段落+参考译文（116 条含译文） |
| 本体 | `ontology/exam_tree.json` `knowledge_nodes.jsonl` | 46 节点 | 考试→模块→题型；知识点含先修关系/CSE 等级 |
| 考试说明 | `exam_guide/cet_overview.md` | — | 题型结构/分值/时间 |

试卷覆盖：108 套 = docx 拆题 90 套（2015.06–2024.06，含 11 套只含写作翻译的节选卷）+ PDF 拆题 18 套（2024.12 / 2025.06 / 2025.12）。47 套达到完整 25听力+30阅读；节选卷经 `listening_ref`/`reading_ref` 指向同场次完整卷；其余差异见 `manifest/papers.jsonl` 的 warnings。**2026.6 为扫描件未拆题**（原件路径已登记）。

## 数据字典

所有库为 JSONL（每行一条 JSON = 一个检索原子/chunk）。通用字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 全局唯一，`{exam小写}.{module}.{年月}_p{套}.{序号}`，如 `cet6.r.2022-06_p1.q46` |
| `exam` | `CET-4` / `CET-6` |
| `year` / `paper` | 考试年月（`2022-06`）/ 套数 1-3 |
| `text` | 预渲染检索文本（含元信息前缀），**embedding 直接用此字段** |
| `source.origin_file` | 原始资料路径，可回溯 |
| `review.status` | `auto_parsed`（未人工复核）；题目另有 `analysis_status=answer_from_key` 表示答案来自解析册 |

题目专用：`module`（听力/阅读）、`question_type`（短篇新闻/长对话/听力篇章/讲座讲话/选词填空/长篇阅读/仔细阅读）、`number`(1-55)、`stem/options/answer`、`passage_id`（关联文章）、`knowledge_nodes`（自动挂载的 L3 知识点）、`group`（题组）。词汇专用：`word/phonetic/pos_meaning/tier/cse_level`。

> 第2/3套卷听力常与第1套相同（实考共享），未重复入库：`manifest/papers.jsonl` 用 `listening_ref` 指向同场次含听力的卷。

## 检索约定

- 1 记录 = 1 chunk，不二次切分；题目 chunk 自含题干+选项+答案
- 混合检索：向量（`text`）+ metadata 过滤（exam/year/module/question_type/tier）；查词走 jsonl 精确查询
- 建议给 Agent 配 5 个检索工具：`查词(word)`、`搜题(过滤条件)`、`取文章(id)`、`找范文(主题/年份)`、`知识树(节点)`

### JSONL → 向量库 ingest 示例

```python
import json
docs = []
for line in open("questions/cet6/2024-06_p1.jsonl", encoding="utf-8"):
    r = json.loads(line)
    meta = {k: r[k] for k in ("exam","year","paper","module","question_type","knowledge_nodes") if r.get(k) is not None}
    docs.append({"id": r["id"], "text": r["text"], "metadata": meta})
# 之后按所用框架写入 FAISS / Milvus / Dify 知识库等
```

## 已知限制（详见 manifest/stats.json → not_ingested）

1. 听力原文合集、2026.6 真题/解析册为扫描件 → 待 OCR 补录
2. 2016.06–2017.06 部分解析册字体损坏 → 这些年份答案缺失较多
3. 逐题文字解析（key_info/trace_back）未做切分 → 待 LLM 增补
4. 老卷长篇阅读段落字母丢失 → 文章未分段（已标注），配对答案依赖解析册

## 复跑

```bash
python scripts/build_vocab.py --src <资料根> --out <KB>/vocabulary
python scripts/build_questions.py --src <资料根> --stage scripts/_staging --kb <KB>
python scripts/build_questions_pdf.py --src <资料根> --kb <KB>
python scripts/fill_answers.py --stage scripts/_staging/answers --src <资料根> --kb <KB>
python scripts/build_writing_translation.py --src <资料根> --kb <KB>
python scripts/build_templates.py --src <资料根> --kb <KB>
python scripts/build_stats.py --kb <KB>
```

> 注：
> - 本仓库远端：https://github.com/sgrz666/knowledge-map.git（真题文本为个人学习整理，建议仓库保持私有）
> - 范文/译文覆盖不全系源文件所致：四六级《写作/翻译范文》合集 PDF 仅收录 2015–2023 各 12 月场次及 2024.06、2025.06
