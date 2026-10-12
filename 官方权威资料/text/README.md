# 官方权威资料/text/ —— 官方原件的抽取纯文本与 Word 表格 JSON；由 extract_word.ps1 和 collect_sources.py 生成，被 requirements.jsonl 的 locator 与两库节点/题目消费

115 个数据文件 = 67 个 `.txt`（每个来源一份正文）+ 48 个 `.tables.json`（48 份 Word 原件的表格单元格原文，与 Word 一一对应）。`requirements.jsonl` 中 2,435 条条款的 `locator.text_path` 和 61 条面试细则的 `locator.table_path` 以写死前缀 `权威资料/text/` 指到这里——`权威资料` 是工作区根指向 `官方权威资料` 的符号链接，本 README 及清单内文只写真实目录名，但读 locator/脚本时看到的前缀就是 `权威资料/`。这里入库进检索面：`数据集/四六级/graph/nodes.jsonl`、`ontology/*.jsonl` 等直接引用 `权威资料/text/cet.syllabus.2016.txt`、`cet.score.interpretation.txt`、`cse.gf0018-2018.txt` 的行定位。逐文件对应哪个官方来源、URL、抽取方式与 locator 引用数见下表（引用数为 requirements.jsonl 现算）。

## 文件清单（115 个，按文件名排序）

