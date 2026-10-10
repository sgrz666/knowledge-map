"""Byte-offset-backed indexes over the knowledge dataset.

The dataset is the only source of truth for agent-visible content: questions are
addressed by ``question_id`` and read lazily from their JSONL line, so no answer,
stem or difficulty is ever embedded in service code.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from services.knowledge.naming import exam_values, task_type_value
from services.knowledge.trust import SERVABLE_ANSWER_STATUSES

REPO_ROOT = Path(__file__).resolve().parents[2]

QUESTION_DIRS: Tuple[str, ...] = (
    "数据集/教资/questions",
    "数据集/四六级/questions",
)

REQUIREMENT_FILES: Tuple[str, ...] = (
    "官方权威资料/requirements.jsonl",
    "权威资料/requirements.jsonl",
)

GRAPH_FILES: Dict[str, Tuple[str, str]] = {
    "ntce": ("数据集/教资/graph/nodes.jsonl", "数据集/教资/graph/edges.jsonl"),
    "cet": ("数据集/四六级/graph/nodes.jsonl", "数据集/四六级/graph/edges.jsonl"),
}

# Official paper blueprints: section order, per-section counts and minute budgets.
PAPER_SPEC_FILES: Tuple[str, ...] = (
    "数据集/教资/paper_specs.jsonl",
    "数据集/四六级/manifest/paper_specs.jsonl",
)


def _loads(raw: bytes) -> Optional[dict]:
    if not raw or not raw.strip():
        return None
    return json.loads(raw.decode("utf-8"))


#: 套名/来源行形如「【2019年12月CET-6真题第1套·阅读·选词填空】」，题号只剩数字。
#: 去掉这两样之后还剩文字，或者带选项可勾，才算learner 真能作答的题面。
_PAPER_HEADER = re.compile(r"^【[^】]*】")


def has_answerable_text(stem: Optional[str], options: Optional[Iterable]) -> bool:
    if list(options or ()):
        return True
    core = _PAPER_HEADER.sub("", stem or "").strip(" 　、,，.。0123456789")
    return bool(core)


def _as_set(value: Optional[Iterable[str]], *, exam: bool = False) -> Optional[frozenset]:
    """Normalize a predicate without letting a bare string explode into single characters.

    ``exams="NTCE"`` would otherwise become ``{"N","T","C","E"}`` and silently return an empty
    pool, which every downstream agent reports as "库里没有可用题目".
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = (value,)
    if exam:
        expanded: List[str] = []
        for item in value:
            expanded.extend(exam_values(item) or (item,))
        return frozenset(expanded)
    return frozenset(value)


@dataclass(frozen=True)
class QuestionMeta:
    """Cheap, index-only projection of a question record."""

    question_id: str
    exam: str
    module: Optional[str]
    section: Optional[str]
    question_type: Optional[str]
    subject: Optional[str]
    school_level: Optional[str]
    node_ids: Tuple[str, ...]
    requirement_ids: Tuple[str, ...]
    review_status: Optional[str]
    answer_status: Optional[str]
    difficulty: Optional[float]
    difficulty_method: Optional[str]
    file: str
    offset: int
    length: int
    #: 抽取完整性而不是可信度：只剩「【2019年12月CET-6真题第1套·阅读·选词填空】35.」这种套名题号、
    #: 又没有选项可答的题，在索引阶段就标出来，组卷池子才不会把空题面算成可用题量。
    has_answerable_text: bool = True


