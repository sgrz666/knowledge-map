# knowledge_map 知识图谱与智能备考系统

本工程是一个面向**大学英语四六级（CET-4/6）**与**中小学教师资格考试（NTCE）**的结构化知识库与智能备考工程项目。

## 网页端智能体（2026-10-11）

PowerShell 中运行 `python -m pip install -r requirements.txt`，再运行 ` .\start_web.ps1`，打开 **http://127.0.0.1:8000/**。
“模型与设置”支持填写 DeepSeek API Key、Base URL 和模型名；Key 只保留在当前页面内存。无 Key 也可用真实题库练习、规则检索、学情、计划和面试文字反馈。

- [安装、使用与测试说明](docs/web_agent_usage.md)
- [教资完整性核对与本次交付报告](docs/教资完整性与网页端交付报告.md)
- [无题叶子考点的考纲学习索引](docs/教资无题考点学习索引.md)
- [网页与接口验收记录](docs/web_agent_verification.md)

当前无具名签核题，六份教资加权量规待签署；“签署内容”档为空，练习不提供官方报告分或通过概率。

## 目录导航（每个文件夹一份项目目录）

每个目录在自己名下放一份 `README.md`，逐个文件写清"这段代码/这份数据具体干什么、谁生成、谁读、改它要跑哪条门禁"。
本索引只给入口与归属：目录里的实况数字归该目录的文档所有，这里不重复抄一遍（抄了就必然漂移）。

### 运行时与代码

- [`services/`](services/README.md) —— agent 运行时总览与 16 个子模块导航表（含 `app.py` 的路由、SSE 帧序与令牌校验）
  - [`services/knowledge/`](services/knowledge/README.md) 唯一读数据门面（字节偏移索引、16 词边名白名单、Chroma 召回、TrustGate 两档裁决）
  - [`services/common/`](services/common/README.md) 共享模型与两处"唯一出处"数值（配速、薄弱线）｜ [`services/llm/`](services/llm/README.md) 结构化输出与禁用声称护栏
  - [`services/orchestrator/`](services/orchestrator/README.md) 自研状态机与会话信封
  - 能力层：[`practice/`](services/practice/README.md) [`diagnostic/`](services/diagnostic/README.md) [`planner/`](services/planner/README.md) [`memory/`](services/memory/README.md) [`qa/`](services/qa/README.md) [`grader/`](services/grader/README.md) [`interview/`](services/interview/README.md) [`master/`](services/master/README.md)
  - 闭环与接口：[`learning/`](services/learning/README.md) [`exam_sessions/`](services/exam_sessions/README.md) [`review/`](services/review/README.md) [`web/`](services/web/README.md)
- [`web/`](web/README.md) —— 浏览器直加载的四个静态文件（无构建单页工作台），含接口-视图对照
- [`kb_tools/`](kb_tools/README.md) —— 教资管线 35 个文件逐个说明 + 复跑顺序与命令
- [`tests/`](tests/README.md) —— 29 个测试文件各自锁哪条契约（含 §8 A1–A11 验收项）、怎么单跑、失败意味着什么
- [`审查/`](审查/README.md) —— 门禁脚本、生成物与本地临时件的逐文件清单（`待复核清单.md` 等生成物不要手改）
- [`docs/`](docs/README.md) —— 设计与验收文档；[`docs/superpowers/`](docs/superpowers/README.md) 及其 [`plans/`](docs/superpowers/plans/README.md)、[`specs/`](docs/superpowers/specs/README.md)

### 交付数据（入库）

