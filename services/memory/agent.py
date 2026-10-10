"""MemoryReviewAgent: Coordinates error attribution, FSRS memory scheduling, and mastery persistence.

The event's ``is_correct`` is a claim, not a verdict: before anything is written to a learner's
profile it goes through ``TrustGate.reconcile_verdict``, which prefers the library answer key and
only falls back to the claim when the library cannot check it (see ``docs/agent_architecture.md`` §8 A10).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from services.common.models import (
    ErrorAttributionCategory,
    ErrorAttributionResult,
    ErrorReviewEvent,
    ReviewBundle,
    UserMasteryRecord,
)
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate
from services.memory.attribution import ErrorAttributionEngine
from services.memory.fsrs import FSRSModel
from services.memory.store import default_store

logger = logging.getLogger("services.memory.agent")


class MemoryReviewAgent:
    """Agent managing error analysis, spaced repetition updates, and mastery state."""

    def __init__(self, store=None, repository: Optional[KnowledgeRepository] = None):
        # Defaults to the on-disk store under .local_state/ so scheduling survives restarts.
        self.store = store if store is not None else default_store()
        # 库门面用来核对申报的对错；不注入时按默认门面走，不给"没核对"留口子。
        self.repository = repository if repository is not None else get_repository()
        # 档位写死在 research_internal：让调用方自选档位就等于让它自己挑一套更宽的核对口径。
        self.gate = TrustGate("research_internal")

    def _reconcile(self, event: ErrorReviewEvent):
        """Right/wrong plus its provenance; ``None`` verdict means "write nothing"."""
        record = self.repository.load_question(event.question_id) if event.question_id else None
        return self.gate.reconcile_verdict(record, event.selected_option, event.is_correct)

    def _not_attributable(self, event: ErrorReviewEvent, notices) -> ReviewBundle:
        return ReviewBundle(
            user_id=event.user_id,
            node_id=event.node_id,
            followup_plan=(
                "这次作答没有可核对的对错判据（库内该题答案不可用，且没有提交可核对的所选选项）："
                "系统不虚构对错，掌握度与复习队列都未改动。"
            ),
            verdict_source=None,
            attributable=False,
            notices=list(notices),
        )

    def get_user_mastery(self, user_id: str, node_id: str) -> Optional[UserMasteryRecord]:
        """Retrieve existing mastery record for a user on a given knowledge node."""
        return self.store.get(user_id, node_id)

    def due_question_ids(self, user_id: str, limit: int = 20) -> list:
        """Question ids the learner owes a re-attempt on (FSRS queue)."""
        return self.store.due_question_ids(user_id, limit=limit)

    def weak_node_ids(self, user_id: str, limit: int = 5) -> list:
        """Lowest-mastery nodes for this learner, worst first."""
        return self.store.weak_node_ids(user_id, limit=limit)

    def _prior_error_entry(self, event: ErrorReviewEvent) -> dict:
        for entry in self.store.error_entries(event.user_id):
            if entry.get("question_id") == event.question_id:
                return entry
        return {"correct_count": 0, "incorrect_count": 0}

    def process_event(self, event: ErrorReviewEvent) -> ReviewBundle:
        """Process an answering event, update FSRS scheduling, and return review bundle."""
        checked, provenance, notices = self._reconcile(event)
        if checked is None:
            return self._not_attributable(event, notices)
        if bool(event.is_correct) != checked:
            logger.warning(
                "question %s: reported is_correct=%s contradicts the library answer key; using %s",
                event.question_id,
                event.is_correct,
                checked,
            )
        event = event.model_copy(update={"is_correct": checked})
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # 1. Determine FSRS rating (1=Again, 2=Hard, 3=Good, 4=Easy)
        if not event.is_correct:
            fsrs_rating = 1  # Again
        else:
            if event.time_spent_seconds > 45.0 or event.option_flip_count >= 1:
                fsrs_rating = 2  # Hard
            elif event.time_spent_seconds < 10.0 and event.option_flip_count == 0:
                fsrs_rating = 4  # Easy
            else:
                fsrs_rating = 3  # Good

        # 2. Attribution: analyze root cause if wrong; if correct, note mastery
        if not event.is_correct:
            attribution = ErrorAttributionEngine.attribute(event)
        else:
            attribution = ErrorAttributionResult(
                category=ErrorAttributionCategory.CARELESS,  # Neutral placeholder
                category_name="掌握巩固",
                confidence=1.0,
                rationale="作答正确，已在认知网络中建立有效联结。",
                recommended_action="按计划进行间隔复习即可，无需额外补做基础概念卡片。",
            )

        # 3. Retrieve or initialize existing mastery record
        existing = self.get_user_mastery(event.user_id, event.node_id)
        current_fsrs = existing.fsrs_state if existing else None
        p_count = (existing.practice_count if existing else 0) + 1
        c_count = (existing.correct_count if existing else 0) + (1 if event.is_correct else 0)

        # 4. FSRS step
        new_fsrs, next_days = FSRSModel.step(current_fsrs, fsrs_rating, now=now)
        retrievability = FSRSModel.retrievability(0.0, new_fsrs.stability)

        # 5. Compute Bayesian-damped mastery score [0.0, 1.0]
        # M = (alpha * acc + (1 - alpha) * (1 - diff)) * R
        acc = (c_count + 1.0) / (p_count + 2.0)  # Laplace smoothed accuracy
        diff_factor = 1.0 - (event.question_difficulty * 0.4)
        raw_mastery = (0.7 * acc + 0.3 * diff_factor) * retrievability
        mastery_score = max(0.05, min(0.98, round(raw_mastery, 3)))

        # 6. Build updated UserMasteryRecord
        updated_mastery = UserMasteryRecord(
            user_id=event.user_id,
            node_id=event.node_id,
            mastery_score=mastery_score,
            practice_count=p_count,
            correct_count=c_count,
            fsrs_state=new_fsrs,
            last_updated_at=now_iso,
        )

        # Persist mastery, and keep a question-level error queue for 错题消灭 mode
        self.store.put(updated_mastery)
        prior = self._prior_error_entry(event)
        self.store.log_error(
            {
                "user_id": event.user_id,
                "question_id": event.question_id,
                "node_id": event.node_id,
                "exam": event.exam,
                "error_category": None if event.is_correct else attribution.category.value,
                "correct_count": prior["correct_count"] + (1 if event.is_correct else 0),
                "incorrect_count": prior["incorrect_count"] + (0 if event.is_correct else 1),
                "last_reviewed_at": now_iso,
                "due_at": new_fsrs.due_date,
            }
        )

        # 7. Formulate followup plan
        if not event.is_correct:
            followup = (
                f"【{attribution.category_name}】复习计划已生成：1. 建议当日内重做本题及考点卡片；"
                f"2. 系统已调度在第 {int(next_days)} 天（{new_fsrs.due_date[:10]}）推送同考点变式练习题；"
                "3. 建议回顾错因反思，避免再次落入相似考点陷阱。"
            )
        else:
            followup = f"掌握度已提升至 {mastery_score*100:.1f}%。下次巩固日期已调度为：{new_fsrs.due_date[:10]}。"

        return ReviewBundle(
            user_id=event.user_id,
            node_id=event.node_id,
            attribution=attribution,
            updated_mastery=updated_mastery,
            fsrs_rating=fsrs_rating,
            retrievability=round(retrievability, 3),
            next_review_interval_days=next_days,
            followup_plan=followup,
            verdict_source=provenance,
            notices=list(notices),
        )
