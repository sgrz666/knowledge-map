# 网页端验收记录

2026-10-11。分三档写明：完整自动化覆盖、真实浏览器实测、尚未实测。没跑过的不写成跑过。

## 自动化

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

已提交树（`f0ff2dd7`）：`424 项通过、55 个子测试通过`（实测 211.69 秒）。跑测试要先把状态目录指向临时处（`$env:KNOWLEDGE_MAP_STATE_DIR = <空目录>`），否则网页用例会把练习卷和提交写进本机 `.local_state/`。

错因与掌握度这一收口（+4 条用例）：**427 项通过、55 个子测试通过、1 项失败**，实测 209.33 秒。那条失败是 `tests/test_ntce_hierarchy_contract.py::test_learning_resources_layer_seven_compliance_and_graph_connectivity`——工作区里并行写的一批新资源 `数据集/教资/resources/study_guides.jsonl` 用 `guide_id` 当键，七层资源契约要的是 `resource_id`，用例在第 187 行 `assertTrue(rid)` 就停了；同一个文件还会让 `kb_tools/build_graph.py` 在 `res['resource_id']` 处 KeyError。它由数据文件触发，与本次改的 `services/memory/**` 无关。这批资源后来按教研决定升格为 L7 并入图，见下面"无题考点学习指南并入 L7"一节。

计数只能在主工作区取：另开一个只含已提交内容的 detached worktree 跑同一套代码，会多出 14 项失败与 22 项错误，全是 `数据集/**/_staging/*.docx` 这类**未入库的原始卷面文件**不在场导致的 `FileNotFoundError`，不是代码问题。

L7 升格这一轮的计数（**447 项通过、63 个子测试通过、7 项失败**，实测 194.96 秒，退出码 `1`）取的是**工作区树**，不是已提交树：并行会话的网页学习闭环改动（`services/web/**`、`services/learning/**`、`services/exam_sessions/**`、`web/**` 与四个新测试文件）也在同一目录里未入库，用例总数因此从 428 涨到 454。7 项失败没有一项由这一轮的数据改动产生，分两类：

- 5 项在 `tests/test_learning_workflow.py`，报错都是同一句 `AttributeError: 'Workbench' object has no attribute 'exam_sessions'`。该文件的 fixture 用 `Workbench.__new__(Workbench)` 跳过构造函数、再手挑依赖字段，而同一批未入库改动已在 `services/web/service.py:124` 的提交路径上加了 `self.exam_sessions.guard_submission(...)`； fixture 少赋一个字段就整组报红。两边都还在工作区，不属于本仓库已提交内容，本会话不碰。
- 2 项在 `tests/test_learning_resources.py`，断言 7 个无题叶子考点都有指南、共 14 道自测题，实际只有 3 条 6 题——就是交付清单第 4 项的内容缺口（下面覆盖表里 `tests/test_learning_resources.py` 那一行列清了缺的是哪 4 个考点），报红是有意的缺口标记，不是回归坏了。

上一轮那两项与本会话相关的红都已转绿：`test_learning_resources_layer_seven_compliance_and_graph_connectivity`（`guide_id` 换成带完整 L7 信封的 `resource_id`）、`test_the_review_queue_is_generated_not_transcribed`（重跑生成脚本，不是手改数字）。两处细节见下面"无题考点学习指南并入 L7（2026-10-11，教研决定）"一节。

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

## 无题考点学习指南并入 L7（2026-10-11，教研决定）

这批草稿原先放在 `数据集/教资/resources/study_guides.jsonl`，用 `guide_id` 当键，既不过七层资源契约，也会让图谱导出脚本在 `res['resource_id']` 处 KeyError。按"升格为 L7 资源并入图"的决定，每行前面加了 L7 外壳：`resource_id`（`ntce.res.guide.<学段>_<科目>_<节>_<考点>`，由 `node_id` 派生）、`type = study_guide`、`title`、`exam`、`summary`（取概念讲解第一段）、`copyright`（`authorization_status = unknown`、`use_scope = research_non_commercial`、`source_nature` 沿用行内 `content_status`，不新造词表外的值）、`knowledge_node_ids` / `ability_ids` / `exam_requirement_ids` 三个挂接字段。原来的 `guide_id` 折进 `resource_id`，**唯一丢掉的信息是它尾部的 `.v1` 版本号**——行内没有第二个字段记版本。

