"""卡片 frontmatter 的 answer 必须是题记录 content.answer 的镜像。

只读模式：逐张比对 `数据集/*/cards/**/*.md` 头部 `answer:` 与 `questions/**/*.jsonl`
的 `content.answer`，把差异分成三类打印出来，不落盘。
写入模式：`--apply` 以题记录为唯一权威改写 `answer:` 那一行（正文与其余字段不动），
`--apply --dry-run` 只打印 diff 摘要（张数 + 样本）不写文件。

判据（权威值 None -> 字面量 `null`，与 YAML 空值口径一致；字符串 -> 原值逐字相等）：
  1. 一致            —— 卡片值 == 期望值
  2. 占位词但题记录有值 —— 卡片值是生成器留下的占位词（`有` / `未提供`），题记录却有真实答案
  3. 双向都不符      —— 其余所有不一致（含卡片有值而题记录为 null、拼写漂移等）
"""
import argparse
import collections
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "kb_tools"))

from ntce_io import atomic_write  # noqa: E402  原子写，避免半截文件

LIBS = {"NTCE": os.path.join(ROOT, "数据集", "教资"), "CET": os.path.join(ROOT, "数据集", "四六级")}
# 生成器历史上给非选择题写的占位词；题记录为 None 时期望值只有 `null`
PLACEHOLDERS = ("有", "未提供")
APPLY_ALLOWED_LIBS = ("NTCE",)


def authoritative_answers(root):
    """{question_id: content.answer}；以题记录为唯一权威。"""
    out = {}
    qdir = os.path.join(root, "questions")
    for dirpath, _dirnames, filenames in os.walk(qdir):
        for name in sorted(filenames):
            if not name.endswith(".jsonl"):
                continue
            with io.open(os.path.join(dirpath, name), encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if isinstance(rec, dict) and "question_id" in rec and "content" in rec:
                        out[rec["question_id"]] = rec["content"].get("answer")
    return out


def expected_display(answer):
    """题记录答案 -> 卡片头部期望文本。"""
    if answer is None:
        return "null"
    if isinstance(answer, str):
        return answer
    return json.dumps(answer, ensure_ascii=False)


def read_card_header(path):
    """返回 (fields, 行号列表)；非 frontmatter 卡片返回 (None, None)。"""
    with io.open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    if not lines or lines[0].strip() != "---":
        return None, None
    fields = {}
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return fields, lines
        if line[:1] in (" ", "-", "\t"):
            continue
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields, lines


def scan(root, authoritative, samples_limit, report):
    """逐张分类，返回 (计数 dict, 待修卡片列表)。"""
    counts = collections.Counter()
    to_fix = []
    scanned = 0
    cards = os.path.join(root, "cards")
    if not os.path.isdir(cards):
        return counts, to_fix
    for dirpath, _dirnames, filenames in os.walk(cards):
        for name in sorted(filenames):
            if not name.endswith(".md") or name == "README.md":
                continue
            path = os.path.join(dirpath, name)
            scanned += 1
            fields, lines = read_card_header(path)
            if fields is None:
                counts["无 frontmatter 而跳过"] += 1
                continue
            question_id = fields.get("id")
            if question_id not in authoritative:
                counts["卡片 id 无对应题记录"] += 1
                report["孤儿卡片"].append(path)
                continue
            if fields.get("answer_status") == "source_conflict":
                counts["隔离题卡片"] += 1
                if fields.get("answer") != "null":
                    counts["隔离题卡片答案非 null"] += 1
            got = fields.get("answer")
            if got is None:
                counts["卡片缺 answer 键"] += 1
                continue
            want = expected_display(authoritative[question_id])
            if got == want:
                counts["一致"] += 1
                continue
            if got in PLACEHOLDERS and authoritative[question_id] is not None:
                counts["占位词但题记录有值"] += 1
                kind = "placeholder"
            else:
                counts["双向都不符"] += 1
                kind = "mismatch"
            to_fix.append({"path": path, "id": question_id, "kind": kind,
                           "line": _answer_line_index(lines), "got": got, "want": want})
            if len(report[kind]) < samples_limit:
                report[kind].append({"path": os.path.relpath(path, ROOT), "id": question_id,
                                     "card": got, "record": want})
    counts["扫卡总数"] = scanned
    return counts, to_fix


def _answer_line_index(lines):
    """返回 frontmatter 内 `answer:` 键所在行号（不含缩进行）。"""
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            break
        if line[:1] in (" ", "-", "\t"):
            continue
        key, separator, _value = line.partition(":")
        if separator and key.strip() == "answer":
            return index
    return None


def apply_fixes(items):
    """只改写 answer 那一行，正文一个字节都不动。"""
    changed = 0
    for item in items:
        fields, lines = read_card_header(item["path"])
        index = _answer_line_index(lines)
        if index is None:
            continue
        newline = "answer: %s" % item["want"]
        if lines[index] == newline:
            continue
        lines[index] = newline
        atomic_write(__import__("pathlib").Path(item["path"]), "\n".join(lines))
        changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(description="卡片 answer 与题记录的镜像检查/修复")
    parser.add_argument("--lib", default="all", choices=["all", "NTCE", "CET"])
    parser.add_argument("--apply", action="store_true", help="以题记录为权威改写卡片 frontmatter")
    parser.add_argument("--dry-run", action="store_true", help="配合 --apply：只打印 diff 摘要不写盘")
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()

    names = list(LIBS) if args.lib == "all" else [args.lib]
    total_bad = 0
    for name in names:
        root = LIBS[name]
        authoritative = authoritative_answers(root)
        report = collections.defaultdict(list)
        counts, to_fix = scan(root, authoritative, args.samples, report)
        print("=== %s (%s) ===" % (name, os.path.relpath(root, ROOT)))
        print("题记录数: %d" % len(authoritative))
        for key in ("扫卡总数", "一致", "占位词但题记录有值", "双向都不符", "隔离题卡片", "隔离题卡片答案非 null",
                    "卡片缺 answer 键", "卡片 id 无对应题记录", "无 frontmatter 而跳过"):
            if counts.get(key):
                print("  %-22s %d" % (key, counts[key]))
        for kind, title in (("placeholder", "占位词但题记录有值"), ("mismatch", "双向都不符"),
                            ("孤儿卡片", "孤儿卡片")):
            rows = report[kind]
            if rows:
                print("  [%s] 样本（最多 %d 条）:" % (title, args.samples))
                for row in rows[:args.samples]:
                    print("    %s" % json.dumps(row, ensure_ascii=False))
        total_bad += counts.get("占位词但题记录有值", 0) + counts.get("双向都不符", 0)
        if not to_fix:
            continue
        if name not in APPLY_ALLOWED_LIBS:
            print("  提示: %s 不在本次允许改写范围内，仅报告不修复。" % name)
            continue
        if not args.apply:
            print("  只读模式：加 --apply 才落盘修复（共 %d 张待修）。" % len(to_fix))
            continue
        if args.dry_run:
            print("  dry-run diff 摘要：待改写 %d 张，样本如下" % len(to_fix))
            for item in to_fix[:args.samples]:
                print("    %s: answer: %s -> answer: %s" % (
                    os.path.relpath(item["path"], ROOT), item["got"], item["want"]))
            continue
        changed = apply_fixes(to_fix)
        print("  已改写 %d 张卡片的 answer 行。" % changed)
    return 1 if total_bad and not args.apply else 0


if __name__ == "__main__":
    sys.exit(main())
