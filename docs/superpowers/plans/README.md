# docs/superpowers/plans/ —— 每轮交付的实施计划（任务分解 + 可执行验收步骤），手写、按轮追加

一轮实施一份 `YYYY-MM-DD-<主题>.md`：头部写 Goal/Architecture/Tech Stack 与执行方式（executing-plans 当前会话逐项执行），正文按任务编号拆步骤，每一步的验收都指到具体测试文件或具体命令，不写形容词。做到哪勾到哪，后续会话只追加"接手后追加的任务"一节。

## 文件清单

- `2026-10-11-web-agent.md`（49 行，手写，入库）—— 网页端备考智能体的实施计划。锁定的范围与验收步骤：
  - **任务 1 基线及缺口**：跑 pytest 与 `validate_kb.py --output .local_state/web_audit_baseline.json` 存基线；新增 `services/knowledge/completeness.py` + `审查/audit_ntce_completeness.py`；补 `数据集/教资/schemas/paper_spec.json` 并全量验证 32 份教资规格。
  - **任务 2 闭环与范围**：`tests/test_web_workbench.py` 先测 404 再实现；`attribution.persisted_mastery` 收成必填 keyword-only（掌握度只认持久化记录，判据见 `docs/agent_architecture.md` §8 A10）；计划/练习/MASTER 支持学段科目筛选、空池不回退；提交收据带输入指纹，改答案重放在任何学习写入前 `409`。
  - **任务 3 模型配置及工作台**：`services/web/models.py`（Key 为 SecretStr）、`provider.py`（请求私有 LLMClient）、复用 LLM 护栏拒绝越界引用、`service.py`/`routes.py` 接九类能力、`services/app.py` 同源挂静态页。
  - **任务 4 网页和交付**：`web/index.html|styles.css|app.js` 响应式学习桌面；`requirements.txt`、`start_web.ps1`、`docs/web_agent_usage.md`；重跑四道门禁并把真实结果记入 `docs/web_agent_verification.md`；真实浏览器 + 手机宽度实测。
  - **接手后追加的任务（交付清单第 3–6 项）**：五批答案冲突回卷核对（证据落 `数据集/教资/review/`）、无题叶子考点 3 份讲解升格 L7 入图、判重两维缺口进 `待复核清单.md` §3.3、六面学习闭环对账 + 面试连续会话；**仍未勾的两项**：剩余隔离题四类卡点与补收录缺口要人读原卷、真实 DeepSeek Key 线上验证只能由学习者本人完成；媒体与完整模考只做了一半（后端阶段状态/超时收卷已实现，原图与音频切片、CET 逐节收卡未做）。
  - 计数与逐题证据不在本文件，统一指向 `docs/web_agent_verification.md`"当前实况"与交付报告。

## 改这里之前要知道的

- 本文件是历史执行台账：完成行不回改，新工作另起一份日期文件；把计数抄进来会造成第二真相（文件里明确写了这条纪律）。
