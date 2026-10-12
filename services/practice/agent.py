"""PracticeEngineAgent: assembles papers from the knowledge library through TrustGate.

Nothing here embeds a question, an answer or a difficulty value; every item is read from
``数据集/**/questions`` by ``question_id``, filtered by the gate for the requested tier,
and mock exams follow the official blueprints in ``paper_specs.jsonl``.
"""
from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from datetime import date
from typing import List, Optional, Sequence, Tuple

from services.common.models import (
    AssemblePaperRequest,
    PracticeMode,
    PracticePaperResponse,
    TrustTier,
)
from services.common.pacing import paper_minutes, pacing_notice
from services.common.weakness import WEAK_MASTERY_BAR
from services.knowledge.naming import exam_values, module_values
from services.knowledge.repository import (
    KnowledgeRepository,
    QuestionMeta,
    get_repository,
    item_time_limit,
    mock_minutes,
    timed_stages,
)
from services.knowledge.trust import COPYRIGHT_NOTICE, TrustGate
from services.memory.agent import MemoryReviewAgent
from services.practice.cet_statemachine import CETExamStateMachine

NO_CONTENT_NOTICE = "当前档位没有可用于组卷的内容；请修复待复核队列或改用 research_internal 档位。"
NO_INPUT_NOTICE = "该模式需要输入（考点/错题/模块），系统不猜测填充；请携带 target_node、weak_node_ids 或 wrong_question_ids 重试。"

MODE_TITLES = {
    PracticeMode.POINT_FOCUS: "【考点专练】{scope} 定向强化",
    PracticeMode.WEAKNESS_BREAKTHROUGH: "【薄弱突击】诊断驱动的薄弱考点歼灭",
    PracticeMode.ERROR_ELIMINATION: "【错题消灭】FSRS 到期错题重做",
    PracticeMode.DAILY_PRACTICE: "【每日一练】真题池随机抽练",
    PracticeMode.HIGH_FREQUENCY: "【高频冲刺】按历年考点覆盖度排序",
    PracticeMode.TIMED_SPRINT: "【限时快练】客观题节奏冲刺",
    PracticeMode.MOCK_EXAM: "【全真模考】{scope} 官方考务时序卷",
}