三条记录：`ntce.res.guide.chuzhong_lishi_s3_k01`（条款 310.r007／r009）、`ntce.res.guide.chuzhong_shengwu_s3_k01`（308.r009–r012）、`ntce.res.guide.chuzhong_tiyu_s3_k04`（313.r019／r027）。`ability_ids` 留空——草稿只核到考点与条款，没有逐项判定能力归属，所以不产生 `supports_resource` 边。

入图不手改 `graph/*.jsonl`，走唯一出口 `python kb_tools/build_graph.py`：L7 由 8 个变 11 个，节点 22,104 → 22,107，边 96,774 → 96,785（+3 个 `supplements_resource`、+8 个 `aligned_to_requirement`，方向照旧"支撑方 → 被支撑方"），`MANIFEST.json` 同步。图谱只是登记挂接关系，**没有把任何审核状态往上抬**：三条仍 `review.status = needs_fix`、`checked_by = null`、`formal_question_pool_eligible = false`，自测题仍是 `research_draft`、不带 `question_id` 与分值，具名签核数为 0。

覆盖与边界：

| 检查 | 结果 |
| --- | --- |
| 七层资源契约（`test_ntce_hierarchy_contract.py`） | 原先那条红用例转绿；连同方向契约、状态词表共 20 项 + 14 子测试通过 |
| 严格审查 `validate_kb.py` | `structure_errors` 仍 0，`remaining_gaps` 仍 130,762，逐规则计数不变——它的资源规则只扫四六级官方样卷，教资 `resources/*.jsonl` 不在分母内，指南的形状与引用由七层契约和这批文件自带的用例钉住 |
| 状态词表 `数据集/教资` | 15,185 条 0 违规。比已提交树的 15,182 多 3 条，是这 3 行指南记录本身进了扫描分母（与本次换键无关）；换键后才通过的是七层资源契约，不是词表 |
| `tests/test_learning_resources.py` | 仍有 2 项失败：7 个无题叶子考点只整理了 3 份讲解，缺初中物理、初中信息技术、高中物理、高中音乐。属交付清单第 4 项的内容缺口，不是本次并入造成的回归；`learning_resources.py` 门面只按 `node_id` 读行，不认 `guide_id`，所以换键没动调用方（这份门面与它的用例、以及 `services/web/knowledge.py` 都还是并行会话在工作区里未入库的改动，本仓库提交树内暂无这些文件，本节只是登记已核对过的读法） |
| 复核队列复现 `test_the_review_queue_is_generated_not_transcribed` | 并入后先红了一次：`审查/待复核清单.md` §2 写"被 `aligned_to_requirement` 引用的有 548 条、未引用 5,707 条"，生成器按新图重算出 551／5,704（`ntce.*` 那一档 740 → 737）。差的正是这 3 条指南新引到的 3 个条款——清单是生成物不是手写台账，所以按唯一出口 `python 审查/build_review_queue.py` 重跑落盘，用例转绿，没有手改那两行数字 |
| 完整性快照 `审查/教资完整性核对.json` | 同一批重跑把 `L7` 从 8 改成 11、`graph_edges` 从 96,774 改成 96,785，其余计数逐字不变；这份 JSON 也只写库内容的函数值，不含钟点 |

条款前缀交叉核对（发现一处不一致，留给教研，不改生成物）：`docs/教资无题考点学习索引.md` 把初中历史 `ntce.chuzhong.lishi.s3.k01` 自动对齐到 `ntce.outline.316.r007`，而 316 的科目是**历史与社会学科知识及教学能力**；指南草稿引的 `ntce.outline.310.r007／r009` 科目才是**历史学科知识与教学能力（初级中学）**，与这条考点所在的学科一致，内容也确实写着"分析学生的学习需求""对历史教材的内容进行梳理和分析"。两边都是未核定的对齐线索，谁也没被签核，所以这里只登记不改：入图用指南自陈的 310，索引里那条 316 保持原样等命题核定，`aligned_to_requirement` 边只说明挂在哪，不代表挂对了。

