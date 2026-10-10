"""Runtime review queue: the only place a degraded agent response is allowed to land.

``docs/agent_architecture.md`` §6 and acceptance A9 require that anything TrustGate blocks
becomes a *reviewable record for the single 教研 reviewer* instead of being silently dropped or,
worse, auto-approved. The user is the only reviewer, so nothing in this module may fill
``checked_by``, set ``review.status`` to ``checked`` / ``expert_reviewed``, or set
``expert_verified = true``.

Rows are JSONL under ``.local_state/review_queue/`` (never committed) and mirror the shape the
offline builder in ``审查/build_review_queue.py`` already uses, so runtime degradations and static
audit findings end up in one queue rather than two.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from services.memory.store import state_dir

QUEUE_SUBDIR = "review_queue"
REVIEWER = "教研审核（唯一人工审核人）"

SIGNABLE_FIELDS = ("checked_by", "expert_verified")


class ReviewQueue:
    """Append-only JSONL queue of items that must be decided by a human."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else state_dir() / QUEUE_SUBDIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path_for(self, bucket: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in bucket) or "general"
        return self.root / f"{safe}.jsonl"

    def add(
        self,
        *,
        reason: str,
        user_id: str,
        question_id: Optional[str] = None,
        node_id: Optional[str] = None,
        requirement_id: Optional[str] = None,
        tier: Optional[str] = None,
        source: Optional[str] = None,
        detail: Optional[dict] = None,
    ) -> dict:
        row: Dict[str, object] = {
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "user_id": user_id,
            "question_id": question_id,
            "node_id": node_id,
            "requirement_id": requirement_id,
            "trust_tier": tier,
            "source": source,
            "detail": detail or {},
            "status": "pending_human_review",
            "reviewer": REVIEWER,
            # The reviewer signs in 审查/待复核清单.md; runtime never does.
            "checked_by": None,
            "expert_verified": False,
        }
        bucket = (question_id or node_id or requirement_id or reason)[:60]
        with self._lock:
            with open(self.path_for(bucket), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def recent(self, limit: int = 50) -> List[dict]:
        rows: List[dict] = []
        for path in sorted(self.root.glob("*.jsonl")):
            with open(path, "rb") as fh:
                for line in fh:
                    try:
                        rows.append(json.loads(line.decode("utf-8")))
                    except json.JSONDecodeError:
                        continue
        rows.sort(key=lambda r: str(r.get("queued_at", "")), reverse=True)
        return rows[:limit]

    def stats(self) -> dict:
        files = sorted(self.root.glob("*.jsonl"))
        total = 0
        for path in files:
            with open(path, "rb") as fh:
                total += sum(1 for line in fh if line.strip())
        return {
            "queue_dir": self.root.as_posix(),
            "buckets": len(files),
            "pending_records": total,
            "reviewer": REVIEWER,
            "note": "运行时降级项在此排队，签署动作只发生在 审查/待复核清单.md 的人工流程里。",
        }


_DEFAULT_QUEUE: Optional[ReviewQueue] = None


def get_review_queue() -> ReviewQueue:
    global _DEFAULT_QUEUE
    if _DEFAULT_QUEUE is None:
        _DEFAULT_QUEUE = ReviewQueue()
    return _DEFAULT_QUEUE
