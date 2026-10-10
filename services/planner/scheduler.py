"""Scheduling over the library's own nodes — no built-in syllabus.

The previous version of this file shipped ``DEFAULT_SYLLABUS_NODES``: thirteen hardcoded 教资
syllabus nodes with weights, frequencies and prerequisites, i.e. a second copy of the knowledge
graph living inside service code. Acceptance A1 forbids that, so the candidate list now comes
from ``KnowledgeRepository`` (nodes that questions actually attach to, with their real pool
sizes) and the ordering comes from ``GraphIndex.topological_order``, which refuses to use
prerequisite edges while none are confirmed (§3.3: 先修边暂不入算法).

一场模考要多久同样来自 ``repository.mock_minutes_for(exam)``：旧版写死 ``MOCK_MINUTES = 90``，
而库内卷面是 NTCE 120 / CET 逐节 125——90 既让日历在 60 分钟的一天承诺做不完的模考，也替官方考试
编了一个教研从未核定的时长。规格给不出一致用时时就不排模考，并在 notices 里说明。

而"每题几分钟"这个配速数也不归本文件所有：它住在 ``services.common.pacing``，组卷层给一卷限时时
用的是同一份。两个层各抄一个数，就会出现日历按 2 分钟一题排、卷子按 1 分钟一题发的打架。
配速只是兜底：库里说得出单题用时的地方是题面约束（``repository.item_time_limit``，经索引投影
读进 ``QuestionMeta.time_limit_minutes``），排课一格能放几题先按这些题的真实用时算。以前一律按
每题 2 分钟折算，于是一道写明 30 分钟的 CET 作文被排进 2 分钟的一格——同一批题，日历许的时间与
组卷发的限时由同一份库给出却互相打脸。

Missing mastery is treated as *unseen*, not as a made-up 0.40 baseline: an unseen node is ranked
by how much practice material the library actually holds for it, and the plan says so.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from services.common.models import DailyPlan, DailyTaskItem, UserMasteryRecord
from services.common.pacing import MINUTES_PER_QUESTION, paper_minutes
from services.knowledge.graph_index import get_graph_index, library_for_exam
from services.knowledge.naming import exam_values
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate

REVIEW_SHARE = 0.30
NEW_NODE_SHARE = 0.55
NODES_PER_DAY = 2
MOCK_EVERY_DAYS = 7
WEAK_MASTERY_THRESHOLD = 0.5

UNSEEN_NOTICE = (
    "排课依据为库内真实题池与已持久化的掌握度；未练习过的考点按“无掌握度记录”处理，"
    "不套用任何默认基线分。"
)
PACING_NOTICE = (
    "日程里的分钟数按“先问库内、问不到才估”算：带题面用时约束的题"
    "（extra.task_constraints.time_limit_minutes）按题面约束计，"
    f"库里说不出用时的题按服务配速每题 {MINUTES_PER_QUESTION:g} 分钟估——后者不是官方题均用时；"
    "模考那一格取库内考务规格的卷面用时。一格排不进一道完整的题时宁可少排或不排，"
    "日历不会把官方题面用时改短来塞进格子。"
)
REVIEW_UNFIT_NOTICE = (
    "有到期题的库内题面用时超过当日复习格能分到的分钟数，本日不排这些题："
    "日历不把官方题面用时改短来凑一格，也不会用配速估时去覆盖题面约束。"
)
POOL_EXHAUSTED_NOTICE = (
    "新考点已排完，后续日程改为对已排考点做巩固练习；如需更大题量请先扩充题库，系统不会虚构考点。"
)


class AdaptiveScheduler:
    """Builds the day-by-day calendar from library facts and the learner's persisted state."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        store=None,
    ) -> None:
        self.repository = repository or get_repository()
        self.store = store

    # ------------------------------------------------------------- candidates
    def candidate_nodes(self, exam: str, *, tier: str = "research_internal") -> List[dict]:
        """Every knowledge node that the current tier can actually practise, with its real pool
        and the pool's own per-item minutes (题面约束优先，库里说不出才按共用配速估)。"""
        gate = TrustGate(tier)  # type: ignore[arg-type]
        library = library_for_exam(exam)
        graph = get_graph_index(library) if library else None

        pools: Dict[str, dict] = {}
        for meta in self.repository.find_questions(
            exams=exam_values(exam), require_nodes=True, require_answer=True
        ):
            if not gate.classify_meta(meta).usable:
                continue
            for node_id in meta.node_ids:
                row = pools.get(node_id)
                if row is None:
                    row = pools[node_id] = {
                        "node_id": node_id,
                        "pool": 0,
                        "module": meta.module or "未标注模块",
                        "difficulty_sum": 0.0,
                        "difficulty_n": 0,
                        "minutes_sum": 0.0,
                    }
                row["pool"] += 1
                if meta.difficulty is not None:
                    row["difficulty_sum"] += float(meta.difficulty)
                    row["difficulty_n"] += 1
                # 题面说得出用时就用题面的，说不出才落到共用配速（与组卷给一卷限时用的是同一份读法）。
                if meta.time_limit_minutes:
                    row["minutes_sum"] += meta.time_limit_minutes
                else:
                    row["minutes_sum"] += MINUTES_PER_QUESTION

        rows: List[dict] = []
        for node_id, row in pools.items():
            row["requirements"] = len(graph.requirements_for(node_id)) if graph else 0
            row["avg_difficulty"] = (
                round(row["difficulty_sum"] / row["difficulty_n"], 4) if row["difficulty_n"] else None
            )
            # 这个考点的题池做一题要多久：按池内每题的真实用时平均，不是服务拍的题均分钟数。
            row["minutes_per_item"] = round(row["minutes_sum"] / max(row["pool"], 1), 3)
            row.pop("difficulty_sum", None)
            row.pop("difficulty_n", None)
            row.pop("minutes_sum", None)
            rows.append(row)
        rows.sort(key=lambda r: (-r["pool"], r["node_id"]))
        return rows

    # ------------------------------------------------------------- scheduling
    def schedule(
        self,
        *,
        user_id: str,
        exam: str,
        days: int,
        daily_minutes: int,
        mastery_records: Optional[List[UserMasteryRecord]] = None,
        tier: str = "research_internal",
    ) -> Tuple[List[DailyPlan], List[str], str]:
        notices: List[str] = []
        rows = self.candidate_nodes(exam, tier=tier)
        if not rows:
            notices.append("当前档位内没有可用于排课的考点（题池为空），已停止生成日历而不是用内置大纲填充。")
            return [], notices, ""

        by_node = {row["node_id"]: row for row in rows}
        mastery_map = self._mastery_map(user_id, mastery_records)
        library = library_for_exam(exam)
        ranked, prereq_note = self._rank(rows, mastery_map, library)
        if library:
            notices.extend(get_graph_index(library).notices())
        if prereq_note:
            notices.append(prereq_note)
        notices.append(UNSEEN_NOTICE)
        notices.append(PACING_NOTICE)

        # 一场模考要多久只问库内考务规格（与组卷、时序机共用同一份读法）。以前这里写死 90 分钟，
        # 于是日历既会在 60 分钟的一天承诺一场做不完的模考，也替官方考试编了一个教研没核定的时长。
        exam_minutes = self.repository.mock_minutes_for(exam)
        if exam_minutes is None:
            notices.append(
                "库内该考试的考务规格没有一致的卷面用时（逐节缺失或各套不同），日程不排限时模考；"
                "要排模考请先由教研把 paper_specs 的用时补齐，系统不替考试编一个分钟数。"
            )

        due = self._due_question_ids(user_id)
        due_minutes = self._due_item_minutes(due)
        today = date.today()
        plans: List[DailyPlan] = []
        cursor = 0
        exhausted_reported = False

        for index in range(days):
            budget = daily_minutes
            tasks: List[DailyTaskItem] = []

            if exam_minutes and (index + 1) % MOCK_EVERY_DAYS == 0 and budget >= exam_minutes:
                budget -= exam_minutes
                tasks.append(
                    DailyTaskItem(
                        task_type="mock_sprint",
                        title=f"限时模考冲刺（库内卷面 {exam_minutes} 分钟，按官方规格组卷）",
                        estimated_minutes=exam_minutes,
                        target_question_count=0,
                    )
                )

            review_cap = int(budget * REVIEW_SHARE)
            if due:
                take = self._fit_within(due_minutes, review_cap)
                if take:
                    minutes = paper_minutes(due_minutes[:take])["total"]
                    budget -= minutes
                    tasks.append(
                        DailyTaskItem(
                            task_type="fsrs_review",
                            title=f"FSRS 到期错题回炉（{take} 题）",
                            estimated_minutes=minutes,
                            target_question_count=take,
                        )
                    )
                else:
                    notices.append(REVIEW_UNFIT_NOTICE)

            if cursor >= len(ranked):
                if not exhausted_reported:
                    notices.append(POOL_EXHAUSTED_NOTICE)
                    exhausted_reported = True
                cursor = 0
            focus = self._next_nodes(ranked, cursor)
            cursor += len(focus)

            new_minutes = int(budget * NEW_NODE_SHARE)
            per_node = new_minutes / max(len(focus), 1)
            for node_id in focus:
                # 一格能排几题，按这个考点题池的真实用时算：CET 写作题池每题 30 分钟，
                # 16 分钟的一格就排不下一题——把 30 分钟的题塞进 2 分钟的格子是日历在撒谎。
                pace = by_node[node_id]["minutes_per_item"]
                count = min(by_node[node_id]["pool"], int(per_node // pace)) if pace > 0 else 0
                if count <= 0:
                    continue
                minutes = int(round(count * pace))
                budget -= minutes
                tasks.append(
                    DailyTaskItem(
                        task_type="new_node_learning",
                        node_id=node_id,
                        title=f"考点学习：{node_id}",
                        estimated_minutes=minutes,
                        target_question_count=count,
                    )
                )

            weak_focus = [node_id for node_id in focus if mastery_map.get(node_id) is not None]
            for node_id in weak_focus[:2]:
                pace = by_node[node_id]["minutes_per_item"]
                if pace <= 0:
                    continue
                count = min(by_node[node_id]["pool"], 3, int(budget // pace))
                if count <= 0:
                    continue
                minutes = int(round(count * pace))
                budget -= minutes
                tasks.append(
                    DailyTaskItem(
                        task_type="weakness_drill",
                        node_id=node_id,
                        title=f"薄弱考点专项：{node_id}（掌握度 {mastery_map[node_id]:.2f}）",
                        estimated_minutes=minutes,
                        target_question_count=count,
                    )
                )

            plans.append(
                DailyPlan(
                    day_index=index + 1,
                    date_str=(today + timedelta(days=index)).isoformat(),
                    focus_module=(
                        by_node[focus[0]]["module"] if focus else rows[0]["module"]
                    ),
                    tasks=tasks,
                    total_minutes=sum(t.estimated_minutes for t in tasks),
                )
            )

        return plans, self._dedupe(notices), prereq_note

    # ---------------------------------------------------------------- helpers
    def _mastery_map(self, user_id: str, records: Optional[List[UserMasteryRecord]]) -> Dict[str, float]:
        """Only scores that exist — persisted first, then whatever the caller supplied."""
        merged: Dict[str, float] = {}
        for record in records or []:
            merged[record.node_id] = record.mastery_score
        if self.store is not None:
            for node in self.store.weak_node_ids(user_id, limit=20):
                record = self.store.get(user_id, node)
                if record is not None:
                    merged[node] = record.mastery_score
        return merged

    def _rank(
        self, rows: List[dict], mastery_map: Dict[str, float], library: Optional[str]
    ) -> Tuple[List[str], str]:
        ordered = sorted(
            rows,
            key=lambda row: self._sort_key(row, mastery_map),
        )
        node_ids = [row["node_id"] for row in ordered]
        if library is None:
            return node_ids, ""
        graph = get_graph_index(library)
        ranked, note = graph.topological_order(node_ids)
        return (ranked or node_ids), note

    @staticmethod
    def _sort_key(row: dict, mastery_map: Dict[str, float]) -> Tuple[int, float, int, str]:
        node_id = row["node_id"]
        if node_id in mastery_map:
            score = mastery_map[node_id]
            # Weak-but-known nodes first, weakest at the top.
            return (0, score, -row["pool"], node_id) if score < WEAK_MASTERY_THRESHOLD else (2, score, -row["pool"], node_id)
        # Unseen: no invented baseline, order by how much material the library really holds.
        return (1, 0.0, -row["pool"], node_id)

    def _due_question_ids(self, user_id: str) -> List[str]:
        if self.store is None:
            return []
        return list(self.store.due_question_ids(user_id, limit=20))

    def _due_item_minutes(self, question_ids: List[str]) -> List[Optional[int]]:
        """到期题的用时只问题面约束（与组卷同一个读法）；None 是库里说不出，留给共用配速估。"""
        return [
            meta.time_limit_minutes if meta is not None else None
            for meta in (self.repository.get_meta(qid) for qid in question_ids)
        ]

    @staticmethod
    def _fit_within(item_minutes: List[Optional[int]], cap: int) -> int:
        """按到期题顺序逐题累加真实用时，加到再加一题就超过当日复习格为止。"""
        take = 0
        while take < len(item_minutes) and (paper_minutes(item_minutes[: take + 1])["total"] or 0) <= cap:
            take += 1
        return take

    @staticmethod
    def _dedupe(notices: List[str]) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for notice in notices:
            if notice and notice not in seen:
                seen.add(notice)
                out.append(notice)
        return out

    @staticmethod
    def _next_nodes(ranked: List[str], cursor: int) -> List[str]:
        """Take the next slice of the ranked list; the caller cycles when it reaches the end."""
        return ranked[cursor : cursor + NODES_PER_DAY]
