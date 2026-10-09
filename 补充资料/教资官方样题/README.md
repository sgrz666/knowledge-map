# 教资官方样题与补充来源

本目录独立于主库及通用考试要求。38份官方大纲的样题正文完整保存；每条题目或题组有来源ID、URL、原Word路径与SHA-256、提取文本行定位、原文以及是否提供答案的标记。来源是考试大纲样题，不能据此把现有题库题目声称为官方发布的历年真题。

## 已完成

- `official_examples.jsonl`：35份笔试大纲、3份面试大纲，210条样题或题组，157条单题、53条保留共享材料的题组。题组没有冒充已经唯一对齐的单题。
- `source_sample_sections.jsonl`：38份样题章节的完整提取原文，包括题型标题和嵌入材料。原Word中的图和公式仍以原件为准。
- `exact_matches.jsonl`：对现有14,500题作完整题干、全部选项的NFKC与空白规范化匹配；保留歧义、材料不等价及无答案状态。
- `recovery_patches.jsonl`：只输出来源和题干均唯一、完整且真实带答案的补丁；目前是空文件，确切恢复数为0。主库未被本工具修改。
- `supplementary_sources.json`：9个官方或出版社补充来源；6个出版社条目只取得目录或书目信息，没有将未获取的样章冒充答案。

只有初中科学大纲 `ntce.outline.317` 明确刊出7题标准答案及评分标准。它的7题均已保留完整原件视觉上下文：原DOC中15个嵌入对象和3个浮动对象都仍存在。纯文本抽取漏掉了样题1的分式、2的碳循环图、4的向量、6的作业框与公式、7的教材图；这些不是官方原件缺失。

`ntce.outline.317.pdf` 由隐藏、只读、禁宏Word COM导出，未修改原DOC。第4页包含题1–6，第5页包含题7，第6页包含答案1–6，第7页包含答案7；相应页图已逐页看过且可读。`visual_verification.json` 保存原件、PDF、页图的哈希及视觉检查记录，检查不等于人工专家审定。`official_examples.jsonl` 的 `visual_context` 可直接定位对应页面；`object_transcription` 提供原件公式的辅助转录。含图或公式的5题不会仅凭残缺文本生成恢复补丁。

其余大纲没有刊出样题答案。高中化学大纲的“故答案为B”属于供考生诊断的错误解答；面试大纲的整体评分表属于通用面试评价，均未归入样题参考答案。现有题库的两个精确题目匹配也都没有官方样题答案，不能恢复。

## 使用与复跑

在仓库根目录执行：

```powershell
$env:PYTHONIOENCODING='utf-8'
python kb_tools/official_examples.py
python -m unittest discover -s tests -p test_official_examples.py -v
```

构建只更新本目录的4个JSONL和`summary.json`。先验证权威资料的Word与提取文本哈希；若原件改变，停止并要求重新核源。PDF、页图和视觉清单也会核对哈希。所有JSONL按物理行读取，不会把题目内部的Unicode行分隔符当成记录边界。

主库恢复代码可调用：

```python
from pathlib import Path
from kb_tools.official_examples import extract_catalog, read_jsonl, match_examples, recovery_patches

root = Path.cwd()
examples = extract_catalog(root)
questions = [q for p in sorted((root / '教资KB/questions').rglob('*.jsonl'))
             for q in read_jsonl(p)]
matches = match_examples(examples, questions)
patches = recovery_patches(matches, examples, questions)
```

`recovery_patches` 会重新匹配当前题目，拒绝陈旧匹配；生成补丁含 `before_content_sha256`，实际写入前必须再次检查此哈希。它只返回数据，调用方负责主库变更。答案溯源应标为 `official_outline_sample_reference`，不得设置 `expert_verified=true` 或改成官方历年真题。

## 补充原料与尚未取得内容

教育部《3-6岁儿童学习与发展指南》的官方通知及DOC已新取得并保存；原DOC为50页，正文提取为974段、23080字符。来源索引保留原件、提取文本和通知页哈希，短摘有精确字符定位。它可作为幼儿发展、生活游戏、活动设计等原创解答的理论依据，不能声称直接发布了现有题库某题的考试答案。

清华大学出版社4个书目详情页已核实ISBN、日期、目录及“暂无样章”状态。高等教育出版社2个书目从官方域名检索缓存得到，直接访问返回500或客户端跳转，未可靠取得样章正文。只保留来源、短摘和原创归纳；没有复制批量商业解析。书目出版于2012或2016年，涉及法律法规或课程版本的解答仍须查核适用时间的官方版本。

因此，本批新增了可练习、可追溯的官方样题和用于后续原创解答的资料入口，原答案CSV中的“参见解析”缺口仍需题目专属正文或经过复核的原创解答解决。没有删题或缩小主库范围。
