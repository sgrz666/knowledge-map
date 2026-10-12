# docs/superpowers/ —— writing-plans / executing-plans 流程留下的计划与设计稿存放处

本目录收纳"先写 spec 定范围、再写 plan 拆步骤、最后逐任务执行并勾选"这条工作流的两个产物子目录：`specs/`（设计稿：锁定范围、改动边界、验收口径）与 `plans/`（实施计划：任务分解 + 验收步骤 + 追加任务台账）。目前只沉淀了一轮交付（2026-10-11 网页端备考智能体），历史不删除、不回改，新会话接手先读这里的 plan 再动代码。
执行时的规则来自 plan 头部声明：用 executing-plans 在当前会话逐项执行；计数与证据不写回 plan 正文，统一指向 `docs/web_agent_verification.md` 与 `docs/教资完整性与网页端交付报告.md`。

## 文件清单

- `plans/` —— 一轮实施一个 `YYYY-MM-DD-<主题>.md`，见 `plans/README.md`。
- `specs/` —— 一轮设计一个 `YYYY-MM-DD-<主题>-design.md`，见 `specs/README.md`。

## 改这里之前要知道的

- plan 里的复选框是执行台账，勾与不勾代表当时会话做到哪一步；后续会话补做不回改历史行，只追加"接手后追加的任务"一节（现有文件就是这么长的）。
- plan/spec 里落库路径引用的是真实目录（`数据集/教资/…`），不是 `教资`/`权威资料` Junction 别名；写文件必须走真实路径（别名口径见根 README 与 `tests/test_workspace_aliases.py`）。
