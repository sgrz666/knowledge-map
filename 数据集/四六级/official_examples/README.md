# 数据集/四六级/official_examples/ —— 大纲官方样卷的随库参考页图（非抽取产物本体），手放置、无脚本读写，权威件在 补充资料/四六级官方样题/

- 角色：只放一张《四六级考试大纲（2016 修订版）》官方样卷起始页（第 150 页）的渲染图，作为随四六级库交付的视觉参照；不存题目、答案或抽取数据。
- 生成：无脚本生成。图片随提交 `cf519280`（"四六级库产物入库"）一起手放入，路径未被任何 `scripts/` 或 `kb_tools/` 的写出逻辑引用。
- 权威抽取件在别处：官方样卷的结构化产物（`questions.jsonl` 114 题、`official_examples.jsonl`、`passages.jsonl` 23 篇、逐页 `page.150.png…page.211.png` 等）全部在 `补充资料/四六级官方样题/`，由 `kb_tools/cet_official_examples.py`（读 `权威资料/originals/cet.syllabus.2016.pdf`、写 `OUTPUT_REL=补充资料/四六级官方样题`）生成。本目录那张 `cet-syllabus-p150.png` 与 `补充资料/…/page.150.png` 是同一页大纲样卷的图像，本目录只留一页做索引参照。
- 消费：`tests/test_cet_official_examples.py` 与 `审查/validate_kb.py` 读的都是 `补充资料/四六级官方样题/`，不读本目录；本目录图片仅供人查阅，运行时 `services/knowledge/` 不加载。

## 文件清单

- `pages/`（1 个文件）—— 官方大纲样卷页图子目录，见 `pages/README.md`。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- 别把本目录当官方样题数据源：题目/答案/语篇的抽取、哈希、页定位都在 `补充资料/四六级官方样题/`，重跑 `kb_tools/cet_official_examples.py` 才更新；改本目录图片不会影响任何门禁。
- 门禁读的是 补充资料 路径下的 `questions.jsonl`（`审查/validate_kb.py` 第 919–939 行按 `cet_official_examples` 单列计数），本目录文件不在其扫描范围。
