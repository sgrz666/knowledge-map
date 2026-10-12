# 官方权威资料/ —— 存放官方公开原文、抽取文本与考试要求条款索引；由本目录抓取/建索引脚本生成，被数据集/教资与数据集/四六级两库消费

这里是整个仓库的"官方证据层"：交付库 `数据集/四六级/` 全部 5,632 条题目和 `数据集/教资/` 14,500 条题目中的 10,572 条都带 `exam_requirement_ids`，这些 ID 逐条落到本目录 `requirements.jsonl` 的 6,255 行条款上；`数据集/教资/questions/` 里另有 5 处 `source.files[].path` 直接写 `权威资料/originals/law.teacher.2009.html`。所有 `locator.*_path` 和 `catalog.json` 的 `local_path/text_path/landing_path` 都以 **`权威资料/` 为写死前缀**——那是工作区根指向本目录的符号链接（见根目录 `ls -l`：`权威资料 -> 官方权威资料`），`verify_sources.py`、`build_index.py`、`审查/validate_kb.py` 也都经该链接拼路径，链接缺失时核验直接失败。`originals/` 的 123 份原件（html/doc/docx/pdf/json/js）只做哈希核验与再抽取的原料，不进入向量库/知识库；进检索面的是 `text/` 的抽取文本。写本目录文件一律用真实目录名 `官方权威资料/…`，不得经 `权威资料/` 链接写。

# 权威考试资料与标准引用索引

本目录保存官方公开原文、可检索文本、具体要求条目及评分表，采集和核验于2026-10-03。共67项来源、6255条可定位条目，来源核验不等同于知识点映射审核、答案审核或授权商用。

## 文件清单（顶层 18 个文件 + text/、originals/ 两个子目录 + __pycache__/）

| 文件 | 作用 | 现算规模 |
| --- | --- | --- |
| `catalog.json` | 来源登记表（schema_version 1.0，generated_at 2026-10-03T14:59:42Z）：`sources` 数组每项含 standard_id/name/authority/source_url/版本/生效日/`local_path`/`text_path`/各类 SHA-256/verified；另带 `requirement_count_by_standard` | 67 个来源；合计 6,255 条 |
| `requirements.jsonl` | 考试要求条款索引，交付库 `exam_requirement_ids` 的落点；locator 四形态见下节 | 6,255 行；覆盖 66 个 standard_id（evidence.gbt41671-2022 为纯纠正证据、0 条款） |
| `collect_sources.py` | 联网抓取：discover_ntce() 扫 3 类分类页发现 35 笔试大纲+3 面试+1 考试标准，FIXED 内置 4 条 CET/CSE；下载字节存 `originals/<sid><ext>`，抽正文到 `text/<sid>.txt`，落地页存 `.landing.html`，目录页存 `ntce.*.index.html`；更新 catalog、追加 acquisition_log；参数 `--offline/--extras` | acquisition_log 现有 240 行（239 downloaded + 1 failed） |
| `prepare_extras.py` | 从教育部通知页解析 doc/docx 附件 URL，写 `extra_sources.json`（教师标准 11、法律规程 9、CSE2024 数据集、GB/T 纠正证据、CET 分数解释等） | 输出 24 条待采来源 |
| `extra_sources.json` | prepare_extras.py 的产出，供 `collect_sources.py --extras` 消费 | 24 项 |
| `extract_word.ps1` | Word COM 隐藏、只读、禁宏把 `originals/` 的 48 份 doc/docx 转 UTF-8 纯文本并抽表格；原件零修改；`-OnlyMissing` 跳过已产出 | 生成 `text/` 的 48 个 .txt + 48 个 .tables.json |
| `build_index.py` | 离线重建 requirements.jsonl 与评分表：CET HTML 表格行、NTCE Word 条款边界、面试 61 条细则、CSE JSON 指针；复用旧 ID 并预留退休号段，原子替换 | 产出现行 `requirements.jsonl` 全部 6,255 行 |
| `verify_sources.py` | 离线核验：三类路径 SHA-256、ID 唯一、退休 ID 不复用、逐条 locator 原文比对、35 科大纲"试卷结构/题型示例"边界、CET 表格完整行、CSE json_pointer、面试各学段权重合计 100 | 产出现行 `verification_report.json`，写入本目录 |
| `verification_report.json` | 上一次核验的机器结果（见"如何测试与复跑"数字），不是本 README 的手写声明 | 10 个计数字段 + error_count=0 |
| `test_source_index.py` | unittest 离线回归：CET 五模块编号技能 01..N 齐全且 locator 原文一致、模板/版心行不误入库 | 断言 听力9/阅读10/写作11/翻译5/口语5 |
| `official_interview_rubrics.json` | 面试官方评分细则 61 条（official=true），按学段建权重合计 | criteria 61 |
| `official_cet_rubrics.json` | CET 写作、翻译各 5 档总体印象评分（14/11/8/5/2 分），official=true，note 声明 15 分原始档≠710 报道分 | rubrics 2 组、band 共 10 |
| `practice_rubrics.json` | 自编练习分维建议，official=false、status=local_practice_suggestion_needs_subject_expert_review，禁止换算正式分 | rubrics 4 |
| `retired_requirement_ids.json` | 退休 requirement_id 黑名单（verify 强制禁复用），batches 记录两批退休时间与原因 | retired 170（ntce.outline 137 + cet.syllabus 5 + cet.content 28） |
| `retired_requirement_records.jsonl` | 退休条目的退休前完整旧记录，只供追溯抽取修正 | 142 行（137 ntce.outline + 5 cet.syllabus；cet.content 28 条从未入库无旧行） |
| `cet_skill_coverage.json` | CET 大纲 1.1.2–1.5.2 编号技能逐项落位报告：期望码=实际码、complete=true，每条带 requirement_id 与 text_path 行号+PDF 页/章节 | 5 模块共 40 技能 |
| `cet_skill_index_changes.json` | 技能索引修正账：短技能句与多列编号补齐 14 个新增 ID，纯版心/章节模板废弃 5 个 | added 14 / retired 5 |
| `acquisition_log.jsonl` | 每次 fetch 的 url/status/bytes/retrieved_at/final_url 追加日志，含未成年人保护法人大 PDF 403 的 failed 记录 | 240 行 |
| `README.md` | 本说明 | — |
| `text/`、`originals/` | 抽取文本层与原件归档层，逐文件清单各自见其 README | 115 个 / 123 个文件 |
| `__pycache__/` | Python 导入 build_index 时的字节码缓存，非数据 | — |

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

