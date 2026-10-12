# services/ —— 这个目录放什么、谁来用

这里是 agent 运行时（架构方案里的 F 层）：把 `数据集/**` 与 `官方权威资料/**` 里的结构化数据，
经 `knowledge/` 这个唯一读数据门面 + TrustGate 可信裁决，组装成 FastAPI 接口和自研编排闭环。
本目录顶层只有两个 py：`__init__.py` 是包标记，`app.py` 是 HTTP 入口；全部能力实现放在下面 16 个子模块里。
谁往里写：改 agent 逻辑的工程师；谁从里读：`web/` 工作台与 `tests/`。运行时不手抄任何题面/卷面数据，
一律经 `knowledge/repository.py` 从 `数据集/教资/questions`、`数据集/四六级/questions` 等路径取数。
改这里要跑：`python -m pytest tests/test_acceptance_gate.py -q`（它会 AST 扫描 `services/**.py` 找影子数据常量）；
起服务：`python -m uvicorn services.app:app --host 127.0.0.1 --port 8000`（或仓库根 `.\start_web.ps1`，默认端口 8000）。

## 文件清单

- `__init__.py`（2 行）—— 包标记：只声明 `__version__ = "1.0.0"`，无逻辑；被 `import services` 与所有 `services.x.y` 子模块导入时执行。
- `app.py`（556 行）—— FastAPI 入口（`app = FastAPI(title="H-MAATS Adaptive Exam Agent Services", version=VERSION)`，`VERSION="1.2.0"`）。
  顶层建模块级单例：`repository=get_repository()`，再用同一 `repository` 构造 8 个能力 agent
  （`grader_agent/memory_agent/diagnostic_agent/planner_agent/practice_agent/qa_agent/interview_agent/master_agent`）、
  `retrieval_service=get_retrieval_service()`、`review_queue=get_review_queue()`。
  鉴权常量 `ENV_RUNTIME_TOKEN="KNOWLEDGE_MAP_RUNTIME_TOKEN"`。逐路由见下一节。跑：`python -m uvicorn services.app:app --host 127.0.0.1 --port 8000`，打开 `http://127.0.0.1:8000/`；接口文档 `/docs`。

## app.py 逐路由 / 逐能力

所有 POST/GET 业务路由都通过 `Depends(AuthContext.from_header)` 拿 `Authorization` 头，再调 `auth.require(tier)`。
`AuthContext.require`（类在 app.py，不在 common）的具体行为：读 `os.environ["KNOWLEDGE_MAP_RUNTIME_TOKEN"].strip()`，
**只有当请求档位是 `research_internal` 且环境变量非空时**才校验——取 `authorization.removeprefix("Bearer ").strip()`，
用 `secrets.compare_digest(supplied, token)` 比对，缺失或不符抛 401；`published` 档永不要求令牌（它当前是空集）。
环境变量未配置时 `research_internal` 直接放行（本地开发默认）。

- `GET /api/v1/health`（参数 `probe: bool = Query(default=True)`）→ `HealthResponse`。`probe=true` 时调 `_readiness()`：
  在 `tempfile.mkdtemp(prefix="hm-probe-")` 里建一次性 `ReviewQueue` 和 `SessionStore(root/"orchestrator.sqlite3")`，
  用真实题号（`repository.find_questions(exams="NTCE", require_nodes=True)`，主观题取 `question_types=("材料分析","简答")`）
  逐个跑 14 项探针（KnowledgeRepository/GraphIndex/VectorCardIndex/TrustGate/TutorQA/SubjectiveGrader/PracticeEngine/
  CurriculumPlanner/Diagnostic/MemoryReview/InterviewCoach/TutorMaster/RetrievalService/ReviewQueue），坏的报告
  `agents_not_ready`（带异常文本），最后 `sessions.close()` + `shutil.rmtree` 清临时目录——健康检查绝不写真实队列或学习者状态。
  `llm_mode` 取 `get_llm_client().is_rule_only`（无 key 报 `rule_only`，有 key 报 `llm`）。`?probe=false` 跳过全部探针。
- `POST /api/v1/retrieval/search` → `RetrievalResponse`。`auth.require(request.trust_tier)` 后调
  `retrieval_service.search(query, exam, tier, k=top_k, user_id, modules, question_types, levels, use_graph)`（三路召回+门禁过滤）；
  返回结果 `model_validate` 失败转 500。
