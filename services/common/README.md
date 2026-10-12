# services/common/ —— 这个目录放什么、谁来用

跨模块共享层：一份 Pydantic 请求/响应契约（`models.py`）加三条"只许有一个出处"的服务侧口径
（配速、薄弱线、判分安全阀）。谁往里写：定契约的工程师；谁从里读：几乎每个子模块都 `from services.common.models import …`，
`pacing` 被 `practice/ planner` 读、`weakness` 被 `diagnostic/ planner/ practice/ master/ learning` 读、`safety` 被 `grader` 读。
本目录**不读任何磁盘数据路径**，也不写任何状态——它只是内存里的类型与常量。改这里跑：
`python -m pytest tests/test_acceptance_gate.py tests/test_services_safety.py tests/test_services_api.py -q`。

## 文件清单

- `models.py`（633 行）—— 全部 agent 的输入/输出 Pydantic 模型，`from pydantic import BaseModel, Field`、`from enum import Enum`。
  顶层：`ExamType(str,Enum)`（`CET4="CET-4"/CET6="CET-6"/NTCE="NTCE"`）、`UserRole`、
  `TrustTier(str,Enum)`（`RESEARCH_INTERNAL/PUBLISHED`，注意与 `knowledge/trust.py` 里同名 `Literal` 是两个类型，接口边界用这个枚举）、
  `AuthContext(user_id, role=STUDENT, exam=NTCE)`、`GeneratedBy(agent, version="1.1.0", requested_model, mode∈{rule_only,llm,deterministic}, prompt_sha256, created_at)`
  （每条 agent 消息必须带的出处戳）、`EvidenceItem`（一条回指库内文本的指针，保证"没有来源的话不往外送"）、
  `AgentMessageEnvelope(BaseModel, Generic[T])`——§3.4 规定的编排节点之间唯一消息形状：
  `message_id/trace_id/timestamp/sender/recipient/action/auth_context/trust_tier/evidence[]/generated_by/notices[]/payload:T/error`。
  判分：`SubjectiveGradingRequest`（`task_type/stem/student_answer/reference_answer/rubric_id/max_score/scoring_mode∈{auto,holistic_band,analytic_criteria}/trust_tier`）、
  `HolisticDetails/HolisticDimensionFeedback/AnalyticDimensionResult/RubricPointHit/AnalyticDetails`、
  `UnifiedSubjectiveGradingResponse`（A4 契约：`total_score` 可空、`feedback_only: bool`、
  `score_basis∈{signed_rubric,unsigned_framework,none}`、`rubric_signed`，`review_status` 含
  `quarantined_for_human` 与 `refused_ungradable_input`）。记忆/FSRS：`ErrorAttributionCategory`（careless/misconception/blindspot/time_pressure/expression_deficit）、
  `ErrorAttributionResult`、`FSRSState`（stability/difficulty[1,10]/due_date/state∈{learning,review,relearning}/reps/lapses）、
  `UserMasteryRecord`、`ErrorReviewEvent`（`is_correct` 是**调用方申报**，由 `MemoryReviewAgent` 按库内答案键 reconcile，A10）、`ReviewBundle`（带 `verdict_source`/`attributable`）。
  诊断：`AnswerSubmission`（`is_correct/node_id/module_id` 均可空，申报字段不是判据）、`ModuleAbility`、`DiagnosticRequest`、
  `DiagnosticReport`（`estimate_basis="coverage_heuristic"`、`publishable=False`、`blocked_submissions`、写死的免责 `disclaimer`）。
  排课：`DailyTaskItem/DailyPlan/PlanRequest(days_until_exam=30 ge=1 le=180, daily_available_minutes=60 ge=15 le=360)/CurriculumPlanResponse`。
  组卷：`PracticeMode`（point_focus/weakness_breakthrough/error_elimination/daily_practice/high_frequency/timed_sprint/mock_exam）、
  `ExamStageState`（**`stage: str` 来自库内 `paper_specs` 的 `parts[].name`，不再是手抄的三段 Literal**）、
  `AssemblePaperRequest(item_count=10 ge=1 le=500)/PracticePaperResponse`（`time_limit_minutes` 库里没给就是 `None`）。
  答疑：`QARequest(mode∈{sparks_three_chain,socratic_hint}, hint_turn=1)`、`SparksThreeChainResponse`、`SocraticHintResponse`。
  面试：`SpeechAnalysisRequest(audio_duration_seconds gt=0)`、`TeachingPhaseMatch`、`SpeechAnalysisResponse`（`overall_score` 未签署恒 null）、
  `LessonPlanReviewRequest/LessonPlanReviewResponse(feedback_only=True)`。编排入口：`UserIntent`（8 值枚举）、
  `MasterInteractionRequest/MasterInteractionResponse`（`card_type` 8 值 Literal、`state="IDLE"`）。检索：`RetrievalRequest(top_k=8 ge=1 le=50)`/`RetrievalResponse`。
