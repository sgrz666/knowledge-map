# services/diagnostic/ —— 覆盖度诊断门面：雷达画像的每一格凭什么、为什么不信申报值

这里是"作答提交 → 雷达画像"那一层：`DiagnosticAgent.evaluate` 把一批 `AnswerSubmission` 折算成按模块的掌握率和考点薄弱清单，是学习闭环里"学情"一侧的判据出口。写入方是调用者（`services/app.py` 的 `POST /api/v1/diagnostic/evaluate`、`services/master/agent.py`、`services/learning/workflow.py` 的诊断流程、`services/web/service.py` 的 Workbench），它自己只在被 TrustGate 拒绝时往审查待复核队列（`services/review/queue.py`，产物 `审查/待复核清单.md`）追加行，不写学习状态存储——持久化掌握度归 `services/memory/`。口径（提交 f52f19c3 落成）：掌握度只读学习者自己的作答证据，申报的题目难度与申报的当前掌握度不进判定。改动跑 `python -m pytest tests/test_services_all_agents.py -q`（`TestDiagnosticAgent` 类），判据归属验收在 `tests/test_acceptance_gate.py`（A10）。

## 文件清单

- `agent.py`（294 行）—— `DiagnosticAgent.evaluate(request: DiagnosticRequest) -> DiagnosticReport`，全目录唯一实现文件。流程：① 逐条 `repository.get_meta(question_id)`，不在索引的进 `blocked_submissions`；`TrustGate(request.trust_tier)` 判 `classify_meta(...).usable`，被挡的题连 reason 一起转待复核队列（`queue.add(reason="trust_gate_blocked", detail={"path": "diagnostic", ...})`）。② `published` 档位先按 `SIGNED_STATUSES = {"checked", "expert_reviewed"}` 过滤，库里一题签署都没有就直接拒出结论（返回 `_empty`）。③ 对错判定在 `_attribute`：核对门写死 `TrustGate("research_internal")`（注释说明理由——让调用方自选档位等于让它自选一套更宽的答案键核对口径），逐条调 `reconcile_verdict(record, submission.user_answer, submission.is_correct)`：优先库内答案键（`provenance == VERDICT_SOURCE_KEY`，即"库内答案键核对"），库内核对不了才回退采信申报的 `is_correct`，两边都没有判据的按 blocked 计（不算错，免得把编出来的 0 分放进雷达）；申报与核对结果矛盾时 `logger.warning` 但仍以核对为准。`claimed` 计数聚合进 notice（"X 条采信了调用方申报"）。④ 雷达聚合：`module_stats`/`node_stats` 按判过的对错累计，`radar_chart` 每模块 `mastery_rate = correct/total`（round 3），`weak_points_top5` 取正确率低于 `WEAK_MASTERY_BAR=0.60`（`services/common/weakness.is_weak`，与排课共用同一条线）的考点前 5。⑤ 度量类字段全部置 None：`point_estimate`、`predicted_score_interval`、`pass_probability` 恒空，`estimate_basis="coverage_only"`、`publishable=False`、notices 必带 `COVERAGE_ONLY_NOTICE`——设计文档 §10 因无真实作答校准数据排除了 IRT/CAT/BKT，A7 禁止在未校准路径上用能力测量措辞。辅助：`_library_context` 用 `graph_index.requirements_for` 检查薄弱考点有没有 `aligned_to_requirement` 边，没有就声明给不出条款依据；`_actions` 按考点数可用题池给建议。为什么不许用申报值：模块 docstring 写明"先信申报的话，任何人报 20 次'对'就能拿走一张满掌握雷达"。
- `__init__.py`（8 行）—— 转出 `DiagnosticAgent`，docstring 声明本目录不再有报道分/量表分/IRT 转换模块（§10 明确不做）。

## 改这里之前要知道的

- 核对档位（`research_internal`）与报告档位（`request.trust_tier`）是两件事：前者写死，不许做成参数。
- 答案不可核对的题不进运行时待复核队列——它们已按 `answer_status` 全量列在 `审查/待复核清单.md`，逐人次追加会淹掉唯一一位教研的队列（`_attribute` 内注释）。
- 雷达与薄弱项只读学习者作答证据：调用方传入的题目难度/掌握度申报值在本文件里没有任何消费点，别加回去。
- `__pycache__/` 是生成物。