- `GET /api/v1/review/queue`（参数 `limit=Query(50, ge=1, le=500)`）—— 人工教研唯一入口，**恒要 `research_internal` 令牌**；
  返回 `review_queue.stats()` + `review_queue.recent(limit)`。绝不自动签署。
- `POST /api/v1/grade/subjective` → `UnifiedSubjectiveGradingResponse`：`grader_agent.grade(request)`，量规未签署只出反馈不出分。
- `POST /api/v1/memory/review`（体 `ErrorReviewEvent`）→ `ReviewBundle`：**恒要令牌**；`memory_agent.process_event`，按库内答案键核对后更新 FSRS。
- `GET /api/v1/memory/mastery/{user_id}/{node_id}` → `UserMasteryRecord`：**恒要令牌**（画像可按 user_id 枚举，属个人数据）；`None` 转 404。
- `POST /api/v1/diagnostic/evaluate` → `DiagnosticReport`：`diagnostic_agent.evaluate`（覆盖度启发式，无 IRT/CAT）。
- `POST /api/v1/planner/generate` → `CurriculumPlanResponse`：`planner_agent.generate_plan`（先修边未核定不入排序）。
- `POST /api/v1/practice/assemble` → `PracticePaperResponse`：`practice_agent.assemble_paper`（从真实索引题组卷）。
- `POST /api/v1/qa/query` → `Union[SparksThreeChainResponse, SocraticHintResponse]`：`qa_agent.answer_query(request)`。
- `POST /api/v1/interview/speech` → `SpeechAnalysisResponse`：`interview_agent.analyze_speech`。
- `POST /api/v1/interview/lesson_plan` → `LessonPlanReviewResponse`：`interview_agent.review_lesson_plan`。
- `POST /api/v1/master/chat` → `MasterInteractionResponse`：`master_agent.handle_interaction`（走 orchestrator 闭环）。
- `GET /api/v1/qa/stream`（SSE，参数 `question_id/user_id/mode/trust_tier`）→ `_stream(qa_agent.answer_query, "qa_card")`。
- `GET /api/v1/master/stream`（SSE，参数 `message/user_id/session_id/exam_type/trust_tier`）→ `_stream(master_agent.handle_interaction, "master_card")`。
  SSE 帧序列由 `_stream` 固定：先 `event: status`（`{stage:"running", card_type}`）；同步 agent 调用经
  `anyio.to_thread.run_sync` 跑在线程里；成功发 `event: card`（`result.model_dump()`）再 `event: done`
  （`{trust_tier, notices}`）；异常发 `event: error`（`{detail, degraded:true}`）再 `event: done{}`。
  `_sse` 用 `StreamingResponse(media_type="text/event-stream")` 包装。凡门禁没放行的内容一律不出现在流里。
- 工作台挂载：`app.include_router(build_router(AuthContext.from_header))`（路由在 `services/web/routes.py`），
  `WEB_ROOT = Path(__file__).resolve().parents[1]/"web"`（即仓库根 `web/`），`app.mount("/assets", StaticFiles(WEB_ROOT))`，
  `GET /` → `FileResponse(WEB_ROOT/"index.html", headers={"Cache-Control":"no-store"})`。无浏览器 CORS/密钥代理。

## 子目录（16 个子模块导航）

- `common/`：共享契约层。`knowledge/`：唯一读数据门面。`llm/`：结构化输出与禁用声称护栏。`orchestrator/`：自研状态机与会话持久化。
- `master/`：编排入口 agent。`diagnostic/ planner/ practice/ memory/ grader/ interview/ qa/`：七个能力 agent。
- `review/`：运行时降级的人工复核队列。`web/`：网页工作台 HTTP 入口与运行态存储。`learning/`：web 侧学习闭环。`exam_sessions/`：web 侧限时模考会话。

