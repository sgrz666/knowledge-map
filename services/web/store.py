"""Persist paper ownership and submissions; repeated HTTP requests do not repeat reviews.

A submission row is a receipt too, so it carries the same kind of input fingerprint as the memory
event receipts (``services/memory/receipt.py``): the row says which attempt it is, the fingerprint
says what the learner actually submitted. Without it a retry that changed the answer would be
served the stored "答错了" as if it were that new answer's verdict.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path
from services.knowledge.repository import REPO_ROOT
from services.memory.receipt import fingerprint


def submission_inputs(req) -> dict:
    """The request fields that decide what this submission records."""
    return {
        'user_id': req.user_id,
        'paper_id': req.paper_id,
        'question_id': req.question_id,
        'answer': req.answer,
        'trust_tier': req.trust_tier.value,
        'time_spent_seconds': req.time_spent_seconds,
        'option_flip_count': req.option_flip_count,
    }


def submission_fingerprint(req) -> str:
    return fingerprint(submission_inputs(req))


class WorkbenchStore:
    def __init__(self, path=None):
        directory = Path(os.environ.get('KNOWLEDGE_MAP_STATE_DIR', REPO_ROOT / '.local_state'))
        path = Path(path) if path else directory / 'workbench.sqlite3'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, user TEXT NOT NULL, data TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP)')
        self.db.execute('CREATE TABLE IF NOT EXISTS submissions (paper TEXT, question TEXT, data TEXT NOT NULL, fingerprint TEXT, PRIMARY KEY(paper,question))')
        # CREATE TABLE IF NOT EXISTS 不会给已经存在的库补列：指纹上线之前写下的提交没有指纹，
        # 那些行只能留 NULL 当"无法核对"，不能猜一个出来回填（原请求的选项修改次数没存过）。
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(submissions)')}
        if 'fingerprint' not in columns:
            self.db.execute('ALTER TABLE submissions ADD COLUMN fingerprint TEXT')
        self.db.commit()

    def save_paper(self, user, data):
        with self.lock:
            self.db.execute('INSERT INTO papers(id,user,data) VALUES(?,?,?)', (data['paper_id'], user, json.dumps(data, ensure_ascii=False)))
            self.db.commit()

    def paper(self, user, paper):
        with self.lock:
            row = self.db.execute('SELECT data FROM papers WHERE id=? AND user=?', (paper, user)).fetchone()
            return json.loads(row[0]) if row else None

    def submission(self, paper, question):
        with self.lock:
            row = self.db.execute('SELECT data FROM submissions WHERE paper=? AND question=?', (paper, question)).fetchone()
            return json.loads(row[0]) if row else None

    def submission_receipt(self, paper, question):
        """``(recorded response, fingerprint)`` for this attempt, or None when there is none."""
        with self.lock:
            row = self.db.execute('SELECT data, fingerprint FROM submissions WHERE paper=? AND question=?',
                                  (paper, question)).fetchone()
            return (json.loads(row[0]), row[1]) if row else None

    def save_submission(self, paper, question, data, fp=None):
        with self.lock:
            self.db.execute('INSERT INTO submissions VALUES(?,?,?,?)', (paper, question, json.dumps(data, ensure_ascii=False), fp))
            self.db.commit()

    def submissions(self, user):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute(
                'SELECT s.data FROM submissions s JOIN papers p ON p.id=s.paper WHERE p.user=? ORDER BY p.created DESC LIMIT 100', (user,)).fetchall()]

    def paper_submissions(self, paper):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM submissions WHERE paper=?', (paper,)).fetchall()]

    def latest_paper(self, user, *, exam=None, school_level=None, subject=None, trust_tier=None):
        with self.lock:
            for row in self.db.execute('SELECT data FROM papers WHERE user=? ORDER BY rowid DESC', (user,)):
                data = json.loads(row[0])
                if any(expected is not None and data.get(key) != expected for key, expected in (
                    ('exam_type', exam), ('school_level', school_level), ('subject', subject), ('trust_tier', trust_tier))):
                    continue
                return data
            return None
