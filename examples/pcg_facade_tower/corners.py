"""pcg_facade_tower corner pieces: one Part per (turn, height) type from the layout schedule.

Corner-local frame (BUILD_PLAN): origin = building-line vertex, x = incoming edge tangent, y up (0 = band level),
z = incoming outward normal. The plan polygon (layout.corner_profile_local) is bounded by the building line,
both panel bands' outer faces (offset frame_d) and the two band end lines at corner_c - joint/2 from the vertex,
so the piece sits one joint off each neighbouring panel. Convex (turn > 0) and reflex (turn < 0) share the builder.
"""
from __future__ import annotations

from types import SimpleNamespace

import simplecadapi as scad

import layout as L
import panels as P


def corner_section(turn: float, corner_c: float, frame_d: float, joint: float) -> list[tuple[float, float]]:
    return L.corner_profile_local(turn, SimpleNamespace(corner_c=corner_c, frame_d=frame_d, joint=joint))


def build_corner(*, turn: float, h: float, corner_c: float, frame_d: float, joint: float):
    pts = corner_section(turn, corner_c, frame_d, joint)

    # ---- feature: corner-post (build, profile=sketch) ----
    # XZ sketch: (u, v) -> corner-local (x, z); extruded up the band inside the joint
    sk = P.polygon_loop(scad.make_sketch_rsketch(name="corner-post", plane="XZ"), "c", pts)
    face = scad.make_face_from_sketch_rface(sketch=sk, profile="c_l0", require_fully_constrained=True)
    post = scad.extrude_rsolid(profile=face, direction=(0.0, 1.0, 0.0), distance=h - joint)
    return scad.translate_shape(shape=post, vector=(0.0, joint / 2.0, 0.0))


def builder_args(spec: dict, p: L.FacadeParams) -> tuple:
    return build_corner, dict(turn=spec["turn"], h=spec["h"], corner_c=p.corner_c, frame_d=p.frame_d, joint=p.joint)


def make_corner_part(type_id: str, spec: dict, p: L.FacadeParams):
    builder, kwargs = builder_args(spec, p)
    return scad.part(id=type_id, revision="1.0.0", project_root=P.ROOT)(builder)(**kwargs)