| 子模块 | 角色 | 入口文件 | 依赖（services 内其它子模块） |
| --- | --- | --- | --- |
| `common/` | 共享 Pydantic 模型与口径常量（被几乎所有模块读，自身几乎不依赖别人） | `models.py` | `safety.py`→`models`；`pacing/weakness` 无内部依赖 |
| `knowledge/` | 全库唯一读数据门面：字节偏移索引 + TrustGate + 图谱 + 向量 + 三路召回 | `repository.py`（取数）/`retrieval.py`（召回） | `naming`、`trust`、`graph_index`、`vector_index`；`retrieval`→`review.queue` |
| `llm/` | 模型调用唯一门 + Schema/写权限/措辞护栏 | `client.py` | `guardrails`；违例经 `enforce_payload`→`review.queue` |
| `orchestrator/` | §2.1 闭环状态机 + 会话信封 SQLite 持久化 | `state_machine.py`/`session.py` | `state_machine`→`common.models`；`session`→`memory.store` |
| `master/` | 编排网关：把 8 能力 agent 注册为 orchestrator 节点并跑闭环 | `agent.py` | 全部能力 agent + `knowledge`、`orchestrator.{session,state_machine}`、`review.queue`、`memory.store` |
| `diagnostic/` | 能力 agent：覆盖度诊断雷达 | `agent.py` | `knowledge.{graph_index,repository,trust}`、`common.{models,weakness}`、`review.queue` |
| `planner/` | 能力 agent：日历排课（FSRS 到期+新学+模考+薄弱专项） | `agent.py` | `knowledge.{graph_index,naming,repository,trust}`、`common.{models,pacing,weakness}`、`memory.store` |
| `practice/` | 能力 agent：组卷/模考时序机 | `agent.py` | `knowledge.{naming,repository,trust}`、`common.{models,pacing,weakness}`、`memory.agent` |
| `memory/` | 能力 agent：FSRS 调度+错因归因+SQLite 画像持久化 | `agent.py` | `knowledge.{repository,trust}`、`common.models`；`store.py` 落 `.local_state/` |
| `grader/` | 能力 agent：主观题判分（未签署量规只出反馈） | `agent.py` | `knowledge.{repository,trust}`、`common.{models,safety}`、`llm.client`、`review.queue` |
| `interview/` | 能力 agent：试讲语音指标 + 教案点评 | `agent.py` | `knowledge.{repository,trust}`、`common.models`、`grader.evidence`、`review.queue` |
| `qa/` | 能力 agent：Sparks 三链讲解 + 苏格拉底多轮提示 | `agent.py` | `knowledge.{repository,trust}`、`common.models` |
| `review/` | 运行时降级记录的人工复核队列（JSONL 落盘，唯一人工入口） | `queue.py` | `memory.store.state_dir`、`review.reasons` |
| `web/` | 网页工作台 HTTP 入口 + 运行态存储 + LLM 密钥代理 | `routes.py` | 几乎所有子模块 + `learning`、`exam_sessions`；`store.py` 落 `.local_state/` |
| `learning/` | web 侧学习闭环（诊断→规划→练习→面试）编排与路由 | `workflow.py`/`router.py` | `common.{models,weakness}`、`knowledge.{graph_index,learning_resources,trust}`、`grader.evidence`、`planner.agent`、`web.models` |
| `exam_sessions/` | web 侧限时模考会话（收卡/封锁时序）服务与路由 | `service.py`/`routes.py` | `common.models`、`knowledge.repository.timed_stages`、`memory.receipt`、`web.{models,store}` |

## 改这里之前要知道的

- **影子数据门禁会红**：`tests/test_acceptance_gate.py::TestA1NoShadowData` 会 AST 遍历 `services/**.py` 的每个字符串常量
  （长度 > 40），一旦命中"题面/条文形态"正则（填空括号、A–D 并列选项、【答案】/【解析】块）就失败；也禁止出现
  `SAMPLE_QUESTION_BANK`/`PROVENANCE_DB` 这类常量名，禁止自有 `MOCK_MINUTES`、`MINUTES_PER_QUESTION`（只能住 `common/pacing.py`）、
  `WEAK*` 数值常量（只能住 `common/weakness.py`）。所有题面/答案/卷面规格都必须从门面取数。
- **published 档是空集**：当前无任何具名签署题，`TrustGate("published")` 走 `fail_closed()`，接口只回 `no_qualified_content`。别为了让某档"有内容"而放宽判据。
- **别名依赖**：`repository.py` 的 `REQUIREMENT_FILES` 同时列了 `官方权威资料/requirements.jsonl` 与别名路径 `权威资料/requirements.jsonl`，
  条款 `locator.text_path` 以 `权威资料/` 开头——本仓库根的 `权威资料/`、`教资/` 是指向真实目录的工作区链接，缺失会致门面读不到数据。
- **幂等重跑**：`knowledge/`、`vector_index`、`review.queue` 都是可重建产物；`chroma/` 与 `.local_state/` 不入库，改数据后靠指纹增量重建而非重启。