网页知识浏览器（`services/web/knowledge.py`，同样是并行会话在工作区未入库的改动，下面的读法来自当场翻代码，不是提交树里能复现的事实）走的是 `LearningResources().list_guides()` 直读文件，不经图谱，因此这步并入只改变"能不能在图里查到这份资源、它挂在哪个考点"，不改变页面能展示的字段。

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
| `python 审查/状态词表检查.py 数据集/教资` | 扫描 15,185 条，违规 0，退出码 0（比升格前多 3 条，正是并入 L7 的 3 份学习指南） |
| `python 审查/状态词表检查.py 数据集/四六级` | 扫描 31,991 条，违规 0，退出码 0 |
| `python 审查/audit_ntce_completeness.py` | 退出码 0；791 知识点／160 无题／7 无题叶子，32 份卷面规格，6 份量规未签署，八层 L0–L7 = 2320／7／38／51／791／586／18303／11 |
| `python 审查/validate_kb.py --output .local_state/web_audit_final.json` | 退出码 1：`structure_errors=0`、`remaining_gaps=130762`、`complete=false` |

退出码 1 只表示严格审查仍有内容缺口，与结构错误无关；130,762 是多维待补／待核定记录数，可在同一题重叠，不是缺同数量的题。逐条数字见 [教资完整性与网页端交付报告](教资完整性与网页端交付报告.md)。

完整性快照落盘只写库内容的函数值，不写钟点（`tests/test_completeness_audit.py` 断言重跑逐字相同、且仓库里那份能由库复现）。之前它带一个 `generated_at`，每批修补后重跑都会把文件改脏，`git diff` 就分不清是补掉了缺口还是只是过了几分钟。

## 答案冲突首批核对之后（2026-10-11，`xiaoxue/jiaoyuxinlixue`）

这一轮**动了数据**，上面各处记录的 13,269 可练、1,040 冲突、`remaining_gaps = 130,762` 是核对前那棵树的数，实况以本节为准。

