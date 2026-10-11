# 教资KB/review — 质量审计与待办队列

本目录存放全库审计结果与教研专家待复核队列。

## 核心文件
- **verification.json**：幂等性双跑对比快照与结构化错误统计（structural_errors: 0）。
- **pending.jsonl**：全库保留的待专家审核、待标定真实缺口清单。
- **source_boundaries.jsonl**：边界排查日志。
- **answer_conflict_reconciliation.jsonl**：答案冲突回原卷核对的逐题证据，由 `kb_tools/ntce_conflict_reconcile.py` 整批再生。每行一题，含题号、所在批次、核对结论（`reconciled` / `refused`）、拒绝原因、原卷答案文件与卷内题号、隔离时保全的候选答案，以及落回前后的字段对照（答案、`answer_status`、审核状态、答案校验状态、来源边界状态）与同步重写的规则解析草稿。
- **answer_conflict_reconciliation_summary.json**：同批汇总。`restored_in_dataset` 与 `still_quarantined` 说明题库数据实况；`applied`、`scopes_touched`、`cards_rewritten_this_run` 只描述当次运行模式——默认运行只出证据不改数据，所以这些字段会是 `false` / 空 / 0，不代表这批没落回。

## 题面串题证据（`content_boundary`）

带跨题风险的拒绝题不只写一个风险码，还附 `content_boundary`，把"题面吞了邻题"落到可核对的位置：`sequence_fields` / `sequence_counts` 指出完整 A-D 选项序列出现在哪个字段、出现几次（题干还是某个选项、吞了几道），`combined_sequences` 是题干加全部选项里的完整序列总数，`embedded_numbers` 是正文里露出来的邻题编号，`embedded_numbers_without_record` 进一步区分这些编号在本卷**有没有独立题记录**。

这个区分决定下一步：编号有独立记录，说明同一份文本存了两处，该剪的是重复；编号在本卷没有任何记录，那段文本是库里唯一一份，剪掉就等于删题，要走的是回原件补收录。所以证据只定位与分诊，不自动剪文本。

`embedded_numbers` 按"数字 + 邻题常见开头词"识别，是**下限而不是穷举**——识别不出编号的串题仍由序列计数暴露；编号本身也可能与库内重新编号后的题号不对应，对不上只说明"本卷没有这条记录"，是否漏收录要回原件判断。汇总里的 `refused_with_open_question_boundary` 统计的是"题面带串题风险的拒绝题"，与拒绝原因 `cross_question_risk_open` 的计数不必相等：题型不合（如五选项多选）会先触发拒绝，串题证据照样登记。

串题检测的口径只有一份，在 `kb_tools/ntce_repair.py`（`mix_risk_evidence` / `source_mix_risks`）；核对工具与修复轮读同一份，不得另写正则。

落回只承认"题干在原卷唯一定位到题号 + 答案键该题号是单字母且落在印刷选项内 + 与保全候选一致"三件同时成立；核对不出来一题也不动，继续留在 `source_conflict` 与 `quarantined`。审核签署字段（`checked_by`、`content_verified`）不因落回而提升，`answer_validation_status` 记为 `not_expert_verified`，`expert_content_review_needed` 留在待补项里。
