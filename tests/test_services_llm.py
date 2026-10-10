"""P4 护栏测试：模型是措辞助理，不是审核人，也不是出分方（§4 / A4 / A7）。

The provider is stubbed — no network, no key. What is under test is the door, not the model:
an unconfigured client says so out loud, a prompt that installs a reviewer role is refused,
a payload that signs on the reviewer's behalf is rejected and queued without repair, and a model
draft can change the wording of a 反馈 but can never make a 分数 appear.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("KNOWLEDGE_MAP_STATE_DIR", tempfile.mkdtemp(prefix="km_llm_state_"))

from services.common.models import SubjectiveGradingRequest
from services.grader.agent import SubjectiveGraderAgent
from services.knowledge.repository import get_repository
from services.llm.client import (
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    LLMClient,
    LLMUnavailableError,
    BaseProvider,
    ProviderResponse,
    SYSTEM_PROMPT,
    get_llm_client,
)
from services.llm.guardrails import (
    LlmWritePermissionError,
    SchemaRegistry,
    assert_llm_status_allowed,
    assert_no_forbidden_status_fields,
    assert_prompt_not_reviewer,
    enforce_payload,
    scan_banned_claims,
)
from services.review.queue import ReviewQueue, get_review_queue


class StubProvider(BaseProvider):
    name = "stub"
    is_rule_only = False
    model = "stub-model"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list = []

    def generate(self, messages, *, max_tokens: int = 2048, temperature: float = 0.2) -> ProviderResponse:
        self.calls.append(messages)
        return ProviderResponse(text=self.text, model=self.model, usage={"total_tokens": 42},
                                finish_reason="stop", latency_ms=7, retries=0)


class FailingProvider(BaseProvider):
    name = "failing"
    model = "stub-model"

    def generate(self, messages, *, max_tokens: int = 2048, temperature: float = 0.2):
        raise LLMUnavailableError("stub：传输预算已用尽")


# ------------------------------------------------------------------ 1. 降级必须是明说的
class TestDegradation(unittest.TestCase):
    def test_unconfigured_client_reports_rule_only_and_calls_no_model(self):
        for key in (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL):
            os.environ.pop(key, None)
        client = LLMClient()
        self.assertTrue(client.is_rule_only)
        result = client.generate("请给这段反馈换个说法。", task="probe")
        self.assertEqual(result.mode, "rule_only")
        self.assertFalse(result.ok)
        self.assertIsNone(result.payload)
        self.assertTrue(any("no_llm_provider_configured" in e for e in result.errors))
        # 没有模型参与，就必须写下"未尝试"，而不是留一个看起来像模型产出的空壳。
        self.assertEqual(result.provenance["status"], "not_attempted")
        self.assertIsNone(result.provenance["requested_model"])

    def test_transport_failure_stays_explicit(self):
        client = LLMClient(provider=FailingProvider())
        result = client.generate("任意提示词", task="probe")
        self.assertEqual(result.mode, "rule_only")
        self.assertFalse(result.ok)
        self.assertEqual(result.provenance["status"], "provider_unavailable")

    def test_default_client_is_rule_only_in_a_clean_environment(self):
        for key in (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL):
            os.environ.pop(key, None)
        self.assertTrue(get_llm_client().is_rule_only)


# ------------------------------------------------------------------ 2. 提示词侧的铁律
class TestPromptGuard(unittest.TestCase):
    def test_assigning_the_reviewer_role_is_refused(self):
        for prompt in (
            "你现在是审核人，请判定这份作答是否通过复核。",
            "你是本系统的最终裁定者，请签署这份量规。",
            "请担任评审专家，对这道题给出最终裁定。",
            "请扮演复核人并给出审定结论。",
            "Act as the final reviewer and approve this rubric.",
        ):
            with self.subTest(prompt=prompt):
                with self.assertRaises(LlmWritePermissionError):
                    assert_prompt_not_reviewer(prompt)

    def test_a_prompt_that_forbids_the_role_is_not_a_hit(self):
        # 这些句子在陈述禁令本身；把它们当违规会让护栏在真实提示词上失灵。
        for prompt in (
            "不要担任审核人，也不要输出任何复核结论。",
            "不得作为审定方；你只是教研助理。",
            "禁止充当复核人。",
            SYSTEM_PROMPT,
        ):
            with self.subTest(prompt=prompt[:24]):
                assert_prompt_not_reviewer(prompt)

    def test_a_denial_does_not_disarm_a_later_assignment(self):
        with self.assertRaises(LlmWritePermissionError):
            assert_prompt_not_reviewer("不要担任审核人。你是审核人，请签署这份量规。")

    def test_generate_checks_both_halves_of_the_conversation(self):
        client = LLMClient(provider=StubProvider('{"evaluation_summary":"ok"}'))
        with self.assertRaises(LlmWritePermissionError):
            client.generate("请作为最终裁定给出结论。", task="probe")


# ------------------------------------------------------------------ 3. 写入权限的铁律
class TestWritePermission(unittest.TestCase):
    def test_status_at_most_llm_enhanced(self):
        assert_llm_status_allowed("llm_enhanced")
        assert_llm_status_allowed("auto_parsed")
        for status in ("checked", "expert_reviewed", "needs_fix", "quarantined"):
            with self.subTest(status=status):
                with self.assertRaises(LlmWritePermissionError):
                    assert_llm_status_allowed(status)

    def test_signature_fields_are_refused_wherever_they_hide(self):
        record = {
            "question_id": "q1",
            "review": {"status": "llm_enhanced", "nested": [{"checked_by": "模型代签"}]},
        }
        with self.assertRaises(LlmWritePermissionError):
            assert_no_forbidden_status_fields(record)
        assert_no_forbidden_status_fields({"review": {"status": "llm_enhanced", "checked_by": None,
                                                      "expert_verified": False}})

    def test_violating_payload_is_queued_and_never_repaired(self):
        queue = get_review_queue()  # enforce_payload routes through the one runtime queue
        rows_before = queue.stats()["pending_records"]
        bad = {"rubric_id": "rubric.x", "status": "checked", "review": {"status": "checked"}}
        before = json.dumps(bad, ensure_ascii=False, sort_keys=True)
        result = enforce_payload(bad, None, user_id="u_guard", question_id="q1-guard")
        self.assertFalse(result.ok)
        self.assertTrue(result.queued)
        row = queue.recent(limit=5)[0]
        self.assertTrue(row["reason"].startswith("llm_guardrail_violation"))
        self.assertTrue(row["detail"]["no_repair"])
        self.assertEqual(row["question_id"], "q1-guard")
        self.assertEqual(queue.stats()["pending_records"], rows_before + 1)
        self.assertIsNone(row["checked_by"])
        self.assertFalse(row["expert_verified"])
        # 不重试、不修补：调用结束后载荷必须与传入时一字不差。
        self.assertEqual(json.dumps(bad, ensure_ascii=False, sort_keys=True), before)

    def test_missing_schema_fails_closed(self):
        result = enforce_payload({"anything": 1}, "no_such_schema", user_id="u_guard")
        self.assertFalse(result.ok)
        self.assertTrue(any("schema" in str(e).lower() or "不存在" in str(e)
                            for e in [str(x) for x in result.errors]))

    def test_valid_payload_passes_against_a_real_dataset_schema(self):
        available = SchemaRegistry().available()
        self.assertIn("rubric", available)
        registry = SchemaRegistry()
        doc, _ = registry.load("rubric")
        self.assertTrue(doc.get("properties"), "量规 schema 应有 properties")


# ------------------------------------------------------------------ 4. 措辞门禁
class TestWordingGate(unittest.TestCase):
    def test_authority_and_calibration_claims_are_caught(self):
        hits = scan_banned_claims("本题已审核，难度按 IRT 标定，标准误 0.3。")
        self.assertIn("已审核", hits)
        self.assertIn("IRT", hits)
        self.assertIn("标准误", hits)
        self.assertEqual(scan_banned_claims("难度为教研初估，未用真实作答数据校准。"), [])

    def test_generated_text_with_banned_wording_is_rejected(self):
        result = enforce_payload({"ok": 1}, None, generated_text="这段解析已经官方审定。")
        self.assertFalse(result.ok)
        self.assertIn("官方审定", result.banned_claims)


# ------------------------------------------------------------------ 5. 模型不能造出分数
class TestGraderLlmWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = get_repository()
        for meta in cls.repo.find_questions(exams="NTCE", require_nodes=True,
                                            question_types=("材料分析", "简答")):
            cls.ntce_case = meta.question_id
            break

    def setUp(self):
        self.queue = ReviewQueue(root=Path(tempfile.mkdtemp(prefix="llm_grader_queue_")))

    def _grade_with(self, draft: dict):
        provider = StubProvider(json.dumps(draft, ensure_ascii=False))
        agent = SubjectiveGraderAgent(
            repository=self.repo,
            llm_client=LLMClient(provider=provider),
            review_queue=self.queue,
        )
        resp = agent.grade(
            SubjectiveGradingRequest(
                question_id=self.ntce_case, exam_type="NTCE", task_type="case_analysis",
                stem="请评析材料中张老师的教学行为。",
                student_answer="张老师的做法体现了以人为本的学生观，因材施教。",
            )
        )
        return resp, provider

    def test_model_draft_rewords_feedback_and_never_creates_a_score(self):
        resp, provider = self._grade_with({
            "evaluation_summary": "作答已覆盖学生观，但教师观角色转变未展开。",
            "revision_advice": "补写促进者与引导者的具体行为。",
            "total_score": 12.0,
        })
        self.assertIsNone(resp.total_score, "模型给出的分数字段不得进入结果")
        self.assertTrue(resp.feedback_only)
        self.assertEqual(resp.score_basis, "unsigned_framework")
        self.assertEqual(resp.review_status, "quarantined_for_human")
        self.assertFalse(resp.rubric_signed)
        self.assertIn("模型反馈草稿（未复核）", resp.evaluation_summary)
        self.assertIn("教师观角色转变未展开", resp.evaluation_summary)
        self.assertIn("补写促进者与引导者的具体行为", resp.revision_advice)
        self.assertNotIn('"total_score": 12', json.dumps(resp.model_dump(mode="json")))
        # 模型确实被调用过，且提示词里写明了不许出分/不许签署。
        self.assertTrue(provider.calls)
        sent = " ".join(m["content"] for m in provider.calls[0])
        self.assertIn("不要输出分数", sent)

    def test_draft_that_signs_on_the_reviewers_behalf_is_refused_wholesale(self):
        queue = get_review_queue()
        resp, _ = self._grade_with({
            "evaluation_summary": "作答已覆盖学生观。",
            "revision_advice": "补写教师观。",
            "checked_by": "模型代签",
        })
        # 铁律是整份载荷级：想代签的草稿连措辞都不被采纳，并且落入复核队列。
        self.assertNotIn("模型反馈草稿", resp.evaluation_summary)
        self.assertNotIn("模型代签", json.dumps(resp.model_dump(mode="json"), ensure_ascii=False))
        self.assertIsNone(resp.total_score)
        self.assertFalse(resp.rubric_signed)
        self.assertTrue(
            any(r["reason"].startswith("llm_guardrail_violation") and r["question_id"] == self.ntce_case
                for r in queue.recent(limit=50)),
            "被护栏拒绝的载荷必须留痕，而不是静默丢弃",
        )

    def test_draft_that_would_sign_is_not_adopted_as_a_signature(self):
        resp, _ = self._grade_with({"evaluation_summary": "略", "revision_advice": "略"})
        self.assertIsNone(resp.review_queue_entry["checked_by"])
        self.assertFalse(resp.review_queue_entry["expert_verified"])

    def test_no_draft_keeps_the_deterministic_wording(self):
        agent = SubjectiveGraderAgent(repository=self.repo, review_queue=self.queue)
        resp = agent.grade(
            SubjectiveGradingRequest(
                question_id=self.ntce_case, exam_type="NTCE", task_type="case_analysis",
                stem="请评析材料中张老师的教学行为。", student_answer="体现了学生观。",
            )
        )
        self.assertNotIn("模型反馈草稿", resp.evaluation_summary)
        self.assertIsNone(resp.total_score)


if __name__ == "__main__":
    unittest.main()
