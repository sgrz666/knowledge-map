# kb_tools/ —— 这个目录放什么、谁来用

这里是教资（NTCE）数据管线的全部构建/修复/校验代码，外加两库共用的作用域路由与官方样题抽取器。原始题面从 `教资/真题/` 的 CSV 解析进 `数据集/教资/`（questions、materials、cards、graph、rubrics、outline、review、MANIFEST.json），修复与再生的唯一核心是 `ntce_repair.py` 的 `repair()`；官方样题只写 `补充资料/`，绝不碰主库。

改了这里的任何文件，最低验收是回归三件套：`python -m pytest tests -q`、`python 审查/validate_kb.py`、`python 审查/状态词表检查.py`。改了 `ntce_repair.py` 或它 import 的模块，还要先跑 `python kb_tools/ntce_verify.py --check-idempotence`（双跑哈希必须一致）。直接跑脚本前先确认工作区别名已建（见文末"改这里之前要知道的"第 1 条）。

## 文件清单

- `README.md`（115 行）—— 本文件。旧版有乱码（`\r`/`\n` 转义被吃掉，`ntce_repair.py` 显示成 `tce_repair.py`），2026-10 起整篇重写为逐文件清单。
- `build_kb.py`（854 行）—— 全库根入口兼公共库。CLI：`python kb_tools/build_kb.py inventory|sample N|build`。`build` 时若 `数据集/教资/questions/*/*/*.jsonl` 已存在则不重新分配 ID、直接委派 `ntce_repair.repair()` 做安全重算；否则从 `教资/真题/` 的 CSV 解析题面/材料/卡片，写 `数据集/教资/questions|materials|cards`、`MANIFEST.json`、`qa_report.md`、`subject_map.json`，最后也落到 `repair()`。它导出的 `ROOT/OUT/load_text/norm_stem/parse_question_text/render_card/parse_answers/classify_answer/ANSWER_CONTRACT/sha/out_file/TYPE_MAP/SECTION_WORDS/NUM_CAND_SKIP_AFTER` 被 kb_tools 几乎所有模块 import，改签名等于改全目录。`safe_part/out_file` 对路径成分做白名单，防 `..` 注入。依赖 `教资/真题` 别名，缺别名直接找不到源。
- `ntce_repair.py`（839 行）—— 修复管线核心，`repair()` 全库幂等重算（可反复跑，不产生新 ID）。CLI：`python kb_tools/ntce_repair.py [--skip-outline]`。读 `数据集/教资/questions` + `权威资料/catalog.json|requirements.jsonl|official_interview_rubrics.json`；逐题跑 `ntce_material_repair.recover_case_materials`、`ntce_type_repair.repair_type`、答案 sanitize/recover/quarantine、跨题风险→quarantine（`extra.answer_candidate` 保全候选）；主观题 `practice_rubric`、选择题 `drop_choice_framework`（删除影子评分框架）；用 `ntce_ontology.select_nodes`（tagger=content-rule-v2）重打标签，但人工已复核或 llm-v2 有效签名的问题不动；`refresh_tags` 保留 `DIFFICULTY_TRACE_KEYS`（method/calibration/version/features）。写 `outline/*.json`（align_outline）、`review/baseline_metrics.json`（仅在缺失时写）、`review/pending.jsonl`、`review/question_type_source_audit.jsonl`、`stats.json`、`source_boundaries.jsonl`、`llm_tag_queue.jsonl`、`llm_analysis_failures.jsonl`、`rubrics/official_interview.json`、`MANIFEST.json`、cards（`sync_cards/card_path`），最后一步调 `build_graph.build()`。被 `build_kb`、`ntce_verify --check-idempotence`、`llm_batch`、`ntce_analysis_chain_fix`、`ntce_source_supplements` 及几乎所有 tests/ 教资用例间接调用。
- `build_graph.py`（229 行）—— 八层图谱导出器，`build()`（也可 `python kb_tools/build_graph.py` 直跑，无参数）。读 `数据集/教资/questions|outline|materials|rubrics|resources` + `权威资料/`（经 `kb_scope.select('ntce')` 过滤）+ `graph/edges_curated.jsonl`；curated 边只收 `prerequisite_of/confused_with/misconception_lead_to` 三种白名单，无署名 `verified` 的先修边降级为 `proposed_pending_review`。写 `graph/nodes.jsonl`、`graph/edges.jsonl` 并更新 MANIFEST 图谱统计。缺 knowledge/ability/requirement 节点或边端点悬空→`ValueError` 直接崩，这是设计行为。注意它 glob rubrics 时显式跳过 `README.md`（见坑第 3 条）。
- `ntce_verify.py`（93 行）—— 结构验收器。CLI：`python kb_tools/ntce_verify.py [--check-idempotence]`。不带参数：分母钉死 14500、ID 唯一、引用无悬空、退役 ID（`权威资料/retired_requirement_ids.json`）不得复活、`source.files[].path` 可解析（经 `教资/` 别名）、分析占位符（'缺','略','ABCDE'）检出、非客观题禁 `letter_only`、`source_conflict` 必须空答案、先修边规则、每模块 L2→L4 通路；写 `数据集/教资/review/verification.json`，有错 `SystemExit(1)`。带 `--check-idempotence`：跑两遍 `repair()` 并对全库做 sha256 快照比对，不一致即幂等回归。
- `ntce_contract.py`（192 行）—— 附录 A.1 状态词表迁移器，`python kb_tools/ntce_contract.py`（无参数）。幂等：把 `review.status` 别名（已清洗/待复核/低置信→契约词）、`answer_status` 别名（letter/brief/derived_reference→契约词）、MODEL_METHODS→`llm_enhanced`、无 `checked_by` 的 `checked`→`needs_fix`、`source_conflict`→`quarantined`、tags.review 镜像同步；同时重写 card front-matter（`migrate_card`）。跳过 `graph/` 与 `_backup` 目录；`migrate_jsonl` 按 `"\n"` 切分（正文含 U+2028，禁用 splitlines，见坑第 6 条）。残留非枚举状态时打印 UNMAPPED 并返回码 1。调用方：根 README 的契约迁移复跑顺序、`审查/_dryrun_contract.py`（外部试运行）。仓库根 `_contract_snapshot/`（141MB 迁移前快照，内容是 `数据集/教资/questions` 的旧版）没有任何脚本写它——未接线：只在根 README 出现（"不入库"）。
- `ntce_io.py`（20 行）—— 唯一的落盘出口：`atomic_write(path, text)`，同目录隐藏 `.tmp` + fsync + copymode + `os.replace`。全目录写 JSONL/JSON 都必须走它，防止半截文件被 tests/消费端读到；`ntce_repair` 的原子性由 `test_ntce_repair.py::test_atomic_writer_never_exposes_partial_file` 钉住。例外：`ntce_rubric_contract.py` 自带一套 temp+replace 的 `write_rows`，`ntce_difficulty.py` 的报告用了裸 `write_text`（见各自条目）。
- `kb_scope.py`（52 行）—— 纯函数库，无 CLI：`library_of/classify/select` 按 `exam_scope` 用 NTCE_MARKS/CET_MARKS 前缀把记录路由到两库之一；同时命中或都不命中→`ValueError`（宁可崩也不猜）。correction_evidence 除外。两库导出层（`build_graph.py` 与 `数据集/四六级/scripts/*`）共用它，是"一条记录只能进一库"契约的实现点。
- `ntce_ontology.py`（327 行）—— 内容规则本体模块，无 CLI。`ABILITY_NAMES`（10 项能力）、学科/公共/教学主题词表；`expand_outline` 生成稳定节点 ID（按行号后缀、append-only，不重排旧 ID）；`select_nodes` 每题取 top-3 可考知识点并附字面证据（method=`literal_content_rule`，拉丁词做词边界匹配）；`CHAPTER_NODE` 被 `ntce_repair` 引用。改词表会改变全库打标结果，必须双跑幂等验证。
- `m5_tag.py`（244 行）—— 大纲种子与打标 CLI：`python kb_tools/m5_tag.py outline|tag`（默认 tag）。`OUTLINES` 是大纲硬编码种子，`gen_outline` 合并时保留人工字段；`tag_all()` 实际只是调 `repair()`。主要由 `ntce_repair` 的 gen_outline/align_outline 流程 import；`--skip-outline` 时不调它。
- `llm_batch.py`（507 行）—— 通用 LLM 批量打标/解析器（非 DashScope 专用）：`python kb_tools/llm_batch.py refine-tag|gen-analysis|upgrade-analysis [--limit N] [--untagged-only] [--model M] [--retry-failed] [--subjects a,b] [--question-ids-file f] [--budget-cny X]`。env：`LLM_API_KEY/LLM_BASE_URL/LLM_MODEL`，本地 URL 需 `LLM_ALLOW_LOCAL=1`；`validate_base_url` 有 SSRF 拦截 + 禁重定向 opener。预算守卫对照 `数据集/教资/review/llm_usage.jsonl`，但单价表只有 deepseek-flash——`--budget-cny` 对其它模型不生效（诚实口径）。refine-tag 写 `knowledge_node_ids`（tagger=llm-v2）+ `extra.llm_tag_signature`；analysis 写 `extra.llm_analysis_signature` + result，method 为 `llm` 或 `llm_structured_from_source`；写 `review/llm_analysis_sample.jsonl`；结束时自动 `repair(skip_outline=True)`。`ANALYSIS_EXCLUSIONS` 正则跳过疾病/法律话题。导出的 `input_status/analysis_eligible/analysis_upgrade_eligible/question_brief` 被 `ntce_repair`、`ntce_analysis_sample`、`ntce_llm_audit` import。
- `batch_upgrade_ntce_analysis.py`（267 行）—— DashScope 批量升级教资解析：`python kb_tools/batch_upgrade_ntce_analysis.py --limit N|--all [--workers N] [--subject S] [--model M]`；无 `DASHSCOPE_API_KEY` 直接 exit 1。`is_eligible_ntce` 圈定范围；写 `analysis`（method=`<model>_structured_v1`，status=`llm_draft_pending_expert`）+ `content.analysis` + `extra.analysis_status`；每 30 题增量落盘、可断点续跑。跑完不会自动 repair——cards/graph 会短暂落后，需手动 `python kb_tools/ntce_repair.py --skip-outline`。由 `run_full_upgrade.py` 调用。
- `infer_ntce_candidate_answers.py`（280 行）—— 对客观题空答案做候选推断，CLI 同 `batch_upgrade_ntce_analysis`（`--limit/--all/--workers/--subject/--model`，另支持 `--dry-run`）；无 `DASHSCOPE_API_KEY` exit 1。只写 `extra.candidate_answer` + `extra.candidate_inference`（`*_deduced_candidate_v1`，状态 `candidate_pending_expert_review`）+ 解析草稿，绝不写 `content.answer`——答案落回仍需专家。被 `run_infer_all_cet.py` 的同名四六级脚本镜像。
- `ntce_analysis_chain_fix.py`（60 行）—— 一次性修复 2026-10-05 `upgrade-analysis` 的误升级：analysis method 已是 `llm_structured_from_source` 但 attempts[0] 是 `llm` 的记录回滚到 attempts[0]，并记 `discarded_reason`；跑完自动 `repair(skip_outline=True)`。按构造幂等（修过的记录不再命中）。`python kb_tools/ntce_analysis_chain_fix.py`。
- `ntce_analysis_cleanup.py`（134 行）—— `python kb_tools/ntce_analysis_cleanup.py [--dry-run]`。把命中 `TEMPLATE_MARKERS` 模板话术的 `analysis.option_compare` 置 None（`expert_verified` 的题目除外）；直接读写 `数据集/教资/questions`，不调 repair。失败口径：dry-run 只报计数。
- `ntce_analysis_fill.py`（333 行）—— 规则兜底解析生成器：`python kb_tools/ntce_analysis_fill.py [--dry-run] [--refresh]`（--refresh 只重算客观题且 method==rule_kb_draft）。诚实口径：只在选项含 ABSOLUTE_MARKERS 极端词时才给 option_compare，否则 None；从不署名、不调 repair。它的 `METHOD/build_key_info/build_option_compare/build_explanation/load_node_index/node_anchor` 被 `ntce_conflict_reconcile.py` import 复用。
- `ntce_analysis_sample.py`（62 行）—— LLM 解析试点的选题器：`prepare()`（`python kb_tools/ntce_analysis_sample.py`）按 sha 排序确定性选取 5 题/组 ×（小学/幼儿/中学综合、中学教育知识），条件是题干唯一可定位且答案键在源文件里对得上；凑不满 20 题→`RuntimeError`。写 `review/llm_analysis_plan.jsonl` + `llm_analysis_question_ids.json`。不打 API，供 llm_batch `--question-ids-file` 消费。
- `ntce_llm_audit.py`（87 行）—— 只读审计：`audit()`（`python kb_tools/ntce_llm_audit.py`）扫全库签名，写 `review/llm_audit.json`、`llm_context_audit.jsonl`、`llm_analysis_sample.md`；从 `review/llm_usage.jsonl` 汇总成本，`hard_budget_cny=5`，标记 legacy_48_question_pilot。不改任何题目。
- `ntce_conflict_reconcile.py`（290 行）—— 答案冲突回原卷核对：`python kb_tools/ntce_conflict_reconcile.py --scope xiaoxue/jiaoyuxinlixue --apply`（不带 --apply 只出证据）。`reconcile_one` 的闸门：answer_raw 存在、题号在原卷唯一定位、恰好 ABCD 四选项、无 cross_question_risk、单字母在选项内、与隔离时保全的 `extra.answer_candidate` 一致——任一不满足→refused 带编码理由。`--apply` 才落回：`answer_status=letter_only`、`quarantined→needs_fix`、记 `source_repairs`（kind=`source_conflict_answer_reconciled`），`refresh_rule_analysis` 复用 `ntce_analysis_fill` 的构建器，恢复的题走 `sync_cards`。每批证据写 `review/answer_conflict_reconciliation.<scope>.jsonl` + `.summary.json`；已核对过的题重跑会复核同一结论（批次证据可再生）。`run(..., review_dir=)` 参数专供 `test_ntce_conflict_reconcile.py` 重定向。
- `ntce_copyright_scope.py`（180 行）—— 版权范围声明：`python kb_tools/ntce_copyright_scope.py [--dry-run]`。写 `source.copyright.use_scope='research_non_commercial'`、按文件名判 source_nature（exam_recall/compiled_selection/provincial_exam/official_exam）、`attribution_required`；从不碰 `authorization_status`（授权与否要人来定）；人工已复核的记录跳过。
- `ntce_difficulty.py`（270 行）—— 启发式难度标定：`python kb_tools/ntce_difficulty.py`，`--dry-run` 经 sys.argv 判断（不是 argparse）。对 `difficulty=null` 的题按 OBJ_WEIGHTS 5 特征分位取 0.20–0.85，主观题 SUBJ_BASE+抖动；已有值的题不动（幂等）；`source_conflict`/`stem_incomplete` 保持 null。写 `review/difficulty_calibration_report.json`（用的是裸 write_text，非 atomic_write，这是已知不一致）。method 一律 `heuristic_*`，绝不冒充专家校准。
- `ntce_material_repair.py`（158 行）—— 材料修复模块，无独立 CLI，被 `repair()` 逐题调用：`recover_case_materials`（案例题材料从题干回收，mid=`<qid>.material.recovered`、原因 `trailing_case_detached`）、`case_risks()`、`has_inline_material`；同时清理无人认领的 recovered 材料。
- `ntce_type_repair.py`（148 行）—— 题型修复模块，无独立 CLI，被 `repair()` 调用：`repair_type` 用"当前题干在原 CSV 唯一定位到的那一题"来裁决 question_type，写 `extra.source_question_number` + `source_boundary_verification='unique_text_boundary'`；定位不了或非客观题却是 `letter_only`→quarantine（理由 `nonobjective_letter_quarantined`）。`source_sections/choice_evidence` 供其他模块 import。
- `ntce_reference_import.py`（133 行）—— 参考解答导入器：`python kb_tools/ntce_reference_import.py`，`--refresh-locators` 经 sys.argv。读 `补充资料/教资参考解答/reference_drafts.jsonl`；逐条验证：题目存在、未人工复核、无既有 content、题干 sha 与 `expected_stem_sha256` 相符、origin 全文唯一、源文件 sha256 + 物理 LF 定位器上下文 sha + THEORY_TERMS 全过——任一失败即拒绝。通过→`answer_status=reference_only`、答案标 `original_reference_draft_pending_expert`、解析草稿、rubric points 记 `<draft_id>.pN`；写 `review/reference_draft_import.jsonl` + summary。不调 repair，导入后要手动 `ntce_repair.py --skip-outline`。
- `ntce_source_audit.py`（56 行）—— 只读审计：`audit()`（`python kb_tools/ntce_source_audit.py`）对 `reference_only` 的题重读答案源文件，产出 result 码：source_only_refers_to_missing_analysis / source_explicit_answer_conflict / source_contains_answer_candidate / source_placeholder_missing_answer / source_number_missing / answer_file_missing；写 `review/reference_answer_source_audit.jsonl` + summary。是冲突核对（ntce_conflict_reconcile）的前置证据来源。
- `ntce_source_supplements.py`（96 行）—— 定向源数据补充清单：3 条 BRIEF（安康学院文本；`数据集/教资/sources/aku_education_reference.txt` 缺失→`RuntimeError`）+ 5 条 LAW（教师法 39 条）的 ID 硬编码写进题目源记录；跑完自动 `repair(skip_outline=True)`，`--no-sync` 可跳过。`python kb_tools/ntce_source_supplements.py`。
- `ntce_option_compare.py`（247 行）—— 选项对比导入/验证器：`python kb_tools/ntce_option_compare.py --scope gaozhong|chuzhong|youer|zhongxue|xiaoxue|all [--subjects a,b] [--input {qid:text}.json] [--verify-only]`。BANNED 措辞 + 最短 30 字双闸，不过就拒收；收写 `analysis.option_compare` + `option_compare_meta`（method=`agent_curated_v1`，仍需专家）；`--verify-only` 报 banned/missing_answer_letter/too_short。
- `ntce_rubric_contract.py`（96 行）—— 量规契约整理：`PYTHONIOENCODING=utf-8 python kb_tools/ntce_rubric_contract.py [--dry-run]`（Windows 控制台编码，见坑第 9 条）。与 `repair()` 共用 `drop_choice_framework` 删选择题影子框架；规范化 `rubrics/*.json`：删 `name/levels/max_level` 遗留键（与 `dimension_name/criteria_levels/weight_score` 并存即双真相）、`expert_verified`→false、review 置 `needs_fix`/pending RUBRIC_PENDING。迁移前快照写 `归档/教资_迁移前快照_20261009/`。写盘用它自己的 `write_rows`（temp+replace，非 ntce_io.atomic_write）。
- `ntce_rubric_points.py`（339 行）—— 主观题采分点生成：`python kb_tools/ntce_rubric_points.py [--types 材料分析 教学设计 简答] [--dry-run]`。用 `parse_subquestions` + 模板确定性生成 points；跳过客观题和人工已复核的量规；`official_scoring/expert_verified` 保持 false。不调 repair。跑批顺序参见下一个条目。
- `ntce_rubric_points_report.md`（96 行）—— 不是脚本，是 2026-10-07 那次 `ntce_rubric_points.py` 跑批的报告：计划 2582 条 vs 入库 2579（3 条丢失归因于与难度标定并发写）。给出的顺序结论：difficulty 落定 → 重跑 rubric_points → `ntce_repair.py --skip-outline` ×2。改这两个工具前应先读它。
- `official_examples.py`（388 行）—— 教资官方样题抽取器：`python kb_tools/official_examples.py [--root PATH] [--output PATH]`（默认 `补充资料/教资官方样题`）。从 `权威资料/catalog.json` 里 ntce.outline.*/ntce.interview.* 源抽样题，全程 sha256 守护：样题源字节被改→`ValueError`；`ntce.outline.317` 特判配合 `visual_verification.json` 人工看图机制。写 `official_examples.jsonl`、`source_sample_sections.jsonl`、`exact_matches.jsonl`、`recovery_patches.jsonl`、`summary.json`——只提供审阅补丁，从未写主库。由 `test_official_examples.py` 直接 import 回归。
- `cet_official_examples.py`（765 行）—— 四六级官方样题抽取器（2016 考试大纲 PDF）：`python kb_tools/cet_official_examples.py [--root PATH] [--render]`。读 `权威资料/originals/cet.syllabus.2016.pdf`（EXPECTED_SHA256 钉死），CID 字体空格恢复；写 `补充资料/四六级官方样题/`：`source_pages.json`、`reconstructed_source.txt`、`official_examples.jsonl`、`questions.jsonl`、`passages.jsonl`、`oral_samples.jsonl`、`source_sections.jsonl`、`exact_matches.jsonl`、`recovery_patches.jsonl`、`summary.json`、`index.html` 浏览器页（summary 里 `main_corpus_modified: False` 是契约）。`--render` 额外渲染原页 PNG 并写排版对账表。由 `test_cet_official_examples.py` import 回归（其中 `extract_official` 被 setUpClass 真实跑，PDF 缺失即全套 error）。
- `gen_cet_sample_analysis.py`（110 行）—— 注意：这是顶层脚本、没有 `__main__` 守卫，import 即执行；无参数。硬编码 5 道 CET 题（cet4-2015-06-p1-reading-46/47/48、listening-1/4——文件头注释写"5 阅读 + 3 听力"与实际 ID 列表不符，以代码为准）。读 `数据集/四六级` 的 passages+questions，需 `DASHSCOPE_API_KEY`（无则 exit 1）；只写 `审查/四六级解析小样复查.json`，不写库。复跑流程记录在 `审查/README.md`；无任何 tests/ 用例 import 它。
- `harness_analysis_import.py`（109 行）—— 会话侧 LLM 解析回灌器：`python kb_tools/harness_analysis_import.py`（无参数）。读 `审查/harness_batches/results/batch_*_results.jsonl`，写题 `analysis`（method=`harness_llm`，model=`GLM-5.3-Flash(session)`，generation.channel=`zcode_session_subagent`）；已有 analysis 的题跳过（幂等）；不调 repair，回灌后要手动同步。
- `run_full_upgrade.py`（80 行）—— 全库升级编排：`python kb_tools/run_full_upgrade.py [--workers N] [--cet-limit N] [--ntce-limit N] [--ntce-only|--cet-only]`。按序 subprocess 调：`数据集/四六级/scripts/batch_upgrade_analysis.py` → `kb_tools/batch_upgrade_ntce_analysis.py` → `python -m unittest discover -s tests` → `python 权威资料/verify_sources.py` → `python 审查/知识库形式审查.py`；任一环节非零退出即停。
- `run_infer_all_cet.py`（45 行）—— 四六级候选答案编排：`python kb_tools/run_infer_all_cet.py [--workers N] [--limit N]`。先跑 `数据集/四六级/scripts/infer_candidate_answers.py`，再跑回归三件套（pytest/validate_kb/状态词表检查）。

