# 知识库短板补齐工作流与实施计划 (Agent Workflow Plan)

> **任务目标**：全面补齐四六级（CET）与教资（NTCE）知识库的系统性短板，彻底打通 RAG 轨 B、多模态音频切片、写译模块统一、L7 模考蓝图及知识图谱认知诊断链。

## 1. 任务分解与执行顺序 (Task Decomposition & Sequencing)

| 阶段 | 子任务编号 | 子任务名称 | 依赖前序 | 交付成果 | 验证机制 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **阶段 1** | T1.1 | 四六级轨 B（RAG 卡片）批处理生成脚本编写与执行 | 无 | `数据集/四六级/cards/` (5,340 题卡片) | 卡片数量核对 = 5,340，Frontmatter 格式校验 |
| **阶段 1** | T1.2 | 四六级写作与翻译题型数据统一规整与入库 | 无 | `数据集/四六级/questions/` 增加写译题目 | 题目 ID 唯一性校验，Schema 校验 |
| **阶段 2** | T2.1 | L7 卷级编排与模考规格元数据（PaperSpecification）构建 | T1.2 | `数据集/四六级/manifest/paper_specs.jsonl` 及 `教资KB/paper_specs.jsonl` | 模考规格字段覆盖率、710分换算与计时锁校验 |
| **阶段 2** | T2.2 | 听力多模态音频媒体资产（L5）扫描与时间戳结构对齐 | 无 | 题目 `extra.audio` 挂载相对音频文件与时间切片 | 120 套音频索引建立，1,969 听力题关联校验 |
| **阶段 3** | T3.1 | L1 知识图谱扩展：考纲词汇关联与认知诊断边补充 | T1.1 | `ontology/edges.jsonl` 及 `knowledge_nodes.jsonl` | 图谱孤岛检测、`prerequisite_of` / `confused_with` 边增量统计 |
| **阶段 4** | T4.1 | 综合回归测试与质量门禁审计 | T1.1-T3.1 | 单元测试、合约测试与形式审查报告 | 197+ 项测试通过、0 悬空节点通过 |

## 2. 详细工件交互 (Handoff Points)
- **T1.1 -> T4.1**：`数据集/四六级/cards/` 中的 Markdown 卡片供 RAG 索引与向量检索评测验证。
- **T1.2 -> T2.1**：规整后的统一写作与翻译题元，作为 L7 套卷（PaperSpecification）的 Part I 与 Part IV 构成项。
- **T2.2 -> T4.1**：更新后的 `listening/transcripts.jsonl` 与听力题 `audio_ref`。
- **T3.1 -> T4.1**：图谱边关系更新到 `ontology/edges.jsonl`，确保形式审查脚本 `审查/知识库形式审查.py` 验证 0 孤岛。
