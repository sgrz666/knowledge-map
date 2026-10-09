"""教资 KB 状态词表契约迁移（幂等）。

把存储层统一到附录 A.1 规定的两套英文枚举：
  review.status      -> auto_parsed|llm_enhanced|checked|expert_reviewed|needs_fix|quarantined
  content.answer_status -> verified|letter_only|reference_only|missing|source_conflict
历史中文态与解析形状不丢弃：分别落到 review.review_priority 与 extra.answer_provenance，
供教研定位证据；不产生任何新的事实判定（不声称已复核、已授权、已标定）。
"""
import io
import json
import sys
import collections
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "数据集" / "教资"

REVIEW_STATES = ("auto_parsed", "llm_enhanced", "checked", "expert_reviewed", "needs_fix", "quarantined")
ANSWER_STATES = ("verified", "letter_only", "reference_only", "missing", "source_conflict")

# 答案可用性归约：字母型/文本参考型/缺失/冲突四类语义保持不变，只统一拼写。
ANSWER_ALIAS = {
    "letter": "letter_only",
    "brief": "reference_only",
    "reference": "reference_only",
    "derived_reference": "reference_only",
    "original_reference_draft_pending_expert": "reference_only",
    "official_source_available_pending_expert_review": "reference_only",
    "no_unique_answer_published": "missing",
}

# 复核态归约：中文态全部表示“尚未经教研复核”，不得升格为 checked/expert_reviewed。
REVIEW_ALIAS = {"已清洗": "auto_parsed", "待复核": "needs_fix", "低置信": "needs_fix",
                "待专家审核": "needs_fix", "待专家复核": "needs_fix", "专家审核": "needs_fix"}
PRIORITY = {"低置信": "low_confidence", "待复核": "flagged_general", "已清洗": "none"}
# 材料/资源侧把“来源抽取方式”写进了 review.status；状态与溯源需分开保存。
EXTRACTION_ALIAS = {"source_interval_recovered_pending_expert": "auto_parsed",
                    "source_parsed_pending_review": "auto_parsed"}
MODEL_METHODS = {"llm", "ai", "harness_llm", "qwen-plus_structured_v1",
                 "qwen-plus_deduced_candidate_v1", "llm_generated"}


def migrate_question(rec):
    stats = collections.Counter()
    content = rec.setdefault("content", {})
    extra = rec.setdefault("extra", {})
    review = rec.setdefault("review", {})

    raw_status = content.get("answer_status")
    if raw_status in ANSWER_ALIAS:
        content["answer_status"] = ANSWER_ALIAS[raw_status]
        if not extra.get("answer_provenance"):
            extra["answer_provenance"] = raw_status
        stats["answer_normalized"] += 1
    elif raw_status not in ANSWER_STATES:
        content["answer_status"] = "missing" if raw_status is None else raw_status
        stats["answer_unmapped"] += 1
    if not extra.get("answer_provenance"):
        extra["answer_provenance"] = "unspecified"

    # 隔离题（来源答案冲突）不进入判分，复核态应为 quarantined。
    legacy = review.get("status")
    if content["answer_status"] == "source_conflict":
        target = "quarantined"
    elif legacy in REVIEW_ALIAS:
        target = REVIEW_ALIAS[legacy]
    elif legacy in REVIEW_STATES:
        target = legacy
    else:
        target = "auto_parsed"
    analysis = rec.get("analysis")
    method = (analysis or {}).get("method") if isinstance(analysis, dict) else None
    if target == "auto_parsed" and method in MODEL_METHODS:
        target = "llm_enhanced"
    if target in ("checked", "expert_reviewed") and not review.get("checked_by"):
        target = "needs_fix"  # 无署名审核记录不算已审核
    review["status"] = target
    if legacy not in REVIEW_STATES:
        review["review_priority"] = PRIORITY.get(legacy, "unspecified")
        stats["review_normalized"] += 1
    review.setdefault("review_priority", "unspecified" if legacy is None else PRIORITY.get(legacy, "unspecified"))
    review.setdefault("checked_by", None)
    review.setdefault("checked_at", None)
    # tags.review 是 ntce_repair.refresh_tags 生成的镜像，必须与权威字段一致。
    mirror = (rec.get("tags") or {}).get("review")
    if isinstance(mirror, dict) and "status" in mirror:
        mirror["status"] = review["status"]
    return stats


def migrate_entity_review(rec):
    stats = collections.Counter()
    review = rec.get("review")
    if not isinstance(review, dict):
        return stats
    current = review.get("status")
    if current in EXTRACTION_ALIAS:
        review["status"] = EXTRACTION_ALIAS[current]
        review.setdefault("extraction_status", current)
        stats["extraction_status_moved"] += 1
    elif current not in REVIEW_STATES and current is not None:
        stats["review_unmapped:" + str(current)] += 1
    return stats


def migrate_jsonl(path):
    records, stats = [], collections.Counter()
    raw = path.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    # 正文可能含 U+2028/U+2029，只能用 \n 分行；splitlines 会把一条记录切成两半。
    for line in text.split("\n"):
        if not line.strip():
            continue
        rec = json.loads(line)
        if "content" in rec and "review" in rec:
            stats += migrate_question(rec)
        elif isinstance(rec, dict):
            stats += migrate_entity_review(rec)
        records.append(rec)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
    if raw != body:
        with io.open(str(path), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    return stats


CARD_KEYS = ("answer_status", "review_status")


def migrate_card(path):
    text = path.read_text("utf-8")
    if not text.startswith("---"):
        return False
    head, sep, rest = text.partition("\n---\n")
    if not sep:
        return False
    lines = head.splitlines()
    changed = False
    for i, line in enumerate(lines):
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "answer_status" and value in ANSWER_ALIAS:
            lines[i] = "answer_status: %s" % ANSWER_ALIAS[value]
            changed = True
        elif key == "review_status":
            mapped = REVIEW_ALIAS.get(value)
            if value not in REVIEW_STATES and mapped:
                lines[i] = "review_status: %s" % mapped
                changed = True
    if changed:
        path.write_text("\n".join(lines) + sep + rest, "utf-8")
    return changed


def main():
    total = collections.Counter()
    files = sorted(p for p in OUT.rglob("*.jsonl")
                   if "graph" not in p.parts and not any(part.startswith("_backup") for part in p.parts))
    for path in files:
        total += migrate_jsonl(path)
    cards = sorted(OUT.joinpath("cards").rglob("*.md"))
    card_changed = sum(migrate_card(p) for p in cards)

    after = collections.Counter()
    for path in files:
        for line in path.read_text("utf-8").split("\n"):
            if not line.strip():
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict):
                continue
            if "content" in rec and "review" in rec:
                after["review:" + rec["review"]["status"]] += 1
                after["answer:" + rec["content"]["answer_status"]] += 1
            else:
                review = rec.get("review")
                if isinstance(review, dict) and "status" in review:
                    after["entity_review:" + review["status"]] += 1
    print("question files:", len(files), "| cards rewritten:", card_changed, "of", len(cards))
    print("migration:", dict(total))
    print("live vocab:", json.dumps(dict(after.most_common()), ensure_ascii=False))
    bad = {k: v for k, v in after.items()
           if (k.startswith("review:") or k.startswith("entity_review:")) and k.split(":", 1)[1] not in REVIEW_STATES
           or (k.startswith("answer:") and k.split(":", 1)[1] not in ANSWER_STATES)}
    if bad:
        print("UNMAPPED:", json.dumps(bad, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
