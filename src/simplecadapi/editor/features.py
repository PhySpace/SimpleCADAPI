"""GUI-made features: the operations a person can add with a button, and the cells they become.

A feature is an ordinary notebook cell (``# ---- feature: <slug> (<role>) ----``, one operation that makes one new public
name) with its numbers in a ``# ---- params: <slug> ----`` cell, so a person or an agent can read and edit it like any
other cell.  A cell made here carries one more line, ``# gui: {...}``, from which the form is rebuilt; a cell without that
line is code, shown in the tree and never rewritten.

Nothing in this module runs a kernel or touches a file.  :func:`render_feature` turns validated values into source text;
every value that reaches the text is a number, a choice from a fixed list, a name from the notebook, or a tag built from
the slug, so a request cannot put code into a cell.

Selections are written as stable references, one statement per selection slot::

    _edges = scad.ref.edges(scad.ref.edge("base", "make_box_rsolid", between=("box.front", "box.top"), guard=(...)))

The server names each picked entity in the kernel (:func:`simplecadapi.ref.of`, through
:mod:`simplecadapi.runtime.live_refs`); this module only writes the references it is given and reads them back
(:func:`extract_refs`, :func:`replace_refs`).  A reference that splits or is lost is an error on the feature that lists
the candidates, never another face.  An item that could not be named (a body without recorded history) falls back to
the older *recipe*: the face tags first, the picked geometry second, the count checked.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import json
import keyword
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .. import ref as _ref
from . import assembly_doc, sketch_doc
from .selection import selector_conditions

GUI_MARKER = "# gui:"
VERSION = 1
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,40}")
_TAG = re.compile(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)+")
_RESERVED = frozenset(keyword.kwlist) | frozenset(dir(builtins)) | {"scad", "app", "marimo"}
_AXES = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}
_AXIS_OPTIONS = [{"value": key, "label": key} for key in _AXES]
_DIR_OPTIONS = [
    *({"value": key, "label": key} for key in _AXES),
    {"value": "normal", "label": "normal of the sketch plane"},
    {"value": "-normal", "label": "against the normal of the sketch plane"},
]
_PLANE_NORMALS = {"XY": (0.0, 0.0, 1.0), "XZ": (0.0, 1.0, 0.0), "YZ": (1.0, 0.0, 0.0)}


class FeatureError(ValueError):
    """A request the registry cannot turn into a feature; the message is meant for the person."""


@dataclass(frozen=True)
class Slot:
    """One input of a feature.

    kind: ``length`` (mm), ``angle`` (deg), ``float``, ``count``, ``bool``, ``enum``, ``point`` (three lengths),
    ``body`` (a solid made earlier), ``profile`` (a sketch face made earlier), ``select`` (faces or edges picked in the
    viewport), ``points2d`` (``x, y`` per line), ``sketch`` (a sketch document, see :mod:`.sketch_doc`), ``assembly`` (an
    assembly document, see :mod:`.assembly_doc`), ``color`` (a display colour, RGB in [0, 1]).
    """

    name: str
    label: str
    kind: str
    default: Any = None
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[dict[str, str]] | None = None
    entity: str | None = None  # face | edge, for kind == "select"
    help: str = ""
    optional: bool = False
    single: bool = False  # a selection slot that takes exactly one item
    accepts: tuple[str, ...] | None = None  # kind == "value": the kinds of named values that fit (solid, wire, face ...)
    many: bool = False  # kind == "value": a list of them
    show_when: dict[str, list[str]] | None = None  # the slot is shown (and used) only when another slot has one of these values

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "label": self.label, "kind": self.kind}
        for key in ("default", "unit", "min", "max", "step", "options", "entity"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.help:
            out["help"] = self.help
        if self.optional:
            out["optional"] = True
        if self.single:
            out["single"] = True
        if self.accepts:
            out["accepts"] = list(self.accepts)
        if self.many:
            out["many"] = True
        if self.show_when:
            out["show_when"] = self.show_when
        return out


@dataclass(frozen=True)
class Spec:
    id: str
    label: str
    group: str
    role: str  # build | add | subtract | modifier
    produces: str  # solid | solids | face | assembly
    description: str
    slots: tuple[Slot, ...]
    build: Callable[["Context"], list[str]] = field(repr=False, compare=False)
    combinable: bool = False  # makes a new solid that is joined to, cut from or intersected with the body so far (see _with_combine)
    body_slot: str = "body"  # the slot naming the body a selection recipe resolves against
    operation: str | None = None  # the SDK operation it calls, for the forms made from the catalog (op_specs.py)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "role": self.role,
            "produces": self.produces,
            "description": self.description,
            "slots": [slot.to_dict() for slot in self.slots],
            **({"combinable": True} if self.combinable else {}),
            **({"operation": self.operation} if self.operation else {}),
        }


@dataclass
class Rendered:
    slug: str
    spec: str
    params: list[str]  # lines of the params cell ("" when the feature has no numbers)
    feature: str  # the feature cell
    before: list[str]  # cells that go between the params cell and the feature cell (an assembly's child uses)
    reads: list[str]  # bodies this feature consumes
    produces: str
    gui: dict[str, Any]


class Context:
    """What a template needs: the slug, the variable of each number, the bodies, the selection recipes."""

    def __init__(self, spec: Spec, slug: str, values: Mapping[str, Any], bodies: Mapping[str, str], recipes: Mapping[str, list[str]], env: Mapping[str, Any] | None = None):
        self.spec, self.slug, self.values = spec, slug, values
        self._bodies, self._recipes = bodies, recipes
        self.env = dict(env or {})
        self.before: list[str] = []
        self.params: list[str] = []
        self.reads: list[str] = []
        self._base = slug.upper()
        self.used: set[str] = set()

    # -- numbers --------------------------------------------------------------------------------------------------
    def var(self, slot: str) -> str:
        """The params-cell variable holding this number (written on first use)."""
        spec = self._slot(slot)
        name = f"{self._base}_{slot.upper()}"
        if name in self.used:
            return name
        self.used.add(name)
        value = self.values[slot]
        comment = spec.label
        if spec.kind == "bool":
            self.params.append(f"{name} = {bool(value)}  # ui: toggle()")
        elif spec.kind == "count":
            low, high = _count_range(spec, int(value))
            self.params.append(f"{name} = {int(value)}  # ui: number({low}, {high}, step=1, label={json.dumps(comment)})")
        elif spec.kind == "float":
            low, high = _range(spec, float(value))
            self.params.append(f"{name} = {_num(float(value))}  # ui: number({_num(low)}, {_num(high)}, step={_num(_step(spec, low, high))}, label={json.dumps(comment)})")
        else:
            unit = "deg" if spec.kind == "angle" else "mm"
            low, high = _range(spec, float(value))
            var_name = f"{self.slug}_{slot}"
            self.params.append(
                f"{name} = scad.var(name={json.dumps(var_name)}, default={_num(float(value))}, unit={json.dumps(unit)}, "
                f"comment={json.dumps(comment)})  # ui: slider({_num(low)}, {_num(high)}, step={_num(_step(spec, low, high))}, label={json.dumps(comment)})"
            )
        return name

    def point(self, slot: str) -> str:
        """A ``(x, y, z)`` expression from the three length variables of a point slot."""
        spec = self._slot(slot)
        names = []
        for axis, value in zip("xyz", self.values[slot]):
            name = f"{self._base}_{slot.upper()}_{axis.upper()}"
            if name not in self.used:
                self.used.add(name)
                if spec.unit is None:  # a direction: plain numbers (its length does not matter, it has no unit)
                    self.params.append(f"{name} = {_num(float(value))}  # ui: number(-1, 1, step=0.1, label={json.dumps(f'{spec.label} {axis}')})")
                else:
                    low, high = _range(spec, float(value))
                    self.params.append(
                        f"{name} = scad.var(name={json.dumps(f'{self.slug}_{slot}_{axis}')}, default={_num(float(value))}, unit=\"mm\", "
                        f"comment={json.dumps(f'{spec.label} {axis}')})  # ui: slider({_num(low)}, {_num(high)}, step=1, label={json.dumps(f'{spec.label} {axis}')})"
                    )
            names.append(name)
        return f"({', '.join(names)})"

    @property
    def out(self) -> str:
        """What the template assigns its solid to: the feature's name, or a private tool when it is combined with a body."""
        if self.spec.combinable and self.values.get("operation", "new") != "new":
            return "_tool"
        return self.slug

    def raw_params(self, lines: list[str]) -> None:
        """Params-cell lines a template writes itself (the dimensions of a sketch)."""
        self.params.extend(lines)

    def choice(self, slot: str) -> str:
        """The value of an enum slot (already checked against its options)."""
        return str(self.values[slot])

    def axis(self, slot: str) -> str:
        value = str(self.values[slot])
        if value in ("normal", "-normal"):  # the normal of the sketch plane the profile was drawn on, or its opposite
            vector = (self.env.get("profile_normals") or {}).get(str(self.values.get("profile")))
            if vector is None:
                raise FeatureError(f"the direction {value!r} needs a sketch profile")
            sign = -1.0 if value == "-normal" else 1.0
            return repr(tuple(round(sign * v, 9) + 0.0 for v in vector))
        return repr(_AXES[value])

    def normal(self, slot: str) -> str:
        return repr(_PLANE_NORMALS[str(self.values[slot])])

    # -- bodies and selections ------------------------------------------------------------------------------------
    def body(self, slot: str) -> str:
        name = str(self.values[slot])
        if name not in self.reads:
            self.reads.append(name)
        return name

    def body_named(self, name: str) -> str:
        """A named value the feature reads (a value slot's choice)."""
        if name not in self.reads:
            self.reads.append(name)
        return name

    def spread(self, slot: str) -> str:
        """``*name`` when the body slot names a list of solids, else ``name``."""
        name = self.body(slot)
        return f"*{name}" if self._bodies.get(name) == "solids" else name

    def selection(self, slot: str) -> str:
        """The variable the recipe of this selection slot binds (the recipe is added to the cell first)."""
        return f"_{slot}"

    def recipe(self, slot: str, tip: str) -> list[str]:
        return list(self._recipes[slot])

    def _slot(self, name: str) -> Slot:
        for slot in self.spec.slots:
            if slot.name == name:
                return slot
        raise KeyError(name)

    def tag(self, role: str) -> str:
        """A readable face tag for this feature, e.g. ``base.top`` (survives booleans, not fillets)."""
        return json.dumps(f"{self.slug}.{role}")


