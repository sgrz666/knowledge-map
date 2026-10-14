# services/knowledge/ —— 这个目录放什么、谁来用

这是全库**唯一的读数据门面**：所有能力 agent（`practice/ diagnostic/ planner/ memory/ qa/ grader/ interview/ master/`）
与 `app.py` 的检索入口都只能经这里取数，磁盘上的题面、答案、卷面规格、条款原文一律不在 service 代码里手抄。
写方向只有两处运行时状态：被门禁挡下的请求写 `review/` 的待复核队列、卡片向量索引写 `chroma/`（可重建产物）。
读方向是 `数据集/**`、`官方权威资料/**` 与别名路径 `权威资料/**`。改这里跑：`python -m pytest tests/test_acceptance_gate.py
tests/test_services_data_source.py tests/test_graph_direction_contract.py tests/test_completeness_audit.py
tests/test_learning_resources.py tests/test_status_vocabulary.py -q`。

## 文件清单

- `__init__.py`（12 行）—— 门面导出面：只 re-export `KnowledgeRepository/QuestionMeta/get_repository`（来自 `repository.py`）
  与 `TrustGate/TrustTier/TrustVerdict`（来自 `trust.py`），并写进 `__all__`。调用方 `from services.knowledge import ...` 走这里。
- `repository.py`（642 行）—— 字节偏移索引，`class KnowledgeRepository` + `@lru_cache(maxsize=1) get_repository()`（进程内单例，
  全量建索引约 1.2s / 750 个 JSONL）。路径常量（全部相对 `REPO_ROOT = Path(__file__).resolve().parents[2]`）：
  `QUESTION_DIRS = ("数据集/教资/questions", "数据集/四六级/questions")`、
  `REQUIREMENT_FILES = ("官方权威资料/requirements.jsonl", "权威资料/requirements.jsonl")`、
  `GRAPH_FILES = {"ntce": (…/graph/nodes.jsonl, …/graph/edges.jsonl), "cet": (同结构)}`、
  `PAPER_SPEC_FILES = ("数据集/教资/paper_specs.jsonl", "数据集/四六级/manifest/paper_specs.jsonl")`、
  `RUBRIC_DIR = "数据集/教资/rubrics"`、`CET_RUBRIC_FILE = "数据集/四六级/ontology/scoring_rubrics.jsonl"`。
  **字节偏移索引怎么建**：`_build_question_index()` 以 `"rb"` 打开每个题文件，逐行累加 `offset += len(line)`，
  把每行的 `file/offset/length` 连同投影字段存进 `QuestionMeta`（frozen dataclass：`question_id/exam/module/section/
  question_type/subject/school_level/node_ids/requirement_ids/review_status/answer_status/difficulty/difficulty_method/
  file/offset/length/has_answerable_text/time_limit_minutes`）；坏行不整文件丢弃，经 `_note_scan_error` 登记缺口后继续。
  **存在哪**：只存在进程内存（`self._questions` dict），不落盘；它是"数据的缓存"而不是"进程启动时的快照"——
  `_tracked_files()/_fingerprint()` 对全部被跟踪文件取 `(mtime_ns, st_size)`，`_check_fresh()` 每 `self._ttl` 秒复核一次
  （默认 `_default_ttl()` 5.0s，读环境变量 `KNOWLEDGE_MAP_INDEX_TTL`，设 0 表示每次读都复核），指纹变了就
  `_invalidate_locked()` 清空三类缓存并把 `generation += 1`。
  **偏移的身份校验**：`load_question()` 用 `fh.seek(meta.offset); fh.read(meta.length)` 读回，`_read_range` 要求解出的
  `record["question_id"]` 仍等于请求的 id；不等则 `logger.warning` + 只重扫该题所在文件（`_rescan_file`，不动条款/量规
  缓存、不 `generation += 1`）、按新位置再读一次，仍对不上就登记缺口返回 `None`（绝不把别人的题面/答案键当成这道题送出去）。
  读 API：`questions/get_meta/find_questions`（谓词 `exams/modules/sections/question_types/node_ids/review_statuses/
  answer_statuses/require_nodes/require_answer/require_answerable_text/exclude/school_level/subject`，其中 `require_answer`
  复用 `trust.SERVABLE_ANSWER_STATUSES`，不另写一套词表）、`requirements/get_requirement`（第一个存在的 REQUIREMENT_FILES
  生效并 `break`，别名不贡献新记录）、`graph_records/_read_jsonl`、`rubrics/find_rubric`、`paper_specs/mock_minutes_for`、
  `reading_passage`（读 `数据集/四六级/passages/reading.jsonl`）、`audio_path`（校验后缀 `.mp3/.wav/.m4a` 且 `is_relative_to(root)`）、
  `has_unavailable_figure`、`load_material`（读 `数据集/教资/materials`）、`stats()`。
  共用读法只写一遍的三处：`has_answerable_text`（`_PAPER_HEADER = ^【[^】]*】` 去套名后仍无文字且无选项 → False）、
  `timed_stages/mock_minutes/item_time_limit`（单题用时只读 `extra.task_constraints.time_limit_minutes`，读不出返回 `None`）、
  `_as_set`（防 `exams="NTCE"` 被拆成单字符集）。跑通冒烟：`python -m pytest tests/test_acceptance_gate.py::TestA11IndexRegeneration -q`。
