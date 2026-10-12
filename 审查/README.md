# 审查/ —— 全库数据门禁与复核证据的存放地，教研与接手开发者在这里读"库到底缺什么"

这里放三类东西：**可执行的验收脚本**（`validate_kb.py` 等 9 个 `.py`：8 个已在版本库，`卡片答案镜像检查.py` 现在还是未跟踪状态）、**脚本生成的结果文件**（`.json` / `.md`，标了生成来源的不要手改）、**一次性排查用的本地临时脚本**（以 `_` 开头，全部被 `.gitignore` 排除，不在版本库里）。
日常顺序：改数据 → `python 审查/validate_kb.py` 看结构与缺口 → `python 审查/build_review_queue.py` 重生成待复核清单 → 需要完整证据链时跑 `python 审查/run_verification.py`。
命令都在仓库根目录执行（多个脚本用相对路径 glob，cd 到别处会扫不到数据）。
入库口径见 `.gitignore` 第 47–59 行：`审查/*.py`、`审查/*.md` 与少量证据 `.json` 入库；不入库的是 `审查/_tmp_*`、`审查/_*.json`、`审查/_*.txt`、`审查/_*.py`、`审查/_work/`、`审查/batch/`、`审查/harness_batches/`、`审查/验证日志/`、`审查/知识库验收结果.json`、`审查/知识库待补队列.jsonl` 与 `审查/*.log`（`.py` 与 `.log` 临时件没有一条统一的 `审查/_*` 规则：`审查/_*.log` 实际靠 `审查/*.log` 排除；`__pycache__/` 靠第 36 行全局规则）。

## 文件清单（入库脚本）

- `validate_kb.py`（967 行）—— 全量结构验收器，本目录最核心的门禁。读 `权威资料/catalog.json`、`权威资料/requirements.jsonl`、`数据集/四六级/**`、`数据集/教资/**`、`补充资料/四六级官方样题/`，逐题逐资源检查约 80 条规则（悬空引用、答案绑定、来源哈希/区间哈希、状态词表越界、量规双真相、版权越界、先修环等），严重级只有两档：`error`（结构性错误）与 `gap`（内容待补），没有 warn。写 `审查/知识库验收结果.json`（`--output` 可改）并把全部 issue 逐行写到**同目录**的 `知识库待补队列.jsonl`（`args.output.with_name(...)`，改 output 路径时队列会跟着落过去）。退出码：有任意 issue（含 gap）即 1，零 issue 才 0。单跑：`python 审查/validate_kb.py`。
- `build_review_queue.py`（547 行）—— `待复核清单.md` 的**唯一生成器**：现算先修候选边、官方条款未被引用清单、答案/题面/判重三类抽取缺口（复用 `services/knowledge/repository.py` 投影与 `kb_tools/ntce_repair.py` 同一份判据）、量规底数、paper_specs 内部一致性与题面用时交叉核对。必须从仓库根运行（内部 `ROOT = Path('.')`）；写 `审查/待复核清单.md`，环境变量 `KM_QUEUE_OUT` 可改输出路径；stdout 打一行摘要计数。清单里的数字全是算出来的，手抄段落重跑即被抹掉。
- `知识库形式审查.py`（312 行）—— 只读形式审查：两套库 JSONL 可解析性、覆盖率统计、悬空引用、语篇/材料双向绑定、图谱 DAG 与模块可达性。写 `审查/知识库形式审查结果.json`，并**顺带重新生成** `审查/知识库形式审查.ipynb`（把自身代码嵌进 notebook 连同上次输出）。无退出码逻辑，恒 0。单跑：`python 审查/知识库形式审查.py`。
- `状态词表检查.py`（77 行）—— 附录 A.1 六态复核词表 + 五态答案词表的独立自检，扫目录参数下全部 `*.jsonl`/`*.json`（跳过 `graph/schemas/manifest/review` 与 `_backup*`），顺带查 `letter_only/reference_only` 缺 `extra.answer_provenance` 和废弃键 `extra.answer_status`。用法：`python 审查/状态词表检查.py 数据集/教资`（缺省即教资）；违规打印计数器并退出 1，干净退出 0。
- `build_repair_summary.py`（168 行）—— 修复验收报告生成器：读 `知识库验收结果.json`（`--validation-file` 可换）、入库的冻结基线 `修复前基线.json`、`权威资料/verification_report.json`、`验证运行记录.json`、`数据集/四六级/manifest/passage_reference_repair_report.json`（存在才读），写 `四六级与教资修复验收报告.md` 并打印路径。必须在 `validate_kb.py` 之后跑。
- `run_verification.py`（63 行）—— 五道检查的串跑器：依次执行 `python -m unittest discover -s tests -v`、`-s 权威资料 -p test_source_index.py`、`权威资料/verify_sources.py`、`审查/知识库形式审查.py`、`审查/validate_kb.py`，原始 stdout 存 `验证日志/<时间戳>/01..05.log`，命令/退出码/日志 SHA-256 记入 `验证运行记录.json`，最后自动调 `build_repair_summary.py`。任一命令非 0 则本脚本返回 1，**不改写**验收的失败结论。
- `audit_ntce_completeness.py`（60 行）—— 教资完整性快照生成器：调 `services/knowledge/completeness.audit_ntce()`，把**不带钟点**的结果写 `教资完整性核对.json`（因此可 `git diff`、可字节复现），stdout 打带 `written_at` 的摘要。带 `--study-index docs/教资无题考点学习索引.md` 时另生成无题叶子考点学习索引（`docs/` 里那份就是它的产物）。`--output` 可改 json 路径。
- `build_reference_drafts.py`（70 行）—— 幼儿保教原创参考草稿的装订器：读 `补充资料/教资参考解答/reference_seeds.json` 与 `补充资料/教资官方样题/supplementary_sources.json`，**校验原文 SHA-256 后**按题干精确匹配 `数据集/教资/questions/youer/baojiao/*.jsonl` 组出带官方指南行号定位的证据记录，写 `补充资料/教资参考解答/reference_drafts.jsonl` 与 `summary.json`。不修改主题库。
- `卡片答案镜像检查.py`（208 行，**当前未入库**：`git status` 显示 `??`，`.gitignore` 没有排除它，属待 `git add` 的新脚本）—— 卡片 frontmatter 的 `answer:` 与题记录 `content.answer` 的镜像检查器。以题记录为唯一权威（`authoritative_answers():31` 走 `questions/**/*.jsonl` 建 `{question_id: answer}`），逐张读 `数据集/*/cards/**/*.md`（`scan():78`，跳过字面名 `README.md`），按 7 类计数：`一致` / `占位词但题记录有值`（占位词表 `("有","未提供")`）/ `双向都不符` / `卡片缺 answer 键` / `卡片 id 无对应题记录` / `隔离题卡片`（隔离题答案应为 `null`，非 `null` 另计 `隔离题卡片答案非 null`）/ `无 frontmatter 而跳过`；权威值为 `None` 时期望显示字面量 `null`（`expected_display():50`）。CLI：`--lib all|NTCE|CET`（缺省 all）、`--samples N`（缺省 5）、`--apply` 才改写卡片那一行 `answer:`（`apply_fixes():142`，用 `kb_tools/ntce_io.atomic_write`，正文与其余字段不动）、`--dry-run` 配合 `--apply` 只打 diff 摘要。改写范围 `APPLY_ALLOWED_LIBS = ("NTCE",)`：CET 永远只报告，打印「不在本次允许改写范围内」。只读用法：`python 审查/卡片答案镜像检查.py`（默认不加 `--apply` 不落盘）。2026-10-12 一次只读运行（`--lib NTCE`）的实测：题记录 14,500、扫卡 12,881、`一致` 12,030、`占位词但题记录有值` 175、`双向都不符` 676、`隔离题卡片` 753（其中答案非 `null` 504）、待修 851 张——数字随数据变动，只作跑法与判据的实证，不作基线。

