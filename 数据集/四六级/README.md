# 四六级 RAG 知识库

> 状态：**v2 已按《应试考证功能设计与技术支撑》层级标准重构**（2026-10-02）。层级：L0 标准 → 素养 → L1 能力维度 → L2 知识点(含先修) → L3 题型 → L4 题目/资源 → L5 掌握度(模板)。质检：`manifest/stats.json`；来源映射：`manifest/ingest_log.md`。
> 来源：《英语四六级资料合集（2026年最新）》→ 本库整理，全部记录可回溯原始文件。

## 库存总览

| 库 | 文件 | 条数 | 说明 |
| --- | --- | --- | --- |
| 词汇 | `vocabulary/words_cet4.jsonl` | 4424 | 四级大纲词（含音标/释义；与六级共有词标 `CET-4/6`） |
| 词汇 | `vocabulary/words_cet6.jsonl` | 5518 | 六级大纲词 |
| 词汇 | `vocabulary/core_words.jsonl` | 3123 | 四/六级核心1500词（tier=core） |
| 词汇 | `vocabulary/phrases_highfreq.jsonl` | 1406 | 六级高频词组635 + 高频700词 + 必背200词（含近年频次） |
| 词汇 | `vocabulary/translation_topic_words.jsonl` | 8 | 翻译热点主题词（文化/科技/经济等主题分组） |
| 真题 | `questions/cet4/*.jsonl` `questions/cet6/*.jsonl` | 5294 | **126 套卷**（2015.06–2025.12，docx 108 + PDF 18）逐题拆分，答案填充 835（16%），95 条标 `needs_fix`；每题按内容细粒度挂载知识点+能力 |
| 长语料 | `passages/reading.jsonl` | 431 | 阅读文章/完形（含词库）/长篇阅读（老卷未分段已标注） |
| 写作 | `writing/model_essays.jsonl` | 177 | 真题写作题目+范文（68 条含范文全文） |
| 写作 | `writing/templates.jsonl` | 69 | 模板句（按功能分类：开头/论证/建议/结尾…）+ 人读版 md |
| 翻译 | `translation/items.jsonl` | 193 | 真题中文段落+参考译文（116 条含译文） |
| 本体 | `ontology/standards.json` `ability_nodes.jsonl` `knowledge_nodes.jsonl` `edges.jsonl` `mastery_template.json` | 48 知识点 + 28 能力 + 99 边 | L0 标准/CSE → 素养 → 能力维度 → 知识点(先修关系)；L5 掌握度模板 |
| 考试说明 | `exam_guide/cet_overview.md` | — | 题型结构/分值/时间 |

试卷覆盖：**126 套** = docx 拆题 108 套（2015.06–2024.06，含 11 套仅写作翻译的节选卷）+ PDF 拆题 18 套（2024.12 / 2025.06 / 2025.12）。节选卷经 `listening_ref`/`reading_ref` 指向同场次完整卷。**2026.6 为扫描件未拆题**（原件路径已登记）。

## 数据字典（v2，对齐需求文档 §3.3）

所有库为 JSONL。**题目记录**严格采用文档参考 schema，一行 = 一个检索原子：

```json
{
  "question_id": "cet4-2022-06-p1-reading-46",
  "exam": "CET-4",
  "module": "阅读理解",
  "question_type": "仔细阅读",
  "source": {"type": "真题", "year": "2022-06", "paper": "第一套", "verified": false,
             "origin_file": "<原始资料路径>", "analysis_file": "<解析册路径>"},
  "knowledge_node_ids": ["cet4.read.locate", "cet4.read.infer"],
  "ability_ids": ["ab.cet4.read.locate", "ab.cet4.read.infer"],
  "difficulty": null,
  "content": {"stem": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, "answer": "B"},
  "analysis": {"key_info": null, "option_compare": null, "trace_back": null, "raw": null, "status": "answer_from_key"},
  "tags": {"来源": "真题", "审核": "auto_parsed|needs_fix|checked", "版权": "internal-personal-use", "难度": null},
  "extra": {"number": 46, "group": "c1", "passage_id": "cet4-2022-06-p1-reading-p1",
            "text": "<预渲染RAG检索文本>", "review": {"status": "auto_parsed"}},
  "text": "<同 extra.text，便于RAG加载器直接使用>"
}
```

- **id 约定**：`{exam}-{年月}-p{套}-{listening|reading|writing|translation}-{题号}`（在文档示例基础上增加 p{套} 段，因四六级一考多卷必须区分）
- **层级挂载**：`knowledge_node_ids` 按题干内容细分类挂载（仔细阅读分 细节/定位/推断/主旨/态度，听力分 细节/主旨/推断），**每题 ≥1 个知识点**；`ability_ids` 由知识点经图谱边自动获得
- **资源记录**（文章/范文/翻译/模板/词汇）统一 `resource_id/resource_type/knowledge_node_ids/ability_ids/source/tags/extra`，全部挂载图谱
- **L5 掌握度**：运行时数据，schema 见 `ontology/mastery_template.json`（用户×知识点，支持 BKT/FSRS 扩展）
- **9 类标签**：考试=exam、科目=module、题型=question_type、知识点=knowledge_node_ids、能力=ability_ids、难度=difficulty(tags.难度)、来源=source.type、审核=tags.审核、版权=tags.版权

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
    meta = {"exam": r["exam"], "module": r["module"], "question_type": r["question_type"],
            "year": r["source"]["year"], "knowledge_nodes": r["knowledge_node_ids"]}
    docs.append({"id": r["question_id"], "text": r["text"], "metadata": meta})
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
