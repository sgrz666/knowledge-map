# 数据集/四六级/writing/md/ —— 写作模板的人读镜像（单个 templates.md），build_templates.py 连带写出，仅供人看、无脚本消费

- 角色：`writing/templates.jsonl` 的人类可读投影（Markdown），不是独立事实源；检索/图谱走的是同目录上级的 `templates.jsonl`。
- 生成：`scripts/build_templates.py`（第 129 行 `(KB/'writing'/'md'/'templates.md').write_text(...)`，与 `templates.jsonl` 同批写出）。改内容要重跑该脚本，不手改本 md（会被覆盖）。
- 消费：仅人阅读与编辑器预览；`services/knowledge/`、`scripts/build_graph.py`、`审查/` 均不解析本文件（grep `templates.md` 无读取点）。
- 门禁：无专属门禁；其一致性由 `templates.jsonl` 的 `tests/test_cet_repair.py` 间接保证（两者同一次 build_templates.py 运行写出）。

## 文件清单

- `templates.md`（14414B, 152L）—— 6 个 H2 章、33 个 H3 句型小节、69 条 bullet（与 `../templates.jsonl` 的 69 条一一对应，如"名言警句类破题句""漫画类描述图画句""表达不同观点万能句"）。首行标注"检索版见 writing/templates.jsonl"，明确本文件是人读镜像。命名固定 `templates.md`，由 build_templates.py 重生成，不手改。
- `README.md`（本文件）—— 手维护说明。

## 改这里之前要知道的

- 这是 build_templates.py 的产物：任何在此手加的句型都不会进 `templates.jsonl`，也不会进图谱 L7，重跑即被抹掉。要真正加模板，应改源 docx/PDF 与 build_templates.py 解析。
- 本目录只有这一个数据文件，别在此新建其它文件。
