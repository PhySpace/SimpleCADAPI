"""Every SDK operation as a GUI feature: forms made from :mod:`simplecadapi.catalog`, never written by hand.

The curated features of :mod:`.features` (a hole, an extrude of a sketch, pull a face ...) are compositions of SDK calls
shaped for people; this module adds the rest: one feature per public operation of the SDK and of its standard library,
with a slot per parameter whose kind the catalog read from the operation's signature.  The cell it writes is a plain call
(``name = scad.<op>(param=..., ...)``), numbers in the params cell as ``scad.var`` sliders, values by name, picked faces and
edges as a selection recipe.  An operation whose parameters the editor cannot offer (a sketch reference, an untyped
``object``) is left out, so the forms never ask for something they cannot write.
"""

from __future__ import annotations

import dataclasses
import json
from collections import Counter
from functools import lru_cache
from typing import Any

from .. import catalog as C

PREFIX = "op."
"""Spec ids of the operations: ``op.<operation name>``."""

# What a value parameter may be given: the kinds of named values in the notebook that fit it.
_VALUE_FITS: dict[str, tuple[str, ...]] = {
    "solid": ("solid",),
    "face": ("face",),
    "wire": ("wire", "edge"),  # an edge is taken as the wire of that one edge (a curve drawn in the editor is an edge)
    "edge": ("edge",),
    "vertex": ("vertex",),
    "shell": ("shell",),
    "compound": ("compound",),
    "shape": ("solid", "face", "wire", "edge", "vertex", "shell", "compound"),
    "part": ("part",),
    "assembly": ("assembly",),
    "material": ("material",),
    "placement": ("placement",),
    "connector": ("connector",),
    "connector_ref": ("connector_ref",),
}
_NUMBER_KINDS = {"length": "length", "angle": "angle", "number": "float", "int": "count", "count": "count"}
_VECTOR_KINDS = ("point3", "direction3", "vector3")
_SKIP_PREFIXES = ("inspect_", "measure_", "diff_", "render_", "get_", "load_", "solve_", "explode_")
"""Operations that read or report rather than make something (they stay code)."""
_TAG_PARAM = ("tag_prefix", "result_tag", "tracking_policy")

_GROUPS = {
    "solid": "Solids",
    "solids": "Solids",
    "face": "Surfaces",
    "shell": "Surfaces",
    "wire": "Curves",
    "edge": "Curves",
    "vertex": "Curves",
    "wires": "Curves",
    "part": "Product",
    "assembly": "Assembly",
    "connector": "Product",
    "placement": "Product",
    "material": "Product",
}


_MAKES = {"edge": "curve (edge)", "wire": "wire", "face": "face", "shell": "surface", "solid": "solid", "solids": "solids"}
"""How a label names what an operation makes, where two operations share a name."""


def _label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _op_label(op: C.Operation) -> str:
    base = op.name.rsplit("_r", 1)[0]
    for prefix in ("make_", "add_"):
        if base.startswith(prefix):
            base = base[len(prefix):]
    return _label(base)


def _hidden(param: C.Param) -> bool:
    """Tags and policies are code-level choices; a GUI feature tags its result from its own name."""
    return param.name in _TAG_PARAM or param.name.endswith("_tag") or param.name.endswith("_tags")


def _default_number(param: C.Param) -> float:
    if isinstance(param.default, (int, float)) and not isinstance(param.default, bool):
        return float(param.default)
    return {"angle": 45.0, "count": 3.0, "int": 3.0}.get(param.kind, 10.0)


def _slot(param: C.Param, features: Any) -> Any | None:
    """The form slot of one parameter, or ``None`` when the editor cannot offer it (the operation is then left out)."""
    Slot = features.Slot
    label = _label(param.name)
    optional = param.optional or (param.has_default and param.default is None)
    kind = param.kind
    if kind in _NUMBER_KINDS and not param.many:
        slot_kind = _NUMBER_KINDS[kind]
        unit = {"length": "mm", "angle": "deg"}.get(kind)
        minimum = -10000.0 if slot_kind in ("length", "float") else (-360.0 if slot_kind == "angle" else 0.0)
        default = None if optional and not param.has_default else _default_number(param)
        if param.has_default and param.default is None:
            default = None
        if param.name == "opacity":  # a fraction: 0 (clear) to 1 (opaque)
            return Slot(param.name, label, slot_kind, default=default, min=0.0, max=1.0, step=0.05, optional=optional)
        return Slot(param.name, label, slot_kind, default=default, unit=unit, min=minimum, optional=optional)
    if kind in _VECTOR_KINDS and not param.many:
        default = list(param.default) if isinstance(param.default, (list, tuple)) and len(param.default) == 3 else ([0.0, 0.0, 1.0] if kind == "direction3" else [0.0, 0.0, 0.0])
        unit = None if kind == "direction3" else "mm"
        if param.has_default and param.default is None:
            return Slot(param.name, label, "point", default=None, unit=unit, min=-10000.0, optional=True)
        return Slot(param.name, label, "point", default=[float(v) for v in default], unit=unit, min=-10000.0)
    if kind == "grid":  # a control net: rows of points (a flat 3 x 3 patch to start from)
        return Slot(param.name, label, "grid", default=[[[x * 10.0, y * 10.0, 0.0] for x in range(3)] for y in range(3)], unit="mm")
    if kind == "points":
        return Slot(param.name, label, "points3d", default=[[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 10.0, 0.0]], unit="mm")
    if kind == "bool":
        return Slot(param.name, label, "bool", default=bool(param.default) if param.has_default else False)
    if kind == "enum":
        options = [{"value": c, "label": c} for c in param.choices]
        default = param.default if param.default in param.choices else (param.choices[0] if param.choices else None)
        return Slot(param.name, label, "enum", default=default, options=options) if options else None
    if kind == "text":
        if optional:
            return None if param.name != "name" else Slot(param.name, label, "text", default=None, optional=True)
        return Slot(param.name, label, "text", default=str(param.default) if param.has_default else "")
    if kind == "color":  # a display colour: RGB in [0, 1]
        default = [float(v) for v in param.default] if isinstance(param.default, (list, tuple)) and len(param.default) == 3 else None
        return Slot(param.name, label, "color", default=default, optional=optional)
    if kind == "shape" and param.many and "ShapeSelector" in param.type:
        # shapes of the scope, or a ql selection of them (apply_tag_rselection's targets): faces picked in the viewport
        return Slot(param.name, label, "select", entity="face")
    if kind == "query" or (kind in ("edge", "face") and param.many and param.name in ("edges", "faces", "faces_to_remove")):
        entity = "edge" if "edge" in param.name or kind == "edge" else "face"
        return Slot(param.name, label, "select", entity=entity)
    if kind in _VALUE_FITS:
        return Slot(param.name, label, "value", accepts=_VALUE_FITS[kind], many=param.many, optional=optional)
    return None


