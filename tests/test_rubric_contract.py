"""量规契约：题内练习框架与附录 A.6 可计算量规分离，权重唯一真相在 rubrics/*.json。

覆盖三类曾被破坏的不变式：
  - 选择题按选项字母判分，不得携带主观题评分框架（曾有 152 道带无 ID 的影子框架）；
  - 一个维度只允许一套名称/档位/权重，name+levels+max_level 与 dimension_name+criteria_levels+weight_score 并存即双真相；
  - expert_verified 只在有具名审核人时成立，自动化不得声称已核。
权重本身属于教研待核定内容，本测试只锁定"权重未被署名通过时必须在待复核队列里"，不校验权重取值。
"""
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kb_tools"))

from ntce_repair import CHOICE_TYPES, drop_choice_framework  # noqa: E402

NTCE = ROOT / "数据集" / "教资"
LIBS = {"NTCE": NTCE, "CET": ROOT / "数据集" / "四六级"}
SCHEMAS = {p.stem: json.loads(p.read_text("utf-8")) for p in (NTCE / "schemas").glob("*.json")}


def rows(path):
    return [json.loads(line) for line in path.read_text("utf-8").split("\n") if line.strip()]


def questions(root):
    for path in sorted(root.joinpath("questions").rglob("*.jsonl")):
        for record in rows(path):
            yield record


def rubric_of(record):
    extra = record.get("extra") or {}
    return record.get("rubric") or extra.get("rubric") or extra.get("scoring_rubric")


def canonical_rubrics():
    for path in sorted((NTCE / "rubrics").glob("*.json")):
        if path.name == "official_interview.json":
            continue  # 官方面试评分口径原文，不是可计算量规实体
        payload = json.loads(path.read_text("utf-8"))
        for entry in (payload if isinstance(payload, list) else [payload]):
            if isinstance(entry, dict) and entry.get("rubric_id"):
                yield path, entry


class RubricContractTests(unittest.TestCase):
    def test_choice_questions_never_carry_subjective_framework(self):
        choice_total = 0
        for name, root in LIBS.items():
            for record in questions(root):
                if record.get("question_type") not in CHOICE_TYPES:
                    continue
                choice_total += 1
                self.assertIsNone(rubric_of(record), f"{name}: 选择题 {record.get('question_id')} 携带主观题评分框架")
                self.assertIsNone(record.get("rubric_id"), f"{name}: 选择题 {record.get('question_id')} 绑定量规 ID")
        self.assertGreater(choice_total, 10000)

    def test_canonical_rubrics_are_computable_single_truth(self):
        validator = jsonschema.Draft202012Validator(SCHEMAS["rubric"])
        files = 0
        for path, rubric in canonical_rubrics():
            files += 1
            errors = list(validator.iter_errors(rubric))
            self.assertEqual([], errors, f"{path.name} 不符合 A.6 量规 Schema: {[e.message for e in errors]}")
            weights = [dimension["weight_score"] for dimension in rubric["dimensions"]]
            self.assertAlmostEqual(rubric["total_score"], sum(weights), places=6,
                                   msg=f"{path.name}: 维度权重之和必须等于满分")
            self.assertEqual(len(set(dimension["dimension_name"] for dimension in rubric["dimensions"])),
                             len(weights), f"{path.name}: 维度名必须唯一")
            for dimension in rubric["dimensions"]:
                for level in dimension["criteria_levels"]:
                    self.assertLessEqual(max(level["score_range"]), dimension["weight_score"],
                                         f"{path.name}: 档位上界不得超过维度权重")
        self.assertEqual(6, files, "六套加权量规实体应全部在册")

    def test_inline_frameworks_stay_unweighted_and_addressable(self):
        framework_validator = jsonschema.Draft202012Validator(SCHEMAS["practice_framework"])
        checked = 0
        for record in questions(NTCE):
            rubric = rubric_of(record)
            if not isinstance(rubric, dict):
                continue
            checked += 1
            errors = list(framework_validator.iter_errors(rubric))
            self.assertEqual([], errors, f"{record.get('question_id')} 题内框架不符合 Schema: {[e.message for e in errors]}")
            self.assertEqual(record.get("rubric_id"), rubric.get("rubric_id"),
                             f"{record.get('question_id')}: 题目与框架的量规 ID 必须同值，否则 has_rubric 边断裂")
            self.assertEqual("rubric." + record["question_id"], rubric["rubric_id"])
            for dimension in rubric["dimensions"]:
                self.assertNotIn("weight_score", dimension, "题内框架不得携带权重，权重只属于 rubrics/*.json 实体")
                self.assertNotIn("criteria_levels", dimension, "题内框架不得携带档位分值")
        self.assertGreater(checked, 3000)

    def test_expert_claim_requires_named_reviewer(self):
        carriers = [(path.name, rubric) for path, rubric in canonical_rubrics()]
        for root in LIBS.values():
            carriers += [(record.get("question_id"), rubric_of(record)) for record in questions(root)
                         if isinstance(rubric_of(record), dict)]
        for label, rubric in carriers:
            if rubric.get("expert_verified") is True:
                review = rubric.get("review") if isinstance(rubric.get("review"), dict) else {}
                self.assertTrue(rubric.get("checked_by") or review.get("checked_by"),
                                f"{label}: expert_verified 却没有具名审核人")

    def test_unapproved_weights_stay_in_review_queue(self):
        for path, rubric in canonical_rubrics():
            review = rubric.get("review") or {}
            if review.get("status") != "expert_reviewed":
                self.assertIn("rubric_dimension_weights_pending_subject_expert", review.get("pending_reasons", []),
                              f"{path.name}: 权重未经教研签署时必须写明待办理由，供待复核清单收录")

    def test_repair_writer_strips_choice_framework_but_keeps_manual_work(self):
        stale = {"question_id": "ntce.demo.q01", "question_type": "单选",
                 "rubric": {"rubric_id": "rubric.ntce.demo.q01",
                            "status": "practice_framework_pending_subject_expert",
                            "question_specific_points": [], "dimensions": [{"name": "要点覆盖"}]},
                 "rubric_id": "rubric.ntce.demo.q01"}
        self.assertTrue(drop_choice_framework(stale))
        self.assertNotIn("rubric", stale)
        self.assertNotIn("rubric_id", stale)

        reviewed = {"question_id": "ntce.demo.q02", "question_type": "多选",
                    "rubric": {"checked_by": "teacher-1", "question_specific_points": ["正确解释大气分层"]},
                    "rubric_id": "rubric.ntce.demo.q02"}
        self.assertFalse(drop_choice_framework(reviewed))
        self.assertEqual("teacher-1", reviewed["rubric"]["checked_by"])
        self.assertEqual("rubric.ntce.demo.q02", reviewed["rubric_id"])


if __name__ == "__main__":
    unittest.main()
