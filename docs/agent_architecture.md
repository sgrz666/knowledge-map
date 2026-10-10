# Agent 架构设计方案（教资 NTCE / 四六级 CET 双库）

> 状态：设计定稿，待实现。日期 2026-10-10。
> 上位文档：`应试考证功能设计与技术支撑：以教资和四六级为例.md`（下称"设计文档"）。
> 本方案只做一件事：把设计文档已定死的**数据契约**（八层 L0–L7、16 种边、三层状态、双轨量规）翻译成可运行的 agent 运行时。设计文档对编排层只字未提（全文无 agent/编排/LangGraph/流式/工具调用字样），所以本方案是**补齐**，不是改写。

## 0. 已定决策

| 决策项 | 取值 | 理由 |
| --- | --- | --- |
| 编排 | **自研状态机**（不用 LangGraph/LangChain） | 边名词表、状态词表、量规双轨都在我们自己手里；外部框架只带来检查点与可视化，代价是多一套依赖与一套自己的状态语义 |
| 向量库 | **Chroma** | 零运维、本机即跑，与设计文档 §5.1"原型与中等规模直接采用 pgvector/Chroma"一致；索引全部可从 `数据集/**` 重建，坏了就删 |
| 图引擎 | **NetworkX 单机内存**，`edges.jsonl` 全量加载 | 设计文档 §5.1 已论证（教资 22,104 节点/96,774 边、四六级 25,659/86,688 内存图性能极佳且零运维）；复杂拓扑再演进 Neo4j |
| 异步与队列 | **不引入 Celery/Redis；批量回填走 stdlib 离线 CLI** | 运行时只有分钟级的 Chroma 冷启动与离线解析回填需要"后台"，两者都可以重跑且无并发诉求；为此常驻 worker 只多两套运维。落地口径见 §3.5 |
| 仓库可见性 | **public**（所有者 2026-10-10 明确同意继续公开推送） | 风险留痕见 §9，不再重复劝阻 |

## 1. 现状事实（全部带证据，不靠印象）

### 1.1 服务层已经建成 8 个 agent、10 条路由，但读的是另一份数据

| 事实 | 证据 |
| --- | --- |
| 组卷用 4 条硬编码样例题，不读 14,500 道真题 | `services/practice/agent.py:15` `SAMPLE_QUESTION_BANK`，`:95` 按它筛题 |
| 法条溯源用 4 条硬编码条文，不读 6,255 条条款 | `services/qa/sparks_chain.py:9` `PROVENANCE_DB`，`:60` 按 node_id 取 |
| 讲评结论硬编码"本题答案为 B"，与实际题无关 | `services/qa/sparks_chain.py:69` |
| 两库图谱、12,881 张卡片零读取；仅读两个量规文件 | `services/grader/cet_holistic.py:22`、`ntce_analytic.py:23` |
| CET 量规加载函数是死代码，从未被调用 | `services/grader/cet_holistic.py:55` `load_rubric` |
| 无 LLM 调用层：`llm_client=None` 存而不用，`llm_response` 从不传入 | `services/grader/agent.py:27,59-61` |
| 学习状态是进程内 dict，重启即丢 | `services/memory/agent.py:26,90` |
| 总控只做关键词路由并回话术卡片，不调任何子 agent；`AgentMessageEnvelope` 定义后零使用 | `services/master/agent.py:12,16,22` |
| `agents_ready` 是硬编码字符串列表而非探测 | `services/app.py:69-79` |
| 库内不变量（`research_non_commercial`、`official_scoring`、`expert_verified`、`heuristic_*`）在 services 内零落地 | services/ 全量 grep 命中 0 |

这轮刚在数据层清掉"双真相"（影子量规、`generation_source` 假字段），同一类问题立刻在服务层以 `SAMPLE_QUESTION_BANK` / `PROVENANCE_DB` 的形态复现。**本方案的第一原则就是不允许它存在。**

### 1.2 真实题池（2026-10-10 实测，决定架构而非细节）

