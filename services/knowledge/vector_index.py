"""Chroma-backed card index with an offline fallback, so retrieval never needs a model download.

Cards under ``数据集/**/cards`` are self-contained (stem, options, answer slot, structured
analysis, provenance footer), which makes them the right RAG document body. Every indexed
document carries ``review_status`` / ``answer_status`` in its metadata: the design document
§3.1 and §5 require filtering *after* recall but *before* generation, and the metadata is what
lets the retrieval layer refuse quarantined cards instead of letting them leak through a
similarity hit.

The default embedder is a deterministic signed-hashing bag of character n-grams. That is an
honest lexical embedder — results are labelled ``embedder=hash-ngram-384`` and the mode is
reported — not a semantic model. Swapping in a real model only means supplying a different
callable; nothing else in the runtime changes. If ``chromadb`` is absent the same documents are
served by a BM25 fallback with an identical query API, so the runtime degrades explicitly
instead of failing.

Indexes are rebuildable artifacts and are never committed (``chroma/`` is gitignored).
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from services.knowledge.repository import REPO_ROOT, KnowledgeRepository, get_repository

CARD_DIRS: Dict[str, str] = {
    "ntce": "数据集/教资/cards",
    "cet": "数据集/四六级/cards",
}
COLLECTION_NAMES: Dict[str, str] = {"ntce": "ntce_cards", "cet": "cet_cards"}

EMBEDDING_DIM = 384
EMBEDDER_NAME = f"hash-ngram-{EMBEDDING_DIM}"
CHROMA_DIRNAME = "chroma"
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.S)
_LIST_RE = re.compile(r"^\[(.*)\]$")

LEXICAL_NOTICE = "向量后端不可用（chromadb 未安装），本次检索使用 BM25 词法回退模式，语义召回能力受限。"


def _default_card_ttl() -> float:
    """卡片目录指纹的复核窗口（秒）。

    复核一次要 stat 全部卡片文件（万级，约半秒），所以窗口比知识门面放宽到 60s：教研改卡之后最迟
    一分钟，检索命中的就是新正文，而不是"等下次重启"。用 ``KNOWLEDGE_MAP_CARD_TTL`` 覆盖。
    """
    try:
        return max(float(os.environ.get("KNOWLEDGE_MAP_CARD_TTL", "60.0")), 0.0)
    except ValueError:
        return 60.0


CARD_TTL_SECONDS = _default_card_ttl()


@dataclass
class CardDoc:
    question_id: str
    library: str
    path: str
    text: str
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    question_id: str
    library: str
    score: float
    path: str
    metadata: Dict[str, str]
    snippet: str

    def node_ids(self) -> List[str]:
        return _split(self.metadata.get("node_ids"))

    def requirement_ids(self) -> List[str]:
        return _split(self.metadata.get("requirement_ids"))


def _split(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part for part in value.split(",") if part]


def _content_digest(text: str, metadata: Dict[str, str]) -> str:
    """一张卡片"正文 + 状态"的指纹。

    只比条数的重建等于没重建：教研改一张卡的正文或把 ``review_status`` 签成 ``checked``，条数不变，
    旧实现会把旧文本永久留在集合里。指纹进 metadata 一起存，重建时才分得出"哪几张真的变了"。
    """
    payload = (text + "\n" + "\n".join(f"{key}={metadata[key]}" for key in sorted(metadata))).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


def _doc_id(doc: CardDoc) -> str:
    return f"{doc.library}:{doc.question_id}"


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip().strip('"')
        list_match = _LIST_RE.match(raw)
        if list_match:
            raw = ",".join(part.strip().strip('"') for part in list_match.group(1).split(",") if part.strip())
        elif raw.lower() in ("null", "none", "~"):
            raw = ""
        fields[key] = raw
    return fields, text[match.end():]


def hash_ngram_embedding(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """Deterministic signed-hashing embedding over char n-grams and ascii tokens."""
    vector = [0.0] * dim
    normalised = re.sub(r"\s+", " ", text.lower())
    grams: Counter = Counter()
    for token in re.findall(r"[a-z0-9]+", normalised):
        grams[token] += 1
    chinese = re.findall(r"[\u4e00-\u9fff]", normalised)
    for i in range(len(chinese) - 1):
        grams["".join(chinese[i:i + 2])] += 1
    grams.update(chinese)
    for gram, count in grams.items():
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


Embedder = Callable[[Sequence[str]], List[List[float]]]


class ChromaStore:
    """Persistent Chroma collection per library, rebuilt from the cards on first use."""

    backend = "chroma"

    def __init__(self, root: Path, embedder: Optional[Embedder] = None) -> None:
        import chromadb  # noqa: PLC0415 - optional dependency, guarded by available()

        self._root = root
        self._embedder = embedder or (lambda texts: [hash_ngram_embedding(t) for t in texts])
        self._dir = root / CHROMA_DIRNAME
        self._dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._dir), settings=_chroma_settings())
        self._lock = threading.Lock()

    def _collection(self, library: str):
        return self._client.get_or_create_collection(
            name=COLLECTION_NAMES[library], metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, library: str, docs: List[CardDoc]) -> int:
        if not docs:
            return 0
        collection = self._collection(library)
        embeddings = self._embedder([d.text for d in docs])
        batch = 512
        for start in range(0, len(docs), batch):
            chunk = docs[start:start + batch]
            collection.upsert(
                ids=[_doc_id(d) for d in chunk],
                documents=[d.text for d in chunk],
                embeddings=embeddings[start:start + batch],
                metadatas=[d.metadata for d in chunk],
            )
        return len(docs)

    def known_digests(self, library: str) -> Dict[str, str]:
        """集合里已有文档的指纹：增量的依据是内容，不是条数。"""
        collection = self._collection(library)
        if collection.count() == 0:
            return {}
        rows = collection.get(include=["metadatas"])
        return {doc_id: str((meta or {}).get("card_digest", "")) for doc_id, meta in zip(rows["ids"], rows["metadatas"])}

    def prune(self, library: str, keep: set) -> int:
        """卡片被删/改名后从集合里移除：留着它，隔离题就能靠一次相似命中回到答案里。"""
        stale = [doc_id for doc_id in self.known_digests(library) if doc_id not in keep]
        if stale:
            self._collection(library).delete(ids=stale)
        return len(stale)

    def count(self, library: str) -> int:
        return self._collection(library).count()

    def search(self, library: str, query: str, k: int, filters: Dict[str, set]) -> List[SearchHit]:
        collection = self._collection(library)
        if collection.count() == 0:
            return []
        conditions = [{key: {"$in": sorted(allowed)}} for key, allowed in filters.items() if allowed]
        where: Optional[dict] = None
        if len(conditions) == 1:
            where = conditions[0]
        elif conditions:
            # Chroma accepts exactly one top-level operator, so combine under $and.
            where = {"$and": conditions}
        result = collection.query(
            query_embeddings=[self._embedder([query])[0]],
            n_results=min(k, collection.count()),
            where=where or None,
            include=["metadatas", "documents", "distances"],
        )
        hits: List[SearchHit] = []
        for qid, meta, doc, distance in zip(
            result["ids"][0], result["metadatas"][0], result["documents"][0], result["distances"][0]
        ):
            metadata = {key: ("" if value is None else str(value)) for key, value in (meta or {}).items()}
            hits.append(
                SearchHit(
                    question_id=metadata.get("question_id", qid.split(":", 1)[-1]),
                    library=library,
                    score=round(1.0 - float(distance), 6),
                    path=metadata.get("path", ""),
                    metadata=metadata,
                    snippet=_snippet(doc),
                )
            )
        return hits


def _chroma_settings():
    import chromadb  # noqa: PLC0415

    # No anonymised telemetry, and no attempt to fetch a default embedding model: every call
    # passes explicit embeddings.
    return chromadb.Settings(allow_reset=True, anonymized_telemetry=False)


class LexicalStore:
    """BM25 fallback used when chromadb is unavailable; same documents, same query API."""

    backend = "bm25_fallback"

    def __init__(self) -> None:
        # 倒排表按库分开放：两库共用一张 posting 表时，重建第二库会把第一库的下标解释成自己的文档。
        self._by_id: Dict[str, Dict[str, CardDoc]] = defaultdict(dict)
        self._docs: Dict[str, List[CardDoc]] = defaultdict(list)
        self._postings: Dict[str, Dict[str, Dict[int, int]]] = defaultdict(dict)
        self._lengths: Dict[str, List[int]] = defaultdict(list)
        self._embedder: Optional[Embedder] = None

    @staticmethod
    def _tokens(text: str) -> List[str]:
        lowered = text.lower()
        return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{1,2}", lowered)

    def _reindex(self, library: str) -> None:
        docs = list(self._by_id[library].values())
        self._docs[library] = docs
        postings: Dict[str, Dict[int, int]] = {}
        lengths: List[int] = []
        for position, doc in enumerate(docs):
            counts = Counter(self._tokens(doc.text))
            lengths.append(sum(counts.values()))
            for term, count in counts.items():
                postings.setdefault(term, {})[position] = count
        self._postings[library] = postings
        self._lengths[library] = lengths

    def upsert(self, library: str, docs: List[CardDoc]) -> int:
        """按文档 id 合并，和 Chroma 的 upsert 同语义：增量重建不能把其余卡片清掉。"""
        bucket = self._by_id[library]
        for doc in docs:
            bucket[_doc_id(doc)] = doc
        self._reindex(library)
        return len(docs)

    def known_digests(self, library: str) -> Dict[str, str]:
        return {doc_id: doc.metadata.get("card_digest", "") for doc_id, doc in self._by_id[library].items()}

    def prune(self, library: str, keep: set) -> int:
        bucket = self._by_id[library]
        stale = [doc_id for doc_id in bucket if doc_id not in keep]
        for doc_id in stale:
            del bucket[doc_id]
        if stale:
            self._reindex(library)
        return len(stale)

    def count(self, library: str) -> int:
        return len(self._by_id.get(library, {}))

    def search(self, library: str, query: str, k: int, filters: Dict[str, set]) -> List[SearchHit]:
        docs = self._docs.get(library, [])
        if not docs:
            return []
        lengths = self._lengths[library]
        postings_all = self._postings.get(library, {})
        average = max(sum(lengths) / max(len(lengths), 1), 1.0)
        total = len(docs)
        scores: Dict[int, float] = defaultdict(float)
        k1, b = 1.5, 0.75
        for term in set(self._tokens(query)):
            postings = postings_all.get(term)
            if not postings:
                continue
            idf = math.log(1.0 + (total - len(postings) + 0.5) / (len(postings) + 0.5))
            for position, count in postings.items():
                if position >= total:
                    continue
                denominator = count + k1 * (1.0 - b + b * lengths[position] / average)
                scores[position] += idf * count * (k1 + 1.0) / denominator
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: max(k * 4, k)]
        hits: List[SearchHit] = []
        for position, score in ranked:
            doc = docs[position]
            if not _matches(doc.metadata, filters):
                continue
            hits.append(
                SearchHit(
                    question_id=doc.question_id,
                    library=library,
                    score=round(score, 6),
                    path=doc.path,
                    metadata=doc.metadata,
                    snippet=_snippet(doc.text),
                )
            )
            if len(hits) >= k:
                break
        return hits


def _matches(metadata: Dict[str, str], filters: Dict[str, set]) -> bool:
    for key, allowed in filters.items():
        if not allowed:
            continue
        if metadata.get(key, "") not in allowed:
            return False
    return True


def _snippet(text: str, limit: int = 220) -> str:
    body = re.sub(r"\s+", " ", text).strip()
    return body[:limit]


def available_backend() -> str:
    try:
        import chromadb  # noqa: F401, PLC0415
    except Exception:
        return "bm25_fallback"
    return "chroma"


class CardIndex:
    """Builds and queries the per-library card collections."""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        root: Optional[Path] = None,
        embedder: Optional[Embedder] = None,
        store=None,
        card_ttl_seconds: Optional[float] = None,
    ) -> None:
        self.repository = repository or get_repository()
        self.root = Path(root) if root else REPO_ROOT
        self._embedder = embedder
        self._lock = threading.Lock()
        self._built: set = set()
        self._store = store
        self.backend = getattr(store, "backend", None) or available_backend()
        self._card_ttl = CARD_TTL_SECONDS if card_ttl_seconds is None else float(card_ttl_seconds)
        self._card_stamp: Dict[str, Tuple[float, Tuple[Tuple[str, int, int], ...]]] = {}

    # ------------------------------------------------------------------ docs
    def card_files(self, library: str) -> List[Path]:
        base = self.root / CARD_DIRS[library]
        if not base.is_dir():
            return []
        return [path for path in sorted(base.rglob("*.md")) if path.name != "README.md"]

    def _card_stamp_of(self, library: str) -> Tuple[Tuple[str, int, int], ...]:
        rows: List[Tuple[str, int, int]] = []
        for path in self.card_files(library):
            try:
                stat = path.stat()
            except OSError:
                continue
            rows.append((path.relative_to(self.root).as_posix(), stat.st_mtime_ns, stat.st_size))
        return tuple(rows)

    def _ensure_current(self, library: str) -> None:
        """运行期间教研也会改卡片：按窗口复核文件指纹，变了就增量重建，而不是抱着旧正文到重启。"""
        if library not in self._built:
            return  # 还没建过，交给 search() 里的首次 build
        stamp = self._card_stamp.get(library)
        if stamp is not None and time.monotonic() - stamp[0] < self._card_ttl:
            return
        current = self._card_stamp_of(library)
        if stamp is None or current != stamp[1]:
            # 不在这儿加锁：build() 会经由 store 属性取同一把锁。并发的重复 upsert 是幂等的。
            self.build([library])
        self._card_stamp[library] = (time.monotonic(), current)

    def iter_cards(self, library: str, limit: Optional[int] = None) -> Iterable[CardDoc]:
        base = self.root / CARD_DIRS[library]
        if not base.is_dir():
            return
        produced = 0
        for path in sorted(base.rglob("*.md")):
            if path.name == "README.md":
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue
            fields, body = _parse_frontmatter(raw)
            question_id = fields.get("id") or path.stem
            if not question_id.startswith(("ntce.", "cet")) and "question_id" in fields:
                question_id = fields["question_id"]
            text = body.strip() or raw.strip()
            metadata = {
                "question_id": question_id,
                "exam": fields.get("exam", ""),
                "library": library,
                "level": fields.get("level") or fields.get("exam_level", ""),
                "subject": fields.get("subject", ""),
                "module": fields.get("module", ""),
                "section": fields.get("section", ""),
                "question_type": fields.get("question_type", ""),
                "review_status": fields.get("review_status", ""),
                "answer_status": fields.get("answer_status", ""),
                "node_ids": fields.get("knowledge_nodes", ""),
                "requirement_ids": fields.get("exam_requirement_ids", ""),
                "rubric_id": fields.get("rubric_id", ""),
                "copyright_scope": fields.get("copyright_scope", ""),
                "path": path.relative_to(self.root).as_posix(),
            }
            metadata["card_digest"] = _content_digest(text, metadata)
            yield CardDoc(
                question_id=question_id,
                library=library,
                path=metadata["path"],
                text=text,
                metadata=metadata,
            )
            produced += 1
            if limit is not None and produced >= limit:
                return

    # ----------------------------------------------------------------- store
    @property
    def store(self):
        if self._store is None:
            with self._lock:
                if self._store is None:
                    if self.backend == "chroma":
                        try:
                            self._store = ChromaStore(self.root, embedder=self._embedder)
                        except Exception:
                            self.backend = "bm25_fallback"
                            self._store = LexicalStore()
                    else:
                        self._store = LexicalStore()
        return self._store

    def build(self, libraries: Sequence[str] = ("ntce", "cet"), limit_per_library: Optional[int] = None) -> dict:
        """按内容指纹增量重建：条数相同但正文/状态变过的卡也必须重新入集合。"""
        report: Dict[str, dict] = {}
        for library in libraries:
            docs = list(self.iter_cards(library, limit=limit_per_library))
            ids = {_doc_id(d) for d in docs}
            known_digests = getattr(self.store, "known_digests", None)
            known: Dict[str, str] = {}
            if callable(known_digests):
                try:
                    known = known_digests(library)
                except Exception:
                    known = {}
            changed = [d for d in docs if known.get(_doc_id(d)) != d.metadata.get("card_digest")]
            if changed:
                self.store.upsert(library, changed)
            pruned = 0
            prune = getattr(self.store, "prune", None)
            if callable(prune) and limit_per_library is None:
                try:
                    pruned = prune(library, ids)
                except Exception:
                    pruned = 0
            try:
                stored = self.store.count(library)
            except Exception:
                stored = len(ids)
            report[library] = {
                "documents": stored,
                "cards": len(ids),
                "changed": len(changed),
                "pruned": pruned,
                "rebuilt": bool(changed or pruned),
            }
            self._built.add(library)
            self._card_stamp[library] = (time.monotonic(), self._card_stamp_of(library))
        return {"backend": self.backend, "embedder": EMBEDDER_NAME if self.backend == "chroma" else "bm25", "libraries": report}

    def notices(self) -> List[str]:
        if self.backend == "chroma":
            return [f"向量召回后端 chromadb，embedder={EMBEDDER_NAME}（词法哈希，非语义模型）。"]
        return [LEXICAL_NOTICE]

    # ---------------------------------------------------------------- search
    def search(
        self,
        query: str,
        *,
        libraries: Sequence[str] = ("ntce", "cet"),
        k: int = 8,
        filters: Optional[Dict[str, set]] = None,
    ) -> List[SearchHit]:
        filters = filters or {}
        hits: List[SearchHit] = []
        for library in libraries:
            if library not in CARD_DIRS:
                continue
            if library not in self._built:
                self.build([library])
            else:
                self._ensure_current(library)
            try:
                hits.extend(self.store.search(library, query, k, filters))
            except Exception as exc:  # a broken index is rebuildable, not fatal
                self._built.discard(library)
                raise RuntimeError(f"vector search failed for {library}: {exc}") from exc
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]


@lru_cache(maxsize=1)
def get_card_index() -> CardIndex:
    return CardIndex()
