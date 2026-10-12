# services/planner/ —— 排期门面：日历按库内题池与持久化掌握度生成，本身不落盘

这里是"考点清单 → 逐日日历"那一层：`AdaptiveScheduler` 从知识库里能真实练习的考点（有题、有答案、过信任门禁）排出 N 天日程，`CurriculumPlannerAgent` 包一层请求/响应模型。调用方是 `services/app.py` 的 `POST /api/v1/planner/generate`、`services/master/agent.py` 和 `services/web/service.py` 的 Workbench；本机学习闭环里日程真正被持久化发生在 `services/learning/workflow.py::create_plan`——它调 `generate_plan` 后补 task_id/status 字段、写进 `.local_state/learning.sqlite3` 的 `learning_documents` 表，本目录代码自己只读不写。输入三样：`PlanRequest`（days_until_exam、daily_available_minutes、current_mastery、trust_tier、school_level/subject）、库内题池、`store.due_question_ids` 的 FSRS 到期队列。改动跑 `python -m pytest tests/test_services_all_agents.py -q`（`TestCurriculumPlanner` 类），闭环侧看 `tests/test_learning_workflow.py`，无影子数据验收在 `tests/test_acceptance_gate.py`。

## 文件清单

- `agent.py`（99 行）—— `CurriculumPlannerAgent.generate_plan(request: PlanRequest) -> CurriculumPlanResponse`：把参数转给 `scheduler.schedule(...)`，拼 `total_days`/`milestones`/`prerequisite_note`。`_milestones` 的里程碑文本从已生成的日历里读回（第 1 天考点数与题量、含 `mock_sprint` 任务的天、含 `weakness_drill` 的天、末日的 `new_node_learning` 统计），不预写文案；日历为空时里程碑直说"当前档位内可用考点为空"。
- `scheduler.py`（355 行）—— `AdaptiveScheduler`，算法本体。`candidate_nodes(exam, tier, school_level, subject)`：`repository.find_questions(require_nodes=True, require_answer=True)` 逐题过 `TrustGate(tier).classify_meta(...).usable`，按考点聚出 `pool`（真实题数）、`avg_difficulty`、`requirements`（图谱条款数）、`minutes_per_item`（池内每题用时平均：`QuestionMeta.time_limit_minutes` 即题面约束优先，说不出才按 `MINUTES_PER_QUESTION=2.0` 估，共用 `services/common/pacing`），按题池大小降序排。`schedule(user_id, exam, days, daily_minutes, mastery_records, tier, school_level, subject) -> (List[DailyPlan], notices, prereq_note)`，常量 `REVIEW_SHARE=0.30`（复习格占比）、`NEW_NODE_SHARE=0.55`、`NODES_PER_DAY=2`、`MOCK_EVERY_DAYS=7`（每逢第 7 天且当日预算够才排）。逐日流程：模考格时长取 `repository.mock_minutes_for(exam)`——多套规格给出不一致的用时它就返回 None，此时不排模考并写 notice，不内置 90 分钟；复习格用 `_due_question_ids`（`store.due_question_ids(user_id, limit=20)`）按 `_fit_within` 逐题累加真实用时装满，装不进整题就挂 `REVIEW_UNFIT_NOTICE` 宁少排不拆题；新考点格 `count = min(pool, int(per_node // minutes_per_item))`，30 分钟一题的写作池在 16 分钟格里直接排 0 题；薄弱专项只给 `is_weak(mastery)`（线在 `services/common/weakness`，`WEAK_MASTERY_BAR=0.60`，与诊断同源）的考点，全都不低于线时挂 `NO_WEAK_NODE_NOTICE`。排序 `_rank`：先 `_sort_key`（已掌握且低于线的最前、未练的按题池大小、不虚构 0.40 基线，见 `UNSEEN_NOTICE`），再 `graph.topological_order` 做先修拓扑（§3.3 先修边未确认时它拒绝使用并给 note）。`_mastery_map`：先放入调用方传的 `current_mastery`，再用 `store.weak_node_ids(user_id, limit=20)` 查 `store.get` 的持久化记录覆盖。notices 经 `_dedupe` 去重后随响应返回。
- `__init__.py`（5 行）—— 转出 `CurriculumPlannerAgent`、`AdaptiveScheduler`。

## 改这里之前要知道的

- 旧版此文件自带 `DEFAULT_SYLLABUS_NODES`（13 个写死的教资考点带权重/先修）和 `MOCK_MINUTES = 90`，都是 A1 禁止的影子数据，已删——候选考点只准来自 `repository`，时序读法只在 `repository.timed_stages/mock_minutes` 写一遍。
- 排课的薄弱线必须与诊断共用 `services/common.weakness`：历史上两边各写 0.5/0.6，同一学习者在一条闭环里被两套判定（提交 0960668c 收成一条线）。
- 配速 `MINUTES_PER_QUESTION` 与组卷层共用 `services/common/pacing`，别在本文件另抄一个"每题几分钟"。
- `__pycache__/` 是生成物。