| 文件名 | 对应官方来源（版本） | 来源 URL | 被 requirements.jsonl 引用情况 |
| --- | --- | --- | --- |
| `cet.content.cet4.txt` | 全国大学英语四级笔试（CET4）考核内容 | https://cet.neea.edu.cn/xhtml1/report/16123/196-1.htm | 不经 text 引用：该来源 9 条条款的 locator.html_path 直接指 originals/cet.content.cet4.html |
| `cet.content.cet6.txt` | 全国大学英语六级笔试（CET6）考核内容 | https://cet.neea.edu.cn/xhtml1/report/16123/201-1.htm | 不经 text 引用：该来源 9 条条款的 locator.html_path 直接指 originals/cet.content.cet6.html |
| `cet.score.interpretation.txt` | CET笔试分数解释 | https://cet.neea.edu.cn/xhtml1/folder/19081/5124-1.htm | locator.text_path 引用 4 条 |
| `cet.syllabus.2016.txt` | 全国大学英语四、六级考试大纲（2016年修订版）（2016年修订版） | https://cet.neea.edu.cn/res/Home/1704/55b02330ac17274664f06d9d3db8249d.pdf | locator.text_path 引用 87 条 |
| `cse.gf0018-2018.txt` | 中国英语能力等级量表（GF 0018—2018）（GF 0018—2018） | https://www.moe.gov.cn/jyb_sjzl/ziliao/A19/201807/W020180725662475781772.pdf | locator.text_path 引用 145 条 |
| `cse.gf0018-2024.txt` | 中国英语能力等级量表（GF 0018—2024）官方描述语数据集（GF 0018—2024） | https://www.neea.edu.cn/api/dict/ability.json | 不经 text 引用：3,741 条条款的 locator.json_path 指 originals/cse.gf0018-2024.json，本 txt 是同数据的缩进整理副本 |
| `evidence.gbt41671-2022.txt` | GB/T 41671-2022对应化学纤维溶剂残留量测定（CSE错误编号纠正证据）（GB/T 41671—2022） | https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=539A94752F8764D4E765BC5930B11004 | 无条款：纠正证据存档，该 standard_id 在 requirements.jsonl 中 0 条，仅参与哈希核验 |
| `law.compulsory.2018.txt` | 中华人民共和国义务教育法（2018年修正）（2018年12月29日第二次修正） | https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/202110/t20211029_575949.html | locator.text_path 引用 64 条 |
| `law.education.2021.txt` | 中华人民共和国教育法（2021年修正）（2021年4月29日第三次修正） | https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/202107/t20210730_547843.html | locator.text_path 引用 87 条 |
| `law.juvenile_prevention.2020.txt` | 中华人民共和国预防未成年人犯罪法（2020年修订）（2020年12月26日修订） | https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_qtxgfl/202110/t20211025_574843.html | locator.text_path 引用 69 条 |
| `law.minors.2024.txt` | 中华人民共和国未成年人保护法（2024年修正）（2024年4月26日第二次修正） | https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_54358c05e57642ab895176413f7cd4d7.html | locator.text_path 引用 124 条 |
| `law.preschool.2024.txt` | 中华人民共和国学前教育法（2024年11月8日通过） | https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/202411/t20241108_1161363.html | locator.text_path 引用 86 条 |
| `law.teacher.2009.txt` | 中华人民共和国教师法（2009年修正）（2009年8月27日修正） | https://www.moe.gov.cn/jyb_sjzl/sjzl_zcfg/zcfg_jyfl/tnull_1314.html | locator.text_path 引用 44 条 |
| `ntce.interview.xiaoxue.tables.json` | 中小学和幼儿园教师资格考试面试大纲(试行)--小学（试行（原文署二〇一二年五月）） | https://ntce.neea.edu.cn/xhtml1/report/1508/379-1.htm | locator.table_path 引用 23 条 |
| `ntce.interview.xiaoxue.txt` | 中小学和幼儿园教师资格考试面试大纲(试行)--小学（试行（原文署二〇一二年五月）） | https://ntce.neea.edu.cn/xhtml1/report/1508/379-1.htm | locator.text_path 引用 23 条 |
| `ntce.interview.youeryuan.tables.json` | 中小学和幼儿园教师资格考试面试大纲(试行)--幼儿园（试行（原文署二〇一二年五月）） | https://ntce.neea.edu.cn/xhtml1/report/1508/381-1.htm | locator.table_path 引用 16 条 |
| `ntce.interview.youeryuan.txt` | 中小学和幼儿园教师资格考试面试大纲(试行)--幼儿园（试行（原文署二〇一二年五月）） | https://ntce.neea.edu.cn/xhtml1/report/1508/381-1.htm | locator.text_path 引用 16 条 |
| `ntce.interview.zhongxue.tables.json` | 中小学和幼儿园教师资格考试面试大纲(试行)--中学（试行（原文署二〇一二年五月）） | https://ntce.neea.edu.cn/xhtml1/report/1508/377-1.htm | locator.table_path 引用 22 条 |
| `ntce.interview.zhongxue.txt` | 中小学和幼儿园教师资格考试面试大纲(试行)--中学（试行（原文署二〇一二年五月）） | https://ntce.neea.edu.cn/xhtml1/report/1508/377-1.htm | locator.text_path 引用 25 条 |
| `ntce.outline.101.tables.json` | 101-《综合素质》（幼儿园） | https://ntce.neea.edu.cn/xhtml1/report/1508/334-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.101.txt` | 101-《综合素质》（幼儿园） | https://ntce.neea.edu.cn/xhtml1/report/1508/334-1.htm | locator.text_path 引用 43 条 |
| `ntce.outline.102.tables.json` | 102-《保教知识与能力》(幼儿园） | https://ntce.neea.edu.cn/xhtml1/report/1508/330-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.102.txt` | 102-《保教知识与能力》(幼儿园） | https://ntce.neea.edu.cn/xhtml1/report/1508/330-1.htm | locator.text_path 引用 39 条 |
| `ntce.outline.201.tables.json` | 201-《综合素质》（小学） | https://ntce.neea.edu.cn/xhtml1/report/1508/337-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.201.txt` | 201-《综合素质》（小学） | https://ntce.neea.edu.cn/xhtml1/report/1508/337-1.htm | locator.text_path 引用 48 条 |
| `ntce.outline.202.tables.json` | 202-《教育教学知识与能力》（小学） | https://ntce.neea.edu.cn/xhtml1/report/1508/339-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.202.txt` | 202-《教育教学知识与能力》（小学） | https://ntce.neea.edu.cn/xhtml1/report/1508/339-1.htm | locator.text_path 引用 46 条 |
| `ntce.outline.301.tables.json` | 301-《综合素质》（中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/341-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.301.txt` | 301-《综合素质》（中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/341-1.htm | locator.text_path 引用 50 条 |
| `ntce.outline.302.tables.json` | 302-《教育知识与能力》（中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/343-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.302.txt` | 302-《教育知识与能力》（中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/343-1.htm | locator.text_path 引用 47 条 |
| `ntce.outline.303.tables.json` | 303-《语文学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/345-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.303.txt` | 303-《语文学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/345-1.htm | locator.text_path 引用 29 条 |
| `ntce.outline.304.tables.json` | 304-《数学学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/347-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.304.txt` | 304-《数学学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/347-1.htm | locator.text_path 引用 23 条 |
| `ntce.outline.305.tables.json` | 305-《英语学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/349-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.305.txt` | 305-《英语学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/349-1.htm | locator.text_path 引用 21 条 |
| `ntce.outline.306.tables.json` | 306-《物理学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/351-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.306.txt` | 306-《物理学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/351-1.htm | locator.text_path 引用 24 条 |
| `ntce.outline.307.tables.json` | 307-《化学学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/353-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.307.txt` | 307-《化学学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/353-1.htm | locator.text_path 引用 32 条 |
| `ntce.outline.308.tables.json` | 308-《生物学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/355-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.308.txt` | 308-《生物学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/355-1.htm | locator.text_path 引用 20 条 |
| `ntce.outline.309.tables.json` | 309-《道德与法治学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/383-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.309.txt` | 309-《道德与法治学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/383-1.htm | locator.text_path 引用 18 条 |
| `ntce.outline.310.tables.json` | 310-《历史学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/357-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.310.txt` | 310-《历史学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/357-1.htm | locator.text_path 引用 20 条 |
| `ntce.outline.311.tables.json` | 311-《地理学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/359-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.311.txt` | 311-《地理学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/359-1.htm | locator.text_path 引用 21 条 |
| `ntce.outline.312.tables.json` | 312-《音乐学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/361-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.312.txt` | 312-《音乐学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/361-1.htm | locator.text_path 引用 16 条 |
| `ntce.outline.313.tables.json` | 313-《体育与健康学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/363-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.313.txt` | 313-《体育与健康学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/363-1.htm | locator.text_path 引用 30 条 |
| `ntce.outline.314.tables.json` | 314-《美术学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/365-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.314.txt` | 314-《美术学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/365-1.htm | locator.text_path 引用 33 条 |
| `ntce.outline.315.tables.json` | 315-《信息技术学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/367-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.315.txt` | 315-《信息技术学科知识与教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/367-1.htm | locator.text_path 引用 36 条 |
| `ntce.outline.316.tables.json` | 316-《历史与社会学科知识及教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/387-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.316.txt` | 316-《历史与社会学科知识及教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/387-1.htm | locator.text_path 引用 17 条 |
| `ntce.outline.317.tables.json` | 317-《科学学科知识及教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/385-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.317.txt` | 317-《科学学科知识及教学能力》（初级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/385-1.htm | locator.text_path 引用 23 条 |
| `ntce.outline.403.tables.json` | 403-《语文学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/328-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.403.txt` | 403-《语文学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/328-1.htm | locator.text_path 引用 32 条 |
| `ntce.outline.404.tables.json` | 404-《数学学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/369-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.404.txt` | 404-《数学学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/369-1.htm | locator.text_path 引用 24 条 |
| `ntce.outline.405.tables.json` | 405-《英语学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/371-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.405.txt` | 405-《英语学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/371-1.htm | locator.text_path 引用 21 条 |
| `ntce.outline.406.tables.json` | 406-《物理学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/373-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.406.txt` | 406-《物理学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/373-1.htm | locator.text_path 引用 24 条 |
| `ntce.outline.407.tables.json` | 407-《化学学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/375-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.407.txt` | 407-《化学学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/375-1.htm | locator.text_path 引用 32 条 |
| `ntce.outline.408.tables.json` | 408-《生物学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/326-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.408.txt` | 408-《生物学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/326-1.htm | locator.text_path 引用 21 条 |
| `ntce.outline.409.tables.json` | 409-《思想品德学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/324-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.409.txt` | 409-《思想品德学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/324-1.htm | locator.text_path 引用 18 条 |
| `ntce.outline.410.tables.json` | 410-《历史学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/322-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.410.txt` | 410-《历史学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/322-1.htm | locator.text_path 引用 20 条 |
| `ntce.outline.411.tables.json` | 411-《地理学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/320-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.411.txt` | 411-《地理学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/320-1.htm | locator.text_path 引用 20 条 |
| `ntce.outline.412.tables.json` | 412-《音乐学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1103-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.412.txt` | 412-《音乐学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1103-1.htm | locator.text_path 引用 17 条 |
| `ntce.outline.413.tables.json` | 413-《体育与健康学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1104-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.413.txt` | 413-《体育与健康学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1104-1.htm | locator.text_path 引用 32 条 |
| `ntce.outline.414.tables.json` | 414-《美术学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1105-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.414.txt` | 414-《美术学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1105-1.htm | locator.text_path 引用 33 条 |
| `ntce.outline.415.tables.json` | 415-《信息技术学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1106-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.415.txt` | 415-《信息技术学科知识与教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1507/1106-1.htm | locator.text_path 引用 36 条 |
| `ntce.outline.418.tables.json` | 418-《通用技术学科知识及教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/389-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.outline.418.txt` | 418-《通用技术学科知识及教学能力》（高级中学） | https://ntce.neea.edu.cn/xhtml1/report/1508/389-1.htm | locator.text_path 引用 21 条 |
| `ntce.standard.trial.tables.json` | 中小学和幼儿园教师资格考试标准（试行）（试行） | https://ntce.neea.edu.cn/xhtml1/report/1508/332-1.htm | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `ntce.standard.trial.txt` | 中小学和幼儿园教师资格考试标准（试行）（试行） | https://ntce.neea.edu.cn/xhtml1/report/1508/332-1.htm | locator.text_path 引用 144 条 |
| `regulation.discipline.2020.txt` | 中小学教育惩戒规则（试行）（教育部令第49号（试行）） | https://www.moe.gov.cn/jyb_xxgk/xxgk/zhengce/guizhang/202112/P020211208553109328813.pdf | locator.text_path 引用 28 条 |
| `regulation.kindergarten.2016.txt` | 幼儿园工作规程（教育部令第39号） | https://www.moe.gov.cn/jyb_xxgk/xxgk/zhengce/guizhang/202112/t20211206_585104.html | locator.text_path 引用 66 条 |
| `regulation.school_protection.2021.txt` | 未成年人学校保护规定（教育部令第50号） | https://www.moe.gov.cn/jyb_xxgk/xxgk/zhengce/guizhang/202112/P020211208553316253863.pdf | locator.text_path 引用 84 条 |
| `teacher.behavior.2018.txt` | 新时代高校、中小学、幼儿园教师职业行为十项准则（教师〔2018〕16号） | https://www.moe.gov.cn/srcsite/A10/s7002/201811/t20181115_354921.html | locator.text_path 引用 35 条 |
| `teacher.competence.2021.teshu.tables.json` | 5.《特殊教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486931986.docx | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.competence.2021.teshu.txt` | 5.《特殊教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486931986.docx | locator.text_path 引用 39 条 |
| `teacher.competence.2021.xiaoxue.tables.json` | 2.《小学教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486911125.docx | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.competence.2021.xiaoxue.txt` | 2.《小学教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486911125.docx | locator.text_path 引用 37 条 |
| `teacher.competence.2021.xueqian.tables.json` | 3.《学前教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486917925.docx | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.competence.2021.xueqian.txt` | 3.《学前教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486917925.docx | locator.text_path 引用 27 条 |
| `teacher.competence.2021.zhongxue.tables.json` | 1.《中学教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486891275.docx | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.competence.2021.zhongxue.txt` | 1.《中学教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486891275.docx | locator.text_path 引用 36 条 |
| `teacher.competence.2021.zhongzhi.tables.json` | 4.《中等职业教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486921150.docx | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.competence.2021.zhongzhi.txt` | 4.《中等职业教育专业师范生教师职业能力标准（试行）》（教师厅〔2021〕2号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/202104/W020210426331486921150.docx | locator.text_path 引用 40 条 |
| `teacher.curriculum.2011.tables.json` | 教师教育课程标准（试行）（教师〔2011〕6号附件（试行）） | https://www.moe.gov.cn/ewebeditor/uploadfile/2011/10/19/20111019100845630.doc | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.curriculum.2011.txt` | 教师教育课程标准（试行）（教师〔2011〕6号附件（试行）） | https://www.moe.gov.cn/ewebeditor/uploadfile/2011/10/19/20111019100845630.doc | locator.text_path 引用 112 条 |
| `teacher.ethics.2008.txt` | 中小学教师职业道德规范（2008年修订）（教师〔2008〕2号（2008年修订）） | https://www.moe.gov.cn/srcsite/A10/s7002/200809/t20080901_145824.html | locator.text_path 引用 10 条 |
| `teacher.plan.2022.txt` | 新时代基础教育强师计划（教师〔2022〕6号） | https://www.moe.gov.cn/srcsite/A10/s7034/202204/t20220413_616644.html | locator.text_path 引用 4 条 |
| `teacher.professional.2012.xiaoxue.tables.json` | 小学教师专业标准（试行）（教师〔2012〕1号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/201209/W020250425561302022200.doc | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.professional.2012.xiaoxue.txt` | 小学教师专业标准（试行）（教师〔2012〕1号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/201209/W020250425561302022200.doc | locator.text_path 引用 4 条 |
| `teacher.professional.2012.youeryuan.tables.json` | 幼儿园教师专业标准（试行）（教师〔2012〕1号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/201209/W020250425561302005587.doc | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.professional.2012.youeryuan.txt` | 幼儿园教师专业标准（试行）（教师〔2012〕1号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/201209/W020250425561302005587.doc | locator.text_path 引用 4 条 |
| `teacher.professional.2012.zhongxue.tables.json` | 中学教师专业标准（试行）（教师〔2012〕1号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/201209/W020250425561302032896.doc | 不被 locator 直接引用：该来源条款定位走同目录正文 .txt，本文件保留 Word 表格单元格原文备查 |
| `teacher.professional.2012.zhongxue.txt` | 中学教师专业标准（试行）（教师〔2012〕1号附件（试行）） | https://www.moe.gov.cn/srcsite/A10/s6991/201209/W020250425561302032896.doc | locator.text_path 引用 4 条 |

## 生成与核验口径

- `.txt` 三条产出路径：43 doc + 5 docx 经 `extract_word.ps1`（Word 隐藏、只读、禁宏）转 UTF-8 无 BOM 文本；14 个 HTML 正文经 `collect_sources.py` 的 Page/Article 解析器去导航存正文；4 个 PDF 经 pypdf 逐页抽取并带 `[[PDF_PAGE n]]` 页标；`cse.gf0018-2024.txt` 是官方 JSON 的缩进重排副本。`cet.syllabus.2016.txt` 去页眉内容在条款里标 `content_type=source_text_with_layout_lines_removed`，`original_text` 保留定位范围完整原文。
- `.tables.json` 全部由 `extract_word.ps1` 产出，结构为 `[{table, cells:[{row, column, text}]}]`；面试 3 份（xiaoxue/zhongxue/youeryuan 共 23+22+16=61 处）被 `locator.table_path` 直接引用，是 `official_interview_rubrics.json` 的原料；其余 45 份笔试/教师标准大纲的表格未被 locator 引用（这些来源的条款走正文 text_path 定位），保留作单元格原文备查。
- 每个文件的 `text_sha256` 记在 `../catalog.json`，由 `../verify_sources.py` 离线复比对；4 个不经 text 引用的 `.txt`（cet.content.cet4/cet6、cse.gf0018-2024、evidence.gbt41671-2022）仍参与哈希核验。
