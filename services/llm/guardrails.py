"""Structured guardrails for every LLM payload (docs/agent_architecture.md §4, §5.2).

Three jobs, all fail-closed and all *without repair*:

1. JSON Schema validation against the authoritative schema directory
   ``数据集/教资/schemas/`` (both libraries share it — that directory's README
   forbids a CET copy). Validation uses ``jsonschema`` when importable, else a
   small built-in validator covering ``type`` / ``required`` / ``properties`` /
   ``items`` / ``enum`` / ``additionalProperties`` / same-document ``$ref`` /
   ``minimum`` / ``maximum`` / ``minLength`` (plus ``const`` / ``minItems`` /
   ``allOf`` which the real schemas also use). A missing schema is itself a
   violation — we never wave an unvalidated payload through.
2. The write-permission iron law: LLM output may advance ``review.status`` to
   at most ``llm_enhanced``; it may never write ``checked`` / ``expert_reviewed``,
   set ``expert_verified = true`` / ``content_verified = true``, or fill
   ``checked_by``. See :func:`assert_llm_status_allowed`.
3. Wording gates: generated text may never assert 已审核/已核定/官方 status, and
   difficulty stays heuristic ("教研初估") — no IRT / CAT / 标准误 / 能力值 claims.

Anything that trips a gate goes to ``services.review.queue`` for the single
human 教研 reviewer. The client must NOT retry-guess or repair the payload.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:  # optional dependency — a stdlib fallback validator ships below
    import jsonschema as _jsonschema  # type: ignore
except ImportError:  # pragma: no cover
    _jsonschema = None

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_GLOBS = ("数据集/*/schemas/*.json",)

# ---------------------------------------------------------------- iron law
MAX_LLM_STATUS = "llm_enhanced"
#: the only review.status values an LLM-produced record may ever carry
LLM_WRITABLE_STATUSES = frozenset({"auto_parsed", "llm_enhanced"})
#: explicit deny list from §4 / acceptance A4 (plus reviewer-only demotions)
FORBIDDEN_LLM_STATUSES = frozenset({"checked", "expert_reviewed", "needs_fix", "quarantined"})
#: fields only the human reviewer may fill (mirrors queue.SIGNABLE_FIELDS;
#: content_verified/checked_at are the other half of a human signature)
FORBIDDEN_STATUS_FIELDS = frozenset({"checked_by", "expert_verified", "content_verified", "checked_at"})


class LlmWritePermissionError(RuntimeError):
    """Raised when LLM output would cross the write-permission iron law."""


def assert_llm_status_allowed(status: Optional[str]) -> None:
    """LLM may emit ``review.status`` of at most ``llm_enhanced``; anything else raises."""
    if status not in LLM_WRITABLE_STATUSES:
        raise LlmWritePermissionError(
            f"LLM 不得写入 review.status={status!r}；上限为 {MAX_LLM_STATUS!r}，"
            "checked/expert_reviewed 只属于人工复核签署动作。"
        )


def assert_no_forbidden_status_fields(obj: Any, _path: str = "$") -> None:
    """Reject payloads that sign or counter-sign on behalf of the reviewer."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            dot = f"{_path}.{key}"
            if key in FORBIDDEN_STATUS_FIELDS and value:
                raise LlmWritePermissionError(
                    f"LLM 输出在 {dot} 写入了签署字段 {key!r}（值 {value!r}）；"
                    "该字段只能由教研审核人签署后写入。"
                )
            assert_no_forbidden_status_fields(value, dot)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            assert_no_forbidden_status_fields(item, f"{_path}[{i}]")


def assert_llm_record(record: Any) -> None:
    """Combined iron-law check: signing fields + any review.status present in the record."""
    assert_no_forbidden_status_fields(record)
    if isinstance(record, dict):
        review = record.get("review")
        if isinstance(review, dict) and "status" in review:
            assert_llm_status_allowed(review.get("status"))
        if isinstance(record.get("status"), str) and "rubric_id" in record:
            # rubric / practice_framework records carry a top-level status
            assert_llm_status_allowed(record["status"])


# ------------------------------------------------------------- wording gates
BANNED_ASSERTION_PHRASES = ("已审核", "已核定", "审核通过", "已通过复核", "官方认定", "官方审定", "官方标准答案")
BANNED_DIFFICULTY_CLAIMS = ("标准误", "能力值", "能力估计", "题目反应理论")
_BANNED_ASCII = re.compile(r"\b(IRT|CAT|item response theory)\b", re.IGNORECASE)


