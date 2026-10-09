# tests — 自动化测试套件

本目录存放知识库数据质量、结构合规性与功能回归的自动化测试用例。

## 测试文件清单
- **	est_ntce_hierarchy_contract.py**：八层数据分级（L0–L7）拓扑完整性、Draft 2020-12 Schema 强约束与 Markdown 卡片契约测试。
- **	est_ntce_repair.py**：教资数据修复行为回归测试（材料关联、防截断、冲突隔离）。
- **	est_kb_contract.py**：全库统一知识库数据门禁测试（64项通用违规规则断言）。
- **	est_official_examples.py**：官方样卷提取与正文一致性回归。
- **	est_cet_official_examples.py**：四六级官方样卷及分档评分标准回归。
- **	est_cet_repair.py** / **	est_cet_passage_references.py**：四六级语篇双向引用与题组绑定回归。
