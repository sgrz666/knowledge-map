"""SQLite documents and idempotency receipts; no mutable library data lives here."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException
from services.knowledge.repository import REPO_ROOT
from services.memory.receipt import fingerprint


def scope_data(ctx):
    return {key: getattr(ctx, key) for key in ('user_id', 'exam_type', 'school_level', 'subject')} | {
        'trust_tier': ctx.trust_tier.value}


def scope_key(ctx):
    return fingerprint(scope_data(ctx))


class LearningStore:
    def __init__(self, workbench):
        # Tests and callers with a custom workbench DB keep every associated file together.
        source = workbench.store.db.execute('PRAGMA database_list').fetchone()[2]
        fallback = Path(source).parent if source else REPO_ROOT / '.local_state'
        directory = Path(os.environ.get('KNOWLEDGE_MAP_STATE_DIR', fallback))
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / 'learning.sqlite3', check_same_thread=False, timeout=30)
        self.lock = threading.RLock()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS learning_documents '
                        '(id TEXT PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL, data TEXT NOT NULL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS learning_documents_scope ON learning_documents(scope,kind)')
        self.db.execute('CREATE TABLE IF NOT EXISTS learning_receipts '
                        '(scope TEXT, action TEXT, request TEXT, fingerprint TEXT NOT NULL, resource TEXT NOT NULL, '
                        'PRIMARY KEY(scope,action,request))')
        self.db.commit()

    @contextmanager
    def transaction(self):
        # BEGIN IMMEDIATE also serializes two workflow instances/processes sharing this DB.
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def get(self, ctx, kind, identity):
        with self.lock:
            row = self.db.execute('SELECT data FROM learning_documents WHERE id=? AND kind=? AND scope=?',
                                  (identity, kind, scope_key(ctx))).fetchone()
        return json.loads(row[0]) if row else None

    def latest(self, ctx, kind):
        with self.lock:
            row = self.db.execute('SELECT data FROM learning_documents WHERE scope=? AND kind=? '
                                  'ORDER BY rowid DESC LIMIT 1', (scope_key(ctx), kind)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, ctx, kind, identity, data):
        """写入即提交：脱离事务单独调用也不能静默丢失半提交。

        事务内的写入由上下文管理器统一 commit；这里自带的 commit 在事务内不生效，
        在事务外则保证调用方忘记包事务时数据仍然落盘。
        """
        with self.lock:
            self.db.execute('INSERT INTO learning_documents(id,kind,scope,data) VALUES(?,?,?,?) '
                            'ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                            (identity, kind, scope_key(ctx), json.dumps(data, ensure_ascii=False)))
            if not self.db.in_transaction:
                self.db.commit()

    def replay(self, req, action):
        row = self.db.execute('SELECT fingerprint,resource FROM learning_receipts '
                              'WHERE scope=? AND action=? AND request=?',
                              (scope_key(req), action, req.request_id)).fetchone()
        if row:
            if row[0] != fingerprint(req.model_dump(mode='json')):
                raise HTTPException(409, '同一 request_id 的请求参数已改变，请为新操作使用新的 request_id。')
            return row[1]
        return None

    def receipt(self, req, action, resource):
        self.db.execute('INSERT INTO learning_receipts VALUES(?,?,?,?,?)',
                        (scope_key(req), action, req.request_id,
                         fingerprint(req.model_dump(mode='json')), resource))
