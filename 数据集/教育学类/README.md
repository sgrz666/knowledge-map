# 数据集/教育学类/ —— 国家高等教育智慧教育平台教育学门类抓取快照，外部抓取脚本生成（脚本不在本仓库），暂无任何消费方

本目录与交付库 `数据集/四六级/` 无关：四六级知识库 `questions/**.jsonl` 及全库 `source` 字段中没有任何路径指向这里（全仓库 grep 仅 `审查/_scan_big_files.py` 把本目录文件列入凭据扫描名单）。这里存的是 2026-09-09 从 higher.smartedu.cn 抓取的两份 JSON 快照，属"备用教学数据"，尚未建库、尚未消费。抓取脚本未入本仓库（仓库内无 smartedu/chinaooc 抓取代码），入库记录见提交 c77ce274「课程目录数据集入库：计算机类与教育学类全量抓取结果」。

## 文件清单
- `education_courses_教育学_全量课程_pretty.json`（79,233,311 字节，75.6MB）— 教育学门类全量课程明细。顶层 `meta` + `courses`；`courses` 共 1457 条课程记录。来源：国家高等教育智慧教育平台 higher.smartedu.cn，课程接口 api.chinaooc.com.cn/api/v1，过滤条件 classInfo=教育学，抓取日期 2026-09-09。每条记录字段：course_id、title、platform、course_url、cover_url、colleges、host_teacher、teachers、subject、level、flags、state、schedule、enrollment、intro、outline、update_date，另保留 raw_list/raw_detail 原始响应；`meta.stats.field_coverage` 记录逐字段填充率（如 outline 1451/1457，colleges 1404/1457）。未被引用，仅作来源留存。
- `smartedu_books_教育学类_三板块全量.json`（984,727 字节，961.6KB）— 教育学类三板块教材清单。顶层 `meta` + `textbooks`；`textbooks` 共 18 条。来源：higher.smartedu.cn/books 教材板块，板块构成：马克思主义理论研究和建设工程重点教材 5、首届全国教材建设奖·全国优秀教材 12、国外优秀教材 1。每条字段：type、subject、section、id、title、subtitle、authors、organization、publisher、isbn、edition、publish_date、price、pages、words_thousand、education_level、subject_category、key_project、keywords、cover_url、toc_html、toc_text、preface_ref、detail_url、sample_chapter；`meta.field_coverage_by_section` 按板块记录填充率。未被引用，仅作来源留存。

消费状态：两份文件目前只被 `审查/_scan_big_files.py`（超 8MB 快照的凭据扫描，只读）列出，检索/出题/RAG 链路均未接入。
