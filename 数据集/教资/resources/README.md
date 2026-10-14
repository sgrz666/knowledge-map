# 教资KB/resources — L7 学习资源库

本目录存放辅导学习专用的核心理论、现行法规、面试模型结构化数据，以及无题考点的学习指南草稿。目录内每个 `.jsonl` 都是 L7 资源源文件：`kb_tools/build_graph.py` 会把每条记录导出成 L7 节点，并按 `knowledge_node_ids` / `ability_ids` / `exam_requirement_ids` 连出 `supplements_resource` / `supports_resource` / `aligned_to_requirement` 边，所以每行必须携带 `resource_id`、`title` 与 `copyright.use_scope = research_non_commercial`（由 `tests/test_ntce_hierarchy_contract.py` 钉住）。

## 核心文件
- **pedagogical_theories.jsonl**：教育学与心理学重要流派（皮亚杰、维果茨基、埃里克森等）理论卡片。
- **legal_frameworks.jsonl**：现行教育法律法规（学前教育法2025、未保法2024、教师法等）重点条文对照。
- **interview_scenarios.jsonl**：中小学面试高频情境与应对策略。
- **study_guides.jsonl**：无题叶子考点的原创讲解草稿（`type = study_guide`，`resource_id` 形如 `ntce.res.guide.<学段>_<科目>_<节>_<考点>`）。内容含概念讲解、学科情境、作答结构与自测题；每行 `content_status = original_research_draft`、`review.status = needs_fix`、审核人为空、`formal_question_pool_eligible = false`，自测题的 `answer_status = research_draft` 且不带 `question_id` 与分值——它们是研究草稿，不是真题，也不进题池。消费方须同时展示行内 `notice`。7 个叶子考点各 1 条、共 14 道自测题（初中历史/生物/体育/信息技术/物理、高中物理/音乐），2026-10-12 由 `审查/_append_study_guides.py` 补齐最后 4 条；引用条款以库内 requirement 记录为准，原创部分仍待教研复核。