class KnowledgeRepository:
    """Read-only facade over questions, authoritative requirements and the graph."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else REPO_ROOT
        self._lock = threading.Lock()
        self._questions: Optional[Dict[str, QuestionMeta]] = None
        self._requirements: Optional[Dict[str, dict]] = None
        self._rubrics: Optional[Dict[str, dict]] = None
        self._scan_errors: List[str] = []

    # ---------------------------------------------------------------- paths
    def path(self, rel: str) -> Path:
        return self.root / rel

    def question_files(self) -> List[Path]:
        files: List[Path] = []
        for rel in QUESTION_DIRS:
            base = self.path(rel)
            if base.is_dir():
                files.extend(sorted(base.rglob("*.jsonl")))
        return files

    # ------------------------------------------------------------ questions
    def questions(self) -> Dict[str, QuestionMeta]:
        if self._questions is None:
            with self._lock:
                if self._questions is None:
                    self._questions = self._build_question_index()
        return self._questions

    def _build_question_index(self) -> Dict[str, QuestionMeta]:
        index: Dict[str, QuestionMeta] = {}
        self._scan_errors = []
        for path in self.question_files():
            rel = path.relative_to(self.root).as_posix()
            try:
                with open(path, "rb") as fh:
                    offset = 0
                    for line in fh:
                        length = len(line)
                        record = _loads(line)
                        if record is not None:
                            meta = self._to_meta(record, rel, offset, length)
                            if meta is not None:
                                if meta.question_id in index:
                                    self._scan_errors.append(f"duplicate question_id {meta.question_id}")
                                else:
                                    index[meta.question_id] = meta
                        offset += length
            except OSError as exc:
                self._scan_errors.append(f"{rel}: {exc}")
        return index

    @staticmethod
    def _to_meta(record: dict, rel: str, offset: int, length: int) -> Optional[QuestionMeta]:
        qid = record.get("question_id")
        if not qid:
            return None
        content = record.get("content") or {}
        review = record.get("review") or {}
        difficulty = record.get("difficulty")
        difficulty_method = None
        if isinstance(difficulty, dict):
            difficulty_method = difficulty.get("method")
            difficulty = difficulty.get("value")
        else:
            difficulty_method = (record.get("difficulty_meta") or {}).get("method")
        return QuestionMeta(
            question_id=qid,
            exam=record.get("exam") or "",
            module=record.get("module"),
            section=record.get("section"),
            question_type=record.get("question_type"),
            subject=record.get("subject"),
            school_level=record.get("school_level"),
            node_ids=tuple(record.get("knowledge_node_ids") or ()),
            requirement_ids=tuple(record.get("exam_requirement_ids") or ()),
            review_status=review.get("status"),
            answer_status=content.get("answer_status"),
            difficulty=difficulty,
            difficulty_method=difficulty_method,
            file=rel,
            offset=offset,
            length=length,
            has_answerable_text=has_answerable_text(
                content.get("stem") or record.get("text"), content.get("options")
            ),
        )

    def get_meta(self, question_id: str) -> Optional[QuestionMeta]:
        return self.questions().get(question_id)

    def load_question(self, question_id: str) -> Optional[dict]:
        """Read the full record for a question id from its byte range."""
        meta = self.get_meta(question_id)
        if meta is None:
            return None
        with open(self.path(meta.file), "rb") as fh:
            fh.seek(meta.offset)
            return _loads(fh.read(meta.length))

    def find_questions(
        self,
        *,
        exams: Optional[Iterable[str]] = None,
        modules: Optional[Iterable[str]] = None,
        sections: Optional[Iterable[str]] = None,
        question_types: Optional[Iterable[str]] = None,
        node_ids: Optional[Iterable[str]] = None,
        review_statuses: Optional[Iterable[str]] = None,
        answer_statuses: Optional[Iterable[str]] = None,
        require_nodes: bool = False,
        require_answer: bool = False,
        require_answerable_text: bool = False,
        exclude: Optional[Iterable[str]] = None,
    ) -> Iterator[QuestionMeta]:
        """Stream index entries matching every provided predicate."""
        exams_t = _as_set(exams, exam=True)
        modules_t = _as_set(modules)
        sections_t = _as_set(sections)
        qtypes_t = _as_set(question_types)
        nodes_t = _as_set(node_ids)
        review_t = _as_set(review_statuses)
        answer_t = _as_set(answer_statuses)
        skip = frozenset(exclude or ())

        for meta in self.questions().values():
            if meta.question_id in skip:
                continue
            if exams_t is not None and meta.exam not in exams_t:
                continue
            if modules_t is not None and meta.module not in modules_t:
                continue
            if sections_t is not None and meta.section not in sections_t:
                continue
            if qtypes_t is not None and meta.question_type not in qtypes_t:
                continue
            if nodes_t is not None and not (nodes_t & set(meta.node_ids)):
                continue
            if review_t is not None and meta.review_status not in review_t:
                continue
            if answer_t is not None and meta.answer_status not in answer_t:
                continue
            if require_nodes and not meta.node_ids:
                continue
            # A3 只有一份词表：组卷/判分可用 = TrustGate 认可的答案状态，不在这里另写一套。
            if require_answer and meta.answer_status not in SERVABLE_ANSWER_STATUSES:
                continue
            if require_answerable_text and not meta.has_answerable_text:
                continue
            yield meta

    # --------------------------------------------------------- requirements
    def requirements(self) -> Dict[str, dict]:
        if self._requirements is None:
            with self._lock:
                if self._requirements is None:
                    self._requirements = self._build_requirement_index()
        return self._requirements

    def _build_requirement_index(self) -> Dict[str, dict]:
        index: Dict[str, dict] = {}
        for rel in REQUIREMENT_FILES:
            path = self.path(rel)
            if not path.is_file():
                continue
            with open(path, "rb") as fh:
                for line in fh:
                    record = _loads(line)
                    if record is None:
                        continue
                    rid = record.get("requirement_id")
                    if rid and rid not in index:
                        index[rid] = record
            # The first existing file wins; later aliases add nothing new.
            break
        return index

    def get_requirement(self, requirement_id: str) -> Optional[dict]:
        return self.requirements().get(requirement_id)

    # --------------------------------------------------------------- graph
    def graph_records(self, library: str) -> Tuple[List[dict], List[dict]]:
        nodes_rel, edges_rel = GRAPH_FILES[library]
        return self._read_jsonl(nodes_rel), self._read_jsonl(edges_rel)

    def _read_jsonl(self, rel: str) -> List[dict]:
        path = self.path(rel)
        if not path.is_file():
            return []
        out: List[dict] = []
        with open(path, "rb") as fh:
            for line in fh:
                record = _loads(line)
                if record is not None:
                    out.append(record)
        return out

    # --------------------------------------------------------------- rubrics
    def rubrics(self) -> Dict[str, dict]:
        """A.6 weighted rubrics (NTCE json) and CET holistic band rubrics, by rubric_id.

        The grader must not open these files itself: rubric provenance and signature state is a
        knowledge-facade concern, and a second reader would be a second source of truth.
        """
        if self._rubrics is None:
            with self._lock:
                if self._rubrics is None:
                    self._rubrics = self._build_rubric_index()
        return self._rubrics

    def _build_rubric_index(self) -> Dict[str, dict]:
        index: Dict[str, dict] = {}
        ntce_dir = self.path("数据集/教资/rubrics")
        for path in sorted(ntce_dir.glob("*.json")) if ntce_dir.is_dir() else []:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(record, dict) and record.get("rubric_id"):
                record.setdefault("library", "ntce")
                record.setdefault("rubric_source", path.relative_to(self.root).as_posix())
                index[record["rubric_id"]] = record
        cet_rel = "数据集/四六级/ontology/scoring_rubrics.jsonl"
        for record in self._read_jsonl(cet_rel):
            if record.get("rubric_id"):
                record.setdefault("library", "cet")
                record.setdefault("rubric_source", cet_rel)
                index[record["rubric_id"]] = record
        return index

    def find_rubric(self, *, rubric_id: Optional[str] = None, task_type: Optional[str] = None, exam: Optional[str] = None) -> Optional[dict]:
        rubrics = self.rubrics()
        if rubric_id:
            return rubrics.get(rubric_id)
        wanted = task_type_value(task_type)
        values = set(exam_values(exam)) if exam else set()
        for record in rubrics.values():
            if wanted and record.get("task_type") not in (wanted, None):
                continue
            exams = record.get("exams") or []
            if values and exams and not (values & set(exams)):
                continue
            if record.get("dimensions") or record.get("bands"):
                return record
        return None

    # --------------------------------------------------------------- paper specs
    def paper_specs(self, exam: Optional[str] = None) -> List[dict]:
        """Official blueprints (section order, counts, minute budgets) for both libraries."""
        specs: List[dict] = []
        for rel in PAPER_SPEC_FILES:
            specs.extend(self._read_jsonl(rel))
        if exam:
            values = set(exam_values(exam))
            specs = [s for s in specs if s.get("exam") in values]
        return specs

    # --------------------------------------------------------------- stats
    def stats(self) -> dict:
        q = self.questions()
        return {
            "question_records": len(q),
            "requirement_records": len(self.requirements()),
            "question_files": len(self.question_files()),
            "paper_specs": len(self.paper_specs()),
            "scan_issues": len(self._scan_errors),
            "root": self.root.as_posix(),
        }


@lru_cache(maxsize=1)
def get_repository() -> KnowledgeRepository:
    """Process-wide singleton: index build costs ~1.2s over 750 JSONL files."""
    return KnowledgeRepository()
