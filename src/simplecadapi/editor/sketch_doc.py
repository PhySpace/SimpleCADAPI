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
ENTITY_KINDS = {"line": ("start", "end"), "circle": ("center",), "arc": ("start", "end", "center"), "bspline": ("start", "end")}
"""A B-spline also lists its ``control_points`` (point ids, the first and the last are its start and end) and a ``degree``, and,
when they are not the uniform clamped ones (a trimmed or extended B-spline), its distinct ``knots`` and their ``multiplicities``."""
_MAX_DEGREE = 5

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
            raise SketchError(f"unknown entity kind {kind!r} (line, circle, arc, bspline)")
        entity: dict[str, Any] = {"id": new_id(raw.get("id"), "entity"), "kind": kind, "construction": bool(raw.get("construction", False))}
        for role in ENTITY_KINDS[kind]:
            ref = str(raw.get(role))
            if ref not in point_ids:
                raise SketchError(f"{entity['id']}: {role} {ref!r} is not a point of the sketch")
            entity[role] = ref
        if kind == "bspline":
            poles = [str(p) for p in raw.get("control_points") or []]
            missing = [p for p in poles if p not in point_ids]
            if missing:
                raise SketchError(f"{entity['id']}: control point {missing[0]!r} is not a point of the sketch")
            degree = raw.get("degree", 3)
            if isinstance(degree, bool) or not isinstance(degree, int) or not 1 <= degree <= _MAX_DEGREE:
                raise SketchError(f"{entity['id']}: the degree is a whole number from 1 to {_MAX_DEGREE}")
            if len(poles) < degree + 1:
                raise SketchError(f"{entity['id']}: a degree {degree} B-spline needs at least {degree + 1} control points")
            if poles[0] != entity["start"] or poles[-1] != entity["end"]:
                raise SketchError(f"{entity['id']}: the first and the last control points are its start and end")
            entity["control_points"] = poles
            entity["degree"] = degree
            knots = _knot_vector(raw, len(poles), degree, entity["id"])
            if knots is not None:
                entity["knots"], entity["multiplicities"] = knots
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


def _uniform_knots(count: int, degree: int) -> tuple[list[float], list[int]]:
    """The knots ``add_bspline_rsketch`` gives *count* control points when it is given none (uniform, clamped)."""
    spans = count - degree
    return [i / spans for i in range(spans + 1)], [degree + 1] + [1] * (spans - 1) + [degree + 1]


def _same_knots(a: tuple[list[float], list[int]], b: tuple[list[float], list[int]]) -> bool:
    return a[1] == b[1] and len(a[0]) == len(b[0]) and all(abs(x - y) <= 1e-12 for x, y in zip(a[0], b[0]))


def _knot_vector(raw: Mapping[str, Any], count: int, degree: int, eid: str) -> tuple[list[float], list[int]] | None:
    """The validated ``knots`` / ``multiplicities`` of a document B-spline, or None when it has none (the uniform ones)."""
    if raw.get("knots") is None and raw.get("multiplicities") is None:
        return None
    knots, mults = raw.get("knots"), raw.get("multiplicities")
    if not isinstance(knots, (list, tuple)) or not isinstance(mults, (list, tuple)) or len(knots) != len(mults) or len(knots) < 2:
        raise SketchError(f"{eid}: knots and multiplicities are two lists of the same length (two or more)")
    values = [_number(k, f"{eid} knot") for k in knots]
    if any(b <= a for a, b in zip(values, values[1:])):
        raise SketchError(f"{eid}: the knots must increase")
    if any(isinstance(m, bool) or not isinstance(m, int) or not 1 <= m <= degree + 1 for m in mults):
        raise SketchError(f"{eid}: a multiplicity is a whole number from 1 to {degree + 1}")
    if sum(mults) != count + degree + 1:
        raise SketchError(f"{eid}: the multiplicities must add up to {count + degree + 1} ({count} control points, degree {degree})")
    return values, [int(m) for m in mults]


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
        elif entity["kind"] == "bspline":
            poles = ", ".join(_ref(p) for p in entity["control_points"])
            if entity.get("knots") is not None:  # repr keeps every digit of a knot (they are validated finite floats)
                extra = f', knots=[{", ".join(repr(float(k)) for k in entity["knots"])}], multiplicities={[int(m) for m in entity["multiplicities"]]}' + extra
            lines.append(
                f'_sketch = scad.add_bspline_rsketch(sketch=_sketch, entity_id={_ref(entity["id"])}, start={_ref(entity["start"])}, end={_ref(entity["end"])}, '
                f'control_points=[{poles}], degree={entity["degree"]}{extra})'
            )
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


