"""复核队列的缺陷码：一条缺陷在队列里只许有一个名字。

`reason` 是教研（本仓库唯一的人工审核人）在 `GET /api/v1/review/queue` 里唯一的分类入口，
它同时也是队列的分桶名。所以这一列必须是**受控词表**：同一类缺陷在不同层、不同文案下都得落进
同一个桶，计数才能相加，优先级才能排。

旧写法是半码半文：判分量规那两侧写的是机器码（`rubric_signature_required`），诊断与检索却把
TrustGate 给人读的说明句子原样拼进来（`"；".join(verdict.notices)`），检索的双真相直接把整条
notice 当 reason，编排层用"编排降级"兜底。于是改一次说明文案，队列的分桶与计数整体漂移——
文案是本服务为了对用户诚实而写的，不是分类键；按它分桶等于让一句 UI 文本决定教研怎么看队列。
而真正的数据状态字段（`review_status`/`answer_status`/被违反的 schema 名）当时没写进行，
队列里只剩下一句话，复核者无从核对是哪一条状态触发的。

码只在这里增删。`services.review.queue.ReviewQueue.add` 在入口校验：词表外的码直接抛
`UnknownReasonError`，与 `graph_index` 对第 17 个边名的处理同一手法——把"不得再自造一个名字"
变成运行时约束，而不是评审意见。
"""
from __future__ import annotations

from typing import Dict


class UnknownReasonError(ValueError):
    """队列收到一个词表外的缺陷码。"""


#: 码 → 这条缺陷在说什么、教研要动哪个文件。措辞给人看，码本身是稳定键。
REVIEW_REASONS: Dict[str, str] = {
    "trust_gate_blocked": (
        "C 层按数据状态挡下这道题（quarantined / needs_fix / source_conflict / missing）："
        "要复核的是数据状态本身，明细见 detail.review_status / detail.answer_status"
    ),
    "orphan_card_hit": (
        "向量召回命中了卡片，题目索引里却没有这个 question_id："
        "卡片与题目索引已不是同一份数据，查 数据集/**/cards 与索引重建"
    ),
    "card_index_status_mismatch": (
        "同一道题的卡片状态与题目索引状态不一致（双真相）：以索引为准，"
        "两处取值见 detail.card_status / detail.index_status，需教研核定哪一侧是旧的"
    ),
    "rubric_signature_required": (
        "量规已找到但未署名（review.checked_by 为空 / official_scoring=false）："
        "运行时只能出维度反馈，签署在 数据集/**/rubrics 与 review 文件里由教研完成"
    ),
    "rubric_missing_for_task": (
        "这道题所属任务在库内根本没有量规条目：需要教研补条目，而不是在服务里加默认权重"
    ),
    "llm_unparseable_payload": (
        "模型返回的内容解析不出结构化结果：查 prompt 与 数据集/** 的题面形状，不改判分口径"
    ),
    "llm_guardrail_violation": (
        "模型产出未通过写权限/结构校验（禁止口径或 schema 不符）：被违反的 schema 名见 "
        "detail.schema_name，运行时不写 review.checked_by"
    ),
    "orchestrator_degraded": (
        "闭环某一步没出卡（空池、无作答记录、无判据等）：原句见 detail.reason_text，"
        "先按那句判断是数据缺口还是使用者输入缺口"
    ),
}


def describe(reason: str) -> str:
    """校验缺陷码并给出它的人读说明；词表外一律拒绝。"""
    try:
        return REVIEW_REASONS[reason]
    except KeyError:
        raise UnknownReasonError(
            f"复核队列收到词表外的缺陷码 {reason!r}。码只在 services/review/reasons.py 增删；"
            "给人读的说明文本请放进 detail，不要当分类键。"
        ) from None
