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
from services.memory.receipt import verify_receipt

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_STATE_DIR = "KNOWLEDGE_MAP_STATE_DIR"
SCHEMA_VERSION = 2

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
-- 事件收据：event_id 说"这是哪一次作答"，fingerprint 说"那一次到底答了什么"。
-- fingerprint 为 NULL 的行是指纹上线之前写入的旧收据，无法核对输入，见 services/memory/receipt.py。
CREATE TABLE IF NOT EXISTS memory_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT,
    fingerprint TEXT,
    result_json TEXT NOT NULL
);
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
        self._events: Dict[str, dict] = {}

    def run_once(self, event_id, event_fingerprint, apply, *, user_id=None):
        receipt = self._events.get(event_id)
        if receipt is not None:
            verify_receipt(event_id, receipt[1], event_fingerprint)
            return receipt[2]
        result = apply()
        self._events[event_id] = (user_id, event_fingerprint, result)
        return result

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
        # 事件收据也是学习记录的一部分：只清掌握度和错题会留下收据，下一次同一 event_id 的
        # 提交会被当成"已经记过一次"原样回放，学习者再也拿不回这次的计数。
        if user_id is None:
            self._records.clear()
            self._errors.clear()
            self._events.clear()
            return
        for key in [k for k in self._records if k.split(":", 1)[0] == user_id]:
            del self._records[key]
        for key in [k for k in self._errors if k.split(":", 1)[0] == user_id]:
            del self._errors[key]
        for key in [k for k, (owner, _, _) in self._events.items() if owner == user_id]:
            del self._events[key]


class SqliteMasteryStore:
    """File-backed store so FSRS scheduling survives process restarts."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else state_dir() / "memory.sqlite3"
        self._lock = threading.RLock()
        self._in_transaction = False
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # CREATE TABLE IF NOT EXISTS 不会给已经存在的库补列：收据表换代前上线的库里
            # 已有 event_id/result_json，这两列必须 ALTER 出来，旧行的 fingerprint 留 NULL 当"无法核对"。
            columns = {row[1] for row in self._conn.execute('PRAGMA table_info(memory_events)')}
            if 'user_id' not in columns:
                self._conn.execute('ALTER TABLE memory_events ADD COLUMN user_id TEXT')
            if 'fingerprint' not in columns:
                self._conn.execute('ALTER TABLE memory_events ADD COLUMN fingerprint TEXT')
            self._conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            self._conn.commit()

    def _execute(self, sql: str, params: Iterable) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            if not self._in_transaction:
                self._conn.commit()
            return cur

    def run_once(self, event_id, event_fingerprint, apply, *, user_id=None):
        """Persist the event receipt and its mastery/error writes in one transaction.

        A receipt whose fingerprint differs is refused before ``apply`` runs, so a retry that
        changed the answer (or the time spent, or the option flips) cannot leave a second
        learning write behind and cannot be served the first attempt's verdict.
        """
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            self._in_transaction = True
            try:
                row = self._conn.execute(
                    'SELECT fingerprint, result_json FROM memory_events WHERE event_id=?', (event_id,)).fetchone()
                if row is None:
                    result = apply()
                    self._conn.execute(
                        'INSERT INTO memory_events (event_id, user_id, fingerprint, result_json) VALUES(?,?,?,?)',
                        (event_id, user_id, event_fingerprint, json.dumps(result, ensure_ascii=False)),
                    )
                else:
                    verify_receipt(event_id, row['fingerprint'], event_fingerprint)
                    result = json.loads(row['result_json'])
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise
            finally:
                self._in_transaction = False

    def unverifiable_receipts(self) -> int:
        """How many receipts predate fingerprinting and therefore cannot be replayed."""
        with self._lock:
            return self._conn.execute('SELECT COUNT(*) FROM memory_events WHERE fingerprint IS NULL').fetchone()[0]

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
            self._execute("DELETE FROM memory_events", ())
            return
        self._execute("DELETE FROM user_mastery WHERE user_id=?", (user_id,))
        self._execute("DELETE FROM error_log WHERE user_id=?", (user_id,))
        # 指纹上线前的旧收据没有 user_id，只能由整库清空带走；它们本来就无法核对（见 receipt.py）。
        self._execute("DELETE FROM memory_events WHERE user_id=?", (user_id,))

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
