"""Operation tip loader for the re-studio composer.

An operation tip is a packaged prompt fragment (CLI-command style) bound to a
composer chip. Tips are content, not code: each ``operations/<op_id>.md``
file carries YAML-ish frontmatter (label, category, api, reads, doc_refs)
plus the hint text as its body. Editing or adding a tip is a markdown edit;
this module only loads and validates the folder.

Semantics of the frontmatter fields:

- ``category`` — one of ``OPERATION_CATEGORIES`` (the human's five-way
  classification: sketch / solid build / modifier / surface / pattern);
- ``api`` — the SDK entry points the tip is about;
- ``reads`` — which geometric features of the tagged entities the operation
  consumes, so context assembly knows what to extract and pass;
- ``doc_refs`` — repo-relative skill references the agent should read before
  using the operation;
- body — the imperative hint itself.

The browser renders its palette from ``GET /api/operations`` and
``compose_submission`` embeds the tips for every referenced operation, so the
agent receives the doc pointers without scraping. Malformed files are never
silently skipped: they are named in the payload ``errors`` list and logged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_TIPS_DIR = Path(__file__).resolve().parent / "operations"
_KNOWN_FIELDS = ("label", "category", "api", "reads", "doc_refs")
_LIST_FIELDS = ("api", "reads", "doc_refs")

OPERATION_CATEGORIES: tuple[dict[str, str], ...] = (
    {"id": "sketch", "label": "SKETCH", "description": "constrained 2D profiles (sketch API)"},
    {"id": "boolean", "label": "BOOLEAN", "description": "union / cut / intersect"},
    {"id": "solid", "label": "SOLID", "description": "extrude / revolve / sweep / loft body builds"},
    {"id": "primitive", "label": "PRIMITIVE", "description": "box / cylinder / cone / sphere stock bodies"},
    {"id": "modify", "label": "MODIFY", "description": "fillet / chamfer / shell edge & face treatments"},
    {"id": "surface", "label": "SURFACE", "description": "patch / fill / freeform surface construction"},
    {"id": "pattern", "label": "PATTERN", "description": "linear / radial (circular) arrays and mirrors"},
)
_CATEGORY_ORDER = {category["id"]: index for index, category in enumerate(OPERATION_CATEGORIES)}

_REGISTRY_CACHE: dict[str, Any] | None = None
_REGISTRY_STAMP: tuple[tuple[str, float], ...] | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the tiny frontmatter subset these files use (stdlib only)."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("frontmatter must open with '---'")
    fields: dict[str, Any] = {}
    index = 1
    while index < len(lines) and lines[index].strip() != "---":
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", stripped)
        if not match:
            raise ValueError(f"unparseable frontmatter line {index + 1}: {stripped!r}")
        key, value = match.group(1), match.group(2).strip()
        if key not in _KNOWN_FIELDS:
            raise ValueError(f"unknown frontmatter field {key!r}")
        if value:
            fields[key] = value
            index += 1
            continue
        items: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip().startswith("- ") and lines[index].strip() != "---":
            items.append(lines[index].strip()[2:].strip())
            index += 1
        fields[key] = items
    if index >= len(lines):
        raise ValueError("frontmatter is never terminated with '---'")
    body = "\n".join(lines[index + 1 :]).strip()
    return fields, body


def _validate_tip(op_id: str, fields: dict[str, Any], body: str) -> None:
    if not isinstance(fields.get("label"), str) or not fields["label"]:
        raise ValueError("label must be a non-empty string")
    category = fields.get("category")
    if category not in _CATEGORY_ORDER:
        raise ValueError(f"category {category!r} is not one of {sorted(_CATEGORY_ORDER)}")
    for field in _LIST_FIELDS:
        value = fields.get(field)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise ValueError(f"{field} must be a non-empty dash list")
    if not body:
        raise ValueError("hint body is empty")


def _load_registry() -> dict[str, Any]:
    """Load (and mtime-cache) the operations folder."""

    global _REGISTRY_CACHE, _REGISTRY_STAMP
    files = sorted(_TIPS_DIR.glob("*.md")) if _TIPS_DIR.is_dir() else []
    stamp = tuple((path.name, path.stat().st_mtime) for path in files)
    if _REGISTRY_CACHE is not None and stamp == _REGISTRY_STAMP:
        return _REGISTRY_CACHE
    tips: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in files:
        op_id = path.stem
        try:
            fields, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            _validate_tip(op_id, fields, body)
        except (OSError, ValueError) as exc:
            message = f"{path.name}: {exc}"
            errors.append(message)
            print(f"[re-studio] operation tip rejected — {message}", file=sys.stderr)
            continue
        tips[op_id] = {"op_id": op_id, **fields, "hint": body}
    registry = {"tips": tips, "errors": errors}
    _REGISTRY_CACHE = registry
    _REGISTRY_STAMP = stamp
    return registry


def operation_payload() -> dict[str, Any]:
    """Registry payload for ``GET /api/operations`` (browser palette)."""

    registry = _load_registry()
    operations = sorted(
        registry["tips"].values(),
        key=lambda tip: (_CATEGORY_ORDER[tip["category"]], tip["op_id"]),
    )
    return {
        "categories": [dict(category) for category in OPERATION_CATEGORIES],
        "operations": operations,
        "errors": list(registry["errors"]),
    }


def operation_context_for(op_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Tips for every referenced operation, keyed by op id (stable order)."""

    registry = _load_registry()
    return {op_id: dict(registry["tips"][op_id]) for op_id in op_ids if op_id in registry["tips"]}


__all__ = [
    "OPERATION_CATEGORIES",
    "operation_context_for",
    "operation_payload",
]
