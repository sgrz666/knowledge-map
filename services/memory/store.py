"""Persistence for FSRS mastery and error logs.

State lives under ``.local_state/`` (never committed): it is per-machine learner data,
not part of the knowledge library. Tests point ``KNOWLEDGE_MAP_STATE_DIR`` at a temp dir.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from services.common.models import UserMasteryRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_STATE_DIR = "KNOWLEDGE_MAP_STATE_DIR"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_mastery (
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, node_id)
);
CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    exam TEXT,
    error_category TEXT,
    correct_count INTEGER NOT NULL DEFAULT 0,
    incorrect_count INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TEXT,
    due_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_error_log ON error_log (user_id, question_id);
CREATE INDEX IF NOT EXISTS ix_error_log_due ON error_log (user_id, due_at);
"""


def state_dir(root: Optional[Path] = None) -> Path:
    override = os.environ.get(ENV_STATE_DIR)
    base = Path(override) if override else (root or REPO_ROOT) / ".local_state"
    base.mkdir(parents=True, exist_ok=True)
    return base


class InMemoryMasteryStore:
    """Volatile store used by tests and one-shot scripts."""

    def __init__(self) -> None:
        self._records: Dict[str, UserMasteryRecord] = {}
        self._errors: Dict[str, dict] = {}

    def get(self, user_id: str, node_id: str) -> Optional[UserMasteryRecord]:
        return self._records.get(f"{user_id}:{node_id}")

    def put(self, record: UserMasteryRecord) -> None:
        self._records[f"{record.user_id}:{record.node_id}"] = record

    def log_error(self, entry: dict) -> None:
        key = f"{entry['user_id']}:{entry['question_id']}"
        self._errors[key] = entry

    def error_entries(self, user_id: str) -> List[dict]:
        return [e for e in self._errors.values() if e["user_id"] == user_id]

    def due_question_ids(self, user_id: str, now: Optional[datetime] = None, limit: int = 20) -> List[str]:
        now = now or datetime.now(timezone.utc)
        rows = sorted(
            self.error_entries(user_id),
            key=lambda e: (e.get("due_at") or "9999", -int(e.get("incorrect_count") or 0)),
        )
        out: List[str] = []
        for e in rows:
            if len(out) >= limit:
                break
            out.append(e["question_id"])
        return out

    def weak_node_ids(self, user_id: str, limit: int = 5) -> List[str]:
        scores: Dict[str, List[float]] = {}
        for key, record in self._records.items():
            uid, _, node = key.partition(":")
            if uid != user_id:
                continue
            scores.setdefault(node, [0.0, 0])
            scores[node][0] += record.mastery_score
            scores[node][1] += 1
        ranked = sorted(scores.items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1))
        return [node for node, _ in ranked[:limit]]

    def clear(self, user_id: Optional[str] = None) -> None:
        if user_id is None:
            self._records.clear()
            self._errors.clear()
            return
        for key in [k for k in self._records if k.split(":", 1)[0] == user_id]:
            del self._records[key]
        for key in [k for k in self._errors if k.split(":", 1)[0] == user_id]:
            del self._errors[key]


class SqliteMasteryStore:
    """File-backed store so FSRS scheduling survives process restarts."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else state_dir() / "memory.sqlite3"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    def _execute(self, sql: str, params: Iterable) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def get(self, user_id: str, node_id: str) -> Optional[UserMasteryRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT record_json FROM user_mastery WHERE user_id=? AND node_id=?",
                (user_id, node_id),
            ).fetchone()
        if row is None:
            return None
        return UserMasteryRecord.model_validate_json(row["record_json"])

    def put(self, record: UserMasteryRecord) -> None:
        self._execute(
            """
            INSERT INTO user_mastery (user_id, node_id, record_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id, node_id) DO UPDATE SET
                record_json=excluded.record_json, updated_at=excluded.updated_at
            """,
            (record.user_id, record.node_id, record.model_dump_json(), record.last_updated_at),
        )

    def log_error(self, entry: dict) -> None:
        self._execute(
            """
            INSERT INTO error_log (user_id, question_id, node_id, exam, error_category,
                                   correct_count, incorrect_count, last_reviewed_at, due_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, question_id) DO UPDATE SET
                correct_count=excluded.correct_count,
                incorrect_count=excluded.incorrect_count,
                last_reviewed_at=excluded.last_reviewed_at,
                due_at=excluded.due_at,
                error_category=excluded.error_category,
                node_id=excluded.node_id
            """,
            (
                entry["user_id"],
                entry["question_id"],
                entry["node_id"],
                entry.get("exam"),
                entry.get("error_category"),
                int(entry.get("correct_count") or 0),
                int(entry.get("incorrect_count") or 0),
                entry.get("last_reviewed_at"),
                entry.get("due_at"),
            ),
        )

    def error_entries(self, user_id: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM error_log WHERE user_id=? ORDER BY due_at IS NULL, due_at",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def due_question_ids(self, user_id: str, now: Optional[datetime] = None, limit: int = 20) -> List[str]:
        now = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT question_id FROM error_log
                WHERE user_id=? AND (due_at IS NULL OR due_at<=?)
                ORDER BY due_at IS NULL, due_at, incorrect_count DESC
                LIMIT ?
                """,
                (user_id, now, limit),
            ).fetchall()
        return [r["question_id"] for r in rows]

    def weak_node_ids(self, user_id: str, limit: int = 5) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT node_id, AVG(mastery_score) AS m, COUNT(*) AS n
                FROM (
                    SELECT node_id,
                           CAST(json_extract(record_json, '$.mastery_score') AS REAL) AS mastery_score
                    FROM user_mastery WHERE user_id=?
                )
                GROUP BY node_id ORDER BY m ASC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [r["node_id"] for r in rows]

    def clear(self, user_id: Optional[str] = None) -> None:
        if user_id is None:
            self._execute("DELETE FROM user_mastery", ())
            self._execute("DELETE FROM error_log", ())
            return
        self._execute("DELETE FROM user_mastery WHERE user_id=?", (user_id,))
        self._execute("DELETE FROM error_log WHERE user_id=?", (user_id,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_DEFAULT_STORE: Optional[object] = None


def default_store() -> object:
    """Process-wide store, SQLite-backed unless the state dir is unavailable."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = SqliteMasteryStore()
    return _DEFAULT_STORE
