"""从全量验收证据生成修复报告；不把局部测试通过写成知识库完整通过。"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "审查"


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build(validation_path):
    report = load(validation_path)
    baseline = load(OUT / "修复前基线.json")
    official = load(ROOT / "权威资料/verification_report.json")
    evidence_path = OUT / "验证运行记录.json"
    verification = load(evidence_path) if evidence_path.exists() else {}
    cet, ntce = report["metrics"]["cet"], report["metrics"]["ntce"]
    old_cet = baseline["cet"]["questions"]["counts"]
    old_ntce = baseline["ntce"]["questions"]["counts"]
    passage_repair_path = ROOT / "数据集/四六级/manifest/passage_reference_repair_report.json"
    passage_repair = load(passage_repair_path).get("summary", {}) if passage_repair_path.exists() else {}
    passage_repair_text = ""
    if passage_repair:
        passage_repair_text = (
            f"首次正式全量门禁另外发现{passage_repair['original_structure_errors']}处题目与语篇关联错误。"
            f"经完整原文复核，补齐{passage_repair['restored_original_error_backlinks_verified']}处反向引用，"
            f"恢复{passage_repair['complete_articles_restored_with_history']}份受污染或截短的完整语篇并保留旧文，"
            f"清除{passage_repair['inactive_parser_artifact_links_cleared']}条停用伪题的活动关联，"
            f"隔离{passage_repair['unproven_active_links_quarantined']}条无法唯一确认身份的关联并禁止自动判分。"
            "没有按ID末尾猜原题号，也没有替换保留题目的正文或答案。"
            "完整来源身份、正文边界和两次重跑证据见四六级manifest下的passage_reference_repair_report.json与passage_reference_idempotency_report.json。"
        )
    rows = []
    for title, key, old_key in [("全量题目条目", "total", "total"), ("知识点标签", "with_knowledge", "with_knowledge"),
                               ("能力标签", "with_ability", "with_ability_field"), ("具体考试要求字段", "with_requirement", "with_exam_requirement_id"),
                               ("答案字段有值", "with_answer", "with_answer"), ("有解析正文", "with_substantive_analysis_text", "with_analysis_content")]:
        rows.append(f"| {title} | {old_cet.get(old_key, 0)} → {cet.get(key, 0)} | {old_ntce.get(old_key, 0)} → {ntce.get(key, 0)} |")
    gaps = Counter((i.get("dataset", "official"), i["rule"]) for i in report["issues"] if i["severity"] == "gap")
    accepted_pending_rules = {
        "Q_CONTENT_PENDING_REVIEW", "R_CONTENT_PENDING_REVIEW",
        "Q_DIFFICULTY_MISSING", "R_DIFFICULTY_MISSING",
        "Q_DIFFICULTY_UNCALIBRATED", "R_DIFFICULTY_UNCALIBRATED",
    }
    accepted_pending = Counter(i["rule"] for i in report["issues"]
                               if i["severity"] == "gap" and i["rule"] in accepted_pending_rules
                               and i.get("dataset") in {"cet", "ntce"})
    supplemental_pending = Counter(i["rule"] for i in report["issues"]
                                  if i["severity"] == "gap" and i["rule"] in accepted_pending_rules
                                  and i.get("dataset") not in {"cet", "ntce"})
    other_gaps = sum(i["severity"] == "gap" and i["rule"] not in accepted_pending_rules
                     for i in report["issues"])
    remaining = []
    for title, rules in [("缺少可用答案", ("Q_ANSWER_MISSING",)), ("答案来源冲突", ("Q_ANSWER_SOURCE_CONFLICT",)),
                         ("答案缺来源或未绑定本题", ("Q_ANSWER_SOURCE_UNLOCATED", "Q_ANSWER_BINDING_PENDING", "Q_ANSWER_IDENTITY_MISMATCH")),
                         ("解析缺失或结构不完整", ("Q_ANALYSIS_MISSING", "Q_ANALYSIS_INCOMPLETE", "Q_ANALYSIS_UNSTRUCTURED")),
                         ("选项或共享词库不足", ("Q_OPTIONS_INCOMPLETE",)), ("题目源边界需复核", ("Q_SOURCE_BOUNDARY_AMBIGUOUS",)),
                         ("题型未核定", ("Q_TYPE_UNVERIFIED",)), ("题干任务缺失", ("Q_STEM_EMPTY",)),
                         ("阅读语篇未关联（含停用审计记录）", ("Q_PASSAGE_UNLINKED",)),
                         ("额外条款映射缺依据", ("Q_REQUIREMENT_BINDING_UNSUPPORTED",)),
                         ("知识点未挂载", ("Q_KNOWLEDGE_MISSING",)), ("能力未挂载", ("Q_ABILITY_MISSING",)),
                         ("缺具体考试要求", ("Q_REQUIREMENT_MISSING",)), ("自动要求映射待复核", ("Q_REQUIREMENT_MAPPING_PENDING_REVIEW",)),
                         ("音频缺失或未分段", ("Q_AUDIO_UNLINKED", "Q_AUDIO_SEGMENT_UNSPECIFIED")),
                         ("版权使用范围未明确", ("Q_COPYRIGHT_UNRESOLVED",)), ("难度未标定", ("Q_DIFFICULTY_MISSING", "Q_DIFFICULTY_UNCALIBRATED")),
                         ("内容待专家审核", ("Q_CONTENT_PENDING_REVIEW",))]:
        remaining.append(f"| {title} | {sum(gaps['cet', rule] for rule in rules)} | {sum(gaps['ntce', rule] for rule in rules)} |")
    source_examples = []
    for folder, label in [("教资官方样题", "教资官方样题"), ("四六级官方样题", "四六级官方样卷"), ("教资参考解答", "幼儿保教原创参考")]:
        path = ROOT / "补充资料" / folder / "summary.json"
        if path.exists():
            summary = load(path)
            source_examples.append(f"- {label}：完整数据和覆盖计数见 `补充资料/{folder}/summary.json`，使用方法见该目录README。快照：`{json.dumps({k: v for k, v in summary.items() if isinstance(v, (int, bool))}, ensure_ascii=False)}`。")
    test_text = "正式运行记录尚未保存，以实际输出为准。"
    if verification:
        test_text = "; ".join(f"{r['command']}：退出{r['exit_code']}" for r in verification.get("runs", []))
    tests = [r for r in verification.get("runs", []) if "test_count" in r]
    test_count_text = "; ".join(f"{r['test_count']}项测试，退出{r['exit_code']}" for r in tests)
    text = f"""# 四六级与教资知识库修复验收报告

