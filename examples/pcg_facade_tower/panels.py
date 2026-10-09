"""pcg_facade_tower panel family: one Part per panel type id from the layout schedule.

Panel-local frame (BUILD_PLAN): x along the building edge (0 = left joint centreline), y up (0 = floor level),
z outward (0 = building line). The module is [0, w] x [0, h]; the unit body sits inside the joint,
[j/2, w - j/2] x [j/2, h - j/2] x [0, frame_d].

Fin-local frame: same axes as the panel; origin = right-jamb centreline on the frame outer face.
Fins are separate site-attached Parts (see layout.py header): theta > 0 tilts the tip toward +x.

Families
  vision   frame ring (vision opening + spandrel opening when spandrel > 0) + recessed glass + spandrel infill
  solid    frame ring (one opening) + opaque infill (closers, parapets, the Bayer-solid modules)
  fin      parallelogram blade: root flush on the frame face, sides at theta, thickness fin_t, length fin_depth
"""
from __future__ import annotations

import math
from pathlib import Path

import simplecadapi as scad
from simplecadapi import ql

import layout as L

ROOT = Path(__file__).resolve().parent
GLASS_TAG = "facade.vision_glass"
PLANE_TOL = 1.0e-3


# ---------------------------------------------------------------- sketch helpers


def _rect_loop(sk, key: str, x0: float, y0: float, x1: float, y1: float):
    """Closed, fully constrained rectangle loop; profile id = f"{key}_lb" (its first line)."""
    for pid, x, y in (("a", x0, y0), ("b", x1, y0), ("c", x1, y1), ("d", x0, y1)):
        sk = scad.add_point_rsketch(sketch=sk, point_id=f"{key}_{pid}", x=x, y=y)
    for lid, s, e in (("lb", "a", "b"), ("lr", "b", "c"), ("lt", "c", "d"), ("ll", "d", "a")):
        sk = scad.add_line_rsketch(sketch=sk, entity_id=f"{key}_{lid}", start=f"{key}_{s}", end=f"{key}_{e}")
    sk = scad.constrain_fix_rsketch(sketch=sk, target=f"{key}_a")
    sk = scad.constrain_horizontal_rsketch(sketch=sk, line=f"{key}_lb")
    sk = scad.constrain_vertical_rsketch(sketch=sk, line=f"{key}_lr")
    sk = scad.constrain_horizontal_rsketch(sketch=sk, line=f"{key}_lt")
    sk = scad.constrain_vertical_rsketch(sketch=sk, line=f"{key}_ll")
    sk = scad.constrain_distance_x_rsketch(sketch=sk, a=f"{key}_a", b=f"{key}_b", value=x1 - x0)
    sk = scad.constrain_distance_y_rsketch(sketch=sk, a=f"{key}_a", b=f"{key}_d", value=y1 - y0)
    return sk


def polygon_loop(sk, key: str, pts):
    """Closed polygon loop, fully constrained: first vertex fixed, the rest dimensioned x / y from it.
    Profile id = f"{key}_l0"."""
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        sk = scad.add_point_rsketch(sketch=sk, point_id=f"{key}_p{i}", x=x, y=y)
    for i in range(n):
        sk = scad.add_line_rsketch(sketch=sk, entity_id=f"{key}_l{i}", start=f"{key}_p{i}", end=f"{key}_p{(i + 1) % n}")
    sk = scad.constrain_fix_rsketch(sketch=sk, target=f"{key}_p0")
    for i in range(1, n):
        sk = scad.constrain_distance_x_rsketch(sketch=sk, a=f"{key}_p0", b=f"{key}_p{i}", value=pts[i][0] - pts[0][0])
        sk = scad.constrain_distance_y_rsketch(sketch=sk, a=f"{key}_p0", b=f"{key}_p{i}", value=pts[i][1] - pts[0][1])
    return sk


def _rect_plate(name: str, x0: float, y0: float, x1: float, y1: float, z0: float, z1: float):
    """profile=sketch: one constrained rectangle extruded from z0 to z1."""
    sk = _rect_loop(scad.make_sketch_rsketch(name=name, plane="XY"), "o", x0, y0, x1, y1)
    face = scad.make_face_from_sketch_rface(sketch=sk, profile="o_lb", require_fully_constrained=True)
    plate = scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=z1 - z0)
    return scad.translate_shape(shape=plate, vector=(0.0, 0.0, z0))