## 管线顺序

首次从 CSV 建库（`教资/真题/` 必须在）：

```bash
python kb_tools/build_kb.py build          # 解析 + 首轮 repair()
python kb_tools/ntce_verify.py             # 结构验收，非零即停
```

日常修复/再生（改完本目录代码后的标准动作）：

```bash
python kb_tools/ntce_repair.py --skip-outline   # 幂等重算，内部自动 build_graph
python kb_tools/ntce_verify.py --check-idempotence
python -m pytest tests -q
python 审查/validate_kb.py
python 审查/状态词表检查.py
```

状态词表迁移（出现旧词/别名时）：

```bash
python kb_tools/ntce_contract.py           # 有 UNMAPPED 残留则返回 1
python kb_tools/ntce_repair.py --skip-outline
```

LLM 打标/解析（通用网关版）：

```bash
python kb_tools/ntce_analysis_sample.py    # 先出试点题单
python kb_tools/llm_batch.py refine-tag --question-ids-file 数据集/教资/review/llm_analysis_question_ids.json
python kb_tools/llm_batch.py gen-analysis --limit 20
# llm_batch 结尾自动 repair(skip_outline=True)，无需手动补
```

DashScope 批量升级与推断（需 `DASHSCOPE_API_KEY`）：

```bash
python kb_tools/run_full_upgrade.py --ntce-only
python kb_tools/batch_upgrade_ntce_analysis.py --all
python kb_tools/ntce_repair.py --skip-outline   # 上一步不自带同步，必须补跑
```

