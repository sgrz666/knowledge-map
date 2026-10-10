"""Session persistence for the orchestrator, next to the FSRS state (§3.5).

``.local_state/`` is per-machine learner data and is never committed. Sessions live in SQLite so
a conversation and its state trace survive a restart and are readable from another process —
the in-process dict this replaces could not be read cross-process at all.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from services.memory.store import state_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_session (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    exam TEXT,
    state TEXT NOT NULL,
    context_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    state TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_trace_seq ON agent_trace (session_id, seq);
CREATE INDEX IF NOT EXISTS ix_trace_session ON agent_trace (session_id, seq);
"""


class SessionStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else state_dir() / "orchestrator.sqlite3"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def save(self, *, session_id: str, user_id: str, exam: Optional[str], state: str, context: dict) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agent_session (session_id, user_id, exam, state, context_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (session_id) DO UPDATE SET
                    state=excluded.state, context_json=excluded.context_json, updated_at=excluded.updated_at
                """,
                (
                    session_id,
                    user_id,
                    exam,
                    state,
                    json.dumps(context, ensure_ascii=False, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def load(self, session_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_session WHERE session_id=?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "exam": row["exam"],
            "state": row["state"],
            "context": json.loads(row["context_json"]),
            "updated_at": row["updated_at"],
        }

    def append_trace(self, session_id: str, envelope: dict) -> int:
        state = str(envelope.get("action", ""))
        with self._lock:
            seq = int(
                self._conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM agent_trace WHERE session_id=?",
                    (session_id,),
                ).fetchone()["next"]
            )
            self._conn.execute(
                """
                INSERT INTO agent_trace (session_id, seq, state, envelope_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, seq, state, json.dumps(envelope, ensure_ascii=False, default=str),
                 datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
        return seq

    def trace(self, session_id: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, envelope_json FROM agent_trace WHERE session_id=? ORDER BY seq",
                (session_id,),
            ).fetchall()
        return [{"seq": r["seq"], "envelope": json.loads(r["envelope_json"])} for r in rows]

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            if session_id is None:
                self._conn.execute("DELETE FROM agent_session")
                self._conn.execute("DELETE FROM agent_trace")
            else:
                self._conn.execute("DELETE FROM agent_session WHERE session_id=?", (session_id,))
                self._conn.execute("DELETE FROM agent_trace WHERE session_id=?", (session_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_DEFAULT: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = SessionStore()
    return _DEFAULT
