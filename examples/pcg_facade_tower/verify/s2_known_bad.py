"""S2 known-bad proof: check_body must FAIL on each deliberately wrong solid and PASS on the clean ones.

Each case builds the body from mutated builder arguments (or a mutated step) but checks it against the
unchanged type spec, the way a drifted builder would be caught.

  KB0 clean vision / solid / fin                      -> must pass
  KB1 vision frame 1 mm shallow                       -> P2 / P3
  KB2 glass recessed 1 mm deeper                      -> P4 (plane) + P5
  KB3 glass face never tagged                         -> P4
  KB4 panel built to the module, no joint             -> P2 / P3
  KB5 solid panel carries a glass tag                 -> P4
  KB6 fin built 0.1 deg off its bin                   -> P6 (angle)
  KB7 fin angle sign flipped                          -> P6 (angle + lean)
  KB8 fin lifted 1 mm off the frame face              -> P6 (root)
  KB9 fin 1 mm thicker                                -> P6 (side planes)
"""
import sys
from types import SimpleNamespace

from _common import report
from s2_verify import check_body

import layout as L
import panels as P
import simplecadapi as scad

p = L.default_params()
TYPES = L.build_schedule(p).types
VISION = next(t for t, s in TYPES.items() if s["family"] == "vision" and s["spandrel"] > 0)
SOLID = next(t for t, s in TYPES.items() if s["family"] == "solid")
FIN = next(t for t, s in TYPES.items() if s["family"] == "fin" and s["angle"] > 0)


def case(tid, mutate_kwargs=None, post=None):
    builder, kwargs = P.builder_args(TYPES[tid], p)
    body = builder(**{**kwargs, **(mutate_kwargs or {})})
    if post is not None:
        body = post(body)
    return tid, SimpleNamespace(part_id=tid, body=body)


def _untagged_vision(_body):
    kw = P.builder_args(TYPES[VISION], p)[1]
    ops = P.openings(kw["w"], kw["h"], kw["spandrel"], kw["frame_sight"], kw["joint"])
    z1 = kw["frame_d"] - kw["glass_recess"]
    body = P._frame_ring(kw["w"], kw["h"], ops, kw["frame_d"], kw["joint"])
    body = scad.union_rsolid(body, P._rect_plate("s", *P._grow(ops["spandrel"], 30.0), z1 - kw["glass_t"],
                                                 kw["frame_d"] - kw["glass_recess"] / 2.0))
    return scad.union_rsolid(body, P._rect_plate("g", *P._grow(ops["vision"], 30.0), z1 - kw["glass_t"], z1))


def _tag_solid(body):
    kw = P.builder_args(TYPES[SOLID], p)[1]
    op = P.openings(kw["w"], kw["h"], 0.0, kw["frame_sight"], kw["joint"])["vision"]
    return P._tag_front_face(body, op, kw["frame_d"] - kw["glass_recess"] / 2.0, P.GLASS_TAG)


cases = {
    "KB0 clean vision": (case(VISION), True),
    "KB0 clean solid": (case(SOLID), True),
    "KB0 clean fin": (case(FIN), True),
    "KB1 frame 1 mm shallow": (case(VISION, dict(frame_d=p.frame_d - 1.0)), False),
    "KB2 glass 1 mm deeper": (case(VISION, dict(glass_recess=p.glass_recess + 1.0)), False),
    "KB3 glass never tagged": (case(VISION, post=_untagged_vision), False),
    "KB4 no joint": (case(VISION, dict(joint=0.0)), False),
    "KB5 solid tagged as glass": (case(SOLID, post=_tag_solid), False),
    "KB6 fin 0.1 deg off bin": (case(FIN, dict(angle=TYPES[FIN]["angle"] + 0.1)), False),
    "KB7 fin sign flipped": (case(FIN, dict(angle=-TYPES[FIN]["angle"])), False),
    "KB8 fin lifted 1 mm": (case(FIN, post=lambda b: scad.translate_shape(shape=b, vector=(0.0, 0.0, 1.0))), False),
    "KB9 fin 1 mm thicker": (case(FIN, dict(fin_t=p.fin_t + 1.0)), False),
}
wrong = []
for name, ((tid, part), should_pass) in cases.items():
    failures = check_body(tid, TYPES[tid], part, p)
    passed = not failures
    verdict = "as designed" if passed == should_pass else "GATE BROKEN"
    print(f"--- {name:26s} => {'pass' if passed else 'fail'} ({verdict})"
          + ("" if passed else f"   first: {failures[0]}  [+{len(failures) - 1}]"))
    if passed != should_pass:
        wrong.append(name)
sys.exit(report("S2 known-bad", [f"{name}: gate did not discriminate" for name in wrong]))