证据生成于 {report['generated_at']}。本报告覆盖两套库全量题目和学习资源，并使用完整问题队列；没有通过缩小题库来提高通过率。

**结构错误：{report['structure_errors']}；内容及状态待补事项：{report['remaining_gaps']}；完整验收：{'通过' if report['complete'] else '未通过'}。** 当前库可用于继续建设、查看原料及审查草稿，不能把待审核答案与评分结果当作已经核定的考试参考。

用户已确认当前没有教研审核记录、难度标注或学生作答数据，允许保留待审核与待标定状态。两套主库当前单列保留：题目内容待专家审核 {accepted_pending['Q_CONTENT_PENDING_REVIEW']} 项、学习资源内容待专家审核 {accepted_pending['R_CONTENT_PENDING_REVIEW']} 项、题目难度待标定 {accepted_pending['Q_DIFFICULTY_MISSING']} 项。另行校验的官方样卷补充集有 {supplemental_pending['Q_CONTENT_PENDING_REVIEW']} 项题目审核、{supplemental_pending['R_CONTENT_PENDING_REVIEW']} 项资源审核和 {supplemental_pending['Q_DIFFICULTY_MISSING']} 项题目难度待标定，不混入主库覆盖计数。这些状态依然计入完整验收；答案、选项、原文材料等缺口另列，不能因为允许待审核而视为已有正文。

除上述允许保留的审核与标定状态外，仍有 {other_gaps} 项其他待补事项，同一题或资源可能对应多项。这表明完整性缺口不只是专家审核与难度标定。

## 已修复和补全

| 指标 | 四六级修复前 → 当前 | 教资修复前 → 当前 |
| --- | --- | --- |
{chr(10).join(rows)}

这些是字段或正文覆盖数，并不证明标签、答案已经经过专家确认。教资原“解析”包含缺、略、字母串及拼串，修复后改为实质正文统计，前后口径差异已明确。来源冲突及失去证据的自动答案退出判分字段，保留历史，答案数量下降不能据此判定数据丢失。

当前完整三段解析：四六级 {cet.get('with_complete_structured_analysis', 0)}，教资 {ntce.get('with_complete_structured_analysis', 0)}。按本验收器规则可用的答案字段：四六级 {cet.get('with_usable_answer_field', 0)}，教资 {ntce.get('with_usable_answer_field', 0)}；这个指标没有代替题干、选项、来源边界或专家内容审核。

四六级当前标为活动状态的记录 {cet.get('active_records', 0)}，保留的已停用编号伪题 {cet.get('retained_parser_artifacts', 0)}。活动状态只表示仍进入建设与复核，不等于可以发布或判分；基线ID保留、新来源待核记录和解析伪题分别记录，不将新增条目全部称为新恢复真题。

