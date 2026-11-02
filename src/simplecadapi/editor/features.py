"""GUI-made features: the operations a person can add with a button, and the cells they become.

A feature is an ordinary notebook cell (``# ---- feature: <slug> (<role>) ----``, one operation that makes one new public
name) with its numbers in a ``# ---- params: <slug> ----`` cell, so a person or an agent can read and edit it like any
other cell.  A cell made here carries one more line, ``# gui: {...}``, from which the form is rebuilt; a cell without that
line is code, shown in the tree and never rewritten.

Nothing in this module runs a kernel or touches a file.  :func:`render_feature` turns validated values into source text;
every value that reaches the text is a number, a choice from a fixed list, a name from the notebook, or a tag built from
the slug, so a request cannot put code into a cell.

Selections are written as *recipes* inside the feature cell, resolved against the body the cell receives: the face tags a
primitive or extrude was given (they survive booleans, not fillets) first, the picked geometry second, and the count of
what was picked is always checked.  A recipe that no longer resolves is an error on the feature, never another face.
"""

from __future__ import annotations

import builtins
import json
import keyword
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from . import sketch_doc
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
_PLANE_NORMALS = {"XY": (0.0, 0.0, 1.0), "XZ": (0.0, 1.0, 0.0), "YZ": (1.0, 0.0, 0.0)}
_PLANE_OPTIONS = [{"value": key, "label": key} for key in _PLANE_NORMALS]


class FeatureError(ValueError):
    """A request the registry cannot turn into a feature; the message is meant for the person."""


