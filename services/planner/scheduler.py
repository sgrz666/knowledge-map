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

Missing mastery is treated as *unseen*, not as a made-up 0.40 baseline: an unseen node is ranked
by how much practice material the library actually holds for it, and the plan says so.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from services.common.models import DailyPlan, DailyTaskItem, UserMasteryRecord
from services.knowledge.graph_index import get_graph_index, library_for_exam
from services.knowledge.naming import exam_values
from services.knowledge.repository import KnowledgeRepository, get_repository
from services.knowledge.trust import TrustGate

MINUTES_PER_QUESTION = 2.0
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
    f"日程里除模考那一格外，分钟数都是服务按每题 {MINUTES_PER_QUESTION:g} 分钟估的配速，"
    "不是官方题均用时；模考那一格取的是库内考务规格的卷面用时。"
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
        """Every knowledge node that the current tier can actually practise, with its real pool."""
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
                    }
                row["pool"] += 1
                if meta.difficulty is not None:
                    row["difficulty_sum"] += float(meta.difficulty)
                    row["difficulty_n"] += 1

        rows: List[dict] = []
        for node_id, row in pools.items():
            row["requirements"] = len(graph.requirements_for(node_id)) if graph else 0
            row["avg_difficulty"] = (
                round(row["difficulty_sum"] / row["difficulty_n"], 4) if row["difficulty_n"] else None
            )
            row.pop("difficulty_sum", None)
            row.pop("difficulty_n", None)
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
                take = min(len(due), max(1, int(review_cap / MINUTES_PER_QUESTION)))
                minutes = int(take * MINUTES_PER_QUESTION)
                if minutes <= budget:
                    budget -= minutes
                    tasks.append(
                        DailyTaskItem(
                            task_type="fsrs_review",
                            title=f"FSRS 到期错题回炉（{take} 题）",
                            estimated_minutes=minutes,
                            target_question_count=take,
                        )
                    )

            if cursor >= len(ranked):
                if not exhausted_reported:
                    notices.append(POOL_EXHAUSTED_NOTICE)
                    exhausted_reported = True
                cursor = 0
            focus = self._next_nodes(ranked, cursor)
            cursor += len(focus)

            new_minutes = int(budget * NEW_NODE_SHARE)
            per_node = max(0, int(new_minutes / max(len(focus), 1)))
            for node_id in focus:
                if per_node < MINUTES_PER_QUESTION:
                    break
                count = min(by_node[node_id]["pool"], int(per_node / MINUTES_PER_QUESTION))
                if count <= 0:
                    continue
                minutes = int(count * MINUTES_PER_QUESTION)
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
                count = min(by_node[node_id]["pool"], 3)
                minutes = int(count * MINUTES_PER_QUESTION)
                if count <= 0 or minutes > budget:
                    continue
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
