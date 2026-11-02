"""The assembly document a GUI edits, and the cells it becomes.

An assembly is not a chain of features: every cell that returned the growing assembly would cache a full copy of it, which the
cell rules warn against.  The document is therefore the whole layout (components, which one is grounded, the constraints), and
:func:`render` writes it as three cells, the way the notebook templates do:

* ``# ---- params: <slug> ----``: each placement's origin and each joint's drive as ``scad.var`` sliders;
* ``# ---- feature: <slug>_parts (add) ----``: one ``scad.use`` per child;
* ``# ---- feature: <slug> (add) ----``: the assembly built in one pass and solved; this cell carries the ``# gui:`` line and
  binds the product ``<slug>``.

Document::

    {"components": [{"id": "base", "part": "base.py", "origin": [0, 0, 0], "x_axis": "+x", "y_axis": "+y"}],
     "ground": "base",
     "constraints": [{"id": "j1", "kind": "revolute", "a": {"component": "base", "connector": "top"},
                      "b": {"component": "arm", "connector": "root"}, "drive": 30.0, "limit": [-90, 90]}]}

Constraint kinds: ``fixed``, ``revolute`` (drive in degrees), ``prismatic`` (drive in mm), ``gear`` (pitch radii), ``belt``
(pulley radii), ``rack_pinion`` (``a`` is the rack, ``b`` the pinion).  A mate is a ``fixed`` constraint between two connector
frames; the connectors themselves are declared in the part notebooks (see :func:`connectors_of`).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

_ID = re.compile(r"[a-z][a-z0-9_]{0,30}")
_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.py")
_CONNECTOR = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,60}")
AXES = {"+x": (1.0, 0.0, 0.0), "-x": (-1.0, 0.0, 0.0), "+y": (0.0, 1.0, 0.0), "-y": (0.0, -1.0, 0.0), "+z": (0.0, 0.0, 1.0), "-z": (0.0, 0.0, -1.0)}
KINDS = ("fixed", "revolute", "prismatic", "gear", "belt", "rack_pinion")


class AssemblyError(ValueError):
    """An assembly document that cannot be used; the message is meant for the person."""


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise AssemblyError(f"{what}: a number is required")
    return float(value)


def _num(value: float) -> str:
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    return "0.0" if text in ("", "-0") else (text if "." in text else text + ".0")


def validate(doc: Mapping[str, Any]) -> dict[str, Any]:
    """The cleaned document, or :class:`AssemblyError`."""
    components: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in doc.get("components") or []:
        cid = str(raw.get("id"))
        if not _ID.fullmatch(cid):
            raise AssemblyError(f"component id {cid!r}: lowercase letters, digits and underscores, starting with a letter")
        if cid in ids:
            raise AssemblyError(f"the component id {cid!r} is used twice")
        ids.add(cid)
        part = str(raw.get("part"))
        if not _PART.fullmatch(part) or ".." in part.split("/"):
            raise AssemblyError(f"{cid}: {part!r} is not a notebook path inside the workspace")
        origin = raw.get("origin", [0.0, 0.0, 0.0])
        if not (isinstance(origin, (list, tuple)) and len(origin) == 3):
            raise AssemblyError(f"{cid}: the origin is three numbers (x, y, z)")
        x_axis, y_axis = str(raw.get("x_axis", "+x")), str(raw.get("y_axis", "+y"))
        if x_axis not in AXES or y_axis not in AXES:
            raise AssemblyError(f"{cid}: an axis is one of {', '.join(AXES)}")
        if x_axis[1] == y_axis[1]:
            raise AssemblyError(f"{cid}: the x axis and the y axis must not be along the same line")
        components.append({"id": cid, "part": part, "origin": [_number(v, f"{cid} origin") for v in origin], "x_axis": x_axis, "y_axis": y_axis})
    ground = doc.get("ground")
    if ground is not None and ground not in ids:
        raise AssemblyError(f"the grounded component {ground!r} is not in the assembly")
    constraints: list[dict[str, Any]] = []
    used: set[str] = set()
    for number, raw in enumerate(doc.get("constraints") or [], start=1):
        kind = raw.get("kind")
        if kind not in KINDS:
            raise AssemblyError(f"unknown constraint {kind!r}")
        cid = str(raw.get("id") or f"k{number}")
        if not _ID.fullmatch(cid) or cid in used:
            raise AssemblyError(f"constraint id {cid!r} is invalid or used twice")
        used.add(cid)
        item: dict[str, Any] = {"id": cid, "kind": kind}
        for side in ("a", "b"):
            ref = raw.get(side) or {}
            component, connector = str(ref.get("component")), str(ref.get("connector"))
            if component not in ids:
                raise AssemblyError(f"{cid}: {component!r} is not a component of the assembly")
            if not _CONNECTOR.fullmatch(connector):
                raise AssemblyError(f"{cid}: {connector!r} is not a connector name")
            item[side] = {"component": component, "connector": connector}
        if item["a"]["component"] == item["b"]["component"]:
            raise AssemblyError(f"{cid}: a constraint joins two different components")
        if kind in ("revolute", "prismatic"):
            if raw.get("drive") is not None:
                item["drive"] = _number(raw["drive"], f"{cid} drive")
            limit = raw.get("limit")
            if limit is not None:
                if not (isinstance(limit, (list, tuple)) and len(limit) == 2):
                    raise AssemblyError(f"{cid}: the limit is a lower and an upper value")
                low, high = _number(limit[0], f"{cid} limit"), _number(limit[1], f"{cid} limit")
                if low >= high:
                    raise AssemblyError(f"{cid}: the lower limit must be below the upper one")
                item["limit"] = [low, high]
        if kind in ("gear", "belt", "rack_pinion"):
            names = ("pitch_radius",) if kind == "rack_pinion" else (("pitch_radius_a", "pitch_radius_b") if kind == "gear" else ("pulley_radius_a", "pulley_radius_b"))
            for name in names:
                value = _number(raw.get(name), f"{cid} {name}")
                if value <= 0:
                    raise AssemblyError(f"{cid}: {name} must be greater than zero")
                item[name] = value
            if raw.get("phase") is not None:
                item["phase"] = _number(raw["phase"], f"{cid} phase")
        constraints.append(item)
    if constraints and ground is None:
        raise AssemblyError("constraints need a grounded component: the solver moves everything else relative to it")
    return {"components": components, "ground": ground, "constraints": constraints}


def _ref(side: Mapping[str, str]) -> str:
    return f"scad.make_connector_ref_rconnectorref(component_id={json.dumps(side['component'])}, connector_id={json.dumps(side['connector'])})"


def render(slug: str, name: str, doc: Mapping[str, Any], notebook_dir: Path | None = None, workspace: Path | None = None) -> dict[str, Any]:
    """The cells of a validated *doc*: ``{"params": [...], "uses": [...], "layout": [...]}`` (lists of lines).

    Part paths in the document are relative to the workspace; ``scad.use`` resolves paths from the notebook, so they are
    rewritten relative to *notebook_dir* when both directories are given.
    """
    params: list[str] = []
    var: dict[str, str] = {}

    def slider(key: str, label: str, value: float, unit: str, low: float, high: float) -> str:
        variable = f"{slug}_{key}".upper()
        step = "1.0" if high - low >= 20 else "0.1"
        params.append(
            f"{variable} = scad.var(name={json.dumps(variable.lower())}, default={_num(value)}, unit={json.dumps(unit)}, "
            f"comment={json.dumps(label)})  # ui: slider({_num(low)}, {_num(high)}, step={step}, label={json.dumps(label)})"
        )
        var[key] = variable
        return variable

    uses: list[str] = []
    lines = [f"_assembly = scad.make_assembly_rassembly(assembly_id=scad.notebook_id(), name={json.dumps(name)})"]
    for comp in doc["components"]:
        cid = comp["id"]
        origin = [slider(f"{cid}_{axis}", f"{cid} origin {axis}", comp["origin"][i], "mm", comp["origin"][i] - 200, comp["origin"][i] + 200) for i, axis in enumerate("xyz")]
        path = comp["part"]
        if notebook_dir is not None and workspace is not None:
            import os

            path = Path(os.path.relpath(workspace / comp["part"], notebook_dir)).as_posix()
        uses.append(f"{cid}_part = scad.use({json.dumps(path)})")
        lines.append(
            f"_assembly = scad.add_component_rassembly(assembly=_assembly, item={cid}_part, component_id={json.dumps(cid)},\n"
            f"    placement=scad.make_placement_rplacement(origin=({', '.join(origin)}), x_axis={AXES[comp['x_axis']]!r}, y_axis={AXES[comp['y_axis']]!r}))"
        )
    if doc["ground"]:
        lines.append(f"_assembly = scad.ground_component_rassembly(assembly=_assembly, component_id={json.dumps(doc['ground'])})")
    for con in doc["constraints"]:
        cid, kind = con["id"], con["kind"]
        head = f"_assembly = scad.add_{kind}_constraint_rassembly(assembly=_assembly, constraint_id={json.dumps(cid)}, "
        if kind == "fixed":
            lines.append(head + f"connector_a={_ref(con['a'])}, connector_b={_ref(con['b'])})")
        elif kind in ("revolute", "prismatic"):
            unit = "deg" if kind == "revolute" else "mm"
            drive_name, limit_name = ("drive_angle_degrees", "angle_limit") if kind == "revolute" else ("drive_distance", "distance_limit")
            extra = ""
            if "drive" in con:
                low, high = (-180.0, 180.0) if kind == "revolute" else (con["drive"] - 100, con["drive"] + 100)
                if "limit" in con:
                    low, high = con["limit"]
                extra += f", {drive_name}=" + slider(f"{cid}_drive", f"{cid} {'angle' if kind == 'revolute' else 'distance'}", con["drive"], unit, low, high)
            if "limit" in con:
                extra += f", {limit_name}=scad.make_scalar_limit_rscalarlimit(lower_value={_num(con['limit'][0])}, upper_value={_num(con['limit'][1])})"
            lines.append(head + f"connector_a={_ref(con['a'])}, connector_b={_ref(con['b'])}{extra})")
        elif kind == "rack_pinion":
            phase = f", phase_offset={_num(con['phase'])}" if "phase" in con else ""
            lines.append(head + f"rack_connector={_ref(con['a'])}, pinion_connector={_ref(con['b'])}, pitch_radius={_num(con['pitch_radius'])}{phase}")
        else:
            a_name, b_name = ("pitch_radius_a", "pitch_radius_b") if kind == "gear" else ("pulley_radius_a", "pulley_radius_b")
            phase = f", phase_offset={_num(con['phase'])}" if "phase" in con else ""
            lines.append(head + f"connector_a={_ref(con['a'])}, connector_b={_ref(con['b'])}, {a_name}={_num(con[a_name])}, {b_name}={_num(con[b_name])}{phase}")
    lines.append(f"{slug} = scad.solve_assembly_constraints_rassembly(assembly=_assembly)" if doc["constraints"] else f"{slug} = _assembly")
    return {"params": params, "uses": uses, "layout": lines}


# ---- what a part offers ----------------------------------------------------------------------------------------------------

_cache: dict[tuple[str, float], list[dict[str, Any]]] = {}


def connectors_of(path: Path) -> list[dict[str, Any]]:
    """The connectors a part notebook declares, with their frames (``origin``, ``x_axis``, ``y_axis``, ``z_axis``).

    Runs the notebook headless (its cell cache applies) and remembers the answer until the file changes.
    """
    key = (str(path.resolve()), path.stat().st_mtime)
    if key in _cache:
        return _cache[key]
    from ..runtime.runner import run_notebook

    product = run_notebook(path).product
    out: list[dict[str, Any]] = []
    ids = getattr(product, "connector_ids", None)
    for connector_id in (ids() if callable(ids) else ids) or ():
        connector = product.get_connector(connector_id)
        frame = getattr(connector, "placement", None)
        if frame is None:
            continue
        out.append(
            {
                "id": connector_id,
                "origin": list(frame.origin),
                "x_axis": list(frame.x_axis),
                "y_axis": list(frame.y_axis),
                "z_axis": list(frame.z_axis),
            }
        )
    _cache[key] = out
    return out


__all__ = ["AXES", "AssemblyError", "KINDS", "connectors_of", "render", "validate"]