冲突核对回答案（按学段/科目分批）：

```bash
python kb_tools/ntce_source_audit.py
python kb_tools/ntce_conflict_reconcile.py --scope xiaoxue/jiaoyuxinlixue          # 只出证据
python kb_tools/ntce_conflict_reconcile.py --scope xiaoxue/jiaoyuxinlixue --apply  # 证据合格才落回
```

官方样题抽取（两库，只写 `补充资料/`）：

```bash
python kb_tools/official_examples.py
python kb_tools/cet_official_examples.py
```

## 改这里之前要知道的

1. **工作区别名是硬编码路径的一部分**：`权威资料/` → `官方权威资料/`、`教资/` → `教资原始资料/` 是仓库根的符号链接，不进版本库。缺了它们 `build_kb` 找不到题源、`ntce_verify` 报 source 不可解析、下游 22 个测试直接 error（见根 README"工作区别名"）。重建：`ln -s "$(pwd)/官方权威资料" 权威资料`、`ln -s "$(pwd)/教资原始资料" 教资`。绝不通过这两个别名路径写文件——它们指向的原始资料只读。
2. **生成物不许手改**：`数据集/**` 下的一切（含 cards、graph、review/*.json）都是本目录脚本的产物，手改会在下一次 `repair()` 时被覆盖或制造哈希不一致。唯一例外是设计上允许人工扩展的字段（人工复核状态、curated 边、量规人工修订），`repair()` 有显式保留逻辑（`test_ntce_repair.py::test_manual_rubric_and_tag_extensions_survive_refresh`）。
3. **`build_graph.py` 在 glob `rubrics/*.json` 时显式跳过 `README.md`**：往 rubrics 目录放说明文件只能用 `README.md` 这个名字；任何其它 `*.json` 都会被当成量规解析并进入图谱。
4. **`_contract_snapshot/` 与 `归档/` 都不由脚本生成**：仓库根的 `_contract_snapshot/`（141MB，迁移前 `数据集/教资/questions` 的旧版快照）和 `归档/`（281MB）只在根 README 出现、不入库；`ntce_contract.py` 不写快照目录。别指望跑脚本能重建它们。
5. **有些工具改完 questions 不碰卡片和图谱**：`ntce_reference_import`、`ntce_copyright_scope`、`ntce_rubric_points`、`ntce_analysis_cleanup/fill`、`batch_upgrade_ntce_analysis`、`harness_analysis_import` 都不调 `repair()`。用完必须补 `python kb_tools/ntce_repair.py --skip-outline`，否则 cards/graph 与 questions 漂移，`test_acceptance_gate.py` 的 A11（索引新鲜度）会红。
6. **JSONL 行分隔只能按 `"\n"`**：题目正文含 U+2028 等奇异字符，`str.splitlines()` 会把一行拆成两行——`ntce_contract.migrate_jsonl`、各测试的 `rows()` 全部手写 `split("\n")`，新代码要照抄这个口径。
7. **诚实性红线是代码契约不是口号**：任何工具不得写 `checked_by/expert_verified`（`checked` 无署名会被 `ntce_contract` 打回 `needs_fix`）；难度只能标 `heuristic_*`；LLM 产出只到 `llm_draft_pending_expert/candidate_pending_expert_review`；选择题携带评分框架直接违反附录 A.6（`drop_choice_framework` 在 repair 里每次强制执行）。
8. **幂等 = 双跑哈希一致**：`repair()` 重跑不允许重新分配 ID、不允许时间戳入文件（`test_completeness_audit.py` 专门禁止 `generated_at`）。改了任何影响输出的代码先跑 `--check-idempotence` 再看测试。
9. **Windows/Git Bash 细节**：`ntce_rubric_contract.py` 需要 `PYTHONIOENCODING=utf-8`（打印中文统计）；`ntce_difficulty.py` 与 `ntce_reference_import.py` 的开关是 `sys.argv` 判断而非 argparse，加参数时别按 argparse 习惯改。
10. **`build_kb.py` 是隐式依赖中枢**：全目录十几个模块 `from build_kb import ...`；在包外以脚本方式运行时它靠 `parents[1]` 定位仓库根，移动文件会断掉 ROOT/OUT 与全部 import 链。