## 文件清单（入库报告与证据）

- `README.md`（本文件）—— 手改。
- `待复核清单.md`（276 行）—— 由 `build_review_queue.py` 生成，**不要手改**。教研签署队列：§0 底数、§1 先修边、§2 未引用条款、§3 答案/题面/判重缺口（含 §3.1–3.3）、§4 量规、§5 优先级、§6/§6.1 考务规格与题面用时、§7 复核动作。当前工作区状态是 M（脚本改动后未重跑），以重跑后为准。
- `四六级与教资修复验收报告.md`（101 行）—— 由 `build_repair_summary.py` 生成，不要手改。修复前后覆盖数对比 + 剩余缺口分类表 + 证据文件清单（含验收结果 JSON 的哈希）。
- `四六级与教资知识库符合性审查.md`（150 行）—— 手写的 2026-10-03 首次基线审查报告，只作历史证据，当前状态不看它看验收结果 JSON。
- `知识库修复与使用说明.md`（88 行）—— 手写。两套库的数据入口表（题目/语篇/文字稿/本体/材料/图谱各在哪、按什么字段连接）与四道门禁的复跑顺序。
- `知识库形式审查.ipynb`（1527 行）—— 由 `知识库形式审查.py` 每次运行**覆盖生成**，不要手改；notebook 里嵌的是脚本当时的副本加最后一次输出。
- `知识库形式审查结果.json`（41KB，入库）—— `知识库形式审查.py` 的输出。
- `修复前基线.json`（37KB）—— 2026-10-03 冻结的形式审查输出快照（`build_repair_summary.py` 的对比基线），**冻结件，重跑脚本不会更新它**，别拿它当现状。
- `教资完整性核对.json`（36KB）—— `audit_ntce_completeness.py` 生成，内容字节可复现（不含时间戳）。
- `验证运行记录.json`（2.2KB）—— `run_verification.py` 生成，记录最近一次五道运行的命令、退出码、日志路径与哈希。当前指向 `验证日志/20261004-111237/`。
- `四六级解析小样复查.json`（19KB）—— 由 `kb_tools/gen_cet_sample_analysis.py` 生成（脚本里写死了这个输出路径），四六级逐题解析的人工小样文本，供复查用。
- `教资解析小样复查.json`（7KB）—— 2026-10-04 对 20 题 AI 解析小样的逐条复查记录（含样本文件哈希、结论与限制），**仓库内找不到生成它的脚本**，属会话内人工/AI 复查落盘。
- `官方条目定位核验.json`（58B）—— 一次性定位核验结果（`{"checked": 6383, "issues": []}`），仓库内无生成脚本；现行同类检查在 `权威资料/verify_sources.py` 与 `validate_kb.py`。
- `来源凭据.json`（4.9KB）—— "结论 → 证据文件/指标定义"的凭据包（schemaVersion 1），仓库内无生成脚本，人工维护的证据映射。
- `AI补全费用估算.json`（1.6KB）—— 2026-10-03 的 DeepSeek 价格快照与费用估算依据（附来源 URL），人工记录，不是脚本产物。

## 文件清单（大体积运行产物，不入库）

- `知识库验收结果.json`（约 42MB）—— `validate_kb.py` 全量输出（含全部 issue 明细），gitignore 排除，随时可重建。
- `知识库待补队列.jsonl`（约 34MB）—— `validate_kb.py` 把上面的 issues 逐行写的待补队列，gitignore 排除。

## 本地临时脚本（`_` 开头，`.gitignore` 排除 `审查/_*.py`，用完即弃、不要依赖）

