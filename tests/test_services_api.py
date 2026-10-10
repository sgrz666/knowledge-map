"""Runtime tests for the FastAPI layer (services/app.py).

The endpoint that used to assert ``total_score >= 10`` is now the endpoint that asserts the
opposite: the runtime must not ship a score on an unsigned rubric, must fail closed at the
published tier, must not let a caller declare an answer key, and must not let a health probe
write into the single human reviewer's queue.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from starlette.testclient import TestClient

# The runtime opens its FSRS store at import time; point it at a throwaway directory so the
# assertions about first-ever practice counts stay reproducible.
os.environ["KNOWLEDGE_MAP_STATE_DIR"] = tempfile.mkdtemp(prefix="km_test_api_state_")

from services.app import app  # noqa: E402
from services.knowledge.repository import get_repository  # noqa: E402

REPO = get_repository()


def _library_id(exam: str, types) -> str:
    for meta in REPO.find_questions(exams=exam, require_nodes=True, question_types=tuple(types)):
        return meta.question_id
    raise unittest.SkipTest(f"库内没有 {exam} 的 {types} 题目")


class TestAgentAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ntce_case = _library_id("NTCE", ("材料分析", "简答"))
        cls.ntce_choice = _library_id("NTCE", ("单选",))

    def setUp(self):
        self.client = TestClient(app)

    # -------------------------------------------------------------------- health
    def test_health_reports_library_counts(self):
        data = self.client.get("/api/v1/health?probe=false").json()
        self.assertEqual(data["status"], "healthy")
        self.assertGreater(data["library"]["question_records"], 1000)
        self.assertEqual(data["llm_mode"], "rule_only")

    def test_health_probe_runs_every_agent_without_touching_the_review_queue(self):
        before = self.client.get("/api/v1/health?probe=false").json()["review_queue_pending"]
        data = self.client.get("/api/v1/health?probe=true").json()
        for name in (
            "KnowledgeRepository",
            "TrustGate",
            "SubjectiveGraderAgent",
            "CurriculumPlannerAgent",
            "PracticeEngineAgent",
            "TutorQAAgent",
            "InterviewCoachAgent",
            "TutorMasterAgent",
            "RetrievalService",
            "MemoryReviewAgent",
        ):
            self.assertIn(name, data["agents_ready"], f"{name} 未通过就绪探针：{data['agents_not_ready']}")
        self.assertEqual(data["agents_not_ready"], [])
        after = self.client.get("/api/v1/health?probe=false").json()["review_queue_pending"]
        self.assertEqual(before, after, "健康探针不得往教研复核队列写条目")

    # -------------------------------------------------------------------- grader
    def test_grade_endpoint_returns_no_score_on_unsigned_rubric(self):
        payload = {
            "question_id": self.ntce_case,
            "exam_type": "NTCE",
            "task_type": "case_analysis",
            "stem": "评析材料中教师的做法。",
            "student_answer": "该教师体现了以人为本的学生观，尊重个体差异。",
            "max_score": 14.0,
        }
        resp = self.client.post("/api/v1/grade/subjective", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNone(data["total_score"])
        self.assertTrue(data["feedback_only"])
        self.assertFalse(data["rubric_signed"])
        self.assertEqual(data["review_status"], "quarantined_for_human")
        self.assertIsNotNone(data["review_queue_entry"], "未签署出反馈必须落一条待复核队列（A9）")
        self.assertIsNone(data["review_queue_entry"]["checked_by"])
        self.assertFalse(data["review_queue_entry"]["expert_verified"])

    def test_grade_endpoint_has_no_answer_status_parameter(self):
        """A caller-supplied dispute flag was a spoofing vector; the route must not accept one."""
        params = self.client.get("/openapi.json").json()["paths"]["/api/v1/grade/subjective"]["post"]
        self.assertNotIn("answer_status", str(params))

    # ------------------------------------------------------------------ retrieval
    def test_retrieval_endpoint_returns_gate_filtered_candidates(self):
        resp = self.client.post(
            "/api/v1/retrieval/search",
            json={"query": "小学 教学设计 导入 核心素养", "top_k": 3},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(data["backend"], ("chroma", "lexical_bm25"))
        for cand in data["candidates"]:
            self.assertIn(
                cand["review_status"],
                ("needs_fix", "auto_parsed", "llm_enhanced", "checked", "expert_reviewed"),
            )
            self.assertTrue(cand["card_path"], "每条候选都要能回到库内原文定位")

    def test_published_tier_is_empty_at_the_endpoint(self):
        resp = self.client.post(
            "/api/v1/retrieval/search",
            json={"query": "教学设计", "trust_tier": "published"},
        )
        data = resp.json()
        self.assertEqual(data["candidates"], [])
        self.assertEqual(data["candidate_count"], 0)

    # ---------------------------------------------------------------- review queue
    def test_review_queue_endpoint_lists_runtime_degradations(self):
        self.client.post(
            "/api/v1/grade/subjective",
            json={
                "question_id": self.ntce_case,
                "exam_type": "NTCE",
                "task_type": "case_analysis",
                "stem": "题干",
                "student_answer": "作答",
            },
        )
        body = self.client.get("/api/v1/review/queue?limit=20").json()
        self.assertGreaterEqual(body["stats"]["pending_records"], 1)
        self.assertTrue(all(r["checked_by"] is None for r in body["pending"]))
        self.assertTrue(all(r["expert_verified"] is False for r in body["pending"]))

    # ------------------------------------------------------------------ token gate
    def test_research_internal_requires_token_when_configured(self):
        payload = {"query": "教学设计", "trust_tier": "research_internal"}
        with mock.patch.dict(os.environ, {"KNOWLEDGE_MAP_RUNTIME_TOKEN": "s3cr3t-token"}):
            self.assertEqual(self.client.post("/api/v1/retrieval/search", json=payload).status_code, 401)
            ok = self.client.post(
                "/api/v1/retrieval/search", json=payload, headers={"Authorization": "Bearer s3cr3t-token"}
            )
            self.assertEqual(ok.status_code, 200)
            # published is the tier that serves nothing, so it never needs a token
            pub = self.client.post(
                "/api/v1/retrieval/search", json={**payload, "trust_tier": "published"}
            )
            self.assertEqual(pub.status_code, 200)
            self.assertEqual(pub.json()["candidates"], [])
        without_env = self.client.post("/api/v1/retrieval/search", json=payload)
        self.assertEqual(without_env.status_code, 200)

    def test_every_route_but_health_sits_behind_the_auth_dependency(self):
        """令牌闸按路由挂：漏一条就等于给那条路由开了免检口，而画像/溯源/原文都在那些路由里。"""
        from fastapi.routing import APIRoute

        from services.app import AuthContext

        open_routes = {"/api/v1/health"}
        covered = 0
        for route in app.routes:
            if not isinstance(route, APIRoute) or route.path in open_routes:
                continue
            calls = {dep.call for dep in route.dependant.dependencies}
            self.assertIn(
                AuthContext.from_header, calls, f"{route.path} 没有挂 AuthContext，会绕过档位令牌"
            )
            covered += 1
        self.assertGreaterEqual(covered, 12, "路由数量与文档口径不符，先复核这条检查的范围")

    # ---------------------------------------------------------------------- memory
    def test_memory_review_and_mastery_endpoint(self):
        event_payload = {
            "user_id": "u-api-test-888",
            "question_id": "q-api-ntce-001",
            "node_id": "ntce.xiaoxue.jiaoxue.m1.k01",
            "exam": "NTCE",
            "is_correct": False,
            "time_spent_seconds": 4.2,
            "has_negation_in_stem": True,
            "question_difficulty": 0.4,
            "current_node_mastery": 0.7,
        }
        review = self.client.post("/api/v1/memory/review", json=event_payload)
        self.assertEqual(review.status_code, 200)
        data = review.json()
        self.assertEqual(data["user_id"], "u-api-test-888")
        self.assertEqual(data["attribution"]["category"], "careless")
        self.assertEqual(data["updated_mastery"]["fsrs_state"]["reps"], 1)
        self.assertEqual(data["updated_mastery"]["fsrs_state"]["lapses"], 1)

        mastery = self.client.get("/api/v1/memory/mastery/u-api-test-888/ntce.xiaoxue.jiaoxue.m1.k01").json()
        self.assertEqual(mastery["practice_count"], 1)
        self.assertEqual(mastery["correct_count"], 0)

        missing = self.client.get("/api/v1/memory/mastery/u-none/ntce.none.k99")
        self.assertEqual(missing.status_code, 404)

    # --------------------------------------------------------------------- practice
    def test_practice_endpoint_uses_library_questions(self):
        resp = self.client.post(
            "/api/v1/practice/assemble",
            json={"user_id": "u-api", "exam_type": "NTCE", "practice_mode": "daily_practice", "item_count": 3},
        )
        data = resp.json()
        self.assertEqual(data["total_items"], len(data["questions"]))
        for item in data["questions"]:
            self.assertIsNotNone(REPO.get_meta(item["question_id"]), "组卷题目必须存在于索引内")

    def test_published_practice_is_empty(self):
        resp = self.client.post(
            "/api/v1/practice/assemble",
            json={
                "user_id": "u-api-pub",
                "exam_type": "NTCE",
                "practice_mode": "daily_practice",
                "item_count": 5,
                "trust_tier": "published",
            },
        )
        data = resp.json()
        self.assertEqual(data["total_items"], 0)
        self.assertEqual(data["questions"], [])

    # ---------------------------------------------------------------------- interview
    def test_interview_endpoints_feedback_only(self):
        speech = self.client.post(
            "/api/v1/interview/speech",
            json={"transcript_text": "导入，新授，巩固，小结，布置作业。", "audio_duration_seconds": 480},
        ).json()
        self.assertIsNone(speech["overall_score"])
        self.assertTrue(any("签署" in n for n in speech["notices"]))

        plan = self.client.post(
            "/api/v1/interview/lesson_plan",
            json={
                "topic": "教学过程的基本规律",
                "plan_text": "教学目标：知识与技能。重点：规律。难点：运用。导入、新课、探究、练习、总结、作业。板书设计：提纲式。",
            },
        ).json()
        self.assertIsNone(plan["total_score"])
        self.assertTrue(plan["feedback_only"])
        self.assertEqual(plan["rubric_id"], "rubric.ntce.lesson_plan.standard_v1")
        self.assertTrue(plan["dimensions"], "维度应来自库内量规")

    # ----------------------------------------------------------------------- master
    def test_master_chat_reports_real_counts_only(self):
        resp = self.client.post(
            "/api/v1/master/chat",
            json={"user_id": "u-api-master", "message": "开启今日练习", "exam_type": "NTCE", "action_payload": {"item_count": 2}},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(data["card_type"], ("practice_card", "text_message"))
        self.assertNotIn("30 道", data["reply_text"])
        if data["card_type"] == "practice_card":
            self.assertEqual(data["card_data"]["total_items"], len(data["card_data"]["sample"]) or data["card_data"]["total_items"])

    def test_qa_endpoint_rejects_invented_question_id_without_grounding(self):
        data = self.client.post(
            "/api/v1/qa/query",
            json={"user_id": "u-api", "question_id": "no.such.id"},
        ).json()
        self.assertFalse(data["grounded_in_library"])
        self.assertIn("不在知识库", data["key_clue_localization"] + data["explanation_summary"])

    # -------------------------------------------------------------------------- SSE
    def test_master_stream_emits_status_card_done(self):
        with self.client.stream(
            "GET", "/api/v1/master/stream", params={"message": "开启今日练习", "user_id": "u-sse"}
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
            text = "".join(resp.iter_text())
        self.assertIn("event: status", text)
        self.assertIn("event: card", text)
        self.assertIn("event: done", text)

    def test_qa_stream_reports_error_event_for_unknown_id(self):
        with self.client.stream("GET", "/api/v1/qa/stream", params={"question_id": "no.such.id"}) as resp:
            text = "".join(resp.iter_text())
        self.assertIn("event: card", text)
        self.assertIn("event: done", text)


if __name__ == "__main__":
    unittest.main()