- `trust.py`（374 行）—— TrustGate：全库唯一"数据质量 → 运行时行为"的降级裁决点，**只读不写状态**。
  `TrustTier = Literal["research_internal", "published"]`（注意与 `common/models.py` 里同名 `str, Enum` 是两个类型）。
  常量：`SIGNED_STATUSES = {"checked", "expert_reviewed"}`、`ANSWER_VERIFIED = "verified"`、
  `SERVABLE_ANSWER_STATUSES = ("letter_only", "reference_only", "verified")`、`LETTER_ANSWER_STATUSES = ("letter_only", "verified")`、
  判据来源标记 `VERDICT_SOURCE_KEY = "库内答案键核对"` / `VERDICT_SOURCE_CLAIM = "调用方申报"`。
  **两档裁决判据**（`classify(question_id, review/content/difficulty_meta 或 review_status/answer_status/difficulty_method)`）：
  ① `status == "quarantined"` 或 `answer_status == "source_conflict"` → 立即返回 `usable=False, tier=None, answer_visibility="none"`
  + `QUARANTINE_NOTICE`；② 可见性映射：`verified/letter_only → "letter"`、`reference_only → "reference"`、其他 → `"none"` 并附
  `ANSWER_MISSING_NOTICE`；③ `signed` 四条件同时成立 = `status in SIGNED_STATUSES` 且 `review.checked_by` 且
  `review.content_verified` 且 `answer_status == "verified"`，否则附 `UNREVIEWED_NOTICE`；④ 有 `difficulty_method` 就附
  `DIFFICULTY_NOTICE`（只用于选题排序，不构成测量学结论）；⑤ 档位分歧：`published` → `usable = signed`（当前恒 False，**fail closed**），
  `research_internal` → `usable = True`。`TrustVerdict`（frozen）属性 `may_assert_answer / servable_in_paper / signed`，
  其中 `servable_in_paper = usable and answer_status in SERVABLE_ANSWER_STATUSES`。
  其余入口：`classify_meta`（不读整条记录，按投影判）、`classify_record`、`filter_usable`、
  `reconcile_verdict(record, selected_option, claimed)` 返回 `(verdict, provenance, notices)` 并把判据优先级固定为
  **库内答案键 > 调用方申报 > 无判据**（`verdict is None` 时不许写画像、不给错因，申报与答案键相反时附 `VERDICT_CONTRADICTION_NOTICE`）、
  `classify_requirement`（`source_verified` 才可引用，`mapping_status != "mapped"` 与 `locator.html_path` 各附一条 notice）、
  `classify_rubric` → `RubricVerdict.may_score = found and signed`（未签署只给反馈，`RUBRIC_UNSIGNED/MISSING/OFFICIAL_NOTICE` +
  `COPYRIGHT_NOTICE`）、`response_notices` 去重、`fail_closed()` 返回 `code="no_qualified_content"`。
  `answer_letter()` 是唯一一份"取首个 A–Z 字母"实现（`master` 与 `qa` 曾各写一份）。
