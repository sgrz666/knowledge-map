# services/exam_sessions/ —— 服务端计时模考：时限与收卡由后端记，不信任浏览器时钟

给网页"分阶段模考 · 服务端计时"模式提供一场**能在刷新/重开后继续**的模考：起始即按库内卷面规格算出每一节的绝对起止时刻，作答只在所属小节开放时收，到点自动收卡，交卷前不下发讲评。写它的是 `services/web/service.py::Workbench`（`self.exam_sessions = ExamSessions(self)`），读它的是 `web/workflows.js` 的 `startExam/restoreExam/refreshExam/renderExam`，落库文件是 `services/web/store.py::WorkbenchStore` 那一份 `.local_state/workbench.sqlite3`（本目录在其中新建 `exam_sessions`、`exam_admissions` 两张表，并共用它的 `store.lock` 与连接，不另开库）。接口全部挂在 `services/web/routes.py` 之下，因此沿用同一道运行时令牌校验：`POST /api/v1/web/exam/start`、`/exam/latest`、`/exam/{session_id}/state`、`/exam/{session_id}/advance`、`/exam/{session_id}/submit`、`/exam/{session_id}/finish`（全是 POST，因为作用域/user_id 走请求体）。

改动后跑（本轮实测：`tests/test_exam_sessions.py + tests/test_learning_workflow.py` 一起 17 passed，64.02s）：

```powershell
$env:KNOWLEDGE_MAP_STATE_DIR = "D:\tmp\kb_state_check"   # 否则模考行会写进本机 .local_state/workbench.sqlite3
python -m pytest tests/test_exam_sessions.py -q
python -m pytest tests/test_acceptance_gate.py -q -k "exam_clock or timetable or pace_number or own_exam_length"
.\start_web.ps1           # 手工验收：练习视图选"分阶段模考 · 服务端计时"，刷新页面看计时是否续上
```

## 文件清单

- `models.py`（16 行）—— 两个请求模型，都 `model_config = ConfigDict(extra='forbid')` 且继承 `services/web/models.py::WebContext`（`user_id`/`exam_type`/`school_level`/`subject`/`trust_tier`）。`ExamStartRequest` 多两个字段：`request_id`（1–120 字符，幂等键）、`spec_id`（可选，指定卷面规格）。`ExamContext` 是空体：状态变更请求**不接受**客户端时钟、也不接受任意小节序号——阶段推进只由服务端墙上时间决定，多余的键直接被 pydantic 拒掉。
- `routes.py`（36 行）—— `build_router(workbench)`：`APIRouter(prefix='/exam', tags=['服务端计时模考'])`，`service = workbench.exam_sessions`，六个 POST 端点逐一对应 `service.start/latest/state/advance/submit/finish`。注释写明必须在 web 主路由之下 include（`services/web/routes.py:78`），否则拿不到主路由 `router.dependencies` 里那两道 `Depends(auth_dependency)` 档位校验。
- `service.py`（325 行）—— `ExamSessions(workbench, *, clock=None)`，本目录主体。
  - 构造：`with self.store.lock` 里 `CREATE TABLE IF NOT EXISTS exam_sessions(id, paper UNIQUE, user, request_id, request_fingerprint, data, UNIQUE(user, request_id))` 与 `exam_admissions(paper, question, fingerprint, accepted_at, PRIMARY KEY(paper, question))`；`clock` 注入时必须是带 tz 的 datetime（`_now()` 校验后转 UTC），`tests/test_exam_sessions.py` 靠它拨表测收卡。
  - `start(req)`：先算 `request_fp = fingerprint(req.model_dump(exclude={'request_id'}))`，命中同一 `(user, request_id)` 且指纹相同就回放原快照、指纹不同 409；否则 `_select_spec(req)` → `workbench.practice(WebPracticeRequest(..., practice_mode=PracticeMode.MOCK_EXAM, spec_id=...))` 出题（成卷由 Workbench 存进 `papers` 表），题空时 `DELETE FROM papers` 再 409；`_make_stages(spec, paper, now)` 逐节把 `now` 往后推，`session_id = 'exam-'+uuid4hex`，notices 里剔掉旧版"尚未执行逐节收卡/系统不内置模考时序"两句、换成"服务端保存考试起止时间……已结束的小节无法继续作答""当前为库内规格模拟……不提供官方报告分"，NTCE 追加整卷时长说明，听力节追加 `_audio` 的时序免责；最后 `UPDATE papers SET data=?`（写入 `exam_session_id`、改标题为【服务端计时模考】、`time_limit_minutes = Σ duration_seconds/60`）+ `INSERT INTO exam_sessions`。
  - `_select_spec(req)`：`workbench.repo.paper_specs(req.exam_type)`，按 `spec_id`、`school_level`、`subject` 过滤（筛空 404/409，不退到别的科目），CET 按 `year`+`paper` 倒序取最新一套；CET 必须 `repository.timed_stages(spec)` 非空且每节分钟 > 0，非 CET 必须 `total_duration_minutes` 为正，否则 409"缺少完整逐节时长/整卷时长，暂不能开始计时模考"。
  - `_make_stages(...)`：CET 用 `repository.timed_stages(spec)`（读 `数据集/四六级/manifest/paper_specs.jsonl` 的 `parts[].duration_minutes` 与 `lock_policy`），其它考试退化为单节 `整卷作答`；题目按 `spec['parts'][i]['question_ids']` 钉位，钉不住时按 `q['module'] == stage['module']` 或 `q['section'] == stage['name']` 归节；有题归不进任何节就 409。每节记录 `duration_seconds`/`starts_at`/`ends_at`/`question_ids`/`sheet_submission`/`allow_backtrack`/`can_submit_early=False`/`audio`。
  - `_audio(stage, ids, questions)`：靠 `stage['module']=='听力理解'` 或节名含 `listening` 判定听力，`mode` 取 `source_audio`/`unavailable`/`not_applicable`，`urls` 从题目 `audio_url` 去重；`verified_timing=False`、`strict_playback=False`，notice 明说"切片及官方播放时序未经逐段核验，本节按库内分钟数计时"。
  - `_refresh(data, now)`：唯一的时序推进逻辑，纯墙上时间比对——整场过点即 `status='completed'`、`finish_reason='timeout'`；每节按 pending/active/collected 重算并 `_save`。`advance()` 只是 `state()` 的别名（`"""Reconcile elapsed wall time; callers cannot choose or accelerate stages."""`），没有"跳到第 N 节"的入参。
  - `_snapshot(data)`：给前端的整份现状，含 `server_now`、每节 `time_remaining_seconds` 与 `input_locked = status != 'active'`、`current_stage`、`allowed_question_ids`（当前节题号减去 `input_blocked` 的缺图题）、`locked_question_ids`、`collected_stages`/`collected_sheets`（按 `sheet_submission` 归组）、未完成时 `submissions` 走 `_ack` 只回执不给讲评、完成后才带 `results`。`_results(...)` 汇总已交题数/客观题正确率/主观题条数，`official_score=None` + 一句"不是官方评分"。
  - `guard_submission(req, paper)` / `mask_submission(paper_id, response)` / `submit(session_id, req)`：`guard_submission` 是 `Workbench.submit` 的强制前置（模块 docstring 写明调用次序：归属/档位/成员校验之后、回执查询与记忆写入之前）——无注册会话的普通练习卷原样放行；否则核 user、档位、题目归属，再查 `exam_admissions`：同指纹允许重试（半途失败后的补写），异指纹 `verify_receipt` 抛 `ReceiptConflict` → 409；已过点或非当前节题目 → 409"该题所属小节尚未开始或已收卡"；`input_blocked` → 409。首次放行才 `INSERT INTO exam_admissions`。`mask_submission` 在两条返回路径（新判分、旧回执）与所有恢复路由（`services/web/routes.py::paper`、`Workbench.profile`）上都得调，未完成时把响应折成 `_ack`（只留 `paper_id/question_id/user_answer/time_spent_seconds/submitted_at` + `accepted=True, deferred_feedback=True`）。`submit()` 里 `req.paper_id != data['paper_id']` 直接 409。
