# 数据集/四六级/exam_guide/ —— 四六级考试说明散文，手维护、无脚本生成，学习 Agent 问答消费，无专属门禁

- 角色：给人/学习 Agent 读的"考试怎么考"说明，不含可判分事实；分值结构、题量、时长等口径的权威源是 `ontology/exam_tree.json`（同为手维护，无写入脚本），本文只做人类可读转述。
- 生成：无。`scripts/` 下没有任何脚本写 `cet_overview.md`（全库 grep `cet_overview` 无写入点）；手改即生效，无重生成命令。
- 消费：学习/问答 Agent 检索本目录回答考试规则类问题；`services/knowledge/` 不直接读它（repository/vector_index 均无 exam_guide 路径）。
- 门禁：`tests/test_cet_*`、`审查/validate_kb.py`、`tests/test_status_vocabulary.py` 均不解析本文件——改动不需跑门禁，但分值/占比若与 `ontology/exam_tree.json` 不一致属内容错误，需人工对齐（现有两处一致：写作 15% 30min、听力 35% 25/30min、阅读 35% 40min、翻译 15% 30min，总分 710）。

## 文件清单

- `cet_overview.md`（2342B, 33L）—— 考试概览：710 分制与 425 通过线、130 分钟流程（写作→听力→阅读+翻译）、四模块占比/分值/时长/题量表、题型说明（选词填空 26–35、长篇阅读 36–45、仔细阅读 46–55、听力播一遍、段落汉译英）、评分档次（14/11/8/5/2 分档）、卷次说明（多套卷听力共用、经 `papers.jsonl` 的 `listening_ref` 指向同场次含听力卷）。手维护，可直接编辑；命名固定，无重生成脚本。被 `ontology/exam_tree.json` 的口径引用（反向：本文转述 exam_tree）。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- 本目录是散文说明，不是数据源：任何"题量/分值/通过率"数字都应先改 `ontology/exam_tree.json` 再同步本文，否则两份会漂移且没有门禁拦截。
- 不要在这里放真题、答案或词汇表——那些分别归 questions/、vocabulary/、writing/、translation/，且都是脚本产物。
