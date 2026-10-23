"""Shared error types and formatting for LLM-facing SDK feedback."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
from typing import Any, Iterable, Optional, Sequence, Tuple, NoReturn


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff" for char in value)


def _normalize_lines(values: Iterable[str]) -> Tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _technical_details_from_error(error: BaseException) -> str:
    message = str(error).strip()
    if message:
        if _contains_cjk(message):
            message = "The underlying validation failed; use the structured guidance above to repair the operation."
        return f"{type(error).__name__}: {message}"
    return type(error).__name__


@dataclass(frozen=True)
class ErrorMeasurement:
    """One failure-time geometric fact: a named scalar or vector with unit.

    Text axiom: every measurement renders into the error text itself, so
    text-only agents and tests never depend on the rendered evidence image.
    """

    name: str
    value: Any
    unit: str = ""

    def display(self) -> str:
        if isinstance(self.value, (tuple, list)):
            rendered = "(" + ", ".join(f"{float(v):.4g}" for v in self.value) + ")"
        else:
            rendered = f"{float(self.value):.4g}"
        return f"{self.name}: {rendered}" + (f" {self.unit}" if self.unit else "")


@dataclass(frozen=True)
class ErrorEvidence:
    """Rendered visual evidence; labels in the image share the symbol table."""

    kind: str  # "render" today
    path: str
    view: str = ""
    caption: str = ""
    symbols: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class InventoryEntry:
    """One candidate entity in a selection diagnosis (hit / near_miss / unmatched)."""

    symbol: str
    status: str
    description: str


@dataclass(frozen=True)
class ErrorGuidance:
    what_happened: str
    possible_causes: Tuple[str, ...]
    how_to_fix: Tuple[str, ...]
    technical_details: Optional[str] = None
    signature: Optional[str] = None
    documentation_hint: Optional[str] = None
    measurements: Tuple[ErrorMeasurement, ...] = ()
    evidence: Tuple[ErrorEvidence, ...] = ()
    repair: Tuple[str, ...] = ()
    inventory: Tuple[InventoryEntry, ...] = ()


def _resolve_operation_callable(operation: str) -> Any:
    op = str(operation).strip()
    if not op:
        return None

    if "." in op:
        module_name, attr_path = op.rsplit(".", 1)
        try:
            obj = importlib.import_module(module_name)
        except Exception:
            obj = None
        if obj is not None:
            for part in attr_path.split("."):
                if not hasattr(obj, part):
                    obj = None
                    break
                obj = getattr(obj, part)
            if obj is not None:
                return obj

        try:
            scad = importlib.import_module("simplecadapi")
        except Exception:
            return None
        obj = scad
        for part in op.split("."):
            if not hasattr(obj, part):
                return None
            obj = getattr(obj, part)
        return obj

    try:
        scad = importlib.import_module("simplecadapi")
    except Exception:
        return None
    return getattr(scad, op, None)


def _operation_signature(operation: str) -> Optional[str]:
    obj = _resolve_operation_callable(operation)
    if obj is None:
        return None
    try:
        return f"{operation}{inspect.signature(obj)}"
    except (TypeError, ValueError):
        return None


def _documentation_hint(operation: str) -> str:
    op = str(operation).strip()
    if not op:
        return "For full usage details, run help(...) on the failing operation."
    if "." in op:
        return f"For full usage details, run help({op})."
    return f"For full usage details, run help(simplecadapi.{op})."


def format_llm_error(operation: str, guidance: ErrorGuidance) -> str:
    lines = [f"Operation: {operation}"]
    if guidance.signature:
        lines.append(f"Signature: {guidance.signature}")
    if guidance.documentation_hint:
        lines.append(f"Documentation: {guidance.documentation_hint}")
    lines.append(f"What happened: {guidance.what_happened}")
    if guidance.measurements:
        lines.append("Measurements:")
        lines.extend(f"- {item.display()}" for item in guidance.measurements)
    if guidance.evidence:
        lines.append("Evidence:")
        for item in guidance.evidence:
            rendered = f"- {item.kind} view '{item.view or 'default'}'"
            if item.path:
                rendered += f": {item.path}"
            if item.caption:
                rendered += f" ({item.caption})"
            lines.append(rendered)
            if item.symbols:
                table = ", ".join(f"{sym}={desc}" for sym, desc in item.symbols)
                lines.append(f"  symbols: {table}")
    lines.append("Possible causes:")
    lines.extend(f"- {item}" for item in guidance.possible_causes)
    fix_items = tuple(guidance.repair) + tuple(guidance.how_to_fix)
    lines.append("How to fix:")
    lines.extend(f"- {item}" for item in fix_items)
    if guidance.inventory:
        lines.append("Inventory:")
        lines.extend(
            f"- {entry.symbol} [{entry.status}] {entry.description}"
            for entry in guidance.inventory
        )
    if guidance.technical_details:
        lines.append(f"Technical details: {guidance.technical_details}")
    return "\n".join(lines)


class SimpleCADError(ValueError):
    """Structured ValueError variant for LLM-oriented repair guidance."""

    def __init__(self, operation: str, guidance: ErrorGuidance):
        self.operation = str(operation)
        self.guidance = guidance
        super().__init__(format_llm_error(self.operation, self.guidance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "what_happened": self.guidance.what_happened,
            "possible_causes": list(self.guidance.possible_causes),
            "how_to_fix": list(self.guidance.how_to_fix),
            "technical_details": self.guidance.technical_details,
            "signature": self.guidance.signature,
            "documentation_hint": self.guidance.documentation_hint,
            "measurements": [
                {
                    "name": m.name,
                    "value": list(m.value) if isinstance(m.value, (tuple, list)) else m.value,
                    "unit": m.unit,
                }
                for m in self.guidance.measurements
            ],
            "evidence": [
                {
                    "kind": e.kind,
                    "path": e.path,
                    "view": e.view,
                    "caption": e.caption,
                    "symbols": dict(e.symbols),
                }
                for e in self.guidance.evidence
            ],
            "repair": list(self.guidance.repair),
            "inventory": [
                {"symbol": i.symbol, "status": i.status, "description": i.description}
                for i in self.guidance.inventory
            ],
        }


class SimpleCADMessageError(SimpleCADError):
    """Message-first SDK error that still carries the structured payload.

    Sole sanctioned base for message-style error families: raise sites keep
    their legacy ``Error("message")`` call shape while the structured channel
    (guidance, ``to_dict``) becomes available family-wide.

    A family declares its designed guidance with the class attributes
    ``possible_causes`` and ``how_to_fix``; the error then renders in full
    (operation, what happened, possible causes, how to fix) like every
    operator error, and ``str()`` carries all of it for the agent that reads
    it.  A family that has none yet keeps the plain one-line display.
    """

    operation = "simplecadapi"
    possible_causes: Tuple[str, ...] = ()
    how_to_fix: Tuple[str, ...] = ()

    def __init__(self, message: str) -> None:
        self.message = str(message)
        guidance = ErrorGuidance(
            what_happened=self.message,
            possible_causes=tuple(type(self).possible_causes),
            how_to_fix=tuple(type(self).how_to_fix),
        )
        self._display = (
            format_llm_error(type(self).operation, guidance)
            if guidance.possible_causes or guidance.how_to_fix
            else self.message
        )
        super().__init__(type(self).operation, guidance)
        self.args = (self._display,)

    def __str__(self) -> str:
        return self._display

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._display!r})"


def raise_harness_error(
    *,
    operation: str,
    what_happened: str,
    possible_causes: Sequence[str],
    how_to_fix: Sequence[str],
    technical_details: Optional[str] = None,
    error: Optional[BaseException] = None,
    measurements: Sequence[ErrorMeasurement] = (),
    evidence: Sequence[ErrorEvidence] = (),
    repair: Sequence[str] = (),
    inventory: Sequence[InventoryEntry] = (),
) -> NoReturn:
    if isinstance(error, SimpleCADError):
        raise error

    resolved_details = technical_details
    if resolved_details is None and error is not None:
        resolved_details = _technical_details_from_error(error)

    guidance = ErrorGuidance(
        what_happened=str(what_happened).strip(),
        possible_causes=_normalize_lines(possible_causes),
        how_to_fix=_normalize_lines(how_to_fix),
        technical_details=(
            str(resolved_details).strip()
            if resolved_details is not None and str(resolved_details).strip()
            else None
        ),
        signature=_operation_signature(str(operation)),
        documentation_hint=_documentation_hint(str(operation)),
        measurements=tuple(measurements),
        evidence=tuple(evidence),
        repair=_normalize_lines(repair),
        inventory=tuple(inventory),
    )
    raise SimpleCADError(str(operation), guidance) from error