- `graph_index.py`（308 行）—— NetworkX `MultiDiGraph` 视图 + 边名数据契约。`ALLOWED_EDGE_TYPES` 是**闭合 16 词白名单**（顺序即契约）：
  `specifies, contains, targets, supports_ability, has_rubric, refers_to_material, has_child, assesses, prerequisite_of,
  comprises, basis, aligned_to_requirement, confused_with, misconception_lead_to, supports_resource, supplements_resource`
  （`ALLOWED_EDGE_TYPES_SET` 为其 frozenset）；`_build()` 遇到第 17 个边名抛 `UnknownEdgeTypeError`（继承 `RuntimeError`）。
  边集合按数据固定方向（文件头 docstring 逐条列出 `assesses 节点→题` 等），故 helper 把方向编码一次：
  `nodes_for_question = link_in(q, "assesses")`、`requirements_for = link_in(n, "aligned_to_requirement")`、
  `rubric_for = link_out(n, "has_rubric")`、`materials_for = link_out(q, "refers_to_material")` 等；
  分组常量 `CONTAINER_EDGES / MISCONCEPTION_EDGES / RESOURCE_EDGES`。缓存换代：`_built_generation` 与
  `repository.generation` 不一致就重建（`graph` 属性双检锁）。
  数据门禁：`prerequisite_pairs()` 只统计 `active_for_learning_path` 为真的 `prerequisite_of`（当前 0 条），
  `prerequisites_active` 因而为 False，`topological_order()` 原序返回并附 `PREREQUISITE_DISABLED_NOTICE`；
  `mapping_status/verified` 一律原样透传不升级，`notices()` 对未核对的边名附 `UNREVIEWED_MAPPING_NOTICE`。
  `LIBRARY_VALUES = ("ntce", "cet")`，`@lru_cache(maxsize=4) get_graph_index(library)`，`library_for_exam()` 把 NTCE/省考→ntce、CET*→cet。
  跑：`python -m pytest tests/test_graph_direction_contract.py -q`。
- `vector_index.py`（554 行）—— 卡片向量索引（Chroma 优先 + BM25 离线回退），`class CardIndex` + `@lru_cache(maxsize=1) get_card_index()`。
  常量：`CARD_DIRS = {"ntce": "数据集/教资/cards", "cet": "数据集/四六级/cards"}`、
  **Chroma 集合名 `COLLECTION_NAMES = {"ntce": "ntce_cards", "cet": "cet_cards"}`**、`EMBEDDING_DIM = 384`、
  `EMBEDDER_NAME = "hash-ngram-384"`、`CHROMA_DIRNAME = "chroma"`（`ChromaStore` 落 `REPO_ROOT/chroma`，
  `PersistentClient`，`hnsw:space=cosine`，`anonymized_telemetry=False`）。
  默认 embedder `hash_ngram_embedding()`：字符 n-gram + ascii token 的确定性带符号哈希词法向量，**不是语义模型**，
  `notices()` 因此明说 `embedder=hash-ngram-384`；`chromadb` import 失败 → `available_backend()` 返回 `bm25_fallback`，
  由 `LexicalStore`（BM25，k1=1.5、b=0.75，倒排表按库隔离）提供同签名 API，并发 `LEXICAL_NOTICE`。
  卡片读取 `iter_cards()`：`*.md`（跳过 `README.md`），`_parse_frontmatter` 解析 `---` 块，metadata 必带
  `review_status/answer_status`（召回后、生成前过滤靠它），`card_digest = _content_digest(text, metadata)`（blake2b-16，正文+状态一起进指纹）。
  `build()` 按内容指纹增量 upsert 并 `prune`（教研撤卡/改名后从集合删除，防隔离题靠一次相似命中回到答案）。
  **重建命令**：运行期由 `search()` 首次调用自动 `build([library])`；`_ensure_current()` 每 `CARD_TTL_SECONDS`
  （默认 60.0s，环境变量 `KNOWLEDGE_MAP_CARD_TTL`）复核卡片目录指纹后增量重建。手动增量重建：
  `python -c "from services.knowledge.vector_index import get_card_index as g; print(g().build())"`；
  全量重建 = 先删 `chroma/` 目录再跑同一句（`chroma/` 是 gitignored 的可重建产物，不入库）。
  跑：`python -m pytest tests/test_services_data_source.py -q`。