- `_chk_*.py`（7 个，18–40 行）—— 只读排查：`_chk_body/_chk_body2` 核对四六级卡片与题记录正文/隔离态一致性；`_chk_cards` 找教资 `source_conflict` 题是否还留在卡片里；`_chk_cet_cards` 解析 CET 卡片 frontmatter 比对；`_chk_card_framework` 用 `kb_tools/build_kb.render_card` 重渲染验证框架字段；`_chk_clause_gap` 数权威条款与图谱 `aligned_to_requirement` 的引用差；`_chk_sc` 全库扫 JSON 解析错误。
- `_sync_*.py` / `_resync_cards.py`、`_find_render_fail.py` —— 按源码读查修正方向：`_sync_card_states.py` 与 `_sync_cet_cards.py` 都以**题记录为权威源、只改写卡片 frontmatter**（不是把卡头写回题记录，尽管后者 docstring 措辞如此）；`_resync_cards` 直接复用 `kb_tools/ntce_repair.sync_cards` 全量重写卡片；`_find_render_fail` 用 `kb_tools/build_kb.render_card(rec, material_text)` 逐题试渲染找 TypeError。逐个点名见文末清单。
- `_probe_*.py`（11 个）—— 只读形状调研（字段分布、exam/module 取值、TrustGate 可用池、来源键形状、解析形状等），不写盘或只写 stdout；各自调研对象逐个点名见文末清单。
- `_smoke_*.py`（4 个）—— 冒烟跑运行时（门面/组卷/答疑/mock 组卷场景）；`_smoke_mock/_smoke_practice/_smoke_qa` 与 `_dbg_cet/_dbg_cet2/_dbg_seq` 先 `KNOWLEDGE_MAP_STATE_DIR=tempfile.mkdtemp()` 防止写进 `.local_state/`，但 `_smoke_facade.py` 没有设该环境变量（只走 repository/TrustGate 只读路径）。
- `_gen_part1..6.py`、`_opt_zhongxue_build.py`、`_opt2_gen_write.py`、`_write_wuli.py`（143–354 行）—— 教资逐项解析（option_compare）的 agent 人工判断载荷：以 `{question_id: 讲解文本}` 字典形式存分析结论（含"需看图、null 不编"的题），供写回脚本读取；`_serial_export*.py`/`_serial_filter.py`/`_dump.py` 是配套的导出与过滤（复用 `kb_tools/ntce_option_compare.needs_work` 判可分析性）。
- `_affected_files.py`、`_pre_mig.py`、`_dim_dup.py`、`_obj_rubric.py`、`_rubric_*.py`、`_rid_shape.py`、`_dryrun_contract.py`、`_audit_tags.py` —— 量规/契约迁移前的形状摸底与干跑（`_dryrun_contract` import `kb_tools/ntce_contract` 只算不改）。
- `_scan_secrets.py`（提交前敏感信息扫描，只读 git 待收文件）、`_scan_big_files.py`、`_scan_untracked_size.py`（体积盘点）。
- `_copyright_run*.log`、`_repair_*.log`、`_tmp_loglist.txt`、`_batch*`、`_eng_*`、`_zz_*`、`_yy_*`、`_part_*.json`、`_rest_*`、`_affected.json`、`_tmp_copyright_report.json`、`_manifest_backup_before.json`、`_stats_backup_before.json`、`_serial_index.json` —— 历次版权清权/修复/批量分析会话的中间数据与日志，`审查/_*.json`、`_*.txt`、`*.log` 均在 gitignore 内；这一族的逐文件点名见文末"逐文件清单（本地临时件，全部不入库）"一节。
- `__pycache__/` —— Python 自动生成的字节码缓存。

## 改这里之前要知道的

- `validate_kb.py` 退出码 1 ≠ 检查失败：它只要有任何 issue（含 gap）就返回 1；判读要分开看 `structure_errors`（形状）与 `remaining_gaps`（内容），结构 0 错也不代表内容核过。
- `--output` 指到别处时，`知识库待补队列.jsonl` 会跟着写到那个目录（`.local_state/` 里那份就是这么来的），不是留在 `审查/`。
- `build_review_queue.py` 与 `audit_ntce_completeness.py` 都 import `services.*`，cwd 必须是仓库根；前者还 import `kb_tools/ntce_repair`，缺 `数据集/**/paper_specs.jsonl` 会直接抛异常。
- `待复核清单.md` 与 `修复验收报告.md` 是生成物：手改会在下一次重跑时被整篇抹掉（脚本头 docstring 明写了这个教训）。
- `知识库形式审查.py` 每次运行都会覆盖 `知识库形式审查.ipynb` 和结果 JSON——在 notebook 里做的临时实验不会被保存，改逻辑要改 `.py`。
- 四道门禁的推荐顺序与各自角色见 `知识库修复与使用说明.md`；`修复前基线.json` 永远停留在 2026-10-03，对比"修复前"只能用基线，不能用当日重跑结果。

## 逐文件清单（本地临时件，全部不入库）

口径：本节点名 `审查/` 下全部 126 个 `_` 开头条目加 `harness_batches/`，共 127 个。排除规则不是单条 `审查/_*`，实际生效的是 `.gitignore` 第 49–56 行的 `审查/_tmp_*`、`审查/_*.json`、`审查/_*.txt`、`审查/_*.py`、`审查/_work/`、`审查/batch/`、`审查/harness_batches/` 与第 59 行的 `审查/*.log`（`_*.log` 靠后者被排除）、第 36 行全局 `__pycache__/`；已用 `git check-ignore -v` 逐类确认归属（抽查 7 个代表路径）。判断依据全部来自 2026-10-12 的字节级读查（大小/mtime/编码/内容首尾/集合现算），.**文本文件实测均为 UTF-8**（严格解码全部通过，未发现 GBK 内容件；此前终端显示的乱码是控制台 GBK 码页转写 UTF-8 所致，与文件本身无关）。"跑得动/跑不动"是读源码比对 import 目标与依赖路径存在性的静态判断——**本节没有任何脚本被执行过**，会写数据的脚本一律未跑。删后能否重建逐条注明；判断不了的写"用途未证实"。

### A. 题面导出与 LLM 增强输入（33 个，集中在 2026-10-08 17:53–20:06 一轮串行补全会话）

