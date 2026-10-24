"""SimpleCADError: the Python face of scad::Error.

The C++ side raises scad::Error with structured guidance; the module's exception
translator builds the Python exception through ``make_error`` so that it is a real
``ValueError`` subclass with the same attributes as ``simplecadapi.SimpleCADError``.
"""

from __future__ import annotations

import inspect
from typing import Any


class SimpleCADError(ValueError):
    """Structured ValueError variant for LLM-oriented repair guidance."""

    def __init__(self, operation: str, guidance: dict[str, Any], message: str) -> None:
        self.operation = operation
        self.guidance = guidance
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.guidance)


def _signature(operation: str) -> str | None:
    import simplecadapi._cpp

    obj: Any = simplecadapi._cpp
    for part in operation.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    try:
        return f"{operation}{inspect.signature(obj)}"
    except (TypeError, ValueError):
        return None


def make_error(operation: str, guidance: dict[str, Any], message: str, family: str = "") -> SimpleCADError:
    """Called by the C++ exception translator (`family`: the message-first error class, if it is one)."""
    signature = guidance.get("signature") or _signature(operation)
    if signature and not guidance.get("signature"):
        guidance = {**guidance, "signature": signature}
        lines = message.split("\n")
        lines.insert(1, f"Signature: {signature}")
        message = "\n".join(lines)
    return SimpleCADError(operation, guidance, message)