# ---------------------------------------------------------------- design openings (shared with the verifier)


def openings(w: float, h: float, spandrel: float, frame_sight: float, joint: float) -> dict:
    """Clear openings in panel-local (x0, y0, x1, y1). 'vision' only when the panel carries glass."""
    j, s = joint, frame_sight
    x0, x1 = j / 2.0 + s, w - j / 2.0 - s
    top = h - j / 2.0 - s
    out = {}
    if spandrel > 0.0:
        out["vision"] = (x0, spandrel + s / 2.0, x1, top)
        out["spandrel"] = (x0, j / 2.0 + s, x1, spandrel - s / 2.0)
    else:
        out["vision"] = (x0, j / 2.0 + s, x1, top)
    return out


def _grow(r, d: float):
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def _frame_ring(w, h, holes: dict, frame_d, joint):
    j = joint
    sk = _rect_loop(scad.make_sketch_rsketch(name="frame-ring", plane="XY"), "o", j / 2.0, j / 2.0, w - j / 2.0,
                    h - j / 2.0)
    for key, r in holes.items():
        sk = _rect_loop(sk, key, *r)
    face = scad.make_face_from_sketch_rface(sketch=sk, profile="o_lb", inner_profiles=tuple(f"{k}_lb" for k in holes),
                                            require_fully_constrained=True)
    return scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=frame_d)


def _tag_front_face(body, rect, z: float, tag: str):
    """Resolve the +Z planar face at z whose centre lies inside rect, then tag it (exactly one)."""
    x0, y0, x1, y1 = rect
    faces = ql.faces().where(ql.and_(
        ql.prop("geom.normal.z", ">=", 1.0 - 1.0e-6),
        ql.prop("geom.center.z", ">=", z - PLANE_TOL), ql.prop("geom.center.z", "<=", z + PLANE_TOL),
        ql.prop("geom.center.x", ">=", x0), ql.prop("geom.center.x", "<=", x1),
        ql.prop("geom.center.y", ">=", y0), ql.prop("geom.center.y", "<=", y1),
    )).resolve(body)
    if len(faces) != 1:
        raise ValueError(f"{tag}: expected one glass face at z={z}, found {len(faces)}")
    return scad.apply_tag_rselection(scope=body, targets=list(faces), tag=tag)


# ---------------------------------------------------------------- builders (every dimension is a builder argument)


def build_vision(*, w: float, h: float, spandrel: float, frame_d: float, frame_sight: float, joint: float,
                 glass_t: float, glass_recess: float):
    s = frame_sight
    ops = openings(w, h, spandrel, frame_sight, joint)
    glass_z1 = frame_d - glass_recess
    glass_z0 = glass_z1 - glass_t

    # ---- feature: frame-ring (build, profile=sketch) ----
    body = _frame_ring(w, h, ops, frame_d, joint)

    # ---- feature: spandrel-infill (add, profile=sketch) ----
    # opaque infill sits half a recess proud of the glass so it reads as a separate plane
    if "spandrel" in ops:
        body = scad.union_rsolid(body, _rect_plate("spandrel-infill", *_grow(ops["spandrel"], s / 2.0), glass_z0,
                                                   frame_d - glass_recess / 2.0))

    # ---- feature: vision-glass (add, profile=sketch) ----
    # grown by s/2 into the jambs so the plate bonds to the ring; its exposed front = the clear opening
    body = scad.union_rsolid(body, _rect_plate("vision-glass", *_grow(ops["vision"], s / 2.0), glass_z0, glass_z1))

    # ---- feature: vision-glass-name (annotate) ----
    return _tag_front_face(body, ops["vision"], glass_z1, GLASS_TAG)


