# 教资KB/review — 质量审计与待办队列

本目录存放全库审计结果与教研专家待复核队列。

## 核心文件
- **verification.json**：幂等性双跑对比快照与结构化错误统计（structural_errors: 0）。
- **pending.jsonl**：全库保留的待专家审核、待标定真实缺口清单。
- **source_boundaries.jsonl**：边界排查日志。
- **answer_conflict_reconciliation.<学段>_<科目>.jsonl**：答案冲突回原卷核对的逐题证据，**一批科目一份**，由 `kb_tools/ntce_conflict_reconcile.py` 整批再生。每行一题，含题号、批次与卷面、卷内题号、核对结论（`reconciled` / `refused`）、拒绝原因、原卷答案文件、印刷选项、答案键原文与字母、隔离时保全的候选、落回依据（`basis`）；拒绝题另附 `content_boundary`。目录里有几对文件，就说明核对过几批。
  落回前后的字段对照（答案、`answer_status`、复核态、答案校验状态、来源边界状态）与同步重写的规则解析草稿**不在证据里**，写在题记录的 `extra.source_repairs`：证据回答"凭什么落回"，题记录回答"改了哪几个字段"。
- **answer_conflict_reconciliation.<学段>_<科目>.summary.json**：同批汇总。`batch` 与 `scope` 分开写（一个是这批、一个当次跑了什么范围），`restored_in_dataset` 与 `still_quarantined` 说明题库数据实况；`applied`、`scopes_touched`、`cards_rewritten_this_run` 只描述当次运行模式——默认运行只出证据不改数据，所以这些字段会是 `false` / 空 / 0，不代表这批没落回。补收录那一侧的两个字段与 `审查/待复核清单.md` §3.2 同口径：`boundary_questions_without_record` 数"露出至少一个无独立记录编号"的题，`boundary_numbers_without_record` 数条，按（学段/科目 · 卷面 · 编号）去重。

一批一份不是排版选择：原先全库共用一对文件，核对第二个科目时同一行 `write_rows` 把上一批的题号、依据与结论整批覆盖掉，修补历史就断了。没被安排核对的科目不会因为跑了一次测试而在这里留下文件。

## 题面串题证据（`content_boundary`）

带跨题风险的拒绝题不只写一个风险码，还附 `content_boundary`，把"题面吞了邻题"落到可核对的位置：`sequence_fields` / `sequence_counts` 指出完整 A-D 选项序列出现在哪个字段、出现几次（题干还是某个选项、吞了几道），`combined_sequences` 是题干加全部选项里的完整序列总数，`embedded_numbers` 是正文里露出来的邻题编号，`embedded_numbers_without_record` 进一步区分这些编号在本卷**有没有独立题记录**。

这个区分决定下一步：编号有独立记录，说明同一份文本存了两处，该剪的是重复；编号在本卷没有任何记录，那段文本是库里唯一一份，剪掉就等于删题，要走的是回原件补收录。所以证据只定位与分诊，不自动剪文本。

`embedded_numbers` 按"数字 + 邻题常见开头词"识别，是**下限而不是穷举**——识别不出编号的串题仍由序列计数暴露；编号本身也可能与库内重新编号后的题号不对应，对不上只说明"本卷没有这条记录"，是否漏收录要回原件判断。汇总里的 `refused_with_open_question_boundary` 统计的是"题面带串题风险的拒绝题"，与拒绝原因 `cross_question_risk_open` 的计数不必相等：题型不合（如五选项多选）会先触发拒绝，串题证据照样登记。

串题检测的口径只有一份，在 `kb_tools/ntce_repair.py`（`mix_risk_evidence` 出证据，`boundary_risks` 把证据映成风险码，`recorded_numbers` 给出同一份卷面里已独立入库的题号，`unrecorded_neighbors` 算出其中没有记录的邻题）；核对工具、修复轮与 `审查/build_review_queue.py` 都读这一份，不得另写正则。