34 题隔离里 22 题回原卷核对成立并落回，12 题核对不出来仍留隔离（题干定位不到 4、两份抽取不一致 6、非四选项单选 2）。逐题的题号、修改前后内容、原卷文件与卷内题号、隔离时保全的候选、审核状态都在 `数据集/教资/review/answer_conflict_reconciliation.jsonl`。

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q`（主工作区工作树） | `455 项通过、63 个子测试通过、7 项失败`，实测 118.94 秒，退出码 `1` |
| `python 审查/audit_ntce_completeness.py` | 14,500 题里 **13,291** 可练（+22），来源冲突 **1,018**（−22），缺答案仍 149，具名签核 0 |
| `python 审查/状态词表检查.py 数据集/教资` | 15,185 条 0 违规，退出码 0 |
| `python 审查/状态词表检查.py 数据集/四六级` | 31,991 条 0 违规，退出码 0 |
| `python 审查/validate_kb.py --output .local_state/web_audit_final.json` | 退出码 `1`：`structure_errors = 0`、`remaining_gaps = 130,738`、`complete = false` |
| `python -m pytest tests/test_ntce_conflict_reconcile.py tests/test_status_vocabulary.py -q` | 15 passed，12 subtests passed，退出码 0 |

严格审查的教资分项：`Q_ANSWER_MISSING` 4,509 → **4,487**，`Q_ANSWER_SOURCE_CONFLICT` 1,040 → **1,018**，`Q_ANSWER_BINDING_PENDING` 2,176 → **2,196**，`Q_STEM_EMPTY` 369 与 `Q_ANALYSIS_INCOMPLETE` 4,829 **不变**。`+20` 那一条不是新缺陷：同一批题从"没有答案"改记为"答案已回卷落回、待原卷绑定核验"（其中 2 题原本就带绑定证据）。少的 24 条全库缺口 = −22 缺答案 − 22 冲突 + 20 待绑定，与 130,762 → 130,738 逐条对得上。**验收达成的是该批内容缺口下降且 `structure_errors` 保持 0。**

7 项失败没有一项由这批数据改动产生，全部在并行会话未入库的那条线上：5 项 `tests/test_learning_workflow.py`（都是 `AttributeError: 'Workbench' object has no attribute 'exam_sessions'`，`services/web/service.py:124` 的提交路径已引用该字段而那批用例的 fixture 没赋）、2 项 `tests/test_learning_resources.py`（断言 7 个无题叶子考点都有讲解与 14 道自测题，实际 3 份 6 题——即交付清单第 4 项按你的决定只写 3 份、另 4 份不编写，报红是有意的缺口标记）。本会话不碰这两组文件，也不把它们的红算成自己的绿。

这一批真正修出来的架构缺陷是**卡片与题记录脱节**：上一轮只重跑了图谱、快照与队列，没重渲染卡片，卡片头部仍写隔离、正文仍断言"本题无给定答案"，学习者读到的是自相矛盾的一张卡。现在落回连带走 `sync_cards` 重渲染（本批 22 张），并由 `test_restored_card_mirrors_the_record_and_stops_denying_the_answer` 钉住；解析草稿只重算受答案影响的三段、仍记 `rule_draft_pending_expert`，由 `test_restored_rule_analysis_follows_the_answer_without_claiming_verification` 钉住。核对工具的摘要另外补了 `restored_in_dataset` / `still_quarantined` 两个字段：默认运行只出证据（`applied = false`、`cards_rewritten_this_run = 0`），没有这两个字段的话，测试里那次只读重跑会把摘要写成"这批一题都没落回"——证据文件自述数据实况，不只自述当次模式。

## 隔离题的题面串题定位到字段（2026-10-11，同批，未动数据）

上一节的 12 道拒绝题只带一个 `cross_question_risk` 风险码，读的人无法判断下一步：题面里吞了整段邻题，究竟是**剪掉重复文本**还是**这段根本没被收录**。这一轮把定位落到证据上，改动只在工具与证据，题库数据一行没动。

`kb_tools/ntce_repair.py` 新增 `mix_risk_evidence(q)`，一份口径同时给修复轮与核对工具读（`sequence_fields` / `sequence_counts` / `combined_sequences` / `embedded_numbers`）；核对工具删掉自己那份正则，改为对每条带串题风险的拒绝题附 `content_boundary`，并用本卷已入库的题号集合算出 `embedded_numbers_without_record`。摘要加 `refused_with_open_question_boundary = 7`、`boundary_numbers_without_record = 2`。

实测结论：该批 7 道题面带串题证据，最重的 `na-p1-jx.q02` 的 E 选项里有 19 道完整 A-D 序列，`na-p1-jx.q04` 的 D 有 7 道；`na-p1-jx` 题面的 77、`na-p2-jx` 题面的 74 在本卷没有任何独立记录，而这几份散卷总共只入库 4～5 条记录。所以**这些文本不能剪**——剪掉等于删掉库里唯一一份邻题内容；该批的题面缺陷登记为收录缺口，下一轮照原件补收录。编号识别是下限不是穷举，识别不出的串题仍由序列计数暴露。

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q`（主工作区工作树） | `457 项通过、63 个子测试通过、7 项失败`，实测 204.59 秒，退出码 `1`。通过数比上一节的 455 多 2，正是本轮新增的两条用例；失败的 7 项与上一节**逐条同名**（5 项 `test_learning_workflow.py`、2 项 `test_learning_resources.py`），仍在并行会话那条线上，不由本轮改动产生 |
| `python -m pytest tests/test_ntce_conflict_reconcile.py tests/test_ntce_repair.py tests/test_kb_contract.py tests/test_status_vocabulary.py tests/test_web_workbench.py -q` | 129 passed，16 subtests passed，退出码 0 |
| `python 审查/状态词表检查.py 数据集/教资` | 15,185 条 0 违规，退出码 0 |
| `python 审查/状态词表检查.py 数据集/四六级` | 31,991 条 0 违规，退出码 0 |
| `python 审查/audit_ntce_completeness.py` | 退出码 0，来源冲突仍为 **1,018**、缺答案仍 149（这一轮不落回任何答案） |
| `python 审查/validate_kb.py --output .local_state/web_audit_final.json` | 退出码 `1`：`structure_errors = 0`、`remaining_gaps = 130,738`，与上一节逐项相同——数据未动，只有两份证据文件重生成 |

`refused_with_open_question_boundary`（7）比拒绝原因 `cross_question_risk_open`（6）多 1：`na-p1-jx.q02` 先因五选项多选被拒，串题证据照样登记。这两个数不该相等，摘要把它们分成两个字段而不是合并成一个"串题题数"。

