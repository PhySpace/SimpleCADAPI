"""S3 known-bad proof: the S3 checks must FAIL on each deliberately wrong solid / placement and PASS on the clean ones.

Bodies are built from mutated builder arguments but checked against the unchanged schedule (a drifted builder).

  KB0 clean corners (+90 / +45 / -90), slab, canopy        -> must pass (L_SHAPE; +45 from CHAMFER)
  KB1 corner legs 1 mm long (corner_c + 1)                 -> K2 (end faces) + K6 (joint)
  KB2 corner 1 mm shallow (frame_d - 1)                    -> K1 (volume) + K2 (outer faces)
  KB3 +90 corner built as +45                              -> K1 + K2
  KB4 corner built without joint                           -> K1 (y span) + K6
  KB5 slab on the building line (slab_gap 0)               -> K4 + K3 (clearance)
  KB6 slab 1 mm thick                                      -> K4 (z span)
  KB7 a floor slab placed on top of its level              -> K3 (level)
  KB8 canopy shifted one module east                       -> K5 (centre)
  KB9 canopy against the panel face (no standoff)          -> K7
  KB10 roof slabs floor-style, on top of the roof level    -> K3 (roof end + terrace cut by the upper tier)
"""
import sys
from types import SimpleNamespace

from _common import report
from s3_verify import Parts, check_canopy, check_canopy_fit, check_corner, check_corner_fit, check_slab, check_slab_fit
from s3_verify import fit_bands

import corners as C
import layout as L
import slabs as S

p = L.default_params(plan_kind=L.PlanKind.L_SHAPE)
sched = L.build_schedule(p)
chamfer = L.build_schedule(L.default_params(plan_kind=L.PlanKind.CHAMFER))


def corner_case(which: float, **mutate) -> list[str]:
    """Tier-0 tower band corner of this turn (L_SHAPE has +/-90, CHAMFER has +45)."""
    s = sched if abs(which) == 90.0 else chamfer
    band = next(b for b in fit_bands(s) if b["band"] == L.Band.TOWER.value and b["tier"] == 0)
    rec = next(r for r in band["corners"] if abs(r["turn"] - which) < 1.0e-9)
    tid, spec = rec["type_id"], s.types[rec["type_id"]]
    body = C.build_corner(**{**C.builder_args(spec, s.params)[1], **mutate})
    parts = Parts(s)
    parts.bodies[tid] = body
    return (check_corner(tid, spec, SimpleNamespace(part_id=tid, body=body), s.params)
            + check_corner_fit(parts, band, rec))


def slab_case(plan=None, slab_t=None, instances=None) -> list[str]:
    kwargs = S.slab_args(sched, 0)
    body = S.build_slab(plan=plan or kwargs["plan"], slab_t=slab_t or kwargs["slab_t"])
    bodies = {k: S.make_slab_part(sched, k).value.body for k in range(len(sched.tiers))}
    bodies[0] = body
    real = L.slab_instances
    if instances is not None:
        L.slab_instances = lambda _s: instances
    try:
        return (check_slab(sched, 0, SimpleNamespace(part_id=S.slab_type_id(0), body=body))
                + check_slab_fit(Parts(sched), bodies))
    finally:
        L.slab_instances = real


def canopy_case(dx=0.0, dy=0.0) -> list[str]:
    kwargs = S.canopy_args(sched)
    body = S.build_canopy(**{**kwargs, "x0": kwargs["x0"] + dx, "x1": kwargs["x1"] + dx, "y1": kwargs["y1"] + dy})
    return (check_canopy(sched, SimpleNamespace(part_id=S.CANOPY_ID, body=body))
            + check_canopy_fit(Parts(sched), body))


def _raised_floor() -> list[dict]:
    out = [dict(i) for i in L.slab_instances(sched)]
    out[3]["level"] += p.slab_t
    return out


def _floor_style_roofs() -> list[dict]:
    return [dict(i, level=sched.levels[i["role"]]) if i["role"].startswith("roof") else dict(i)
            for i in L.slab_instances(sched)]


cases = {
    "KB0 clean corner +90": (lambda: corner_case(90.0), True),
    "KB0 clean corner +45": (lambda: corner_case(45.0), True),
    "KB0 clean corner -90": (lambda: corner_case(-90.0), True),
    "KB0 clean slab": (lambda: slab_case(), True),
    "KB0 clean canopy": (lambda: canopy_case(), True),
    "KB1 corner legs +1 mm": (lambda: corner_case(90.0, corner_c=p.corner_c + 1.0), False),
    "KB2 corner 1 mm shallow": (lambda: corner_case(-90.0, frame_d=p.frame_d - 1.0), False),
    "KB3 +90 built as +45": (lambda: corner_case(90.0, turn=45.0), False),
    "KB4 corner without joint": (lambda: corner_case(90.0, joint=0.0), False),
    "KB5 slab on building line": (lambda: slab_case(plan=tuple(map(tuple, sched.tiers[0]))), False),
    "KB6 slab 1 mm thick": (lambda: slab_case(slab_t=p.slab_t + 1.0), False),
    "KB7 floor slab raised": (lambda: slab_case(instances=_raised_floor()), False),
    "KB8 canopy one module east": (lambda: canopy_case(dx=p.w_std), False),
    "KB9 canopy on panel face": (lambda: canopy_case(dy=p.joint), False),
    "KB10 floor-style roof slabs": (lambda: slab_case(instances=_floor_style_roofs()), False),
}
wrong = []
for name, (run, should_pass) in cases.items():
    failures = run()
    passed = not failures
    verdict = "as designed" if passed == should_pass else "GATE BROKEN"
    print(f"--- {name:28s} => {'pass' if passed else 'fail'} ({verdict})"
          + ("" if passed else f"   first: {failures[0]}  [+{len(failures) - 1}]"))
    if passed != should_pass:
        wrong.append(name)
sys.exit(report("S3 known-bad", [f"{name}: gate did not discriminate" for name in wrong]))
