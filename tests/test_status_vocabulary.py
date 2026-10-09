"""两套主库共用同一状态词表与题目 schema，防止再次出现各库自造枚举。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "审查"))
sys.path.insert(0, str(ROOT / "kb_tools"))

from 状态词表检查 import ANSWER_STATES, REVIEW_STATES, collect  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

SCHEMA = json.loads((ROOT / "数据集/教资/schemas/question.json").read_text("utf-8"))
LIBS = {"NTCE": ROOT / "数据集/教资", "CET": ROOT / "数据集/四六级"}


def question_records(root):
    for path in sorted(root.joinpath("questions").rglob("*.jsonl")):
        for line in path.read_text("utf-8").split("\n"):
            if line.strip():
                rec = json.loads(line)
                if isinstance(rec, dict) and "question_id" in rec and "content" in rec:
                    yield rec


class SharedStatusVocabularyTests(unittest.TestCase):
    def test_entity_stores_use_only_contract_states(self):
        for name, root in LIBS.items():
            with self.subTest(lib=name):
                self.assertEqual({}, dict(collect(root)), "%s 存在越界状态值" % name)

    def test_enum_definitions_match_appendix_a1(self):
        self.assertEqual({"auto_parsed", "llm_enhanced", "checked", "expert_reviewed", "needs_fix", "quarantined"},
                         set(REVIEW_STATES))
        self.assertEqual({"verified", "letter_only", "reference_only", "missing", "source_conflict"},
                         set(ANSWER_STATES))

    def test_letter_and_reference_answers_carry_provenance(self):
        for name, root in LIBS.items():
            with self.subTest(lib=name):
                for rec in question_records(root):
                    if rec["content"]["answer_status"] in ("letter_only", "reference_only"):
                        self.assertTrue((rec.get("extra") or {}).get("answer_provenance"),
                                        rec["question_id"])

    def test_no_reviewer_less_human_review_stage_claims(self):
        for name, root in LIBS.items():
            with self.subTest(lib=name):
                for rec in question_records(root):
                    review = rec.get("review") or {}
                    if review.get("status") in ("checked", "expert_reviewed"):
                        self.assertTrue(review.get("checked_by"), rec["question_id"])

    def test_source_conflict_answers_are_never_scoreable(self):
        for name, root in LIBS.items():
            with self.subTest(lib=name):
                for rec in question_records(root):
                    if rec["content"]["answer_status"] == "source_conflict":
                        self.assertIsNone(rec["content"]["answer"], rec["question_id"])
                        self.assertEqual("quarantined", rec["review"]["status"], rec["question_id"])

    def test_both_libraries_validate_against_shared_question_schema(self):
        validator = Draft202012Validator(SCHEMA)
        for name, root in LIBS.items():
            checked = 0
            with self.subTest(lib=name):
                for rec in question_records(root):
                    errors = sorted(validator.iter_errors(rec), key=lambda e: list(e.path))
                    self.assertEqual([], errors, "%s: %s" % (name, rec.get("question_id")))
                    checked += 1
                self.assertGreater(checked, 5000)


if __name__ == "__main__":
    unittest.main()
