# 网页端验收记录

2026-10-11。分三档写明：完整自动化覆盖、真实浏览器实测、尚未实测。没跑过的不写成跑过。

## 自动化

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

`421 项通过、55 个子测试通过`。跑测试要先把状态目录指向临时处（`$env:KNOWLEDGE_MAP_STATE_DIR = <空目录>`），否则网页用例会把练习卷和提交写进本机 `.local_state/`。

## 提交重试一致性（必修项）

问题原本的形状：第一次作答已经落进掌握度、错题和事件收据，网页结果却没能保存；页面允许改答案重交，后端按新答案判"答对"，Memory 回放第一次的"答错"，最终永久存下自相矛盾的画像。现在收据带输入指纹（`services/memory/receipt.py`），判据见下表。

| 验收点 | 结果 | 覆盖位置 |
| --- | --- | --- |
| 同一事件 ID、相同输入 | 原样回放，题目次数与考点写入都不重复 | `test_same_id_same_inputs_replays_without_a_second_write` |
| 同一 ID、改答案／改耗时／改选项翻转 | `409`，拒绝发生在任何新增学习写入之前 | `test_same_id_changed_inputs_are_refused_before_any_write`、`test_saved_submission_replays_only_that_exact_attempt` |
| 一道多考点题 | 题目只计一次作答，各考点各自更新 | `test_multinode_submission_counts_one_attempt_and_keeps_all_mastery` |
| 返回结果的对错与复习记录 | 同一来源：库内答案键核对，回放不换判据 | 同上，另见 `verdict_source` 断言 |
| 旧收据没有指纹 | 既不回放也不重写，一律 `409`，不默认视为匹配 | `test_receipts_written_before_fingerprinting_migrate_and_then_refuse_replay` |
| 已有库补迁移 | 打开时按 `PRAGMA table_info` 加列，旧行指纹留空 | 同上 |
| 清理学习记录 | `clear()` 同步删 `memory_events`，重置后重新计数 | `test_clear_drops_receipts_so_a_reset_learner_is_counted_again` |

对本机真实状态库的**副本**跑过迁移：`memory.sqlite3` 补出 `user_id`／`fingerprint` 两列，26 条画像与 12 条错题记录不动，14 条旧收据全部记为"无法核对"；`workbench.sqlite3` 补出 `fingerprint` 列，3 份卷、1 条提交不动，那条无指纹提交按 `409` 处理。也就是说这台机器上指纹上线前的重放口子是关着的，要恢复只能清空本机学习记录。

## 真实浏览器实测

后端空 Key（规则模式）、`http://127.0.0.1:8001`、学习者 `retry-verify`、每日一练两份题。

1. 生成练习卷 → 第一题作答后让响应在半路丢掉（服务端已写入，页面拿不到结果）：页面提示失败、作答项锁定、按钮转为"重试提交（沿用上次作答参数）"，`localStorage` 存下原始请求参数（答案 `A`、耗时 6.145 秒、翻转 0）。
2. 刷新：练习卷按学习者／考试／学段／科目／档位恢复，提交行已在库里，直接显示"已提交"，待完成参数清掉。
3. 第二题在请求发出前失败（什么都没存下）：待完成参数落 `localStorage`；重试发出的仍是原参数，耗时没有被重新计算（46.877 秒逐字一致），成功后按钮转"已提交"。
4. 拿改过答案的参数直接打接口：`409`，说明写的是"已经按第一次的作答更新了掌握度与错题记录，重放会给出矛盾的对错"。原参数重打：`200`，返回第一次的 `submitted_at`，没有重新判分。
5. 学情：该考点 `practice_count=1`、`correct_count=1`、`mastery_score=0.667`，与页面上的"答对"一致。

页面布局在桌面宽度下检查；手机布局沿用既有交付时的检查，本轮没有重测。

## 尚未实测

- **真实 DeepSeek Key 的线上调用**：只验过接口适配、结构化回复校验、失败降级、引用越界拒绝和 Key 不回显。账号侧的连通、错误 Key 报错、刷新后 Key 清空而学习记录仍在，都需要你本人的 Key。
- 引用校验只保证引用 ID 属于本次证据，不代表每句解释都被来源支撑。
- CET 逐节收卡与强制听力播放、面试麦克风录入、公网账户／多租户与限流。

## 知识库门禁

结构门禁与状态词表检查的重跑结果记在 [教资完整性与网页端交付报告](教资完整性与网页端交付报告.md)；严格审查仍有内容缺口时退出码为 `1`，结构错误和内容缺口要分开看。
