# services/master/ —— 总控对话层：一句话先进意图路由，再进编排状态机

这一层是"会话入口"：把一条自然语言消息或一次按钮动作分发到具体能力 agent（diagnostic / planner / practice / grader / memory / qa / interview），并把它们真实返回的数据渲染成卡片。写它的是运行时，读它的是 `services/app.py` 的 `POST /api/v1/master/chat` 与 `GET /api/v1/master/stream`（SSE）、`services/web/service.py::Workbench.chat`（只在 `interview_practice` / `submit_subjective` / `error_review` 三种意图上转交），以及 `/api/v1/health` 探针（`services/app.py::_probe_resources` 注入临时队列与会话库）。它自己不碰题库文件：所有取数都经 `services/knowledge/repository.py` 门面；两处写盘都落在 `.local_state/`（会话轨迹 `orchestrator.sqlite3`、降级记录 `review_queue/orchestrator_degraded.jsonl`，均不入库）。

改动后跑：

```powershell
$env:KNOWLEDGE_MAP_STATE_DIR = "D:\tmp\kb_state_check"
python -m pytest tests/test_services_all_agents.py -q -k Master      # TestTutorMaster 五条
python -m pytest tests/test_services_api.py -q -k master             # chat + SSE 两个端点
python -m pytest tests/test_acceptance_gate.py -q -k "A8 or A9"      # 编排闭环 / 人工不旁路
```

## 文件清单

- `__init__.py`（4 行）—— 模块出口：只做 `from services.master.agent import TutorMasterAgent` 并写 `__all__ = ["TutorMasterAgent"]`。
  外部一律 `from services.master import TutorMasterAgent`（`services/app.py`、`services/web/service.py`、`services/orchestrator/*` 都这么引），
  因此新加类不会自动出现在包名空间里——要么改这个 `__all__`，要么让调用方写子模块全路径。
- `agent.py`（784 行）—— `TutorMasterAgent`。`__init__` 装配七个能力 agent（`DiagnosticAgent`/`CurriculumPlannerAgent`/`PracticeEngineAgent`/`SubjectiveGraderAgent`/`MemoryReviewAgent`/`TutorQAAgent`/`InterviewCoachAgent`）+ `default_store()`（`services/memory/store.py`）+ `get_review_queue()` + `get_session_store()`，每个都可注入覆盖。主入口 `handle_interaction(req: MasterInteractionRequest) -> MasterInteractionResponse`：① `IntentRouter.classify(req.message, req.action_payload)`；② `general_chat` 直接回 `GENERAL_HELP`（不假装跑过任何 agent）；③ `qa_ask` 走 `_qa_turn`（组 `QARequest` 交 `TutorQAAgent.answer_query`，卡片带 `grounded_in_library`/`answer_visibility`/`knowledge_provenance`）；④ `interview_practice` 走 `_interview_turn`（有 `plan_text` 交 `review_lesson_plan`、有 `transcript_text` 交 `analyze_speech`、都没有就用 `_trial_teaching_topic()` 从库里取一道真实教学设计题作选题，仍不虚构表现数据）；⑤ 其余意图进 `_orchestrator(session_id).run(entry=INTENT_ENTRY[intent])`，随后 `self.sessions.save(...)` 把状态与 `_serialisable(result.context)` 落到 `.local_state/orchestrator.sqlite3`（表 `agent_session`/`agent_trace`，见 `services/orchestrator/session.py`）。分发表：`INTENT_ENTRY`（6 个意图 → State，注意 `qa_ask`/`interview_practice` 不在表里、走独立回合）、`_handlers()`（`State→self._h_*`，其中 `MOCK` 复用 `_h_practice`、`GRADE`/`FEEDBACK_ONLY` 复用 `_h_grade`、`REPROFILE` 复用 `_h_profile`）、`CARD_BY_STATE`（卡片类型字面量）、`CARD_KEY_BY_STATE`（context 里的卡片键；注释写明为什么不能用命名约定推导——REPROFILE 复用 profile 卡、未签署讲评落在 `card_feedback_only`、MOCK 复用 `card_practice`）、`STATE_LABELS`（11 个状态的中文名，进 `reply_text`）。handler 里每个数字都有出处：`_h_diagnose` 用 `DiagnosticAgent.evaluate`，`_h_profile` 区分"诊断给出的低于薄弱线（`WEAK_MASTERY_BAR`，住 `services/common/weakness.py`）"与"记忆里的相对最低"两种来源并写进 `weak_source`，`_h_practice` 在 `research_internal` 空池时产 `blocked` 行、`published` 空池是设计上的 fail-closed 故不入队，`_h_grade` 只有 `rubric_signed` 才写 `card_grade`，`_h_attribut` 用 `_verdict_with_provenance`（判据优先级：库内答案键核对 > 调用方申报 > 学习者自己的错题日志，判不出就 `attributable=False` 且不写记忆）后交 `MemoryReviewAgent.process_event`。降级两条路：`_enqueue(row)` 以 `reason="orchestrator_degraded"`、`detail.reason_text` 存原句写队列；`kind=="input_gap"`（缺口在调用方）只回提示、明确"这类缺口不进入教研的待复核队列"。`trace_of(session_id)` 回放信封轨迹（A8）。本地看一条完整回合：`python -m uvicorn services.app:app --host 127.0.0.1 --port 8000` 后 `curl -X POST http://127.0.0.1:8000/api/v1/master/chat -H 'Content-Type: application/json' -d '{"user_id":"u1","message":"进行学情摸底"}'`，流式版是 `GET /api/v1/master/stream?message=进行学情摸底`（事件顺序 `status → card → done`，实现在 `services/app.py::_stream`）。
- `intent_router.py`（92 行）—— `IntentRouter.classify(message, action_payload=None) -> UserIntent`，纯静态、无 IO。三步：① `action_payload["intent"]` 显式标签优先，未知标签 `ValueError` 被吞掉继续往下（"不为一个错标签编造意图"）；② 按 `INTENT_KEYWORDS` 列表顺序匹配小写关键词，顺序即优先级：`submit_subjective`（批改/评分/打分/作文批改…）→ `interview_practice`（面试/试讲/答辩/教案/教学设计…）→ `diagnostic`（摸底/诊断/学情…）→ `qa_ask`（为什么选/解析一下/苏格拉底…）→ `error_review`（错题/归因/失分/fsrs…）→ `plan`（计划/排课/倒计时…）→ `practice`（刷题/组卷/模考…），所以"批改我错题本里的作文"落 `submit_subjective` 而不是 `error_review`；③ 都没命中才 `_from_payload(text, payload)` 按**载荷形状**猜：有 `plan_text`/`transcript_text` → 面试，有 `answer_text`/`student_answer` → 主观题提交，有 `is_correct`+`question_id` → 错题归因，只有 `question_id` → 答疑，含"练/题/卷" → practice，否则 `general_chat`。`UserIntent` 的 9 个成员定义在 `services/common/models.py`（`general_chat` 之外 8 个可被路由到）。跑一条分类：`python -c "from services.master.intent_router import IntentRouter; print(IntentRouter.classify('这道题为什么错了', {'question_id':'q1'}))"`。

