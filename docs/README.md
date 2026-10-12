# docs/ —— 运行时设计与交付验收文档层，接手 agent runtime 的人从这里入门

本目录放四类文档：**架构决策**（`agent_architecture.md` 八 Agent + 自研状态机的总设计，`web_agent_architecture.md` 网页端增量）、**使用与验收**（`web_agent_usage.md` 给跑网页工作台的操作手册，`web_agent_verification.md` 逐轮实测记录、`教资完整性与网页端交付报告.md` 数据底数与五批冲突核对）、**数据补齐索引**（`教资无题考点学习索引.md`）、**历史计划**（`agent_workflow_plan.md`）与一张手机布局截图。
新接手运行时的读序：`agent_architecture.md` → `web_agent_architecture.md` → `web_agent_usage.md`；想知道"库现在缺什么"直接跑四道门禁，不要信任何一份文档里的旧计数。
`superpowers/` 子目录是 writing-plans/executing-plans 流程的 plan 与 spec 存放处，见其下 README。

## 文件清单

- `agent_architecture.md`（233 行，手写）—— 总设计：把上位文档《应试考证功能设计与技术支撑》定死的八层数据契约翻译成可运行 agent 运行时。§0 已定决策（自研状态机不用 LangGraph、Chroma、NetworkX、无 Celery、仓库 public）、§1 现状事实、§2 两档运行态（研究档/发布档）、§3 分层（门面/八 Agent/编排/LLM 层）、§5 检索三路径汇流、§6 API 演进、§7 分阶段落地、§8 可执行验收 A1–A11（每条对应 tests 用例）、§9 风险、§10 明确不做、§11 落地状态（2026-10-11）。P0–P4 已落地；增量以 `web_agent_architecture.md` 为准，本文 §1 保留原基线。所有改运行时行为的争论先在这里对决策表。
- `web_agent_architecture.md`（57 行，手写）—— 网页端增量（2026-10-11）：开头 mermaid 图给出 UI→FastAPI→Workbench→八 Agent→门面/TrustGate/SQLite 的调用链；正文四节：事实归属与持久化（`workbench.sqlite3` 提交收据与输入指纹、409 拒绝改答案重放）、模型边界（Key 仅页面内存、SecretStr、HTTPS 公网 Base URL、模型不得签署题库/判客观题）、增量接口（`/api/v1/web` 路由表）、验证与待实现。改 web 路由或提交语义前必读。
- `web_agent_usage.md`（79 行，手写）—— 操作手册，谁要**用**网页工作台谁读：启动（`.\start_web.ps1`，Python≥3.11，本机 127.0.0.1:8000，脚本为 `权威资料`/`教资` 建 Junction）、DeepSeek 配置、八节日常使用（问答/七种练习/学情/计划/面试连续会话/知识库审查面板）、"可复跑验收"一节给出完整命令清单（含 `KNOWLEDGE_MAP_STATE_DIR` 指向临时目录这条硬前提）、数据与边界。
- `web_agent_verification.md`（359 行，手写，逐轮追加）—— 验收记录，按"完整自动化 / 真实浏览器实测 / 尚未实测"三档分开写。**顶部"当前实况"一节是唯一有效快照**（最近一轮：pytest 476 通过 2 项 `test_learning_resources.py` 有意红、audit 退出 0、状态词表两库 0 违规、validate_kb 退出 1=130,555 gaps/0 结构错误）；往下依次是各轮计数史、提交重试一致性、掌握度取证、无题考点并入 L7、六面对账、浏览器/手机宽度实测、模型护栏在本机挡真实请求的记录、五批答案冲突逐批清点。历史节的计数只作对照。
- `教资完整性与网页端交付报告.md`（184 行，手写）—— 交付报告（2026-10-11，五批冲突核对后更新）：核对结论表（14,500 题/13,464 可练/挂载与考纲缺口/签核为 0）、本次补充修复清单、五批 `answer_conflict` 逐批核对记录（小学教育心理学→小学综高→高中历史→初中数学+地理→高中化学+省考两科，机械核对见底）、后续补齐顺序、验证命令。数字须能由 `审查/audit_ntce_completeness.py` 与 `kb_tools/ntce_conflict_reconcile.py` 复现。
- `教资无题考点学习索引.md`（58 行，**由脚本生成，不要手改**）—— 由 `python 审查/audit_ntce_completeness.py --study-index docs/教资无题考点学习索引.md` 重新生成；列 7 个无直接试题的叶子考点，每个附真实考纲条款原文与行号定位（或"无绑定，待补"），文件尾部自带再生成命令。
- `agent_workflow_plan.md`（20 行，手写，历史计划）—— 最早期的知识库短板补齐工作流（T1.1–T4.1：轨 B 卡片、写译统一、paper_specs、音频切片、图谱扩展、回归门禁）。其中"教资KB/"等路径是库改名进 `数据集/教资/` 之前的旧坐标，只当立项脉络读，任务实际完成情况看 git 历史与上面的验收文档。
- `web_agent_mobile.png`（31KB，截图）—— 网页工作台手机宽度实测证据图（工作台 390px 布局），随提交 `5ff2488e` 入库；`web_agent_verification.md` 的"手机宽度实测"一节配套。

## 改这里之前要知道的

- 三份"报告类"文档里的计数全是时点值：库每修一批就过期，有效口径永远以重跑门禁为准（`web_agent_verification.md` 顶部自己就是这么声明的）。
- `教资无题考点学习索引.md` 手改会在下次带 `--study-index` 重跑时被整篇覆盖。
- `agent_workflow_plan.md` 提到的 `数据集/四六级/cards/`（5,340 卡）、`paper_specs.jsonl` 等已实际落地，但它写的"197+ 项测试"等指标早已被 pytest 套件现状取代，别拿它当进度表。