# ---- helpers ------------------------------------------------------------------------------------------------------


def _num(value: float) -> str:
    text = f"{value:.6g}"
    if "e" in text or "E" in text:
        text = f"{value:.9f}".rstrip("0").rstrip(".")
    if "." not in text and "e" not in text:
        text += ".0"
    return "0.0" if text in ("-0.0", "") else text


def _range(spec: Slot, value: float) -> tuple[float, float]:
    """Slider limits for a number: from the slot, else around the value."""
    if spec.min is None:
        low, high = 0.1, max(value * 5, 10.0)
    elif spec.min <= -1000:  # a coordinate or a signed distance: a window around the value
        low, high = math.floor(value - 100), math.ceil(value + 100)
    else:
        low = spec.min
        high = spec.max if spec.max is not None else max(value * 5, low + 10.0)
    if spec.max is not None and spec.min is not None and spec.min > -1000:
        high = spec.max
    if spec.kind == "angle" and spec.max is None:
        high = 360.0
    return (low, high) if low < high else (low, low + 1.0)


def _count_range(spec: Slot, value: int) -> tuple[int, int]:
    low = int(spec.min) if spec.min is not None else 1
    high = int(spec.max) if spec.max is not None else max(value * 4, 10)
    return low, max(high, low + 1)


def _step(spec: Slot, low: float, high: float) -> float:
    if spec.step is not None:
        return spec.step
    return 1.0 if high - low >= 20 else 0.1


