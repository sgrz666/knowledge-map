# services/llm/ —— 这个目录放什么、谁来用

运行时通往语言模型的**唯一一扇门**（架构方案 §4）：`client.py` 负责 provider 选择与有界重试，`guardrails.py` 负责结构化校验与禁用声称。
它被 `grader/agent.py`（判分时让模型只做措辞改写）和 `web/provider.py`（工作台代填密钥的调用）读；违例一律写进 `review/` 队列交人工。
它不读 `数据集/**` 的题面——唯一的磁盘读是 `数据集/教资/schemas/*.json` 这份 JSON Schema。改这里跑：
`python -m pytest tests/test_services_llm.py tests/test_acceptance_gate.py::TestA7DifficultyWording -q`。
没配 key 时它是默认路径：`app.py` 的 `/health` 会报 `llm_mode="rule_only"`。

## 文件清单

- `__init__.py`（8 行）—— 只有一段实现 §4 的模块 docstring（provider 化、无静默回退、单一权威 Schema 目录、写权限铁律），**无 import、无导出、无逻辑**。
- `client.py`（421 行）—— `class LLMClient` + `@... get_llm_client()` 进程内单例（`_DEFAULT_CLIENT` + `_DEFAULT_LOCK`，env 只在构造时读一次）。
  **Key 从哪来**：只认三个环境变量——`ENV_BASE_URL="KNOWLEDGE_MAP_LLM_BASE_URL"`、`ENV_API_KEY="KNOWLEDGE_MAP_LLM_API_KEY"`、
  `ENV_MODEL="KNOWLEDGE_MAP_LLM_MODEL"`；`_provider_from_env()` 要求三者都非空才建 `OpenAICompatibleProvider`，否则退回 `RuleOnlyProvider`。
  provider 类：`BaseProvider`（`is_rule_only=False`）、`RuleOnlyProvider`（`is_rule_only=True`，`generate()` 直接 `raise LLMUnavailableError`，绝不编造补全）、
  `OpenAICompatibleProvider`（stdlib `urllib.request` POST 到 `{base_url}/chat/completions`，头 `Authorization: Bearer {api_key}`）。
  调用参数：`DEFAULT_TIMEOUT_SECONDS=20.0`、`MAX_RETRIES=2`、`RETRY_BACKOFF_SECONDS=(1.0, 3.0)`、
  `_RETRYABLE_STATUS=frozenset({408,429,500,502,503,504})`。`MODE_LLM="llm"` / `MODE_RULE_ONLY="rule_only"`。
  `SYSTEM_PROMPT` 把模型钉成"教研助理不是审核人"，难度只能说"教研初估"，禁 IRT/CAT/标准误/能力值，只输出一个 JSON 对象。
  `generate(prompt, *, task, schema_name, user_id="llm_runtime", question_id, node_id, requirement_id, max_tokens=2048, temperature=0.2)`：
  对 system 与 user **两条消息都跑 `assert_prompt_not_reviewer`**（审核角色最容易被塞进 system）；
  `is_rule_only` → 返回 `mode="rule_only", ok=False, errors=["no_llm_provider_configured…"]`，provenance `status="not_attempted"`（**明确降级、不发 HTTP、不假装模型答过**）；
  provider 抛 `LLMUnavailableError` → 退回 `mode="rule_only", ok=False`，provenance `status="provider_unavailable"`；
  正常返回 → `_extract_json`（先 `json.loads`，再 `_JSON_BLOCK = \{.*\}|\[.*\]` DOTALL 兜底），
  解析失败 → `guard=GuardResult(ok=False, unparseable_json)` 并 `_route(...)` 入队（`reason="llm_unparseable_payload"`，`no_retry=True`）；
  解析成功 → `enforce_payload(...)`；`ok = guard.ok and not errors`，失败 `status="rejected_by_guardrails"`、payload 置 None，**不在这里重试/修补**。
  `validate_local(payload, schema_name, *, user_id, **ids)`：给规则/启发式草稿单独过护栏（`source="services.llm.client.local"`）。
  `_provenance()` 复用库内 `analysis.generation` 字段名（`requested_model/prompt_sha256/created_at/thinking={"type":"disabled"}/method/status`，
  有响应再加 `response_model/usage/finish_reason/latency_ms/retries`，已对 `数据集/教资/questions/**/*.jsonl` 核对）。
  `_account()` 记账 `calls/llm_calls/rule_only_calls/ok/degraded/retries/total_latency_ms/prompt_tokens/completion_tokens/estimated_cost_cny`
  （保守估价 ¥1/1M prompt、¥2/1M completion）。异常基类 `LLMError`、`LLMUnavailableError`；`ProviderResponse`、`LLMResult` 为 dataclass。
