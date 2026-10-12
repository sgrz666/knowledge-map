# services/orchestrator/ —— 这个目录放什么、谁来用

把架构方案 §2.1 的备考闭环（诊断→画像→规划→练习→判分→归因→回写）编成一个**自研状态机**，并把每跳的消息信封落 SQLite。
它自己既不碰磁盘也不碰 LLM：`state_machine.py` 的处理器全部由 `master/agent.py` 注入（八个能力 agent + review 队列），
降级写队列通过 `on_degrade` 回调完成；`session.py` 负责会话与 trace 的持久化。
谁从里读：`master/agent.py`、`app.py`（`/master/chat`、`/master/stream`）与验收 A8/A9/A5。改这里跑：
`python -m pytest tests/test_acceptance_gate.py -k "A8 or A9" tests/test_services_all_agents.py tests/test_services_api.py -q`。

## 文件清单

- `__init__.py`（1 行）—— 只有一句 docstring（"§2.1 闭环的显式状态机"），无 import、无逻辑。
- `state_machine.py`（404 行）—— 无外部编排框架（不用 LangGraph 等），`class Orchestrator` + `class State(str,Enum)` + `NodeSpec` + `RunResult`。
  **12 个状态**：`IDLE / DIAGNOSE / PROFILE / PLAN / PRACTICE / MOCK / GRADE / FEEDBACK_ONLY / ATTRIBUT / REPROFILE / REVIEW_QUEUE / DONE`。
  **迁移全部集中在 `_route(state, outcome, context, cycles)` 一个函数**（不是布尔开关表）：
  `outcome["degrade"]` 恒 → `REVIEW_QUEUE`；`IDLE→DIAGNOSE→PROFILE→PLAN`；
  `PLAN→` `context.mode=="mock"` 或 `outcome.prefer_mock` 则 `MOCK` 否则 `PRACTICE`；
  `PRACTICE/MOCK→` 有 `answer_text` 则按 `outcome.rubric_signed` 分 `GRADE`/`FEEDBACK_ONLY`，有 `selected_option`+`question_id` 则 `ATTRIBUT`，什么都没交则 `DONE`（不编答案）；
  `GRADE/FEEDBACK_ONLY→` `outcome.attributable`（默认 True）则 `ATTRIBUT` 否则 `DONE`（未签署量规的反馈没有对错信号）；
  `ATTRIBUT→REPROFILE`；`REPROFILE→` `cycles>=2` 或 `not context.replan` 则 `DONE` 否则回 `PLAN`；`REVIEW_QUEUE→DONE`。
  `run()` 里进入 `PLAN`/`DIAGNOSE` 时 `cycles += 1`，总步数上限 `MAX_STEPS=16`（用尽即 `kind="budget"` 降级并置 DONE）。
  `NodeSpec(state, action, recipient, timeout_seconds=20.0, requires=(), degrade_to=REVIEW_QUEUE)` 是每跳声明；
  `DEFAULT_NODES` 逐状态给出 action 名与收件 agent（如 `DIAGNOSE→("diagnostic.evaluate","diagnostic",requires=("exam_type",))`、
  `GRADE→("grader.grade","grader",requires=("user_id","answer_text","question_id"))`、`ATTRIBUT→("memory.attribute","memory",requires=("user_id",))`）。
  `missing_inputs()` 把 `is_correct=False` 当答案而非缺失输入（只有 `None/""/[]/{}` 算缺）；`requires` 里刻意不含 `weak_nodes`，让无历史学习者拿真日历而不是降级行。
  **两类降级相反**：调用方缺字段 → `_degrade(kind="input_gap", queue=False)`，只结束本轮、**不占教研队列**；
  内容/执行问题（门禁拒绝 `kind="trust_gate"`、无处理器 `no_handler`、超时 `timeout`、节点异常 `handler_error`、预算耗尽 `budget`、处理器主动要人 `handler_degrade`）
  → 走 `on_degrade` 回调并追加一条 `recipient="review"` 的 `review.enqueue` 信封（验收 A9）。
  `run(*, session_id, user_id, exam_type="NTCE", tier=TrustTier.RESEARCH_INTERNAL, context=None, entry=State.IDLE) -> RunResult`：
  `merged` 先塞 `user_id/exam_type/trust_tier(=tier.value)`，`notices_seen` 去重累积（处理器在别线程拿到的是 context 副本，notice 只能经机器回传）。
  `_invoke` 用 `concurrent.futures.ThreadPoolExecutor(max_workers=1)` 给每跳套 `spec.timeout_seconds` 超时。`replay(session_id, store)` = `store.trace(...)`（A8 要求闭环可回放）。
  依赖 `services.common.models`（`AgentMessageEnvelope/AuthContext/EvidenceItem/GeneratedBy/TrustTier`），**不 import 任何磁盘数据路径**——题面/判据由注入的 handler 从 `knowledge/` 门面取。
