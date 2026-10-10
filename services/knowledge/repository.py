"""Byte-offset-backed indexes over the knowledge dataset.

The dataset is the only source of truth for agent-visible content: questions are
addressed by ``question_id`` and read lazily from their JSONL line, so no answer,
stem or difficulty is ever embedded in service code.

Two consequences of that design are enforced here:

* the index is a *cache* of the dataset, not a snapshot of process start — 教研 edits
  ``review.status`` and rubric signatures directly on disk, so the facade re-checks the
  tracked files and drops a stale index instead of serving an old verdict forever;
* a byte offset is only valid for the file version it was measured on, so a record is
  returned only when the bytes read back still belong to the requested ``question_id``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from services.knowledge.naming import exam_values, task_type_value
from services.knowledge.trust import SERVABLE_ANSWER_STATUSES

logger = logging.getLogger("services.knowledge.repository")

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

RUBRIC_DIR = "数据集/教资/rubrics"
CET_RUBRIC_FILE = "数据集/四六级/ontology/scoring_rubrics.jsonl"


def _default_ttl() -> float:
    """Seconds between two fingerprint checks; 0 means "check on every read".

    一次指纹要 stat 约 770 个文件（约 0.16s），所以默认 5s 复核一次：教研在盘上签署/reopen 之后，
    运行中的服务最迟 5s 就会换代重扫，而不是等到下次重启。用 ``KNOWLEDGE_MAP_INDEX_TTL`` 覆盖。
    """
    try:
        return max(float(os.environ.get("KNOWLEDGE_MAP_INDEX_TTL", "5.0")), 0.0)
    except ValueError:
        return 5.0


def _loads(raw: bytes) -> Optional[dict]:
    if not raw or not raw.strip():
        return None
    return json.loads(raw.decode("utf-8"))


def _loads_safe(raw: bytes) -> Tuple[Optional[dict], Optional[str]]:
    """Decode one JSONL line, reporting a malformed line instead of raising through a route."""
    try:
        return _loads(raw), None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, str(exc)


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

    def __init__(self, root: Optional[Path] = None, *, ttl_seconds: Optional[float] = None) -> None:
        self.root = Path(root) if root else REPO_ROOT
        self._lock = threading.RLock()
        self._questions: Optional[Dict[str, QuestionMeta]] = None
        self._requirements: Optional[Dict[str, dict]] = None
        self._rubrics: Optional[Dict[str, dict]] = None
        self._scan_errors: List[str] = []
        self._ttl = float(ttl_seconds) if ttl_seconds is not None else _default_ttl()
        self._stamp: Optional[Tuple[float, Tuple[Tuple[str, int, int], ...]]] = None
        #: 每次索引换代 +1：GraphIndex 等下游按它判断自己的缓存是否已经属于上一代数据。
        self.generation = 0

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

    # -------------------------------------------------------------- freshness
    def _tracked_files(self) -> List[Path]:
        """Every dataset file a cached index is derived from."""
        files = self.question_files()
        for rel in list(REQUIREMENT_FILES) + list(PAPER_SPEC_FILES) + [CET_RUBRIC_FILE]:
            files.append(self.path(rel))
        for nodes_rel, edges_rel in GRAPH_FILES.values():
            files.extend([self.path(nodes_rel), self.path(edges_rel)])
        rubric_dir = self.path(RUBRIC_DIR)
        if rubric_dir.is_dir():
            files.extend(sorted(rubric_dir.glob("*.json")))
        return files

    def _fingerprint(self) -> Tuple[Tuple[str, int, int], ...]:
        rows: List[Tuple[str, int, int]] = []
        for path in self._tracked_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            rows.append((path.relative_to(self.root).as_posix(), stat.st_mtime_ns, stat.st_size))
        return tuple(sorted(rows))

    def _check_fresh(self) -> None:
        """Drop cached indexes when the files they were built from changed on disk."""
        if self._stamp is not None and self._ttl > 0:
            if time.monotonic() - self._stamp[0] < self._ttl:
                return
        with self._lock:
            if self._stamp is not None and self._ttl > 0:
                if time.monotonic() - self._stamp[0] < self._ttl:
                    return
            stamp = self._fingerprint()
            if self._stamp is not None and stamp != self._stamp[1]:
                self._invalidate_locked()
            self._stamp = (time.monotonic(), stamp)

    def _invalidate_locked(self) -> None:
        self._questions = None
        self._requirements = None
        self._rubrics = None
        self._scan_errors = []
        self.generation += 1

    def invalidate(self) -> None:
        """Forget the cached indexes; the next read rebuilds them and offsets are remeasured."""
        with self._lock:
            self._invalidate_locked()
            self._stamp = None

    def _note_scan_error(self, message: str) -> None:
        if message not in self._scan_errors:
            self._scan_errors.append(message)

    # ------------------------------------------------------------ questions
    def questions(self) -> Dict[str, QuestionMeta]:
        self._check_fresh()
        if self._questions is None:
            with self._lock:
                if self._questions is None:
                    self._questions = self._build_question_index()
        return self._questions

    def _build_question_index(self) -> Dict[str, QuestionMeta]:
        index: Dict[str, QuestionMeta] = {}
        for path in self.question_files():
            rel = path.relative_to(self.root).as_posix()
            try:
                with open(path, "rb") as fh:
                    offset = 0
                    for line in fh:
                        length = len(line)
                        record, decode_error = _loads_safe(line)
                        if decode_error is not None:
                            # 一行坏了不能把这个文件剩下的题全部丢掉：登记缺口，继续索引后续行。
                            self._note_scan_error(f"{rel}: 偏移 {offset} 行不是合法 JSON（{decode_error}）")
                        elif record is not None:
                            meta = self._to_meta(record, rel, offset, length)
                            if meta is not None:
                                if meta.question_id in index:
                                    self._note_scan_error(f"duplicate question_id {meta.question_id}")
                                else:
                                    index[meta.question_id] = meta
                        offset += length
            except OSError as exc:
                self._note_scan_error(f"{rel}: {exc}")
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
        """Read the full record for a question id from its byte range.

        The offset was measured against one version of the file; a 教研 edit elsewhere in that file
        moves every later record. So the bytes are accepted only when they still decode to *this*
        question: 宁可报"读不到"，也绝不把别的题当成这道题送出去——判分拿到别人的答案键，比没有答案危险。
        """
        meta = self.get_meta(question_id)
        if meta is None:
            return None
        record = self._read_range(meta, question_id)
        if record is not None:
            return record
        # 偏移失效：换代重扫一遍再按新位置读一次，仍然对不上就返回 None 并登记缺口。
        logger.warning("question %s: index offset %s@%d no longer decodes to it, rebuilding index",
                       question_id, meta.file, meta.offset)
        self.invalidate()
        meta = self.get_meta(question_id)
        if meta is None:
            self._note_scan_error(f"{question_id}: 索引换代后该题已不在库内")
            return None
        record = self._read_range(meta, question_id)
        if record is None:
            self._note_scan_error(
                f"{meta.file}: 偏移 {meta.offset} 长度 {meta.length} 读不回 {question_id}")
            logger.error("question %s: byte range still does not decode to it after a rebuild", question_id)
        return record

    def _read_range(self, meta: QuestionMeta, question_id: str) -> Optional[dict]:
        try:
            with open(self.path(meta.file), "rb") as fh:
                fh.seek(meta.offset)
                raw = fh.read(meta.length)
        except OSError:
            return None
        record, decode_error = _loads_safe(raw)
        if decode_error is not None:
            return None
        if record is None or record.get("question_id") != question_id:
            return None
        return record

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
        self._check_fresh()
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
                offset = 0
                for line in fh:
                    record, decode_error = _loads_safe(line)
                    if decode_error is not None:
                        self._note_scan_error(f"{rel}: 偏移 {offset} 行不是合法 JSON（{decode_error}）")
                    elif record is not None:
                        rid = record.get("requirement_id")
                        if rid and rid not in index:
                            index[rid] = record
                    offset += len(line)
            # The first existing file wins; later aliases add nothing new.
            break
        return index

    def get_requirement(self, requirement_id: str) -> Optional[dict]:
        return self.requirements().get(requirement_id)

    # --------------------------------------------------------------- graph
    def graph_records(self, library: str) -> Tuple[List[dict], List[dict]]:
        self._check_fresh()
        nodes_rel, edges_rel = GRAPH_FILES[library]
        return self._read_jsonl(nodes_rel), self._read_jsonl(edges_rel)

    def _read_jsonl(self, rel: str) -> List[dict]:
        path = self.path(rel)
        if not path.is_file():
            return []
        out: List[dict] = []
        with open(path, "rb") as fh:
            offset = 0
            for line in fh:
                record, decode_error = _loads_safe(line)
                if decode_error is not None:
                    self._note_scan_error(f"{rel}: 偏移 {offset} 行不是合法 JSON（{decode_error}）")
                elif record is not None:
                    out.append(record)
                offset += len(line)
        return out

    # --------------------------------------------------------------- rubrics
    def rubrics(self) -> Dict[str, dict]:
        """A.6 weighted rubrics (NTCE json) and CET holistic band rubrics, by rubric_id.

        The grader must not open these files itself: rubric provenance and signature state is a
        knowledge-facade concern, and a second reader would be a second source of truth.
        """
        self._check_fresh()
        if self._rubrics is None:
            with self._lock:
                if self._rubrics is None:
                    self._rubrics = self._build_rubric_index()
        return self._rubrics

    def _build_rubric_index(self) -> Dict[str, dict]:
        index: Dict[str, dict] = {}
        ntce_dir = self.path(RUBRIC_DIR)
        for path in sorted(ntce_dir.glob("*.json")) if ntce_dir.is_dir() else []:
            rel = path.relative_to(self.root).as_posix()
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._note_scan_error(f"{rel}: 量规文件读不出（{exc}）")
                continue
            if isinstance(record, dict) and record.get("rubric_id"):
                record.setdefault("library", "ntce")
                record.setdefault("rubric_source", rel)
                index[record["rubric_id"]] = record
        for record in self._read_jsonl(CET_RUBRIC_FILE):
            if record.get("rubric_id"):
                record.setdefault("library", "cet")
                record.setdefault("rubric_source", CET_RUBRIC_FILE)
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
        self._check_fresh()
        specs: List[dict] = []
        for rel in PAPER_SPEC_FILES:
            specs.extend(self._read_jsonl(rel))
        if exam:
            values = set(exam_values(exam))
            specs = [s for s in specs if s.get("exam") in values]
        return specs

    # --------------------------------------------------------------- stats
    def stats(self) -> dict:
        self._check_fresh()
        q = self.questions()
        return {
            "question_records": len(q),
            "requirement_records": len(self.requirements()),
            "question_files": len(self.question_files()),
            "paper_specs": len(self.paper_specs()),
            "scan_issues": len(self._scan_errors),
            "index_generation": self.generation,
            "index_ttl_seconds": self._ttl,
            "root": self.root.as_posix(),
        }


@lru_cache(maxsize=1)
def get_repository() -> KnowledgeRepository:
    """Process-wide singleton: index build costs ~1.2s over 750 JSONL files."""
    return KnowledgeRepository()
