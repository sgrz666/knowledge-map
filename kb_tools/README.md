# kb_tools — 教资知识库处理工具链

本目录包含维护、清洗、修复、构建与验证 教资KB 所需的全套 Python 脚本（共29个工具）。

## 工具分类与核心脚本

### 1. 核心修复与构建管线
- **
tce_repair.py**：全量修复核心流水线（清洗大纲、对齐题型、修复材料关联、更新量规与卡片）。
- **uild_kb.py**：从原始 CSV 解析并生成 questions.jsonl 与 cards/*.md。
- **uild_graph.py**：构建八层知识图谱，生成 
odes.jsonl 与 edges.jsonl。

### 2. 验证与一致性校验
- **
tce_verify.py**：全库结构校验与双次复跑哈希幂等性检验（--check-idempotence）。
- **
tce_io.py**：原子文件安全写入与 JSONL 物理行读写封装。

### 3. 解析与选项处理
- **
tce_analysis_fill.py** / **
tce_analysis_chain_fix.py**：三段式解析结构化填充与修复。
- **
tce_option_compare.py**：选择题逐项对比解析生成。
- **
tce_material_repair.py** / **
tce_type_repair.py**：长材料边界切分与题型归一修复。

### 4. 考纲对齐与本体管理
- **
tce_ontology.py**：考纲细粒度考点树生成与映射。
- **
tce_rubric_points.py**：主观题评分要点提取。
- **
tce_difficulty.py**：启发式（heuristic）难度估算标注。
- **
tce_copyright_scope.py**：版权使用范围与来源性质标注。

### 5. 审计与大模型批处理
- **
tce_source_audit.py** / **
tce_llm_audit.py**：来源真实性核验与模型初标审计。
- **llm_batch.py**：大语言模型批量推理调用工具。
