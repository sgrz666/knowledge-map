"""MemoryReviewAgent: Coordinates error attribution, FSRS memory scheduling, and mastery persistence."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from services.common.models import (
    ErrorAttributionCategory,
    ErrorAttributionResult,
    ErrorReviewEvent,
    ReviewBundle,
    UserMasteryRecord,
)
from services.memory.attribution import ErrorAttributionEngine
from services.memory.fsrs import FSRSModel

logger = logging.getLogger("services.memory.agent")


class MemoryReviewAgent:
    """Agent managing error analysis, spaced repetition updates, and mastery state."""

    def __init__(self, in_memory_store: Optional[Dict[str, UserMasteryRecord]] = None):
        # In-memory mock store for session tracking; in production backed by PostgreSQL / Redis
        self.store = in_memory_store if in_memory_store is not None else {}

    def get_user_mastery(self, user_id: str, node_id: str) -> Optional[UserMasteryRecord]:
        """Retrieve existing mastery record for a user on a given knowledge node."""
        key = f"{user_id}:{node_id}"
        return self.store.get(key)

    def process_event(self, event: ErrorReviewEvent) -> ReviewBundle:
        """Process an answering event, update FSRS scheduling, and return review bundle."""
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

        # Persist to in-memory store
        self.store[f"{event.user_id}:{event.node_id}"] = updated_mastery

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
        )
