# 主观题 question_specific_points 生成 · 验证报告

工具：`kb_tools/ntce_rubric_points.py`（遵循 `ntce_repair.py` / `ntce_io.py` 风格：原子替换写入）。
执行日期：2026-10-07。Python：`C:\Users\sg\.workbuddy\binaries\python\versions\3.13.12\python.exe -X utf8`。

## 1. 生成数量（权威计数，按写入标记 `question_specific_points_meta.generated_by` 统计）

| 题型 | 计划/实测应有 | 当前带本工具标记 | 说明 |
|------|--------------|----------------|------|
| 简答 | 1075 | 1075 | 完整 |
| 材料分析 | 992 | 991 | 1 题被并发写入覆盖（见第 5 节） |
| 教学设计 | 515 | 513 | 2 题被并发写入覆盖 |
| **合计** | **2582** | **2579** | 缺 3 题系外部覆盖，非本工具丢失 |

另有 **6 道 `论述` 题**带 `question_specific_points` 但**无本工具标记** —— 属既有 19 道人工/原有点集，`论述` 不在本次目标题型内，已正确跳过、未覆盖。

每题评分点数（均值）：简答 5.42、材料分析 8.23、教学设计 6.05；本工具累计写入约 17,100 个评分点。
**五维覆盖：2582 道全部覆盖** `要点覆盖 / 理论运用 / 逻辑结构 / 语言表达 / 规范性` 五维（缺维时由 `ensure_dimension_coverage` 补全通用要求）。

## 2. 评分点结构

每个评分点对象：
```
{
  "point_id": "<question_id>__p<NN>",     // 稳定可重放
  "primary_dimension": "要点覆盖",         // 五维之一
  "importance": "核心|重要|一般",           // 类别权重，非数值分值
  "point": "……具体要做到的要点……",
  "generation_method": "stem_structure_and_template",
  "basis": "依据题干第(1)问……；框架推导，非官方答案。",
  "expert_verified": false
}
```
题级元信息 `question_specific_points_meta`：
```
{ generated_by, generation_method, version,
  note: "AI辅助生成的练习建议评分点：依据题干子问题结构与教资通用答题框架推导，非官方评分标准，未经学科专家核定。",
  official_scoring: false,
  covers_dimensions: [五维],
  source_strength: "template_derived_no_official_source",
  point_count }
```

## 3. 抽样完整例子

### (a) 材料分析 · `ntce.chuzhong.dili.2014a-jx-k2.q27`
- [理论运用/核心] 准确运用本题所涉理论评析第(1)问情境（如学科原理、素质教育观、学生观、教学原则、德育原则等，依材料主题判定），完整、规范地陈述理论要点。
- [要点覆盖/核心] 紧扣第(1)问「描述……太平洋垃圾漩涡的大体位置和流动方向……」，结合所给材料具体细节作答，理论观点与材料情境事理对应。
- [理论运用/核心] 第(2)问同上结构（试分析危害与措施）。
- [要点覆盖/核心] 第(2)问同上结构。
- [逻辑结构/重要] 整体按「理论观点→材料印证→分析评价」层层展开。
- [要点覆盖/重要] 给出评价结论或教育启示/改进建议（总结提升）。
- [语言表达/一般] 规范术语，准确连贯。
- [规范性/一般] 格式与学术规范，分条标号清晰。

### (b) 教学设计 · `ntce.chuzhong.dili.2014a-jx-k2.q30`
- [要点覆盖/核心] 设计完整教学过程（情境导入→新知探究/讲授→巩固练习→小结→作业），师生活动具体，体现学生主体。
- [理论运用/重要] 设计体现先进教育理念（学生主体、探究学习、学科育人），与目标/过程一致。
- [逻辑结构/重要] 各环节目标—活动—评价一致，时间分配合理。
- [语言表达/一般] 规范术语。
- [规范性/一般] 格式规范。