每批文件只覆盖**该批核对过的题**（落回与拒绝都在内）。全库同一缺陷的规模在 `审查/待复核清单.md` §3.2 现算，两侧动作分三档写：邻题在本卷都有独立记录（剪重复文本）／有编号在本卷没有独立记录（回原件补收录，按"学段/科目/卷面文件·编号"去重）／命中序列但认不出任何编号（人工回卷，机器不给结论）。漏收邻题在库里表现为根本没有那条记录，`审查/validate_kb.py` 的题级缺口码不会单独计数，只能靠现算清单发现。

落回只承认"题干在原卷唯一定位到题号 + 答案键该题号是单字母且落在印刷选项内 + 与保全候选一致"三件同时成立；核对不出来一题也不动，继续留在 `source_conflict` 与 `quarantined`。审核签署字段（`checked_by`、`content_verified`）不因落回而提升，`answer_validation_status` 记为 `not_expert_verified`，`expert_content_review_needed` 留在待补项里。

## 逐文件清单

以下全部数字为 2026-10 现算：大小取文件字节数，行数取逐行计数（jsonl 一行一条）；每批 `reconciled` / `refused` 逐行读取证据 jsonl 的 `result` 字段统计所得，summary 关键计数逐字段读取对应 summary.json。核对脚本在仓库外（`D:\tmp\scan_review.py`），本目录数据文件未被改动。

### 答案冲突回原卷核对批次（11 对 22 个文件）

