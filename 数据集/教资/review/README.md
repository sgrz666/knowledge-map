# 教资KB/review — 质量审计与待办队列

本目录存放全库审计结果与教研专家待复核队列。

## 核心文件
- **verification.json**：幂等性双跑对比快照与结构化错误统计（structural_errors: 0）。
- **pending.jsonl**：全库保留的待专家审核、待标定真实缺口清单。
- **source_boundaries.jsonl**：边界排查日志。
- **answer_conflict_reconciliation.jsonl**：答案冲突回原卷核对的逐题证据，由 `kb_tools/ntce_conflict_reconcile.py` 整批再生。每行一题，含题号、所在批次、核对结论（`reconciled` / `refused`）、拒绝原因、原卷答案文件与卷内题号、隔离时保全的候选答案，以及落回前后的字段对照（答案、`answer_status`、审核状态、答案校验状态、来源边界状态）与同步重写的规则解析草稿。
- **answer_conflict_reconciliation_summary.json**：同批汇总。`restored_in_dataset` 与 `still_quarantined` 说明题库数据实况；`applied`、`scopes_touched`、`cards_rewritten_this_run` 只描述当次运行模式——默认运行只出证据不改数据，所以这些字段会是 `false` / 空 / 0，不代表这批没落回。

落回只承认"题干在原卷唯一定位到题号 + 答案键该题号是单字母且落在印刷选项内 + 与保全候选一致"三件同时成立；核对不出来一题也不动，继续留在 `source_conflict` 与 `quarantined`。审核签署字段（`checked_by`、`content_verified`）不因落回而提升，`answer_validation_status` 记为 `not_expert_verified`，`expert_content_review_needed` 留在待补项里。