- `session.py`（136 行）—— 会话持久化（§3.5）。`class SessionStore`：SQLite（`sqlite3.connect(check_same_thread=False)` + `threading.Lock`），
  **默认落盘 `.local_state/orchestrator.sqlite3`**（路径 = `services.memory.store.state_dir()/"orchestrator.sqlite3"`；`KNOWLEDGE_MAP_STATE_DIR` 环境变量可改状态根目录）。
  取代旧的"进程内 dict"（跨进程读不到，A5 的历史缺陷）。`SCHEMA` 建两张表：
  `agent_session(session_id PK, user_id, exam, state, context_json, updated_at)` 与
  `agent_trace(id AUTOINCREMENT, session_id, seq, state, envelope_json, created_at)`，
  索引 `ux_trace_seq` 唯一于 `(session_id, seq)`、`ix_trace_session` 于 `(session_id, seq)`。
  方法：`save(*, session_id, user_id, exam, state, context)`（`INSERT ... ON CONFLICT(session_id) DO UPDATE` 幂等 upsert，
  `context` 以 `json.dumps(ensure_ascii=False, default=str)` 存）、`load(session_id)`（返回 `{session_id,user_id,exam,state,context,updated_at}`，无则 None）、
  `append_trace(session_id, envelope)`（`seq = MAX(seq)+1`，`state` 取 `envelope["action"]`，返回 seq）、
  `trace(session_id)`（按 seq 升序回 `[{seq, envelope}]`）、`clear(session_id=None)`、`close()`。
  `get_session_store()` 是模块级惰性单例（`_DEFAULT`，无锁）。

## 子目录

无。本目录 3 个 py 文件（`__init__.py`、`session.py`、`state_machine.py`）。

## 改这里之前要知道的

- **`.local_state/orchestrator.sqlite3` 是运行时状态、不入库**：按机器隔离，删了不影响知识库；测试里必须先把 `KNOWLEDGE_MAP_STATE_DIR`
  指到临时目录（`tests/test_acceptance_gate.py` 在 import 任何 service 之前就 `os.environ.setdefault`），否则学习者会话会写进仓库的 `.local_state/`。
- **A8 钉死了六阶段序列**：`TestA8ClosedLoop.SPINE = ["diagnostic.evaluate","memory.profile","planner.generate",
  "practice.assemble","memory.attribute","memory.profile"]`，且每跳都必须是 `sender="orchestrator"` 的 `AgentMessageEnvelope`、
  `seq` 从 1 连续。改 `_route`/`DEFAULT_NODES` 的顺序或 action 名会让这条验收失败。
- **A9 的输入侧不变量**：调用方缺字段（`input_gap`）不许进教研队列——`_degrade(..., queue=False)` 是关键；
  若把它改成也入队，`test_a_caller_input_gap_does_not_implicate_the_reviewer` 会红，而且唯一一位人工审核会被学习者缺口刷满。
- **`TrustTier` 有两份类型**：机器边界用 `services.common.models.TrustTier`（`str, Enum`），
  `_envelope`/`run` 里对 `tier` 做了 `isinstance` 判定后 `TrustTier(str(tier))` 显式转换；别直接塞 `knowledge/trust.py` 的那个 `Literal`。
- **队列 reason 只能是词表里的字面量码**：状态机不直接写队列（经 `on_degrade` 回调由 `master`/`review` 落），
  任何入队点的 `reason` 必须取 `services/review/reasons.py` 的 `REVIEW_REASONS`，否则 A9 `test_every_queue_reason_is_a_code_from_the_one_vocabulary` 失败。