- `pacing.py`（61 行）—— 服务侧唯一配速数。常量 `MINUTES_PER_QUESTION: float = 2.0`（**验收 A1 把它钉死只能住在本文件**：
  `test_the_pace_number_has_exactly_one_home` 会扫 `services/**.py` 断言 `MINUTES_PER_QUESTION` 的赋值处只有 `services/common/pacing.py`）。
  `pace_minutes(items)`（`ceil(items * 2.0)`，零题不编时间）、
  `paper_minutes(library_limits)`（先吃库内题面约束、缺的才估，返回 `{total, declared_items, declared_minutes, estimated_items, estimated_minutes}`，题量为 0 时 `total=None`）、
  `pacing_notice(breakdown)`（把"多少来自 `extra.task_constraints.time_limit_minutes`、多少是服务估的"拆开说清）。
  它自己不读库：题面用时的读法在 `knowledge/repository.py::item_time_limit`。被 `practice/agent.py`（`paper_minutes, pacing_notice`）
  和 `planner/scheduler.py`（`MINUTES_PER_QUESTION, paper_minutes`）读。跑：`python -m pytest tests/test_acceptance_gate.py -k pace -q`。
- `safety.py`（108 行）—— 判分链路末端的安全阀（`class SafetyGuard`，`CONFIDENCE_THRESHOLD = 0.60`），是 backstop 不是主判者：
  TrustGate 已决定量规能否出分，这里保证那个决定不在下游被推翻。
  `sanitize_grading_response(response, *, rubric_signed, max_allowed_score) -> (response, quarantined)`：
  `rubric_signed is False` 却出现 `total_score` 时**直接剥掉**（置 `None`、`feedback_only=True`、`score_basis="unsigned_framework"`、
  `review_status="quarantined_for_human"`、附 `UNSIGNED_SCORE_REMOVED`）而不是夹紧放行；越界分数按 `max_score` 钳制，
  解析式维度逐维 `[0, max_score]` 钳制并回写维度之和（差 > 0.5 才改），整体式按 `band_range` 钳制；
  `feedback_only` 与分数不同行；`total_score` 存在但 `confidence_score < 0.60` 转 `quarantined_for_human`。
  `check_disputed_question(answer_status, question_id) -> (bool, str)` 对 `source_conflict`/`missing` 给 `DISPUTE_CONFLICT`/`DISPUTE_MISSING` 措辞。
  读 `services.common.models.UnifiedSubjectiveGradingResponse`，被 `grader/agent.py` 调用。跑：`python -m pytest tests/test_services_safety.py -q`。
- `weakness.py`（27 行）—— 服务侧唯一薄弱线。常量 `WEAK_MASTERY_BAR: float = 0.60`（低于才算薄弱，等于不算；
  **验收 A1 `test_the_weakness_bar_has_exactly_one_home` 要求所有以 `WEAK` 开头的数值常量只住本文件**，改名躲不过）。
  `is_weak(score)`（`score < 0.60`）、`weakness_bar_notice()`（自陈"这是本服务自定的复习触发线，不是库内卷面事实也不是教研分数线"）。
  它明确不是库内数据——`数据集/**` 里没有"多少分算薄弱"这种事实。被 `diagnostic/agent.py`、`planner/scheduler.py`、
  `practice/agent.py`、`master/agent.py`、`learning/workflow.py` 共用，历史教训是诊断曾用 0.60、排课用 0.50、组卷干脆不看线。

## 子目录

无。本目录 4 个 py 文件，扁平存放。

## 改这里之前要知道的

- **本目录没有 `__init__.py`**：`services.common` 靠 Python 3 命名空间包被 `from services.common.models import …` 解析。
  别"顺手"加 `__init__.py` 或改目录名，那会影响所有导入路径。
- **这两个数字是门禁目标**：`MINUTES_PER_QUESTION`（pacing）与 `WEAK_MASTERY_BAR`（weakness）各自只许有一处定义，
  `tests/test_acceptance_gate.py` 会用 AST 扫 `services/**.py` 把多出来的出处判失败；新增第三处（哪怕换个文件名）都会让门禁变红。
- **`TrustTier` 有两份**：这里的 `str, Enum` 和 `knowledge/trust.py` 里的 `Literal`。接口/信封边界用本文件的枚举，
  门面内部裁决用 `Literal`；别把它们当同一个类型互相赋值而不做 `.value`/`TrustTier(...)` 转换（`orchestrator/state_machine.py::_envelope` 就做了显式转换）。
- **申报字段不是判据**：`ErrorReviewEvent.is_correct`、`AnswerSubmission.is_correct/question_difficulty/current_node_mastery` 是调用方自填默认值，
  契约上它们只能被 `knowledge/trust.py::reconcile_verdict` 兜底、或被 `memory/receipt.py` 用来算输入指纹；
  判据归属由 A10 `test_no_inference_path_reads_a_claimed_difficulty_or_mastery` 守住——除 `memory/receipt.py` 外任何 service 代码读出它们都失败。