class PracticeEngineAgent:
    """Agent assembling tailored question sets across 7 practice modalities."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        memory: Optional[MemoryReviewAgent] = None,
    ) -> None:
        self.repository = repository or get_repository()
        self._memory = memory

    @property
    def memory(self) -> MemoryReviewAgent:
        if self._memory is None:
            self._memory = MemoryReviewAgent()
        return self._memory

    # --------------------------------------------------------------- public
    def assemble_paper(self, req: AssemblePaperRequest) -> PracticePaperResponse:
        gate = TrustGate(req.trust_tier.value)
        notices: List[str] = [COPYRIGHT_NOTICE]

        exams = exam_values(req.exam_type)
        modules, module_notice = module_values(req.exam_type, req.target_module)
        if module_notice:
            notices.append(module_notice)

        # A3: 缺答案/来源冲突的题不进组卷，索引查询层面就挡住，池子大小才是可核对答案的池子。
        answer_pool = list(self.repository.find_questions(
            exams=exams, require_answer=True, school_level=req.school_level, subject=req.subject
        ))
        pool = [m for m in answer_pool if m.has_answerable_text]
        extraction_gap = len(answer_pool) - len(pool)
        usable_pool = gate.filter_usable(pool)

        spec = None
        structure: List[dict] = []
        if req.practice_mode == PracticeMode.MOCK_EXAM:
            selection, spec, mode_notices, structure, seed_text = self._select_mock(
                req, usable_pool, modules
            )
        else:
            selection, mode_notices, seed_text = self._select_adaptive(
                req, usable_pool, gate, modules, exams
            )
        notices.extend(mode_notices)

        questions, item_verdicts = self._materialise(selection, gate, req.trust_tier)
        notices.extend(gate.response_notices(item_verdicts))
        if extraction_gap:
            notices.append(
                f"{extraction_gap} 题在库内只剩套名与题号（content.stem 为空且无选项可勾），"
                "已从组卷池剔除而不冒充题面；这是题干抽取缺口，需教研补抽取后才可练习。"
            )

        # 模考时序只认这份规格：能列出逐节用时就有时序机，列不出就没有——服务不替官方考试编时间表。
        stages = timed_stages(spec)
        # 单题用时先问库内题面约束（extra.task_constraints），库里说不出来的题才落到共用配速估计。
        breakdown = paper_minutes([q.get("time_limit_minutes") for q in questions])
        limit = self._time_limit(req, spec, breakdown)
        scope = req.target_node or req.target_module or req.exam_type
        title = MODE_TITLES.get(req.practice_mode, "【专项练习】{scope}").format(scope=scope)
        notices.extend(self._timing_notices(req, spec, stages, questions, breakdown))

        if not questions:
            notices.append(
                NO_CONTENT_NOTICE
                if not usable_pool
                else "过滤后没有可组卷的题目（题型/档位/考点条件过窄），已如实返回空卷而不是补造题目。"
            )

        planned = sum(int(e.get("planned_count") or 0) for e in structure) or req.item_count
        return PracticePaperResponse(
            paper_id=f"paper-{req.exam_type.lower()}-{req.practice_mode.value[:4]}-{self._token(req)}",
            title=title,
            exam_type=req.exam_type,
            practice_mode=req.practice_mode,
            questions=questions,
            total_items=len(questions),
            time_limit_minutes=limit,
            stage_state=CETExamStateMachine.get_initial_state(spec),
            trust_tier=req.trust_tier,
            pool_size=len(usable_pool),
            shortfall=max(0, planned - len(questions)),
            spec_id=(spec or {}).get("spec_id"),
            structure=structure,
            notices=notices,
            selection_seed=seed_text,
        )

    def node_frequency(self, exam: str, top: int = 12) -> List[Tuple[str, int]]:
        """Rank knowledge nodes by how many real questions assess them within one exam."""
        counter: Counter = Counter()
        for meta in self.repository.find_questions(exams=exam_values(exam)):
            for node in meta.node_ids:
                counter[node] += 1
        return counter.most_common(top)

    # ---------------------------------------------------------- selection
    def _select_adaptive(
        self,
        req: AssemblePaperRequest,
        usable_pool: Sequence[QuestionMeta],
        gate: TrustGate,
        modules: Optional[Tuple[str, ...]],
        exams: Tuple[str, ...],
    ) -> Tuple[List[QuestionMeta], List[str], str]:
        notices: List[str] = []
        mode = req.practice_mode
        rng, seed_text = self._seeded(req, mode.value)
        pool = self._avoid(list(usable_pool), req, notices)

        if mode == PracticeMode.ERROR_ELIMINATION:
            ids = list(req.wrong_question_ids) or self.memory.due_question_ids(
                req.user_id, limit=req.item_count
            )
            if not ids:
                notices.append("FSRS 队列为空：该 learner 尚无错题记录，请先作答或完成诊断。")
                return [], notices, seed_text
            metas = []
            unknown = skipped = untexted = 0
            for qid in ids:
                meta = self.repository.get_meta(qid)
                if (meta is None or meta.exam not in exams
                    or (req.school_level and meta.school_level != req.school_level)
                    or (req.subject and meta.subject != req.subject)):
                    unknown += 1
                    continue
                if not meta.has_answerable_text:
                    # 错题本里的题也可能只有套名没有题干：重做它等于对着一行标题作答，只能跳过。
                    untexted += 1
                    continue
                if gate.classify_meta(meta).servable_in_paper:
                    metas.append(meta)
                else:
                    # 错题本里可能有教研尚未核定答案的题：重做它没有判分依据，只能跳过并说明。
                    skipped += 1
            if unknown:
                notices.append(f"{unknown} 道错题不在库内或不属于当前考试，已跳过。")
            if untexted:
                notices.append(
                    f"{untexted} 道错题在库内只剩套名与题号（content.stem 为空且无选项可勾），"
                    "已跳过：没有题面的重做无从下手，系统不用猜测题干补位。"
                )
            if skipped:
                notices.append(
                    f"{skipped} 道错题在库内没有可核对的答案（answer_status 非 letter_only/reference_only/verified），"
                    "已跳过：没有答案键的重做没有判分依据，系统不用猜测答案补位。"
                )
            # 到期队列是 FSRS 算出来的，不是随机池：换一批只改这批的先后，不删没做过的到期题。
            if req.rotation:
                notices.append("错题回炉按到期队列出题：换一批只换这批题的先后顺序，到期未做的题不会因此消失。")
            self._shuffle(metas, rng)
            return metas[: req.item_count], notices, seed_text

        if mode in (PracticeMode.POINT_FOCUS,):
            if req.target_node:
                pool = [m for m in pool if req.target_node in m.node_ids]
            elif modules:
                pool = [m for m in pool if m.module in modules]
            else:
                notices.append(NO_INPUT_NOTICE)
                return [], notices, seed_text

        elif mode == PracticeMode.WEAKNESS_BREAKTHROUGH:
            supplied = list(req.weak_node_ids)
            nodes = supplied or self.memory.weak_node_ids(req.user_id)
            if nodes and not supplied:
                # 记忆里的"相对最低"只是按掌握度排序取前几名，与薄弱线无关：全都已掌握时它照样给出名字。
                notices.append(
                    f"本轮薄弱项取自掌握度相对最低的 {len(nodes)} 个考点（相对排序，不代表低于薄弱线 "
                    f"{WEAK_MASTERY_BAR:.2f}）；按线筛出的薄弱项在诊断结果里。"
                )
            elif supplied:
                # 这一层只按传入的考点筛题，线是来源方判的；不写清这点，响应标题的"薄弱"就成了本层自证的结论。
                notices.append(
                    f"本轮的 {len(supplied)} 个考点由调用方传入，本层只按它们筛题：是否低于薄弱线 "
                    f"{WEAK_MASTERY_BAR:.2f} 由来源方判定（诊断按考点作答正确率比线），本层未独立核对。"
                )
            if nodes:
                pool = [m for m in pool if set(nodes) & set(m.node_ids)]
            elif modules:
                pool = [m for m in pool if m.module in modules]
            else:
                ranked = [n for n, _ in Counter(n for m in pool for n in m.node_ids).most_common(3)]
                pool = [m for m in pool if set(ranked) & set(m.node_ids)]
                notices.append("无诊断记录，已回退到历年覆盖度最高的考点抽题（非个性化薄弱项）。")

        elif mode == PracticeMode.HIGH_FREQUENCY:
            ranked = [n for n, _ in Counter(n for m in pool for n in m.node_ids).most_common(12)]
            if modules:
                pool = [m for m in pool if m.module in modules]
            ranked_set = set(ranked)
            scored = [(len(ranked_set & set(m.node_ids)), m.question_id, m) for m in pool]
            scored.sort(key=lambda x: (-x[0], x[1]))
            ranked_pool = [m for _, _, m in scored if m.node_ids]
            # 覆盖度排序决定"从哪一段抽"，段内按种子洗牌：高频优先不等于每次都是同一批题。
            band_end = min(len(ranked_pool), max(req.item_count * 5, 40))
            band = ranked_pool[:band_end]
            self._shuffle(band, rng)
            pool = band + ranked_pool[band_end:]

        elif mode == PracticeMode.TIMED_SPRINT:
            # Letter-answerable is the data-truth definition of an auto-checkable item.
            pool = [m for m in pool if m.answer_status == "letter_only"]
            if modules:
                pool = [m for m in pool if m.module in modules]

        elif mode == PracticeMode.DAILY_PRACTICE:
            if modules:
                pool = [m for m in pool if m.module in modules]

        if mode not in (PracticeMode.HIGH_FREQUENCY, PracticeMode.ERROR_ELIMINATION):
            pool = self._stable_sample(pool, req, seed_extra=mode.value)
        return pool[: req.item_count], notices, seed_text

    def _select_mock(
        self,
        req: AssemblePaperRequest,
        usable_pool: Sequence[QuestionMeta],
        modules: Optional[Tuple[str, ...]],
    ) -> Tuple[List[QuestionMeta], Optional[dict], List[str], List[dict], str]:
        """Follow an official blueprint: real question ids when pinned, section counts otherwise."""
        notices: List[str] = []
        rng, seed_text = self._seeded(req, "mock")
        specs = self.repository.paper_specs(req.exam_type)
        if not specs:
            notices.append("库内没有该考试的考务规格（paper_specs），已退回按题型均衡抽题。")
            return (
                self._avoid(self._stable_sample(list(usable_pool), req, seed_extra="mock"), req, notices),
                None,
                notices,
                [],
                seed_text,
            )

        spec, spec_notice = self._pick_spec(req, specs)
        if spec_notice:
            notices.append(spec_notice)

        by_id = {m.question_id: m for m in usable_pool}
        scoped = self._scope_to_spec(spec, usable_pool)
        sections = spec.get("sections") or spec.get("parts") or []
        structure: List[dict] = []
        chosen: List[QuestionMeta] = []
        taken = set()
        avoided = set(req.avoid_question_ids)
        unpinned_avoided = 0

        for part in sections:
            name = part.get("name") or ""
            qtype = part.get("question_type") or ""
            entry = {
                "name": name,
                "module": part.get("module"),
                "question_type": qtype or None,
                "duration_minutes": part.get("duration_minutes"),
                "score": part.get("score") or part.get("total_score"),
                "score_ratio": part.get("score_ratio"),
                "lock_policy": part.get("lock_policy"),
            }
            pinned = part.get("question_ids")
            want = int(part.get("count") or part.get("question_count") or len(pinned or []))
            entry["planned_count"] = want

            if pinned:
                got = [by_id[qid] for qid in pinned if qid in by_id]
                dropped = len(pinned) - len(got)
                if dropped:
                    notices.append(
                        f"「{name}」有 {dropped} 题不在可用池（隔离、缺答案或未入库），本节实发 {len(got)} 题。"
                    )
                chosen.extend(got)
                entry["issued_count"] = len(got)
            else:
                candidates = [
                    m
                    for m in scoped
                    if m.question_id not in taken
                    and (m.section == name or (qtype and m.question_type == qtype))
                ]
                if avoided:
                    before = len(candidates)
                    candidates = [m for m in candidates if m.question_id not in avoided]
                    unpinned_avoided += before - len(candidates)
                # 卷面只钉了结构与题量，没钉题号：这些题号由本轮种子洗出来，换一批就换一批题。
                self._shuffle(candidates, rng)
                picked = candidates[:want]
                chosen.extend(picked)
                taken.update(m.question_id for m in picked)
                entry["issued_count"] = len(picked)
                if len(picked) < want:
                    notices.append(
                        f"规格 {spec.get('spec_id')} 的「{name or qtype}」需要 {want} 题，"
                        f"同题型可用仅 {len(candidates)} 题，已如实缩短本节。"
                    )
            structure.append(entry)

        if req.avoid_question_ids:
            pinned_count = sum(len(part.get("question_ids") or []) for part in sections)
            if pinned_count and not unpinned_avoided:
                notices.append(
                    f"这份规格的 {pinned_count} 题由官方卷面钉死题号，换一批不影响它们；只有未钉题号的小节会轮换。"
                )
        return chosen, spec, notices, structure, seed_text

    @staticmethod
    def _pick_spec(req: AssemblePaperRequest, specs: Sequence[dict]) -> Tuple[dict, str]:
        if req.spec_id:
            hit = next((s for s in specs if s.get("spec_id") == req.spec_id), None)
            if hit is not None:
                return hit, ""
            notice = f"spec_id={req.spec_id} 不在库内规格中，已按其余条件选择。"
        else:
            notice = ""

        cands = list(specs)
        if req.school_level:
            cands = [s for s in cands if s.get("school_level") == req.school_level]
        if req.subject:
            cands = [s for s in cands if s.get("subject") == req.subject]
        if cands and cands[0].get("paper_id"):
            # CET: newest real paper first, so the default mock is the closest to today's 考务.
            cands.sort(key=lambda s: (str(s.get("year") or ""), str(s.get("paper") or "")), reverse=True)
        if not cands:
            return {}, "所选学段科目没有匹配卷面规格，未退回其它学段科目。"
        chosen = cands[0]
        if not notice:
            notice = (
                f"未指定 spec_id，已按〈{chosen.get('title') or chosen.get('spec_id')}〉组卷；"
                "如需其它学段/科目请传 spec_id。"
            )
        return chosen, notice

    @staticmethod
    def _scope_to_spec(spec: dict, pool: Sequence[QuestionMeta]) -> List[QuestionMeta]:
        school_level = spec.get("school_level")
        subject = spec.get("subject")
        scoped = list(pool)
        if school_level:
            scoped = [m for m in scoped if m.school_level == school_level]
        if subject:
            scoped = [m for m in scoped if m.subject == subject]
        return scoped

    @staticmethod
    def _seeded(req: AssemblePaperRequest, seed_extra: str) -> Tuple[random.Random, str]:
        """Deterministic per (user, day, 模式/规格档, 轮次)：同一轮可复现，下一轮必然换一批。"""
        seed_text = f"{req.user_id}|{date.today().isoformat()}|{seed_extra}|{req.rotation}"
        digest = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:12], 16)
        return random.Random(digest), seed_text

    @staticmethod
    def _shuffle(rows: List[QuestionMeta], rng: random.Random) -> None:
        """先按题号排定基准顺序再洗牌，同一个种子才能拿到同一批顺序。"""
        rows.sort(key=lambda m: m.question_id)
        rng.shuffle(rows)

    @staticmethod
    def _avoid(pool: List[QuestionMeta], req: AssemblePaperRequest, notices: List[str]) -> List[QuestionMeta]:
        """「换一批」只按题号避让：上一批做过的题不再出现；题量不够就如实少发，不重发旧题凑数。"""
        if not req.avoid_question_ids or not pool:
            return pool
        blocked = set(req.avoid_question_ids)
        kept = [m for m in pool if m.question_id not in blocked]
        dropped = len(pool) - len(kept)
        if dropped:
            notices.append(f"换一批：已避开上一批的 {dropped} 题。")
        if not kept:
            notices.append(
                f"当前范围可用题共 {len(pool)} 题，上一批已全部出过，本轮换不出新题："
                "请扩大考点或科目范围，或改做错题回炉。宁可出空卷说明原因，也不重发旧题冒充新批。"
            )
        elif len(kept) < req.item_count:
            notices.append(
                f"避开上一批后同范围只剩 {len(kept)} 题，不足要求的 {req.item_count} 题："
                "本轮如实少发，不重发旧题凑数。"
            )
        return kept

    def _stable_sample(
        self, pool: Sequence[QuestionMeta], req: AssemblePaperRequest, seed_extra: str
    ) -> List[QuestionMeta]:
        """Deterministic per (user, day, mode) so a paper can be reproduced."""
        if not pool:
            return []
        rng, _ = self._seeded(req, seed_extra)
        ordered = list(pool)
        self._shuffle(ordered, rng)
        return ordered

    # -------------------------------------------------------- materialise
    def _materialise(
        self, metas: Sequence[QuestionMeta], gate: TrustGate, tier: TrustTier
    ) -> Tuple[List[dict], List]:
        questions: List[dict] = []
        verdicts = []
        for meta in metas:
            record = self.repository.load_question(meta.question_id)
            if record is None:
                continue
            verdict = gate.classify_record(record)
            if not verdict.servable_in_paper:
                continue
            content = record.get("content") or {}
            stem = content.get("stem") or record.get("text") or ""
            # 库内说不出时就是 None：单题用时不许由服务补一个估计值进题面，估计只进卷级限时并附说明。
            item_limit = item_time_limit(record)
            payload = {
                "question_id": meta.question_id,
                "exam": record.get("exam"),
                "module": record.get("module"),
                "section": record.get("section"),
                "question_type": record.get("question_type"),
                "stem": stem,
                "options": content.get("options") or [],
                "material_id": record.get("material_id"),
                "time_limit_minutes": item_limit,
                "node_ids": list(meta.node_ids),
                "requirement_ids": list(meta.requirement_ids),
                "difficulty": {
                    "value": meta.difficulty,
                    "method": meta.difficulty_method,
                    "calibration": "heuristic",
                    "label": "教研初估",
                },
                "review_status": verdict.review_status,
                "answer_status": verdict.answer_status,
                "answer_available": verdict.may_assert_answer,
                "analysis_available": bool(content.get("analysis") or record.get("analysis")),
                "source": record.get("source") or {},
            }
            # Answers only travel in the research tier; the published tier is
            # fail-closed on unsigned content anyway.
            if tier == TrustTier.RESEARCH_INTERNAL and verdict.may_assert_answer:
                payload["answer"] = content.get("answer")
            questions.append(payload)
            verdicts.append(verdict)
        return questions, verdicts

    @staticmethod
    def _timing_notices(
        req: AssemblePaperRequest,
        spec: Optional[dict],
        stages: List[dict],
        questions: Sequence[dict],
        breakdown: dict,
    ) -> List[str]:
        """Say where every minute on the paper came from, and refuse to pretend when the library has none."""
        if req.practice_mode != PracticeMode.MOCK_EXAM:
            if breakdown["total"] is None:
                return []
            # 只这一条：它已经把「多少来自库内题面约束、多少是服务估的」拆开说清了。
            return [pacing_notice(breakdown)]

        scheduled = mock_minutes(spec) or 0
        conflicting = PracticeEngineAgent._constraint_conflicts(stages, questions)
        if conflicting:
            notices = [
                "库内两处卷面用时对不上：" + "；".join(conflicting) + "。"
                "整卷限时仍按逐节用时（那份数字决定何时收卡），题面约束只报不改——"
                "两处需教研核定后统一，系统不自行改动官方卷面数据。"
            ]
        else:
            notices = []
        if not stages:
            return notices + [
                "库内考务规格没有给出逐节用时（parts[].duration_minutes），系统不内置模考时序："
                "只按卷面结构组卷，收卡与封锁时机需教研把规格补齐后才谈得上。"
            ]
        notices.append(
            f"模考时序按库内规格 {(spec or {}).get('spec_id')} 的 {len(stages)} 节推进，"
            f"合计 {scheduled} 分钟；服务不另立卷面。"
        )
        declared = (spec or {}).get("total_duration_minutes")
        if declared and int(declared) != scheduled:
            notices.append(
                f"库内该规格自相矛盾：逐节用时合计 {scheduled} 分钟，而 total_duration_minutes 写的是 "
                f"{int(declared)} 分钟。时序按逐节数字推进（那份数字决定何时收卡），"
                "两处需教研核定后统一——系统不自行改动官方卷面数据。"
            )
        return notices

    @staticmethod
    def _constraint_conflicts(stages: Sequence[dict], questions: Sequence[dict]) -> List[str]:
        """同一套卷面里，题面约束与所属小节的逐节用时不一致时只报不改。"""
        minutes_by_module = {stage.get("module"): stage["minutes"] for stage in stages}
        conflicts = []
        for item in questions:
            limit = item.get("time_limit_minutes")
            stage_minutes = minutes_by_module.get(item.get("module"))
            if limit and stage_minutes and int(limit) != int(stage_minutes):
                conflicts.append(
                    f"{item.get('question_id')} 题面要求 {limit} 分钟，"
                    f"而库内规格「{item.get('module')}」一节写的是 {stage_minutes} 分钟"
                )
        return conflicts

    @staticmethod
    def _time_limit(
        req: AssemblePaperRequest, spec: Optional[dict], breakdown: dict
    ) -> Optional[int]:
        if req.practice_mode == PracticeMode.MOCK_EXAM:
            # 模考先报卷面说得出的用时（读法在 repository.mock_minutes，与排课同源）：
            # 逐节与声明总时长都没有时，退回题面约束合计——库里说得出多少就限时多少，
            # 两处都说不出就不限时，服务编一个分钟数就是影子数据。
            scheduled = mock_minutes(spec)
            return scheduled or (breakdown["declared_minutes"] or None)
        # 非模考的一卷没有卷面规格，就逐题问题面约束；库里说不出用时的题按共用配速折算并说明。
        return breakdown["total"]

    @staticmethod
    def _token(req: AssemblePaperRequest) -> str:
        digest = hashlib.sha256(
            "|".join(
                [
                    req.user_id,
                    req.practice_mode.value,
                    req.target_node or "",
                    req.spec_id or "",
                    str(req.rotation),
                    date.today().isoformat(),
                ]
            ).encode("utf-8")
        ).hexdigest()
        return digest[:8]
