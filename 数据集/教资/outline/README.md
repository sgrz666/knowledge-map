# 数据集/教资/outline —— L4 考点树的构建期源文件，只有 kb_tools 读它

44 份 `{学段}.{科目}.json`，一份 = 一个考试模块的知识点树（平铺 `nodes[]` + `parent` 指针，不嵌套）。`kb_tools/build_graph.py:87-97` 把它读成图里的 L4 `knowledge_node` 与 `has_child`/`contains`/`basis` 边；`services/**` 一行都不读（运行时取考点走 `graph/nodes.jsonl`）。所以改这里不影响线上读，只影响下一次重建图谱。

顶层键 44 份完全一致：`level`、`subject`、`subject_cn`、`verified`、`note`、`official_standard_ids`、`source_verified`、`nodes`。
`note` 44 份同句：「官方原文自动词项对齐与学科细点拆解；所有映射待教研审核。分组节点assessable=false不参与题级打标。」
`verified` 44 份全为 `false`，全目录没有任何 `checked_by`/`expert_verified` 痕迹（现算：带人工签署痕迹的文件 0 个）。

## 文件清单（44 份；节点数、入图数为 2026-10-12 现算）

「入图」= 该文件 `nodes[].node_id` 命中 `graph/nodes.jsonl` 里 layer=L4 的个数。总数与层级口径见 [`../README.md`](../README.md) 的 L4 行。