| 指标 | 教资 NTCE | 四六级 CET |
| --- | --- | --- |
| 题目总数 | 14,500 | 5,632 |
| `review.status` | needs_fix **13,460**、quarantined **1,040** | auto_parsed 5,354、needs_fix 177、quarantined 101 |
| 已签署（checked/expert_reviewed） | **0** | **0** |
| `content.answer_status` | letter_only 9,972、reference_only 3,339、source_conflict 1,040、missing 149 | missing **3,954**、letter_only 1,285、reference_only 292、source_conflict 101 |
| 带 `knowledge_node_ids` | 13,169 / 14,500 | 5,632 / 5,632 |
| 有难度值 | 12,720（全为 `heuristic_*`，实测校准 0 条） | 1,618 |
| 加权量规 | 6 套，全部 `official_scoring=false`、`expert_verified=false`、`review.status=needs_fix`、无署名 | 2 份，同样未签署 |
| 已核定先修边 | **0**（教资 31 条 / 四六级 56 条候选全部 `active_for_learning_path=false`） | 同左 |

## 2. 核心张力与结论：两档运行态，而不是一刀切

设计文档 §4 明写 `needs_fix`"**不参与诊断**"，而库里教资 13,460/14,500 都是 `needs_fix`。

**推论：严格执行数据层门禁 = 教资诊断能力题池为 0。**
**放松它 = 服务层自己制造一套"已审核"的假象，正是本轮清掉的那类问题。**

所以架构必须把"可信度"做成**运行时档位**，而不是布尔开关：

| 档位 | 用途 | 允许消费的题 | 对外话术 |
| --- | --- | --- | --- |
| `research_internal` | 教研自测、流水线调试、卡片/图谱回归 | 除 `quarantined` 与 `answer_status ∈ {source_conflict, missing}` 外的全部（教资 13,311 = letter_only 9,972 + reference_only 3,339；CET 1,577 = letter_only 1,285 + reference_only 292） | 每条响应必须带 `trust_tier`、`review.status`、`difficulty.kind=heuristic_*` |
| `published` | 面向真实学习者 | 仅 `review.status ∈ {checked, expert_reviewed}` 且答案可用且（判分时）量规已签署 | **当前为空集**，运行时必须显式返回"无可发布内容，等待教研核定"，禁止降级冒充 |

这把设计文档 §7 那句"F1/F3/F5 的诊断结论目前不可对外声称"变成了一条可执行断言，而不是一句免责声明：`published` 档在 0 签署题的现实下必须拒绝出结论。

## 3. 分层

```
A 数据契约层   数据集/**（已入库、已被门禁钉住）           —— 已完成
B 知识门面层   services/knowledge/{repository,graph_index,vector_index}.py
C 信任策略层   services/knowledge/trust.py（TrustGate，全库唯一降级点）
D 能力层       services/{grader,memory,diagnostic,planner,practice,qa,interview}/
E 编排层       services/orchestrator/（自研状态机 + AgentMessageEnvelope）
F 运行时层     services/app.py + SSE、stdlib 离线回填、SQLite 状态持久化
```

**依赖方向单向向下，且只有 B/C 允许触碰磁盘与索引。** D 层任何 agent 不得自己 `open()` 数据文件——这是可测试的约束（见 §8 验收）。

### 3.1 B 知识门面层

- `repository.py`：`question_id → 记录`。实现方式必须避免 142MB 全量进内存：启动时对 `questions/*/*/*.jsonl` 建**字节偏移索引**（一次顺序扫描，记录 `question_id`、`exam`、`level/subject/module`、`question_type`、`knowledge_node_ids`、`answer_status`、`review.status`、`difficulty`、文件路径 + offset），取题时 seek 单行解析。教资 622 个文件、14,500 条；CET 相应规模。
- `graph_index.py`：`edges.jsonl`+`nodes.jsonl` → NetworkX 有向图；**边名白名单硬编码 16 词**（与设计文档 §3.4 同源），出现第 17 个词直接抛错，把"不得再出现新边名"变成运行时约束。
- `vector_index.py`：Chroma 集合 `ntce_cards` / `cet_cards`，文档体取 `数据集/教资/cards/*/*/*/*.md`（自包含卡片，天然适合 RAG）与 CET 对应卡片，metadata 必带 `question_id`、`exam`、`module`、`level`、`review_status`、`answer_status`、`node_ids`。**元数据里带状态是硬要求**：召回后 C 层要按状态过滤，否则隔离题会经向量搜索漏进答案。
- 一切索引均可从 `数据集/**` 全量重建，索引本身不入库（`.gitignore`），坏了删掉重跑。