| 批次（学段·科目） | jsonl（字节/行） | 现算 reconciled / refused | summary.json（字节/行） | summary 关键计数（现算） |
|---|---|---|---|---|
| 初中·地理 `chuzhong/dili` | `answer_conflict_reconciliation.chuzhong_dili.jsonl` 54547B/61行 | 1 / 60 | `answer_conflict_reconciliation.chuzhong_dili.summary.json` 888B/24行 | inspected 61；applied true；restored_in_dataset 1；still_quarantined 60；refused_with_open_question_boundary 44；boundary_questions_without_record 4；boundary_numbers_without_record 4；scopes_touched ["chuzhong/dili"]；cards_rewritten_this_run 1 |
| 初中·数学 `chuzhong/shuxue` | `answer_conflict_reconciliation.chuzhong_shuxue.jsonl` 46750B/51行 | 11 / 40 | `answer_conflict_reconciliation.chuzhong_shuxue.summary.json` 898B/24行 | inspected 51；applied true；restored_in_dataset 11；still_quarantined 40；refused_with_open_question_boundary 29；boundary_questions_without_record 2；boundary_numbers_without_record 3；scopes_touched ["chuzhong/shuxue"]；cards_rewritten_this_run 11 |
| 初中·信息技术 `chuzhong/xinxi` | `answer_conflict_reconciliation.chuzhong_xinxi.jsonl` 49811B/50行 | 0 / 50 | `answer_conflict_reconciliation.chuzhong_xinxi.summary.json` 846B/21行 | inspected 50；applied false；restored_in_dataset 0；still_quarantined 50；refused_with_open_question_boundary 45；boundary_questions_without_record 3；boundary_numbers_without_record 3；scopes_touched []；cards_rewritten_this_run 0 |
| 高中·地理 `gaozhong/dili` | `answer_conflict_reconciliation.gaozhong_dili.jsonl` 72850B/80行 | 0 / 80 | `answer_conflict_reconciliation.gaozhong_dili.summary.json` 845B/21行 | inspected 80；applied false；restored_in_dataset 0；still_quarantined 80；refused_with_open_question_boundary 60；boundary_questions_without_record 4；boundary_numbers_without_record 4；scopes_touched []；cards_rewritten_this_run 0 |
| 高中·化学 `gaozhong/huaxue` | `answer_conflict_reconciliation.gaozhong_huaxue.jsonl` 35221B/38行 | 5 / 33 | `answer_conflict_reconciliation.gaozhong_huaxue.summary.json` 894B/24行 | inspected 38；applied true；restored_in_dataset 5；still_quarantined 33；refused_with_open_question_boundary 20；boundary_questions_without_record 8；boundary_numbers_without_record 9；scopes_touched ["gaozhong/huaxue"]；cards_rewritten_this_run 5 |
| 高中·历史 `gaozhong/lishi` | `answer_conflict_reconciliation.gaozhong_lishi.jsonl` 163973B/173行 | 125 / 48 | `answer_conflict_reconciliation.gaozhong_lishi.summary.json` 897B/24行 | inspected 173；applied true；restored_in_dataset 125；still_quarantined 48；refused_with_open_question_boundary 25；boundary_questions_without_record 3；boundary_numbers_without_record 3；scopes_touched ["gaozhong/lishi"]；cards_rewritten_this_run 95 |
| 高中·信息技术 `gaozhong/xinxi` | `answer_conflict_reconciliation.gaozhong_xinxi.jsonl` 54329B/56行 | 0 / 56 | `answer_conflict_reconciliation.gaozhong_xinxi.summary.json` 847B/21行 | inspected 56；applied false；restored_in_dataset 0；still_quarantined 56；refused_with_open_question_boundary 46；boundary_questions_without_record 3；boundary_numbers_without_record 2；scopes_touched []；cards_rewritten_this_run 0 |
| 小学·教育心理学 `xiaoxue/jiaoyuxinlixue` | `answer_conflict_reconciliation.xiaoxue_jiaoyuxinlixue.jsonl` 31068B/34行 | 22 / 12 | `answer_conflict_reconciliation.xiaoxue_jiaoyuxinlixue.summary.json` 883B/22行 | inspected 34；applied false；restored_in_dataset 22；still_quarantined 12；refused_with_open_question_boundary 7；boundary_questions_without_record 2；boundary_numbers_without_record 2；scopes_touched []；cards_rewritten_this_run 0 |
| 小学·教育学 `xiaoxue/jiaoyuxue` | `answer_conflict_reconciliation.xiaoxue_jiaoyuxue.jsonl` 23699B/29行 | 4 / 25 | `answer_conflict_reconciliation.xiaoxue_jiaoyuxue.summary.json` 944B/25行 | inspected 29；applied true；restored_in_dataset 4；still_quarantined 25；refused_with_open_question_boundary 10；boundary_questions_without_record 3；boundary_numbers_without_record 7；scopes_touched ["xiaoxue/jiaoyuxue"]；cards_rewritten_this_run 4 |
| 小学·综合素质 `xiaoxue/zonghe` | `answer_conflict_reconciliation.xiaoxue_zonghe.jsonl` 47793B/48行 | 24 / 24 | `answer_conflict_reconciliation.xiaoxue_zonghe.summary.json` 851B/23行 | inspected 48；applied true；restored_in_dataset 24；still_quarantined 24；refused_with_open_question_boundary 22；boundary_questions_without_record 7；boundary_numbers_without_record 9；scopes_touched ["xiaoxue/zonghe"]；cards_rewritten_this_run 24 |
| 中学·教育学 `zhongxue/jiaoyuxue` | `answer_conflict_reconciliation.zhongxue_jiaoyuxue.jsonl` 21151B/27行 | 3 / 24 | `answer_conflict_reconciliation.zhongxue_jiaoyuxue.summary.json` 901B/24行 | inspected 27；applied true；restored_in_dataset 3；still_quarantined 24；refused_with_open_question_boundary 6；boundary_questions_without_record 3；boundary_numbers_without_record 7；scopes_touched ["zhongxue/jiaoyuxue"]；cards_rewritten_this_run 3 |

11 批逐行合计 647 题：reconciled 195、refused 452；每批 jsonl 行数与同批 summary 的 `inspected` 一致，逐行 `result` 计数与 `by_result` 一致，带 `content_boundary` 的行数与 `refused_with_open_question_boundary` 一致（如 gaozhong/dili 60 行、chuzhong/xinxi 45 行）。目录里有 11 对文件，按上文口径即核对过 11 批。

### 其余 20 个条目