- `_serial_index.json`（83.2KB，10-08 19:45）—— 单行 JSON：14 科目键 → 待补逐题解析的题 ID 清单，现算共 2,406 条（zhengzhi 405、yingyu 885、yinyue 271、meishu 146、dili 139、xinxi 114、shengwu 83、wuli 78、huaxue 64、zonghe 50、shuxue 48、tiyu 45、yuwen 43、lishi 35）。本轮会话的总索引；仓库内无生成它的脚本，历史留痕。
- `_eng_txt.json`（296.4KB，10-08 19:46）—— 885 题的英语增强输入池，值形 `{stem, ans, lv, opts}`（opts 多为 `"A."`～`"D."` 占位空文本），chuzhong 374 / gaozhong 511；ID 集合与 `_serial_index.json["yingyu"]` 完全一致（现算比对相等）。
- `_eng_a.json`（11.0KB，10-08 19:49）—— 初中英语增强输入 40 题 `{q,a,o}`，范围 2014b-jx.q17–2015b.q20。
- `_eng_b.json`（10.9KB，10-08 19:50）—— 初中英语输入 40 题，范围 2015b.q23–2016b.q23。
- `_eng_c.json`（11.1KB，10-08 19:52）—— 初中英语输入 40 题，范围 2016b.q24–2017b.q18。
- `_eng_d.json`（15.6KB，10-08 19:53）—— 初中英语输入 50 题，范围 2017b.q20–2020b.q20。
- `_eng_e.json`（14.6KB，10-08 19:54）—— 初中英语输入 50 题，范围 2020b.q26–2023a.q27。
- `_eng_f.json`（14.3KB，10-08 19:55）—— 输入 50 题，跨学段切批：初中 19 + 高中 31，范围 2023a.q29–（高中）2014a.q06。
- `_eng_g.json`（14.3KB，10-08 19:56）—— 高中英语输入 50 题，范围 2014a.q07–2015a.q24。
- `_eng_h.json`（14.6KB，10-08 19:57）—— 高中英语输入 50 题，范围 2015a.q27–2016b-k2.q11。
- `_eng_i.json`（13.9KB，10-08 19:57）—— 高中英语输入 50 题，范围 2016b-k2.q12–2017b.q03。
- `_eng_j.json`（14.8KB，10-08 19:58）—— 高中英语输入 50 题，范围 2017b.q04–2019b-jx-k2.q15。
- `_eng_k.json`（18.6KB，10-08 19:59）—— 高中英语输入 60 题，范围 2019b-jx-k2.q16–2021a.q27。
- `_eng_l.json`（13.3KB，10-08 20:00）—— 高中英语输入 48 题，范围 2021a.q29–2023b.q28。
- `_eng_m.json`（2B，10-08 20:01）—— 空字典 `{}`：切到第 13 批无剩余题；无 `_eng_m_out.json`。历史留痕。
- `_yy_a.json`（14.1KB，10-08 20:06）—— 音乐增强输入 55 题 `{q,a,o}`（初中 17 + 高中 38，2015b.q02–2017b.q23）；ID ⊂ `_serial_index["yinyue"]`（271 题）。**目录内无对应 `_yy_*_out.json`**——该批产出未落盘在这里，用途（是否被消费）未证实，仅按内容形状描述。
- `_zz_a.json`（20.6KB，10-08 20:02）—— 政治增强输入 55 题 `{q,a,o}`（初中 11 + 高中 44，2012b.q11–2015b-jx.q03）。
- `_zz_b.json`（22.1KB，20:03）—— 政治输入 55 题，高中，范围 2015b-jx.q05–2019a.q16。
- `_zz_c.json`（23.1KB，20:04）—— 政治输入 55 题，高中，范围 2019a.q20–2022b.q10。
- `_zz_d.json`（17.9KB，20:05）—— 政治输入 40 题，高中，范围 2022b.q14–2023b.q29。四批共 205 题，均 ⊂ `_serial_index["zhengzhi"]`（405 题），剩余 200 题未成批。
- `_rest_all.json`（55.8KB，10-08 20:06）—— 剩余科目增强输入 166 题 `{q,a,o,s}`（s=科目码），覆盖 11 科（dili/huaxue/lishi/meishu/shengwu/shuxue/tiyu/wuli/xinxi/yinyue/yuwen）；ID ⊂ `_serial_index` 且与 yingyu 池零交集。
- `_batch01.json`（22.6KB，10-08 19:48）—— 56 题 `{stem,opts,ans,lv,sub,kn}`（含知识点绑定），学科 xinxi 17 / shuxue 17 / zonghe 10 / wuli 8 / lishi 4，学段 chuzhong 25 / gaozhong 21 / youer 6 / zhongxue 3 / xiaoxue 1。是另一批（带 kn 字段的）增强输入；与 `_serial_index` 无对应关系（科目对不上），生成脚本未证实。
- `_batch_lishi.json`（18.3KB，10-08 19:46）—— 历史 35 题 `{stem,options[{key,text}],answer,level,subject,knowledge}`，全部 lishi；条数与 `_serial_index["lishi"]`（35）一致。
- `_batch1.txt`（16.9KB，10-08 17:54）—— 70 题纯文本题面（`### <序号> <qid> [科目/学段] ans=` + `S:` + `A:`–`D:`），全部初中美术。
- `_batch2.txt`（17.9KB，17:57）—— 70 题，全部初中美术（2016a.q24 起）。
- `_batch3.txt`（18.8KB，17:59）—— 70 题：美术 66 + 体育 4。
- `_batch4.txt`（17.0KB，18:02）—— 70 题：体育 28 + 音乐 42（体育批里部分题面为"缺"）。
- `_batch5.txt`（15.6KB，18:05）—— 70 题，全部初中音乐（谱例类题多）。
- `_batch6.txt`（14.6KB，18:08）—— 70 题：美术 58 + 音乐 12，含少量 gaozhong ID。`_batch1..6.txt` 与 `_gen_part1..6.py` 首题一一对应（同 qid 开头），即这六个 txt 是那六个分析脚本的题面来源。
- `_batchdump1.txt`（103.9KB，10-08 17:53）—— 184 题初中英语题面转储（分隔行 + `qid | level= | type= | ans=` + `--STEM--/--OPTIONS--` 段），范围 2013a-jx.q01–2015a-jx.q21。
- `_batchdump2.txt`（101.3KB，10-08 18:09）—— 同格式 184 题，范围 2015a-jx.q22–2019a.q02，与 dump1 零重叠；两转储合计 368 个 ID 中有 173 个不在当晚的 `_eng_txt.json` 885 池里（是否被后续筛选剔除，未证实）。
- `_dump_lishi.txt`（22.4KB，10-08 17:54）—— 81 题历史题面（`=== <序号> <qid> ANS … LEVEL …` + 题干/选项），初中+高中，2015a.q01–2023a.q03；现算包含 `_batch_lishi.json` 的全部 35 个 ID。
- `_dump_yuwen_1.txt`（152.2KB，10-08 17:58）—— 278 题语文题面，首行自报 "yuwen总数 278"，初中+高中，2012b.q06–2023b.q03。