### 3.2 C 信任策略层 TrustGate（唯一降级点）

策略表（与 `审查/状态词表检查.py`、`审查/validate_kb.py` 共享同一份词表常量，禁止各写一套）：

| 数据状态 | 允许 | 禁止 | 必须呈现 |
| --- | --- | --- | --- |
| `quarantined` + `source_conflict`（教资 1,040 / CET 101） | 展示争议双方与法条沿革 | 判分、计入诊断、出现在组卷 | "开放讨论题"，正文不出现确定答案，不扣能力分 |
| `answer_status = missing`（CET 3,954） | 展示题干与解析 | 组卷作答、自动判分 | "答案待补" |
| `needs_fix` | `research_internal` 下练习与讲解 | `published` 下的一切；计入能力画像聚合 | "内容待复核（`review.checked_by = null`）" |
| `difficulty` 只有 `heuristic_*` | 组卷排序参考 | IRT/CAT/标准误措辞 | "教研初估" |
| 量规 `official_scoring=false` 且无署名（6 套全中） | 维度反馈、自评清单 | **自动出分** | "框架反馈 + 人工复核"，同时把这条作答写进 `审查/` 队列 |
| 题内练习框架（3,736 条，无 `weight_score`） | 生成反馈 | 参与判分 | 同上 |
| `content.stem` 只剩套名/题号且无选项（实测 CET-6 47 / CET-4 75 / 教资 42 题在"有答案"池内） | 教研补题干抽取 | 组卷、错题重做、计入 `pool_size` | 组卷响应里报出缺口条数与原因 |
| `prerequisite_of` 全部 `active_for_learning_path=false` | 供教研核定查看 | 参与路径拓扑排序 | "先修阻断未启用（0 条已核定）" |
| `use_scope ≠ research_non_commercial` | — | 输出原文、二次分发 | 直接拒发并记审计日志 |
| L0 条款 `verified=false`（2,260 + 3,995） | 溯源展示 | 作为"官方要求已核对"的结论 | 附 `requirement_id` + `locator`，标注未核定 |

TrustGate 的输出不是布尔，而是一个带说明的裁决对象。落地形状（`services/knowledge/trust.py`）：`TrustVerdict{question_id, review_status, answer_status, usable, tier, answer_visibility, notices[]}`，再在上面挂**只有门面向量才认识的口径属性**——`may_assert_answer`（能否断言具体答案）、`servable_in_paper`（能否进组卷/判分/召回）、`signed`（是否达到 `published`）。能力层只问"这条内容能不能用于 X"，不自己判断状态语义。

**答案状态只有一份词表**：`SERVABLE_ANSWER_STATUSES = (letter_only, reference_only, verified)`。`servable_in_paper`、`repository.find_questions(require_answer=True)` 与召回过滤 `RESEARCH_ANSWER_STATUSES` 全部引用它——`missing`/`source_conflict` 一旦被判不可用，就在门面、组卷、判分、召回四处同时消失，不存在"某一层还留着口子"的第二套口径。

### 3.3 D 能力层（保留现有 8 个 agent，重写数据依赖）

现有 agent 的**职责划分是对的**（对应设计文档 F1–F7），要改的是它们的数据来源与判分依据：

