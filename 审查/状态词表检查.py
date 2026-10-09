"""全库状态词表结构自检：所有 review.status / content.answer_status 必须落在附录 A.1 枚举内。"""
import json
import io
import glob
import collections
import ntpath
import sys

REVIEW_STATES = ("auto_parsed", "llm_enhanced", "checked", "expert_reviewed", "needs_fix", "quarantined")
ANSWER_STATES = ("verified", "letter_only", "reference_only", "missing", "source_conflict")
PROVENANCE_REQUIRED = ("letter_only", "reference_only")


def walk(node, where, bad):
    """只检查实体顶层契约字段；extra 内的历史 before/candidate 快照保留旧拼写作为证据。"""
    if isinstance(node, list):
        for item in node:
            walk(item, where, bad)
        return
    if not isinstance(node, dict):
        return
    content = node.get("content")
    review = node.get("review")
    if isinstance(review, dict) and "status" in review and review["status"] not in REVIEW_STATES:
        bad["review.status=" + str(review.get("status")) + "@" + where] += 1
    if isinstance(content, dict) and "answer_status" in content:
        st = content["answer_status"]
        if st not in ANSWER_STATES:
            bad["answer_status=" + str(st) + "@" + where] += 1
        if st in PROVENANCE_REQUIRED and not (node.get("extra") or {}).get("answer_provenance"):
            bad["missing_provenance@" + where] += 1
    extra = node.get("extra")
    if isinstance(extra, dict) and "answer_status" in extra:
        bad["legacy_extra.answer_status@" + where] += 1
    for key, value in node.items():
        if key in ("content", "review", "extra", "source"):
            continue
        walk(value, where, bad)


SKIP_DIRS = {"graph", "schemas", "manifest", "review"}  # 报告与图谱派生物保留历史快照拼写，不作实体校验


def collect(root):
    """返回 {违规描述: 次数}；空表示实体库全部落在契约枚举内。"""
    bad = collections.Counter()
    files = glob.glob(str(root) + "/**/*.jsonl", recursive=True) + glob.glob(str(root) + "/**/*.json", recursive=True)
    scanned = 0
    for path in files:
        parts = path.replace("\\", "/").split("/")
        if any(part.startswith("_backup") or part in SKIP_DIRS for part in parts):
            continue
        where = "/".join(parts[1:-1])
        try:
            if path.endswith(".jsonl"):
                rows = [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]
            else:
                rows = [json.load(io.open(path, encoding="utf-8"))]
        except Exception as exc:
            bad["parse_fail@" + where + ":" + type(exc).__name__] += 1
            continue
        scanned += len(rows)
        for row in rows:
            walk(row, where, bad)
    collect.scanned = scanned
    return bad


def main(root):
    bad = collect(root)
    print("scanned records:", collect.scanned, "| violations:", sum(bad.values()))
    print(json.dumps(dict(bad.most_common(40)), ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "数据集/教资"))
