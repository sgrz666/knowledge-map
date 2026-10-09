"""题内评分框架与官方量规的契约归一（幂等）。

三件事，都不新增任何"已审核"的声称：
  1. 单选/多选等选择题不得携带主观题评分框架（库里曾有 152 道选择题带着无 rubric_id 的五维
     练习框架，既不入图也不可判分，只有卡片正文能看到，属于影子量规）。剥离规则与
     ntce_repair.drop_choice_framework 共用同一实现，避免两处漂移。
  2. 官方量规实体（rubrics/*.json）统一到附录 A.6 形状：一个维度只留一套名称与一套档位，
     删掉与 dimension_name/criteria_levels 并存的 name/levels/max_level 旧字段（两者措辞并不相同，
     max_level 还与四档 criteria_levels 矛盾，消费端取哪一份就会得到哪种分数，属双真相）。
  3. 量规实体原先写死 `expert_verified: true` 却没有任何审核人/时间/证据；本脚本把它降回
     `false` + `review.status = needs_fix`，并把待办理由显式写进 review.pending_reasons 供教研排队。

用法：PYTHONIOENCODING=utf-8 python kb_tools/ntce_rubric_contract.py [--dry-run]
迁移前的原始 rubrics/ 与受影响题目文件快照在 归档/教资_迁移前快照_20261009/。
"""
import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kb_tools"))
from ntce_repair import CHOICE_TYPES, drop_choice_framework  # noqa: E402

OUT = ROOT / "数据集" / "教资"
LEGACY_DIMENSION_KEYS = ("name", "levels", "max_level")
RUBRIC_PENDING = ["rubric_dimension_weights_pending_subject_expert",
                  "rubric_descriptor_wording_pending_subject_expert"]


def read_rows(path):
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def write_rows(path, records):
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(body.encode("utf-8"))
    temp.replace(path)


def normalize_canonical_rubric(data, stats):
    """把 附录 A.6 之外的旧字段与未经核实的审核声称一并纠正。"""
    changed = False
    for dimension in data.get("dimensions") or []:
        for key in LEGACY_DIMENSION_KEYS:
            if key in dimension:
                dimension.pop(key)
                stats["legacy_dimension_keys_removed"] += 1
                changed = True
    if data.get("expert_verified") and not (data.get("review") or {}).get("checked_by"):
        data["expert_verified"] = False
        stats["expert_claim_downgraded"] += 1
        changed = True
    review = data.setdefault("review", {})
    if not review.get("checked_by"):
        review.setdefault("status", "needs_fix")
        review.setdefault("checked_by", None)
        review.setdefault("checked_at", None)
        review["pending_reasons"] = RUBRIC_PENDING
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写盘")
    args = parser.parse_args()

    stats = collections.Counter()
    for path in sorted((OUT / "questions").glob("*/*/*.jsonl")):
        records = read_rows(path)
        touched = 0
        for record in records:
            if record.get("question_type") in CHOICE_TYPES and drop_choice_framework(record):
                touched += 1
        if not touched:
            continue
        stats["dropped_from_choice"] += touched
        if not args.dry_run:
            write_rows(path, records)

    for path in sorted((OUT / "rubrics").glob("*.json")):
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict) or "dimensions" not in data:
            continue  # official_interview.json 是官方面试评分口径原文，不是可计算量规实体
        if normalize_canonical_rubric(data, stats) and not args.dry_run:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print(("dry-run " if args.dry_run else "") + json.dumps(dict(stats), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
