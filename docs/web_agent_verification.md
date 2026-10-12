# 网页端验收记录

2026-10-12。分三档写明：完整自动化覆盖、真实浏览器实测、尚未实测。没跑过的不写成跑过。**下面"当前实况"这一节是此刻库与代码的真实状态**；再往下按验收面分开（提交重试、掌握度取证、资源并入、agent 流程四项、浏览器、手机宽度、尚未实测），最后是答案冲突的逐批历史与逐轮清点，历史里保留的每一轮计数只作对照，实况以顶部为准。

## 当前实况（agent 流程四项收口之后全量复跑）

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q`（主工作区工作树，状态目录指向空临时处，整档单独跑、不与其它 pytest 运行重叠） | `2 项失败、492 项通过、63 个子测试通过`，实测 185.53 秒，退出码 `1`。红的两项仍是有意的内容缺口标记：`test_seven_target_nodes_have_substantive_guides_and_fourteen_self_checks` 与 `test_loader_filters_returns_detached_json_and_rereads_changes`（后者红在最后一步 `len(list_guides()) == 7`，它自己的过滤断言是过的），断言 7 个无题叶子考点都有讲解、共 14 道自测题，实际 3 份 6 题——交付清单第 4 项按教研决定留下的缺口，不是回归坏了。本轮为 agent 流程新增的用例全在 `tests/test_web_workbench.py`（该文件现在 30 条，单跑 30 项全绿、39.68 秒）：思考过程六支都产出且步骤集合固定、五条岔路逐条出 trace、批次轮换并避开上一批、越界载荷降级而不 500、同一句话不重复排课、考点真题附题面但不泄答案、没答过的题只给引导不给答案、模块级考点扩到下级考点、卷面回传考点、整句包裹仍锚得到考点、带考点的载荷不被面试关键词抢走、状态冲突与隔离题都带前端能用的错误码。上一档那 5 项 `tests/test_learning_workflow.py` 的红仍然没回来：该 fixture 现在走真实构造函数（`tests/test_learning_workflow.py:23` 那行注释记着这件事），"新增依赖漏赋字段"不再靠两边碰巧同步来避免 |
| `python 审查/audit_ntce_completeness.py` | 本轮复跑，退出码 `0`；数字与上一档逐项一致（库内容这轮没动）：14,500 题里 **13,464** 可练，缺知识点／能力挂载 1,331、缺考纲绑定 3,928、来源冲突 **845**、缺答案 149、空题干 45；791 个考点中 160 个没有直接考查题、其中 **7** 个是叶子；32 份卷面规格、6 份量规未签署、具名签核 0；八层 L0–L7 = 2,320／7／38／51／791／586／18,303／11，图边 96,785 |
| `python 审查/状态词表检查.py 数据集/教资` | 本轮复跑：15,185 条 0 违规，退出码 `0` |
| `python 审查/状态词表检查.py 数据集/四六级` | 本轮复跑：31,991 条 0 违规，退出码 `0` |
| `python 审查/validate_kb.py --output .local_state/web_audit_final.json` | 本轮复跑，退出码实测 `1`：`structure_errors = 0`、`remaining_gaps = 130,555`、`complete = false` |

退出码 `1` 只说明严格审查仍有**内容**缺口，与结构错误无关：`structure_errors = 0` 说的是库的**形状**没问题，`remaining_gaps` 说的是内容还等教研补，两者不能混成"检查失败"。130,555 是多维待补／待核定记录数，可在同一题重叠，**不是缺同样多的题**。教资分项要从 `issues[].dataset`（值是 `ntce`）现算才能分出来（表格里的合计含四六级，且必须按 `== 'ntce'` 而不是 `!= 'cet'` 筛，第三种值是 `cet_official_examples`）：`Q_ANSWER_MISSING` 4,314、`Q_ANSWER_BINDING_PENDING` 2,362、`Q_ANALYSIS_INCOMPLETE` 4,826、`Q_STEM_EMPTY` 369、`Q_ANSWER_SOURCE_CONFLICT` 845、`Q_KNOWLEDGE_MISSING` 1,331、`Q_REQUIREMENT_MISSING` 3,928、`KN_REQUIREMENT_MISSING` 201、`GRAPH_PREREQUISITE_PENDING_REVIEW` 31；教资那份合计 68,905 条（四六级 61,090、官方样卷 560）。逐条数字与口径见 [教资完整性与网页端交付报告](教资完整性与网页端交付报告.md)。

两处复跑注意。跑测试要先把状态目录指向临时处（`$env:KNOWLEDGE_MAP_STATE_DIR = <空目录>`），否则网页用例会把练习卷和提交写进本机 `.local_state/`，把真实学习记录当成被测数据。计数只能在主工作区取：另开一个只含已提交内容的 detached worktree 跑同一套代码，会多出 14 项失败与 22 项错误，全是 `数据集/**/_staging/*.docx` 这类**未入库的原始卷面文件**不在场导致的 `FileNotFoundError`，不是代码问题。

完整性快照 `审查/教资完整性核对.json` 落盘只写库内容的函数值、不含钟点（`tests/test_completeness_audit.py` 断言重跑逐字相同、且仓库里那份能由库复现）——之前它带一个 `generated_at`，每批修补后重跑都会把文件改脏，`git diff` 就分不清是补掉了缺口还是只是过了几分钟。同理，`python 审查/audit_ntce_completeness.py` 打印到标准输出的那份**带** `written_at`：钟点只留在人读的输出里，不进仓库，所以重跑命令不会改动工作树。本轮复跑又核了一次：跑前跑后那份快照逐字节没变，四道门禁里只有它和 `validate_kb.py` 落盘（后者只写 `.local_state/`），门禁重跑不构成工作树脏。

## 各轮的全量测试计数（历史，逐轮只增不减）

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

已提交树（`f0ff2dd7`）：`424 项通过、55 个子测试通过`（实测 211.69 秒）。

错因与掌握度那一收口（+4 条用例）：**427 项通过、55 个子测试通过、1 项失败**，实测 209.33 秒。那条失败是 `tests/test_ntce_hierarchy_contract.py::test_learning_resources_layer_seven_compliance_and_graph_connectivity`——工作区里并行写的一批新资源 `数据集/教资/resources/study_guides.jsonl` 用 `guide_id` 当键，七层资源契约要的是 `resource_id`，用例在第 187 行 `assertTrue(rid)` 就停了；同一个文件还会让 `kb_tools/build_graph.py` 在 `res['resource_id']` 处 KeyError。它由数据文件触发，与那次改的 `services/memory/**` 无关。这批资源后来按教研决定升格为 L7 并入图，见下面"无题考点学习指南并入 L7"一节。

L7 升格这一轮的计数（**447 项通过、63 个子测试通过、7 项失败**，实测 194.96 秒，退出码 `1`）取的是**工作区树**，不是已提交树：并行会话的网页学习闭环改动（`services/web/**`、`services/learning/**`、`services/exam_sessions/**`、`web/**` 与四个新测试文件）也在同一目录里未入库，用例总数因此从 428 涨到 454。7 项失败没有一项由这一轮的数据改动产生，分两类：

- 5 项在 `tests/test_learning_workflow.py`，报错都是同一句 `AttributeError: 'Workbench' object has no attribute 'exam_sessions'`。该文件的 fixture 用 `Workbench.__new__(Workbench)` 跳过构造函数、再手挑依赖字段，而同一批未入库改动已在 `services/web/service.py:124` 的提交路径上加了 `self.exam_sessions.guard_submission(...)`； fixture 少赋一个字段就整组报红。两边都还在工作区，不属于本仓库已提交内容，本会话不碰。
- 2 项在 `tests/test_learning_resources.py`，断言 7 个无题叶子考点都有指南、共 14 道自测题，实际只有 3 条 6 题——就是交付清单第 4 项的内容缺口（下面覆盖表里 `tests/test_learning_resources.py` 那一行列清了缺的是哪 4 个考点），报红是有意的缺口标记，不是回归坏了。

上一轮那两项与本会话相关的红都已转绿：`test_learning_resources_layer_seven_compliance_and_graph_connectivity`（`guide_id` 换成带完整 L7 信封的 `resource_id`）、`test_the_review_queue_is_generated_not_transcribed`（重跑生成脚本，不是手改数字）。两处细节见下面"无题考点学习指南并入 L7（2026-10-11，教研决定）"一节。

教资逐批修补那几轮（交付清单第 3 项）的全量计数各记在下面对应批次那一节的门禁表里，这一节不重复那些数。只有第四批那一轮当时没留表：跑的是 **8 项失败、462 项通过**（总计 470），实测 131.33 秒，退出码 `1`，比第三批那一轮多出的那项红是 `tests/test_ntce_conflict_reconcile.py::test_restored_rule_analysis_follows_the_answer_without_claiming_verification`——它当场照出"落回的答案与解析草稿分属两档"，改法记在第四批那节末尾。这几轮长红的 7 项始终是同一组：5 项 `tests/test_learning_workflow.py`（fixture 跳过构造函数漏赋 `exam_sessions`）＋ 2 项 `tests/test_learning_resources.py`（第 4 项的有意缺口标记）。

面试连续会话收口之前先有一轮只修那 5 项 fixture 红：**2 项失败、470 项通过、63 个子测试通过**（总计 472），实测 131.32 秒，退出码 `1`。总数与第五批那一轮同为 472，只是 5 项红转绿、通过数从 465 涨到 470；红的两项仍是有意的缺口标记。

紧接着一轮把面试分阶段会话的用例补齐（`tests/test_interview_session.py` 六条，见上面六面对账那一行）：**2 项失败、476 项通过、63 个子测试通过**（总计 478），实测 181.37 秒，退出码 `1`。多的 6 项就是那六条用例，红的两项不变。

模型选路护栏这一轮把总数推到 479，多的那一项是 `tests/test_web_workbench.py::test_model_guard_checks_the_endpoint_it_will_actually_dial`，红的仍是那两条缺口标记；这一档的完整计数与耗时就写在顶上"当前实况"，不在这里重复一遍。

agent 流程四项这一轮（含同一天第二轮审计照出并修掉的 8 处缺陷，见下面同名一节）新增的用例都在 `tests/test_web_workbench.py`；这一轮的完整计数只写在顶上"当前实况"，这里不重复一遍。

## agent 流程四项（2026-10-12，思考过程／批次轮换／相关真题／流程缺陷）

设计与口径在 `docs/agent_architecture.md`，这里只记本轮实测到的东西。

- **思考过程**：`/api/v1/web/chat` 六条岔路（题目答疑、计划、组卷、学情、编排、概念）都产出 `trace`，每步只写工具算出来的事实——意图怎么判的、在哪个范围取数、召回多少题／门禁拦下多少、考点锚到哪个节点、模型是否参与、最后靠什么定稿；编不出证据的步骤不写。浏览器实测一次概念提问看到 7 步，每步可展开看原始字段；`test_chat_shows_the_route_and_the_gate_it_actually_walked` 钉住步骤集合与 `candidate_count ≥ 证据里的题数`，`test_every_chat_branch_produces_a_trace_that_says_who_answered` 把五条岔路（题目答疑、计划、学情、编排闭环、发布档拒答）逐条走一遍，要求每条都出非空 trace、每步都有人话结论、最后一步说清这一轮是谁答的。
- **批次轮换**：组卷种子是 `学习者|日期|模式|批号`，同条件重放同一批，换一批带上上一批题号去避开。浏览器实测点一次"换一批"，卷面从"第 1 批 · 批次种子 …|0"变成"第 2 批 · …|1"，两道题的题面全部换掉；`test_practice_from_chat_rotates_and_avoids_the_previous_batch` 钉住重放相同、两批不交、避开生效。
- **相关真题**：概念提问按考点装配最多 6 道真题——页面带来的 `node_id` 优先，其次是这句话里锚到的考点，再次是召回题自己挂的考点；只主题面、卷面出处与考点名，答过的题才带答案与解析。HTTP 实测同一考点提问两次：提交前该题没有 `answer` 字段且 `answer_withheld=true`，提交后同一题返回库内答案字母；`test_concept_answer_attaches_node_questions_without_giving_the_answer_away` 钉住这条闸。回复里说考点来自哪儿也分开写：锚不到考点时写"按这批真题所挂的考点"，不冒充学习者问的那个。
- **状态冲突**：409 现在带 `code`（`paper_tier_mismatch`、`figure_unavailable`、`exam_tier_mismatch`、`exam_closed`、`exam_stage_collected`、`exam_media_missing`、`legacy_receipt`、`receipt_conflict`），前端按码把这一题标成"本题已不可提交"并清掉本机待重试参数，不再挂一个永远重投不通的按钮。浏览器实测这一支走的是桩掉的 409——真实切换档位会先重置工作台，构不出"研究档的卷 + 已发布档的提交"这个组合；处理分支与 DOM 是真的：按钮改名并禁用、选项全部禁用、提示指向"换一批"、`pending-submit:` 键清空。错误码本身由 `test_state_conflicts_carry_a_code_the_front_end_can_act_on` 在后端钉住。
- **顺手修的三处**：概念锚定原来只在"整句话是考点名的一部分"时成立，而知识点页"请助手讲解"发的正是"请解释X，并说明作答思路"这种整句，锚定恒空；现在按逗号切开取前段，前段取不到再反过来用考点名量这句话（名字最短 3 字，库里 791 个考点没有 2 字名，不会误捞），`test_concept_anchor_survives_the_sentence_wrapping_the_ui_suggests` 钉住整句与裸词锚到同一批考点。卡片还命中、题索引已无此题时，知识点详情跳过这一张卡而不是整页 500。聊天排计划的 `request_id` 由会话与这句话算出，重复点同一句不再每点一次就新排一份、把在做的计划变成孤儿（`test_chat_plan_is_idempotent_per_utterance`）。

第二轮审计（同一天，改完上面四项之后再照一遍）又照出 8 处学习者真会撞上的缺陷，都已修：

- **答疑把没答过的题的答案说出来**：带 `question_id` 的提问原来一律走 Sparks 三链，而三链的答案可见性只由档位与答案状态决定、不认学习者有没有作答，于是知识点页的"请助手讲解此题"在练习之前就报出参考答案，同一屏的来源栏却写着"这道题你还没作答"。现在没提交过的题走苏格拉底引导（`hint_turn` 固定 1，引导链到第 3 轮自己就报答案），`tool_result` 里连 `explanation_summary` 与 `option_discrimination` 都不出现；提交之后同一问法才给完整讲解与库内答案。`test_chat_about_an_unanswered_question_hints_instead_of_revealing` 两头都钉。
- **考点专练组出空卷**：卷面不回传 `target_node`，前端"换一批"只能退回下拉框的值；而模块级考点名下常常一道题都不直接挂（小学综合素质 `m3`：名下 139 道可练题全在下级考点上，直接挂在 `m3` 上的是 0 道），精确匹配取不到题。现在 `practice()` 回传 `target_node`，相关真题按 id 前缀扩到下级考点，回复报的考点名一律取题目真挂着的那些，锚到的考点名下没有直接考查题时如实说明取自下级考点。浏览器实测：从"相关真题"点"按这个考点组一张练习卷"，出来的是【考点专练】`ntce.xiaoxue.zonghe.m3.k04` 5 题，点"换一批"到第 2 批（种子 `…|point_focus|1`）五道题全换、考点不变。`test_module_level_anchor_expands_to_the_nodes_that_carry_questions` 与 `test_practice_response_carries_the_node_the_paper_was_built_for` 钉住。
- **`receipt_conflict` 漏在前端的死路码集合外**：它自己的文案就写着只有重新组卷才是出路，前端却一直挂"重试提交（沿用上次作答参数）"，参数还是冻住的那一份，重投必然同样被拒。已补进 `DEAD_END_CODES`；`self.question()` 那条 409 也从裸字符串换成 `{code: question_not_servable}`——裸字符串前端拿不到码，只能按可重试处理（`test_quarantined_question_is_a_coded_conflict_not_a_bare_string`）。
- **面试关键词抢走考点问答**：库内真有叫"教学设计"的考点（初中各科 `s3`），知识点页那句"请解释教学设计…"会被面试关键词判成 `interview_practice`，又因为载荷非空直接进面试状态机。现在载荷带考点且没显式声明 intent 时按考点问答处理，思考过程里写明"不进 interview_practice 那条闭环"；前端也显式带上 `intent:'general_chat'`（`test_node_payload_with_an_interview_keyword_still_answers_the_concept`）。
- **三处前端状态问题**：`busy()` 不可重入，"换一批"连点会嵌套两次组卷，后完成的那次把按钮文字恢复成"正在处理…"，留下一个永久卡住还 enabled 的按钮（现在按钮已禁用就直接返回）；`loadProfile` 与 `init()` 取最近练习卷那两处没有范围守卫，切学习者／科目时在飞的请求会把上一个范围的学情渲染到新范围下（现在都比对 `scopeIdentity()`）；`show('practice')` 不接回服务端计时的模考，切走再切回来那场考试就再也看不见、只能等它自己超时（现在进这一页且屏上没有卷面时会调 `restoreExam()`；接回的这一趟里学习者若已经组出新卷——错题重做、继续摸底、换一批——就让新卷留在屏上，不被旧模考盖掉）。
- **知识点详情的幽灵卡与一处失实标签**：卡片命中但题索引已无此题时，注释写着跳过、代码却照样出一张空题干卡，点"请助手讲解此题"必然 404，现在真的跳过；模考那个下拉标签原来一律写"分阶段模考"，而逐节收卡只存在于四六级规格，现在教资显示"整卷计时模考 · 服务端计时"。

浏览器实测这一批（`http://127.0.0.1:8113/`，状态目录指向空临时处）：切"学情与复习／练习与模考／知识点学习"三页无 JS 报错、无未处理拒绝，学情页正常出读数，考点树 23 行；概念提问的"思考过程"7 步齐全、"相关真题"6 行每行都带"按这个考点组一张练习卷"；从相关真题组卷再换一批如上。未实测的那一支仍记在下面"尚未实测"里。

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
| 严格审查 `validate_kb.py` | `structure_errors` 仍 0，`remaining_gaps` 仍是当时的 130,762，逐规则计数不变——它的资源规则只扫四六级官方样卷，教资 `resources/*.jsonl` 不在分母内，指南的形状与引用由七层契约和这批文件自带的用例钉住 |
| 状态词表 `数据集/教资` | 15,185 条 0 违规。比已提交树的 15,182 多 3 条，是这 3 行指南记录本身进了扫描分母（与本次换键无关）；换键后才通过的是七层资源契约，不是词表 |
| `tests/test_learning_resources.py` | 仍有 2 项失败：7 个无题叶子考点只整理了 3 份讲解，缺初中物理、初中信息技术、高中物理、高中音乐。属交付清单第 4 项的内容缺口，不是本次并入造成的回归；`learning_resources.py` 门面只按 `node_id` 读行，不认 `guide_id`，所以换键没动调用方（这份门面与它的用例、以及 `services/web/knowledge.py` 都还是并行会话在工作区里未入库的改动，本仓库提交树内暂无这些文件，本节只是登记已核对过的读法） |
| 复核队列复现 `test_the_review_queue_is_generated_not_transcribed` | 并入后先红了一次：`审查/待复核清单.md` §2 写"被 `aligned_to_requirement` 引用的有 548 条、未引用 5,707 条"，生成器按新图重算出 551／5,704（`ntce.*` 那一档 740 → 737）。差的正是这 3 条指南新引到的 3 个条款——清单是生成物不是手写台账，所以按唯一出口 `python 审查/build_review_queue.py` 重跑落盘，用例转绿，没有手改那两行数字 |
| 完整性快照 `审查/教资完整性核对.json` | 同一批重跑把 `L7` 从 8 改成 11、`graph_edges` 从 96,774 改成 96,785，其余计数逐字不变；这份 JSON 也只写库内容的函数值，不含钟点 |

条款前缀交叉核对（发现一处不一致，留给教研，不改生成物）：`docs/教资无题考点学习索引.md` 把初中历史 `ntce.chuzhong.lishi.s3.k01` 自动对齐到 `ntce.outline.316.r007`，而 316 的科目是**历史与社会学科知识及教学能力**；指南草稿引的 `ntce.outline.310.r007／r009` 科目才是**历史学科知识与教学能力（初级中学）**，与这条考点所在的学科一致，内容也确实写着"分析学生的学习需求""对历史教材的内容进行梳理和分析"。两边都是未核定的对齐线索，谁也没被签核，所以这里只登记不改：入图用指南自陈的 310，索引里那条 316 保持原样等命题核定，`aligned_to_requirement` 边只说明挂在哪，不代表挂对了。

网页知识浏览器（`services/web/knowledge.py`，同样是并行会话在工作区未入库的改动，下面的读法来自当场翻代码，不是提交树里能复现的事实）走的是 `LearningResources().list_guides()` 直读文件，不经图谱，因此这步并入只改变"能不能在图里查到这份资源、它挂在哪个考点"，不改变页面能展示的字段。

## Agent 学习闭环六面对账（2026-10-11，面试训练补上连续会话）

交付清单第 5 项列了六面。逐面写清"实现在哪、验收认什么、限制还在不在"，口径与全文一致：自动化那一列是真跑过的用例，浏览器那一列是真点过的路径，限制一列是没做的部分。

| 面 | 自动化用例 | 真实浏览器 | 仍保留的限制 |
| --- | --- | --- | --- |
| 初始摸底 | `tests/test_learning_workflow.py:67`（抽样铺真考点、只读本人提交）、`:211`（并发重试只出一份摸底卷）、`:96`（空范围与发布档不编造学习状态） | 摸底表单 → 抽样卷 → "查看本次摸底结果"给出已提交数、已测／未覆盖考点数与未测说明 | 结束条件仍是"提交数＝抽样数"，不按覆盖度自动收卷；未测考点只报未覆盖，不推测水平 |
| 动态计划 | `:105`（计划按范围恢复、id 逐维隔离）、`:122`（完成要有落库证据且预算不被改短）、`:151`／`:170`（重排真读 memory：新观察到的薄弱考点排在未考点之前）、`:192`（只有绑定那份卷里的提交算完成）、`:224`（current 取最新计划，改参数的创建重试报冲突） | 计划页四步：制定 → 开始任务 → 做完任务卷 → 核对完成并更新计划；剩余任务按新学情重排，已完成那条保留 | 计划只排题与排复习，不同步外部日历 |
| 推荐解释 | `:151`／`:170` 把"为什么是它"钉成可复核的方向：任务要么指向薄弱考点，要么指向到期复习 | 任务行给标题（题型即理由：薄弱考点专项／到期错题／模考冲刺）、分钟数与题量；学情页给"几次作答、几个考点有记录、几道到期"，雷达条给逐模块对错数 | 任务是任务级字段，没有单独的"推荐理由"文本项：理由靠标题与学情读数表达，不是一句为这道题写出来的解释 |
| 知识图谱学习 | `tests/test_knowledge_browser.py:19`（树不编造掌握度）、`:28`（无题叶子有草稿讲解与真来源）、`:39`（四六级保留没有题绑定的节点） | 知识库页搜索 → 点节点 → 考纲依据可展开到条款定位，相关概念标"已启用／待核定"，再"进入考点专练"或"请助手讲解" | 先修边 31 条待核定，页面明写"未用于前置阻断"；审核状态不因被看见而自动提升 |
| 主观题反馈 | `services/grader/evidence.py:107 coverage`（逐点命中／半命中／缺失）与 `:177 dimension_feedback`（只引库内量规维度描述，作答原文经 `:46 quote_answer` 摘引） | 反馈卡逐点带 ✓／△／○ 与覆盖率，维度条摘学生原句，漏项与改进建议分开列 | 6 份量规未签署 ⇒ 一律 `total_score: null` ＋ 明写"不给分数，也不给通过概率"；签署与校准之前不放开正式分数 |
| 面试训练 | `tests/test_interview_session.py` 六条：`:70`（每个任务的题面／框架都可回溯到库内情境资源与真题题面）、`:99`（结构化作答推进到一条有依据的追问）、`:119`（三阶段整场跑完且逐阶段证据在案）、`:148`（同参数重放、改参数在任何写入前 `409`、每个任务槽只写一次）、`:182`（开始重试只发一场会话，用户／学段／科目逐维隔离）、`:194`（发布档与四六级都不编造会话） | 见下面"真实浏览器实测"第 6–10 步：一场完整会话（2 道问答＋2 条追问＋试讲转写＋20 分钟简案）跑到 `completed`，刷新后恢复为已完成 | 语音只按转写文本给实测值（语速、停顿、环节覆盖），麦克风录入没实测；不评价仪态、发音与视频表现 |

一条贯穿六面的口径：学习写入都经 `services/learning/store.py` 的收据回放——同 `request_id` 同参数返回现状、同 `request_id` 改参数在写任何东西之前 `409`；必修项那条判据在面试会话上同样成立，`services/learning/interview.py:90` 的 `answer()` 第一步就是回放。可信门禁没有放宽：`services/learning/interview.py:297 _guard` 对发布档报 `409`、非教资范围报 `404`，`_view`／`_task_view`（`:257`／`:278`）在任务仍是"待作答"时不吐 `reference_framework`、`points`、`missed_points`，作答前拿不到参考框架。

## 真实浏览器实测

后端空 Key（规则模式）、`http://127.0.0.1:8001`、学习者 `retry-verify`、每日一练两份题。

1. 生成练习卷 → 第一题作答后让响应在半路丢掉（服务端已写入，页面拿不到结果）：页面提示失败、作答项锁定、按钮转为"重试提交（沿用上次作答参数）"，`localStorage` 存下原始请求参数（答案 `A`、耗时 6.145 秒、翻转 0）。
2. 刷新：练习卷按学习者／考试／学段／科目／档位恢复，提交行已在库里，直接显示"已提交"，待完成参数清掉。
3. 第二题在请求发出前失败（什么都没存下）：待完成参数落 `localStorage`；重试发出的仍是原参数，耗时没有被重新计算（46.877 秒逐字一致），成功后按钮转"已提交"。
4. 拿改过答案的参数直接打接口：`409`，说明写的是"已经按第一次的作答更新了掌握度与错题记录，重放会给出矛盾的对错"。原参数重打：`200`，返回第一次的 `submitted_at`，没有重新判分。
5. 学情：该考点 `practice_count=1`、`correct_count=1`、`mastery_score=0.667`，与页面上的"答对"一致。

第 6–10 步是另一轮：后端 `services.app:app` 起在 `http://127.0.0.1:8011`、状态目录指向空临时处、学习者 `web-interview-check`、NTCE 小学 · 内部研究档、仍然空 Key。

6. 面试训练跑通一场完整会话：开始会话 → 三阶段四任务（结构化问答 2 道 → 试讲转写 → 20 分钟简案），逐任务作答后 `status=completed`、"已完成 4 / 4 个任务"，会话标题转"本次训练会话已完成"。
7. 作答前后是两套可见内容：待作答的任务卡不出现参考框架与采分点，提交后同一张卡逐点给 ✓／△／○ 与覆盖率，追问只钉在没比对到的那一步并写明"依据：库内…步骤"；试讲那一格粘贴转写文本加 480 秒，反馈只报语速、停顿与环节覆盖的实测值。
8. 整场没有数值分数：全页找不到"得分 X / Y"这种形状，说明线原样写着"本次不出分数：量规未签署，也不给通过概率。"
9. 范围与档位门禁在浏览器里也走了一遍：备考方向切到 CET-4，会话区只剩"面试是教师资格考试的环节，四六级没有面试训练…"，"开始训练会话"按钮 disabled、0 个作答入口；档位切到发布档点开始，页面报错线原样显示后端那句说明（"发布档尚无签署的面试量规与情境资源，训练会话按可信门禁停止；请使用内部研究档。"），切回内部研究档后那场已完成会话还在。
10. 刷新恢复：整页 reload 后进面试页，从服务端取回的还是那场已完成会话（4 / 4、0 个作答表单），`localStorage` 里 `pending-*` 0 条。面试提交这一档走的是第 1–3 步同一条冻结参数路径（`pending-interview-answer:会话:任务:槽` 一个键，成功后清掉），但本轮浏览器里每次提交都一次成功，**没有对面试提交单独注入失败**——那一档注入在自动化侧由 `tests/test_interview_session.py:148` 覆盖，不能算浏览器实测。

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
| 面试会话（恢复已完成那场） | 390×844 的同一 iframe 里实测可用宽 375 像素：会话区渲染 41 个标题、22 个"题面出处与绑定"折叠、约 2.08 万字，最右边缘 353 像素仍在视口内，`scrollWidth == clientWidth`，不横向溢出；作答表单 0 个（已完成任务不给第二次写入口） |

只验了布局与点得动，没有在同一轮里重跑桌面宽度那五步重试链路；手机宽度下的"响应半路丢掉→刷新恢复"沿用桌面结论（参数存 `localStorage`，与视口无关），未单独立刻重测。面试那一档同样只验了宽度与可见性，没有在手机宽度下注入提交失败。

## 模型连通性：护栏在这台机器上把真实请求挡掉了（2026-10-12）

学习者填 Key 后点"测试连接"，页面报"模型域名解析到非公网地址，无法连接"。这不是 Key 的问题，也不是配置的问题，是 `services/web/provider.py` 那条 SSRF 护栏的误拒。

本机实测的两条证据：`api.deepseek.com` 解析出 `198.18.0.253`（A）和 `2001:2::104`（AAAA），两个都不是公网地址；同时终端环境里有 `HTTP_PROXY／HTTPS_PROXY／ALL_PROXY = http://127.0.0.1:17899`、`NO_PROXY = localhost,127.0.0.1,::1`。`198.18.0.0/15` 是 RFC 2544 的基准测试段，正是代理客户端 fake-ip 模式发占位地址用的池子。关键在于：**有系统代理时 urllib 连的是代理本身**（对 https 发 `CONNECT api.deepseek.com:443`），那个 fake-ip 从头到尾没被拨号，护栏校验的是一个不参与建连的地址，于是把正常链路判死了。

改法是让护栏去问"实际会连谁"，而不是只看 DNS 答案：`services/web/provider.py` 新增 `_carried_by_system_proxy(scheme, host)`，用 urllib 自己的 `getproxies()` 与 `proxy_bypass(host)` 复现它的选路决定——代理在场就放行，代理不在场（或该域名命中免代理名单）仍按原样逐条校验解析结果。安全边界没松：Base URL 早由 `services/web/models.py:16-32` 限定为 https、端口只许 443、不许带凭据、不许写字面量 IP、不许 `localhost`，`NoRedirect` 继续拒绝重定向转发 Key，走代理时 Bearer 头在 TLS 之内，代理只见主机名。报错文案也补上了那个非公网地址和"该域名走真实解析或配 `HTTPS_PROXY`"的出路。

复测（都用一个明显无效的 Key，不碰学习者账户）：

- 直连路径的 `_post` 现在到达了服务端并返回 `HTTP 401`，说明网络、TLS、路径都是通的，挡人的确实是那条 DNS 校验。
- 走真实按钮的 `/api/v1/web/model/test` 返回 `ok=false, mode=rule_only, errors=['LLM HTTP 401（已用尽重试预算）']`——"错误 Key 明确报错"这一档当场有了读数，页面同时保留规则检索结果。
- 新增用例 `tests/test_web_workbench.py::test_model_guard_checks_the_endpoint_it_will_actually_dial` 钉住四种组合：假 IP 无代理拒、假 IP 命中免代理名单仍拒、公网 IP 无代理放行、假 IP 有代理放行且请求 URL 仍是原 https 地址。`tests/test_web_workbench.py` 与 `tests/test_services_llm.py` 共 35 项加 13 个子测试全绿。

留一句实话：**正常 Key 能不能拿到"模型已参与"的回复，仍然只有学习者本人能验**——本轮只证明通道开着、坏 Key 会被如实报错，没有替账户做真实推理调用。

## 尚未实测

- **真实 DeepSeek Key 的线上调用**：只验过接口适配、结构化回复校验、失败降级、引用越界拒绝和 Key 不回显；上一节又补了通道连通与坏 Key 的报错读数。仍然只能由本人 Key 完成的只剩两件事：正常 Key 拿到"模型已参与"的回复、刷新后 Key 清空而学习记录仍在。
- 引用校验只保证引用 ID 属于本次证据，不代表每句解释都被来源支撑。
- CET 逐节收卡与强制听力播放、面试麦克风录入、公网账户／多租户与限流。
- "本题已不可提交"这张卡只由桩掉的 409 触发过：真实的档位切换会先重置工作台，构不出与研究档练习卷冲突的提交；后端错误码有后端用例钉住，前端这一支的真实触发场景（模考已收卡、题图缺失）没在浏览器里走到过。
- 面试的语音档只按**粘贴进来的转写文本**测语速、停顿与环节覆盖；浏览器录音这条路径没实测过，文字反馈也评价不了仪态、发音与视频表现。
- 推荐解释停在任务级：任务标题与学情读数说清了"哪一类、哪个考点、几道题"，但没有为某一道题单独写出来的理由文本（任务字段里没有这一项）。
- 量规 6 份未签署、教资先修边 31 条待核定：这两条限制继续生效，主观题与面试都不出正式分数与通过概率，先修也不做前置阻断。

## 答案冲突首批核对之后（2026-10-11，`xiaoxue/jiaoyuxinlixue`）

这一轮**动了数据**。实况在顶上"当前实况"一节，本节往下都是逐批的当时状态，只作对照：核对前那棵树是 13,269 可练、1,040 冲突、`remaining_gaps = 130,762`，本节留下这一批的题号与前后对照。

34 题隔离里 22 题回原卷核对成立并落回，12 题核对不出来仍留隔离（题干定位不到 4、两份抽取不一致 6、非四选项单选 2）。逐题的题号、修改前后内容、原卷文件与卷内题号、隔离时保全的候选、审核状态都在 `数据集/教资/review/answer_conflict_reconciliation.xiaoxue_jiaoyuxinlixue.jsonl`（当时这批写在全库共用的一份 `answer_conflict_reconciliation.jsonl` 里，下一节说它为什么按批改名）。

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

## 补收录缺口的全库规模进了现算复核清单（2026-10-11，未动数据）

上一节把 12 道拒绝题的串题证据落到字段，这一节把同一缺陷的**全库规模**变成可核对的现算清单。改动只在 `kb_tools/ntce_repair.py`（判据拆成 `mix_risk_evidence` 出证据、`boundary_risks` 映形态码、`recorded_numbers` 给本卷已入库题号、`unrecorded_neighbors` 取没有记录的那些）、`kb_tools/ntce_conflict_reconcile.py`（改调这同一份函数，删掉自己那份题号与"无记录"计算）、`审查/build_review_queue.py`（新增 §3.2）与三份文档。**题库一行没动**：一条答案、一个审核字段、一张卡片、一条图边都没变。

现算结果（重跑 `python 审查/build_review_queue.py` 可复现，清单里的数字不手抄）：

- 命中任一边界形态 **646** 题（本库 14,500 题）；四个形态各自 280／295／564／227，同一题可命中多项，所以命中数小于四项相加的 1,366。
- 分岔只在"正文露出邻题编号"的 227 题里分：**75 题**的邻题在本卷有独立记录（剪重复文本是去重，题量不变）；**152 题、195 条（卷·编号）**在本卷没有独立记录——按上一节已确认的口径，**这些文本不能剪**，剪掉等于删掉库里唯一一份邻题内容，动作是回原件补收录；其余 **419 题**只数得出序列、认不出编号，逐题人工回卷，机器不给结论。
- 195 条按"学段／科目／卷面文件·编号"去重，其中 2 条落在一条题号定位都没有的 9 份卷面上，那部分只能说"定位缺失"，所以真正能对着原件补的是 **150 题／193 条**；缺口分布在 33 个学段·科目，最集中的是 `chuzhong/yuwen` 与 `gaozhong/yuwen`（各 12 条）。

三个口径错各有一条负向断言钉住，防止清单再漂回去：

- 分母若用回全部命中题（646−152），会把"认不出编号"的 419 题登记成"邻题已有独立记录"，也就是把待人工回卷的题当成可以直接剪文本的题。
- 去重键若用裸文件名：`2019b.jsonl` 这类文件名在 14 个学段·科目目录下都出现，实测把 195 条并成 166 条，29 条缺口藏在合并里。用例同时断言两种键的结果数**不相等**，这条断言不会因数据变化而空跑。
- 无定位卷面的那部分被单列成"证据强度"，并把表中总数减去它给出可动手的题数／条数；清单不把"没有定位"写成"没有记录"。

覆盖在 `tests/test_acceptance_gate.py`：`test_the_boundary_fork_rows_are_recomputed_from_the_library` 用同一组函数把 §3.2 的每个单元格与题库现算逐行对齐；`test_the_queue_does_not_own_a_second_copy_of_the_boundary_rules` 用 AST 禁止清单脚本 `import re`，并要求它从 `ntce_repair` 取那四个函数。`test_the_review_queue_is_generated_not_transcribed` 继续保证整份清单是生成物。

这类缺陷在库里表现为**根本没有那条记录**，`审查/validate_kb.py` 的题级缺口码不会单独计数，所以严格审查这轮逐字不变（`structure_errors = 0`、`remaining_gaps = 130,738`、退出码 `1`），完整性快照同样不变（13,291 可练、1,018 冲突、149 缺答案）。退出码 1 是内容缺口的既有状态，不是本轮引入的回归；`structure_errors` 保持 0。

下一轮按 §3.2 的 150 题／193 条回原件补收录：补成独立记录后走唯一出口重建索引与卡片，验收看该表三条计数同时下降、`structure_errors` 仍 0，且新记录的 `checked_by` / `content_verified` 不因补收录而提升。

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q`（主工作区工作树，最终状态） | `459 项通过、63 个子测试通过、7 项失败`，实测 179.46 秒，退出码 `1`。通过数比上一节的 457 多 2，正是本轮新增的两条用例；失败 7 项与上一节**逐条同名**（5 项 `test_learning_workflow.py` 的 `exam_sessions` AttributeError、2 项 `test_learning_resources.py` 的有意缺口标记），仍全在并行会话未入库的那条线上，本会话不碰也不把它们的红算成自己的绿 |
| `python -m pytest tests/test_acceptance_gate.py -k "boundary_fork or second_copy or review_queue_is_generated" -q` | 3 passed，40 deselected，退出码 0 |
| `python 审查/audit_ntce_completeness.py` | 退出码 0；13,291 可练、来源冲突 1,018、缺答案 149、无题叶子 7、未签署量规 6、L7 = 11、图边 96,785——与上一节逐字相同，`审查/教资完整性核对.json` 重跑后 `git status` 干净（快照不含钟点，所以能证明数据未变） |
| `python 审查/状态词表检查.py 数据集/教资` | 15,185 条 0 违规，退出码 0 |
| `python 审查/状态词表检查.py 数据集/四六级` | 31,991 条 0 违规，退出码 0 |
| `python 审查/validate_kb.py --output .local_state/web_audit_final.json` | 退出码 `1`：`structure_errors = 0`、`remaining_gaps = 130,738`，逐项与上一节相同——数据未动，只有清单生成物与代码变了 |

## 答案冲突第二批核对之后（2026-10-11，`xiaoxue/zonghe`）

这一轮又**动了数据**。上一节记的 13,291 可练、1,018 冲突、`remaining_gaps = 130,738` 是第一批之后的数，本节往下才是这批的对照；两批之后的实况在顶上"当前实况"。

按"先选你实际准备使用的科目"往下走，第二批仍留在小学：`xiaoxue/zonghe`（综合素质）当次有 **48** 题带 `source_conflict`，是小学四个科目里最多的一份（其余 29／12／10）。核对结果 **24 题落回、24 题仍隔离**（题面串题风险未决 15、题干在原卷定位不到题号 9），24 道落回全部来自 `2016a` 一份卷面——那批是同一份卷的两套抽取在答案键上系统性错位，其余卷面要么定位不到、要么题面本身串了邻题。

落回的字段与状态结果与第一批逐条一致：`answer_status` `source_conflict → letter_only`、`review.status` `quarantined → needs_fix`、`answer_validation_status = not_expert_verified`，`checked_by` 一题都没动、`content_verified` 保持 false；前后对照与同步重写的规则解析草稿记在该题 `extra.source_repairs`。24 张卡片连带 `sync_cards` 重渲染，图谱、完整性快照与复核队列各走自己的唯一出口重建。

**验收达成：该批内容缺口下降（批内冲突 48 → 24、该批可练 567 → 591），全库冲突 1,018 → 994、可练 13,291 → 13,315，同时 `structure_errors` 保持 0。** 教资分项：`Q_ANSWER_MISSING` 4,487 → **4,463**，`Q_ANSWER_SOURCE_CONFLICT` 1,018 → **994**，`Q_ANSWER_BINDING_PENDING` 2,196 → **2,220**，`Q_STEM_EMPTY` 369 不变，`Q_ANALYSIS_INCOMPLETE` 4,829 → **4,826**。全库少 27 条 = −24 缺答案 − 24 冲突 + 24 待绑定 − 3 解析分维，与 130,738 → 130,711 逐条对得上；那 −3 不是落回的固定收益，只是这批的落回答案恰好补齐了三题的选项辨析分维。

### 证据文件改为按批存一份

原先全库共用一对 `answer_conflict_reconciliation.{jsonl,summary.json}`，核对第二个科目时同一行 `write_rows` 把第一批的题号、依据与结论整批覆盖掉——修补历史就断了。现在由 `evidence_paths(review, batch)` 按 `answer_conflict_reconciliation.<学段>_<科目>` 命名，一批一对，核对别的科目碰不到这一份；`run()` 另加 `review_dir` 接缝，测试与"没被安排核对的科目"只在临时目录里跑，跑一次测试不会在库里凭空多出"这科已核对"的证据。`test_reconciling_another_batch_keeps_this_batchs_evidence_whole` 用整目录快照钉住这条。

### 补收录的计数只许有一个口径

第一批的摘要把"无独立记录的邻题编号"按题面处数累加（10），而 §3.2 的现算清单按（卷·编号）去重（9）——同一件事两个家。合并到 §3.2 那份口径：`boundary_numbers_without_record` 按（学段/科目 · 卷面 · 编号）去重数**条**，新增 `boundary_questions_without_record` 数**露出至少一个无记录编号的题**。第二批的 22 道带串题证据的拒绝题里 **7 题 / 9 条**要回原件补收录：`2017b`·29（被 `2017b.q09` 与 `2017b.q24` 两道题各露出一次，仍只算一条待补记录）、`2019b`·28、`2022b`·28、`2023a`·8/10/12/19/28、`2023b`·28；这 7 题就是 §3.2 里 `xiaoxue/zonghe` 那一行。最重的 `ntce.xiaoxue.zonghe.2017b.q09` 的 D 选项里数得出 20 道完整 A-D 序列。

去重键必须带学段/科目：`2019b.jsonl` 这类文件名在 14 个学段·科目目录下都出现，用裸文件名会把不同科目的同号卷面并成一条。`test_a_recording_gap_counts_once_per_paper_not_once_per_mention` 用合成行同时钉住"按题面处数累加"和"跨科目同卷名合并"两种错。

同样**不能剪这些文本**——剪掉等于删掉库里唯一一份邻题内容，动作是回原件补成独立记录。落回也不清 `source_mix_risks`，所以这两批都没动 §3.2 的 646 题／152 题／195 条／193 条账。

### 门禁与全量测试（本轮实测）

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q`（主工作区工作树，状态目录指向空临时处） | `461 项通过、63 个子测试通过、7 项失败`，实测 205.67 秒，退出码 `1`。比上一批的 459 多 2，正是本会话为第二批核对新增的两条用例（`test_reconciling_another_batch_keeps_this_batchs_evidence_whole`、`test_a_recording_gap_counts_once_per_paper_not_once_per_mention`，`tests/test_ntce_conflict_reconcile.py` 因此从 10 个用例涨到下面那一行的 12）；失败 7 项与"当前实况"一节**逐条同名**，仍全在并行会话未入库的那条线上 |
| `python -m pytest tests/test_ntce_conflict_reconcile.py -q` | 12 passed，退出码 0 |
| `python -m pytest tests/test_acceptance_gate.py -q` | 43 passed，退出码 0 |
| `python 审查/audit_ntce_completeness.py` | 退出码 0；14,500 题里 13,315 可练、来源冲突 994、缺答案 149、缺挂载 1,331、缺考纲 3,928、空题干与缺选项文本 45、无题叶子 7、未签署量规 6、具名签核 0 |
| `python 审查/状态词表检查.py 数据集/教资` | 15,185 条 0 违规，退出码 0 |
| `python 审查/状态词表检查.py 数据集/四六级` | 31,991 条 0 违规，退出码 0 |
| `python 审查/validate_kb.py --output .local_state/web_audit_final.json` | 退出码 `1`：`structure_errors = 0`、`remaining_gaps = 130,711`、`complete = false`。表里的答案冲突与解析分维等分项是教资＋四六级合计，按 `issues[].dataset` 才能分出上一节那几个教资专数 |

一次并行跑出的 8 项失败里有一项 `test_the_review_queue_is_generated_not_transcribed` 报"清单与生成物不一致"：`审查/待复核清单.md` 是生成物，核对后没及时重跑 `审查/build_review_queue.py` 就会漂红。重跑后与盘上那份逐字相同、该用例单独跑 43 项全绿，属生成物没跟上而非判据有第二份；这也说明清单的红是一条真实护栏——它能在数据改完后发现复核队列还写着旧账。

## 答案冲突第三批核对之后（2026-10-11，`gaozhong/lishi`）

这一轮又**动了数据**。第二批之后记的 13,315 可练、994 冲突、`remaining_gaps = 130,711` 是这一节的对照起点；三批之后的实况在顶上"当前实况"。

第三批走到 `gaozhong/lishi`，当次 **173** 题带 `source_conflict`（该科目共 428 题）。三件判据与前两批一字未改：题干在原卷唯一定位到题号、该题号的答案键是单字母且落在印刷四选项内、并与隔离时保全的候选一致；任一件不成立就一行不动。结果 **125 题落回、48 题仍隔离**（题干在原卷定位不到题号 27、题面串题风险未决 18、五选项多选 3）。与第二批"24 道落回全来自 `2016a` 一份卷面"不同，这批的落回摊在 **7 份卷面**上——`2014a` 16、`2014b` 10、`2015a` 22、`2015b-jx` 5、`2016a` 23、`2016b` 24、`2017a` 25——逐题成立才落，没有哪一份是整卷错位。

落回的字段结果与前两批逐条一致：`answer_status` `source_conflict → letter_only`（125 题全如此）、`review.status` `quarantined → needs_fix`（125）、`answer_validation_status = not_expert_verified`（125）；`checked_by` 一题都没动（非空 0 题）、`content_verified` 保持 false（为真 0 题）。题号、答案文件路径、保全候选、修改前后内容与依据文字都写在该题 `extra.source_repairs` 里 `kind = source_conflict_answer_reconciled` 那一条，条内同时落 `expert_verified: false` 与 `checked_by: null`；规则解析草稿跟着答案同步重写，卡片、图谱、完整性快照与复核队列各走自己的唯一出口重建。

**验收达成：该批内容缺口下降（批内冲突 173 → 48、批内可练 253 → 378，差额就是这 125 题），全库冲突 994 → 869、可练 13,315 → 13,440，同时 `structure_errors` 保持 0。** 教资专数：`Q_ANSWER_MISSING` 4,463 → **4,338**，`Q_ANSWER_SOURCE_CONFLICT` 994 → **869**，`Q_ANSWER_BINDING_PENDING` 2,220 → **2,345**，`Q_STEM_EMPTY` 369 不变，`Q_ANALYSIS_INCOMPLETE` 4,826 不变——这批的落回没有补齐任何一题的解析分维。全库 `remaining_gaps` 130,711 → **130,586**，少的正好 125 条 = −125 缺答案 −125 冲突 +125 待绑定。三批合计：落回 171 题（22 + 24 + 125），`remaining_gaps` 130,762 → 130,586，少 176 条。

### 125 题落回只重写 95 张卡：差的 30 题按设计不出卡

`cards_rewritten_this_run = 95` 不等于落回的 125。差的 30 题都带 `extra.duplicate_of`：`sync_cards` 对判重题跳过出卡（卡只给被指向的规范题，避免同一内容在向量库里堆两份），所以这 30 题落回时没有自己的卡可重写，它们的内容由规范题那张卡代答。逐条查过这 30 题指向的规范题都有卡。这不是漏渲染，也不该靠补卡解决——但"代答"本身露出第二维缺口，见下面那一节。

### §3.2 的补收录账这轮没动

落回不清 `extra.source_mix_risks`，而 §3.2 按题面字段现算、不看批内证据文件，所以四个形态 280／295／564／227、命中任一 **646** 题、**152 题／195 条**（卷·编号）在本卷无独立记录、去掉无定位卷面后可动手的 **150 题／193 条**，与第二批之后逐字相同。该批 48 道拒绝题里 25 道带串题证据、其中 3 题／3 条露出的是无独立记录的邻题编号，这 3 条本来就在那 195 条里（`gaozhong/lishi` 不在分布前 8 名，第 8 名是 7 条）。逐题证据落在 `数据集/教资/review/answer_conflict_reconciliation.gaozhong_lishi.{jsonl,summary.json}`，173 行一批一对，换科目核对碰不到别批那份。

## 判重归属的两维缺口进了现算清单（2026-10-11，未动数据）

上面那个 125／95 的差额把建库时的判重规则照成一个从没被现算过的东西：`数据集/教资/cards` 磁盘上 **12,881** 张卡，另有 **1,619** 题按 `sha(norm_stem(题干))` 判为重复题干、按设计不出卡。这 1,619 条归属里有 **507** 条今天**核不出归属**，形态是三样：指纹是空题干 **71**、指纹只剩一个残留字（如"缺"）**401**、题干在判重之后被改过、现指纹与规范题不等 **35**；指向的规范题已不存在 **0** 条。剩下 **1,112** 条指纹承载内容且仍相等。前两类合起来 472 条是"两条抽取都失败过就等于同一道题"，相等说明不了什么；第三类是归属已自相矛盾——这道题没有自己的卡，规范题那张卡讲的也不是它，RAG 召回看不见它，而 `validate_kb.py` 不报错，因为"记录在、卡不在"是设计行为，形状上没有缺陷可报。

第二维缺口是**代答落空**，与归属核不出正交：这 1,619 条里有 **626** 条，规范题自己就没有可给出的答案（`answer_status` 为 `missing`／`source_conflict`，`content.answer` 已置 null，卡上印"未提供"）。它不计进上面那 507 条——指纹仍然相等、归属仍然对得上，缺的是答案不是归属；其中 **254** 条归属完全可核对，唯一的缺口就是这一条。清 `duplicate_of` 既不解决它也不该解决它，要动的是规范题那一侧的答案核对，两类动作分开排。不可核对的归属集中在 29 个学段·科目，最靠前是 `gaozhong/dili` 61、`chuzhong/dili` 57、`gaozhong/shengwu` 37、`gaozhong/lishi` 28。

两维都由 `kb_tools/ntce_repair.py` 的同一份判据算出（`dedup_evidence` 出单条证据、`dedup_audit` 汇总），`审查/build_review_queue.py` 只做生成：它 `import` 这两个函数、被 AST 用例禁止自己 `import re`，§3.3 表内每个单元格与两维合计都是现算。卡集交叉核对同轮成立：1,619 条归属全部没有自己的卡（`card_written = 0`），这个数字一旦不再等于归属总数，出卡与判重两套口径就开始各说各话。**题库一行没动**：一条答案、一个审核字段、一张卡、一条图边都没变，§3.2 那笔账也没动。脚本不自动清 `duplicate_of`——清了会一次性多出几百张卡，卡集数量、可练题量与向量索引的口径同时变，只能分批人工回卷核。

### 这两轮新增的用例各自钉住了什么

全量 463 的构成里，比第二批那一轮的 461 多出的两条各有唯一归属，逐档实测（状态目录指向空临时处，逐档单独跑、不与全量运行重叠）：

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/test_ntce_conflict_reconcile.py -q` | 13 passed，退出码 `0`。第三批 `gaozhong/lishi` 涨的那条是 `test_a_deduped_restored_question_is_carried_by_the_canonical_card`：落回的题若带 `duplicate_of`，断言它没有自己的卡、且全库汇总 `card_written = 0`；规范题有答案就核对那张卡确实是它的镜像，规范题没答案就核对卡如实印"未提供"，再把这两个维度现算出的条数拿去 §3.3 正文里找同一句，找不到就报红。125／95 那个差额从此有用例守着，也不会被"顺手补几张卡"糊过去 |
| `python -m pytest tests/test_acceptance_gate.py -q` | 44 passed，退出码 `0`。判重两维这轮涨的那条是 `test_the_dedup_link_rows_are_recomputed_from_the_library`：现读全库题记录跑 `dedup_audit`，把 §3.3 的四个形态码行、可核对合计行、标题里那两个数、卡集交叉核对那行、代答落空那两个数逐个对回现算值；同时断言可核对＋核不出＝归属总数、形态码之和不大于核不出的题数、`card_written = 0`、代答落空的可核对子集不大于可核对总数——两维一旦互相顶替或者数字被手抄过，立刻报红 |
| `python -m pytest tests/test_web_workbench.py -q` | 16 passed，退出码 `0`。必修项（提交重试指纹）所在文件整档绿，第 1 项的验收用例在里面 |

知识库四道门禁在这两轮之后的现数就是顶上"当前实况"那张表，本表不复述计数：`structure_errors` 仍为 `0`，`remaining_gaps` 只差在内容缺口上。

## 答案冲突第四批核对之后（2026-10-11，`chuzhong/shuxue` ＋ `chuzhong/dili`）

第三批之后那三个数（13,440 可练、869 冲突、`remaining_gaps = 130,586`）是这一轮的起点。这一轮先做一次**只读全库清点**问"三件判据今天还能给出唯一结论的还有几题"：只剩 24 题，散在多个科目。第四批取其中初中两科，判据与前几批一字未改。

| 科目 | 隔离 | 落回 | 定位不到题号 | 串题未闭合 | 非四选项单选 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `chuzhong/shuxue` | 51 | 11 | 13 | 16 | 11 |
| `chuzhong/dili` | 61 | 1 | 15 | 40 | 5 |

**验收达成：批内冲突 51→40、61→60，批内可练 208→219、350→351；全库冲突 869→857、可练 13,440→13,452、`remaining_gaps` 130,586→130,574（正好 −12），`structure_errors` 仍为 `0`，两库状态词表 0 违规。** 教资专数 −12 缺答案、−12 冲突、+12 待绑定。12 道落回都没有 `duplicate_of`，各渲染出自己的 12 张卡，卡集总数因此不变；字段与审核状态同前三批（`letter_only` / `needs_fix` / `not_expert_verified`，`checked_by` 空、`content_verified` false）。这一轮第一次出现成片的 `not_a_four_option_single_choice`（11＋5）：这些题的印刷选项不是四选一，一个字母不构成完整答案，**不是"答案算不出"，是"这题本就不该按单选落回"**。

### 落回带动解析草稿分成两档：这一轮照出来的

`ntce.chuzhong.dili.2014b-jx.q13` 落回后题记录写着 `answer = C`，解析草稿的 `correct_answer` 还停在空，回归 `test_restored_rule_analysis_follows_the_answer_without_claiming_verification` 当场报红。修的方向不是把断言改松：**答案字段必须与落回一致**，能动多少正文由文案的家决定。`method = rule_kb_draft` 的规则草稿四段整段重算；出身在别处的草稿（如学科大模型推演候选 `qwen-plus_deduced_candidate_v1`）只把 `correct_answer` 对齐，正文、`method`、`status` 一字不改——重写别人的正文等于核对工具替那份草稿做学科判断；人工审核过的（`checked_by` 非空或 `tagger = expert`）两档都不碰。该题正文本就按"②③正确 → C"写，缺的只是答案字段，对齐即自洽；它 `source_note` 那句"原题来源缺失官方答案"现在与原卷不符，但那属于那份草稿自己的申报，要清的仍是教研核定，四条待补项一条都没关。全库 195 道已落回里只有这一道是非规则草稿。新增两条用例守住两档边界：`test_a_draft_owned_by_another_generator_only_gets_its_answer_aligned` 断言差异集只含 `correct_answer` 一个字段、再调一次返回空；`test_a_manually_reviewed_draft_is_left_alone_even_when_the_answer_landed` 断言签核过的草稿整条不碰。

### 跑一次测试套件就会把第一批的摘要写成报告模式

第五批之后发现 `xiaoxue/jiaoyuxinlixue` 的摘要又退回 `applied: false`／`cards_rewritten_this_run: 0`，查到的来源不是探针而是**用例自己**：`tests/test_ntce_conflict_reconcile.py:234` 按设计对真实库调 `run(scope=BATCH, apply_changes=False)`，并在末尾断言 `summary['applied']` 为假——它守的正是"只出报告的运行整批再生证据、一题数据都不动"。所以每跑一次套件，那批的证据文件与摘要就被重写成报告模式，题记录、卡片、审核字段一概不动（那也是同一条用例断言的部分）。收尾动作固定一条命令：`python kb_tools/ntce_conflict_reconcile.py --scope xiaoxue/jiaoyuxinlixue --apply`。两次验证都逐字节幂等——题面文件 sha256 `9c697d2d…`、该科目 36 张卡 sha256 `8df9b1b4…` 跑前跑后不变，摘要回到 `applied: true`／22。读摘要的分工照旧：`restored_in_dataset` 与 `by_result` 是库的实况，`applied` 与 `cards_rewritten_this_run` 只说当次模式。一次并发跑套件时那条恢复撞到过 `PermissionError: [WinError 5]`（`atomic_write` 换文件时被 Windows 占用挡住），单独复跑该文件 15 项全绿、目录没留 `.tmp`，属瞬时锁不是判据问题。

## 答案冲突第五批核对之后（2026-10-11，`gaozhong/huaxue` ＋ 省考两科）：机械核对见底

第四批之后剩下的 857 题隔离，再用同一份判据做只读清点：还能机械落回的只有 **12** 题，摊在三个科目上。第五批把这三科核完。

| 科目 | 隔离 | 落回 | 定位不到题号 | 串题未闭合 | 非四选项单选 | 答案键给多字母 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gaozhong/huaxue` | 38 | 5 | 9 | 14 | 10 | — |
| `xiaoxue/jiaoyuxue`（省考卷面） | 29 | 4 | 2 | 2 | 20 | 1 |
| `zhongxue/jiaoyuxue`（省考卷面） | 27 | 3 | 4 | 2 | 18 | — |

**验收达成：批内冲突 38→33、29→25、27→24，批内可练 267→272、123→127、30→33；全库冲突 857→845、可练 13,452→13,464、`remaining_gaps` 130,574→130,555，`structure_errors` 仍为 `0`，两库词表 0 违规。** 教资专数 −12 缺答案、−12 冲突、**+5** 待绑定——全库少 19 条就是 −12−12+5，那 +5 不是 +12：落回的 12 题里有 7 题的原卷答案条目本就带着可核对的本题题号定位，落回不新增这一维。这一轮第一次照出 `answer_key_offers_multiple_letters`（原卷在该题号给了多个字母，那是多选题，判据按设计只认单字母）。12 道落回又都没有 `duplicate_of`，各渲染 12 张卡。

清点把 845 题的卡点分完类：题面串题 **412**、题干在原卷定位不到题号 **294**、非四选项单选 **138**、答案键给多字母 **1**（四类相加即 845）。清点调的就是落回那份 `reconcile_one`，所以 12 是这台工具自己的天花板而不是估数——**机械核对到此见底，剩下的每一题都要有人在原卷上做一次判断**，工具只能把判断结果落成记录。

### §3.2 那笔补收录的账这两轮各加了若干

批内按（卷·编号）去重的题面收录缺口：第四批 100 道拒绝题里 73 道带串题证据，其中在本卷没有独立记录的是 **6 题 7 条**；第五批 82 道拒绝题里 36 道带证据，是 **14 题 23 条**。全库同一口径的数仍以 [待复核清单](../审查/待复核清单.md) §3.2 现算为准，本档不复述。

### 这两轮之后的门禁与用例（实测）

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q` | `465 项通过、63 个子测试通过、7 项失败`，实测 133.44 秒，退出码 `1`。比第三批那一轮的 463 多的 2 条就是解析归属那两条新用例；7 项红逐条同名，仍全在并行会话未入库的那条线上 |
| `python -m pytest tests/test_ntce_conflict_reconcile.py -q` | 15 passed，退出码 `0`（该文件从 13 涨到 15 就是上面那两条） |
| `python -m pytest tests/test_completeness_audit.py tests/test_acceptance_gate.py tests/test_ntce_conflict_reconcile.py -q` | 62 passed，实测 43.37 秒，退出码 `0`。这一档把"仓库里的完整性快照能由库复现""§3.2／§3.3 的清单数字是现算不是手抄""核对工具的判据与修复轮同一份"三条护栏一起跑一遍；上面那条 PermissionError 单独复跑与合跑都不再出现，确认是瞬时文件锁 |

四道门禁的现数不在这里复述，看顶上"当前实况"那张表。

那 5 项 `exam_sessions` 的红这一轮查清了成因，记在这里供接手的人一句话判定它不是功能缺口：`tests/test_learning_workflow.py:27` 用 `Workbench.__new__(Workbench)` 手工逐字段装配对象，绕过了 `__init__`，而 `self.exam_sessions = ExamSessions(self)` 住在 `services/web/service.py:42` 的 `__init__` 里。所以真实服务路径一直带着这个字段（本机网页的提交链路已在浏览器实测通过），红的只是这份 fixture 没跟上对象后来的形状。修法是在那段装配里补一行赋值，属并行会话那条线的文件，本会话没动它，也没把它的红算成自己的绿。


