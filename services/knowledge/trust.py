"""TrustGate: the single place where knowledge quality degrades agent behaviour.

Every agent asks this gate before showing a question, an answer, an explanation or a
legal clause. Two runtime tiers exist (see ``docs/agent_architecture.md`` §2):

``research_internal``
    Engineering/research builds. May read records that are still awaiting the 教研
    reviewer, but every such record carries an explicit notice.

``published``
    Anything a candidate could see. Only expert-signed content qualifies, which today
    is an empty set in both libraries — so the published tier must fail closed.

The gate never writes status; it only reads ``review`` / ``content`` / ``source`` and
decides. Scripts and LLMs may raise ``review.status`` to ``llm_enhanced`` at most;
``checked`` / ``expert_reviewed`` belong to the human reviewer alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Literal, Optional, Tuple

TrustTier = Literal["research_internal", "published"]

SIGNED_STATUSES = frozenset({"checked", "expert_reviewed"})
ANSWER_VERIFIED = "verified"
#: A3（验收 §8）：只有答案可核对的题才允许进组卷、判分与召回。缺答案/来源冲突的题一律挡住——
#: 无判分练习听起来温和，但它让学习者把一道教研还没核定答案的题当成练习材料，风险方向是错的。
SERVABLE_ANSWER_STATUSES = ("letter_only", "reference_only", ANSWER_VERIFIED)

QUARANTINE_NOTICE = "该题处于隔离/来源冲突状态，答案不可对外呈现，已转入待复核队列。"
UNREVIEWED_NOTICE = "该题尚未通过教研复核（review.status=%s），仅供内部研究，不可作为承诺性教学内容。"
ANSWER_MISSING_NOTICE = (
    "该题在库内没有可核对的答案（answer_status=%s），不进组卷、不判分、不进召回；"
    "答疑只能按题目自身文本讲解，不给出标准答案。"
)
DIFFICULTY_NOTICE = "难度为教研初估（%s），未使用真实作答数据校准，只用于选题排序，不构成任何测量学结论。"
CLAUSE_NOTICE = "条款原文经官方来源核对（source_verified），但与标准条目的映射仍为 %s。"
COPYRIGHT_NOTICE = (
    "库内题目、解析与条款均为科研用途（《著作权法》第二十四条第一款第（六）项），"
    "authorization_status=unknown，不得用于商业交付或对外宣称已获授权。"
)


@dataclass(frozen=True)
class TrustVerdict:
    question_id: str
    review_status: Optional[str]
    answer_status: Optional[str]
    usable: bool
    tier: Optional[TrustTier]
    answer_visibility: Literal["letter", "reference", "none"]
    notices: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def may_assert_answer(self) -> bool:
        return self.answer_visibility != "none"

    @property
    def servable_in_paper(self) -> bool:
        """组卷/判分口径（A3）：可核对答案的题才允许被送进练习与判分。"""
        return self.usable and self.answer_status in SERVABLE_ANSWER_STATUSES

    @property
    def signed(self) -> bool:
        return self.tier == "published"


@dataclass(frozen=True)
class RequirementVerdict:
    requirement_id: str
    citable: bool
    locator: Optional[dict]
    notices: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RubricVerdict:
    """Whether a rubric may produce a score. §10: unsigned rubric ⇒ feedback only."""

    rubric_id: Optional[str]
    found: bool
    signed: bool
    review_status: Optional[str]
    score_use: Optional[str]
    notices: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def may_score(self) -> bool:
        return self.found and self.signed


RUBRIC_UNSIGNED_NOTICE = (
    "量规权重与档位措辞未经教研签署（review.status=%s、checked_by=%s、expert_verified=%s），"
    "系统只给反馈不出分；签署需具名教研核定，脚本不得代签。"
)
RUBRIC_MISSING_NOTICE = (
    "库内没有该题型的量规实体，系统不使用内置模板出分，仅按题目文本给出可核对的反馈。"
)
RUBRIC_OFFICIAL_NOTICE = (
    "该量规为教研按考纲口径自建（official_scoring=%s），不是官方公布的评分细则原件，"
    "分数不可对外宣称为官方判分。"
)


class TrustGate:
    """Reads dataset status fields and returns per-item usability verdicts."""

    def __init__(self, tier: TrustTier = "research_internal") -> None:
        if tier not in ("research_internal", "published"):
            raise ValueError(f"unknown trust tier: {tier}")
        self.tier: TrustTier = tier

    # ------------------------------------------------------------- questions
    def classify(
        self,
        *,
        question_id: str,
        review: Optional[dict] = None,
        content: Optional[dict] = None,
        difficulty_meta: Optional[dict] = None,
        review_status: Optional[str] = None,
        answer_status: Optional[str] = None,
        difficulty_method: Optional[str] = None,
    ) -> TrustVerdict:
        review = review or {}
        content = content or {}
        difficulty_meta = difficulty_meta or {}

        status = review_status or review.get("status")
        ans_status = answer_status or content.get("answer_status")
        method = difficulty_method or difficulty_meta.get("method")

        notices: List[str] = []

        quarantined = status == "quarantined" or ans_status == "source_conflict"
        if quarantined:
            notices.append(QUARANTINE_NOTICE)
            return TrustVerdict(
                question_id=question_id,
                review_status=status,
                answer_status=ans_status,
                usable=False,
                tier=None,
                answer_visibility="none",
                notices=tuple(notices),
            )

        if ans_status == ANSWER_VERIFIED:
            visibility: Literal["letter", "reference", "none"] = "letter"
        elif ans_status == "letter_only":
            visibility = "letter"
        elif ans_status == "reference_only":
            visibility = "reference"
        else:
            visibility = "none"
            notices.append(ANSWER_MISSING_NOTICE % (ans_status or "missing"))

        signed = (
            status in SIGNED_STATUSES
            and bool(review.get("checked_by"))
            and bool(review.get("content_verified"))
            and ans_status == ANSWER_VERIFIED
        )
        if not signed:
            notices.append(UNREVIEWED_NOTICE % (status or "unknown"))

        if method:
            notices.append(DIFFICULTY_NOTICE % method)

        if self.tier == "published":
            usable = signed
            if not usable:
                notices.append("未通过教研签署，published 档位不返回该内容。")
        else:
            usable = True
        return TrustVerdict(
            question_id=question_id,
            review_status=status,
            answer_status=ans_status,
            usable=usable,
            tier="published" if signed else "research_internal",
            answer_visibility=visibility,
            notices=tuple(notices),
        )

    def classify_meta(self, meta) -> TrustVerdict:
        """Classify from an index projection without reading the record."""
        return self.classify(
            question_id=meta.question_id,
            review_status=meta.review_status,
            answer_status=meta.answer_status,
            difficulty_method=meta.difficulty_method,
        )

    def classify_record(self, record: dict) -> TrustVerdict:
        return self.classify(
            question_id=record.get("question_id", ""),
            review=record.get("review"),
            content=record.get("content"),
            difficulty_meta=record.get("difficulty_meta"),
        )

    def usable(self, verdict: TrustVerdict) -> bool:
        return verdict.usable

    def filter_usable(self, metas: Iterable) -> List:
        return [m for m in metas if self.classify_meta(m).usable]

    # --------------------------------------------------------- requirements
    def classify_requirement(self, requirement: Optional[dict]) -> RequirementVerdict:
        if requirement is None:
            return RequirementVerdict(
                requirement_id="",
                citable=False,
                locator=None,
                notices=("条款不在权威索引内，禁止引用。",),
            )
        rid = requirement.get("requirement_id", "")
        notices: List[str] = []
        citable = bool(requirement.get("source_verified"))
        if not citable:
            notices.append("条款未经官方来源核对，禁止对外引用。")
        mapping = requirement.get("mapping_status")
        if mapping and mapping != "mapped":
            notices.append(CLAUSE_NOTICE % mapping)
        locator = requirement.get("locator") or None
        # originals/ 不入库：locator 指向的本地 html 不能声称可下载
        if locator and locator.get("html_path"):
            notices.append("引用请标注 standard_id + 表格/行/表头定位，原始 html 未随仓库分发。")
        return RequirementVerdict(
            requirement_id=rid,
            citable=citable,
            locator=locator,
            notices=tuple(notices),
        )

    # ----------------------------------------------------------------- rubrics
    def classify_rubric(self, rubric: Optional[dict]) -> RubricVerdict:
        """Read the rubric's own signature state; never infer it from a file's existence."""
        if not rubric:
            return RubricVerdict(
                rubric_id=None,
                found=False,
                signed=False,
                review_status=None,
                score_use=None,
                notices=(RUBRIC_MISSING_NOTICE, COPYRIGHT_NOTICE),
            )

        review = rubric.get("review") or {}
        status = review.get("status") or rubric.get("review_status")
        checked_by = review.get("checked_by")
        verified = review.get("expert_verified", rubric.get("expert_verified"))
        signed = (
            status in SIGNED_STATUSES
            and bool(checked_by)
            and bool(verified)
        )
        # A CET band rubric transcribed from the official document is still pending the
        # application-side expert review, so its own score_use field decides.
        score_use = rubric.get("score_use")

        notices: List[str] = []
        if not signed:
            notices.append(RUBRIC_UNSIGNED_NOTICE % (status or "unknown", checked_by, verified))
        if rubric.get("official_scoring") is not None:
            notices.append(RUBRIC_OFFICIAL_NOTICE % rubric.get("official_scoring"))
        if score_use:
            notices.append("库内量规标注的分值用途：%s" % score_use)
        notices.append(COPYRIGHT_NOTICE)

        return RubricVerdict(
            rubric_id=rubric.get("rubric_id"),
            found=True,
            signed=signed,
            review_status=status,
            score_use=score_use,
            notices=tuple(notices),
        )

    # ------------------------------------------------------------- responses
    def response_notices(self, verdicts: Iterable[TrustVerdict]) -> List[str]:
        """De-duplicated notices to attach to a response payload."""
        seen: List[str] = []
        for v in verdicts:
            for n in v.notices:
                if n not in seen:
                    seen.append(n)
        return seen

    def fail_closed(self) -> dict:
        """What the runtime must return when the tier has nothing to serve."""
        return {
            "trust_tier": self.tier,
            "code": "no_qualified_content",
            "message": (
                "当前档位没有通过教研复核的内容，系统不返回任何题目或答案。"
                "请等待复核队列（审查/待复核清单.md）清空后重试。"
            )
            if self.tier == "published"
            else "隔离区内容不可用于组卷，请扩大候选池或修复待复核项。",
        }
