# 网页端验收记录

2026-10-11。分三档写明：完整自动化覆盖、真实浏览器实测、尚未实测。没跑过的不写成跑过。

## 自动化

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

已提交树（`f0ff2dd7`）：`424 项通过、55 个子测试通过`（实测 211.69 秒）。跑测试要先把状态目录指向临时处（`$env:KNOWLEDGE_MAP_STATE_DIR = <空目录>`），否则网页用例会把练习卷和提交写进本机 `.local_state/`。

错因与掌握度这一收口（+4 条用例，共 428 项）：**427 项通过、55 个子测试通过、1 项失败**，实测 209.33 秒。那条失败是 `tests/test_ntce_hierarchy_contract.py::test_learning_resources_layer_seven_compliance_and_graph_connectivity`——工作区里并行写的一批新资源 `数据集/教资/resources/study_guides.jsonl` 用 `guide_id` 当键，七层资源契约要的是 `resource_id`，用例在第 187 行 `assertTrue(rid)` 就停了。它由数据文件触发，与本次改的 `services/memory/**` 无关，改谁的文件归那一批的作者定。

计数只能在主工作区取：另开一个只含已提交内容的 detached worktree 跑同一套代码，会多出 14 项失败与 22 项错误，全是 `数据集/**/_staging/*.docx` 这类**未入库的原始卷面文件**不在场导致的 `FileNotFoundError`，不是代码问题。

## 知识库门禁复跑

同一批改动之后重跑交付清单里的四条命令（`python 审查/audit_ntce_completeness.py`、`python 审查/状态词表检查.py 数据集/教资`、`… 数据集/四六级`、`python 审查/validate_kb.py --output .local_state/web_audit_final.json`）：

| 门禁 | 结果 |
| --- | --- |
| 教资完整性审查 | 退出码 `0`；14,500 题里 13,269 可练，缺知识点／能力挂载 1,331、缺考纲绑定 3,928、答案来源冲突 1,040、缺答案 149、空题干 45；791 个考点中 160 个没有直接考查题，其中 7 个是叶子；待签署量规 6 |
| 状态词表 | 教资 15,185 条 0 违规、四六级 31,991 条 0 违规，两条退出码都是 `0` |
| 严格审查 | 退出码 `1`，`structure_errors = 0`，`remaining_gaps = 130,762`，`complete = false` |

按口径分开看：结构错误为 0 说的是库的**形状**没问题；退出码 `1` 说的是**内容**还等教研补，两者不能混成"检查失败"。这批数字与交付快照一致——本轮改动只碰 `services/memory/**` 与测试／文档，一条数据也没动。

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

## 掌握度与错因只读学习者的证据

收据关住的是"同一次作答不能被改"，这一节关住的是"画像里的数是从哪儿来的"。调用方可以申报题目难度和当前掌握度（`services/common/models.py` 里各给默认 0.5），旧实现把这两个申报值读进了判定：

| 位置 | 旧写法 | 现在 |
| --- | --- | --- |
| 掌握度公式 | `(0.7*正确率 + 0.3*(1 - 申报难度*0.4)) * R`，而 `R` 恒为 1.0 | 只按该考点累计正确率做拉普拉斯平滑 `(correct+1)/(practice+2)`；`R` 按这次作答距上次复习的真实天数对 `stability` 算 |
| 审题疏漏 | 还要申报难度 < 0.75，同样 4 秒交卷报 0.8 就判不成 | 只看学习者自己的耗时与题干否定词 |
| 认知盲区 | 无记录时退回申报的 `current_node_mastery`，说明里给出一个从未存在过的历史百分比 | 只在这位学习者该考点的持久化记录 < 0.35 时成立；`persisted_mastery` 为必填 keyword-only，无记录时在 `notices` 明说"还没有你的作答记录" |
| 事件指纹 | — | 这两个申报字段**照旧计入**指纹：指纹钉的是"这次提交了什么"，摘掉它们会让指纹上线前写下的收据全部对不上 |

覆盖：`TestAttributionEvidenceSource`（申报难度挪不动判定、盲区要么用持久化记录要么不成立、无记录时那句说明真的出现），静态面 `TestA10ProfileVerdictSource.test_no_inference_path_reads_a_claimed_difficulty_or_mastery` 用 AST 扫 `services/**`，读出这两个属性即失败，只有 `services/memory/receipt.py` 在册。

## 真实浏览器实测

后端空 Key（规则模式）、`http://127.0.0.1:8001`、学习者 `retry-verify`、每日一练两份题。

