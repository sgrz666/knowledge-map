# 权威考试资料与标准引用索引

本目录保存官方公开原文、可检索文本、具体要求条目及评分表，采集和核验于2026-10-03。共67项来源、6255条可定位条目，来源核验不等同于知识点映射审核、答案审核或授权商用。

## 取得的原文

| 范围 | 本地材料 |
| --- | --- |
| NTCE笔试 | 官方35份Word大纲：幼儿园/小学/中学6份公共科目，初中15份及高中14份学科大纲。覆盖13个共有学科，以及初中历史与社会、科学和高中通用技术。保留官方网站历史题名与原文，不改写为自行推定的新版本。 |
| NTCE面试 | 幼儿园、小学、中学3份面试大纲（原文署2012年5月，试行），61条官方评分细则；各学段总分均为100，项目细分分值之和与公布权重一致。 |
| NTCE考试标准 | 《中小学和幼儿园教师资格考试标准（试行）》官方Word。 |
| CET | 2016修订版官方完整大纲PDF（215页，含听读写译口语要求、写作/翻译评分及样卷、词表）、两级笔试考核内容完整表格、分数解释官网原文。大纲中的历史口试说明应结合后续口试政策使用。 |
| CSE历史版 | GF 0018—2018完整官方PDF，2018-06-01实施，已由2024版替代。 |
| CSE现行版 | GF 0018—2024官方搜索工具公开JSON数据及版本说明网页，3741条可定位描述语。2024-11-26发布、2025-03-01实施。取得的是官方在线描述语数据集，未取得完整出版物PDF。 |
| 教师职业与培养标准 | 2021年五类师范生职业能力标准、2012年三类教师专业标准、2011年教师教育课程标准、2008年师德规范、2018年职业行为十项准则、2022年强师计划。 |
| 法律法规 | 教育法2021修正、义务教育法2018修正、教师法2009修正、未成年人保护法2024修正、预防未成年人犯罪法2020修订、学前教育法2024通过（2025-06-01实施）；幼儿园工作规程、未成年人学校保护规定、教育惩戒规则。 |
| 标准编号纠正 | 国家标准全文公开平台原页证明GB/T 41671—2022是《化学纤维 溶剂残留量的测定》，不属于CSE。 |

原文件在 `originals/`，提取文本在 `text/`。Word表格另保留 `.tables.json` 的表号、行号、列号与单元格原文。Word只读打开、关闭宏、隐藏运行，原件不修改。

## 数据接口与使用

`catalog.json` 顶层为 `sources` 数组。每项具有稳定 `standard_id`，保存 `name/authority/source_url/version/effective_date/retrieved_at/local_path/text_path/sha256/text_sha256/exam_scope/verified/verification_method`；有落地页或附件时另保留 `landing_path/landing_sha256/document_url`。未知正式版本和生效日期为 `null`，网页发布日期单列 `published_date`。`verified=true` 只说明官方原文取得并核验，不能证明题目或知识点经专家复核。

`requirements.jsonl` 按物理行读取，每项具有 `requirement_id/standard_id/title/content/locator/module/subject/level/mapping_status`。NTCE要求以实际大纲条款、原文段落或子条款保存；大纲未明确的专业细节不可自行声称为其逐字条目。节点和题目引用字段使用 `exam_requirement_ids`，应以术语和内容实际匹配；没有对应证据时保持待对齐。

定位有四种：文本 `text_path + line_start/line_end`；官方Word表格 `table_path + table/row/column`；官网HTML表格 `html_path + table/row/headers`；CSE2024 `json_path + json_pointer + official_descriptor_id`。CET大纲中的去页眉整理内容标为 `content_type=source_text_with_layout_lines_removed`，`original_text` 保存其定位范围完整原文。