- `naming.py`（100 行）—— 请求侧 id → 库内字段值的**唯一共享词表**，口径是"库内兑现不了的别名塌到最近的真实值并回报 notice，
  不悄悄放大或缩小候选池"。`EXAM_VALUES = {"CET-4": ("CET-4",), "CET-6": ("CET-6",), "NTCE": ("NTCE", "省考")}`；
  `MODULE_ALIASES` 把遗留 `m1…m5` 全塌成 `NTCE_QUALITY_MODULES = ("综合素质",)`（库内没有子模块级 `module`，
  命中即附 `COARSE_MODULE_NOTICE` 提示改传 `target_node`），`cet_listening/cet_reading/cet_writing/cet_translation` 与
  `listening/reading/writing/translation` 映射到 `听力理解/阅读理解/写作/翻译`；表外的值当作库内原生模块名原样返回。
  `TASK_TYPE_ALIASES` 把请求任务名映射到 `数据集/教资/rubrics/*.json` 与 `数据集/四六级/ontology/scoring_rubrics.jsonl`
  的 `task_type` 取值（`case_analysis/lesson_plan/short_answer/writing/short_essay/paragraph_translation/interview_qa/interview_teaching`），
  兑现不了的别名**留在原值**，让 grader 报"该题型无量规"而不是拿编造的量规判分。
  函数：`task_type_value/exam_values/module_values`（返回 `(values, notice)`，`values is None` 表示不按模块过滤）。
  旧有的 `is_multiple_choice`（`MC_SECTIONS`/`MC_TYPES`）全仓零调用，已删——需要机器判字母的地方由
  `trust.answer_letter`/`SERVABLE_ANSWER_STATUSES` 承担，不在本文件另留一份词表。
- `completeness.py`（52 行）—— 教资完整性事实**只经 KnowledgeRepository 现算**（A1 口径：不许把计数抄进代码）。
  `audit_ntce(repository=None)`：遍历 `find_questions(exams='NTCE')`，按 `(school_level, subject)` 分 `groups` 并累计 `counts`，
  指标为 `total/usable/missing_knowledge/missing_requirement/missing_answer/answer_conflict/missing_stem/signed_questions`；
  其中 `usable` 的口径是 `gate.classify_meta(meta).servable_in_paper and meta.has_answerable_text`（复用 trust 那份词表，不自写）；
  `signed_questions` 会真去 `load_question()` 读 `review.checked_by`。再读 `graph_records('ntce')` 统计
  `knowledge_nodes/used/unpractised/unpractised_leaf_nodes`（叶子 = 没有 `has_child` 出边）、`graph_layers/graph_edges/materials`，
  `aligned_to_requirement` 边归集 `requirement_ids`，`paper_specs('NTCE')` 给 `paper_specs`，
  `unsigned_rubrics` 由 `classify_rubric(r).signed` 取反计数。三条 `notices` 是数据门禁措辞：可练计数不代表教研已签署或素材齐全、
  缺口是独立维度不能相加、缺答案/来源冲突/人工审核无法由机器补成已核定。被 `web/service.py` 读。跑：
  `python -m pytest tests/test_completeness_audit.py -q`。
- `learning_resources.py`（79 行）—— 非题目类学习资源的只读门面（`class LearningResources`），文件常量
  `GUIDE_FILE = "数据集/教资/resources/study_guides.jsonl"`、`SCENARIO_FILE = "数据集/教资/resources/interview_scenarios.jsonl"`。
  口径：每次调用都从盘重读（本地编辑立即可见，返回的 dict 不会污染共享缓存）；文件缺失→空列表；
  **数据门禁在 `_records()`**：逐行 `json.loads`，空行跳过，坏 JSON/缺主键/主键非非空字符串/主键重复一律
  `raise ValueError(f"{rel}:{line_number}: …")`，绝不返回"部分列表"掩盖损坏或重复记录。
  方法 `list_guides(node_id=None)/get_guide(node_id)`（主键 `node_id`）、`list_scenarios(exam=None)`（主键 `resource_id`，
  结构化问答题面的唯一来源，按资源自带 `exam` 过滤）。顶层便捷函数 `list_guides/get_guide` 走共享 `get_repository()`。
  被 `learning/interview.py` 读；调用方必须把 `notice` 与 `review` 和讲解文本一起展示（这些文档是研究资源，不是题目记录或判分键）。
  跑：`python -m pytest tests/test_learning_resources.py -q`。