def scan_banned_claims(text: str) -> List[str]:
    """Return banned authority/difficulty claims found in generated text (never rewritten)."""
    hits: List[str] = []
    for phrase in BANNED_ASSERTION_PHRASES + BANNED_DIFFICULTY_CLAIMS:
        if phrase in text:
            hits.append(phrase)
    for m in _BANNED_ASCII.finditer(text):
        hits.append(m.group(1))
    return sorted(set(hits))


REVIEWER_ROLE_PATTERNS = re.compile(
    r"(现在是|你是|担任|充当|作为|扮演|成为)\s*[^。\n]{0,12}"
    r"(审核人|审稿人|评审专家|复核人|审定|最终裁定|reviewer|final adjudicator)"
    r"|(act|serve|role)\s+as\s+(the\s+)?(final\s+)?reviewer",
    re.IGNORECASE,
)

#: A prompt that *forbids* the reviewer role ("不要担任审核人") is quoting the iron law, not
#: assigning the role. The negation has to sit directly on the verb — a bare 不 anywhere else in
#: the sentence does not disarm the match.
_NEGATION_ONE = frozenset("不非未没勿别")
_NEGATION_TWO = frozenset({"不要", "不得", "不能", "不可", "不应", "不当", "不准", "不是", "并非",
                           "无需", "不必", "切勿", "请勿", "禁止"})


def _role_verb_is_negated(prompt: str, start: int) -> bool:
    tail = prompt[:start]
    return tail[-2:] in _NEGATION_TWO or tail[-1:] in _NEGATION_ONE


def assert_prompt_not_reviewer(prompt: str) -> None:
    """The LLM must never be told it is the reviewer (§4 iron law, prompt side)."""
    for m in REVIEWER_ROLE_PATTERNS.finditer(prompt):
        if _role_verb_is_negated(prompt, m.start()):
            continue
        raise LlmWritePermissionError(
            f"提示词把模型设定为审核角色（命中片段：{m.group(0)!r}）；模型只能作为教研助理。"
        )


# ------------------------------------------------------------- schema registry
class SchemaNotFound(FileNotFoundError):
    """No schema document exists for the requested payload type (fail closed)."""