| 文件 | 字节 | 节点 | 可评估 | 分组 | 入图 L4 | official_standard_ids | 科目 |
|---|---|---|---|---|---|---|---|
| `chuzhong.dili.json` | 36,052 | 28 | 24 | 4 | 28 | ntce.outline.311 | 地理学科知识与教学能力(初级中学) |
| `chuzhong.huaxue.json` | 31,503 | 24 | 20 | 4 | 24 | ntce.outline.307 | 化学学科知识与教学能力(初级中学) |
| `chuzhong.jiaoyuxinlixue.json` | 3,309 | 4 | 4 | 0 | 0 | — | 教育心理学(省考) |
| `chuzhong.jiaoyuxue.json` | 3,271 | 5 | 5 | 0 | 0 | — | 教育学(省考) |
| `chuzhong.lishi.json` | 26,486 | 23 | 19 | 4 | 23 | ntce.outline.310, ntce.outline.316 | 历史学科知识与教学能力(初级中学) |
| `chuzhong.meishu.json` | 24,724 | 22 | 18 | 4 | 22 | ntce.outline.314 | 美术学科知识与教学能力(初级中学) |
| `chuzhong.shengwu.json` | 26,204 | 23 | 19 | 4 | 23 | ntce.outline.308 | 生物学科知识与教学能力(初级中学) |
| `chuzhong.shuxue.json` | 19,440 | 26 | 22 | 4 | 26 | ntce.outline.304 | 数学学科知识与教学能力(初级中学) |
| `chuzhong.tiyu.json` | 31,045 | 24 | 20 | 4 | 24 | ntce.outline.313 | 体育与健康学科知识与教学能力(初级中学) |
| `chuzhong.wuli.json` | 22,490 | 25 | 21 | 4 | 25 | ntce.outline.306 | 物理学科知识与教学能力(初级中学) |
| `chuzhong.xinxi.json` | 31,196 | 23 | 19 | 4 | 23 | ntce.outline.315 | 信息技术学科知识与教学能力(初级中学) |
| `chuzhong.yingyu.json` | 27,835 | 23 | 19 | 4 | 23 | ntce.outline.305 | 英语学科知识与教学能力(初级中学) |
| `chuzhong.yinyue.json` | 23,568 | 22 | 18 | 4 | 22 | ntce.outline.312 | 音乐学科知识与教学能力(初级中学) |
| `chuzhong.yuwen.json` | 29,428 | 23 | 19 | 4 | 23 | ntce.outline.303 | 语文学科知识与教学能力(初级中学) |
| `chuzhong.zhengzhi.json` | 27,596 | 22 | 18 | 4 | 22 | ntce.outline.309 | 思想品德/思想政治学科知识与教学能力(初级中学) |
| `gaozhong.dili.json` | 35,429 | 28 | 24 | 4 | 28 | ntce.outline.411 | 地理学科知识与教学能力(高级中学) |
| `gaozhong.huaxue.json` | 31,486 | 24 | 20 | 4 | 24 | ntce.outline.407 | 化学学科知识与教学能力(高级中学) |
| `gaozhong.jiaoyuxinlixue.json` | 3,309 | 4 | 4 | 0 | 0 | — | 教育心理学(省考) |
| `gaozhong.jiaoyuxue.json` | 3,271 | 5 | 5 | 0 | 0 | — | 教育学(省考) |
| `gaozhong.lishi.json` | 19,562 | 23 | 19 | 4 | 23 | ntce.outline.410 | 历史学科知识与教学能力(高级中学) |
| `gaozhong.meishu.json` | 24,762 | 22 | 18 | 4 | 22 | ntce.outline.414 | 美术学科知识与教学能力(高级中学) |
| `gaozhong.shengwu.json` | 26,204 | 23 | 19 | 4 | 23 | ntce.outline.408 | 生物学科知识与教学能力(高级中学) |
| `gaozhong.shuxue.json` | 20,092 | 26 | 22 | 4 | 26 | ntce.outline.404 | 数学学科知识与教学能力(高级中学) |
| `gaozhong.tiyu.json` | 31,708 | 24 | 20 | 4 | 24 | ntce.outline.413 | 体育与健康学科知识与教学能力(高级中学) |
| `gaozhong.wuli.json` | 22,470 | 25 | 21 | 4 | 25 | ntce.outline.406 | 物理学科知识与教学能力(高级中学) |
| `gaozhong.xinxi.json` | 31,919 | 23 | 19 | 4 | 23 | ntce.outline.415 | 信息技术学科知识与教学能力(高级中学) |
| `gaozhong.yingyu.json` | 27,189 | 23 | 19 | 4 | 23 | ntce.outline.405 | 英语学科知识与教学能力(高级中学) |
| `gaozhong.yinyue.json` | 24,942 | 22 | 18 | 4 | 22 | ntce.outline.412 | 音乐学科知识与教学能力(高级中学) |
| `gaozhong.yuwen.json` | 29,305 | 23 | 19 | 4 | 23 | ntce.outline.403 | 语文学科知识与教学能力(高级中学) |
| `gaozhong.zhengzhi.json` | 27,643 | 22 | 18 | 4 | 22 | ntce.outline.409 | 思想品德/思想政治学科知识与教学能力(高级中学) |
| `xiaoxue.jiaoxue.json` | 24,226 | 19 | 12 | 7 | 19 | ntce.outline.202 | 教育教学知识与能力(小学) |
| `xiaoxue.jiaoyuxinlixue.json` | 3,304 | 4 | 4 | 0 | 4 | — | 教育心理学(省考) |
| `xiaoxue.jiaoyuxue.json` | 3,265 | 5 | 5 | 0 | 5 | — | 教育学(省考) |
| `xiaoxue.zonghe.json` | 28,133 | 23 | 18 | 5 | 23 | ntce.outline.201 | 综合素质(小学) |
| `youer.baojiao.json` | 21,456 | 21 | 14 | 7 | 21 | ntce.outline.102 | 保教知识与能力(幼儿园) |
| `youer.jiaoyuxinlixue.json` | 3,294 | 4 | 4 | 0 | 0 | — | 教育心理学(省考) |
| `youer.jiaoyuxue.json` | 3,253 | 5 | 5 | 0 | 0 | — | 教育学(省考) |
| `youer.mianshi.json` | 16,885 | 12 | 6 | 6 | 12 | ntce.interview.youeryuan | 幼儿结构化面试 |
| `youer.zonghe.json` | 26,708 | 23 | 18 | 5 | 23 | ntce.outline.101 | 综合素质(幼儿园) |
| `zhongxiaoxue.mianshi.json` | 16,927 | 12 | 6 | 6 | 12 | ntce.interview.xiaoxue, ntce.interview.zhongxue | 中小学结构化面试 |
| `zhongxue.jiaoyuxinlixue.json` | 3,309 | 4 | 4 | 0 | 4 | — | 教育心理学(省考) |
| `zhongxue.jiaoyuxue.json` | 3,271 | 5 | 5 | 0 | 5 | — | 教育学(省考) |
| `zhongxue.jiaoyuzhishi.json` | 36,072 | 24 | 16 | 8 | 24 | ntce.outline.302 | 教育知识与能力(中学) |
| `zhongxue.zonghe.json` | 28,806 | 23 | 18 | 5 | 23 | ntce.outline.301 | 综合素质(中学) |

`source_verified`：34 份国标文件为 `true`，10 份省考文件（`{5 学段} × 教育学/教育心理学`）为 `false` 且 `official_standard_ids` 为空——它们没有官方大纲原文可对，`nodes[]` 全部是 `assessable=true` 的省考模块节点（没有分组层）。

## 节点形状

