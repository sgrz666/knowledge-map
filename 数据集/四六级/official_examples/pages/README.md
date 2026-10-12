# 数据集/四六级/official_examples/pages/ —— 大纲官方样卷的单页参考图（仅 cet-syllabus-p150.png），手放置、无脚本读写

- 角色：`official_examples/` 下的页图子目录，只装一张《考试大纲（2016 修订版）》样卷起始页的渲染图，供人对照；不是抽取管线输出。
- 生成/消费：无脚本写入或读取本目录（全库 grep 无 `official_examples/pages` 引用）。官方样卷的逐页图与结构化数据在 `补充资料/四六级官方样题/`（`page.150.png`…`page.211.png`），由 `kb_tools/cet_official_examples.py` 生成。
- 门禁：无（`tests/test_cet_official_examples.py` 与 `审查/validate_kb.py` 均指向 补充资料 路径）。

## 文件清单

- `cet-syllabus-p150.png`（119956B，PNG 880×1207 RGB）—— 大纲样卷第 150 页（PDF 页 150、印刷页约 145）的页面渲染图，是四级笔试样卷正文起始页。随提交 `cf519280` 手放入并入库；不手改（改了无脚本重生成、也不被校验）。命名规律 `cet-syllabus-p{页码}.png`，当前仅此一张。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- 这是孤立参照图，不是数据源：新增页图请去 `补充资料/四六级官方样题/`（那里有全套 62 页与 PDF 哈希边界校验），本目录不放题目也不放答案。