| agent | 现文档模块 | 应改为消费 | 当前能承诺 / 不能承诺 |
| --- | --- | --- | --- |
| practice | F1 | `repository` 真题 + `graph_index.assesses` 定向 | 能：按考点/模块/题型组卷、CET 三段时序。不能：自动判分依据未签署量规 |
| diagnostic | F3 | `assesses` + `supports_ability` 聚合 | 能：知识点覆盖度提示。不能：对外声称诊断结论、IRT 能力值 |
| planner | F4/F5 | `contains`/`has_child` 结构 + `assesses`；**先修边暂不入算法** | 能：按剩余天数 D 与每日时长 T 出日历。不能：前置阻断 |
| memory | F6 | `confused_with`/`misconception_lead_to` + FSRS | 能：五维归因草稿、间隔调度。不能：把归因当已验证结论 |
| qa | §5.2 | Chroma 卡片 + `aligned_to_requirement` + `权威资料/text/` 原文 | 能：带 `locator` 的溯源回答。不能：无出处回答、编造条文 |
| grader | F7/主观题 | A.6 加权量规（签署后）／题内框架（现在） | 现在只能出维度反馈 + 复核队列，**不出分** |
| interview | F7 | `rubrics/official_interview.json` 口径原文 | 能：结构化建议。不能："不替代正式考试评分"必须常驻 |
| master | §2.1 总控 | 见 E 层 | — |

### 3.4 E 编排层：自研状态机

设计文档 §2.1 的闭环 `A→B(F3)→C(F2)→D(F5)→E(F1,F7)→F(F6)→G(F2,F5)→D` 直接实现为显式状态机，`master` 从"关键词路由回话术卡片"升级成真调度：

```
IDLE → DIAGNOSE → PROFILE → PLAN → PRACTICE|MOCK → GRADE(或 FEEDBACK_ONLY)
     → ATTRIBUT → REPROFILE → (PLAN | DONE)
```

- 每个节点声明：输入 schema、输出 schema、超时、**降级出口**（置信不足或数据不可信 → `REVIEW_QUEUE`，对应设计文档 §5.2 的 `Verify -- 异常/置信不足 --> Queue`）。
- 唯一消息形状：把现在零使用的 `AgentMessageEnvelope`（`services/common/models.py:33`）定为强制信封，所有节点间消息必须带 `trust_tier`、`evidence[]`、`generated_by{agent, version, requested_model, prompt_sha256, created_at}`。
- 状态机自身不碰磁盘与 LLM，只做调度与降级判定；可单测、可重放。

### 3.5 F 运行时层

- **流式**：qa 与 master 走 SSE（`services/app.py:_sse`）；其余保持同步（设计文档未要求全链路流式，别过度设计）。
- **异步与批量回填**：不起 Celery + Redis。模考分段时序由进程内 `practice/cet_statemachine.py` 推进——它是单请求内的确定状态转移，不需要跨进程锁。LLM 解析回填 `analysis` 的落地形态是一个 **stdlib 离线 CLI**：默认 dry-run、只把 `review.status` 抬到 `llm_enhanced`、绝不写 `checked_by`/`expert_verified`、跑完把条目投进 `审查/` 队列等教研签署。当前没有可用的 LLM 端点配置（`KNOWLEDGE_MAP_LLM_*` 未设置，`/health` 报 `rule_only`），所以这一步只留口径、不写工具，免得拿模型编造的解析把库填满。
- **持久化**：FSRS 与掌握度落 SQLite（`services/memory/store.py:SqliteMasteryStore`）、会话与 envelope 落 SQLite（`services/orchestrator/session.py`）、人工复核队列落 JSONL（`services/review/queue.py`）。原先"进程内 dict、跨进程必 404"的缺陷已消除（验收 A5）。状态目录 `.local_state/` 与 `chroma/` 均不入库。
- **鉴权与限流**：`AuthContext` 已是全部 agent 路由的依赖；配置了 `KNOWLEDGE_MAP_RUNTIME_TOKEN` 时，`research_internal` 档必须带 `Authorization: Bearer <token>`，否则 401——未配置即开发默认放行，**公开部署前必须设**，因为该档会外发真题全文。限流未落地（单机研究用途、无并发用户）；上线对外前它是 §9 传播面风险的最后一道技术闸。

## 4. LLM 层（现在完全不存在，必须新写）