### B. LLM 增强输出（逐题讲解载荷，24 个）

- `_eng_a_out.json`（13.7KB，10-08 19:50）—— `_eng_a.json` 的输出：同 40 键 `{qid: 讲解文本或 null}`，34 讲解 / 6 null（null=依赖图/音频，不编造，下同）。
- `_eng_b_out.json`（15.9KB，19:51）—— b 批输出 40/5 null。
- `_eng_c_out.json`（14.6KB，19:52）—— c 批输出 40/4。
- `_eng_d_out.json`（15.9KB，19:54）—— d 批输出 50/8。
- `_eng_e_out.json`（14.8KB，19:54）—— e 批输出 50/11。
- `_eng_f_out.json`（18.3KB，19:55）—— f 批输出 50/5。
- `_eng_g_out.json`（17.3KB，19:56）—— g 批输出 50/4。
- `_eng_h_out.json`（16.2KB，19:57）—— h 批输出 50/7。
- `_eng_i_out.json`（12.9KB，19:58）—— i 批输出 50/5。
- `_eng_j_out.json`（13.6KB，19:59）—— j 批输出 50/7。
- `_eng_k_out.json`（15.0KB，20:00）—— k 批输出 60/6。
- `_eng_l_out.json`（15.3KB，20:01）—— l 批输出 48/4。12 个输出合计 578 键、讲解 506 / null 72（现算）；未覆盖 `_eng_txt.json` 池余下 307 题。
- `_zz_a_out.json`（26.0KB，10-08 20:02）—— `_zz_a.json` 输出，55 键 0 null。
- `_zz_b_out.json`（24.4KB，20:03）—— b 批输出 55/0。
- `_zz_c_out.json`（25.2KB，20:04）—— c 批输出 55/0。
- `_zz_d_out.json`（18.4KB，20:05）—— d 批输出 40/0。政治 205 题全部有讲解。
- `_rest_out.json`（41.4KB，10-08 20:08）—— `_rest_all.json` 输出：同 166 键，100 讲解 / 66 null。
- `_part_dili.json`（7.8KB，10-08 12:10）—— 高中地理逐题讲解 `{qid: 文本}` 36 条、0 null（"丹霞地貌…故选A"体，与 B 组其他输出同形）。
- `_part_huaxue.json`（6.2KB，11:55）—— 高中化学讲解 24 条 / 0 null。
- `_part_lishi.json`（9.3KB，12:13）—— 高中历史讲解 44 条 / 0 null。
- `_part_shengwu.json`（19.7KB，12:07）—— 高中生物讲解 81 条 / 0 null。
- `_part_shuxue.json`（2.6KB，12:19）—— 高中数学讲解 10 条 / 0 null。
- `_part_wuli.json`（8.8KB，12:01）—— 高中物理讲解 31 条 / 0 null。
- `_part_xinxi.json`（11.9KB，12:17）—— 高中信息技术讲解 60 条 / 0 null。`_part_*.json` 共 286 条，mtime 集中在 10-08 上午（早于 A/B 组的串行批次），学段全为 gaozhong；写它们的脚本在仓库内未证实（`_gen_part*.py` 写的是 `_opt2_art_partN.json`，不是这些文件）。
- `_affected.json`（896B，10-09 23:25）—— 14 个文件路径的列表：`数据集/教资/questions/**` 中仍含"无 rubric_id 的 rubric 字典"的 jsonl 文件。生成者明确：`_affected_files.py` 尾行写死该输出路径。可由重跑该脚本重建（脚本写盘，未跑）。

### C. 生成/导出/写盘类脚本（15 个 .py；均会写数据，一律未执行，"跑得动"为源码静态判断）

