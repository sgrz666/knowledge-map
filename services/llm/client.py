"""LLMClient: the only door from the agent runtime to a language model.

Per ``docs/agent_architecture.md`` §4: providers are configured exclusively from
``KNOWLEDGE_MAP_LLM_BASE_URL`` / ``KNOWLEDGE_MAP_LLM_API_KEY`` / ``KNOWLEDGE_MAP_LLM_MODEL``.
With no key the client degrades **explicitly** — every result carries
``mode="rule_only"`` and never pretends a model answered (no silent fallback).
HTTP goes through stdlib ``urllib.request`` only: bounded retries (max 2) with
backoff, per-call timeout, cost/latency accounting.

Provenance reuses the exact ``analysis.generation`` field names already in the
dataset (``requested_model`` / ``prompt_sha256`` / ``created_at`` / ``thinking``),
verified against ``数据集/教资/questions/**/*.jsonl``.

Every payload the client returns has passed ``services.llm.guardrails``: schema
violations land in the review queue and are NOT retried, re-guessed or repaired.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.llm.guardrails import (
    GuardResult,
    LlmWritePermissionError,
    assert_prompt_not_reviewer,
    enforce_payload,
)

ENV_BASE_URL = "KNOWLEDGE_MAP_LLM_BASE_URL"
ENV_API_KEY = "KNOWLEDGE_MAP_LLM_API_KEY"
ENV_MODEL = "KNOWLEDGE_MAP_LLM_MODEL"

MODE_LLM = "llm"
MODE_RULE_ONLY = "rule_only"

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 2  # non-negotiable bound: 2 retries after the first attempt
RETRY_BACKOFF_SECONDS = (1.0, 3.0)
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

#: the model is a 教研助理, never the reviewer; wording law from §4/A7
SYSTEM_PROMPT = (
    "你是教资/四六级教研助理，为备考智能体生成结构化 JSON 草稿。"
    "你不是审核人，不得声称内容已审核、已核定或官方；审核签署只由教研审核人完成。"
    "难度只能表述为“教研初估”，禁止 IRT/CAT/标准误/能力值等未经校准的测量学声称。"
    "只输出一个 JSON 对象，不要输出解释文字。"
)


class LLMError(RuntimeError):
    """Base class for provider transport/protocol failures."""


class LLMUnavailableError(LLMError):
    """Provider exhausted its bounded retries; caller must stay in explicit degraded mode."""


@dataclass
class ProviderResponse:
    text: str
    model: Optional[str]
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    latency_ms: int = 0
    retries: int = 0


class BaseProvider:
    name = "base"
    is_rule_only = False
    model: Optional[str] = None

    def generate(self, messages: List[Dict[str, str]], *, max_tokens: int = 2048,
                 temperature: float = 0.2) -> ProviderResponse:
        raise NotImplementedError


class RuleOnlyProvider(BaseProvider):
    """Default provider when no key is configured: it never fabricates a completion."""

    name = "rule_only"
    is_rule_only = True

    def generate(self, messages: List[Dict[str, str]], *, max_tokens: int = 2048,
                 temperature: float = 0.2) -> ProviderResponse:
        raise LLMUnavailableError("未配置 LLM key，RuleOnlyProvider 不发起任何模型调用。")


class OpenAICompatibleProvider(BaseProvider):
    """chat/completions over stdlib urllib, configured only from the three env vars."""

    name = "openai_compatible"
    is_rule_only = False

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _post(self, body: dict) -> Tuple[dict, int]:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.monotonic()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload, int((time.monotonic() - started) * 1000)

    def generate(self, messages: List[Dict[str, str]], *, max_tokens: int = 2048,
                 temperature: float = 0.2) -> ProviderResponse:
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        last_error: Optional[Exception] = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                payload, latency = self._post(body)
                choice = (payload.get("choices") or [{}])[0]
                usage = payload.get("usage") or {}
                return ProviderResponse(
                    text=(choice.get("message") or {}).get("content") or "",
                    model=payload.get("model") or self.model,
                    usage={k: int(v) for k, v in usage.items() if isinstance(v, (int, float))},
                    finish_reason=choice.get("finish_reason"),
                    latency_ms=latency,
                    retries=attempt,
                )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in _RETRYABLE_STATUS or attempt >= MAX_RETRIES:
                    raise LLMUnavailableError(f"LLM HTTP {exc.code}（已用尽重试预算）") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = exc
                if attempt >= MAX_RETRIES:
                    break
            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
        raise LLMUnavailableError(f"LLM 调用失败（已用尽重试预算）：{last_error}")


@dataclass
class LLMResult:
    """One client call outcome. ``mode`` is always explicit — never a silent fallback."""

    mode: str  # "llm" | "rule_only"
    ok: bool
    task: str
    payload: Optional[dict] = None
    text: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    guard: Optional[GuardResult] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "ok": self.ok,
            "task": self.task,
            "payload": self.payload,
            "errors": self.errors,
            "guard": self.guard.as_dict() if self.guard else None,
            "provenance": self.provenance,
        }


_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


def _extract_json(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


class LLMClient:
    """Single entry point for model calls; owns provider choice, accounting and guardrails."""

    def __init__(self, provider: Optional[BaseProvider] = None) -> None:
        self.provider = provider if provider is not None else self._provider_from_env()
        self._lock = threading.Lock()
        self._stats = {
            "calls": 0,
            "llm_calls": 0,
            "rule_only_calls": 0,
            "ok": 0,
            "degraded": 0,
            "retries": 0,
            "total_latency_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost_cny": 0.0,
        }

    @staticmethod
    def _provider_from_env() -> BaseProvider:
        base_url = os.environ.get(ENV_BASE_URL, "").strip()
        api_key = os.environ.get(ENV_API_KEY, "").strip()
        model = os.environ.get(ENV_MODEL, "").strip()
        if base_url and api_key and model:
            return OpenAICompatibleProvider(base_url, api_key, model)
        return RuleOnlyProvider()

    @property
    def is_rule_only(self) -> bool:
        return self.provider.is_rule_only

    # ------------------------------------------------------------ provenance
    @staticmethod
    def _provenance(prompt: str, *, requested_model: Optional[str], status: str,
                    response: Optional[ProviderResponse] = None) -> Dict[str, Any]:
        """Exact dataset field names from ``analysis.generation`` (grepped from the jsonl)."""
        prov: Dict[str, Any] = {
            "requested_model": requested_model,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "thinking": {"type": "disabled"},
            "method": "rule_only" if response is None else "llm",
            "status": status,
        }
        if response is not None:
            prov["response_model"] = response.model
            prov["usage"] = response.usage
            prov["finish_reason"] = response.finish_reason
            prov["latency_ms"] = response.latency_ms
            prov["retries"] = response.retries
        return prov

    def _account(self, response: Optional[ProviderResponse], ok: bool) -> None:
        with self._lock:
            s = self._stats
            s["calls"] += 1
            if self.is_rule_only:
                s["rule_only_calls"] += 1
            else:
                s["llm_calls"] += 1
            s["ok" if ok else "degraded"] += 1
            if response is not None:
                s["retries"] += response.retries
                s["total_latency_ms"] += response.latency_ms
                s["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
                s["completion_tokens"] += response.usage.get("completion_tokens", 0)
                # conservative estimate: ¥1 / 1M prompt tokens, ¥2 / 1M completion tokens
                s["estimated_cost_cny"] = round(
                    s["estimated_cost_cny"]
                    + response.usage.get("prompt_tokens", 0) / 1_000_000
                    + response.usage.get("completion_tokens", 0) * 2 / 1_000_000,
                    6,
                )

    # ---------------------------------------------------------------- calling
    def generate(
        self,
        prompt: str,
        *,
        task: str = "general",
        schema_name: Optional[str] = None,
        user_id: str = "llm_runtime",
        question_id: Optional[str] = None,
        node_id: Optional[str] = None,
        requirement_id: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> LLMResult:
        """Run one guarded completion. Never claims a model answered when none did."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        # Both halves of the conversation are checked: the iron law is about what the model is
        # told, and the system message is where a reviewer role is most easily smuggled in.
        for message in messages:
            assert_prompt_not_reviewer(message["content"])

        if self.is_rule_only:
            # explicit degradation — no HTTP, no fabricated payload, no silent anything.
            result = LLMResult(
                mode=MODE_RULE_ONLY,
                ok=False,
                task=task,
                errors=["no_llm_provider_configured：未设置 "
                        f"{ENV_BASE_URL}/{ENV_API_KEY}/{ENV_MODEL}，仅规则模式，模型未参与。"],
                provenance=self._provenance(prompt, requested_model=None, status="not_attempted"),
            )
            self._account(None, ok=False)
            return result

        response: Optional[ProviderResponse] = None
        try:
            response = self.provider.generate(
                messages, max_tokens=max_tokens, temperature=temperature
            )
        except LLMUnavailableError as exc:
            result = LLMResult(
                mode=MODE_RULE_ONLY,  # transport failed => we are back in rule-only, openly
                ok=False,
                task=task,
                errors=[str(exc)],
                provenance=self._provenance(prompt, requested_model=self.provider.model,
                                            status="provider_unavailable"),
            )
            self._account(None, ok=False)
            return result

        text = response.text
        payload = _extract_json(text) if text else None
        errors: List[str] = []
        guard: Optional[GuardResult] = None

        if payload is None:
            errors.append("响应中未解析出 JSON 载荷；不做二次猜测，直接转人工复核。")
            guard = GuardResult(ok=False, schema_name=schema_name,
                                errors=[{"path": "$", "message": "unparseable_json"}])
            self._route(text=text, raw=None, schema_name=schema_name, guard=guard,
                        user_id=user_id, question_id=question_id, node_id=node_id,
                        requirement_id=requirement_id)
            guard.queued = True
        else:
            guard = enforce_payload(
                payload,
                schema_name,
                user_id=user_id,
                question_id=question_id,
                node_id=node_id,
                requirement_id=requirement_id,
                source="services.llm.client",
                generated_text=text,
            )
            if not guard.ok:
                errors.extend(f"{e['path']}: {e['message']}" for e in guard.errors[:5])
                # guardrails.py already routed to the review queue; we NEVER retry/repair here.

        ok = guard.ok and not errors
        self._account(response, ok=ok)
        return LLMResult(
            mode=MODE_LLM,
            ok=ok,
            task=task,
            payload=payload if ok else None,
            text=text,
            errors=errors,
            guard=guard,
            provenance=self._provenance(
                prompt,
                requested_model=self.provider.model,
                status="response_received" if ok else "rejected_by_guardrails",
                response=response,
            ),
        )

    def validate_local(
        self,
        payload: Any,
        schema_name: Optional[str],
        *,
        user_id: str = "llm_runtime",
        **ids: Optional[str],
    ) -> GuardResult:
        """Guardrail-only pass for runtime-drafted (rule/heuristic) payloads."""
        return enforce_payload(payload, schema_name, user_id=user_id,
                              source="services.llm.client.local", **ids)

    @staticmethod
    def _route(*, text: Optional[str], raw: Any, schema_name: Optional[str], guard: GuardResult,
               user_id: str, question_id: Optional[str], node_id: Optional[str],
               requirement_id: Optional[str]) -> None:
        from services.review.queue import get_review_queue

        get_review_queue().add(
            reason="llm_unparseable_payload",
            user_id=user_id,
            question_id=question_id,
            node_id=node_id,
            requirement_id=requirement_id,
            source="services.llm.client",
            detail={"schema_name": schema_name, "errors": guard.errors[:5],
                    "text_preview": (text or "")[:400], "no_retry": True},
        )

    def stats(self) -> dict:
        with self._lock:
            return {"provider": self.provider.name, "mode": MODE_RULE_ONLY if self.is_rule_only else MODE_LLM,
                    **self._stats}


_DEFAULT_CLIENT: Optional[LLMClient] = None
_DEFAULT_LOCK = threading.Lock()


def get_llm_client() -> LLMClient:
    """Process-wide client; env is read once at construction."""
    global _DEFAULT_CLIENT
    with _DEFAULT_LOCK:
        if _DEFAULT_CLIENT is None:
            _DEFAULT_CLIENT = LLMClient()
    return _DEFAULT_CLIENT