- [`数据集/`](数据集/README.md) —— 两库与备用学科数据的总目录导航
- [`数据集/教资/`](数据集/教资/README.md) —— 八层 L0–L7 交付库；逐层清单见
  [`questions/`](数据集/教资/questions/README.md)（各学段 [`xiaoxue`](数据集/教资/questions/xiaoxue/README.md) [`chuzhong`](数据集/教资/questions/chuzhong/README.md) [`gaozhong`](数据集/教资/questions/gaozhong/README.md) [`youer`](数据集/教资/questions/youer/README.md) [`zhongxue`](数据集/教资/questions/zhongxue/README.md) [`zhongxiaoxue`](数据集/教资/questions/zhongxiaoxue/README.md)）、
  [`materials/`](数据集/教资/materials/README.md)、[`cards/`](数据集/教资/cards/README.md)、[`graph/`](数据集/教资/graph/README.md)、[`outline/`](数据集/教资/outline/README.md)、
  [`schemas/`](数据集/教资/schemas/README.md)（六态/五态词表的唯一权威出处）、[`rubrics/`](数据集/教资/rubrics/README.md)、[`sources/`](数据集/教资/sources/README.md)、[`review/`](数据集/教资/review/README.md)、[`resources/`](数据集/教资/resources/README.md)
- [`数据集/四六级/`](数据集/四六级/目录清单.md) —— 顶层逐条目清单（该库 `README.md` 是 `build_stats.py` 生成物，不含目录导航）；
  子目录清单见 [`scripts/`](数据集/四六级/scripts/README.md)、[`questions/`](数据集/四六级/questions/README.md)、[`cards/`](数据集/四六级/cards/README.md)、[`manifest/`](数据集/四六级/manifest/README.md)、[`ontology/`](数据集/四六级/ontology/README.md)、[`graph/`](数据集/四六级/graph/README.md)、[`listening/`](数据集/四六级/listening/README.md)、[`passages/`](数据集/四六级/passages/README.md)、[`writing/`](数据集/四六级/writing/README.md)、[`translation/`](数据集/四六级/translation/README.md)、[`vocabulary/`](数据集/四六级/vocabulary/README.md)、[`exam_guide/`](数据集/四六级/exam_guide/README.md)、[`official_examples/`](数据集/四六级/official_examples/README.md)
- [`数据集/教育学类/`](数据集/教育学类/README.md)、[`数据集/计算机类/`](数据集/计算机类/README.md) —— 备用学科抓取快照，当前无消费方
- [`数据集/数据集/`](数据集/数据集/README.md) —— 多套一层目录的遗留扫描产物，可整树删除

### 原始资料层（入库口径见 `.gitignore` 与本页下方）

- [`教资原始资料/`](教资原始资料/README.md) → [`真题/`](教资原始资料/真题/README.md)：12 个学段/卷型目录各有清单（`初中真题`、`初中真题答案`、`小学真题`、`小学真题答案`、`幼儿真题`、`幼儿真题答案`、`高中真题`、`高中真题答案`、`真题精选`、`结构化面试`、`辽宁省考`、`四川省考`）
- [`官方权威资料/`](官方权威资料/README.md)：顶层件 + [`text/`](官方权威资料/text/README.md)（115 个抽取件）+ [`originals/`](官方权威资料/originals/README.md)（123 个原件，不入库）
- [`补充资料/`](补充资料/README.md)：[`教资官方样题/`](补充资料/教资官方样题/README.md)、[`四六级官方样题/`](补充资料/四六级官方样题/README.md)、[`教资参考解答/`](补充资料/教资参考解答/README.md)
- [`英语四六级资料合集（2026年最新）(1)/`](<英语四六级资料合集（2026年最新）(1)/README.md>) —— 原始 PDF/MP3/Word 层（整目录不入库），6 个子目录各有逐件清单

### 本机运行时（都不入库）

[`chroma/`](chroma/README.md) 向量索引 ｜ [`.local_state/`](.local_state/README.md) 学习者状态与验收留痕 ｜ [`_contract_snapshot/`](_contract_snapshot/README.md) 契约迁移回滚快照 ｜ [`归档/`](归档/README.md) 8 份操作前快照 ｜ [`review/`](review/README.md) 空目录遗留 ｜ `.scratch/` 会话级草稿（已列入 `.gitignore` 第 70–72 行，按机器隔离；条目清单见其自述）：现算两件——`find_candidates.py`（只读探针，用 `KnowledgeRepository` 打 4 个无题考点标准 `ntce.outline.306/315/406/412` 的候选条款与其 `locator` 行区间，供人工挑选学习指南引用；这 4 个考点的指南已于 2026-10-12 全部补入 `study_guides.jsonl`，探针保留复跑）与 `goal_state_dir/`（一次把 `KNOWLEDGE_MAP_STATE_DIR` 指到这里跑出来的运行时库：`learning.sqlite3`/`memory.sqlite3`/`orchestrator.sqlite3`/`workbench.sqlite3` + `review_queue/`，形状同 `.local_state/`）。

