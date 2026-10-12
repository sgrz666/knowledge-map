# 数据集/教资/sources —— 一条外部学习参考来源的原件与哈希清单

3 个文件，记同一件东西：安康学院教资专题页《教育知识与能力》知识总结。它是**采集回来的参考原文**，不是官方答案件——`catalog.json` 里 `scope` 写死 `supplementary_learning_reference; not_official_exam_answer`、`copyright.authorization_status: unknown`、`expert_verified: false`。

本目录是 `../README.md` 末尾「允许人工维护」名单里的一项（同名单还有 `graph/edges_curated.jsonl`、`subject_map.json`、`review/answer_conflict_reconciliation.*`）：内容可以手工补。
**但要说清没有门禁兜着**：现算 grep 全仓 `*.py`，读 `数据集/教资/sources/catalog.json` 的只有写它的那个脚本（`kb_tools/ntce_source_supplements.py:40`），`审查/validate_kb.py` 没有一条规则碰本目录——它核对的是**题记录 `source.files[].sha256`**（`validate_kb.py:127`、`:158`），而当前没有任何题记录指向这里（见下节）。所以手改两个原件不会触发任何结构性错误，只会让 `ntce_source_supplements.py` 的行号定位失效（那个脚本会 `RuntimeError` 停下来）和下次重写时的 sha256 变化。哈希是给人看的留痕，不是门禁。

## 文件清单

- `aku_education_reference.txt`（129,462 B，UTF-8 带 BOM，现算 2,059 行）—— 页面正文抽取件，是从题干关键词回查解释文本的行文语料。被 `kb_tools/ntce_source_supplements.py:29` 以**硬编码行号区间**引用：`BRIEF` 表把 3 道题挂到 768–775（科学性和思想性统一原则）与 737–743（启发性教学原则），跑之前先按行号取片段并核对短语，短语不在原文就 `raise RuntimeError('来源或题目已改变，停止使用旧定位：'+qid)`。所以**这份文件的行号是接口**：删一行、动一次空行都会让那个脚本跑不动。现算校验：768–775 仍含「科学性和思想性统一原则」，2,059 行未变。
- `aku_education_reference.html`（530,201 B，UTF-8 带 BOM）—— 同页的原始 HTML（`<TITLE>` 为「教资考试：《教育知识与能力》知识总结.docx-安康学院」）。留着只为对照 txt 抽取有没有丢内容，仓库内没有任何脚本读它；只有 `ntce_source_supplements.py:32` 的 `for p in (local, local.with_suffix('.html'))` 会把它一起算进 `catalog.json` 的 `files[]`。
- `catalog.json`（837 B）—— 生成物，**唯一写入者是 `kb_tools/ntce_source_supplements.py:36-40`**：`source_id: aku.education.20230520`、`source_url: https://dfl.aku.edu.cn/info/1641/6717.htm`、`published_at: 2023-05-20`、`files[]` 两条带 sha256、`scope`/`copyright`/`expert_verified` 见上。重跑 `python kb_tools/ntce_source_supplements.py` 会整份重写（`write_text`，非追加）。它和 `权威资料/catalog.json` 是两份东西：那份是官方大纲/法规来源总账，这份只覆盖这一条学习参考件，不进 `services/knowledge/repository.py` 的读入名单。现算核对：两个原件的 sha256 与这里记的两条逐字相符（txt `804d42b7…5738302a`、html `e65d219f…2dfb3f306`）；自己重算一条：`python -c "import hashlib;print(hashlib.sha256(open('数据集/教资/sources/aku_education_reference.txt','rb').read()).hexdigest())"`。

## 现在谁在引用它

- 生成引用：`kb_tools/ntce_source_supplements.py` 的 3 条 `BRIEF` 会把 `{path: 数据集/教资/sources/aku_education_reference.txt, role: analysis_basis, source_url, locator:{line_start,line_end}, scope: learning_reference_not_official_exam_answer}` 追加进题记录 `source.files[]`，仅在 `not content.get('answer')` 时写入；跑完自动 `repair(skip_outline=True)`（`:90`），`--no-sync` 可跳过修复。5 条 `LAW` 是教师法第 39 条的选择题解析草稿，走 `权威资料/requirements.jsonl` 的 `law.teacher.2009.r040`，与本目录无关。
- 现算引用状态：`数据集/教资/questions/**` 当前 **0 行**题记录含 `aku_education_reference` —— 那 3 道题（`ntce.zhongxue.jiaoyuzhishi.2013a.q25` / `2018b.q25` / `2022a.q26`）都已在后续轮次拿到答案（现查 `answer_status` 均为 `reference_only`、`review.status` 均 `needs_fix`），`not c.get('answer')` 条件不成立，所以再跑脚本也只重写 `catalog.json`、不会再挂新引用。带该引用的历史行还留在迁移前快照里（例：`_contract_snapshot/questions/zhongxue/jiaoyuzhishi/2013a.jsonl` 第 25 行）。
- 也就是说：本目录今天是**证据留存**，不是运行时依赖。删掉两个原件会让 `ntce_source_supplements.py` 一进门就 `RuntimeError`（它先查 `local.exists()`）。

## 改这里之前要知道的

- 只在库外网络可达时才知道的：`source_url` 是安康学院外语系页面，正文转自一份 docx；授权状态未知，因此全库口径是 `use_scope: research_non_commercial`，不许把它当官方答案出处写进任何对外文本。护栏见 `services/llm/guardrails.py` 的 banned-claim 名单。
- 新增第二条来源时：把文件放本目录、在 `ntce_source_supplements.py` 的 `COLLEGE_URL`/`BRIEF` 旁边扩写（`catalog.json` 由脚本整体重写，手加条目会被下一次运行抹掉），行号定位必须来自当前文件实际行号——用 `python -c "print(open('数据集/教资/sources/xxx.txt',encoding='utf-8').read().split(chr(10))[767:775])"` 现查，别照抄旧 README。
- 本目录不参与向量索引：`services/knowledge/vector_index.py` 只吃 `数据集/*/cards/**/*.md`。
