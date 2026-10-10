"""DiagnosticAgent (F3): knowledge coverage diagnostics, explicitly not ability measurement.

The design document §10 rules out IRT/CAT/BKT because there is no real response data to calibrate
on, and acceptance A7 bans measurement vocabulary on an uncalibrated path. So this agent reports
coverage only: which modules and knowledge nodes the learner has actually touched, and how they
did on items the trust gate allows.

It returns no score interval, no ability estimate and no pass probability — those fields are
``None`` with ``estimate_basis="coverage_only"`` instead of being dressed up from accuracy. The
tier decides the rest: under ``published`` with zero expert-signed items in the library, the agent
must refuse to issue a diagnostic conclusion at all.

Right/wrong comes from the same place the learner profile gets it (``docs/agent_architecture.md``
§8 A10): ``TrustGate.reconcile_verdict`` prefers the library answer key, only falls back to the
caller's ``is_correct`` claim when the library cannot check it, and returns ``None`` when neither
exists. Counting the claim first would let anyone report "对" twenty times and walk away with a
full-mastery radar.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from services.common.models import (
    AnswerSubmission,
    DiagnosticReport,
    DiagnosticRequest,
    ModuleAbility,
    TrustTier,
)
from services.knowledge.graph_index import get_graph_index, library_for_exam
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import (
    CLAIMED_VERDICT_NOTICE,
    SIGNED_STATUSES,
    VERDICT_SOURCE_KEY,
    TrustGate,
)
from services.review.queue import get_review_queue

logger = logging.getLogger("services.diagnostic.agent")

WEAK_NODE_THRESHOLD = 0.6
COVERAGE_ONLY_NOTICE = (
    "诊断仅统计知识覆盖度：难度全部为 heuristic_* 且无真实作答校准数据，系统不输出分数区间、报告分或通过率。"
)
NO_JUDGEMENT_NOTICE = (
    "提交的作答都没有可用判据（库内该题答案不可核对，且没有可采信的申报）："
    "诊断不替学习者编对错，因此不出结论。"
)


class DiagnosticAgent:
    """Turns answer submissions into a coverage profile."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        queue=None,
    ) -> None:
        self.repository = repository or get_repository()
        self.queue = queue or get_review_queue()
        # 核对口径的档位写死在 research_internal（与 memory 同一做法）：让调用方自选档位，
        # 就等于让它自己挑一套更宽的答案键核对标准。
        self.verdict_gate = TrustGate("research_internal")

    def evaluate(self, request: DiagnosticRequest) -> DiagnosticReport:
        gate = TrustGate(request.trust_tier.value)
        kept: List[Tuple[AnswerSubmission, object]] = []
        rejected: List[dict] = []
        queued = 0

        for submission in request.submissions or []:
            meta = self.repository.get_meta(submission.question_id)
            if meta is None:
                rejected.append({"question_id": submission.question_id, "reason": "题目不在知识库索引内"})
                continue
            verdict = gate.classify_meta(meta)
            if not verdict.usable:
                row = {
                    "question_id": submission.question_id,
                    "reason": "；".join(verdict.notices) or "TrustGate 拒绝该题参与诊断",
                    "review_status": verdict.review_status,
                }
                rejected.append(row)
                self.queue.add(
                    reason=row["reason"],
                    user_id=request.user_id,
                    question_id=submission.question_id,
                    tier=request.trust_tier.value,
                    detail={"path": "diagnostic"},
                )
                queued += 1
                continue
            kept.append((submission, meta))

        notices = [COVERAGE_ONLY_NOTICE]

        if request.trust_tier is TrustTier.PUBLISHED:
            signed = [(s, m) for s, m in kept if m.review_status in SIGNED_STATUSES]
            if not signed:
                notices.append(
                    "published 档位下库内没有任何已签署（checked/expert_reviewed）的题目，"
                    "系统按设计拒绝出具诊断结论。"
                )
                return self._empty(request, notices + self._blocked_notices(rejected, queued), rejected)
            kept = signed

        if not kept:
            notices.append("没有可计入诊断的作答记录（未提交，或全部被信任门禁拒绝）。")
            return self._empty(request, notices + self._blocked_notices(rejected, queued), rejected)

        judged, unjudged, claimed, verdict_notices = self._attribute(kept)
        rejected.extend(unjudged)
        if not judged:
            notices.append(NO_JUDGEMENT_NOTICE)
            return self._empty(
                request, notices + self._blocked_notices(rejected, queued) + verdict_notices, rejected
            )

        module_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
        node_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
        node_modules: Dict[str, str] = {}
        for _, meta, correct in judged:
            module = meta.module or "未标注模块"
            module_stats[module]["total"] += 1
            module_stats[module]["correct"] += int(correct)
            for node_id in meta.node_ids or (f"question:{meta.question_id}",):
                node_stats[node_id]["total"] += 1
                node_stats[node_id]["correct"] += int(correct)
                node_modules.setdefault(node_id, module)

        correct_total = sum(1 for _, _, correct in judged if correct)
        radar = [
            ModuleAbility(
                module_id=module,
                module_name=module,
                mastery_rate=round(stats["correct"] / max(stats["total"], 1), 3),
                question_count=stats["total"],
                correct_count=stats["correct"],
            )
            for module, stats in sorted(module_stats.items())
        ]

        ranked_nodes = sorted(
            node_stats.items(),
            key=lambda kv: (kv[1]["correct"] / max(kv[1]["total"], 1), -kv[1]["total"]),
        )
        weak_points = [
            node_id
            for node_id, stats in ranked_nodes
            if stats["correct"] / max(stats["total"], 1) < WEAK_NODE_THRESHOLD
        ][:5]

        notices.extend(self._blocked_notices(rejected, queued))
        notices.extend(verdict_notices)
        if claimed:
            notices.append(
                f"计入诊断的 {len(judged)} 条对错里有 {claimed} 条采信了调用方申报"
                "（库内没有可核对的字母答案键，或本次没提交可核对的所选选项），系统未独立核验。"
            )
        notices.extend(self._library_context(request.exam_type, weak_points))
        actions = self._actions(weak_points, node_modules, request)
        return DiagnosticReport(
            user_id=request.user_id,
            exam_type=request.exam_type,
            raw_score=float(correct_total),
            max_raw_score=float(len(judged)),
            point_estimate=None,
            predicted_score_interval=None,
            pass_probability=None,
            radar_chart=radar,
            weak_points_top5=weak_points,
            recommended_actions=actions,
            estimate_basis="coverage_only",
            publishable=False,
            trust_tier=request.trust_tier,
            notices=notices,
            blocked_submissions=rejected,
        )

    # ----------------------------------------------------------------- helpers
    def _attribute(
        self, kept: List[Tuple[AnswerSubmission, object]]
    ) -> Tuple[List[Tuple[AnswerSubmission, object, bool]], List[dict], int, List[str]]:
        """Give every kept submission a verdict the report may count, plus who issued it.

        Returns ``(judged, blocked, claim_backed, notices)``; a submission with no basis at all is
        blocked rather than counted as wrong — an unanswered-but-uncheckable item says nothing
        about the learner, and silently scoring it 0 would put that fiction in the radar.
        """
        judged: List[Tuple[AnswerSubmission, object, bool]] = []
        blocked: List[dict] = []
        claim_backed = 0
        notices: List[str] = []
        for submission, meta in kept:
            record = self.repository.load_question(submission.question_id)
            checked, provenance, verdict_notices = self.verdict_gate.reconcile_verdict(
                record, submission.user_answer, submission.is_correct
            )
            if checked is None:
                # 不进待复核队列：答案不可核对的题已经按 answer_status 全列在 审查/待复核清单.md 里，
                # 运行时再按人次追加只会把唯一一位教研审核的队列淹掉。
                blocked.append(
                    {
                        "question_id": submission.question_id,
                        "reason": "；".join(verdict_notices) or "该次作答没有可计入诊断的对错判据",
                        "review_status": meta.review_status,
                    }
                )
                continue
            if submission.is_correct is not None and bool(submission.is_correct) != checked:
                logger.warning(
                    "question %s: reported is_correct=%s contradicts the verdict (basis=%s)",
                    submission.question_id,
                    submission.is_correct,
                    provenance,
                )
            if provenance != VERDICT_SOURCE_KEY:
                claim_backed += 1
            judged.append((submission, meta, checked))
            for notice in verdict_notices:
                # 逐条的申报提示由聚合那句替代：报告要说清"多少分是申报来的"，而不是重复同一句话。
                if notice != CLAIMED_VERDICT_NOTICE and notice not in notices:
                    notices.append(notice)
        return judged, blocked, claim_backed, notices

    @staticmethod
    def _blocked_notices(rejected: List[dict], queued: int) -> List[str]:
        """Count the refused submissions and say only what actually happened to them."""
        if not rejected:
            return []
        lines = [f"{len(rejected)} 条作答未计入诊断，逐条原因见 blocked_submissions。"]
        if queued:
            lines.append(f"其中 {queued} 条已转入待复核队列，等教研复核后才会重新可用。")
        return lines

    def _empty(self, request: DiagnosticRequest, notices: List[str], rejected: List[dict]) -> DiagnosticReport:
        return DiagnosticReport(
            user_id=request.user_id,
            exam_type=request.exam_type,
            raw_score=0.0,
            max_raw_score=0.0,
            point_estimate=None,
            predicted_score_interval=None,
            pass_probability=None,
            radar_chart=[],
            weak_points_top5=[],
            recommended_actions=["先通过 /practice/assemble 取一组真实题目作答，再回来做覆盖度诊断。"],
            estimate_basis="coverage_only",
            publishable=False,
            trust_tier=request.trust_tier,
            notices=notices,
            blocked_submissions=rejected,
        )

    def _library_context(self, exam_type: str, weak_points: List[str]) -> List[str]:
        library = library_for_exam(exam_type)
        if not library or not weak_points:
            return []
        graph = get_graph_index(library)
        notices: List[str] = []
        for node_id in weak_points:
            requirements = graph.requirements_for(node_id)
            if not requirements:
                notices.append(f"考点 {node_id} 在图谱内没有 aligned_to_requirement 边，无法给出条款依据。")
        notices.extend(graph.notices())
        return notices

    def _actions(self, weak_points: List[str], node_modules: Dict[str, str], request: DiagnosticRequest) -> List[str]:
        actions: List[str] = []
        for node_id in weak_points[:5]:
            pool = list(
                self.repository.find_questions(node_ids=[node_id], require_answer=True)
            )
            actions.append(
                f"考点 {node_id}（{node_modules.get(node_id, '未标注模块')}）可用题目 {len(pool)} 道，"
                "建议先做考点专练，再按计划复习。"
            )
        if not weak_points:
            actions.append("未发现低于阈值的考点，可按计划推进新考点学习。")
        actions.append(
            f"当前档位：{request.trust_tier.value}；诊断结果 publishable=false，不可对外作为能力结论。"
        )
        return actions
