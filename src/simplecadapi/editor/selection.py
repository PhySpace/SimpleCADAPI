"""The viewport selection as notebook code.

Picking in the viewport writes a cell: every picked entity becomes a ``ql``
selector built from its geometry (type, centre, size) and is assigned to
``selected_<kind>`` (``selected_<kind>_<i>`` when several of a kind are
picked), and ``selected_item`` lists them all.  The cell is autosaved with
the notebook, so a coding agent reads what the person selected from the file
on disk and builds on it::

    # ---- selection ----
    selected_edge_1 = scad.ql.edges().where(scad.ql.and_(...)).exactly(1)
    selected_edge_2 = scad.ql.edges().where(scad.ql.and_(...)).exactly(1)
    selected_item = [selected_edge_1, selected_edge_2]
    # next: scad.chamfer_rsolid(solid=body, edges=selected_item[0], ...)

The selectors say where the geometry is, not which id it had, so they keep
selecting it while the model is edited, as long as it stays put.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

MARKER = "# ---- selection ----"
"""First line of the selection cell; how the editor finds it again."""

_QL_TYPES = {
    "plane": "PLANE",
    "cylinder": "CYLINDER",
    "cone": "CONE",
    "sphere": "SPHERE",
    "torus": "TORUS",
    "line": "LINE",
    "circle": "CIRCLE",
    "bspline_surface": "BSPLINE",
    "bspline_curve": "BSPLINE",
    "bezier_surface": "BEZIER",
    "bezier_curve": "BEZIER",
}
_FACTORY = {"face": "faces", "edge": "edges", "solid": "solids", "vertex": "vertices"}
_POSITION_TOLERANCE = 0.1
_RELATIVE_TOLERANCE = 0.01


def selector_expression(kind: str, properties: Mapping[str, Any], geometry: Mapping[str, Any]) -> str | None:
    """A ``scad.ql`` expression selecting the one entity, or ``None``.

    *properties* and *geometry* are the scene sidecar's entity fields.
    """
    factory = _FACTORY.get(kind)
    if factory is None:
        return None
    conditions: list[str] = []
    ql_type = _QL_TYPES.get(str(geometry.get("type", "")))
    if ql_type is not None:
        conditions.append(f'scad.ql.prop("geom.type", "==", "{ql_type}")')
    # A solid has no ql centre; it is told apart by its volume.
    centre = None if kind == "solid" else _vector(
        properties.get("position") if kind == "vertex" else properties.get("centroid")
    )
    if centre is not None:
        for axis, value in zip("xyz", centre):
            conditions.append(f'scad.ql.prop("geom.center.{axis}", ">=", {_number(value - _POSITION_TOLERANCE)})')
            conditions.append(f'scad.ql.prop("geom.center.{axis}", "<=", {_number(value + _POSITION_TOLERANCE)})')
    for name, key in (("geom.area", "area"), ("geom.length", "length"), ("geom.volume", "volume")):
        size = properties.get(key)
        if isinstance(size, (int, float)) and not isinstance(size, bool) and size > 0:
            low, high = size * (1 - _RELATIVE_TOLERANCE), size * (1 + _RELATIVE_TOLERANCE)
            conditions.append(f'scad.ql.prop("{name}", ">=", {_number(low)})')
            conditions.append(f'scad.ql.prop("{name}", "<=", {_number(high)})')
    if not conditions:
        return None
    body = ",\n    ".join(conditions)
    return f"scad.ql.{factory}().where(scad.ql.and_(\n    {body},\n)).exactly(1)"


def selection_cell_code(items: Sequence[Mapping[str, Any]]) -> str:
    """The source of the selection cell for the picked *items*.

    Each item has ``kind`` (``solid|face|edge|vertex|component``) and, for
    the first four, the entity's ``properties`` and ``geometry``; every item
    may carry ``definition_id`` and ``node_id`` for the comment above it.
    """
    lines = [MARKER]
    names: list[str] = []
    totals = Counter(str(item.get("kind", "")) for item in items)
    seen: Counter[str] = Counter()
    for item in items:
        kind = str(item.get("kind", ""))
        seen[kind] += 1
        name = f"selected_{kind}" if totals[kind] == 1 else f"selected_{kind}_{seen[kind]}"
        where = _where(item)
        if kind == "component":
            expression = repr(str(item.get("node_id", "")))
        else:
            expression = selector_expression(kind, item.get("properties") or {}, item.get("geometry") or {})
        if expression is None:
            lines.append(f"# {name}: nothing to select by (no geometry on this entity){where}")
            continue
        lines.append(f"# {kind}{where}")
        lines.append(f"{name} = {expression}")
        names.append(name)
    lines.append(f"selected_item = [{', '.join(names)}]")
    return "\n".join(lines)


def variable_names(items: Sequence[Mapping[str, Any]]) -> list[str]:
    """The ``selected_*`` variable of each item, in order (as in the code)."""
    totals = Counter(str(item.get("kind", "")) for item in items)
    seen: Counter[str] = Counter()
    names = []
    for item in items:
        kind = str(item.get("kind", ""))
        seen[kind] += 1
        names.append(f"selected_{kind}" if totals[kind] == 1 else f"selected_{kind}_{seen[kind]}")
    return names


def _where(item: Mapping[str, Any]) -> str:
    parts = []
    if item.get("definition_id"):
        parts.append(f"of {item['definition_id']}")
    if item.get("node_id"):
        parts.append(f"node {item['node_id']}")
    return f" ({', '.join(parts)})" if parts else ""


def _vector(value: Any) -> tuple[float, float, float] | None:
    if (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(isinstance(part, (int, float)) and not isinstance(part, bool) for part in value)
    ):
        return float(value[0]), float(value[1]), float(value[2])
    return None


def _number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