@dataclass(frozen=True)
class Slot:
    """One input of a feature.

    kind: ``length`` (mm), ``angle`` (deg), ``float``, ``count``, ``bool``, ``enum``, ``point`` (three lengths),
    ``body`` (a solid made earlier), ``profile`` (a sketch face made earlier), ``select`` (faces or edges picked in the
    viewport), ``points2d`` (``x, y`` per line), ``sketch`` (a sketch document, see :mod:`.sketch_doc`).
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
        return out


@dataclass(frozen=True)
class Spec:
    id: str
    label: str
    group: str
    role: str  # build | add | subtract | modifier
    produces: str  # solid | solids | face
    description: str
    slots: tuple[Slot, ...]
    build: Callable[["Context"], list[str]] = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "role": self.role,
            "produces": self.produces,
            "description": self.description,
            "slots": [slot.to_dict() for slot in self.slots],
        }


@dataclass
class Rendered:
    slug: str
    spec: str
    params: list[str]  # lines of the params cell ("" when the feature has no numbers)
    feature: str  # the feature cell
    reads: list[str]  # bodies this feature consumes
    produces: str
    gui: dict[str, Any]


class Context:
    """What a template needs: the slug, the variable of each number, the bodies, the selection recipes."""

    def __init__(self, spec: Spec, slug: str, values: Mapping[str, Any], bodies: Mapping[str, str], recipes: Mapping[str, list[str]]):
        self.spec, self.slug, self.values = spec, slug, values
        self._bodies, self._recipes = bodies, recipes
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
                low, high = _range(spec, float(value))
                self.params.append(
                    f"{name} = scad.var(name={json.dumps(f'{self.slug}_{slot}_{axis}')}, default={_num(float(value))}, unit=\"mm\", "
                    f"comment={json.dumps(f'{spec.label} {axis}')})  # ui: slider({_num(low)}, {_num(high)}, step=1, label={json.dumps(f'{spec.label} {axis}')})"
                )
            names.append(name)
        return f"({', '.join(names)})"

    def raw_params(self, lines: list[str]) -> None:
        """Params-cell lines a template writes itself (the dimensions of a sketch)."""
        self.params.extend(lines)

    def choice(self, slot: str) -> str:
        """The value of an enum slot (already checked against its options)."""
        return str(self.values[slot])

    def axis(self, slot: str) -> str:
        return repr(_AXES[str(self.values[slot])])

    def normal(self, slot: str) -> str:
        return repr(_PLANE_NORMALS[str(self.values[slot])])

    # -- bodies and selections ------------------------------------------------------------------------------------
    def body(self, slot: str) -> str:
        name = str(self.values[slot])
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
        f"{c.slug} = scad.make_box_rsolid(",
        f"    width={c.var('width')}, height={c.var('height')}, depth={c.var('depth')},",
        f"    bottom_face_center={c.point('origin')},",
        f"    bottom_face_tag={c.tag('bottom')}, top_face_tag={c.tag('top')},",
        f"    front_face_tag={c.tag('front')}, back_face_tag={c.tag('back')},",
        f"    left_face_tag={c.tag('left')}, right_face_tag={c.tag('right')},",
        ")",
    ]


def _cylinder(c: Context) -> list[str]:
    return [
        f"{c.slug} = scad.make_cylinder_rsolid(",
        f"    radius={c.var('radius')}, height={c.var('height')},",
        f"    bottom_face_center={c.point('origin')}, axis={c.axis('axis')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_face_tag={c.tag('side')},",
        ")",
    ]


def _sphere(c: Context) -> list[str]:
    return [f"{c.slug} = scad.make_sphere_rsolid(radius={c.var('radius')}, center={c.point('center')})"]


def _cone(c: Context) -> list[str]:
    return [
        f"{c.slug} = scad.make_cone_rsolid(",
        f"    bottom_radius={c.var('bottom_radius')}, top_radius={c.var('top_radius')}, height={c.var('height')},",
        f"    bottom_face_center={c.point('origin')}, axis={c.axis('axis')},",
        # a true cone has no top face to name; the tag is written only when there is one
        f"    start_face_tag={c.tag('start')}, " + (f"end_face_tag={c.tag('end')}, " if c.values["top_radius"] > 0 else "") + f"side_face_tag={c.tag('side')},",
        ")",
    ]


def _extrude_rect(c: Context) -> list[str]:
    return [
        f"_profile = scad.make_rectangle_rface(width={c.var('width')}, height={c.var('height')}, center={c.point('center')}, normal={c.normal('plane')})",
        f"{c.slug} = scad.extrude_rsolid(",
        f"    profile=_profile, direction={c.normal('plane')}, distance={c.var('distance')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')},",
        ")",
    ]


def _extrude_circle(c: Context) -> list[str]:
    return [
        f"_profile = scad.make_circle_rface(center={c.point('center')}, radius={c.var('radius')}, normal={c.normal('plane')})",
        f"{c.slug} = scad.extrude_rsolid(",
        f"    profile=_profile, direction={c.normal('plane')}, distance={c.var('distance')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')},",
        ")",
    ]


def _points(values: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in values["points"]]


def _extrude_polygon(c: Context) -> list[str]:
    pts = ", ".join(f"({_num(x)}, {_num(y)}, 0.0)" for x, y in _points(c.values))
    return [
        f"_outline = scad.make_polyline_rwire(points=[{pts}], closed=True)",
        "_profile = scad.make_face_from_wire_rface(wire=_outline, normal=(0.0, 0.0, 1.0))",
        f"{c.slug} = scad.extrude_rsolid(",
        f"    profile=_profile, direction=(0.0, 0.0, 1.0), distance={c.var('distance')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')},",
        ")",
    ]


def _revolve(c: Context) -> list[str]:
    return [
        "# the section sits in the XZ plane, beside the Z axis, and turns about it",
        f"_profile = scad.make_rectangle_rface(width={c.var('width')}, height={c.var('height')},",
        f"    center=({c.var('offset')} + {c.var('width')} / 2, 0.0, {c.var('height')} / 2), normal=(0.0, 1.0, 0.0))",
        f"{c.slug} = scad.revolve_rsolid(profile=_profile, axis=(0.0, 0.0, 1.0), angle={c.var('angle')}, origin=(0.0, 0.0, 0.0),",
        # a full turn has no start or end face to name; those tags are written only for a partial turn
        "    " + (f"start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, " if c.values["angle"] < 360 else "") + f"side_faces_tag={c.tag('side')})",
    ]


def _loft_circles(c: Context) -> list[str]:
    return [
        "_bottom = scad.make_circle_rwire(center=(0.0, 0.0, 0.0), radius=" + c.var("bottom_radius") + ", normal=(0.0, 0.0, 1.0))",
        "_top = scad.make_circle_rwire(center=(0.0, 0.0, " + c.var("height") + "), radius=" + c.var("top_radius") + ", normal=(0.0, 0.0, 1.0))",
        f"{c.slug} = scad.loft_rsolid(profiles=[_bottom, _top], ruled={c.var('ruled')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')})",
    ]


def _loft_rects(c: Context) -> list[str]:
    return [
        f"_bottom = scad.make_rectangle_rwire(width={c.var('bottom_width')}, height={c.var('bottom_height')}, center=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0))",
        f"_top = scad.make_rectangle_rwire(width={c.var('top_width')}, height={c.var('top_height')}, center=(0.0, 0.0, {c.var('height')}), normal=(0.0, 0.0, 1.0))",
        f"{c.slug} = scad.loft_rsolid(profiles=[_bottom, _top], ruled={c.var('ruled')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')})",
    ]


def _sweep(c: Context) -> list[str]:
    pts = [(float(x), float(y), float(z)) for x, y, z in c.values["path"]]
    path = ", ".join(f"({_num(x)}, {_num(y)}, {_num(z)})" for x, y, z in pts)
    return [
        f"_path = scad.make_polyline_rwire(points=[{path}], closed=False)",
        "# the circle stands on the first point, square to the first segment",
        f"_a, _b = {pts[0]!r}, {pts[1]!r}",
        "_dir = tuple(_q - _p for _p, _q in zip(_a, _b))",
        "_len = sum(_d * _d for _d in _dir) ** 0.5",
        "_dir = tuple(_d / _len for _d in _dir)",
        f"_profile = scad.make_circle_rface(center=_a, radius={c.var('radius')}, normal=_dir)",
        f"{c.slug} = scad.sweep_rsolid(profile=_profile, path=_path, is_frenet=False,",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')})",
    ]


def _sketch(c: Context) -> list[str]:
    params, lines = sketch_doc.render(c.slug, c.values["sketch"])
    c.raw_params(params)
    return lines


def _profile(c: Context, slot: str = "profile") -> str:
    return c.body(slot)


def _extrude_sketch(c: Context) -> list[str]:
    return [
        f"{c.slug} = scad.extrude_rsolid(profile={_profile(c)}, direction={c.axis('direction')}, distance={c.var('distance')},",
        f"    start_face_tag={c.tag('start')}, end_face_tag={c.tag('end')}, side_faces_tag={c.tag('side')})",
    ]


def _revolve_sketch(c: Context) -> list[str]:
    return [
        f"{c.slug} = scad.revolve_rsolid(profile={_profile(c)}, axis={c.axis('axis')}, angle={c.var('angle')}, origin={c.point('origin')},",
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


def _hole(c: Context) -> list[str]:
    direction = c.axis("direction")
    return [
        "# a cylinder from just outside the surface, in the drilling direction, taken out of the body",
        f"_dir = {direction}",
        "_overshoot = 1.0",
        f"_start = tuple(_p - _overshoot * _d for _p, _d in zip({c.point('position')}, _dir))",
        f"_tool = scad.make_cylinder_rsolid(radius={c.var('diameter')} / 2, height={c.var('depth')} + _overshoot, bottom_face_center=_start, axis=_dir)",
        f"{c.slug} = scad.cut_rsolid({c.body('body')}, _tool, skip_non_intersecting=False)",
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


_AXIS = lambda name, label, default="+z": _enum(name, label, _AXIS_OPTIONS, default)  # noqa: E731
_PLANE = lambda: _enum("plane", "Sketch plane", _PLANE_OPTIONS, "XY", help="The profile lies in this plane and is pushed along its normal.")  # noqa: E731
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
    Spec("extrude_rect", "Extrude rectangle", "Profiles", "build", "solid", "A rectangle pushed along the normal of its plane.",
         (_PLANE(), _length("width", "Width", 40.0), _length("height", "Height", 20.0), _point("center", "Centre"), _signed("distance", "Distance", 10.0, min=0.001)), _extrude_rect),
    Spec("extrude_circle", "Extrude circle", "Profiles", "build", "solid", "A circle pushed along the normal of its plane.",
         (_PLANE(), _length("radius", "Radius", 12.0), _point("center", "Centre"), _signed("distance", "Distance", 10.0, min=0.001)), _extrude_circle),
    Spec("extrude_polygon", "Extrude polygon", "Profiles", "build", "solid", "A closed polygon in the XY plane pushed up the Z axis.",
         (Slot("points", "Corners (x, y per line)", "points2d", default=[[0, 0], [40, 0], [40, 20], [20, 30], [0, 20]], unit="mm"),
          _signed("distance", "Distance", 10.0, min=0.001)), _extrude_polygon),
    Spec("revolve", "Revolve", "Profiles", "build", "solid", "A rectangle beside the Z axis, turned about it.",
         (_length("width", "Section width", 10.0), _length("height", "Section height", 25.0),
          Slot("offset", "Distance from the axis", "length", default=10.0, unit="mm", min=0.0),
          Slot("angle", "Angle", "angle", default=360.0, unit="deg", min=1.0, max=360.0)), _revolve),
    Spec("loft_circles", "Loft circles", "Profiles", "build", "solid", "A solid between two circles, one above the other.",
         (_length("bottom_radius", "Bottom radius", 15.0), _length("top_radius", "Top radius", 8.0), _length("height", "Height", 25.0),
          Slot("ruled", "Straight sides", "bool", default=False)), _loft_circles),
    Spec("loft_rects", "Loft rectangles", "Profiles", "build", "solid", "A solid between two rectangles, one above the other.",
         (_length("bottom_width", "Bottom width", 30.0), _length("bottom_height", "Bottom height", 20.0),
          _length("top_width", "Top width", 15.0), _length("top_height", "Top height", 10.0), _length("height", "Height", 25.0),
          Slot("ruled", "Straight sides", "bool", default=True)), _loft_rects),
    Spec("sweep_circle", "Sweep circle along a path", "Profiles", "build", "solid", "A circle swept along a polyline.",
         (_length("radius", "Radius", 4.0), Slot("path", "Path points (x, y, z per line)", "points3d", default=[[0, 0, 0], [0, 0, 30], [30, 0, 60]], unit="mm")), _sweep),
    Spec("sketch", "Sketch", "Sketch", "build, profile=sketch", "face", "A constrained 2D sketch on a plane, made into a face.",
         (Slot("sketch", "Sketch", "sketch", default={"plane": "XY", "points": [], "entities": [], "constraints": [], "profile": 0}),), _sketch),
    Spec("extrude_sketch", "Extrude sketch", "Sketch", "build", "solid", "Push a sketch face along a direction.",
         (_PROFILE(), _AXIS("direction", "Direction", "+z"), _signed("distance", "Distance", 10.0, min=0.001)), _extrude_sketch),
    Spec("revolve_sketch", "Revolve sketch", "Sketch", "build", "solid", "Turn a sketch face about an axis.",
         (_PROFILE(), _AXIS("axis", "Axis"), _point("origin", "Axis point"), Slot("angle", "Angle", "angle", default=360.0, unit="deg", min=1.0, max=360.0)), _revolve_sketch),
    Spec("cut_sketch", "Cut sketch", "Sketch", "subtract", "solid", "Cut a body along a sketch face (a pocket or a through cut).",
         (_BODY(), _PROFILE(), _AXIS("direction", "Direction", "-z"), _length("depth", "Depth", 10.0)), _cut_sketch),
    Spec("boss_sketch", "Boss from sketch", "Sketch", "add", "solid", "Add material along a sketch face to a body.",
         (_BODY(), _PROFILE(), _AXIS("direction", "Direction", "+z"), _signed("distance", "Distance", 10.0, min=0.001)), _boss_sketch),
    Spec("cut", "Cut", "Boolean", "subtract", "solid", "Take one or more bodies out of another.",
         (_body("base", "Body to cut"), _body("tool", "Tool (taken out)")), _cut),
    Spec("union", "Union", "Boolean", "add", "solid", "Join two bodies into one.",
         (_body("base", "First body"), _body("other", "Second body")), _union),
    Spec("intersect", "Intersect", "Boolean", "modifier", "solid", "Keep only what two bodies share.",
         (_body("base", "First body"), _body("other", "Second body")), _intersect),
    Spec("hole", "Hole", "Features", "subtract", "solid", "A round hole from a point on a surface, in a direction, to a depth.",
         (_BODY(), _point("position", "Start point (on the surface)", help="Pick a face to fill the point and direction."),
          _AXIS("direction", "Direction into the material", "-z"), _length("diameter", "Diameter", 6.0), _length("depth", "Depth", 10.0)), _hole),
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
)

BY_ID: dict[str, Spec] = {spec.id: spec for spec in SPECS}


def catalog() -> dict[str, Any]:
    """The registry as plain data, for the forms."""
    groups: list[str] = []
    for spec in SPECS:
        if spec.group not in groups:
            groups.append(spec.group)
    return {"version": VERSION, "groups": [{"id": g, "label": g} for g in groups], "specs": [spec.to_dict() for spec in SPECS]}


# ---- names ----------------------------------------------------------------------------------------------------


def default_slug(spec_id: str, taken: set[str]) -> str:
    base = {"extrude_rect": "block", "extrude_circle": "disc", "extrude_polygon": "profile_solid"}.get(spec_id, spec_id)
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
        if raw is None:
            raise FeatureError(f"{slot.label}: a value is required")
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
            name = str(raw)
            wanted = ("face",) if slot.kind == "profile" else ("solid", "solids")
            if not _NAME.fullmatch(name) or bodies.get(name) not in wanted:
                noun = "sketch profile" if slot.kind == "profile" else "body"
                raise FeatureError(f"{slot.label}: {name!r} is not a {noun} in this notebook")
            clean[slot.name] = name
        elif slot.kind == "sketch":
            try:
                clean[slot.name] = sketch_doc.validate(raw)
            except sketch_doc.SketchError as exc:
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


def selection_recipe(slot: Slot, items: Sequence[Mapping[str, Any]], known_slugs: set[str]) -> list[str]:
    """Source lines of a recipe that selects the picked *items* inside the feature cell (bound to ``_<slot>``)."""
    factory = {"face": "faces", "edge": "edges"}[slot.entity or "face"]
    picked = [item for item in items if item.get("kind") == slot.entity]
    if not picked:
        raise FeatureError(f"{slot.label}: pick at least one {slot.entity} in the viewport")
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


def extract_recipe(code: str, slot: str) -> list[str] | None:
    """The recipe lines of a selection slot in an existing feature cell, so an edit can keep what was picked."""
    lines = code.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("# ") and "picked in the viewport" in line), None)
    if start is None:
        return None
    for end in range(start + 1, len(lines)):
        if lines[end].startswith(f"_{slot} = "):
            return [re.sub(r"(_\w+_source = ).*", r"\1{BODY}", line) for line in lines[start : end + 1]]
    return None


def render_feature(
    spec_id: str,
    slug: str,
    values: Mapping[str, Any],
    *,
    bodies: Mapping[str, str],
    selections: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    known_slugs: set[str] | None = None,
    keep_recipes: Mapping[str, list[str]] | None = None,
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
                recipes[slot.name] = selection_recipe(slot, selections[slot.name], known_slugs or set())
            elif keep_recipes and keep_recipes.get(slot.name):
                recipes[slot.name] = list(keep_recipes[slot.name])
            else:
                raise FeatureError(f"{slot.label}: pick at least one {slot.entity} in the viewport")
    ctx = Context(spec, slug, clean, bodies, recipes)
    code = spec.build(ctx)
    # the recipe resolves against the body slot of the feature ({BODY} is filled with that name)
    body_name = clean.get("body") or ""
    code = [line.replace("{BODY}", body_name) for line in code]
    gui = {"spec": spec.id, "v": VERSION, "values": clean}
    if selections:
        gui["picked"] = {k: len(v) for k, v in selections.items()}
    header = f"# ---- feature: {slug} ({spec.role}) ----"
    feature_lines = [header, f"{GUI_MARKER} {json.dumps(gui, separators=(',', ':'))}", *code]
    params = [f"# ---- params: {slug} ----", *ctx.params] if ctx.params else []
    return Rendered(
        slug=slug,
        spec=spec.id,
        params=params,
        feature="\n".join(feature_lines),
        reads=ctx.reads,
        produces=spec.produces,
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
    "parse_gui",
    "render_feature",
    "selection_recipe",
]