原文件在 `originals/`（123 个文件：67 个正文原件 + 49 个发布/落地页 + 7 个目录页/工具脚本，逐个说明见 `originals/README.md`），提取文本在 `text/`（115 个文件：67 个 .txt + 48 个 .tables.json，见 `text/README.md`）。Word表格另保留 `.tables.json` 的表号、行号、列号与单元格原文。Word只读打开、关闭宏、隐藏运行，原件不修改。

## 数据接口与使用

`catalog.json` 顶层为 `sources` 数组。每项具有稳定 `standard_id`，保存 `name/authority/source_url/version/effective_date/retrieved_at/local_path/text_path/sha256/text_sha256/exam_scope/verified/verification_method`；有落地页或附件时另保留 `landing_path/landing_sha256/document_url`。未知正式版本和生效日期为 `null`，网页发布日期单列 `published_date`。`verified=true` 只说明官方原文取得并核验，不能证明题目或知识点经专家复核。

`requirements.jsonl` 按物理行读取，每项具有 `requirement_id/standard_id/title/content/locator/module/subject/level/mapping_status`。NTCE要求以实际大纲条款、原文段落或子条款保存；大纲未明确的专业细节不可自行声称为其逐字条目。节点和题目引用字段使用 `exam_requirement_ids`，应以术语和内容实际匹配；没有对应证据时保持待对齐。

定位有四种（写死 `权威资料/` 前缀，需工作区符号链接才拼得通）：文本 `text_path + line_start/line_end`（2,435 条，指 `权威资料/text/*.txt`）；官方Word表格 `table_path + table/row/column`（61 条，指 `权威资料/text/ntce.interview.*.tables.json`）；官网HTML表格 `html_path + table/row/headers`（18 条，指 `权威资料/originals/cet.content.cet4.html`、`cet.content.cet6.html` 各 9 条）；CSE2024 `json_path + json_pointer + official_descriptor_id`（3,741 条，指 `权威资料/originals/cse.gf0018-2024.json`）。CET大纲中的去页眉整理内容标为 `content_type=source_text_with_layout_lines_removed`，`original_text` 保存其定位范围完整原文。

ID格式例如 `ntce.outline.311.r008`、`cet.syllabus.2016.r067`、`cse.gf0018-2024.r001`。增补来源不会改变已有条目ID；重建读取现有索引复用ID，并预留全部退休ID的数字。CET内容表当前有效ID为各级 `r015–r023`，未发布的错误数字条目 `r001–r014` 已废弃。NTCE正文边界复查另废弃137个误入的试卷结构/题型样例条目：304.r024–r049、309.r019–r049、404.r025–r055、407.r033–r081（前缀均为 `ntce.outline.`）；正文中的正确ID保持原值。退休ID现共 170 个＝`ntce.outline.*` 137 + `cet.syllabus.2016.*` 5 + `cet.content.cet4/cet6.*` 28，完整清单见 `retired_requirement_ids.json`；退休前的旧记录 142 行（137+5）保存在 `retired_requirement_records.jsonl`（cet.content 的 28 条从未入库，没有旧记录行），只供追踪抽取修正，不能用于通用考试要求映射。采集和索引用临时文件写完后原子替换，避免并发读到半成品。

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

最近一次落盘的 `verification_report.json`（generated 2026-10-03，此后未复跑）记录：source_count=67、verified_source_count=67、requirement_count=6255、written_outline_boundary_count=35、retired_requirement_count=170、official_interview_criterion_count=61、official_cet_band_count=10、cet_numbered_skill_counts 听力9/阅读10/写作11/翻译5/口语5（共40）、error_count=0。短条目也按实际原文保留，修正记录见 `cet_skill_index_changes.json`（新增14、废弃5）。离线重建后要求索引的SHA-256保持一致。查具体引用时，先在JSONL找到 `requirement_id`，再按 `locator` 打开本地文本、原文或JSON。

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