官方归档核验：{official['verified_source_count']}/{official['source_count']}个来源，{official['requirement_count']}个可定位条目，{official['written_outline_boundary_count']}科笔试正文边界，{official['official_interview_criterion_count']}项面试评分和{official['official_cet_band_count']}档写译评分，错误 {official['error_count']}。条目ID保持稳定，废弃抽取错误进入退休清单；来源核验不等于试题答案审核。

修复了四六级阅读误挂听力根节点、资源重复ID和多来源路径、旧听力题组混用阅读语篇引用、跨模块考试要求；恢复源文写译内容，修正先修关系状态。教资扩展细知识点和能力边，修复模块遍历、绝对原料偏移与题号边界，隔离冲突/占位答案，保留人工内容与重复卷历史。两套库采用明确的待审状态，增量生成不会用默认空字段抹掉已经补充的记录。

{passage_repair_text}

{chr(10).join(source_examples)}

## 对照设计文档

| 设计要求 | 当前证据与边界 |
| --- | --- |
| 标准和权威来源可追溯 | 官方原件、URL、版本、哈希、条目定位及退休记录已建立；现行CSE取得官方描述语数据集，整本出版PDF及CET/CSE正式对接未取得。 |
| 考试→模块→具体知识点→题目 | 引用及图谱结构进入全量验收；自动细点拆解、语义对齐和候选先修关系仍需教研复核，候选边不能直接安排正式路径。 |
| 每题、每资源绑定知识点、能力、要求 | 字段覆盖见表；全量资源也独立验收，未挂载与待对齐均保留任务。 |
| 题干、选项、语篇、答案、三段解析 | 逐题检查并保留缺口；共享词库、跨题污染、源文件缺图与文本提取漏图分别处理，不能仅按题号回填答案。 |
| 写译、材料分析与面试量规 | 已取得官方总体评分与面试细则；练习用维度、逐题评分要点和AI参考解答明确标为非正式评分并待审。 |
| 来源真实性与版权标签 | 本地文件存在不等于真实历年试卷或已获出版授权。历史题源矛盾、未知使用范围、来源冲突均保留真实状态。 |
| 难度与专家审核 | 用户确认目前无对应审核/作答数据，按要求保留待审核、待标定；不编造IRT数值、专家姓名或已发布状态。 |
| F1–F7运行时功能 | 当前交付是静态库修复与资料补全。用户掌握度、作答日志、自适应诊断、推荐和音视频评分需要后续应用实现，不能由静态JSONL声明完成。 |

## 全库剩余内容与状态

| 逐题待补事项 | 四六级 | 教资 |
| --- | --- | --- |
{chr(10).join(remaining)}

同一题可以有多个待补事项。全库还检查了 {cet['learning_resources']} 项四六级学习资源和 {ntce['learning_resources']} 项教资共享材料；资源缺口与题目缺口分别保存，不能只看题目完整率。所有明细在 `知识库待补队列.jsonl` 与 `知识库验收结果.json`。

## 测试与使用

正式命令记录：{test_text}

回归实际计数：{test_count_text or '尚未保存正式运行计数'}。

在 `D:\\codeplus\\knowledge_map` 分开执行：

```powershell
python -m unittest discover -s tests -v
python 权威资料/verify_sources.py
python 审查/知识库形式审查.py
python 审查/validate_kb.py
python 审查/build_repair_summary.py
```

单元测试验证修复行为，官方核验检查原件和条目。全量验收存在任意错误或待补时退出1，完全齐备时才退出0；本次未通过的内容不可因测试成功而忽略。

按物理行读取题目JSONL，用 `knowledge_node_ids`、`ability_ids`、`exam_requirement_ids` 连接本体和官方要求；用 `material_id` 或 `extra.passage_id` 连接共享原文。先查看来源与审核状态，再使用答案或量规。详细入口、示例代码和复跑顺序见 `知识库修复与使用说明.md` 及各库README。

## 证据文件

- 全量验收：`{validation_path.relative_to(ROOT).as_posix()}`，SHA-256 `{hashlib.sha256(validation_path.read_bytes()).hexdigest()}`。
- 修复前基线：`审查/修复前基线.json`，保持原始快照。
- 官方核验：`权威资料/verification_report.json`；完整来源在 `catalog.json` 和 `requirements.jsonl`。
- 实际测试命令和退出码：`审查/验证运行记录.json`；未记录的检查不能据本报告视为完成。
"""
    destination = OUT / "四六级与教资修复验收报告.md"
    destination.write_text(text, encoding="utf-8")
    print(str(destination))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-file", type=Path, default=OUT / "知识库验收结果.json")
    build(parser.parse_args().validation_file.resolve())