- `_affected_files.py`（13 行，10-09 23:25）—— 扫教资 questions 找无 rubric_id 的文件，写 `_affected.json` 并打印总 MB。依赖路径存在，判可跑；重跑可重建 `_affected.json`。
- `_gen_part1.py`（147 行，10-08 17:56）—— 内嵌 `d` 字典 70 条讲解（21 null，null 注"需看图"），写 `审查/_opt2_art_part1.json`；题面来源 `_batch1.txt`（首题同为 meishu.2013a.q02）。自包含、判可跑，其产物当前不在目录（已消费），历史留痕。
- `_gen_part2.py`（147 行，17:59）—— 同上，70 条（28 null），写 `_opt2_art_part2.json`，对应 `_batch2.txt`。
- `_gen_part3.py`（144 行，18:02）—— 70 条（14 null），写 `_opt2_art_part3.json`，对应 `_batch3.txt`。
- `_gen_part4.py`（147 行，18:04）—— 70 条（37 null），写 `_opt2_art_part4.json`，对应 `_batch4.txt`。
- `_gen_part5.py`（143 行，18:07）—— 70 条（55 null，音乐谱例题基本全 null），写 `_opt2_art_part5.json`，对应 `_batch5.txt`。
- `_gen_part6.py`（147 行，18:10）—— 70 条（37 null），写 `_opt2_art_part6.json`，对应 `_batch6.txt`。
- `_opt_zhongxue_build.py`（354 行 / 65.7KB，10-08 12:17）—— 内嵌 `ANA` 343 条（18 null），对象是 `shengkao.zhongxue.*` 与 `ntce.zhongxue.*`（中学综合素质/教育知识+省考中学）逐题讲解；尾行写 `审查/_opt_zhongxue_output.json`（该产物当前不在目录）。自包含，判可跑、可重建产物；未执行。
- `_opt2_gen_write.py`（85 行，10-08 18:01）—— 读 `审查/_opt2_gen_input.json`（**该输入文件已不在目录**），内嵌 23 条省考中学/中学知识讲解按输入键对齐，写 `审查/_opt2_gen_part1.json`（也不在目录）。缺输入，判已跑不动；历史留痕。
- `_write_wuli.py`（34 行，10-08 12:19）—— 读 `审查/_opt_chuzhong_output.json`（**已不在目录**），把 20 条初中物理讲解只补写进其中为 null 的键并回写。缺输入，判已跑不动；历史留痕。
- `_dump.py`（13 行，10-08 11:54）—— 读 `审查/_opt_chuzhong_full.json`（**已不在目录**），按 `argv[1]` 学科切片打印题面与选项（stdout，不写盘）。缺输入，判已跑不动。
- `_serial_export.py`（40 行，10-09 16:33）—— argv 传学科/输出路径/上限，从教资 questions 过滤单选/多选且 `kb_tools/ntce_option_compare.needs_work` 判需补的题，导出 `{qid:{stem,options,answer,level,subject,knowledge}}`（`_work/<科目>.json` 的形状）。import 目标与数据路径现查均存在，判可跑；会写盘未执行。
- `_serial_export2.py`（70 行，10-09 16:33）—— 加强版导出：先按 IMG/PHON/READ 正则过滤"图片依赖/选项为空/选项重复/语音题/英语阅读无原文"，再导出并打印判废计数。依赖同上存在，判可跑；会写盘未执行。
- `_sync_card_states.py`（34 行，10-09 22:53）—— 以教资题记录中 `answer_status=source_conflict` 的题的 `review.status` 为准，重写 `数据集/教资/cards/**/*.md` frontmatter 的 `review_status` 行（方向：题记录→卡片）。依赖存在，判可跑；写 `数据集/`，未执行。
- `_sync_cet_cards.py`（52 行，10-09 22:55）—— 把四六级题记录的 review/answer 状态镜像回卡片 frontmatter 并清除答案泄漏，只写 cards。docstring 写"镜像回题记录"与代码不符（代码只写 `.md` 卡片）。判可跑；写 `数据集/`，未执行。

### D. 只读排查与探针脚本（41 个 .py；全部仅读源码+查依赖存在性，无一执行）