def _checked_number(slot: Slot, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise FeatureError(f"{slot.label}: a number is required")
    number = float(value)
    if slot.kind == "length" and slot.min is None and number <= 0:
        raise FeatureError(f"{slot.label}: must be greater than zero")
    if slot.min is not None and number < slot.min:
        raise FeatureError(f"{slot.label}: must be at least {slot.min:g}")
    if slot.max is not None and number > slot.max:
        raise FeatureError(f"{slot.label}: must be at most {slot.max:g}")
    return number


def _length(name: str, label: str, default: float, **kw: Any) -> Slot:
    return Slot(name, label, "length", default=default, unit="mm", **kw)


def _signed(name: str, label: str, default: float, **kw: Any) -> Slot:
    return Slot(name, label, "length", default=default, unit="mm", min=kw.pop("min", -10000.0), **kw)


def _point(name: str, label: str, default: tuple[float, float, float] = (0.0, 0.0, 0.0), help: str = "") -> Slot:
    return Slot(name, label, "point", default=list(default), unit="mm", min=-10000.0, help=help)


def _enum(name: str, label: str, options: list[dict[str, str]], default: str, help: str = "") -> Slot:
    return Slot(name, label, "enum", default=default, options=options, help=help)


def _body(name: str, label: str, help: str = "") -> Slot:
    return Slot(name, label, "body", help=help)


# ---- templates ----------------------------------------------------------------------------------------------------


def _box(c: Context) -> list[str]:
    return [
        f"{c.out} = scad.make_box_rsolid(",
        f"    width={c.var('width')}, height={c.var('height')}, depth={c.var('depth')},",
        f"    bottom_face_center={c.point('origin')},",
        f"    bottom_face_tag={c.tag('bottom')}, top_face_tag={c.tag('top')},",
        f"    front_face_tag={c.tag('front')}, back_face_tag={c.tag('back')},",
        f"    left_face_tag={c.tag('left')}, right_face_tag={c.tag('right')},",
        ")",
    ]


def _cylinder(c: Context) -> list[str]:
    return [
        f"{c.out} = scad.make_cylinder_rsolid(",
        f"    radius={c.var('radius')}, height={c.var('height')},",
        f"    bottom_face_center={c.point('origin')}, axis={c.axis('axis')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_face_tag={c.tag('side')},",
        ")",
    ]


def _sphere(c: Context) -> list[str]:
    return [f"{c.out} = scad.make_sphere_rsolid(radius={c.var('radius')}, center={c.point('center')})"]


def _cone(c: Context) -> list[str]:
    return [
        f"{c.out} = scad.make_cone_rsolid(",
        f"    bottom_radius={c.var('bottom_radius')}, top_radius={c.var('top_radius')}, height={c.var('height')},",
        f"    bottom_face_center={c.point('origin')}, axis={c.axis('axis')},",
        # a true cone has no top face to name; the tag is written only when there is one
        f"    start_face_tag={c.tag('start')}, " + (f"end_face_tag={c.tag('end')}, " if c.values["top_radius"] > 0 else "") + f"side_face_tag={c.tag('side')},",
        ")",
    ]










def _sketch(c: Context) -> list[str]:
    params, lines = sketch_doc.render(c.slug, c.values["sketch"])
    c.raw_params(params)
    workplane = sketch_doc.plane_workplane(c.values["sketch"]["plane"])
    if workplane is not None:
        c.body_named(workplane)  # drawn on a workplane variable of the notebook
    return lines


def _assembly(c: Context) -> list[str]:
    cells = assembly_doc.render(c.slug, str(c.env.get("name") or c.slug), c.values["assembly"], c.env.get("notebook_dir"), c.env.get("workspace"))
    c.raw_params(cells["params"])
    if cells["uses"]:
        c.before.append("\n".join([f"# ---- feature: {c.slug}_parts (add) ----", *cells["uses"]]))
    return cells["layout"]


def _profile(c: Context, slot: str = "profile") -> str:
    return c.body(slot)


def _extrude_sketch(c: Context) -> list[str]:
    return [
        f"{c.out} = scad.extrude_rsolid(profile={_profile(c)}, direction={c.axis('direction')}, distance={c.var('distance')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')})",
    ]


def _revolve_sketch(c: Context) -> list[str]:
    return [
        f"{c.out} = scad.revolve_rsolid(profile={_profile(c)}, axis={c.axis('axis')}, angle={c.var('angle')}, origin={c.point('origin')},",
        "    " + (f"start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, " if c.values["angle"] < 360 else "") + f"side_faces_tag={c.tag('side')})",
    ]


def _cut_sketch(c: Context) -> list[str]:
    return [
        f"_tool = scad.extrude_rsolid(profile={_profile(c)}, direction={c.axis('direction')}, distance={c.var('depth')})",
        f"{c.slug} = scad.cut_rsolid({c.body('body')}, _tool, skip_non_intersecting=False)",
    ]


def _boss_sketch(c: Context) -> list[str]:
    return [
        f"_boss = scad.extrude_rsolid(profile={_profile(c)}, direction={c.axis('direction')}, distance={c.var('distance')})",
        f"{c.slug} = scad.union_rsolid({c.body('body')}, _boss)",
    ]


def _cut(c: Context) -> list[str]:
    return [f"{c.slug} = scad.cut_rsolid({c.body('base')}, {c.spread('tool')}, skip_non_intersecting=False)"]


def _union(c: Context) -> list[str]:
    return [f"{c.slug} = scad.union_rsolid({c.body('base')}, {c.spread('other')})"]


def _intersect(c: Context) -> list[str]:
    return [f"{c.slug} = scad.intersect_rsolid({c.body('base')}, {c.spread('other')})"]


_HOLE_DIRECTIONS = [
    *_AXIS_OPTIONS,
    {"value": "face", "label": "along the picked face's normal"},
    {"value": "vector", "label": "a free vector"},
]
_HOLE_VECTOR = {"direction": ["face", "vector"]}


def _hole_direction(c: Context) -> str:
    """The drilling direction: one of the axes, or the unit vector of (dx, dy, dz) (a face normal or a free vector)."""
    if str(c.values["direction"]) in _AXES:
        return c.axis("direction")
    vector = [float(c.values[name]) for name in ("dx", "dy", "dz")]
    length = sum(v * v for v in vector) ** 0.5
    if length < 1e-9:
        raise FeatureError("the direction vector must not be zero")
    return repr(tuple(round(v / length, 9) + 0.0 for v in vector))


def _hole(c: Context) -> list[str]:
    direction = _hole_direction(c)
    return [
        "# a cylinder from just outside the surface, in the drilling direction, taken out of the body",
        f"_dir = {direction}",
        "_overshoot = 1.0",
        f"_start = tuple(_p - _overshoot * _d for _p, _d in zip({c.point('position')}, _dir))",
        f"_tool = scad.make_cylinder_rsolid(radius={c.var('diameter')} / 2, height={c.var('depth')} + _overshoot, bottom_face_center=_start, axis=_dir)",
        f"{c.slug} = scad.cut_rsolid({c.body('body')}, _tool, skip_non_intersecting=False)",
    ]


_FACE_DIRECTIONS = [
    {"value": "normal", "label": "out of the face (its normal)"},
    {"value": "-normal", "label": "into the body (against the normal)"},
    *_AXIS_OPTIONS,
]


def _extrude_face(c: Context) -> list[str]:
    """Push a picked planar face of a body out (or in) along its normal: no sketch in between."""
    direction = str(c.values["direction"])
    if direction in _AXES:
        vector = c.axis("direction")
    else:
        sign = "-" if direction == "-normal" else ""
        vector = f"({sign}_normal.x, {sign}_normal.y, {sign}_normal.z)"
    return [
        *c.recipe("face", "tip"),
        "_face = _face_query.resolve({BODY})[0]".replace("_face_query", c.selection("face")),
        "_normal = _face.get_normal_at()",
        f"{c.out} = scad.extrude_rsolid(profile=_face, direction={vector}, distance={c.var('distance')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')})",
    ]


def _fillet(c: Context) -> list[str]:
    return [*c.recipe("edges", "tip"), f"{c.slug} = scad.fillet_rsolid(solid={c.body('body')}, edges={c.selection('edges')}, radius={c.var('radius')})"]


def _chamfer(c: Context) -> list[str]:
    return [*c.recipe("edges", "tip"), f"{c.slug} = scad.chamfer_rsolid(solid={c.body('body')}, edges={c.selection('edges')}, distance={c.var('distance')})"]


def _shell(c: Context) -> list[str]:
    return [
        *c.recipe("faces", "tip"),
        f"{c.slug} = scad.shell_rsolid(solid={c.body('body')}, faces_to_remove={c.selection('faces')}, thickness={c.var('thickness')})",
    ]


def _linear_pattern(c: Context) -> list[str]:
    return [
        f"{c.slug} = scad.linear_pattern_rsolidlist(shape={c.body('shape')}, direction={c.axis('direction')}, count={c.var('count')}, spacing={c.var('spacing')})"
    ]


def _radial_pattern(c: Context) -> list[str]:
    return [
        f"{c.slug} = scad.radial_pattern_rsolidlist(shape={c.body('shape')}, center={c.point('center')}, axis={c.axis('axis')},",
        f"    count={c.var('count')}, total_rotation_angle={c.var('total_angle')})",
    ]


def _mirror(c: Context) -> list[str]:
    return [
        f"_mirrored = scad.mirror_shape(shape={c.body('body')}, plane_origin={c.point('origin')}, plane_normal={c.axis('normal')})",
        f"{c.slug} = scad.union_rsolid({c.body('body')}, _mirrored)" if c.values.get("merge") else f"{c.slug} = _mirrored",
    ]


def _translate(c: Context) -> list[str]:
    return [f"{c.slug} = scad.translate_shape(shape={c.body('body')}, vector={c.point('offset')})"]


def _rotate(c: Context) -> list[str]:
    return [
        f"{c.slug} = scad.rotate_shape(shape={c.body('body')}, angle={c.var('angle')}, axis={c.axis('axis')}, origin={c.point('origin')})"
    ]


def _scale(c: Context) -> list[str]:
    factor = c.var("factor")
    return [f"{c.slug} = scad.scale_rsolid(solid={c.body('body')}, factors=({factor}, {factor}, {factor}), center={c.point('origin')})"]


_WORKPLANE_METHODS = [
    {"value": "face", "label": "on a face"},
    {"value": "face_edge", "label": "on a face, x along an edge"},
    {"value": "midplane", "label": "halfway between two parallel faces"},
    {"value": "points", "label": "through three vertices"},
    {"value": "axis", "label": "through an edge, turned about it"},
    {"value": "offset", "label": "moved and turned from a plane, a workplane or a face"},
]
_NAMED_PLANES = ("XY", "XZ", "YZ")
_OFFSET = {"method": ["offset"]}
_ON_FACE = {"method": ["face", "face_edge"]}


def _workplane(c: Context) -> list[str]:
    """A workplane from picked geometry: one recorded SDK constructor per way of picking (see make_workplane_*), or one
    placed by hand on a plane, a workplane or a face (``make_workplane_offset_rworkplane``: the editor's handles)."""
    method = c.choice("method")
    base = str(c.values.get("base") or "XY")
    if method != "offset" or base == "face":
        if not c.values.get("body"):
            raise FeatureError("this workplane is made from the model's geometry: there is no body yet")
        c.body("body")
    lines: list[str] = []

    def pick(slot: str) -> str:
        lines.extend(c.recipe(slot, "tip"))
        name = c.selection(slot)
        lines.append(f"{name} = {name}.resolve({{BODY}})[0]")
        return name

    if method == "offset":
        if base in _NAMED_PLANES:
            on = repr(base)
        elif base == "face":
            # the face's frame with the x direction the handles were drawn with, so the plane made is the one shown
            x_dir = f", x_dir={c.point('x_dir')}" if c.values.get("x_dir") else ""
            on = f"scad.make_workplane_from_face_rworkplane({pick('face')}{x_dir})"
        elif _NAME.fullmatch(base):
            on = c.body_named(base)
        else:
            raise FeatureError(f"Base: {base!r} is not XY, XZ, YZ, a picked face or a workplane of this notebook")
        call = (f"scad.make_workplane_offset_rworkplane({on}, offset={c.point('move')}, "
                f"rx={c.var('rx')}, ry={c.var('ry')}, rz={c.var('rz')})")
    elif method in ("face", "face_edge"):
        face = pick("face")
        x_edge = f", x_edge={pick('edge')}" if method == "face_edge" else ""
        call = f"scad.make_workplane_from_face_rworkplane({face}{x_edge}, offset={c.var('offset')}, flip={c.var('flip')})"
    elif method == "midplane":
        call = f"scad.make_workplane_midplane_rworkplane({pick('face')}, {pick('face_b')})"
    elif method == "points":
        call = f"scad.make_workplane_from_points_rworkplane({pick('point_a')}, {pick('point_b')}, {pick('point_c')})"
    else:
        edge = pick("edge")
        face = f", face={pick('face')}" if "face" in c._recipes else ""
        call = f"scad.make_workplane_from_axis_rworkplane({edge}, {c.var('angle')}{face})"
    return [*lines, f"{c.slug} = {call}"]


_AXIS = lambda name, label, default="+z": _enum(name, label, _AXIS_OPTIONS, default)  # noqa: E731
_PROFILE = lambda: Slot("profile", "Sketch profile", "profile", help="A sketch made earlier.")  # noqa: E731
_BODY = lambda: _body("body", "Body", "The body this feature works on (default: the last one made).")  # noqa: E731

SPECS: tuple[Spec, ...] = (
    Spec("box", "Box", "Primitives", "build", "solid", "A rectangular block; its bottom face is centred on the origin point.",
         (_length("width", "Width (x)", 40.0), _length("height", "Height (y)", 30.0), _length("depth", "Depth (z)", 20.0),
          _point("origin", "Bottom face centre")), _box),
    Spec("cylinder", "Cylinder", "Primitives", "build", "solid", "A cylinder standing on a centre point, along an axis.",
         (_length("radius", "Radius", 10.0), _length("height", "Height", 30.0), _point("origin", "Bottom face centre"),
          _AXIS("axis", "Axis")), _cylinder),
    Spec("sphere", "Sphere", "Primitives", "build", "solid", "A sphere around a centre point.",
         (_length("radius", "Radius", 15.0), _point("center", "Centre")), _sphere),
    Spec("cone", "Cone / frustum", "Primitives", "build", "solid", "A cone, or a frustum when the top radius is above zero.",
         (_length("bottom_radius", "Bottom radius", 15.0), Slot("top_radius", "Top radius", "length", default=0.0, unit="mm", min=0.0),
          _length("height", "Height", 25.0), _point("origin", "Bottom face centre"), _AXIS("axis", "Axis")), _cone),
    Spec("sketch", "Sketch", "Sketch", "build, profile=sketch", "face", "A constrained 2D sketch on a plane, made into a face (a closed profile) or a wire (a profile or an open path).",
         (Slot("sketch", "Sketch", "sketch", default={"plane": "XY", "points": [], "entities": [], "constraints": [], "profile": 0}),), _sketch),
    Spec("extrude_sketch", "Extrude sketch", "Sketch", "build", "solid", "Push a sketch face along a direction.",
         (_PROFILE(), _enum("direction", "Direction", _DIR_OPTIONS, "normal"), _signed("distance", "Distance", 10.0, min=0.001)), _extrude_sketch),
    Spec("revolve_sketch", "Revolve sketch", "Sketch", "build", "solid", "Turn a sketch face about an axis.",
         (_PROFILE(), _AXIS("axis", "Axis"), _point("origin", "Axis point"), Slot("angle", "Angle", "angle", default=360.0, unit="deg", min=1.0, max=360.0)), _revolve_sketch),
    Spec("cut_sketch", "Cut sketch", "Sketch", "subtract", "solid", "Cut a body along a sketch face (a pocket or a through cut).",
         (_BODY(), _PROFILE(), _enum("direction", "Direction", _DIR_OPTIONS, "normal"), _length("depth", "Depth", 10.0)), _cut_sketch),
    Spec("boss_sketch", "Boss from sketch", "Sketch", "add", "solid", "Add material along a sketch face to a body.",
         (_BODY(), _PROFILE(), _enum("direction", "Direction", _DIR_OPTIONS, "normal"), _signed("distance", "Distance", 10.0, min=0.001)), _boss_sketch),
    Spec("assembly", "Assembly layout", "Assembly", "add", "assembly", "Components, the grounded one, and the joints and mates between connector frames.",
         (Slot("assembly", "Assembly", "assembly", default={"components": [], "ground": None, "constraints": []}),), _assembly),
    Spec("cut", "Cut", "Boolean", "subtract", "solid", "Take one or more bodies out of another.",
         (_body("base", "Body to cut"), _body("tool", "Tool (taken out)")), _cut),
    Spec("union", "Union", "Boolean", "add", "solid", "Join two bodies into one.",
         (_body("base", "First body"), _body("other", "Second body")), _union),
    Spec("intersect", "Intersect", "Boolean", "modifier", "solid", "Keep only what two bodies share.",
         (_body("base", "First body"), _body("other", "Second body")), _intersect),
    Spec("hole", "Hole", "Features", "subtract", "solid", "A round hole from a point on a surface, in a direction, to a depth.",
         (_BODY(), _point("position", "Start point (on the surface)", help="Pick a face to fill the point and direction."),
          _enum("direction", "Direction into the material", _HOLE_DIRECTIONS, "face", help="An axis, the normal of the face you picked (into the material), or any vector."),
          *(Slot(name, label, "float", default=default, min=-1000.0, max=1000.0, show_when=_HOLE_VECTOR)
            for name, label, default in (("dx", "Direction x", 0.0), ("dy", "Direction y", 0.0), ("dz", "Direction z", -1.0))),
          _length("diameter", "Diameter", 6.0), _length("depth", "Depth", 10.0)), _hole),
    Spec("extrude_face", "Extrude face", "Features", "build", "solid", "Push a flat face of the body out (or into it) along its normal, without a sketch.",
         (_BODY(), Slot("face", "Face", "select", entity="face", single=True, help="Pick one flat face of the body."),
          _enum("direction", "Direction", _FACE_DIRECTIONS, "normal"), _signed("distance", "Distance", 10.0, min=0.001)), _extrude_face),
    Spec("fillet", "Fillet", "Features", "modifier", "solid", "Round the picked edges.",
         (_BODY(), Slot("edges", "Edges", "select", entity="edge"), _length("radius", "Radius", 2.0)), _fillet),
    Spec("chamfer", "Chamfer", "Features", "modifier", "solid", "Bevel the picked edges.",
         (_BODY(), Slot("edges", "Edges", "select", entity="edge"), _length("distance", "Distance", 1.5)), _chamfer),
    Spec("shell", "Shell", "Features", "modifier", "solid", "Hollow the body, opening the picked faces.",
         (_BODY(), Slot("faces", "Faces to open", "select", entity="face"), _length("thickness", "Wall thickness", 2.0)), _shell),
    Spec("linear_pattern", "Linear pattern", "Pattern", "build", "solids", "Copies of a body along a direction (the original is the first copy).",
         (_body("shape", "Body to repeat"), _AXIS("direction", "Direction", "+x"), Slot("count", "Count", "count", default=3, min=2, max=500),
          _length("spacing", "Spacing", 15.0)), _linear_pattern),
    Spec("radial_pattern", "Radial pattern", "Pattern", "build", "solids", "Copies of a body around an axis.",
         (_body("shape", "Body to repeat"), _point("center", "Axis point"), _AXIS("axis", "Axis"),
          Slot("count", "Count", "count", default=6, min=2, max=500),
          Slot("total_angle", "Total angle", "angle", default=360.0, unit="deg", min=1.0, max=360.0)), _radial_pattern),
    Spec("mirror", "Mirror", "Transform", "build", "solid", "Mirror a body in a plane, and optionally join the halves.",
         (_BODY(), _point("origin", "Plane point"), _AXIS("normal", "Plane normal", "+x"), Slot("merge", "Join with the original", "bool", default=True)), _mirror),
    Spec("translate", "Move", "Transform", "build", "solid", "Move a body by an offset.",
         (_BODY(), _point("offset", "Offset")), _translate),
    Spec("rotate", "Rotate", "Transform", "build", "solid", "Turn a body about an axis.",
         (_BODY(), Slot("angle", "Angle", "angle", default=45.0, unit="deg", min=-360.0, max=360.0), _AXIS("axis", "Axis"), _point("origin", "Axis point")), _rotate),
    Spec("scale", "Scale", "Transform", "build", "solid", "Scale a body uniformly about a point.",
         (_BODY(), Slot("factor", "Factor", "float", default=1.5, min=0.01, max=100.0), _point("origin", "Centre")), _scale),
    Spec("workplane", "Workplane", "Datums", "datum", "workplane",
         "A workplane from picked geometry: on a planar face (x along an edge if one is picked, an offset along the normal), "
         "halfway between two parallel faces, through three vertices, or through an edge turned about it; or placed by hand "
         "(moved and turned with the handles) on XY / XZ / YZ, another workplane or a face. Sketch on it, "
         "or place features in it with `with wp:`.",
         (dataclasses.replace(_BODY(), optional=True), _enum("method", "From", _WORKPLANE_METHODS, "face"),
          Slot("base", "Base", "text", default="XY", show_when=_OFFSET,
               help="XY, XZ or YZ, the name of a workplane of the notebook, or face (the picked face)."),
          Slot("face", "Face", "select", entity="face", single=True, optional=True,
               show_when={"method": ["face", "face_edge", "midplane", "axis"]},
               help="A planar face (for an axis: the face the plane starts from)."),
          Slot("face_b", "Second face", "select", entity="face", single=True, optional=True, show_when={"method": ["midplane"]},
               help="A face parallel to the first."),
          Slot("edge", "Edge", "select", entity="edge", single=True, optional=True, show_when={"method": ["face_edge", "axis"]},
               help="x runs along it (on a face); the axis the plane turns about (through an edge)."),
          Slot("point_a", "Origin vertex", "select", entity="vertex", single=True, optional=True, show_when={"method": ["points"]}),
          Slot("point_b", "x towards vertex", "select", entity="vertex", single=True, optional=True, show_when={"method": ["points"]}),
          Slot("point_c", "Third vertex", "select", entity="vertex", single=True, optional=True, show_when={"method": ["points"]}),
          _signed("offset", "Offset along the normal", 0.0, show_when=_ON_FACE),
          Slot("flip", "Flip the normal", "bool", default=False, show_when=_ON_FACE),
          Slot("angle", "Angle about the edge", "angle", default=0.0, unit="deg", min=-360.0, max=360.0,
               show_when={"method": ["axis"]}),
          Slot("x_dir", "x direction on the face", "point", default=None, unit=None, optional=True, show_when=_OFFSET),
          dataclasses.replace(_point("move", "Move", help="The origin's offset along the base's own x, y and normal (mm)."),
                              show_when=_OFFSET),
          *(Slot(axis, f"Turn about {label}", "angle", default=0.0, unit="deg", min=-360.0, max=360.0, show_when=_OFFSET)
            for axis, label in (("rx", "x"), ("ry", "y"), ("rz", "the normal")))), _workplane),
)

_COMBINE_OPTIONS = [
    {"value": "join", "label": "Join"},
    {"value": "cut", "label": "Cut"},
    {"value": "intersect", "label": "Intersect"},
    {"value": "new", "label": "New body"},
]
_COMBINABLE = frozenset({"box", "cylinder", "sphere", "cone", "extrude_sketch", "revolve_sketch", "extrude_face"})
_COMBINE_ROLE = {"new": "build", "join": "add", "cut": "subtract", "intersect": "intersect"}


def _with_combine(spec: Spec) -> Spec:
    """A part holds one solid, so a new solid is not left beside the old one: it says at once how it meets it."""
    operation = Slot("operation", "Operation", "enum", default="new", options=_COMBINE_OPTIONS,
                     help="How the new solid meets the body so far: join it, cut it out, keep only what they share, or (when there is no body yet) start it.")
    target = Slot("target", "Combine with", "body", optional=True, show_when={"operation": ["join", "cut", "intersect"]},
                  help="The body this solid is joined to, cut from or intersected with (default: the body so far).")
    return dataclasses.replace(spec, slots=(*spec.slots, operation, target), combinable=True)


SPECS = tuple(_with_combine(spec) if spec.id in _COMBINABLE else spec for spec in SPECS)


class _Registry(dict):
    """Specs by id: the curated ones, and (loaded on first need) one per SDK operation (``op.<name>``, :mod:`.op_specs`)."""

    loaded = False

    def _load(self) -> None:
        if not self.loaded:
            self.loaded = True
            from .op_specs import operation_specs

            for spec in operation_specs():
                self.setdefault(spec.id, spec)

    def __missing__(self, key: str) -> Spec:
        self._load()
        if key in self:
            return dict.__getitem__(self, key)
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        if dict.__contains__(self, key):
            return True
        self._load()
        return dict.__contains__(self, key)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return self[key] if key in self else default

    def all(self) -> list[Spec]:
        self._load()
        return list(self.values())


BY_ID: _Registry = _Registry({spec.id: spec for spec in SPECS})


def catalog() -> dict[str, Any]:
    """The registry as plain data, for the forms."""
    groups: list[str] = []
    specs = BY_ID.all()
    for spec in specs:
        if spec.group not in groups:
            groups.append(spec.group)
    return {"version": VERSION, "groups": [{"id": g, "label": g} for g in groups], "specs": [spec.to_dict() for spec in specs]}


# ---- names ----------------------------------------------------------------------------------------------------


def default_slug(spec_id: str, taken: set[str]) -> str:
    base = {"workplane": "wp"}.get(spec_id, spec_id)
    if base.startswith("op."):  # an SDK operation: what it makes (make_spur_gear_rsolid -> spur_gear)
        base = re.sub(r"^(make|add|create)_", "", base[3:].rsplit("_r", 1)[0]) or "shape"
    candidate, number = base, 1
    while candidate in taken or candidate.upper() in taken or candidate in _RESERVED:
        number += 1
        candidate = f"{base}_{number}"
    return candidate


def check_slug(slug: str, taken: set[str]) -> str:
    if not _SLUG.fullmatch(slug):
        raise FeatureError("the name must be lowercase letters, digits and underscores, starting with a letter")
    if slug in _RESERVED:
        raise FeatureError(f"{slug!r} is a Python name; choose another")
    if slug in taken or slug.upper() in taken:
        raise FeatureError(f"the name {slug!r} is already used in this notebook")
    return slug


# ---- values -----------------------------------------------------------------------------------------------------------


def check_values(spec: Spec, values: Mapping[str, Any], bodies: Mapping[str, str]) -> dict[str, Any]:
    """Validate *values* against the slots; returns the cleaned values.  Raises :class:`FeatureError`."""
    clean: dict[str, Any] = {}
    for slot in spec.slots:
        raw = values.get(slot.name, slot.default)
        if slot.kind == "select":
            continue  # the recipe is built from the picked items
        if raw is None and not slot.optional:
            raise FeatureError(f"{slot.label}: a value is required")
        if raw is None and clean.get("operation", "new") == "new":
            continue
        if raw is None and slot.optional and slot.name != "target":
            continue  # an optional parameter left out: the SDK's default
        if slot.kind in ("length", "angle", "float"):
            clean[slot.name] = _checked_number(slot, raw)
        elif slot.kind == "count":
            number = _checked_number(slot, raw)
            if number != int(number):
                raise FeatureError(f"{slot.label}: a whole number is required")
            clean[slot.name] = int(number)
        elif slot.kind == "bool":
            if not isinstance(raw, bool):
                raise FeatureError(f"{slot.label}: true or false")
            clean[slot.name] = raw
        elif slot.kind == "enum":
            allowed = {option["value"] for option in slot.options or []}
            if raw not in allowed:
                raise FeatureError(f"{slot.label}: choose one of {', '.join(sorted(allowed))}")
            clean[slot.name] = str(raw)
        elif slot.kind == "point":
            if not (isinstance(raw, (list, tuple)) and len(raw) == 3):
                raise FeatureError(f"{slot.label}: three numbers (x, y, z)")
            clean[slot.name] = [_checked_number(Slot(slot.name, slot.label, "float", min=slot.min, max=slot.max), part) for part in raw]
        elif slot.kind in ("body", "profile"):
            combining = any(other.name == "operation" for other in spec.slots)
            if slot.optional and ((combining and clean.get("operation", "new") == "new") or (not combining and raw is None)):
                continue  # nothing to combine with (or, for an optional body, none given)
            if raw is None and slot.optional:
                raise FeatureError("there is no body to combine with: choose 'New body' to start one")
            name = str(raw)
            wanted = ("face",) if slot.kind == "profile" else ("solid", "solids")
            if not _NAME.fullmatch(name) or bodies.get(name) not in wanted:
                noun = "sketch profile" if slot.kind == "profile" else "body"
                raise FeatureError(f"{slot.label}: {name!r} is not a {noun} in this notebook")
            clean[slot.name] = name
        elif slot.kind == "value":
            names = list(raw) if slot.many and isinstance(raw, (list, tuple)) else [raw]
            if slot.many and not names:
                raise FeatureError(f"{slot.label}: choose at least one")
            for name in names:
                if not _NAME.fullmatch(str(name)) or bodies.get(str(name)) not in (slot.accepts or ()):
                    raise FeatureError(f"{slot.label}: {name!r} is not a {' or '.join(slot.accepts or ())} in this notebook")
            clean[slot.name] = [str(n) for n in names] if slot.many else str(names[0])
        elif slot.kind == "grid":
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                raise FeatureError(f"{slot.label}: at least two rows of points")
            width = None
            grid = []
            for row in raw:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    raise FeatureError(f"{slot.label}: each row needs at least two points")
                if width is not None and len(row) != width:
                    raise FeatureError(f"{slot.label}: every row needs the same number of points")
                width = len(row)
                points = []
                for point in row:
                    if not (isinstance(point, (list, tuple)) and len(point) == 3):
                        raise FeatureError(f"{slot.label}: each point needs 3 numbers")
                    points.append([_checked_number(Slot(slot.name, slot.label, "float"), v) for v in point])
                grid.append(points)
            clean[slot.name] = grid
        elif slot.kind == "color":
            if not (isinstance(raw, (list, tuple)) and len(raw) == 3):
                raise FeatureError(f"{slot.label}: three numbers (red, green, blue) between 0 and 1")
            clean[slot.name] = [_checked_number(Slot(slot.name, slot.label, "float", min=0.0, max=1.0), part) for part in raw]
        elif slot.kind == "text":
            if not isinstance(raw, str):
                raise FeatureError(f"{slot.label}: text is required")
            clean[slot.name] = raw
        elif slot.kind == "sketch":
            try:
                clean[slot.name] = sketch_doc.validate(raw)
            except sketch_doc.SketchError as exc:
                raise FeatureError(f"{slot.label}: {exc}") from exc
        elif slot.kind == "assembly":
            try:
                clean[slot.name] = assembly_doc.validate(raw)
            except assembly_doc.AssemblyError as exc:
                raise FeatureError(f"{slot.label}: {exc}") from exc
        elif slot.kind in ("points2d", "points3d"):
            width = 2 if slot.kind == "points2d" else 3
            if not isinstance(raw, (list, tuple)) or len(raw) < width:
                raise FeatureError(f"{slot.label}: at least {width} points")
            rows = []
            for row in raw:
                if not (isinstance(row, (list, tuple)) and len(row) == width):
                    raise FeatureError(f"{slot.label}: each point needs {width} numbers")
                rows.append([_checked_number(Slot(slot.name, slot.label, "float"), part) for part in row])
            if slot.kind == "points2d" and len(rows) < 3:
                raise FeatureError(f"{slot.label}: a polygon needs at least three corners")
            if slot.kind == "points3d" and len(rows) < 2:
                raise FeatureError(f"{slot.label}: a path needs at least two points")
            clean[slot.name] = rows
        else:  # pragma: no cover - the registry is ours
            raise FeatureError(f"{slot.label}: unsupported slot kind {slot.kind}")
    return clean


# ---- selection recipes ----------------------------------------------------------------------------------------------


def _picked_refs(slot: Slot, picked: Sequence[Mapping[str, Any]]) -> list[_ref.ElementRef] | None:
    """The references the server attached to the picked items (``item["ref"]``: a record), or ``None`` if one has none."""
    refs: list[_ref.ElementRef] = []
    for item in picked:
        record = item.get("ref")
        if not isinstance(record, Mapping):
            return None
        try:
            reference = _ref.ElementRef.from_dict(record)
        except (TypeError, ValueError) as exc:
            raise FeatureError(f"{slot.label}: {exc}") from exc
        if reference.kind != slot.entity:
            raise FeatureError(f"{slot.label}: a {reference.kind} reference where a {slot.entity} is picked")
        refs.append(reference)
    return refs


def selection_recipe(slot: Slot, items: Sequence[Mapping[str, Any]], known_slugs: set[str]) -> list[str]:
    """Source lines that select the picked *items* inside the feature cell (bound to ``_<slot>``).

    One ``scad.ref`` statement when every item carries its reference; the older tag-or-geometry recipe otherwise.
    """
    factory = {"face": "faces", "edge": "edges", "vertex": "vertices"}[slot.entity or "face"]
    picked = [item for item in items if item.get("kind") == slot.entity]
    if not picked:
        raise FeatureError(f"{slot.label}: pick at least one {slot.entity} in the viewport")
    refs = _picked_refs(slot, picked)
    if refs is not None:
        return f"_{slot.name} = {_ref.selection_code(slot.entity or 'face', refs)}".splitlines()
    geometry: list[str] = []
    tags: list[str] = []
    all_tagged = True
    for item in picked:
        conditions = selector_conditions(str(item.get("kind")), item.get("properties") or {}, item.get("geometry") or {})
        if conditions is None:
            raise FeatureError(f"{slot.label}: an item has no geometry to select it by")
        geometry.append("scad.ql.and_(" + ", ".join(conditions) + ")")
        own = [t for t in (item.get("tags") or []) if isinstance(t, str) and _TAG.fullmatch(t) and t.split(".")[0] in known_slugs]
        if own:
            tags.append(f"scad.ql.tag({json.dumps(sorted(own)[0])})")
        else:
            all_tagged = False
    n = len(picked)
    lines = [f"# {slot.label.lower()}: {n} picked in the viewport, resolved against the body this feature receives"]
    wrap = (lambda parts: parts[0]) if n == 1 else (lambda parts: "scad.ql.or_(" + ", ".join(parts) + ")")
    geo = f"scad.ql.{factory}().where({wrap(geometry)})"
    if tags and all_tagged:
        lines.append(f"_{slot.name}_by_tag = scad.ql.{factory}().where({wrap(tags)})")
        lines.append(f"_{slot.name}_by_geometry = {geo}")
        lines.append(f"_{slot.name}_source = {{BODY}}")
        lines.append(f"_{slot.name} = _{slot.name}_by_tag if len(_{slot.name}_by_tag.resolve(_{slot.name}_source)) == {n} else _{slot.name}_by_geometry.exactly({n})")
    else:
        lines.append(f"_{slot.name} = {geo}.exactly({n})")
    return lines


# ---- rendering ----------------------------------------------------------------------------------------------------------


def _ref_statement(code: str, slot: str) -> tuple[int, int, str, list[_ref.ElementRef]] | None:
    """(first line, last line, kind, references) of ``_<slot> = scad.ref.<kinds>(...)`` in *code* (0-based lines)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == f"_{slot}"
        ):
            try:
                kind, refs = _ref.parse_selection(node.value)
            except ValueError:
                return None
            return node.lineno - 1, (node.end_lineno or node.lineno) - 1, kind, refs
    return None


def extract_refs(code: str, slot: str) -> list[_ref.ElementRef] | None:
    """The references of a selection slot written as ``scad.ref`` in a feature cell, or ``None``."""
    found = _ref_statement(code, slot)
    return found[3] if found else None


def replace_refs(code: str, slot: str, refs: Sequence[_ref.ElementRef]) -> str:
    """*code* with the ``scad.ref`` statement of *slot* rewritten to name *refs* (a repair writes its choice so)."""
    found = _ref_statement(code, slot)
    if found is None:
        raise FeatureError(f"the feature has no scad.ref selection for {slot!r}")
    first, last, kind, _ = found
    lines = code.splitlines()
    lines[first : last + 1] = f"_{slot} = {_ref.selection_code(kind, list(refs))}".splitlines()
    return "\n".join(lines) + ("\n" if code.endswith("\n") else "")


def extract_recipe(code: str, slot: str) -> list[str] | None:
    """The recipe lines of a selection slot in an existing feature cell, so an edit can keep what was picked."""
    found = _ref_statement(code, slot)
    if found is not None:
        return code.splitlines()[found[0] : found[1] + 1]
    lines = code.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("# ") and "picked in the viewport" in line:
            start = index  # the recipe of a slot starts at the comment closest above its line (a cell may hold several)
        elif start is not None and line.startswith(f"_{slot} = "):
            return [re.sub(r"(_\w+_source = ).*", r"\1{BODY}", text) for text in lines[start : index + 1]]
    return None


_REQUIRED_PICKS = {
    "face": ("face",),
    "face_edge": ("face", "edge"),
    "midplane": ("face", "face_b"),
    "points": ("point_a", "point_b", "point_c"),
    "axis": ("edge",),
}
"""The picks each way of making a workplane needs (the others are optional or hidden)."""


def _required_pick(spec: Spec, slot: Slot, clean: Mapping[str, Any]) -> bool:
    """Whether an optional selection slot must still be picked: a workplane's method names the picks it needs."""
    if spec.id == "workplane":
        return slot.name in _REQUIRED_PICKS.get(str(clean.get("method")), ())
    return False


def render_feature(
    spec_id: str,
    slug: str,
    values: Mapping[str, Any],
    *,
    bodies: Mapping[str, str],
    selections: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    known_slugs: set[str] | None = None,
    keep_recipes: Mapping[str, list[str]] | None = None,
    env: Mapping[str, Any] | None = None,
) -> Rendered:
    """The cells of one feature.  *bodies* maps each body variable of the notebook to ``solid`` or ``solids``."""
    spec = BY_ID.get(spec_id)
    if spec is None:
        raise FeatureError(f"unknown operation {spec_id!r}")
    clean = check_values(spec, values, bodies)
    recipes: dict[str, list[str]] = {}
    for slot in spec.slots:
        if slot.kind == "select":
            if (selections or {}).get(slot.name):
                if slot.single and len([i for i in selections[slot.name] if i.get("kind") == slot.entity]) > 1:
                    raise FeatureError(f"{slot.label}: pick exactly one {slot.entity}")
                recipes[slot.name] = selection_recipe(slot, selections[slot.name], known_slugs or set())
            elif keep_recipes and keep_recipes.get(slot.name):
                recipes[slot.name] = list(keep_recipes[slot.name])
            elif slot.optional and not _required_pick(spec, slot, clean):
                continue
            else:
                raise FeatureError(f"{slot.label}: pick at least one {slot.entity} in the viewport")
    ctx = Context(spec, slug, clean, bodies, recipes, env)
    code = spec.build(ctx)
    operation = clean.get("operation", "new") if spec.combinable else "new"
    if operation != "new":
        target = ctx.body("target")
        code.append(
            {
                "join": f"{slug} = scad.union_rsolid({target}, _tool)",
                "cut": f"{slug} = scad.cut_rsolid({target}, _tool, skip_non_intersecting=False)",
                "intersect": f"{slug} = scad.intersect_rsolid({target}, _tool)",
            }[operation]
        )
    role = _COMBINE_ROLE[operation] if spec.combinable else spec.role
    # the recipe resolves against the body slot of the feature ({BODY} is filled with that name)
    body_name = next((v for v in (clean.get(spec.body_slot), clean.get("body")) if isinstance(v, str)), "")
    code = [line.replace("{BODY}", body_name) for line in code]
    gui = {"spec": spec.id, "v": VERSION, "values": clean}
    if selections:
        gui["picked"] = {k: len(v) for k, v in selections.items()}
    header = f"# ---- feature: {slug} ({role}) ----"
    feature_lines = [header, f"{GUI_MARKER} {json.dumps(gui, separators=(',', ':'))}", *code]
    params = [f"# ---- params: {slug} ----", *ctx.params] if ctx.params else []
    return Rendered(
        slug=slug,
        spec=spec.id,
        params=params,
        feature="\n".join(feature_lines),
        before=ctx.before,
        reads=ctx.reads,
        produces=sketch_doc.output_of(clean["sketch"]) if spec.id == "sketch" else spec.produces,
        gui=gui,
    )


def parse_gui(code: str) -> dict[str, Any] | None:
    """The ``# gui:`` payload of a feature cell, or ``None`` for a cell written as code."""
    for line in code.splitlines()[:6]:
        stripped = line.strip()
        if stripped.startswith(GUI_MARKER):
            try:
                data = json.loads(stripped[len(GUI_MARKER):])
            except ValueError:
                return None
            return data if isinstance(data, dict) and data.get("spec") in BY_ID else None
    return None


__all__ = [
    "BY_ID",
    "FeatureError",
    "Rendered",
    "SPECS",
    "catalog",
    "check_slug",
    "check_values",
    "default_slug",
    "extract_recipe",
    "extract_refs",
    "parse_gui",
    "render_feature",
    "replace_refs",
    "selection_recipe",
]
