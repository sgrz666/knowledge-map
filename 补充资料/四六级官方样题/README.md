# CET 2016 官方大纲样卷补充集

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