- `retrieval.py`（387 行）—— §5 三路召回：卡片向量 + metadata 过滤 + 图谱邻域，**中段过 TrustGate**。
  词表常量 `RESEARCH_ANSWER_STATUSES = SERVABLE_ANSWER_STATUSES`（与组卷同一份，A3 只一份词表）、
  `RESEARCH_REVIEW_STATUSES = ("needs_fix","auto_parsed","llm_enhanced","checked","expert_reviewed")`、
  `PUBLISHED_REVIEW_STATUSES = ("checked","expert_reviewed")`。
  `class RetrievalService(repository=get_repository(), card_index=get_card_index(), queue=get_review_queue())`，
  `search(query, exam, tier, k, user_id, modules, question_types, levels, use_graph)`：
  `_libraries(exam)` 走 `library_for_exam`，`_filters(tier, …)` 把 answer/review 状态集合塞进 metadata 过滤；
  每库 `self.cards.search(query, libraries=(library,), k=k*3, filters=…)`，索引异常只登记 `index_errors` 不伪造命中。
  `_reconcile(hit, meta, …)`：**题目索引是唯一真相**——卡片命中但索引无此 id → 记 `orphan_card_hit` 入队并丢弃；
  卡片 `review_status` 与索引不一致 → 仍按索引为准，附 `DUAL_TRUTH_NOTICE` 并记 `card_index_status_mismatch`。
  TrustGate 挡下的题（`verdict.usable` False）进 `blocked` 并 `queue.add(reason="trust_gate_blocked", …)`（验收 A9：被挡必须留下人可处理的记录）。
  命中证据组装：`_requirement_evidence(rid)` 经 `repository.get_requirement()` 取 `数据集/…` 条款实体，
  `source="官方权威资料/requirements.jsonl"`，`verified = bool(requirement["source_verified"])`；
  `_graph_evidence()` 经 `get_graph_index(library).requirements_for/requirements_for_question` 扩条款。
  `published` 且无候选时直接返回 `gate.fail_closed()`。`notices` 恒含 `COPYRIGHT_NOTICE` + `self.cards.notices()`。
  被 `app.py` 的 `/api/v1/retrieval/search` 与 `web/service.py` 读；`get_retrieval_service()` 为 lru_cache 单例。

## 子目录

无。本目录是扁平的 9 个 py 文件；它读的数据目录在仓库根（`数据集/`、`官方权威资料/` 及别名 `权威资料/`、`教资/`），不在这里。

## 改这里之前要知道的

- **门面换代 = 全链路口径**：`repository.generation` 每换代 +1，`GraphIndex._built_generation` 靠它判断自己的缓存是否属于上一代；
  `CardIndex` 另有一套 `CARD_TTL_SECONDS` 的指纹复核窗口（默认 60s，比门面的 5s 宽）。改了 TTL 语义或 generation 递增点，
  `tests/test_acceptance_gate.py::TestA11IndexRegeneration` 会失败。
- **别在 service 代码里抄数据**：本模块是"影子数据"的唯一合法取数处。`SERVABLE_ANSWER_STATUSES`（trust）被 `repository.find_questions(require_answer=True)`
  和 `retrieval.RESEARCH_ANSWER_STATUSES` 共用；另写一份答案状态词表会让召回与组卷对同一道题各说一套（A3）。
- **别名依赖**：`REQUIREMENT_FILES` 里 `权威资料/requirements.jsonl` 是本机工作区链接（指向 `官方权威资料/`）；
  `_build_requirement_index()` 是"第一个存在的文件生效然后 `break`"，所以删了真目录会直接报 `Q_SOURCE_UNRESOLVED`/读不到 catalog。
  写文件请写真实目录名，不要经 `权威资料/` 或 `教资/` 路径写。
- **published 档必须 fail closed**：当前两库都没有具名签署题，`TrustGate.classify` 在 published 下 `usable=signed`（恒 False）、
  `retrieval.search` 在无候选时返回 `fail_closed()`。放宽这两处就等于把未审核内容推给考生。
- **`chroma/` 与 `.local_state/` 都是生成物**：前者按 `数据集/*/cards` 全量重建（首次升级到"按内容指纹重建"时旧集合没有
  `card_digest`，会被判为全部改动、触发一次全量重嵌，之后才增量）；后者是运行时状态，不入库、不要手改。
- **图谱边名白名单是数据契约**：加第 17 个边名要先由教研复核，不能在运行时"顺手宽容"；`UnknownEdgeTypeError` 就是那扇门。
- **先修边当前 0 条已核定**：`prerequisite_of` 全部 `active_for_learning_path=false`，任何"前置阻断保证"的排序结论都不可用。