### 清单覆盖到哪一层（口径）

逐文件清单写到"目录职责"这一级为止：**同构重复的叶子目录不再各放一份文件**，由父级清单把全部子目录名与每组计数列出。
可复核算法（2026-10-12 现算）：`python .local_state/tmp_readme_final_audit.py` —— 走 266 个目录，"有文档但存在未点名条目"的目录 **0 个**；没有自己文档的目录 **144 个**，全部分布在下面六族里，每一族的目录名与计数都在上一级 README 的表格中：
教资 `questions/<学段>/<科目>/`（38）与 `materials/<学段>/<科目>/`（32）与 `cards/<学段>/`（6）、四六级 `cards/<级别>/`（2）与 `manifest/source_evidence/`、`scripts/_staging/`、`vocabulary/md/`（各 1，`vocabulary/md/` 是空目录）、
`_contract_snapshot/questions/<学段>/<科目>/`（38）、`归档/<快照目录>/`（8）、`chroma/<集合 uuid>/`（2）、`英语四六级资料合集（2026年最新）(1)/` 内的场次与专项叶子（15）。
`官方权威资料/text|originals/` 与 `教资原始资料/真题/*/` 的单件、`.local_state/tmp_*` 内部同理，逐个文件名写在上一级清单里。
给 666 个卡片目录各写一份文档只会制造重复与漂移；反过来，凡是**有**文档的目录，其直接子条目必须全部点名——上面那条命令就是在钉这一点（同级《目录清单.md》与《README.md》合并算作文盘面，因为 `数据集/四六级/README.md` 是 `build_stats.py` 的生成物、不许手改）。
该审计不进入 `.` 开头的目录（`.local_state/`、`.scratch/`、`.git/`…），这两个工作目录的逐个条目改由人工核对：`.local_state/` 的 70 个条目全部列在 `.local_state/README.md`，`.scratch/` 的两个条目写在上面"本机运行时"那一行里。

### 根级文件

- `README.md` —— 本文件：项目定位、网页端入口、目录导航、别名前置条件、入库口径。
- `start_web.ps1` —— 网页启动脚本：可选 `-Install` 装依赖，先 `python -c 'import fastapi, pydantic, uvicorn, jsonschema, networkx'` 探依赖，
  再对 `权威资料→官方权威资料`、`教资→教资原始资料` 两个别名做存在性检查（缺失时用 `New-Item -ItemType Junction` 建目录联接），最后起 `python -m uvicorn services.app:app --host 127.0.0.1 --port $Port`（默认 8000）。
- `requirements.txt` —— 运行时依赖锁定版本（fastapi 0.136.0 / pydantic 2.14.0 / uvicorn 0.44.0 / jsonschema 4.26.0 / httpx 0.28.1 / networkx 3.6.1）；
  `chromadb` 按注释单独装，缺它时检索走离线词法回退。
- `requirements-dev.txt` —— 只加 `pytest==9.0.3`，并用 `-r requirements.txt` 继承运行时依赖。
- `.gitignore` —— 入库口径的**唯一权威定义**（哪些数据树入库、原件与中间件为何排除），文件头与逐条注释都在解释理由；本页"数据与版本化口径"是它的可读摘要，两者冲突以 `.gitignore` 为准。
- `应试考证功能设计与技术支撑：以教资和四六级为例.md` —— 顶层功能设计与技术规范，附录 A 是完整 Schema 字典（各库字段口径回溯到这里）。
- `教资知识库整理方案.md` —— 教资原始 CSV（1,390 份）→ 结构化知识库的整理方案与现状盘点，是 `kb_tools/` 的立项依据。
- `教资KB版权清权报告.md` —— 科研非商业定位与合理使用边界；数据里的 `source.copyright` 口径与此文一致。

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