- `_serial_filter.py`（70 行，10-09 16:33）—— 更严格的"文本是否足以逐项分析"分类器（IMG/PHON/READ/STRIP 四组正则），只打印可分析/判废计数不写盘。依赖 `kb_tools/ntce_option_compare` 与教资 questions 均在，判可跑。
- `_chk_body.py`（30 行，10-09 22:55）—— 四六级题记录无答案（隔离态）的题，找卡片正文仍含答案标记的泄漏并打印前 5 例。依赖路径在。
- `_chk_body2.py`（31 行，22:56）—— 同范围：source_conflict 卡的正文标签分布计数 + 卡头单字母 A–O 硬泄漏清单。依赖路径在。
- `_chk_cards.py`（27 行，22:52）—— 教资 source_conflict 题 ID 在 cards 中的出现次数与 frontmatter `review_status` 是否 quarantined 的比对。依赖路径在。
- `_chk_cet_cards.py`（37 行，22:54）—— 解析四六级卡片 frontmatter，与题记录 `review.status`/`content.answer_status` 对差异计数。依赖路径在。
- `_chk_card_framework.py`（40 行，23:46）—— import `kb_tools/build_kb.render_card`，把教资题目重渲染，统计含量规框架块的卡及其中选择题占比。`render_card(rec, material_text)` 签名与当前 build_kb 一致（现查），判可跑。
- `_chk_clause_gap.py`（27 行，23:05）—— `权威资料/**/*.jsonl` 的 requirement ID 全集 与 两库 graph/nodes.jsonl 中 exam_requirement 节点全集的双向差集。依赖路径在（权威资料经符号链接，只读）。
- `_chk_sc.py`（18 行，22:52）—— 两库全部 jsonl 按 review.status 统计 source_conflict 题量。依赖路径在。
- `_probe_analysis.py`（36 行，10-10 12:08）—— 两库题记录"解析"存放位置分布：content.analysis / 顶层 analysis / extra.llm_analysis_result / source.files，各 exam 一条样本。依赖路径在。
- `_probe_cet_rubric.py`（41 行，10-09 23:41）—— 四六级全部 jsonl 的 rubric/scoring_rubric 载体、dimensions/criteria_levels 键形状分布，揪 `expert_verified=true` 但无 `checked_by` 的样本。依赖路径在。
- `_probe_dist.py`（20 行，10-10 11:55）—— 两库 questions 的 review.status / answer_status / 有无知识点 / 有无条款 / module 分布。依赖路径在。
- `_probe_dshape.py`（23 行，10-10 11:55）—— 各取教资高中语文与四六级 cet6 题目录排序后第 4 个文件首条，打印 difficulty/tags/review/content 键形状。两目录现有 19 与 70 个文件（现查），索引不会越界，判可跑。
- `_probe_scan.py`（31 行，10-10 11:54）—— 两库 questions 全量扫描：文件数/记录数/唯一 ID/解析失败行号与耗时。依赖路径在。
- `_probe_services_fields.py`（61 行，10-10 11:49）—— 教资记录 exam/module/section 取值、question_type×answer_status 可判分性、题目引用条款对 `权威资料/requirements.jsonl` 的命中率（ROOT=脚本上级，仓库根可跑）。依赖在。
- `_probe_services_inputs.py`（56 行，10-10 11:42）—— 教资/四六级 questions、materials、ontology、graph 首条记录字段形状，为 services 层选型。依赖在。
- `_probe_sources.py`（8 行，10-09 23:08）—— `权威资料/catalog.json` 与 `requirements.jsonl` 的 standard_id 对表：条款所挂标准是否都在 catalog。两文件均在。
- `_probe_specs.py`（18 行，10-10 12:06）—— CET `manifest/paper_specs.jsonl` 与教资 `paper_specs.jsonl` 首 spec 形状 + `services.knowledge.repository` 加载后的 (school_level, subject) 分布。两个 specs 文件与 import 目标均在。
- `_probe_stem.py`（22 行，10-10 12:21）—— 两库 content.stem / text 有无组合分布，并给"双空"记录 ID 示例。依赖路径在。
- `_probe_trust_pool.py`（42 行，10-10 11:43）—— 两库 review.status/answer_status/question_type/difficulty 分布 + 教资 `rubrics/*.json` 签署字段（official_scoring/expert_verified/checked_by），TrustGate 可用池依据。依赖在。
- `_doc_probe.py`（74 行，10-09 23:46）—— 四件事：1) 两库解析来源键名真实形状；2) 教资 paper_specs 字段；3) CET 知识点被题目引用数；4) `数据集/教资/schemas`、`数据集/四六级/passages` 目录现状 vs 文档宣称。依赖均现查存在。
- `_dryrun_contract.py`（26 行，10-09 22:50）—— import `kb_tools/ntce_contract`，对教资题记录副本跑 `migrate_question`，只统计将被改动的键形状与 review.status 前后对，不写盘。函数现查存在，判可跑。
- `_audit_tags.py`（103 行，10-07 21:41）—— 逐条统计 tags/answer/difficulty/知识点覆盖/来源文件/pending/review.status/学段。glob 路径为相对 cwd 的 `questions/**/*.jsonl`，仓库根无 `questions/` 目录（现查缺失）——从仓库根跑会统计 0 条，判过期（需以科目库目录为 cwd），未执行。
- `_dim_dup.py`（14 行，10-09 23:24）—— 教资 `rubrics/*.json` 各维度 name vs dimension_name、levels vs criteria_levels 描述符逐位相等性、weight 打印。依赖在。
- `_obj_rubric.py`（20 行，10-09 23:23）—— "有 rubric 字典但无 rubric_id"的教资选择题画像：题型×answer_status×选项数×有无知识点×review.status 的 top10 + 3 条样本。依赖在。
- `_pre_mig.py`（18 行，10-09 23:24）—— 同批 152 条记录的 question_specific_points 数量分布 + rubrics/*.json 键形状。依赖在。
- `_rid_shape.py`（18 行，10-09 23:23）—— rubric_id 是否等于 `rubric.<question_id>` 的计数与缺 id 记录形状前 8 条。依赖在。
- `_rubric_ids.py`（17 行，10-09 23:22）—— 教资 rubric_id 去重数/复用计数/前缀分布 + canonical rubrics 文件名单。依赖在。
- `_rubric_link.py`（21 行，10-09 23:22）—— 顶层 `rubric_id` 与内嵌 `rubric.rubric_id` 的共存/一致性、含 ref/official 字样键的形状、canonical 量规文件摘要。依赖在。
- `_rubric_probe.py`（25 行，10-09 23:21）—— 教资内嵌 rubric 的键形状分布、dimensions[0] 形状、缺 rubric_id 计数。依赖在。
- `_find_render_fail.py`（30 行，10-09 23:46）—— 全部教资题跑 `build_kb.render_card` 捕获 TypeError 并打印失败清单与首条完整记录。签名现查匹配，判可跑；只读。
- `_scan_secrets.py`（50 行，10-10 00:55）—— `git ls-files --others --exclude-standard -z` 取未跟踪文件，grep apikey/bearer/cookie/password/私钥头/sk-前缀/带凭证 URL 七模式打印片段。只读，判可跑。
- `_scan_big_files.py`（26 行，10-10 00:56）—— 对 8 个超 8MB 被跳过的数据文件（四六级/教资 graph edges、ontology、省考课程 json、type_source_audit、补充资料 source_pages.json 等，路径硬编码）跑同一组凭据正则；8 条路径现查全部存在。只读，判可跑。
- `_scan_untracked_size.py`（49 行，10-10 00:50）—— 未跟踪文件按目录与扩展名做体积归组（`\\?\` 长路径前缀防 Windows 截断）。只读，判可跑。
- `_smoke_facade.py`（34 行，10-10 11:59? 见 ls 12:00 前）—— `services.knowledge.repository.get_repository().stats()` 与建库耗时打印，再按 TrustGate research_internal/published 对全部题计 usable/answer_visibility。**未设 KNOWLEDGE_MAP_STATE_DIR**（现读源码确认），但只走只读门面路径。import 目标现查存在；未执行。
- `_smoke_mock.py`（22 行，10-10 12:08）—— 先设 tempdir 状态目录，再组 4 套模拟卷（NTCE 200、NTCE youer-zonghe、CET-4 200、CET-4 指定 spec）打印 items/shortfall/spec/structure/notices；判可跑；未执行。
- `_smoke_practice.py`（46 行，10-10 12:06）—— tempdir 状态目录 + 六种练习模式（POINT_FOCUS 取真实节点/target_module、WEAKNESS_BREAKTHROUGH、DAILY、HIGH_FREQUENCY、TIMED_SPRINT）组卷打印；未执行。
- `_smoke_qa.py`（45 行，10-10 12:10）—— tempdir 状态目录 + TutorQAAgent：对教资地理隔离题答 query/苏格拉底三轮、CET 阅读题 QA、stem 检索；未执行。
- `_dbg_cet.py`（28 行，10-10 12:19）—— tempdir 状态目录：CET-4 池×TrustGate 计可用，`_pick_spec` 默认模拟卷的 pinned 题 ID 与可用池差集；未执行。
- `_dbg_cet2.py`（13 行，12:19）—— tempdir：CET-4/6 × 三种 practice_mode 各 8 题组卷结果与 notices；未执行。
- `_dbg_seq.py`（16 行，12:20）—— tempdir：四连组卷序列（NTCE daily 8 / NTCE mock 200 / CET4 mock 200 / CET6 sprint 8），0 输出时打印 notices；未执行。

（注：C 组把 `_serial_export2.py` 计为导出器、D 组把 `_serial_filter.py` 计为只读分类器，故 C=15、D=41；`_affected.json` 归 B 组。）

### E. 运行日志与改动前备份（6 log + 2 json 快照 + 1 空文件）

- `_copyright_run.log`（796B，10-08 01:06）—— `kb_tools/ntce_copyright_scope.py` 一次 write 模式运行的 stdout（首行标题对得上该脚本第 157 行 print）：use_scope=research_non_commercial，更新 7,440、已是目标值 7,060、改写文件数 314；尾部来源性质分布 official_exam 10,381 / exam_recall 2,793 / compiled_selection 1,162 / provincial_exam 164 加学段×来源表。历史留痕。
- `_copyright_run2.log`（792B，01:07）—— 同命令幂等重跑：更新 0、已是目标值 14,500、改写文件数 0。历史留痕。
- `_copyright_run3.log`（794B，01:11）—— 再一次全量改写：更新 14,500、已是目标值 0、改写文件数 622；run2 与 run3 之间库为何回到未标注状态（如被回退），日志未载。历史留痕。
- `_repair_run1.log`（2,532B，10-07 23:22）—— `kb_tools/ntce_repair.py` 一次运行的 stdout：首行图构建统计 JSON（nodes 16,682 / edges 78,716），随后修复计数 JSON：structured_analysis_nonempty 4,734、source_type_repairs_total 152、nonobjective_letter_quarantined_total 446、material_links_recovered_total 490、trailing_cases_detached_total 195、expert_verified_questions 0（后五个键名现查出自 ntce_repair.py 的 stats；首行的 files 只列两个 graph 文件、note 为"L1→L2→L3→L4可遍历"，与当前 `build_graph.py` 的输出形状不一致，判为当时旧版构建器的打印）。历史留痕。
- `_repair_final.log`（2,533B，10-07 23:51）—— 同类运行，与 run1 仅差一个数：structured_analysis_nonempty 14,500（diff 现查）。历史留痕。
- `_repair_after_copyright.log`（2,533B，10-08 11:45）—— 与 `_repair_final.log` 字节相同（diff 现查为空），即版权标注之后复跑的同一计数。历史留痕。
- `_tmp_copyright_report.json`（42.7MB，10-09 19:45）—— `validate_kb.py` 全量输出快照：顶层键 generated_at/scope/complete/structure_errors/remaining_gaps/metrics/by_rule/issues 与现行验收结果一致，generated_at=2026-10-09T19:45:15+08:00，structure_errors 0、remaining_gaps 131,213。版权清权会话那次验收的历史留痕；重跑 `validate_kb.py` 可随时重建同类。
- `_tmp_loglist.txt`（0B，10-10 00:59）—— 空文件；用途未证实，仅按内容形状描述（推测为日志清点会话的重定向占位，未见任何脚本写它）。
- `_manifest_backup_before.json`（2.7KB，10-07 22:01）—— `数据集/教资/manifest.json` 修复前备份：name"教资真题知识库 v2"、generated 2026-10-02、source_files 695、questions 14,500、duplicate_questions_marked 1,619。当前 manifest 仍在且 generated 同为 2026-10-02，本文件是被替换前的字节留痕。
- `_stats_backup_before.json`（19.1KB，10-07 22:01）—— `数据集/教资/stats.json` 修复前备份：与现行 stats 键集相同（现查 26 键），analysis_nonempty 3,017 对现行 6,776，即逐题解析补全前的基线。
- `_work/` 内 13 个科目 json 的导出者虽不可考，但 `_serial_export*.py` 输出形状与其一致（见 C 组），故归入可重建类。

### F. 目录（3 个）

- `__pycache__/` —— 3 个 cpython-313 字节码（validate_kb、build_review_queue、状态词表检查），是这些入库脚本被 import 时 Python 自动生成的缓存；被 `.gitignore` 第 36 行全局 `__pycache__/` 排除；删了下次 import 自动重建。
- `_work/` —— 教资逐项解析的按科目导出缓存（README.md + 13 个科目 json；如 dili 49.1KB、yuwen 211.3KB，形状 `{qid:{stem,options,answer,level,subject,knowledge}}`）；目录内 `_work/README.md` 已自述用途与可删性；`.gitignore` 第 53 行 `审查/_work/` 排除；可由重跑 `_serial_export.py`/`_serial_export2.py`（指定输出到这些路径）重建，删了不影响任何测试与门禁。
- `harness_batches/` —— 2026-10-06/07 一轮 agent 会话批量补教资解析的运行产物（STATUS.json + input/ 54 个文件含 README + results/ 38 个文件含 README）；口径、批次进度与可否删除一律以 `审查/harness_batches/README.md` 为准，不在本节展开；`.gitignore` 第 55 行排除。

### 口径说明

1. 排除规则：`审查/_*.py`、`审查/_*.json`、`审查/_*.txt`、`审查/_tmp_*`、`审查/_work/`、`审查/harness_batches/` 在 `.gitignore` 第 49–56 行，`审查/_*.log` 由第 59 行 `审查/*.log` 排除，`__pycache__/` 由第 36 行全局规则排除（均经 `git check-ignore -v` 抽查确认）。本节 127 个条目一个都不在版本库里。
2. "可由脚本重跑"与"历史留痕"的区分：A/B 组数据文件除 `_affected.json`（有生成脚本）与 `_work/`（可由导出器重建）外，均未在仓库内找到写它们的脚本，属会话历史留痕——删掉不丢功能，但会话里未写回主题库的讲解产出（如 B 组 506+205+100 条文本）就只剩这些文件；`_opt2_gen_input.json`、`_opt_chuzhong_full/output.json`、`_opt2_art_partN.json`、`_opt_zhongxue_output.json` 等输入/输出已不在目录，相关 C 组脚本因此或跑不动或可自重建，逐条已注明。
3. 本节所有计数（条目数、null 数、集合包含关系、diff 结果、依赖文件存在性）都是 2026-10-12 现算；没有执行过任何临时脚本（含只读探针），"判可跑"仅是 import 目标与路径的静态核对。