def build_solid(*, w: float, h: float, frame_d: float, frame_sight: float, joint: float, glass_t: float,
                glass_recess: float):
    s = frame_sight
    opening = openings(w, h, 0.0, frame_sight, joint)["vision"]

    # ---- feature: frame-ring (build, profile=sketch) ----
    body = _frame_ring(w, h, {"op": opening}, frame_d, joint)

    # ---- feature: opaque-infill (add, profile=sketch) ----
    return scad.union_rsolid(body, _rect_plate("opaque-infill", *_grow(opening, s / 2.0),
                                               frame_d - glass_recess - glass_t, frame_d - glass_recess / 2.0))


def fin_section(angle: float, fin_t: float, fin_depth: float) -> list[tuple[float, float]]:
    """Parallelogram in fin-local (x, z): root on z = 0 centred on x = 0, sides along (sin a, cos a)."""
    th = math.radians(angle)
    half = fin_t / (2.0 * math.cos(th))
    dx, dz = fin_depth * math.sin(th), fin_depth * math.cos(th)
    return [(-half, 0.0), (half, 0.0), (half + dx, dz), (-half + dx, dz)]


def build_fin(*, angle: float, h: float, joint: float, fin_t: float, fin_depth: float):
    (r0x, _), (r1x, _), (t1x, t1z), (t0x, _) = fin_section(angle, fin_t, fin_depth)

    # ---- feature: fin-blade (build, profile=sketch) ----
    # XZ sketch: (u, v) -> world (x, z); explicit x / z offsets keep the sign of the angle unambiguous
    sk = scad.make_sketch_rsketch(name="fin-blade", plane="XZ")
    for pid, x, z in (("r0", r0x, 0.0), ("r1", r1x, 0.0), ("t1", t1x, t1z), ("t0", t0x, t1z)):
        sk = scad.add_point_rsketch(sketch=sk, point_id=pid, x=x, y=z)
    for lid, a, b in (("root", "r0", "r1"), ("side_r", "r1", "t1"), ("tip", "t1", "t0"), ("side_l", "t0", "r0")):
        sk = scad.add_line_rsketch(sketch=sk, entity_id=lid, start=a, end=b)
    sk = scad.constrain_fix_rsketch(sketch=sk, target="r0")
    sk = scad.constrain_horizontal_rsketch(sketch=sk, line="root")
    sk = scad.constrain_horizontal_rsketch(sketch=sk, line="tip")
    sk = scad.constrain_distance_x_rsketch(sketch=sk, a="r0", b="r1", value=r1x - r0x)
    sk = scad.constrain_distance_x_rsketch(sketch=sk, a="r0", b="t0", value=t0x - r0x)
    sk = scad.constrain_distance_y_rsketch(sketch=sk, a="r0", b="t0", value=t1z)
    sk = scad.constrain_distance_x_rsketch(sketch=sk, a="t0", b="t1", value=t1x - t0x)
    face = scad.make_face_from_sketch_rface(sketch=sk, profile="root", require_fully_constrained=True)
    blade = scad.extrude_rsolid(profile=face, direction=(0.0, 1.0, 0.0), distance=h - joint)
    return scad.translate_shape(shape=blade, vector=(0.0, joint / 2.0, 0.0))


# ---------------------------------------------------------------- type table -> Part


def builder_args(spec: dict, p: L.FacadeParams) -> tuple:
    """(builder, kwargs) for one type spec. Every value that shapes the solid is an argument (build_key)."""
    common = dict(frame_d=p.frame_d, frame_sight=p.frame_sight, joint=p.joint, glass_t=p.glass_t,
                  glass_recess=p.glass_recess)
    fam = spec["family"]
    if fam == "vision":
        return build_vision, dict(w=spec["w"], h=spec["h"], spandrel=spec["spandrel"], **common)
    if fam == "solid":
        return build_solid, dict(w=spec["w"], h=spec["h"], **common)
    if fam == "fin":
        return build_fin, dict(angle=spec["angle"], h=spec["h"], joint=p.joint, fin_t=p.fin_t,
                               fin_depth=p.fin_depth)
    raise ValueError(f"not a panel family: {fam}")


def make_panel_part(type_id: str, spec: dict, p: L.FacadeParams):
    """Part factory: part id == type id — equal parameters are the same part identity, rebuilt identically."""
    builder, kwargs = builder_args(spec, p)
    return scad.part(id=type_id, revision="1.0.0", project_root=ROOT)(builder)(**kwargs)