## 子目录

- `__pycache__/`：字节码生成物，可删可重建，不作为模块存在的证据。

## 改这里之前要知道的

- 不许回"营销话术 + 编造数字"：文件顶部 docstring 记着旧版本没调用任何子 agent 就回答"30 道分层自适应试题""due_today_count: 8"。任何新增分支里的计数都必须来自 `repository`、`memory store` 或本次 agent 返回值，`tests/test_services_api.py::test_master_chat_reports_real_counts_only` 与 `tests/test_acceptance_gate.py::TestA1NoShadowData` 会盯这条。
- 卡片键与状态是两张表，不是命名约定：`CARD_KEY_BY_STATE` 与 `CARD_BY_STATE` 必须成对维护；漏一项会让网页渲染出空卡（注释里写了历史上"派生键静默产出空卡片"的事故）。
- 降级 ≠ 塞队列：只有内容侧降级（门禁挡下、handler 抛错、无处理器、不收敛）才写 `review_queue`；输入缺口只回提示。教研是仓库里唯一人工审核人，队列被无关行淹没就等於旁路人工（A9）。
- 会话状态在 `.local_state/orchestrator.sqlite3`，不入库、按机器隔离；测试要指 `KNOWLEDGE_MAP_STATE_DIR` 到临时目录，否则 `/health` 探针与单测会往本机真实会话库里写行。
- `ATTRIBUT_NOTICE`（错因由作答特征启发式判定、未接真实校准）与 `NO_DATA_REPLY` 是对外口径文本，前端 `web/app.js` 直接展示 `reply_text`/`notices`，改措辞要同时看网页与 `tests/test_services_all_agents.py::TestTutorMaster`。
- `published` 档在本层没有可用出口：`_trial_teaching_topic` 经 `TrustGate.classify_meta(meta).usable` 过滤，库里 0 具名签署题时返回 `{"question_id": None, "notice": ...}`；不要在这里给发布档加兜底内容。
