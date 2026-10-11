"""Event receipts: ``event_id`` says *which* attempt this is, the fingerprint says *what* the
learner actually did.

Without the second half a retry can only be handled wrongly in one of two ways: replay the old
result — which hands back "答错了" to a request that answered differently, permanently pairing
"卷面答对" with "复习记录答错" — or run it again, which counts the same question twice and feeds a
second error row into the review queue. So a receipt whose inputs differ is refused before any
learning write, and a receipt that predates fingerprinting is refused too: no fingerprint means
nothing proves the retry is the same attempt, and "assume it matches" is exactly the bug being
closed here (see ``docs/agent_architecture.md`` §8 A1 and ``docs/web_agent_architecture.md``).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class ReceiptConflict(Exception):
    """Same ``event_id``, different inputs: a new attempt wearing an old attempt's identity."""


class LegacyReceipt(ReceiptConflict):
    """Receipt written before fingerprints existed, so its inputs cannot be verified."""


CONFLICT_DETAIL = (
    "这次提交的参数与已记录的那次作答不一致（答案、耗时或选项修改次数改过）。系统已经按第一次的作答"
    "更新了掌握度与错题记录，重放会给出矛盾的对错，重跑会把同一题计成两次，因此两者都拒绝。"
    "要继续作答请重新组卷；本机学习记录清空后也可重来。"
)
LEGACY_DETAIL = (
    "这条作答记录写于事件指纹上线之前，系统无法证明这次请求与第一次是同一次作答，"
    "因此不重放旧结果、也不重复计数。清空本机学习记录（会一并清掉这些无指纹收据）后即可继续。"
)


def fingerprint(payload: Mapping[str, Any]) -> str:
    """Canonical digest of the inputs that decide a learning write."""
    canonical = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def event_inputs(event) -> dict:
    """Every field the caller submitted for this attempt — the digest pins the request, not the verdict.

    ``question_difficulty`` and ``current_node_mastery`` are the learner-invisible claims a caller
    makes *about* the question and *about* the learner; neither feeds the mastery formula or the
    attribution tree any more (the tree reads behaviour plus this learner's own persisted record).
    They still belong in the digest because a retry has to be the same submitted request: leaving
    them out would also invalidate every receipt written before this line, which is a worse price
    than digesting a field the service ignores.
    """
    return {
        'user_id': event.user_id,
        'exam': event.exam,
        'question_id': event.question_id,
        'node_id': event.node_id,
        'is_correct': event.is_correct,
        'selected_option': event.selected_option,
        'time_spent_seconds': event.time_spent_seconds,
        'option_flip_count': event.option_flip_count,
        'has_negation_in_stem': event.has_negation_in_stem,
        'is_typical_distractor': event.is_typical_distractor,
        'is_subjective': event.is_subjective,
        'subjective_rubric_misses': list(event.subjective_rubric_misses or []),
        'question_difficulty': event.question_difficulty,
    }


def event_fingerprint(event) -> str:
    return fingerprint(event_inputs(event))


def verify_receipt(event_id, stored, given):
    """Raise unless the stored receipt provably covers this exact request."""
    if stored is None:
        raise LegacyReceipt(f"{LEGACY_DETAIL}（event_id={event_id}）")
    if stored != given:
        raise ReceiptConflict(f"{CONFLICT_DETAIL}（event_id={event_id}）")