def _spec_for(op: C.Operation, features: Any) -> Any | None:
    if op.name.startswith(_SKIP_PREFIXES) or op.name.endswith("_rsketch") or op.module.startswith("simplecadapi.std.bearing"):
        return None
    slots: list[Any] = []
    body_slot = None
    for param in op.params:
        if _hidden(param):
            continue
        slot = _slot(param, features)
        if slot is None:
            if param.has_default:
                continue  # an advanced parameter the form leaves at its default
            return None
        if body_slot is None and slot.kind == "value" and "solid" in slot.accepts and not slot.many:
            body_slot = slot.name
        slots.append(slot)
    if not slots:
        return None
    produces = op.returns if op.returns in ("solid", "solids", "face", "assembly") else op.returns
    takes_solid = body_slot is not None
    role = "modifier" if takes_solid and produces == "solid" else "build"
    group = "Standard library" if op.module.startswith("simplecadapi.std") else _GROUPS.get(op.returns, "More")
    spec = features.Spec(
        id=PREFIX + op.name,
        label=_op_label(op),
        group=group,
        role=role,
        produces=produces,
        description=op.summary or op.name,
        slots=tuple(slots),
        build=_builder(op),
        body_slot=body_slot or "body",
        operation=op.name,
    )
    if produces == "solid" and not takes_solid:
        spec = features._with_combine(spec)
    return spec


def _call_path(op: C.Operation) -> str:
    if op.module == "simplecadapi":
        return f"scad.{op.name}"
    return f"scad.{op.module[len('simplecadapi.'):]}.{op.name}"


def _builder(op: C.Operation):
    def build(c: Any) -> list[str]:
        lines: list[str] = []
        args: list[str] = []
        for slot in c.spec.slots:
            if slot.name in ("operation", "target"):
                continue
            value = c.values.get(slot.name)
            if value is None and slot.kind != "select":  # a selection is picked, not a value (its recipe is in c)
                continue
            if slot.kind in ("length", "angle", "float", "count"):
                expr = c.var(slot.name)
            elif slot.kind == "point":
                expr = c.point(slot.name)
            elif slot.kind == "points3d":
                expr = "[" + ", ".join("(" + ", ".join(repr(float(v)) for v in row) + ")" for row in value) + "]"
            elif slot.kind == "grid":
                expr = "[" + ", ".join("[" + ", ".join("(" + ", ".join(repr(float(v)) for v in p) + ")" for p in row) + "]" for row in value) + "]"
            elif slot.kind == "color":
                expr = "(" + ", ".join(repr(round(float(v), 4)) for v in value) + ")"
            elif slot.kind in ("bool", "enum", "text"):
                expr = json.dumps(value) if slot.kind != "bool" else repr(bool(value))
            elif slot.kind == "select":
                lines.extend(c.recipe(slot.name, "tip"))
                expr = c.selection(slot.name)
            elif slot.kind == "value":
                expr = "[" + ", ".join(c.body_named(n) for n in value) + "]" if slot.many else c.body_named(value)
            else:  # pragma: no cover - every slot kind above
                raise ValueError(slot.kind)
            args.append(f"{slot.name}={expr}")
        call = f"{_call_path(op)}(" + ", ".join(args) + ")"
        lines.append(f"{c.out if c.spec.combinable else c.slug} = {call}")
        return lines

    return build


@lru_cache(maxsize=1)
def operation_specs() -> tuple[Any, ...]:
    """One feature per SDK operation the forms can offer, in catalog order."""
    from . import features

    out = []
    for op in C.operations():
        spec = _spec_for(op, features)
        if spec is not None:
            out.append(spec)
    # Operations that differ only in what they make (loft_rsolid / loft_rshell, make_circle_redge / _rwire / _rface)
    # would read as one: their labels say what each makes.
    count = Counter(spec.label for spec in out)
    return tuple(
        dataclasses.replace(spec, label=f"{spec.label} → {_MAKES.get(spec.produces, spec.produces)}") if count[spec.label] > 1 else spec
        for spec in out
    )


__all__ = ["PREFIX", "operation_specs"]
