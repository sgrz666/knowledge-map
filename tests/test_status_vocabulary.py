"""两套主库共用同一状态词表与题目 schema，防止再次出现各库自造枚举。"""
import json
import re
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

    def test_card_frontmatter_mirrors_authoritative_states(self):
        """卡片头部两轨同表：review_status/answer_status 必须是题记录的镜像，不得各自演化。"""
        for name, root in LIBS.items():
            cards = root.joinpath("cards")
            if not cards.is_dir():
                continue
            authoritative = {rec["question_id"]: (rec["review"]["status"], rec["content"]["answer_status"])
                             for rec in question_records(root)}
            checked = 0
            with self.subTest(lib=name):
                for path in sorted(cards.rglob("*.md")):
                    if path.name == "README.md":
                        continue
                    fields = {}
                    with path.open(encoding="utf-8") as handle:
                        if handle.readline().strip() != "---":
                            continue
                        for line in handle:
                            if line.strip() == "---":
                                break
                            key, separator, value = line.partition(":")
                            if separator and not line.startswith((" ", "-", "\t")):
                                fields[key.strip()] = value.strip()
                        question_id = fields.get("id")
                        self.assertIn(question_id, authoritative, "%s 卡片的 id 没有对应题记录: %s" % (name, path))
                        want_review, want_answer = authoritative[question_id]
                        self.assertEqual((want_review, want_answer),
                                         (fields.get("review_status"), fields.get("answer_status")),
                                         "%s: %s" % (name, question_id))
                        if want_answer == "source_conflict":
                            # 隔离题的卡片正文不得断言具体答案，否则污染向量库并冒充已核定标答。
                            for line in handle:
                                for marker in ("正确答案", "参考答案"):
                                    pos = line.find(marker)
                                    if pos < 0:
                                        continue
                                    tail = line[pos + len(marker):].strip().strip(" :：*`")
                                    if not re.fullmatch(r"[A-O]", tail):
                                        continue
                                    self.fail("%s 隔离题卡片断言了具体答案 %r: %s" % (name, tail, path))
                    checked += 1
                self.assertGreater(checked, 1000)

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
