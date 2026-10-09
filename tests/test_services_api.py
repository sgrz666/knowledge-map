"""Integration tests for FastAPI agent runtime endpoints."""
import unittest
from starlette.testclient import TestClient

from services.app import app


class TestAgentAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check_endpoint(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("SubjectiveGraderAgent", data["agents_ready"])
        self.assertIn("MemoryReviewAgent", data["agents_ready"])

    def test_grade_subjective_endpoint(self):
        payload = {
            "question_id": "api-cet4-test-01",
            "exam_type": "CET-4",
            "task_type": "short_essay",
            "stem": "Write an essay about reading habits.",
            "student_answer": (
                "With the rapid advancement of modern information technology, reading habits play "
                "an indispensable role in contemporary college students' personal and intellectual growth. "
                "Firstly, reading academic books broadens our horizons and introduces novel concepts. "
                "Secondly, it significantly bolsters critical thinking and communicative efficiency in remote research settings. "
                "However, many undergraduates still struggle with information overload, screen distraction, and shallow reading habits. "
                "Therefore, universities should establish systematic reading clubs and guidance programs to cultivate students' "
                "sustained reading routines and intellectual autonomy. "
                "In conclusion, embracing deep reading habits is of vital significance for our lifelong development."
            ),
            "max_score": 15.0,
        }
        resp = self.client.post("/api/v1/grade/subjective", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["question_id"], "api-cet4-test-01")
        self.assertEqual(data["grading_mode"], "holistic_band")
        self.assertGreaterEqual(data["total_score"], 10.0)
        self.assertIn("holistic_details", data)
        self.assertIn(data["holistic_details"]["selected_band"], [11, 14])

    def test_memory_review_and_mastery_endpoint(self):
        # 1. Process review event
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
        review_resp = self.client.post("/api/v1/memory/review", json=event_payload)
        self.assertEqual(review_resp.status_code, 200)
        review_data = review_resp.json()
        self.assertEqual(review_data["user_id"], "u-api-test-888")
        self.assertEqual(review_data["node_id"], "ntce.xiaoxue.jiaoxue.m1.k01")
        self.assertEqual(review_data["attribution"]["category"], "careless")
        self.assertEqual(review_data["fsrs_rating"], 1)
        self.assertEqual(review_data["updated_mastery"]["fsrs_state"]["reps"], 1)
        self.assertEqual(review_data["updated_mastery"]["fsrs_state"]["lapses"], 1)

        # 2. Query updated mastery
        mastery_resp = self.client.get("/api/v1/memory/mastery/u-api-test-888/ntce.xiaoxue.jiaoxue.m1.k01")
        self.assertEqual(mastery_resp.status_code, 200)
        mastery_data = mastery_resp.json()
        self.assertEqual(mastery_data["user_id"], "u-api-test-888")
        self.assertEqual(mastery_data["node_id"], "ntce.xiaoxue.jiaoxue.m1.k01")
        self.assertEqual(mastery_data["practice_count"], 1)
        self.assertEqual(mastery_data["correct_count"], 0)
        self.assertGreaterEqual(mastery_data["mastery_score"], 0.0)
