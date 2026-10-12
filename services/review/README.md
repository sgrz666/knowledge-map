# services/review/ —— 教研待复核队列：机器挡下的东西只有一个落点

运行时里凡是 `TrustGate` 拒了、编排降级了、模型产出没通过护栏的条目，都必须变成**一条可复核记录**交给人，而不是被静默丢弃或被机器代签。本仓库唯一的人工审核人是教研本人，所以这个模块的写侧永远不填 `checked_by`、不把 `status` 推进到 `checked`/`expert_reviewed`、不写 `expert_verified=true`。写它的是各能力层（诊断、检索、判分、面试、总控、LLM 客户端与护栏、网页"反馈内容问题"按钮），读它的是 `services/app.py::GET /api/v1/review/queue`（`stats()` + `recent(limit)`）和 `tests/test_acceptance_gate.py::TestA9HumanInTheLoop`。落盘位置：`.local_state/review_queue/<缺陷码>.jsonl`（`services/memory/store.py::state_dir()` 的派生目录，不入库，可整目录删除重建）。

改动后跑：

```powershell
$env:KNOWLEDGE_MAP_STATE_DIR = "D:\tmp\kb_state_check"
python -m pytest tests/test_acceptance_gate.py -q -k A9          # 一次拒绝 = 一条可复核行、码在词表内
python -m pytest tests/test_services_api.py -q -k review_queue   # GET /api/v1/review/queue 看得见刚写的行
python -m pytest tests/test_services_api.py -q -k health_probe   # /health 探针不碰真实队列
```

## 文件清单

- `queue.py`（125 行）—— `ReviewQueue`，追加式 JSONL 队列。`__init__(root=None)` 默认根目录 `state_dir() / QUEUE_SUBDIR`（`QUEUE_SUBDIR="review_queue"`，即 `.local_state/review_queue/`；`KNOWLEDGE_MAP_STATE_DIR` 会整体搬走它），`mkdir(parents=True)` 后建 `threading.Lock`。`path_for(bucket)` 把桶名非 `[A-Za-z0-9_.-]` 的字符换成 `_`，空则落 `general`。`add(*, reason, user_id, question_id=None, node_id=None, requirement_id=None, tier=None, source=None, detail=None) -> dict` 先 `describe(reason)`（词表外抛 `UnknownReasonError`，写不进队列），再写一行固定形状：`queued_at`（UTC ISO）、`reason`、`reason_label`（码的人读说明一起入队）、四个 id、`trust_tier`、`source`、`detail`、`status="pending_human_review"`、`reviewer=REVIEWER`（常量 `"教研审核（唯一人工审核人）"`）、`checked_by=None`、`expert_verified=False`。文件名按**缺陷码**分片：一个码一个 `.jsonl`（注释记录了旧写法按 `reason[:60]` 或题号分片导致队列目录按文案历史增长/一题一文件）。`recent(limit=50)` 读全部 `*.jsonl`、坏行跳过、按 `queued_at` 倒序截断。`stats()` 返回 `queue_dir`/`buckets`/`pending_records`/`by_reason`（按计数倒序）/`reviewer`/`note`（写明"签署动作只发生在 审查/待复核清单.md 的人工流程里"）。`get_review_queue()` 进程级单例；`SIGNABLE_FIELDS = ("checked_by", "expert_verified")` 是给人对照的常量，`services/llm/guardrails.py:45` 注释明确镜像了它。跑一条：`python -c "from services.review.queue import get_review_queue as g; print(g().add(reason='trust_gate_blocked', user_id='u1', detail={'note':'demo'}))"`，再 `curl http://127.0.0.1:8000/api/v1/review/queue`（研究档需 `Authorization: Bearer $env:KNOWLEDGE_MAP_RUNTIME_TOKEN`，未设该环境变量时免令牌）。
- `reasons.py`（71 行）—— 缺陷码词表，唯一允许增删码的地方。`REVIEW_REASONS: Dict[str, str]` 现有 9 个码，每个值写明"这条缺陷在说什么 + 教研要动哪个文件"：`learner_content_feedback`（`services/web/routes.py::feedback` 写入）、`trust_gate_blocked`（`services/diagnostic/agent.py`、`services/knowledge/retrieval.py`）、`orphan_card_hit` 与 `card_index_status_mismatch`（检索侧卡片/索引双真相）、`rubric_signature_required` 与 `rubric_missing_for_task`（`services/grader/agent.py`、`services/interview/agent.py`）、`llm_unparseable_payload`（`services/llm/client.py`）、`llm_guardrail_violation`（`services/llm/guardrails.py`，被违反的 schema 名放 `detail.schema_name`）、`orchestrator_degraded`（`services/master/agent.py::_enqueue`，原句放 `detail.reason_text`）。`describe(reason)` 命中返回说明，否则抛 `UnknownReasonError`（消息要求把给人读的文本放进 `detail` 而不是当分类键）。
- `__init__.py`（1 行）—— 只有模块 docstring，包本身不转出名字；调用方一律 `from services.review.queue import get_review_queue` 与 `from services.review.reasons import REVIEW_REASONS, UnknownReasonError`。

## 改这里之前要知道的

- 队列**不读也不写** `审查/待复核清单.md`。那份 markdown 是 `审查/build_review_queue.py` 从 `数据集/**`、`数据集/*/graph/edges*.jsonl` 与题面抽取缺口现算出来的**生成物**（可用 `KM_QUEUE_OUT` 改写输出路径，重跑命令 `python 审查/build_review_queue.py`），`tests/test_acceptance_gate.py:186-204` 会逐字比对"生成器输出 vs 已提交文件"，手改 markdown 就是红灯。运行时队列与它的关系只有一条：同一位教研、同一套"机器不得代签"的约束、行形状对齐，使静态审计发现与运行时降级汇成一条队列而不是两条。
- `reason` 是教研在 `GET /api/v1/review/queue` 里唯一的分类入口，只许取 `REVIEW_REASONS` 的字面量码。给人读的说明句子必须进 `detail`（`tests/test_acceptance_gate.py:1169` 起那段用 AST 扫全仓 `reason=` 实参，非字面量或词表外的码直接失败）。新增一类缺陷 = 在 `reasons.py` 加码 + 让写入方用它，不要在调用点临时拼字符串。
- 代签就是旁路人工：`add()` 里 `checked_by=None` / `expert_verified=False` 两行是 A9 的直接断言点（`assertIsNone(row["checked_by"], "运行时代签 = 旁路人工")`），LLM 侧同一铁律在 `services/llm/guardrails.py`（模型产出最多把 `review.status` 推进到 `llm_enhanced`）。想让某个降级"自动放行"请改数据并让教研签署，别改这里。
- 只有内容侧降级该进队列。调用方缺字段（编排器 `kind == "input_gap"`）、`published` 档的空池（设计上的 fail-closed）都不写行——写进去只会淹没教研真正能决定的条目，见 `services/master/agent.py::_h_practice` 与 `services/orchestrator/state_machine.py` 顶部说明。
- `/api/v1/health` 的探针必须用临时目录构造的 `ReviewQueue(root=...)`（`services/app.py::_probe_resources`），否则每跑一次健康检查就给真实队列加行。
- `.local_state/review_queue/` 是运行时状态、不入库（`.gitignore` 第 65 行），当前工作区已有 `rubric_signature_required.jsonl`、`trust_gate_blocked.jsonl` 两桶；测试请指 `KNOWLEDGE_MAP_STATE_DIR` 到临时目录，否则计数断言会被本机历史污染。
