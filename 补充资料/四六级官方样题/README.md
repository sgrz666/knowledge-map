# 补充资料/四六级官方样题/ —— 《四六级大纲（2016 修订版）》样卷部分的抽取产物；由 kb_tools/cet_official_examples.py 生成，供四六级库的答案恢复核对与审查消费

## 文件清单（92 个数据文件 + README.md，逐个列名/按命名规律列全）

### 抽取与索引数据（14 个）

| 文件名 | 内容 |
| --- | --- |
| `exact_matches.jsonl` | 与主库 CET 题的完整匹配记录（现检查 5,340 条主库记录，完整匹配 0） |
| `index.html` | 离线查看页（双击可筛学段/题型/展开答案，无网络依赖） |
| `official_examples.jsonl` | 118 条完整提取档案＝114 题 + 4 组写译评分样卷（每组 14/11/8/5/2 分共 20 篇作答） |
| `oral_samples.jsonl` | 两套官方口试正文（四级 169–171、六级 192–193 页）与六级图像卡片文字；知识点/能力列表为空并标待对齐 |
| `passages.jsonl` | 23 篇完整听读语篇（15 组听力文字稿、2 选词填空、2 长篇阅读、4 仔细阅读），resource_id 供题目 extra.passage_id 对接 |
| `questions.jsonl` | 114 条标准题目契约记录；source.files[].path 全部指 `权威资料/originals/cet.syllabus.2016.pdf`（276 处引用，现算），题面带 PDF 页码与 locator |
| `reconstructed_source.txt` | PDF 150–211 页恢复文本 |
| `recovery_patches.jsonl` | 严格恢复补丁；当前 0 字节（真实恢复 0，主库未被修改） |
| `source_pages.json` | 约 39 MB 抽取产物：62 页原生文本、字符坐标、原始字形流、恢复文本与页图路径；由 kb_tools/cet_official_examples.py 生成（dump_json 到本目录），PDF 哈希变化时拒绝沿用旧边界 |
| `source_sections.jsonl` | 14 个完整原文边界（两套笔试、听力稿、答案、口试、答题卡、写译评分） |
| `summary.json` | 数量/缺口摘要，含 page_text_path 指 source_pages.json |
| `viewer_preview.png` | 查看页冒烟测试的浏览器截图留档（viewer_smoke.cjs 跑过后的画面存证，非试题内容） |
| `viewer_smoke.cjs` | Node 冒烟测试：浏览器筛选、搜索、答案展开 |
| `visual_verification.json` | 原 PDF、页图、恢复文本哈希与实际视觉检查范围；哈希变动会撤销 visually_verified |

### 页图与布局图（62 个 PNG + 16 个 JPG）

`page.NNN.png`（62 个，150–211 全列）：大纲 PDF 第 150–211 页逐页渲染图（pymupdf 出图，`--render` 重建）。页段：150–161 四级笔试、162–167 四级听力稿、168 四级答案、169–171 四级口试、172–183 六级笔试、184–190 六级听力稿、190–191 六级答案、192–193 六级口试、194–201 八张答题卡、202–204 四级作文评分样卷、205–207 六级作文、208–209 四级翻译、210–211 六级翻译。答题卡页 194–201 主要是扫描图，只留原图、不标完整文字提取——扫描件原件不入库，入库检索面只有文字条款与题目契约，扫描页以原图 + 哈希留档（哈希见 visual_verification.json）：

`page.150.png` `page.151.png` `page.152.png` `page.153.png` `page.154.png` `page.155.png` `page.156.png` `page.157.png` `page.158.png` `page.159.png` `page.160.png` `page.161.png` `page.162.png` `page.163.png` `page.164.png` `page.165.png` `page.166.png` `page.167.png` `page.168.png` `page.169.png` `page.170.png` `page.171.png` `page.172.png` `page.173.png` `page.174.png` `page.175.png` `page.176.png` `page.177.png` `page.178.png` `page.179.png` `page.180.png` `page.181.png` `page.182.png` `page.183.png` `page.184.png` `page.185.png` `page.186.png` `page.187.png` `page.188.png` `page.189.png` `page.190.png` `page.191.png` `page.192.png` `page.193.png` `page.194.png` `page.195.png` `page.196.png` `page.197.png` `page.198.png` `page.199.png` `page.200.png` `page.201.png` `page.202.png` `page.203.png` `page.204.png` `page.205.png` `page.206.png` `page.207.png` `page.208.png` `page.209.png` `page.210.png` `page.211.png`

`layout.NNN-NNN.jpg`（16 个，每 4 页一组拼版，Pillow 合成，供布局核对复看）：

`layout.150-153.jpg` `layout.154-157.jpg` `layout.158-161.jpg` `layout.162-165.jpg` `layout.166-169.jpg` `layout.170-173.jpg` `layout.174-177.jpg` `layout.178-181.jpg` `layout.182-185.jpg` `layout.186-189.jpg` `layout.190-193.jpg` `layout.194-197.jpg` `layout.198-201.jpg` `layout.202-205.jpg` `layout.206-209.jpg` `layout.210-211.jpg`

双击 `index.html` 即可筛选四级/六级、题型、评分样卷、口试及完整原文档案，展开官方参考答案，查看完整语篇、听力文字稿和原 PDF 页图。页面无需网络或服务器。

## 内容与使用