class SchemaRegistry:
    """Maps schema file stems (question/rubric/...) to documents under 数据集/*/schemas/."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else REPO_ROOT
        self._paths: Optional[Dict[str, Path]] = None
        self._docs: Dict[str, dict] = {}

    @property
    def paths(self) -> Dict[str, Path]:
        if self._paths is None:
            found: Dict[str, Path] = {}
            for pattern in SCHEMA_GLOBS:
                for path in sorted(self.root.glob(pattern)):
                    found.setdefault(path.stem, path)
            self._paths = found
        return self._paths

    def available(self) -> List[str]:
        return sorted(self.paths)

    def load(self, name: str) -> Tuple[dict, str]:
        path = self.paths.get(name)
        if path is None:
            raise SchemaNotFound(
                f"数据集/*/schemas/ 下没有 {name!r} Schema（可用：{self.available()}）；"
                "未定义的 Schema 一律 fail closed，不放行。"
            )
        doc = self._docs.get(name)
        if doc is None:
            doc = json.loads(path.read_text(encoding="utf-8"))
            self._docs[name] = doc
        return doc, path.as_posix()


_DEFAULT_REGISTRY = SchemaRegistry()


# ------------------------------------------------------------- validation core
@dataclass
class GuardResult:
    """Outcome of one guardrail pass; ``ok=False`` means: queue it, do not repair."""

    ok: bool
    schema_name: Optional[str] = None
    schema_path: Optional[str] = None
    errors: List[Dict[str, str]] = field(default_factory=list)
    banned_claims: List[str] = field(default_factory=list)
    queued: bool = False

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "schema_name": self.schema_name,
            "schema_path": self.schema_path,
            "errors": self.errors[:20],
            "banned_claims": self.banned_claims,
            "queued": self.queued,
        }


def _resolve_ref(root_doc: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise SchemaNotFound(f"仅支持同文档 $ref，收到 {ref!r}")
    node: Any = root_doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise SchemaNotFound(f"$ref 无法解析：{ref!r}")
    return node


_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _fallback_validate(instance: Any, schema: Any, root: dict, path: str) -> Iterator[Tuple[str, str]]:
    """Minimal JSON Schema subset: the keywords the real 教资 schemas actually use."""
    if schema is True or schema == {}:
        return
    if schema is False:
        yield path, "schema 为 false，任何值都不通过"
        return
    if "$ref" in schema:
        schema = _resolve_ref(root, schema["$ref"])
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPE_CHECKS.get(tt, lambda v: False)(instance) for tt in types):
            yield path, f"type 期望 {types}，实际 {type(instance).__name__}"
    if "enum" in schema and instance not in schema["enum"]:
        yield path, f"值 {instance!r} 不在 enum {schema['enum']} 内"
    if "const" in schema and instance != schema["const"]:
        yield path, f"值 {instance!r} != const {schema['const']!r}"
    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                yield path, f"缺少必填字段 {req!r}"
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in instance:
                yield from _fallback_validate(instance[key], sub, root, f"{path}.{key}")
        extra = schema.get("additionalProperties")
        if extra is not None:
            if extra is False:
                for key in instance:
                    if key not in props:
                        yield path, f"不允许的额外字段 {key!r}"
            elif isinstance(extra, dict):
                for key, value in instance.items():
                    if key not in props:
                        yield from _fallback_validate(value, extra, root, f"{path}.{key}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            yield path, f"字符串长度 {len(instance)} < minLength {schema['minLength']}"
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            yield path, f"{instance} < minimum {schema['minimum']}"
        if "maximum" in schema and instance > schema["maximum"]:
            yield path, f"{instance} > maximum {schema['maximum']}"
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            yield path, f"数组长度 {len(instance)} < minItems {schema['minItems']}"
        items = schema.get("items")
        if isinstance(items, dict):
            for i, element in enumerate(instance):
                yield from _fallback_validate(element, items, root, f"{path}[{i}]")
    for sub in schema.get("allOf", []):
        yield from _fallback_validate(instance, sub, root, path)


def validate_payload(payload: Any, schema_name: str, registry: Optional[SchemaRegistry] = None) -> GuardResult:
    """Validate one LLM payload against the dataset schema; returns errors, never fixes them."""
    reg = registry or _DEFAULT_REGISTRY
    try:
        doc, doc_path = reg.load(schema_name)
    except SchemaNotFound as exc:
        return GuardResult(ok=False, schema_name=schema_name, errors=[{"path": "$", "message": str(exc)}])
    errors: List[Dict[str, str]] = []
    if _jsonschema is not None:
        validator = _jsonschema.Draft202012Validator(doc)
        for err in validator.iter_errors(payload):
            errors.append({"path": "$." + ".".join(str(p) for p in err.absolute_path), "message": err.message})
    else:
        errors = [{"path": p, "message": m} for p, m in _fallback_validate(payload, doc, doc, "$")]
    return GuardResult(ok=not errors, schema_name=schema_name, schema_path=doc_path, errors=errors)


def _preview(payload: Any, limit: int = 600) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(payload)
    return text[:limit]


def enforce_payload(
    payload: Any,
    schema_name: Optional[str],
    *,
    user_id: str = "llm_runtime",
    question_id: Optional[str] = None,
    node_id: Optional[str] = None,
    requirement_id: Optional[str] = None,
    source: str = "services.llm.guardrails",
    registry: Optional[SchemaRegistry] = None,
    generated_text: Optional[str] = None,
) -> GuardResult:
    """Full guardrail pass; on any violation route to the review queue and return not-ok.

    Explicitly does NOT retry, re-guess, or repair the payload — §4 说"不做二次猜测".
    """
    result = GuardResult(ok=True, schema_name=schema_name)
    if generated_text:
        hits = scan_banned_claims(generated_text)
        if hits:
            result.ok = False
            result.banned_claims = hits
            result.errors.append({"path": "$.text", "message": f"生成文本含禁止的权威/校准口吻：{hits}"})
    try:
        assert_llm_record(payload)
    except LlmWritePermissionError as exc:
        result.ok = False
        result.errors.append({"path": "$.review", "message": str(exc)})
    if result.ok and schema_name is not None:
        result = validate_payload(payload, schema_name, registry)
    if not result.ok:
        from services.review.queue import get_review_queue

        get_review_queue().add(
            reason="llm_guardrail_violation",
            user_id=user_id,
            question_id=question_id,
            node_id=node_id,
            requirement_id=requirement_id,
            source=source,
            detail={
                "schema_name": result.schema_name or "unknown_schema",
                "errors": result.errors[:20],
                "banned_claims": result.banned_claims,
                "payload_preview": _preview(payload),
                "no_repair": True,
                "next_action": "人工复核；运行时不重试、不修补该 payload。",
            },
        )
        result.queued = True
    return result
