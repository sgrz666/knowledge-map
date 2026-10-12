# 数据集/计算机类/ —— 智慧教育平台计算机类抓取快照（课程/教材/101计划/AI专区），外部脚本生成，暂无消费方

与交付库 `数据集/四六级/` 无关：四六级知识库 `source` 字段无路径指向这里（全仓库检索仅 `审查/_scan_big_files.py` 引用其中 2 个文件做凭据扫描）。抓取日期均为 2026-09-09，抓取脚本不在仓库内；入库记录见提交 c77ce274。

## 文件清单
- `computer_courses_工学_计算机类_全量课程_pretty.json`（94,937,468 字节，90.5MB）— 工学-计算机类全量课程明细，`meta` + `courses`（1679 条）。来源 higher.smartedu.cn（api.chinaooc.com.cn/api/v1），filter classInfo=工学、subject=计算机类。字段与教育学类课程快照同构（course_id/title/platform/…/raw_list/raw_detail）。入库口径：本文件是目录内最大单文件（90.5MB），以 94,937,468 字节原始 blob 直接提交进 git 树（`git ls-files -s` 为普通 100644 对象；`git lfs ls-files` 全库只有 `补充资料/` 下 2 个 0 字节 recovery_patches.jsonl 走 LFS），即未经 Git LFS。它被 `审查/_scan_big_files.py`（对超 8MB 阈值快照做凭据扫描，只读）列入名单。未被题面引用，仅作来源留存。
- `p101_计算机科学_四类资源全量.json`（1,104,191 字节，1.1MB）— 国家智慧教育平台「101 计划」计算机科学与技术资源专区全量：`meta/overview/report/qa/courses/textbooks/projects/departments`，计数 courses 15、textbooks 20、projects 36、departments 13，合计 84 条资源。未被题面引用，仅作来源留存。
- `smartedu_books_工学_计算机类_全量教材.json`（531,897 字节，519.4KB）— 工学-计算机类教材清单，`meta` + `books`（35 条）：首届全国教材建设奖 19 本（核心 B0809 计算机类 16 + 相关 3，一等 6/二等 13）+ 国外优秀教材 16 本。来源 smartedu.tbook.com.cn（bookData.json 全量 458 条目录 + 详情页）与 api.chinaooc.com.cn /api/v2/Book/search（学科代码 0812）。未被题面引用，仅作来源留存。
- `topic_courses_计算机人工智能_全量.json`（9,722,543 字节，9.3MB）— 高校专业/职业本科/AI 专区计算机人工智能课程合集，`meta` + `courses`（316 条），`meta.section_stats` 按 9 个板块给出条数（如高校专业专业课课程群 91、AI 通识课程群 99）。未被题面引用，仅作来源留存。

消费状态：4 份 JSON 均未接入知识库或检索链路；只有 `审查/_scan_big_files.py` 把 computer_courses_工学_计算机类_全量课程_pretty.json 与 topic_courses_计算机人工智能_全量.json 列入超阈值快照凭据扫描名单（只读）。