- `questions.jsonl`：114 条标准题目。四级、六级各 55 道客观题、1 个写作任务和 1 个翻译任务；110 道客观题有官方参考答案，两个翻译任务有官方参考译文。写作 `content.answer=null`。
- `passages.jsonl`：23 篇完整听读语篇（15 组听力文字稿、2 篇选词填空、2 篇长篇阅读、4 篇仔细阅读），含词库/段落选项与题目 ID。用题目 `extra.passage_id` 对接 `resource_id`。
- `official_examples.jsonl`：118 条完整提取档案，含上述 114 条及 4 组写译评分样卷。每组原样保存 14、11、8、5、2 分作答，共 20 篇；拼写与语法错误保留，低分作答不是范文。官方没有逐篇点评，相关字段明确为空。
- `oral_samples.jsonl`：两套完整官方口试正文、页图及六级图像卡片文字。四级图画和六级卡片保留原图。现有本体没有口试具体节点，知识点/能力列表为空并明确待对齐；没有虚造 ID。
- `source_sections.jsonl`：14 个完整原文边界，包括两套笔试、听力稿、答案、口试、答题卡和写译评分部分。
- `source_pages.json` / `reconstructed_source.txt`：PDF 150–211 共 62 页的原生文本、字符坐标、原始字形流、恢复文本和原图路径。答题卡主要是扫描图，不标为完整文字提取。
- `page.NNN.png` / `layout.NNN-NNN.jpg`：全部原页渲染及布局核对图。
- `visual_verification.json`：原 PDF、页图和恢复文本哈希，以及实际视觉检查范围。全页布局、字体空格/连字符/撇号、双栏选项、跨页题目与语篇、答案行和评分边界已检查；这不代表独立逐字专家校对。
- `exact_matches.jsonl` / `recovery_patches.jsonl` / `summary.json`：主库完整精确匹配记录、严格候选回填补丁和数量/缺口摘要。当前检查 5,340 条主库记录（原5,294个ID全部保留，另含新增待核和停用审计记录），完整匹配 0，真实恢复 0。

题目采用共同格式：`question_id/exam/module/question_type/content/extra.passage_id/source.files`。来源明确为官方大纲样卷，保留 PDF 页码、定位、来源 URL 与 SHA-256，不标作某年月实考真题。具体知识点、能力和大纲要求 ID 从主库只读复用并校验；题型/题干关键词初标仍待专家确认。全部 `review.status=pending_expert_review`、`difficulty=null`，官方答案不代表专家审核完成。

## 复跑与测试

在 `D:\codeplus\knowledge_map` 的 PowerShell 运行（Python 需要 `pymupdf`、`fonttools`；重新渲染布局图还需要 `Pillow`）：

```powershell
$env:PYTHONIOENCODING='utf-8'
python kb_tools/cet_official_examples.py
python -m unittest discover -s tests -p test_cet_official_examples.py -v
```

首次重建全部页图或恢复图像文件：

```powershell
python kb_tools/cet_official_examples.py --render
```

脚本只写本目录，不修改主库、权威原件或 requirements。源 PDF 哈希改变会拒绝沿用旧边界/字形规则；页图或恢复文本哈希改变会撤销对应的 `visually_verified` 状态，不能靠重新运行自动声明看过新内容。

可用 `viewer_smoke.cjs` 验证实际浏览器筛选、搜索与答案展开：

```powershell
& 'C:\Users\sg\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' '补充资料/四六级官方样题/viewer_smoke.cjs'
```

## 严格恢复接口

`kb_tools.cet_official_examples` 提供 `extract_official(root)`、`load_main_questions(root)`、`match_examples(examples, questions)` 和 `recovery_patches(matches, examples, questions)`。主库问答比较完整题干、标签对应的全部选项和完整语篇，仅规范化 NFKC/排版空白；英语词间边界保留。选词填空还比较原空位标签，前提始终是完整语篇/词库/题干一致。相同题号、年月、短片段或仅选项一致都不能恢复。来源与主库任一侧歧义、源文本未视觉检查、旧内容发生变化或已有答案均不会产生补丁。

补丁包含 `before_content_sha256`、完整上下文签名及官方出处，调用方应在实际写入前再次核对。这里没有直接修改主库。旧听力题如果没有题干/文字稿，不能用官方听力稿或别卷音频替代，因而无法通过完整匹配。

## 来源与确切缺口

唯一试题原料为教育部教育考试院发布的 [《全国大学英语四、六级考试大纲（2016 年修订版）》](https://cet.neea.edu.cn/res/Home/1704/55b02330ac17274664f06d9d3db8249d.pdf)，本地原件 `权威资料/originals/cet.syllabus.2016.pdf`，SHA-256 为 `9166d3c03b7bc43abd9d9df91bd2ef8085b4419286f1e5ca100dea68f3cfd1f1`。PDF 页码从 1 开始，印刷页码为 PDF 页码减 5。

四级笔试 150–161、听力稿 162–167、答案 168；六级笔试 172–183、听力稿 184–190、答案 190–191。口试四级 169–171、六级 192–193；评分样卷四级作文 202–204、六级作文 205–207、四级翻译 208–209、六级翻译 210–211。八张答题卡 194–201 完整保留为原图。

缺口是源音频/时间戳、逐题官方解析、写作唯一答案、口试作答样例、专家审核、难度实测及口试具体本体映射。所有字段如实标记缺失或待处理。此目录没有批量复制第三方商业解析，也没有生成替代官方答案的原创分析。
