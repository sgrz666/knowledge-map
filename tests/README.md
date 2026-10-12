# tests/ —— 这个目录放什么、谁来用

这里是知识库契约与运行时的门禁层：29 个测试文件把 `数据集/**` 的内容契约（附录 A.1 状态词表、A.6 量规、§3.2/§3.4 图谱层级与边方向）和 `services/**` 的行为契约（docs/agent_architecture.md §8 的 A1–A11 可执行验收）钉成可重跑的断言。测试本身不产出数据目录——只读库、把 learner 状态写进 `tempfile.mkdtemp`。

改 `kb_tools/`、`services/` 或 `数据集/**` 后都必须全绿：`python -m pytest tests -q`，再跑 `python 审查/validate_kb.py` 与 `python 审查/状态词表检查.py`（回归三件套，docs/agent_architecture.md §8 末行；`审查/待复核清单.md` 由 `审查/build_review_queue.py` 生成、逐字可复现，同属 A1 锁定范围）。全量收集必须用 pytest：`run_full_upgrade.py` 里的 `python -m unittest discover -s tests` 收不到 6 个 pytest-only 文件（见文末坑 4）。

## 文件清单

- `README.md`（本文件）—— 2026-10-11 重写为逐文件门禁清单；旧版只有目录级套话。
- `test_workspace_aliases.py`（24 行）—— 第一道闸：`权威资料/`、`教资/` 两个工作区别名目录可解析，且 `权威资料/catalog.json`、`权威资料/requirements.jsonl`、`教资/真题` 三个关键入口存在；断言消息里直接给出可执行的 `ln -s` 命令。它红了先修别名再谈其它失败——其余读库测试会跟着成串 error。单跑：`python -m unittest tests.test_workspace_aliases -v`。
- `test_acceptance_gate.py`（1405 行）—— docs/agent_architecture.md §8 的 A1–A11 逐条验收，一条一个类：TestA1NoShadowData、TestA2RealReferences、TestA3QuarantineCannotLeak、TestA4NoScoreWithoutSignature、TestA5StateSurvivesAcrossProcesses、TestA6EdgeVocabulary、TestA7DifficultyWording、TestA8ClosedLoop、TestA9HumanInTheLoop、TestA10ProfileVerdictSource、TestA11IndexRegeneration。铁律写在文件头：断言只允许引用 `数据集/**`、`官方权威资料/**` 里的实体本身或调用方送进来的文本，不写死题号/分值/条数（写死=把影子数据搬进测试）；A1 另用 AST 扫 `services/**/*.py` 禁 `SAMPLE_QUESTION_BANK/PROVENANCE_DB/MOCK_MINUTES` 这类常量名。模块级先把 `KNOWLEDGE_MAP_STATE_DIR` 指到临时目录再 import services。失败=对应那条验收被破坏，直接挡发布。单跑：`python -m unittest tests.test_acceptance_gate -v`，可细到 `python -m unittest tests.test_acceptance_gate.TestA3QuarantineCannotLeak -v`。
- `test_services_data_source.py`（469 行）—— 知识门面（repository/retrieval/trust/card index）的 §8 子集验收：TestA1NoShadowData、TestA2RealReferences、TestA3QuarantineCannotLeak、TestA5StatePersistence、TestA7DifficultyWording、TestA11FacadeFreshness、TestA11CardIndexFreshness——A11 重点锁门面缓存新鲜度、字节偏移完整性与卡索引按内容摘要重建。`KNOWLEDGE_MAP_STATE_DIR` 指临时目录。失败=消费端读到了过期/未过滤的库内容。单跑：`python -m unittest tests.test_services_data_source -v`。
- `test_services_all_agents.py`（930 行）—— 能力层（D 层）回归：TestDiagnosticAgent、TestCurriculumPlanner、TestPracticeEngine、TestTutorQA、TestInterviewCoach、TestTutorMaster。规则与 acceptance_gate 同源：断言只对比库实体或对 caller 文本做测量，禁止发明数字——文件头点名历史病灶（服务自带权重的 0-100 试讲合成分、第二份 40 分教案模板、probit 换算的 IRT 报道分、60 分钟日历排 90 分钟模考）。关联验收：A4/A5/A8/A10。失败=某个 agent 又开始自带数据口径。单跑：`python -m unittest tests.test_services_all_agents -v`。
- `test_services_api.py`（289 行）—— `services/app.py` FastAPI 层（TestAgentAPI，TestClient）：unsigned 量规的 grade 响应必须无分数（A4）、grade 请求体不得有 answer_status 参数（调用方不能自定答案键）、retrieval 候选过 gate、published 档在端点为空（A3）、health 探针跑全 agent 但不写唯一审核人的队列（A9 侧写）、除 health 外所有路由在 auth 依赖后、`KNOWLEDGE_MAP_RUNTIME_TOKEN` 配置后 research_internal 必须带 token。无库内匹配题时 `_library_id` 会 SkipTest。失败=运行时越权面被打开。单跑：`python -m unittest tests.test_services_api -v`。
- `test_services_grader.py`（374 行）—— A4 契约：TestGraderUnsigned（未署名量规只出反馈不出分）、TestGraderSignedPath（具名签署后才走评分路径）、TestGraderLibraryTruth（采分点与题面必须来自库内记录，caller 文本只能兜底/展示，不能顶替教研口径，也不能让立不住的题拿到分数或队列条目）。旧的 `DEFAULT_CET_BANDS`/NTCE 四维模板已删，断言全部改为对比库实体本身。单跑：`python -m unittest tests.test_services_grader -v`。
- `test_services_llm.py`（284 行）—— §4/A4/A7 的 LLM 护栏：TestDegradation（未配 key 必须显式抛 `LLMUnavailableError`）、TestPromptGuard（试图给模型安审核人角色的 prompt 被拒）、TestWritePermission（替审核人署名的 payload 拒绝入队且不做修复）、TestWordingGate、TestGraderLlmWiring（模型草稿只能改反馈措辞，绝不能让分数出现）。Provider 用 StubProvider/FailingProvider 打桩，全程无网络、不需 key。失败=LLM 权限边界回退。单跑：`python -m unittest tests.test_services_llm -v`。
- `test_services_memory.py`（275 行）—— MemoryReviewAgent/归因/FSRS：TestMemoryReviewService（掌握度记录按 `数据集/教资/schemas/user_mastery.json` 做 jsonschema 校验）、TestAttributionEvidenceSource（错因归因证据必须能回指库内）、TestEventReceipts（回执冲突 `ReceiptConflict` 防重复记账）。失败=记忆层写库偏离 schema 或重复计分。单跑：`python -m unittest tests.test_services_memory -v`。
- `test_services_safety.py`（155 行）—— `services/common/safety.py` SafetyGuard 单测：主观题响应的分数钳制上下界（total_score 超 max_score/低于下界要钳回）、数值边界、置信闸门。注意它锁的是"响应形状的兜底"，不改变 A4"未署名不出分"的前提。失败=安全阀松动。单跑：`python -m unittest tests.test_services_safety -v`。
- `test_ntce_repair.py`（319 行）—— `kb_tools/ntce_repair.py::repair()` 的全库语义护栏（接手管线的人最常碰的一个）：始终检查全库、不靠发布筛选缩分母（14500 钉死、ID 唯一）；MANIFEST materials 计数与库一致；每个 L2 模块有到 L4 的通路；source 验证不得冒充 expert 审核；退役官方 ID 全域消失；quarantine 的答案重跑不回魂；LLM 拿不到完整上下文就必须跳过而非硬编；原子写不暴露半截文件；人工字段/量规扩展在自动重打标签中存活（`test_manual_rubric_and_tag_extensions_survive_refresh`）；案例材料边界从源回收、内联案例不强要独立 material；占位符与五字母"解析"不算解析。sys.path 注入 `kb_tools`。失败=repair 语义回归，先别动数据，先看代码。单跑：`python -m unittest tests.test_ntce_repair -v`。
- `test_ntce_hierarchy_contract.py`（241 行）—— 教资 L0–L7 深度契约：MANIFEST 的 `eight_layer_hierarchy`、nodes 层级、双轨卡片、`数据集/教资/schemas/*.json` + yaml 全量校验（questions/materials/graph 逐条过 jsonschema）。失败=八层层级或 schema 漂移。单跑：`python -m unittest tests.test_ntce_hierarchy_contract -v`。
- `test_graph_direction_contract.py`（113 行）—— 设计文档 §3.2（单一层级字段）+ §3.4（边名词表、"支撑方→被支撑方"方向）在两库同时成立：ALLOWED 表钉死每种边的 `(src_type, dst_type)` 组合（assesses=knowledge_node→question、aligned_to_requirement=exam_requirement→…等）；题目外键必须镜像为 provider 边；L0 包含每一条 live 权威条款。历史上两库曾把 assesses 写反导致消费端各写一套遍历。失败=有人翻转边方向或自造边名。单跑：`python -m unittest tests.test_graph_direction_contract -v`。
- `test_status_vocabulary.py`（120 行）—— 附录 A.1：`sys.path` 注入 `审查/` 后 import `状态词表检查.py` 的 `ANSWER_STATES/REVIEW_STATES/collect`，两库共用同一词表与题目 schema——实体存储只用契约词、枚举定义与 A.1 逐字一致、letter/reference 答案必须带 provenance、无审核人不得声称 human 阶段、source_conflict 永不计分、卡 front-matter 镜像权威状态、两库过同一 `question.json`。失败=某库自造枚举回潮。单跑：`python -m unittest tests.test_status_vocabulary -v`。
- `test_kb_contract.py`（522 行）—— `审查/validate_kb.py::inspect_question` 的规则行为回归（importlib 按路径加载；文件缺失即报"缺少统一知识库验收器"）：逐案钉 Q_KNOWLEDGE_TOO_BROAD、Q_MODULE_MISMATCH、Q_ABILITY_MISSING/MISMATCH、Q_ANSWER_MISSING/INVALID、Q_ANSWER_SOURCE_CONFLICT、Q_REQUIREMENT_MISSING/DANGLING/SCOPE_MISMATCH/MAPPING_COARSE/MAPPING_PENDING_REVIEW、Q_RUBRIC_MISSING/PENDING_REVIEW、Q_SOURCE_UNRESOLVED、Q_REVIEW_EVIDENCE_MISSING、Q_DIFFICULTY_UNCALIBRATED、Q_PASSAGE_UNLINKED、Q_AUDIO_UNLINKED、Q_SUBJECT_MISMATCH 的触发/不触发边界。失败=验收器判据被改动（放松或误伤）。单跑：`python -m unittest tests.test_kb_contract -v`。
- `test_rubric_contract.py`（136 行）—— 附录 A.6，两库同时跑：选择题绝不携带主观评分框架（import `ntce_repair.CHOICE_TYPES/drop_choice_framework`，曾有 152 道带无 ID 影子框架）；一个维度只允许一套名称/档位/权重（`name+levels+max_level` 与 `dimension_name+criteria_levels+weight_score` 并存=双真相）；`expert_verified` 必须有具名审核人；未核准权重的量规必须留在待复核队列；repair 写回剥框架但不吞人工成果。它只锁"权重未署名通过就必须在队列"，不校验权重取值。失败=影子量规/双真相回潮。单跑：`python -m unittest tests.test_rubric_contract -v`。
- `test_ntce_conflict_reconcile.py`（333 行）—— `kb_tools/ntce_conflict_reconcile.py` 的落回契约：不信工具结论，直接重读原卷答案 CSV 逐条复算落回字母；锁三件闸门全过才落回、`quarantined→needs_fix` 且审核状态不被"带走"、批次证据文件名口径由工具自己管（测试用 `evidence_paths` 而非手拼）。批次 `xiaoxue/jiaoyuxinlixue`，未落回的必须仍是 `source_conflict`。失败=出现了原卷不可复算的答案，或隔离被错误解除。单跑：`python -m unittest tests.test_ntce_conflict_reconcile -v`。
- `test_official_examples.py`（167 行）—— `kb_tools/official_examples.py` 来源回归：`test_implementation_available` 先保证模块存在（importlib 按路径加载，缺模块直接红），再跑 `extract_catalog(ROOT)`（读 `权威资料/catalog.json`，依赖别名）锁 sha256 守护与"只提供审阅补丁、不写主库"；等待实现时 `skipTest`。失败=官方样题源字节变化或抽取逻辑被改。单跑：`python -m unittest tests.test_official_examples -v`。
- `test_cet_official_examples.py`（166 行）—— `kb_tools/cet_official_examples.py` 双层回归：TextAndMatchTests 纯函数级（normalize_text 词边界/标点空格、parse_options 双栏、match_examples、recovery_patches）；ActualOfficialSourceTests 在 setUpClass 真跑 `extract_official(ROOT, render=False)`（读 `权威资料/originals/cet.syllabus.2016.pdf`），钉写各 57 题、客观答案键 1–55 齐全、听力 50 题全 ABCD 且 `audio.status=not_provided_in_source`、matching 每卷 10 题选项集与卷标一致、scoring_sample 4 篇各带 [14,11,8,5,2] 五份官方作答、writing 答案必须 None、CID 空格恢复不"顺手纠错"。缺别名/PDF→整类 error。失败=官方样题 bundle 形状变了。单跑：`python -m unittest tests.test_cet_official_examples -v`。
- `test_cet_eight_layer_contract.py`（90 行）—— 四六级八层图谱导出：`数据集/四六级/graph/nodes|edges.jsonl` 覆盖 L0–L7、附录 A schema（借 `数据集/教资/schemas/` 的同一套）合规、先修关系未核定不得进入学习路径。失败=CET 图谱导出或 schema 合规回归。单跑：`python -m unittest tests.test_cet_eight_layer_contract -v`。
- `test_cet_repair.py`（433 行）—— `数据集/四六级/scripts/` 构建模块（repair_kb/fill_answers/build_questions/build_writing_translation 等，importlib 按路径加载并伪造 sys.argv 指向 `scripts/_staging/`）四个面：MigrationTests（听力 section 标题不是题干预提示、迁移不丢字段）、AnswerTests（冲突答案不投票表决、首个选项不是答案键、负向对比不供正确答案、零字形词库恢复）、IncrementalTests（增量不激活未批准边）、ArtifactTests（产物文件契约）。失败=CET 构建脚本回归。单跑：`python -m unittest tests.test_cet_repair -v`。
- `test_cet_passage_references.py`（192 行）—— 2026-10-04 四六级语篇修复的来源身份回归：动态加载 `数据集/四六级/scripts/repair_passage_references.py`，SourceIdentityTests 用固定 fixture 验题目↔语篇唯一绑定（题号范围头、Part IV 边界），PassageArtifactTests 查落盘产物。脚本缺失即断言失败。失败=语篇绑定/修复脚本回归。单跑：`python -m unittest tests.test_cet_passage_references -v`。
- `test_gap_remediation.py`（217 行）—— 短板补齐全量契约（数量类断言集中地）：四六级 5,340 题双轨自包含 Markdown 卡片与 `card_frontmatter.json` schema + 四阶段解析、写作/翻译 73 题（写译各 4 份文件）与评分量规、卷级 PaperSpecification（CET 126 套 710 分制、NTCE 32 套 120 分制）、听力音频 120 套索引与切片对齐、万级考纲词汇挂载、认知诊断 DAG 无环。失败=补齐批次欠账或有人改了库没同步规格。单跑：`python -m unittest tests.test_gap_remediation -v`。
- `test_completeness_audit.py`（31 行）—— 完整性快照是库内容的纯函数：`services.knowledge.completeness.audit_ntce()` 输出不得含 `generated_at` 之类钟点、重跑逐字节相同、已提交的 `审查/教资完整性核对.json` 必须能从当前库原样复现。按 pytest 收集（模块级 test_ 函数，`unittest` 收不到）。失败=快照落后于库，或审计里混进了时间戳。单跑：`python -m pytest tests/test_completeness_audit.py -v`。
- `test_exam_sessions.py`（182 行）—— services/exam_sessions 持久化模考：pytest fixture + Clock 假时钟 + tmp_path SQLite + 库内真实卷面；锁时长准入、跨进程续考、超时判定的 durable admission。失败=模考计时/准入持久化回归。单跑：`python -m pytest tests/test_exam_sessions.py -v`（不能 unittest 直跑，fixture 依赖）。
- `test_interview_session.py`（200 行）—— 面试陪练单场会话：整场只能由库内 scenario 资源搭成，题面/追问依据/阶段任务必须回指库内资产；量规未签署时整场不出分数（A4 在面试侧的落点）。pytest fixture，tmp 状态目录。单跑：`python -m pytest tests/test_interview_session.py -v`。
- `test_knowledge_browser.py`（42 行）—— `services/web/knowledge.KnowledgeBrowser`：tree 按学段/科目作用域返回库内节点（id 前缀断言）、mastery 一律 None（不得凭空造掌握度）、parent_id 闭合、published 档返回空（A3）。pytest。单跑：`python -m pytest tests/test_knowledge_browser.py -v`。
- `test_learning_workflow.py`（232 行）—— `services.learning` 持久学习工作流：断言包存在本身是一项测试；fixture 走真实 `Workbench()` 构造再换 tmp_path 的 SqliteMasteryStore（文件注释记录了教训：手工逐字段装配的 fixture 曾漏掉 `__init__` 新依赖把 exam_sessions 拖红）。覆盖 planner→practice→memory 的闭环状态（A8 侧写）。单跑：`python -m pytest tests/test_learning_workflow.py -v`。
- `test_web_workbench.py` —— Web 工作台用户可见契约，直接跑在真实库上：`/` 200、`/api/v1/web/bootstrap` 写死 `total=14500、missing_knowledge=1331、signed_questions=0、unpractised_nodes=160`、`KNOWLEDGE_MAP_RUNTIME_TOKEN` 存在时未带 token 401、交卷幂等且卷面归属库。agent 流程那几条也在这里：思考过程六支都产出且步骤集合固定、批次轮换可重放并避开上一批、越界载荷降级不 500、同一句话不重复排课、整句包裹仍锚得到考点、考点真题附题面但不泄答案、状态冲突带前端能用的错误码。模块级 `TestClient(app)` 收集自 pytest（`unittest` 收不到这些函数）；作答类用例一律走 HTTP，不要另开一个 `Workbench()` 连接写库——应用读写走它自己那条连接，测试连接上的提交它看不见，答案解锁那类断言就验不真。失败=对外暴露的数字和库脱节——先判断是库 legitimately 变了还是代码错了，再决定改测试还是改管线。单跑：`python -m pytest tests/test_web_workbench.py -v`。
- `test_learning_resources.py`（138 行）—— `数据集/教资/resources/study_guides.jsonl` 是"可追溯研究草稿"契约：EXPECTED 表硬编码 7 个锚定知识点→需求 ID，7 份实质指南 + 14 道 self-check、所有引用必须命中真实需求（学科+文本位置）、不得伪造签名也不得冒充正式题身份、源边界显式声明、loader 过滤返回 detached JSON 且重读变化、文件缺失=空、畸形/重复数据拒收。失败=指南与库脱钩或有人把草稿转正了。单跑：`python -m unittest tests.test_learning_resources -v`。