- `services/llm/client.py`：`LLMClient` provider 接口（本地 / 远端），统一超时、重试、成本统计；无 key 时**显式降级为规则模式并在响应里标 `mode=rule_only`**，不许静默。
- 结构化护栏按设计文档 §5.2"防幻觉护栏 (结构化 JSON Schema 约束)"：所有 LLM 输出必须过 `数据集/*/schemas/` 下对应 Schema（`question`/`rubric`/`practice_framework`/`requirement`），校验失败进 `REVIEW_QUEUE`，不做二次猜测。
- 留痕字段复用库里已有的 `analysis.generation{requested_model, prompt_sha256, created_at, thinking}` 形状，不造新词——设计文档 §4.1 已经写清教资现有取值分布（deepseek-flash 2,991 等）。
- **写权限铁律**：LLM 产出只能把 `review.status` 推进到 `llm_enhanced`，永远不得写 `checked`/`expert_reviewed`，不得写 `expert_verified=true`，不得填 `checked_by`。签署只发生在 `审查/待复核清单.md` 的人工动作里。这条要同时被代码和数据门禁（`Q_RUBRIC_EXPERT_CLAIM` 等）钉住。
- 评分调用：`grader` 的 `llm_response` 形参终于要真传；未传时的启发式分支必须标 `heuristic_graded`，且不得出现分数以外的权威口吻。

## 5. 检索：设计文档 §5.2 三路径汇流

```
query ─┬─ Chroma 向量召回（卡片自包含正文）
       ├─ 元数据过滤（exam / module / level / question_type）
       └─ 图谱邻域（assesses、supports_ability、aligned_to_requirement）
                    ↓
            TrustGate 过滤（隔离题、未签署量规、越权版权范围在此剔除）
                    ↓
            融合与证据装配 evidence[]{node_id, edge, requirement_id, locator}
```

要点：**过滤必须发生在召回之后、生成之前**。向量索引里带着 `review_status`/`answer_status` 元数据，就是为了让这一步无法被绕过。返回的每条证据都要能点回原文与条款——这是设计文档"绝不歪曲原意、严格注明出处"在运行时的兑现形式。

## 6. API 演进（10 条现有路由保持，语义收紧）

| 路由 | 改动 |
| --- | --- |
| `/grade/subjective` | 未签署量规下 `score = null` + `feedback_only = true` + 写入复核队列；不再回启发式分数 |
| `/practice/assemble` | 题目来自 `repository`，返回体带 `trust_tier` 与每题 `review.status` |
| `/qa/query` | 溯源改真条款（`requirement_id` + `locator`）；删除硬编码"本题答案为 B" |
| `/diagnostic/evaluate`、`/planner/generate` | `published` 档在 0 签署题下必须显式返回不可声称；先修阻断保持关闭并说明原因 |
| `/memory/*` | 落 SQLite，跨进程可读 |
| `/master/chat` | 由状态机驱动，真调子 agent |
| 新增 `/retrieval/search` | 三路径 + TrustGate 的统一出口，供 qa 与前端复用 |
| 新增 `/review/queue` | 把运行时降级项写进教研队列（与 `build_review_queue.py` 同源），保证"agent 不旁路人工" |
| `/health` | `agents_ready` 改真实探测 |

## 7. 分阶段落地

| 阶段 | 内容 | 规模 | 退出条件 |
| --- | --- | --- | --- |
| P0 | `repository` 字节偏移索引 + practice/qa 改读真数据 + 删除两处硬编码 + memory 落 SQLite | 0.5–1d | §8 断言 A1、A2、A5 绿 |
| P1 | `trust.py` 策略表 + 两档运行态 + 与门禁共享词表 | 1–2d | A3、A4 绿 |
| P2 | `graph_index`(NetworkX) + `vector_index`(Chroma) + `/retrieval/search` | 2–3d | A6、A7 绿 |
| P3 | `orchestrator` 状态机 + SSE + `AgentMessageEnvelope` 落地 | 2–3d | A8 绿 |
| P4 | `LLMClient` + JSON Schema 护栏（批量回填按 §3.5 口径推迟为离线 CLI，不起 worker） | 按需 | A9 绿 |

## 8. 可执行验收（每条都是测试，不是形容词）

