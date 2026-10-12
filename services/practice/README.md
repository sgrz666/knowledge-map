# services/practice/ —— 组卷门面：七种练习模式怎么选题、模考时序按什么推进

这里是出题链路的组卷层：把 `数据集/**/questions` 索引出的真实题目按七种练习模式（考点专练/薄弱突击/错题消灭/每日一练/高频冲刺/限时快练/全真模考）组装成一卷。上游调用者是 `services/app.py` 的 `POST /api/v1/practice/assemble`、`services/master/agent.py` 和 `services/web/service.py` 的 Workbench（后者把成卷存进 `.local_state/workbench.sqlite3` 的 papers）。判分不在这里：客观题对错由提交链路走 `TrustGate.reconcile_verdict`（见 `services/web/service.py::Workbench.submit`），主观题走 `services/grader/`。本目录只读库、不写盘。改动后至少跑 `python -m pytest tests/test_services_all_agents.py -q`（`TestPracticeEngine` 类），数据侧断言在 `tests/test_services_data_source.py`，无影子数据验收在 `tests/test_acceptance_gate.py`。

## 文件清单

- `agent.py`（516 行）—— `PracticeEngineAgent` 组卷主体。入口 `assemble_paper(req: AssemblePaperRequest) -> PracticePaperResponse`：先 `repository.find_questions(exams, require_answer=True)` 拿有答案的题池、剔除无题面文本的（`has_answerable_text`）、再 `TrustGate.filter_usable` 按档位过滤，`pool_size`/`shortfall` 报的是过滤后真实数。七模式分流在 `_select_adaptive`：`ERROR_ELIMINATION` 用 `req.wrong_question_ids` 或 `MemoryReviewAgent.due_question_ids(user_id)`（FSRS 到期队列），跳过不在库/无题面/无答案键三类错题并逐类写 notices；`WEAKNESS_BREAKTHROUGH` 用传入 `weak_node_ids` 或 `memory.weak_node_ids`（后者是相对最低排序，notice 里明确不等于低于薄弱线 `WEAK_MASTERY_BAR=0.60`，线住在 `services/common/weakness.py`）；`TIMED_SPRINT` 只取 `answer_status == "letter_only"`；`HIGH_FREQUENCY` 按考点覆盖度排序。`_select_mock` 逐节走 `repository.paper_specs(exam_type)` 的 `sections/parts`：钉死 `question_ids` 的按 id 发、缺题如实报数，没钉的按 `section/question_type` 补足 `count`，`_pick_spec` 优先 `req.spec_id`、CET 默认取最新年份套卷（按 year+paper 倒序）。`_stable_sample` 用 `sha256(user_id|今天|mode)` 做种子洗牌——同一人同一天同一模式可复现同一卷。`_materialise` 逐题 `repository.load_question` + `gate.classify_record`，题面带 `review_status/answer_status/difficulty`（label 固定"教研初估"、calibration="heuristic"），答案只在 `TrustTier.RESEARCH_INTERNAL` 且 `verdict.may_assert_answer` 时随卷下发。限时口径在 `_time_limit`/`_timing_notices`/`_constraint_conflicts`：模考只认库内 `timed_stages(spec)` 的逐节用时（`repository.mock_minutes`），逐节与 `total_duration_minutes` 打架时"只报不改"；非模考逐题问 `item_time_limit(record)`（题面约束 `extra.task_constraints`），说不出才落 `services/common/pacing.paper_minutes` 的共用配速并在 notices 拆开报"多少来自库内、多少是估的"。另有 `node_frequency(exam, top=12)` 按卷数考点覆盖度。`paper_id` 由 `_token`（sha256 前 8 位）拼出。
- `cet_statemachine.py`（83 行）—— `CETExamStateMachine` 模考时序机，管的是一份卷"现在在第几节、还剩多少秒、答题卡收没收"的状态（`ExamStageState`），不含任何卷面常数。`get_initial_state(spec)` 从 `repository.timed_stages(spec)`（读 `数据集/四六级/manifest/paper_specs.jsonl` 的 `parts[].duration_minutes`）取第一节生成初始状态，库内说不出逐节用时就返回 `None`——`assemble_paper` 把它填进 `PracticePaperResponse.stage_state`。`step_stage(current_state, elapsed_seconds, spec)` 先扣时、到点推进到规格里的下一节：当前节声明了 `sheet_submission` 就记 `sheet_collected=True`；状态里的小节名不在这份规格里（换卷/教研改了卷面）返回 `None` 拒绝推进；走完最后一节进 `COMPLETED_STAGE="completed"` 终局态（`input_locked=True`）。`input_locked` 只留给终局：卷面 `lock_policy` 的"本节不许回头"由 `can_switch_modules=bool(stage["allow_backtrack"])` 表达，混用会让学习者在听力刚开局就被锁死输入。`step_stage` 目前只有 `tests/test_services_all_agents.py`（约 550–591 行处）在驱动推进，运行时尚未接生产调用方。
- `__init__.py`（5 行）—— 转出 `PracticeEngineAgent`、`CETExamStateMachine`。

## 子目录

- `__pycache__/`：字节码生成物，可删可重建，不作为任何模块存在的证据。

## 改这里之前要知道的

- 模块里不许出现题目、答案、难度值或卷面用时常量（验收 A1 无影子数据）：旧版时序机写死的"写作 30 / 听力 30 / 阅读+翻译 70"就与库内 30/25/40/30 打架过，导致同一响应两套时间表。逐节读法只允许写在 `repository.timed_stages` 一处。
- 空结果要说空：题池为空返回 `NO_CONTENT_NOTICE`、缺输入返回 `NO_INPUT_NOTICE`，绝不补造题目；题干抽取缺口（只剩套名）单独计数写进 notices。
- 组卷响应依赖 `MemoryReviewAgent` 的 FSRS 队列（错题消灭、薄弱突击两模式），动 `services/memory/store.py` 的 `due_question_ids`/`weak_node_ids` 语义要连带回归本目录测试。
- `_stable_sample` 的确定性按天滚动：测试复现要固定 `seed_extra` 语义，别改成随机。
