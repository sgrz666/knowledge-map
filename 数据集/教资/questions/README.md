# 教资KB/questions — 结构化试题库（轨 A）

本目录包含全量 14,500 道 NTCE 试题的结构化 JSONL 数据文件，按学段与科目组织。

## 数据特点
- 一行一道题，严格符合 [schemas/question.json](../schemas/question.json) 规范。
- 绑定知识点（knowledge_node_ids）、能力（bility_ids）、大纲要求（exam_requirement_ids）与评分量规（
ubric_id）。
- 绝不伪造 IRT 难度校准值（均附带 difficulty_meta）。

## 子目录学段分布
- **youer/**：幼儿保教与综合素质试题。
- **xiaoxue/**：小学教育教学与综合素质试题。
- **chuzhong/**：初中各学科与公共科目试题。
- **gaozhong/**：高中各学科与公共科目试题。
- **zhongxue/**：中学共用公共科目试题。
- **zhongxiaoxue/**：中小学面试试题。
