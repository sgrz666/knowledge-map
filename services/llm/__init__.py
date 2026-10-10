"""LLM layer for the exam-prep agent runtime (教资 NTCE / 四六级 CET).

Implements ``docs/agent_architecture.md`` §4: a provider-based :class:`LLMClient`
that never silently falls back, JSON-Schema guardrails bound to the single
authoritative schema directory (``数据集/教资/schemas/``, shared by both libraries
per its README), and the write-permission iron law (LLM output advances
``review.status`` to at most ``llm_enhanced``).
"""