def solve(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Solve *doc* without recording anything: status, degrees of freedom, solved geometry, diagnostics and the profiles
    (the SDK's own list, ``inspect_sketch_rsketchprofiles``: the same indices ``make_face_from_sketch_rface`` takes).

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
    listed = scad.inspect_sketch_rsketchprofiles(sketch=sketch, strict=False)
    curves = _bspline_samples(data.get("solved_entities") or {})
    crossings = scad.inspect_sketch_rsketchcrossings(sketch=sketch)
    return {
        "status": data.get("status"),
        "dof": data.get("dof"),
        "residual": data.get("residual_norm"),
        "points": data.get("solved_points") or {},
        "scalars": data.get("solved_scalars") or {},
        "entities": data.get("solved_entities") or {},
        "diagnostics": data.get("diagnostics") or [],
        "profiles": listed["profiles"],
        "unusable": listed["unusable"],
        "crossings": crossings,
        "curves": curves,
    }


def _bspline_samples(solved: Mapping[str, Any], count: int = 64) -> dict[str, Any]:
    """Each solved B-spline drawn and combed by the SDK: ``{id: {points: [[u, v]...], normals, curvatures}}`` in sketch coordinates."""
    import simplecadapi as scad

    out: dict[str, Any] = {}
    for entity_id, item in solved.items():
        if not isinstance(item, Mapping) or item.get("kind") != "bspline":
            continue
        try:
            edge = scad.make_spline_redge(
                control_points=[(float(x), float(y), 0.0) for x, y in item["control_points"]],
                degree=int(item["degree"]),
                knots=item.get("knots"),
                multiplicities=item.get("multiplicities"),
                weights=item.get("weights"),
                periodic=bool(item.get("periodic")),
            )
            comb = scad.sample_curve_rcurvature(edge=edge, count=count)
        except Exception:  # noqa: BLE001 - a curve the kernel cannot build is drawn by its control polygon
            continue
        out[entity_id] = {
            "points": [[p[0], p[1]] for p in comb["points"]],
            "normals": [[n[0], n[1]] for n in comb["normals"]],
            "curvatures": list(comb["curvatures"]),
        }
    return out


# ---- the SDK's sketch edit operations, through the document ----------------------------------------------------------------------
#
# The capabilities (solve, trim, extend, ...) are SDK operations an agent calls in code (``scad.trim_rsketch``); the document is
# only how a GUI holds a sketch.  These adapters turn a document into an SDK ``Sketch``, call the operation by its SDK name and
# turn the result back into a document: there is no geometry here.

EDIT_OPERATIONS = frozenset({"trim", "extend", "fillet_corner", "chamfer_corner", "project"})  # the SDK's ``<name>_rsketch`` functions that edit a sketch (add more as the SDK gains them)


def to_sketch(doc: Mapping[str, Any]) -> Any:
    """The SDK ``Sketch`` that the validated document *doc* builds (the same calls the cell makes)."""
    import simplecadapi as scad

    clean = validate(doc)
    plane = clean["plane"] if isinstance(clean["plane"], str) else {k: tuple(v) for k, v in clean["plane"].items()}
    namespace: dict[str, Any] = {"scad": scad, "_sketch": scad.make_sketch_rsketch(name="canvas", plane=plane)}
    for line in _calls(clean):
        exec(line, namespace)  # noqa: S102 - generated from validated ids and numbers only
    return namespace["_sketch"]


def _target(item: Mapping[str, Any]) -> str:
    sub = item.get("subentity")
    return f"{item['entity_id']}.{sub}" if sub in _SUB else str(item["entity_id"])


def from_sketch(sketch: Any, like: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The document of an SDK ``Sketch`` (the plane, profile choice and constrained flag are taken from *like*)."""
    data = sketch.to_dict()
    points: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    for item in data["entities"]:
        if item["kind"] == "point":
            points.append({"id": item["id"], "x": float(item["x"]), "y": float(item["y"])})
            continue
        if item["kind"] not in ENTITY_KINDS:
            raise SketchError(f"the sketch has a {item['kind']} ({item['id']}), which the document cannot hold")
        entity: dict[str, Any] = {"id": item["id"], "kind": item["kind"], "construction": bool(item.get("construction", False))}
        for role in ENTITY_KINDS[item["kind"]]:
            entity[role] = item[role]
        if item["kind"] == "circle":
            entity["radius"] = float(item["radius"])
        if item["kind"] == "bspline":
            refs = [c.get("point_id") if isinstance(c, Mapping) else None for c in item.get("control_points") or []]
            if None in refs or item.get("weights") or item.get("periodic"):
                raise SketchError(f"{item['id']}: a B-spline with literal, weighted or periodic control points is code, not a document")
            entity["control_points"] = refs
            entity["degree"] = int(item["degree"])
            knots = [float(k) for k in item.get("knots") or []]
            mults = [int(m) for m in item.get("multiplicities") or []]
            if not _same_knots((knots, mults), _uniform_knots(len(refs), entity["degree"])):
                entity["knots"], entity["multiplicities"] = knots, mults
        entities.append(entity)
    constraints: list[dict[str, Any]] = []
    for item in data["constraints"]:
        if item["kind"] not in CONSTRAINTS:
            raise SketchError(f"the sketch has a {item['kind']} constraint ({item['id']}), which the document cannot hold")
        constraint: dict[str, Any] = {"id": item["id"], "kind": item["kind"], "targets": [_target(t) for t in item["targets"]]}
        if item.get("value") is not None:
            constraint["value"] = float(item["value"])
            constraint["driving"] = bool(item.get("driving", True))
        meta = {**(item.get("metadata") or {}), **item}
        for extra in CONSTRAINTS[item["kind"]][2]:
            if meta.get(extra) is not None:
                constraint[extra] = meta[extra]
        constraints.append(constraint)
    base = like or {}
    return validate(
        {
            "plane": base.get("plane", "XY"),
            "points": points,
            "entities": entities,
            "constraints": constraints,
            "profile": 0,
            "inner": [],
            "fully_constrained": base.get("fully_constrained", False),
        }
    )


def apply_edit(doc: Mapping[str, Any], operation: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Run the SDK edit ``<operation>_rsketch`` on the sketch of *doc*; returns ``{sketch, created, removed, ...}``.

    ``created``/``removed``/``changed`` are the SDK's own ``diff_sketch_rsketchdiff``; ``notes`` are the operation's.
    """
    import simplecadapi as scad

    if operation not in EDIT_OPERATIONS:
        raise SketchError(f"unknown sketch operation {operation!r} (known: {', '.join(sorted(EDIT_OPERATIONS))})")
    kwargs = dict(args)
    if "at" in kwargs and isinstance(kwargs["at"], (list, tuple)):
        kwargs["at"] = tuple(kwargs["at"])
    if "source_doc" in kwargs:  # project_rsketch takes another sketch: the caller sends its document
        kwargs["source"] = to_sketch(kwargs.pop("source_doc"))
    before = to_sketch(doc)
    try:
        after = getattr(scad, f"{operation}_rsketch")(sketch=before, **kwargs)
    except (ValueError, TypeError) as exc:  # the SDK's errors name the ids involved
        raise SketchError(_short(exc)) from exc
    clean = validate(doc)
    return {
        "sketch": from_sketch(after, clean),
        **scad.diff_sketch_rsketchdiff(before=before, after=after),
        "notes": list((after.get_metadata("last_edit") or {}).get("notes", [])),
    }


def _short(error: Exception) -> str:
    """The part of an SDK error a person reads: the technical details line, else the first line."""
    text = str(error)
    for line in text.splitlines():
        if line.startswith("Technical details:"):
            return line.split(":", 2)[-1].strip()
    return text.splitlines()[0] if text else type(error).__name__


__all__ = [
    "EDIT_OPERATIONS",
    "apply_edit",
    "from_sketch",
    "to_sketch",
"CONSTRAINTS", "ENTITY_KINDS", "PLANES", "PLANE_NORMALS", "SketchError", "plane_normal", "render", "solve", "validate", "validate_plane"]