| 文件名 | 大小 | 行数/条目数 | 现算内容 |
|---|---|---|---|
| `verification.json` | 1055B | 29行 | questions 14500；structural_errors 0；errors []；pending_questions 14500；幂等对比 files_checked 13899、changed_files []、passed true、snapshot_sha256 c1d70dc7…fb5f168c |
| `pending.jsonl` | 4830950B | 14500行（14500条） | 每行含 question_id、reasons、origin_file；与 verification.json 的 pending_questions 14500 对上 |
| `source_boundaries.jsonl` | 446730B | 922行（922条） | 每行 question_id、origin_file、boundary、risk、answer_candidate |
| `llm_usage.jsonl` | 1031968B | 1298行（1298条） | 每次 LLM 调用一行：created_at、requested_model、prompt_sha256、input_bytes、thinking、status、question_ids |
| `baseline_metrics.json` | 384B | 16行 | questions 14500；knowledge_mapped 12109；answers_nonempty 11062；answer_status 分布 letter 10991 / reference 3339 / missing 99 / brief 71；answer_not_in_options 23；choice_options_under_four 834 |
| `difficulty_calibration_report.json` | 878B | 18行 | version heuristic-v1；total 14500；filled_total 12720；new_this_run 0；kept_null 1780；objective_n 9706；subjective_n 3014 |
| `llm_audit.json` | 1780B | 62行 | questions 14500；eligible_complete_context 10732；skipped_context 3768；current_llm_mapped 2339；saved_llm_results 2471；saved_llm_successful_drafts 2439；saved_llm_unmatched 32；invalidated_context_results 82；still_unmapped 1561；conservative_total_cny 1.88755；hard_budget_cny 5 |
| `llm_context_audit.jsonl` | 5675166B | 14500行（14500条） | 每题一行的输入完备性审计（question_id、input_status） |
| `llm_tag_queue.jsonl` | 420877B | 1418行（1418条） | 待打标队列逐行记录 |
| `question_type_source_audit.jsonl` | 10784840B | 14500行（14500条） | 题型级来源定位审计，全库每题一行 |
| `reference_answer_source_audit.jsonl` | 3149276B | 3339行（3339条） | 参考答案来源逐题审计；行数与 baseline_metrics 的 answer_status.reference 3339 对上 |
| `reference_answer_source_audit_summary.json` | 13795B | 228行 | records 3339；by_result：source_only_refers_to_missing_analysis 2602、source_contains_answer_candidate 722、source_number_missing 5、source_placeholder_missing_answer 9、source_explicit_answer_conflict 1 |
| `reference_draft_import.jsonl` | 2422B | 16行（16条） | 草稿引用刷新逐题记录（question_id、status、draft_id、expert_verified） |
| `reference_draft_import_summary.json` | 125B | 7行 | candidates 16；by_status references_refreshed 16；skip_reasons {}；expert_verified false |
| `llm_analysis_plan.jsonl` | 39872B | 20行（20条） | 试点分析计划逐题记录（question_id、stem 等） |
| `llm_analysis_question_ids.json` | 738B | 21行 | JSON 数组 20 个 question_id，与 plan 的 20 条对上 |
| `llm_analysis_failures.jsonl` | 187626B | 188行（188条） | 试点分析失败/争议逐题记录（question_id、result） |
| `llm_analysis_sample.jsonl` | 1B | 0条 | 仅一个换行符，无记录 |
| `llm_analysis_sample.md` | 43893B | 524行 | 试点分析样本的人类可读文档 |
| `README.md` | 5010B | 27行 | 本节追加之前的口径正文（本节自身行数不计入） |

### 现算修正

- 上文口径"目录里有几对文件，就说明核对过几批"：现算为 11 对 / 22 个文件。此前流转的任务描述写的旧值"13 对 / 26 个文件"按现算修正为 11 对 / 22 个文件。
- 旧值"该目录 41 个条目"按现算修正：全目录含 `README.md` 自身共 42 个文件，除 README 外 41 个。
- 证据 jsonl 中"核对结论"的实际字段名是 `result`（取值 `reconciled` / `refused`），"落回依据"实际字段名 `basis`，"隔离时保全的候选"实际字段名 `preserved_candidate`；原文只用中文描述、未点名这三个字段，此处以现算补实名，不构成数字冲突。
- `verification.json` 的 structural_errors 旧口径 0 与现算 0 一致，无需修正。