### (c) 简答 · `ntce.chuzhong.dili.2014a-jx-k2.q25`
- [要点覆盖/核心] 针对本题「简述对《义务教育地理课程标准》中‘选择多种多样的地理教学方式方法’……」，列出关键要点并简要展开，无遗漏。
- [理论运用/重要] 必要时援引相关教育理论/法规支撑要点。
- [逻辑结构/一般] 要点按逻辑顺序组织，分条清晰。
- [语言表达/一般] 规范术语。
- [规范性/一般] 格式规范。

## 4. 依据强度（诚实说明）

- 评分点**来源 = 题干子问题结构（(1)(2)…/整题）+ 教资通用答题框架**（材料分析「理论+材料+总结」、教学设计「目标/重难点/过程/板书」）。
- **不是官方标准答案**，不指向任何官方文件，`basis` 字段均标注「非官方答案/模板推导」；**未伪造 `locator`**。
- **无任何数值权重/分值**：仅用「核心/重要/一般」类别标记；`official_scoring=false`、`expert_verified=false`，符合 README 第 29、33 行关于「模型输出不能标成官方标准答案」「评分点无正式权重，不能直接换算成绩」的约束。
- 与 `rubrics/official_interview.json`（面试 61 项官方指标）**无关**：未借用其 `weight/score`，亦未套用到单题。

## 5. 验证结果

- **幂等性（本工具）**：评分点由题干结构确定性推导；对同一题重复 `process()` 输出逐字节一致，不累积、不破坏。✔
- **与 `ntce_repair.py` 兼容**：`practice_rubric()`（第 359–369 行）用 `setdefault` 填充 `question_specific_points` 默认 `[]`。**实测**（`practice_rubric` 连续调用两次）确认：已存在的非空 `question_specific_points` 与 `question_specific_points_meta` 均被保留，`official_scoring`/`expert_verified` 保持 `false`，未发明权重/分值。✔
- **全库双跑复算（`ntce_repair.py --skip-outline` ×2）**：**暂缓**。原因见第 6 节——当前存在并发写入，全量复算会崩溃或丢失更新。

## 6. 与现有工具链的不兼容 / 风险发现（须协调）

1. **同文件并发冲突（已观察到）**：与 `difficulty-calibrator` 并行处理难度标定，双方改写同一批 `教资KB/questions/*/*/*.jsonl`。实测发现 3 道（材料分析 1 + 教学设计 2）题的 `rubric` 字段被对方 read-modify-write 覆盖丢失——本工具计数 2582 但在库仅 2579 带本标记，缺口与 `材料分析/教学设计` 下降量一致；`论述` 6 道原有点集未被触碰（符合预期）。
2. **结论**：本工具安全（只写 `rubric.question_specific_points` 及元信息，绝不碰 `difficulty`、绝不碰客观题），但**全量 `ntce_repair --skip-outline` 当前不可安全运行**——并发写入会令读取偶发 `JSONDecodeError`（已多次捕获未终止 JSON/PermissionError），且 read-modify-write 存在互丢更新风险。
3. **建议执行顺序**（解决后请按此收尾）：
   - (a) `difficulty-calibrator` 完成/暂停其写入，并其重写须保留整条 `rubric` 对象；
   - (b) 本工具**幂等重跑一次** → 自动恢复被覆盖的 3 题评分点，回到 2582；
   - (c) 再 `ntce_repair.py --skip-outline` 连跑两次，确认 `question_specific_points` 不丢（届时无并发写入即可稳定验证）。

## 7. 约束遵守核对
- 只读不写人工审核：`manually_reviewed(rubric)`（checked_by/expert_verified）时跳过，未覆盖任何人工数据。✔
- 只写主观题：客观题（单选/多选/未标注）一律 `continue`。✔
- 不碰 `difficulty`、不碰 `questions/` 以外文件。✔
- 不伪造来源定位（无 `locator` 指向不存在文件）。✔
