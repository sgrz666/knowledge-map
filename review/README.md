# review/ —— 这个目录放什么、谁来用

空目录、无版本化内容、疑似早期人工复核入口遗留，当前运行时的复核队列在 `.local_state/review_queue/` 与 `services/review/`。
本 README 之前，这里 0 个文件；git 里也从未有过这个目录的任何历史。

## 文件清单

- `README.md` —— 本说明文件。除它以外目录为空。

## 核查过程（本目录为何判定为遗留）

- `git log --diff-filter=A -- review`：无输出（从未有文件在此目录被添加）。
- `git log -- review`：无输出。
- `git ls-files review`：无输出（当前无任何已跟踪文件）。
- `git check-ignore review`：不匹配（不在 `.gitignore` 名单里——它只是空，而不是被排除；Git 不跟踪空目录，所以它在版本历史中完全不存在）。
- 目录 mtime 2026-10-08 18:25，与当天四六级修复操作同一时段。

## 改这里之前要知道的

- 复核数据现在住两个地方，不要新建到这里：运行时降级记录（append-only JSONL，按缺陷码分桶）在 `.local_state/review_queue/`，由 `services/review/queue.py` 写；静态审计与人工待办的清单文档是 `审查/待复核清单.md`，由 `审查/build_review_queue.py` 生成，不要手改。
- 根 `README.md` 把复核队列职责记在 `services/review/`，与本目录无关；引用文档里没有一处指向 `review/`。