- `guardrails.py`（360 行）—— 对每个 LLM payload 的三类 fail-closed 检查，**任何违例都不修、只转人工**。
  Schema 侧：`REPO_ROOT = Path(__file__).resolve().parents[2]`，`SCHEMA_GLOBS = ("数据集/*/schemas/*.json",)`
  （当前只有 `数据集/教资/schemas/` 命中；两库共用这一份，`四六级` 无自己的 schemas），`SchemaRegistry.paths` 以文件名为键
  （`question/rubric/requirement/user_mastery/practice_framework/paper_spec/…` 等），`load()` 找不到就 `raise SchemaNotFound`（未定义 Schema 一律不放行）。
  校验用 `jsonschema.Draft202012Validator`（可导入时），否则内置 `_fallback_validate` 覆盖
  `type/required/properties/items/enum/const/additionalProperties/同文档 $ref/minimum/maximum/minLength/minItems/allOf`；`validate_payload()` 返回错误、绝不修复。
  **写权限铁律**：`MAX_LLM_STATUS="llm_enhanced"`，`LLM_WRITABLE_STATUSES={"auto_parsed","llm_enhanced"}`，
  `FORBIDDEN_LLM_STATUSES={"checked","expert_reviewed","needs_fix","quarantined"}`，
  `FORBIDDEN_STATUS_FIELDS={"checked_by","expert_verified","content_verified","checked_at"}`；
  `assert_llm_status_allowed / assert_no_forbidden_status_fields / assert_llm_record` 任一被触犯即 `raise LlmWritePermissionError`（模型不得代签、不得推进签署状态）。
  **禁用声称具体拦哪几类话**（`scan_banned_claims(text)`，命中只上报、绝不改写）：
  ① 权威/核定口吻 `BANNED_ASSERTION_PHRASES=("已审核","已核定","审核通过","已通过复核","官方认定","官方审定","官方标准答案")`；
  ② 未校准测量学 `BANNED_DIFFICULTY_CLAIMS=("标准误","能力值","能力估计","题目反应理论")` + 正则 `_BANNED_ASCII=\b(IRT|CAT|item response theory)\b`；
  ③ 提示词侧 `assert_prompt_not_reviewer`（`REVIEWER_ROLE_PATTERNS` 抓"你是/担任/充当…审核人/reviewer"，
  动词内部允许空白以堵住"你 是 审核人"这类插空绕过；`_role_verb_is_negated` 允许紧邻否定词
  "不要担任审核人"这类引用铁律的写法，也认"不要声称/不得冒充你 是审核人"这类转述禁令——
  但转述词隔着句号就是两句，后一句的赋权照样拦下）。
  `enforce_payload(payload, schema_name, *, user_id, question_id, node_id, requirement_id, source, registry, generated_text)`：
  先扫 `generated_text` 的禁用声称、再 `assert_llm_record`、再 Schema 校验；任一不过就
  `get_review_queue().add(reason="llm_guardrail_violation", detail={errors, banned_claims, payload_preview, no_repair=True, next_action:"人工复核；运行时不重试、不修补该 payload。"})`
  并把 `result.queued=True`。结果类型 `GuardResult(ok, schema_name, schema_path, errors[:20], banned_claims, queued)`，`as_dict()` 供 `LLMResult` 序列化。

## 子目录

无。本目录 3 个 py 文件（`__init__.py`、`client.py`、`guardrails.py`）。

## 改这里之前要知道的

- **禁用声称护栏与验收同源**：`tests/test_acceptance_gate.py::TestA7DifficultyWording` 会拿诊断/排课/组卷/答疑/判分/编排的每条输出文本跑
  `scan_banned_claims(...)`，非空即失败。往任何 notice/summary 里加"官方/已审核/能力值/IRT"这类词都会让门禁变红。
- **绝不静默回退**：`client.py` 的设计契约是"没模型参与就明说 `mode=rule_only`、`ok=False`"。加任何"失败就返回一份像样的默认答案"的代码都是破坏信任链。
- **护栏不做二次猜测/修补**：`guardrails.py` 与 `client.py` 都只在违例时入队（`no_repair=True` / `no_retry=True`）。别在这里 retry、重排 JSON 或补字段。
- **env 只在构造时读一次**：`get_llm_client()` 是进程单例，改环境变量后需新建进程（或测试里显式 `LLMClient(provider=...)`）才生效。
  工作台网页把 Key 只留在当前页面内存，由 `web/provider.py` 现建 provider，不是走本文件的全局单例。
- **Schema 目录是共享权威源**：`数据集/教资/schemas/` 的 README 禁止为四六级单开一份；新增 `schema_name` 若在该目录不存在会 `SchemaNotFound`（fail closed），
  而不是放行未校验的 payload。
