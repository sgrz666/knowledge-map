"""Diagnostic Agent module.

The agent reports 卷面分口径 only: ``pass_probability`` stays ``None`` on every path, and there is
no 报道分 / 量表分 / IRT 转换 module here any more (§10 明确不做).
"""
from services.diagnostic.agent import DiagnosticAgent

__all__ = ["DiagnosticAgent"]