ID格式例如 `ntce.outline.311.r008`、`cet.syllabus.2016.r067`、`cse.gf0018-2024.r001`。增补来源不会改变已有条目ID；重建读取现有索引复用ID，并预留全部退休ID的数字。CET内容表当前有效ID为各级 `r015–r023`，未发布的错误数字条目 `r001–r014` 已废弃。NTCE正文边界复查另废弃137个误入的试卷结构/题型样例条目：304.r024–r049、309.r019–r049、404.r025–r055、407.r033–r081（前缀均为 `ntce.outline.`）；正文中的正确ID保持原值。完整清单见 `retired_requirement_ids.json`，这137条旧记录保存在 `retired_requirement_records.jsonl`，只供追踪抽取修正，不能用于通用考试要求映射。采集和索引用临时文件写完后原子替换，避免并发读到半成品。

`official_interview_rubrics.json` 为官方61条面试细则，`official_cet_rubrics.json` 为写作、翻译各5档官方总体印象评分。CET15分原始评分不得直接当作710分报道分；官方相同档次描述并不表示四六级任务和样卷难度相同。

## 缺项与边界

- 未找到可核验的CET分数或考试级别与CSE等级官方对接结果。CET-4/CET-6中的数字不等于CSE四级/六级；官网给出的初始检索学段建议也明确不是官方指导，不作为考试对接依据。
- 尚未取得CSE2024完整出版物PDF，但取得了官方在线描述语数据集及版本证据。2018原件可查历史依据，不能当成现行版。
- 公开NTCE笔试大纲包含材料分析、教学设计能力要求与题型示例，未取得跨题通用的正式逐点评分细则，也未取得全库每道真题的官方评分参考。`practice_rubrics.json` 单独给出练习用分维建议，明确 `official=false`、待专家审核，不换算为正式考试分数。
- 未成年人保护法2024人大公报PDF直接下载返回403；已实际取得国家市场监管总局官方转载2024全文，保留原失败URL及日志。其他失败和备用站尝试见 `acquisition_log.jsonl`。
- 大纲引用的历史课程标准、旧法条及原始历史卷须按题目时间与标准版本使用，不能只因官网仍发布就把所有文字认定为2026年新修订内容。

## 如何测试与复跑

从仓库根运行以下离线命令，即可核验全部来源SHA-256、条目ID唯一性和退休ID禁用、每条定位原文、35科笔试要求正文边界、CET HTML表格完整行、CSE JSON指针和面试评分权重，结果写入 `verification_report.json`：

```powershell
$taskPython = 'C:\Users\sg\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $taskPython .\权威资料\verify_sources.py
```

本次核验为67/67来源哈希有效、6255条要求定位一致、35科要求正文边界有效、61条面试细则各学段合计100、10条CET分档齐全，错误为0。CET逐项技能覆盖听力9、阅读10、写作11、翻译5、口语5，共40项；短条目也按实际原文保留，修正记录见 `cet_skill_index_changes.json`。离线重建后要求索引的SHA-256保持一致。查具体引用时，先在JSONL找到 `requirement_id`，再按 `locator` 打开本地文本、原文或JSON。

以下为全量重新获取与重建命令，会联网重新下载；Word提取需要已安装的Microsoft Word，PDF读取使用捆绑Python中的pypdf。仅写本目录。`build_index.py` 可独立离线运行。

```powershell
$taskPython = 'C:\Users\sg\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
& $taskPython .\权威资料\collect_sources.py
& $taskPython .\权威资料\prepare_extras.py
& $taskPython .\权威资料\collect_sources.py --extras
powershell -NoProfile -ExecutionPolicy Bypass -File .\权威资料\extract_word.ps1
& $taskPython .\权威资料\build_index.py
& $taskPython .\权威资料\verify_sources.py
```

原文仍可在[NTCE大纲目录](https://ntce.neea.edu.cn/xhtml1/category/1507/1099-1.htm)、[CET考试大纲](https://cet.neea.edu.cn/res/Home/1704/55b02330ac17274664f06d9d3db8249d.pdf)、[CSE现行版官方工具](https://www.neea.edu.cn/html1/folder/2503/1-1.htm)、[教育部法律栏目](https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/)复核；各来源精确URL以catalog为准。
