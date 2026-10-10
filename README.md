# knowledge_map 知识图谱与智能备考系统

本工程是一个面向**大学英语四六级（CET-4/6）**与**中小学教师资格考试（NTCE）**的结构化知识库与智能备考工程项目。

## 目录架构概览

- **`数据集/教资/`**：教资结构化知识库（核心交付产物，八层体系 L0–L7、14,500题、自包含卡片、图谱）
- **`数据集/四六级/`**：四六级结构化知识库（真题、长篇语料、大纲词汇、写作范文、翻译）
- **`权威资料/`**：官方权威标准与考纲原件（67项来源，6,255条定位条款，现行 CSE 2024 等）
- **`补充资料/`**：官方样卷集与教研参考解答（教资官方样题、四六级样卷、保教参考答卷）
- **`教资/`**：教资原始数据层（1,390个 CSV 原始真题与答案文件）
- **`英语四六级资料合集（2026年最新）(1)/`**：四六级原始资料层（9.8G 真题 PDF、听力 MP3、Word）
- **`数据集/`**：结构化考试与课程数据集总目录（四六级、教资、教育学类、计算机类）
- **kb_tools/**：教资数据处理与知识图谱构建工具链（含 `ntce_contract.py` 状态契约迁移、`build_graph.py` 图谱导出）
- **审查/**：全库质量与门禁工具（`validate_kb.py` 结构与引用门禁、`状态词表检查.py` 状态枚举门禁、`build_review_queue.py` 生成教研待复核清单（清单是生成物，计数一律现算，不要手改 markdown）、`知识库形式审查.py` 形式审查与验收报告）
- **tests/**：自动化测试套件（回归测试与数据契约断言，含 `test_graph_direction_contract.py` 两库图谱方向/层级契约、`test_status_vocabulary.py` 两库状态词表契约、`test_rubric_contract.py` 题内练习框架与 A.6 加权量规的双轨契约、`test_acceptance_gate.py` 架构方案 §8 的可执行验收 A1–A11（无影子数据（含卷面考务规格与生成物清单）、真实引用、隔离不漏、判分不冒充、状态持久、边名白名单、难度措辞、编排闭环、人工不旁路、判据归属（画像与诊断雷达）、门面换代与偏移身份）、`test_workspace_aliases.py` 工作区别名前置条件）
- **services/**：agent 运行时（47 个 py / 13 个模块）。`knowledge/` 是唯一的读数据门面（字节偏移索引、16 词边名白名单图谱、Chroma 卡片召回、TrustGate 两档可信裁决），`practice/ diagnostic/ planner/ memory/ qa/ grader/ interview/ master/` 八个能力层 agent 只经门面取数，`orchestrator/` 是自研状态机与会话信封，`llm/` 是结构化输出与禁用声称护栏，`review/` 是教研待复核队列，`app.py` 是 FastAPI 入口（含 SSE 与运行时令牌校验）
- **docs/**：项目实施计划与文档（`agent_architecture.md` agent 运行时架构设计、`agent_workflow_plan.md` 知识库数据补齐工作流）

## 工作区别名（必须在本地建立，且不入库）

`权威资料/` 与 `教资/` 不是普通目录，而是指向真实资料目录的**工作区链接**：

| 别名（代码与数据里出现的路径） | 实际目录 | 建立方式（Git Bash） |
| --- | --- | --- |
| `权威资料/…` | `官方权威资料/` | `ln -s "$(pwd)/官方权威资料" 权威资料` |
| `教资/真题/…` | `教资原始资料/真题/…` | `ln -s "$(pwd)/教资原始资料" 教资` |

- **为什么不能改脚本了事**：别名已经写进数据本身——`权威资料/requirements.jsonl` 里 6,255 条条款的 `locator.text_path` 全部以 `权威资料/` 开头，教资 14,500 道题的 `source.files[].path` 全部以 `教资/真题/` 开头。把脚本里的路径换成真实目录名，只会让已入库的定位信息与原文件断开；要彻底去掉别名，必须同时迁移两库的 locator 与 source 记录，那是一次数据迁移而不是清理。
- **缺失时的表现**：链接不存在时 `tests/` 会有 22 个用例直接报错（读不到 catalog 与原文），`审查/validate_kb.py` 会把来源判成 `Q_SOURCE_UNRESOLVED`。`tests/test_workspace_aliases.py` 先断言别名存在并给出上面的建立命令。
- **不入库的理由**：别名只是本机路径映射，跨机器无意义；而且 git 会顺着链接把同一批文件按两条路径各存一份。真实目录本身已按下面的口径入库（原件除外），克隆后只需按上表重建链接。

## 数据与版本化口径

两库的交付数据已随脚本一起入库（此前只有脚本与设计文档随库，克隆出来无法复现任一剑读数）。**入库内容**（约 470MB / 20,935 个文件，2026-10-10 起）：

| 路径 | 体积 | 内容 |
| --- | --- | --- |
| `数据集/教资/` | 230MB · 13,944 文件 | questions 142MB、cards 69MB、review 26MB、graph 20MB、materials 2.8MB、outline、schemas、rubrics、sources、resources、paper_specs、MANIFEST |
| `数据集/四六级/` | 77MB · 5,403 文件 | vocabulary 44MB、cards 41MB、questions 33MB、graph 17MB、ontology 16MB、manifest、listening、passages、writing、translation、official_examples |
| `数据集/计算机类/`、`数据集/教育学类/` | 179MB · 8 文件 | 课程目录抓取结果（最大单文件 90.5MB，在 GitHub 100MB 硬限内，未走 LFS） |
| `官方权威资料/` | 7.7MB · 135 文件 | `text/` 抽取文本、`requirements.jsonl` 与条款索引、抓取与核验脚本 |
| `教资原始资料/` | 6.8MB · 1,400 文件 | 1,390 份原始真题/答案 csv |
| `补充资料/` | 43.9MB · 29 文件 | 样题抽取结果（含 39MB `source_pages.json`）与教研参考解答 |
| `services/` | 47 个 py | agent 运行时（知识门面 + TrustGate + 八个能力 agent + 自研状态机 + LLM 护栏 + 复核队列 + FastAPI） |

**不入库**（可由脚本重建、或属原始二进制件）：`英语四六级资料合集（2026年最新）(1)/`（9.8GB 原始 PDF/MP3/Word）、`官方权威资料/originals/`（抓回的官方页面 html 与 doc/docx/pdf 原件）、`补充资料/` 的样题扫描件 png/jpg 与 PDF/Word 原件、`数据集/四六级/scripts/_staging/`（734MB OCR 中间件）、`归档/`（281MB 历史快照，仅作本机回退）、`_contract_snapshot/`（141MB 契约迁移前快照）、`审查/` 的运行产物（约 120MB）、`数据集/*/manifest/*.log`、`chroma/`（向量索引，按 `数据集/*/cards` 全量重建）、`.local_state/`（learner 的 FSRS 画像、会话与复核队列，按机器隔离的运行时状态）、根级别名 `权威资料/` 与 `教资/`。原始二进制件不进库不等于放弃溯源：每条题目与条款的 `source_locator`/`locator` 仍指向本机原件路径，重建时按上表恢复。

## 核心规范文档
- [应试考证功能设计与技术支撑：以教资和四六级为例.md](应试考证功能设计与技术支撑：以教资和四六级为例.md)：系统顶层功能设计与技术规范（含附录 A 完整 Schema 字典）。
- [教资KB版权清权报告.md](教资KB版权清权报告.md)：科研非商业使用定位与合理使用边界。
- [审查/待复核清单.md](审查/待复核清单.md)：教研签署队列（当前 0 人具名审核、0 条实测校准难度；先修边教资 31 条 / 四六级 56 条全部待核定；6 套加权量规的维度权重与档位措辞也全部待签署）。由 `审查/build_review_queue.py` 重新生成，请勿手改数据结论。
- [docs/agent_architecture.md](docs/agent_architecture.md)：Agent 架构设计方案——把本库的数据契约（八层 L0–L7、16 种边、三层状态、双轨量规）翻译成运行时：知识门面、TrustGate 两档运行态、自研编排状态机、Chroma 检索与 LLM 结构化护栏，并逐条给出可执行验收断言。