## 门禁与跑法

全量（推荐的唯一口径，pytest 同时收集 unittest 类与模块级函数）：

```bash
python -m pytest tests -q
python 审查/validate_kb.py
python 审查/状态词表检查.py
```

单文件/单类：

```bash
python -m unittest tests.test_ntce_repair -v
python -m unittest tests.test_acceptance_gate.TestA3QuarantineCannotLeak -v
python -m pytest tests/test_exam_sessions.py -v          # 6 个 pytest-only 文件必须这样跑
```

建议顺序：`test_workspace_aliases`（环境闸）→ `test_ntce_repair` / `test_status_vocabulary` / `test_rubric_contract` / 图谱与层级契约（库内容面）→ `test_kb_contract`（验收器判据面）→ `test_acceptance_gate` + `test_services_*`（运行时面）→ `test_gap_remediation` / `test_web_workbench`（数量与用户可见面）。

管线↔测试的接线（谁跑测试）：`kb_tools/run_full_upgrade.py` 在两库批量升级后跑 `python -m unittest discover -s tests`；`kb_tools/run_infer_all_cet.py` 推断后跑回归三件套。

## 改这里之前要知道的

1. **别在本目录写文件**：测试对 `数据集/**`、`审查/**` 只读；任何 learner/queue 状态必须落 `tempfile.mkdtemp`/`tmp_path`。`test_acceptance_gate.py`、`test_services_all_agents.py`、`test_services_api.py`、`test_services_data_source.py`、`test_services_llm.py` 都在 import services **之前**设置 `KNOWLEDGE_MAP_STATE_DIR`——写新测试要照抄这个顺序，否则学习者 FSRS 状态会漏进仓库的 `.local_state/`。
2. **不许写死影子数字**：`test_acceptance_gate.py`/`test_services_all_agents.py` 的铁律是断言只对比库实体或调用方文本；例外是明确"数量契约"的 `test_gap_remediation.py`、`test_web_workbench.py`、`test_ntce_repair.py`（14500）和 `test_cet_official_examples.py`（57/50/126 等）——这些数字合法，因为它们复述的是库自身的规格，库 legitimately 变化时要在同一批改动里同步生成器与测试。
3. **大量测试按路径动态 import**：`kb_tools/`（build_kb/ntce_repair/ntce_conflict_reconcile/official_examples/cet_official_examples）、`审查/`（validate_kb.py、状态词表检查.py，中文模块名）、`数据集/四六级/scripts/`。移动/改名这些脚本会连锁弄红对应测试；改函数签名前先看有没有测试 import 它。
4. **`unittest discover` 收不到 6 个文件**：`test_completeness_audit`、`test_exam_sessions`、`test_interview_session`、`test_knowledge_browser`、`test_learning_workflow`、`test_web_workbench` 是 pytest 风格（fixture 或模块级 test_ 函数）。`run_full_upgrade.py` 用的正是 `python -m unittest discover -s tests`——它全绿不代表这 6 个跑过，收尾必须再 `python -m pytest tests -q`。
5. **别名缺失的表现是"成串 error"不是断言失败**：`权威资料/`、`教资/` 符号链接不在仓库里，读库/读源的测试在 setUpClass 就炸（根 README 口径：22 个测试）。先跑 `test_workspace_aliases.py` 区分环境问题与代码问题，修复命令就在它的失败消息里（`ln -s "$(pwd)/官方权威资料" 权威资料`）。
6. **skip 是口径不是遮羞布**：仅有的正当跳过——`test_services_api.py` 库内无匹配题型时 SkipTest、`test_official_examples.py` 等待实现时 skipTest、6 个 pytest-only 文件在 unittest 下静默不被收集（这不是 skip，见坑 4）。新增 skip 必须写明条件，否则等于给契约开后门。
