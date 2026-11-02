"""The sketch document a 2D canvas edits, the cell code it becomes, and the solve a canvas asks for while a point is dragged.

A document is plain data: a plane, points (their coordinates are solver seeds), entities (line, circle, arc) that name
points, constraints that name entities or points, and which profile of the solved sketch becomes the face::

    {"plane": "XY",
     "points": [{"id": "a", "x": 0, "y": 0}, ...],
     "entities": [{"id": "l0", "kind": "line", "start": "a", "end": "b", "construction": false}, ...],
     "constraints": [{"id": "c1", "kind": "horizontal", "targets": ["l0"]},
                     {"id": "c2", "kind": "length", "targets": ["l0"], "value": 40.0}, ...],
     "profile": 0, "inner": [], "fully_constrained": true}

:func:`validate` checks it (every id that reaches code matches a fixed pattern, every number is finite), :func:`render` writes
the sketch cell (dimensions become ``scad.var`` sliders in the params cell), and :func:`solve` runs the SDK's solver without
recording anything, so a canvas can show the solved geometry, the degrees of freedom and the conflicts at every drag step.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Mapping

_ID = re.compile(r"[a-z][a-z0-9_]{0,30}")
_SUB = ("start", "end", "center")
PLANES = ("XY", "XZ", "YZ")
PLANE_NORMALS = {"XY": "+z", "XZ": "-y", "YZ": "+x"}
ENTITY_KINDS = {"line": ("start", "end"), "circle": ("center",), "arc": ("start", "end", "center")}

# kind -> (target parameter names in the SDK function, unit of its value or None, extra keyword parameters)
CONSTRAINTS: dict[str, tuple[tuple[str, ...], str | None, tuple[str, ...]]] = {
    "fix": (("target",), None, ()),
    "coincident": (("a", "b"), None, ()),
    "point_on": (("point", "entity"), None, ()),
    "horizontal": (("line",), None, ()),
    "vertical": (("line",), None, ()),
    "points_horizontal": (("a", "b"), None, ()),
    "points_vertical": (("a", "b"), None, ()),
    "parallel": (("a", "b"), None, ()),
    "perpendicular": (("a", "b"), None, ()),
    "collinear": (("a", "b"), None, ()),
    "tangent": (("a", "b"), None, ("at_a", "at_b", "mode")),
    "concentric": (("a", "b"), None, ()),
    "midpoint": (("point", "line"), None, ()),
    "symmetric": (("a", "b", "axis"), None, ()),
    "equal_length": (("a", "b"), None, ()),
    "equal_radius": (("a", "b"), None, ()),
    "length": (("line",), "mm", ()),
    "distance": (("a", "b"), "mm", ()),
    "distance_x": (("a", "b"), "mm", ()),
    "distance_y": (("a", "b"), "mm", ()),
    "line_distance": (("a", "b"), "mm", ()),
    "angle": (("a", "b"), "deg", ()),
    "radius": (("circle",), "mm", ()),
    "diameter": (("circle",), "mm", ()),
}
_EXTRA_CHOICES = {"at_a": ("start", "end"), "at_b": ("start", "end"), "mode": ("external", "internal")}


class SketchError(ValueError):
    """A sketch document that cannot be used; the message is meant for the person."""


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SketchError(f"{what}: a number is required")
    return float(value)


def _num(value: float) -> str:
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    return "0.0" if text in ("", "-0") else (text if "." in text else text + ".0")


def _vec3(value: Any, what: str) -> list[float]:
    if not (isinstance(value, (list, tuple)) and len(value) == 3):
        raise SketchError(f"{what}: three numbers")
    return [_number(v, what) for v in value]


def validate_plane(plane: Any) -> Any:
    """A named plane (XY, XZ, YZ) or a frame ``{origin, x_axis, y_axis}`` (unit axes, square to each other)."""
    if isinstance(plane, str):
        if plane not in PLANES:
            raise SketchError(f"the sketch plane must be one of {', '.join(PLANES)}")
        return plane
    if not isinstance(plane, Mapping):
        raise SketchError("the sketch plane is a name or a frame {origin, x_axis, y_axis}")
    origin, x, y = _vec3(plane.get("origin"), "plane origin"), _vec3(plane.get("x_axis"), "plane x axis"), _vec3(plane.get("y_axis"), "plane y axis")
    if any(abs(math.sqrt(sum(v * v for v in axis)) - 1.0) > 1e-6 for axis in (x, y)):
        raise SketchError("the plane axes must be unit vectors")
    if abs(sum(a * b for a, b in zip(x, y))) > 1e-6:
        raise SketchError("the plane x axis and y axis must be square to each other")
    return {"origin": origin, "x_axis": x, "y_axis": y}


def plane_normal(plane: Any) -> list[float]:
    """The normal of a validated plane: x cross y (a named plane has the SDK's own frame)."""
    frames = {"XY": ((1, 0, 0), (0, 1, 0)), "XZ": ((1, 0, 0), (0, 0, 1)), "YZ": ((0, 1, 0), (0, 0, 1))}
    x, y = (frames[plane] if isinstance(plane, str) else (plane["x_axis"], plane["y_axis"]))
    return [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]


def _plane_literal(plane: Any) -> str:
    if isinstance(plane, str):
        return json.dumps(plane)
    parts = ", ".join(f'"{key}": ({", ".join(_num(v) for v in plane[key])})' for key in ("origin", "x_axis", "y_axis"))
    return "{" + parts + "}"


def validate(doc: Mapping[str, Any]) -> dict[str, Any]:
    """The cleaned document, or :class:`SketchError`."""
    plane = validate_plane(doc.get("plane", "XY"))
    points: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    ids: set[str] = set()

    def new_id(raw: Any, what: str) -> str:
        text = str(raw)
        if not _ID.fullmatch(text):
            raise SketchError(f"{what} id {text!r}: lowercase letters, digits and underscores, starting with a letter")
        if text in ids:
            raise SketchError(f"the id {text!r} is used twice")
        ids.add(text)
        return text

    for raw in doc.get("points") or []:
        points.append({"id": new_id(raw.get("id"), "point"), "x": _number(raw.get("x"), "point x"), "y": _number(raw.get("y"), "point y")})
    point_ids = {p["id"] for p in points}
    for raw in doc.get("entities") or []:
        kind = raw.get("kind")
        if kind not in ENTITY_KINDS:
            raise SketchError(f"unknown entity kind {kind!r} (line, circle, arc)")
        entity: dict[str, Any] = {"id": new_id(raw.get("id"), "entity"), "kind": kind, "construction": bool(raw.get("construction", False))}
        for role in ENTITY_KINDS[kind]:
            ref = str(raw.get(role))
            if ref not in point_ids:
                raise SketchError(f"{entity['id']}: {role} {ref!r} is not a point of the sketch")
            entity[role] = ref
        if kind == "circle":
            radius = _number(raw.get("radius"), f"{entity['id']} radius")
            if radius <= 0:
                raise SketchError(f"{entity['id']}: the radius must be greater than zero")
            entity["radius"] = radius
        entities.append(entity)
    entity_ids = {e["id"] for e in entities}
    constraints: list[dict[str, Any]] = []
    used: set[str] = set()
    for number, raw in enumerate(doc.get("constraints") or [], start=1):
        kind = raw.get("kind")
        if kind not in CONSTRAINTS:
            raise SketchError(f"unknown constraint {kind!r}")
        targets_spec, unit, extras = CONSTRAINTS[kind]
        cid = str(raw.get("id") or f"c{number}")
        if not _ID.fullmatch(cid) or cid in used:
            raise SketchError(f"constraint id {cid!r} is invalid or used twice")
        used.add(cid)
        targets = [str(t) for t in raw.get("targets") or []]
        if len(targets) != len(targets_spec):
            raise SketchError(f"{kind} needs {len(targets_spec)} target(s): {', '.join(targets_spec)}")
        for target in targets:
            base, _, sub = target.partition(".")
            if base not in point_ids | entity_ids or (sub and sub not in _SUB):
                raise SketchError(f"{kind}: {target!r} is not a point or entity of the sketch")
        item: dict[str, Any] = {"id": cid, "kind": kind, "targets": targets}
        if unit is not None:
            value = _number(raw.get("value"), f"{kind} value")
            if unit == "mm" and value <= 0 and kind not in ("distance_x", "distance_y"):
                raise SketchError(f"{kind}: the value must be greater than zero")
            item["value"] = value
            item["driving"] = bool(raw.get("driving", True))
        for extra in extras:
            if raw.get(extra) is not None:
                if raw[extra] not in _EXTRA_CHOICES[extra]:
                    raise SketchError(f"{kind}: {extra} must be one of {', '.join(_EXTRA_CHOICES[extra])}")
                item[extra] = raw[extra]
        constraints.append(item)
    profile = raw_profile = doc.get("profile", 0)
    if isinstance(raw_profile, bool) or not isinstance(profile, int) or profile < 0:
        raise SketchError("the profile must be a whole number from zero")
    inner = [int(i) for i in doc.get("inner") or [] if isinstance(i, int) and not isinstance(i, bool) and i >= 0 and i != profile]
    return {
        "plane": plane,
        "points": points,
        "entities": entities,
        "constraints": constraints,
        "profile": profile,
        "inner": inner,
        "fully_constrained": bool(doc.get("fully_constrained", False)),
    }


# ---- code ---------------------------------------------------------------------------------------------------------------------


def _ref(target: str) -> str:
    return json.dumps(target)


def _calls(doc: Mapping[str, Any], *, var_for: Mapping[str, str] | None = None) -> list[str]:
    """The ``_sketch = scad....`` lines that build the sketch of *doc* (dimensions use *var_for* names when given)."""
    lines = []
    for point in doc["points"]:
        lines.append(f'_sketch = scad.add_point_rsketch(sketch=_sketch, point_id={_ref(point["id"])}, x={_num(point["x"])}, y={_num(point["y"])})')
    for entity in doc["entities"]:
        extra = ", construction=True" if entity["construction"] else ""
        if entity["kind"] == "line":
            lines.append(f'_sketch = scad.add_line_rsketch(sketch=_sketch, entity_id={_ref(entity["id"])}, start={_ref(entity["start"])}, end={_ref(entity["end"])}{extra})')
        elif entity["kind"] == "circle":
            lines.append(f'_sketch = scad.add_circle_rsketch(sketch=_sketch, entity_id={_ref(entity["id"])}, center={_ref(entity["center"])}, radius={_num(entity["radius"])}{extra})')
        else:
            lines.append(
                f'_sketch = scad.add_arc_rsketch(sketch=_sketch, entity_id={_ref(entity["id"])}, start={_ref(entity["start"])}, end={_ref(entity["end"])}, center={_ref(entity["center"])}{extra})'
            )
    for constraint in doc["constraints"]:
        names, unit, extras = CONSTRAINTS[constraint["kind"]]
        args = [f"{name}={_ref(target)}" for name, target in zip(names, constraint["targets"])]
        if unit is not None:
            value = (var_for or {}).get(constraint["id"]) or _num(constraint["value"])
            args.append(f"value={value}")
            if not constraint["driving"]:
                args.append("driving=False")
        for extra in extras:
            if extra in constraint:
                args.append(f"{extra}={_ref(constraint[extra])}")
        args.append(f"constraint_id={_ref(constraint['id'])}")
        lines.append(f"_sketch = scad.constrain_{constraint['kind']}_rsketch(sketch=_sketch, {', '.join(args)})")
    return lines


def render(slug: str, doc: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(lines of the params cell body, lines of the feature cell body) for a validated *doc*; the face is bound to *slug*."""
    params: list[str] = []
    var_for: dict[str, str] = {}
    for constraint in doc["constraints"]:
        unit = CONSTRAINTS[constraint["kind"]][1]
        if unit is None or not constraint.get("driving", True):
            continue
        stem = constraint["kind"] + "_" + "_".join(t.replace(".", "_") for t in constraint["targets"])
        name = f"{slug}_{stem}".upper()
        while name in var_for.values():
            name += "_2"
        value = constraint["value"]
        high = 360.0 if unit == "deg" else max(abs(value) * 5, 10.0)
        low = 0.0 if unit == "deg" else (-high if constraint["kind"] in ("distance_x", "distance_y") else 0.1)
        comment = constraint["kind"] + " " + " ".join(constraint["targets"])
        var_name = json.dumps(name.lower())
        step = "1.0" if high - low >= 20 else "0.1"
        params.append(
            f"{name} = scad.var(name={var_name}, default={_num(value)}, unit={json.dumps(unit)}, comment={json.dumps(comment)})"
            f"  # ui: slider({_num(low)}, {_num(high)}, step={step}, label={json.dumps(comment)})"
        )
        var_for[constraint["id"]] = name
    inner = f"[{', '.join(str(i) for i in doc['inner'])}]"
    lines = [
        f"_sketch = scad.make_sketch_rsketch(name={json.dumps(slug)}, plane={_plane_literal(doc['plane'])})",
        *_calls(doc, var_for=var_for),
        f"{slug} = scad.make_face_from_sketch_rface(sketch=_sketch, profile={doc['profile']}, inner_profiles={inner}, require_fully_constrained={bool(doc['fully_constrained'])})",
    ]
    return params, lines


# ---- solve ----------------------------------------------------------------------------------------------------------------


def solve(doc: Mapping[str, Any], *, max_profiles: int = 16) -> dict[str, Any]:
    """Solve *doc* without recording anything: status, degrees of freedom, solved geometry, diagnostics and the profiles.

    Never raises for a sketch that is merely wrong (conflicting, under-constrained): that is the answer.
    """
    import simplecadapi as scad

    clean = validate(doc)
    namespace: dict[str, Any] = {"scad": scad}
    plane = clean["plane"] if isinstance(clean["plane"], str) else {k: tuple(v) for k, v in clean["plane"].items()}
    sketch = scad.make_sketch_rsketch(name="canvas", plane=plane)
    namespace["_sketch"] = sketch
    for line in _calls(clean):
        exec(line, namespace)  # noqa: S102 - generated from validated ids and numbers only
    sketch = namespace["_sketch"]
    result = scad.inspect_sketch_rsketchresult(sketch=sketch, strict=False)
    data = result.to_dict()
    profiles = []
    for index in range(max_profiles):
        try:
            face = scad.make_face_from_sketch_rface(sketch=sketch, profile=index, strict=False)
        except Exception:  # noqa: BLE001 - there is no profile with this index
            break
        center = face.get_center()
        profiles.append({"index": index, "area": face.get_area(), "centroid": [center.x, center.y, center.z]})
    return {
        "status": data.get("status"),
        "dof": data.get("dof"),
        "residual": data.get("residual_norm"),
        "points": data.get("solved_points") or {},
        "scalars": data.get("solved_scalars") or {},
        "entities": data.get("solved_entities") or {},
        "diagnostics": data.get("diagnostics") or [],
        "profiles": profiles,
    }


__all__ = ["CONSTRAINTS", "ENTITY_KINDS", "PLANES", "PLANE_NORMALS", "SketchError", "plane_normal", "render", "solve", "validate", "validate_plane"]