```
node_id            ntce.{学段}.{科目}.s{模块号}          分组节点（assessable=false）
                   ntce.{学段}.{科目}.s{模块号}.k{两位序号}  可评估细点
                   shengkao.{学段}.{科目}.m{序号}         省考节点
name / parent / keywords[] / ability_codes[]（subject|theory|ability|...）
assessable         false 只做分组，题级打标与图检索都不认它
exam_requirement_ids[]  对齐到的权威条款 id，最多 3 条（ntce_repair.py 的 scored[:3]）
alignment_evidence[]    {requirement_id, matched_terms[], method, rationale, expert_verified:false}
sources[]               {standard_id, path(权威资料/originals/…), source_url, locator…}
mapping_status     见下表；verified 恒 false
```

`mapping_status` 全库四态（现算 818 节点）：`automatic_alignment_pending_review` 264（官方原文词项直接命中）、`pending_official_alignment` 228（没对齐上，含全部省考节点）、`derived_from_official_scope_pending_review` 173（把官方能力/知识范围拆成可评估细点，`method=domain_requirement_operationalization`，`rationale` 写「将官方能力/知识范围拆解为可评估任务：+节点名」）、`grouping_only` 153（分组节点）。第五个值 `manual_mapping_requires_source_migration` 只在引用了失效条款时才被写入（`ntce_repair.py:80-87`），当前 0 个节点带它，旧引用会留在 `retired_alignment_evidence[]`。

## 谁写谁读

- 写入（结构）：`kb_tools/m5_tag.py:173 gen_outline()`，由 `kb_tools/ntce_ontology.py:262 expand_outline()` 把 `OUTLINES` 种子展开成节点；命令 `python kb_tools/m5_tag.py outline`。已存在文件会被逐节点合并：带 `checked_by` 或 `expert_verified` 的节点整体保留旧值，其余节点只补「新文档里没有的旧键」。
- 写入（对齐）：`kb_tools/ntce_repair.py:73 align_outline()`，逐文件在 `:692` 被 `glob('*.json')` 扫到，拿 `权威资料/requirements.jsonl` 按 `same_scope()`（`:60`）筛同科目同学段条款，再用 `keywords` 词项命中打分改写 `exam_requirement_ids`/`alignment_evidence`/`mapping_status`。命令 `python kb_tools/ntce_repair.py`（含重建结构）或 `--skip-outline`（只对齐）。
- 读取：`kb_tools/build_graph.py:87`（L4 节点 + `basis` 边 + `has_child`/`contains`）、`kb_tools/llm_batch.py:217 load_outline()`（给批量打标提供考点上下文）、`kb_tools/ntce_analysis_fill.py:37`（已有考点词表）、`kb_tools/ntce_verify.py:13`（`('outline','*.json')` 进快照哈希，用于双次复跑幂等判定）。
- 校验：`ntce_verify.py` 之外没有单测直接断言本目录内容；图谱侧的约束由 `tests/test_graph_direction_contract.py`、`tests/test_ntce_hierarchy_contract.py` 间接覆盖。

## 改这里之前要知道的

- 本目录是生成物，`../README.md` 末尾的「生成物一律不手改」名单包含 `outline/*.json`。手改会被下一次 `m5_tag.py outline` / `ntce_repair.py` 覆盖——`keywords` 在新文档里存在，所以手加的关键词会被种子值顶掉；只有给节点写上 `checked_by` 或 `expert_verified` 才能整节点保住。
- 6 份文件（初中/高中/幼儿园的 `jiaoyuxue`+`jiaoyuxinlixue`，27 个 `shengkao.*` 节点）**不入图**：`build_graph.py:35-45` 的 `modules` 键来自 `questions/{学段}/{科目}/` 目录，这三个学段没有对应题目目录，于是文件根本不被读。小学、中学的同名文件因为题库里有 `xiaoxue/jiaoyuxue`、`zhongxue/jiaoyuxinlixue` 题目而入了图（见上表「入图 L4」列的 4/5）。
- 10 份省考文件是同一份内容的 5 份复制：按（节点名 + keywords + ability_codes）归一化后现算哈希，`jiaoyuxue` 5 份（初中/高中/小学/幼儿园/中学）完全相同、`jiaoyuxinlixue` 5 份完全相同，差别只有 `level`/`subject` 与 `node_id` 前缀。改一份必须同时改五份，否则下次重跑会让五份重新被同一颗子覆盖，但读到的中间状态不一致。
- 对齐证据的 `expert_verified` 恒为 `false`，节点 `verified` 恒为 `false`：这些 `exam_requirement_ids` 是脚本词项匹配的结果，不是教研核定结果。学习路径与题→考点映射可以用它们，但对外口径必须带「待审核」。`审查/待复核清单.md` 由 `build_review_queue.py` 现算列出未覆盖条款。
- 树只有两层（模块分组 → 细点），`nodes[]` 平铺、靠 `parent` 串；不要在文件里嵌套 children，`build_graph.py:96` 只读 `n['parent']`。