- **A1 无影子数据**：`services/**.py` 中不得出现题面/条文常量（断言 `SAMPLE_QUESTION_BANK`、`PROVENANCE_DB` 不存在，且任何字符串常量长度 > 40 的中文题面形态一律拒绝）。
- **A2 真实引用**：`/practice/assemble` 返回的每个 `question_id` 必须能在 `数据集/**/questions` 索引中命中；`/qa/query` 的每条溯源必须命中 `权威资料/requirements.jsonl` 的 `requirement_id`。
- **A3 隔离不可漏**：`quarantined` 或 `answer_status ∈ {source_conflict, missing}` 的题，永不出现在 practice 组卷、grader 判分与向量召回结果中；卡片正文不出现确定答案。只剩套名/题号、无选项可答的题同样不得入卷，也不得计入 `pool_size`（缺口条数必须在 `notices` 里可见）。
- **A4 判分不冒充**：量规无署名时响应必须 `score=null`、`feedback_only=true`，且 `review.status` 不得被推进到 `checked`/`expert_reviewed`（LLM 同理）。
- **A5 状态持久**：两个独立进程实例共享同一状态目录时，`GET /memory/mastery/{user}/{node}` 必须命中。
- **A6 边名白名单**：加载 `edges.jsonl` 时出现 16 词表外边名即抛错；`prerequisite_of` 在 `active_for_learning_path=false` 时不得进入 planner 排序。
- **A7 难度措辞**：任何 `heuristic_*` 难度在响应中的 label 必须为"教研初估"，全库禁止 IRT/CAT/标准误字样出现在未校准路径输出里——**运行时自己写的提示语也在扫描范围内**，否则一句"不可用作能力估计"就会成为第一条违规。
- **A8 编排闭环**：一条会话可跑完 `诊断→画像→规划→刷题→归因→回写`，且每步消息都是 `AgentMessageEnvelope`。归因步只承认三种判据：调用方显式给的 `is_correct`、库内答案键、学习者自己的错题日志；三者都没有就不写记忆、不给错因，状态机停在中立出口而不是编造一个对错。
- **A9 人工不旁路**：每一条**教研能拍板**的拒绝（内容隔离、答案来源冲突、量规待签署）都必须在 `/review/queue` 留下一条 `pending_human_review` 记录，且 `checked_by=null`、`expert_verified=false`。反向同样成立：调用方漏传输入、`published` 档天然空池**不得**入队——否则唯一审核人会被无效项淹没，真正要他签的条目反而看不见。
- 回归总闸：`python -m pytest tests -q`、`审查/validate_kb.py`（结构性错误必须仍为 0）、`审查/状态词表检查.py` 两库各 0 违规。A1–A9 的实现是 `tests/test_acceptance_gate.py`，一条验收一个测试。

## 9. 风险与留痕

- **版权**：仓库 public，且已推送 470MB 含真题题干/答案/解析与 6,255 条条款抽取文本；运行时还有 `research_internal` 档会全文外发。所有者 2026-10-10 明确同意此状态。库内口径保持 `use_scope=research_non_commercial`、`authorization_status=unknown`，**不得在任何对外文案里声称已获授权或商业可用**；`AuthContext` 与限流是现存的唯一技术收口。
- **Chroma 冷启动**：12,881+ 卡片首次 embedding 有分钟级成本，需持久化 `chroma/` 目录并纳入"可重建产物"口径（不入库）。
- **`needs_fix` 占教资题池 92.8%**：这是 `published` 档当前为空集的直接原因，也是 §2 两档设计的全部动机。
- **4,014 道 CET 题无难度值**：planner/practice 的排序不能假设难度非空，缺失即显式降级。

## 10. 明确不做

不上 IRT / CAT / BKT / DKT（无真实作答数据，设计文档列为阶段二三）；不启用先修路径阻断（0 条已核定）；不在 `published` 档给出诊断结论；不做未签署量规的自动出分；不引入外部编排框架；不把索引与 Chroma 数据写入 git。

## 11. 落地状态（2026-10-10）

P0–P4 全部完成，§8 的 A1–A9 各有对应测试，实现在 `tests/test_acceptance_gate.py`（23 例），全库回归 `python -m pytest tests -q` 为 347 passed + 55 subtests。仍未落地的只有两件，且都是有意为之：批量解析回填（无可用的 LLM 端点，见 §3.5）与对外限流（无并发用户，公开部署前必须补）。
