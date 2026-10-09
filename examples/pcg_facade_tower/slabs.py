"""pcg_facade_tower slabs and the entrance canopy.

Slab-local frame = world axes, z = 0 at the slab's level: each tier's building line pulled in by slab_gap,
extruded slab_t up (A3: the slab occupies [level, level + slab_t]; floor slabs from the floor level, roof slabs
ending at the roof; `layout.slab_instances`).
Floor slabs and the tier's roof share one Part per tier; placement only translates by the level.
Canopy-local frame = world (it is built where it stands; placed with the identity).
"""
from __future__ import annotations

import simplecadapi as scad

import layout as L
import panels as P


def slab_type_id(tier: int) -> str:
    return f"slab-tier{tier}"


CANOPY_ID = "canopy-south"


def build_slab(*, plan: tuple, slab_t: float):
    # ---- feature: slab-plate (build, profile=sketch) ----
    sk = P.polygon_loop(scad.make_sketch_rsketch(name="slab-plate", plane="XY"), "s", plan)
    face = scad.make_face_from_sketch_rface(sketch=sk, profile="s_l0", require_fully_constrained=True)
    return scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=slab_t)


def build_canopy(*, x0: float, x1: float, y0: float, y1: float, z0: float, z1: float):
    # ---- feature: canopy-plate (build, profile=sketch) ----
    sk = P._rect_loop(scad.make_sketch_rsketch(name="canopy-plate", plane="XY"), "o", x0, y0, x1, y1)
    face = scad.make_face_from_sketch_rface(sketch=sk, profile="o_lb", require_fully_constrained=True)
    plate = scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=z1 - z0)
    return scad.translate_shape(shape=plate, vector=(0.0, 0.0, z0))


def slab_args(sched: L.FacadeSchedule, tier: int) -> dict:
    plan = tuple((round(x, 6), round(y, 6)) for x, y in L.slab_plans(sched)[tier])
    return dict(plan=plan, slab_t=sched.params.slab_t)


def canopy_args(sched: L.FacadeSchedule) -> dict:
    box = L.canopy_box(sched)
    return {k: box[k] for k in ("x0", "x1", "y0", "y1", "z0", "z1")}


def make_slab_part(sched: L.FacadeSchedule, tier: int):
    return scad.part(id=slab_type_id(tier), revision="1.0.0", project_root=P.ROOT)(build_slab)(**slab_args(sched, tier))


def make_canopy_part(sched: L.FacadeSchedule):
    return scad.part(id=CANOPY_ID, revision="1.0.0", project_root=P.ROOT)(build_canopy)(**canopy_args(sched))
