"""FSRS-v4 (Free Spaced Repetition Scheduler) mathematical model implementation.

Provides optimal spaced repetition interval scheduling and memory retrievability
decay modeling based on cognitive memory retention dynamics.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from services.common.models import FSRSState


class FSRSModel:
    """Mathematical implementation of the Free Spaced Repetition Scheduler (v4)."""

    # Decay constants ensuring R(S, S) = 0.90 exactly
    FACTOR: float = 19.0 / 81.0
    DECAY: float = -0.5
    REQUEST_RETENTION: float = 0.90

    # Default initial stability for ratings [Again=1, Hard=2, Good=3, Easy=4]
    INIT_STABILITY = {
        1: 0.4,
        2: 0.9,
        3: 2.4,
        4: 5.8,
    }

    # Default initial difficulty
    INIT_DIFFICULTY = {
        1: 7.5,
        2: 6.2,
        3: 5.0,
        4: 3.5,
    }

    @classmethod
    def retrievability(cls, elapsed_days: float, stability: float) -> float:
        """Calculate predicted retrievability R(t, S) in [0.0, 1.0]."""
        if stability <= 0.0:
            return 0.0
        if elapsed_days <= 0.0:
            return 1.0
        return math.pow(1.0 + cls.FACTOR * (elapsed_days / stability), cls.DECAY)

    @classmethod
    def next_interval(cls, stability: float, target_retention: float = 0.90) -> float:
        """Calculate optimal next review interval I in days for target retention rate."""
        if stability <= 0.0:
            return 1.0
        interval = (stability / cls.FACTOR) * (math.pow(target_retention, 1.0 / cls.DECAY) - 1.0)
        return max(1.0, round(interval, 1))

    @classmethod
    def step(
        cls,
        current_state: Optional[FSRSState],
        rating: int,  # 1=Again, 2=Hard, 3=Good, 4=Easy
        now: Optional[datetime] = None,
    ) -> Tuple[FSRSState, float]:
        """Advance FSRS memory state given student feedback rating.

        Returns:
            (new_state, next_interval_days)
        """
        rating = max(1, min(4, rating))
        now = now or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        if current_state is None:
            # First learning event
            init_s = cls.INIT_STABILITY[rating]
            init_d = cls.INIT_DIFFICULTY[rating]
            next_days = cls.next_interval(init_s, cls.REQUEST_RETENTION)
            due = (now + timedelta(days=next_days)).isoformat()
            state_label = "learning" if rating > 1 else "relearning"

            return (
                FSRSState(
                    stability=round(init_s, 2),
                    difficulty=round(init_d, 2),
                    due_date=due,
                    state=state_label,
                    reps=1,
                    lapses=1 if rating == 1 else 0,
                    last_review=now_iso,
                ),
                next_days,
            )

        # Subsequent review event
        # 1. Compute elapsed days since last review
        last_dt = now
        if current_state.last_review:
            try:
                last_dt = datetime.fromisoformat(current_state.last_review.replace("Z", "+00:00"))
            except Exception:
                pass
        elapsed = max(0.01, (now - last_dt).total_seconds() / 86400.0)

        # 2. Retrievability R at review time
        r = cls.retrievability(elapsed, current_state.stability)

        # 3. Update Difficulty D
        # D' = clamp(D - 0.7 * (rating - 3), 1.0, 10.0)
        new_d = current_state.difficulty - 0.7 * (rating - 3)
        new_d = max(1.0, min(10.0, round(new_d, 2)))

        # 4. Update Stability S
        s = current_state.stability
        if rating == 1:
            # Lapse / Forgot
            new_s = max(0.2, min(cls.INIT_STABILITY[1], round(s * 0.25, 2)))
            new_lapses = current_state.lapses + 1
            new_state_label = "relearning"
        else:
            # Recall success (Hard=2, Good=3, Easy=4)
            bonus = 0.75 if rating == 2 else (1.0 if rating == 3 else 1.35)
            # Power law expansion
            growth = 1.0 + math.exp(0.5) * (11.0 - new_d) * math.pow(s, -0.2) * (math.exp(1.0 - r) - 1.0) * bonus
            growth = max(1.1, min(3.5, growth))
            new_s = round(s * growth, 2)
            new_lapses = current_state.lapses
            new_state_label = "review"

        # 5. Compute next interval
        next_days = cls.next_interval(new_s, cls.REQUEST_RETENTION)
        due_iso = (now + timedelta(days=next_days)).isoformat()

        return (
            FSRSState(
                stability=new_s,
                difficulty=new_d,
                due_date=due_iso,
                state=new_state_label,
                reps=current_state.reps + 1,
                lapses=new_lapses,
                last_review=now_iso,
            ),
            next_days,
        )