1. 生成练习卷 → 第一题作答后让响应在半路丢掉（服务端已写入，页面拿不到结果）：页面提示失败、作答项锁定、按钮转为"重试提交（沿用上次作答参数）"，`localStorage` 存下原始请求参数（答案 `A`、耗时 6.145 秒、翻转 0）。
2. 刷新：练习卷按学习者／考试／学段／科目／档位恢复，提交行已在库里，直接显示"已提交"，待完成参数清掉。
3. 第二题在请求发出前失败（什么都没存下）：待完成参数落 `localStorage`；重试发出的仍是原参数，耗时没有被重新计算（46.877 秒逐字一致），成功后按钮转"已提交"。
4. 拿改过答案的参数直接打接口：`409`，说明写的是"已经按第一次的作答更新了掌握度与错题记录，重放会给出矛盾的对错"。原参数重打：`200`，返回第一次的 `submitted_at`，没有重新判分。
5. 学情：该考点 `practice_count=1`、`correct_count=1`、`mastery_score=0.667`，与页面上的"答对"一致。

## 手机宽度实测

同上后端，独立状态目录，`http://127.0.0.1:8003/`，学习者 `local-learner`。视口用同源 390×844 的 iframe 造出来（`window.open` 弹窗被拦，新窗口宽度不可信），浏览器实际可用宽 386 像素。

| 检查 | 结果 |
| --- | --- |
| 七个分区能不能到 | 导航是 `flex-wrap:nowrap` 加横向滚动，内容宽 508 对可见宽 331；滑到底 `scrollLeft` 到 177，最后一项"⚙模型与设置"完整入视 |
| 页面横向溢出 | `documentElement.scrollWidth == clientWidth`，六档视图（练习／学情／审查／设置等）都没有 |
| 每日一练组卷 | 5 张题卡，卡片左右边 22／349、宽 327，选项行高 42–63 像素，全部在视口内可点 |
| 作答与提交 | 选 A 提交后判"答对"，按钮转"已提交／给我一点提示／向助手追问／反馈内容问题"，`localStorage` 里 `pending-submit:*` 清成 0 条 |
| 学情与复习 | 无溢出，画像与错题列表正常渲染 |
| 知识库审查 | 审查表列数多，横向滚动关在 `.table-wrap` 容器里，页面本体不跟着滚 |

只验了布局与点得动，没有在同一轮里重跑桌面宽度那五步重试链路；手机宽度下的"响应半路丢掉→刷新恢复"沿用桌面结论（参数存 `localStorage`，与视口无关），未单独立刻重测。

## 尚未实测

- **真实 DeepSeek Key 的线上调用**：只验过接口适配、结构化回复校验、失败降级、引用越界拒绝和 Key 不回显。账号侧的连通、错误 Key 报错、刷新后 Key 清空而学习记录仍在，都需要你本人的 Key。
- 引用校验只保证引用 ID 属于本次证据，不代表每句解释都被来源支撑。
- CET 逐节收卡与强制听力播放、面试麦克风录入、公网账户／多租户与限流。

## 知识库门禁

2026-10-11 在提交后的树上重跑，逐条记录：

| 命令 | 结果 |
| --- | --- |
| `python 审查/状态词表检查.py 数据集/教资` | 扫描 15,182 条，违规 0，退出码 0 |
| `python 审查/状态词表检查.py 数据集/四六级` | 扫描 31,991 条，违规 0，退出码 0 |
| `python 审查/audit_ntce_completeness.py` | 退出码 0；791 知识点／160 无题／7 无题叶子，32 份卷面规格，6 份量规未签署，八层 L0–L7 = 2320／7／38／51／791／586／18303／8 |
| `python 审查/validate_kb.py --output .local_state/web_audit_final.json` | 退出码 1：`structure_errors=0`、`remaining_gaps=130762`、`complete=false` |

退出码 1 只表示严格审查仍有内容缺口，与结构错误无关；130,762 是多维待补／待核定记录数，可在同一题重叠，不是缺同数量的题。逐条数字见 [教资完整性与网页端交付报告](教资完整性与网页端交付报告.md)。

完整性快照落盘只写库内容的函数值，不写钟点（`tests/test_completeness_audit.py` 断言重跑逐字相同、且仓库里那份能由库复现）。之前它带一个 `generated_at`，每批修补后重跑都会把文件改脏，`git diff` 就分不清是补掉了缺口还是只是过了几分钟。