- `__init__.py`（5 行）—— 转出 `ExamSessions` 与 `build_router`；`services/web/service.py` 用前者、`services/web/routes.py` 用后者。

## 子目录

- `__pycache__/`：字节码生成物。

## 改这里之前要知道的

- 分钟数只有库内这一个来源：本目录**不 import** `services/common/pacing.py`。`pacing.MINUTES_PER_QUESTION = 2.0`（以及 `paper_minutes`/`pacing_notice`）是给"非模考的单题估时"用的，只有 `services/practice/agent.py` 与 `services/planner/scheduler.py` 用它；模考一节多少分钟必须等于 `repository.timed_stages(spec)` 里的 `duration_minutes`。三道门禁钉着这件事：`tests/test_acceptance_gate.py::test_the_exam_clock_is_the_blueprint_not_a_transcript`（逐节名称与分钟必须原样等于规格）、`test_the_state_machine_holds_no_transcribed_timetable`（`services/practice/cet_statemachine.py` 里除 0/1/60 之外不许出现整数字面量）、`test_no_service_layer_ships_its_own_exam_length`（服务层不许出现 `MOCK_MINUTES` 这类自有时长常量）、`test_the_pace_number_has_exactly_one_home`（`MINUTES_PER_QUESTION` 只许住在 pacing.py）。在这里加"听力 30 分钟"这种常量会直接把这几条踢红。
- 库里 126 套 CET 规格的逐节合计（125）与 `total_duration_minutes`（130）本来就打架，本目录的处理是**按逐节推进、把矛盾交给教研**（见 `docs/agent_architecture.md` §6 与 `审查/待复核清单.md`）；不要在这里"顺手改成 130"或取平均。
- `input_locked` 与 `deferred_feedback` 是两件事：前者决定这一题现在能不能提交（由 `_refresh` 的墙上时间算出），后者决定交卷前看不看得到讲评。前端 `web/workflows.js::renderExam` 只按 `allowed_question_ids` 过滤渲染、按 `server_now` 与 `ends_at` 之差倒计时，所以 `_snapshot` 少给任一字段，页面就会要么放开输入要么提前泄答案。
- 会话数据在 `.local_state/workbench.sqlite3`（WAL，运行时状态，不入库）：删库等于所有模考与提交记录消失，`tests/` 一律指 `KNOWLEDGE_MAP_STATE_DIR` 到临时目录。本目录与 Workbench 共用一个连接和 `RLock`，所有公开方法都在 `with self.store.lock` 里跑；新增入口别绕过这把锁，也别假设能和 `learning.sqlite3` 组成跨库事务（默认只跑一个 worker，见 `docs/web_agent_architecture.md`）。
- 收卡后的重试口径：`exam_admissions` 里的准入指纹让"半途失败后的补写"合法，但**换答案必被 409**（`ReceiptConflict`）。想让学习者重做只能重新开考一场（新 `request_id`）。
- 别把这里当成 `services/practice/cet_statemachine.py` 的替代品：那份是内存态的节状态机（`stage_state`，供组卷响应携带），这一份是持久化服务端时限；两者的逐节读法都只能来自 `repository.timed_stages`。
