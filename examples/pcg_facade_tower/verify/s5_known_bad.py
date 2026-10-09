"""S5 known-bad proof: the S5 checks must FAIL on each deliberately wrong tower assembly and PASS on the clean one.

Towers are rebuilt from the tower component list with one edit (same band / slab / canopy definitions), then checked
against the unchanged schedule. Each bad case must fire (at least) the listed gates; the clean ones none.

  KB0 clean tower                                            -> must pass
  KB1 floor2 30 mm high (into floor3, a sampled floor)       -> V8 + V1 + V2
  KB2 floor7 missing                                         -> T0 + V4 (T1 is SDK-vs-ours, self-consistent here)
  KB3 floor13 (tier 1's first) given a tier 0 band           -> T0 + V8 + V2 (into parapet0) + V4
  KB4 parapet1 standing on roof 0                            -> V8 + V1 + V2
  KB5 roof slab 0 floor-style (on the roof, not below it)    -> V8 + V2 (cuts tier 1's first floor)
  KB6 floor5 with the wrong fin phase                        -> T0 + V4
  KB7 floor20 not grounded                                   -> T0
  KB8 slab under floor2 pushed 40 mm east (slab_gap is 30)   -> T1 + V2
  KB9 floor3 turned 90 degrees about its centre              -> T1 + V1 + V5
  KB10 a rebuild still reporting a dirty instance            -> A2
"""
import math
import sys

from _common import report
from s4_verify import check_solve
from s5_verify import check_tower

import layout as L
import simplecadapi as scad
from tower import TOWER_ID, definitions, make_tower, tower_components

sched = L.build_schedule(L.default_params())
p = sched.params
COMPS = tower_components(sched)
DEFS = definitions(sched, COMPS)


def tower(edit=None, unground=()) -> scad.Assembly:
    comps = [dict(c) for c in COMPS]
    if edit:
        comps = edit(comps)
    asm = scad.make_assembly_rassembly(assembly_id=TOWER_ID)
    for c in comps:
        dx, dy = c.get("xy", (0.0, 0.0))
        a = math.radians(c.get("rot", 0.0))
        cx, cy = c.get("centre", (0.0, 0.0))
        # rotation about (cx, cy): origin = centre - R centre
        ox = cx - (math.cos(a) * cx - math.sin(a) * cy) + dx
        oy = cy - (math.sin(a) * cx + math.cos(a) * cy) + dy
        asm = scad.add_component_rassembly(
            assembly=asm, item=DEFS[c["ref"]].value, component_id=c["component_id"],
            placement=scad.make_placement_rplacement(origin=(ox, oy, c["level"]), x_axis=(math.cos(a), math.sin(a), 0.0),
                                                     y_axis=(-math.sin(a), math.cos(a), 0.0)))
        if c["component_id"] not in unground:
            asm = scad.ground_component_rassembly(assembly=asm, component_id=c["component_id"])
    return asm


def _find(comps, cid):
    return next(c for c in comps if c["component_id"] == cid)


def change(cid, **kw):
    def edit(comps):
        c = _find(comps, cid)
        for key, value in kw.items():
            c[key] = value(c[key]) if callable(value) else value
        return comps
    return edit


def drop(cid):
    return lambda comps: [c for c in comps if c["component_id"] != cid]


def tower_case(**kw) -> list[str]:
    return check_tower(sched, tower(**kw))[0]


def solve_case() -> list[str]:
    from dataclasses import replace
    warm = make_tower(sched)
    fake = replace(warm, solve_report=replace(warm.solve_report, dirty_instances=("floor1",)))
    return check_solve("tower", warm, fake)


first13 = _find(COMPS, "floor13")
poly0 = sched.tiers[0]
centre = (sum(v[0] for v in poly0) / len(poly0), sum(v[1] for v in poly0) / len(poly0))
phase5 = _find(COMPS, "floor5")["ref"][1]
other_phase = next(b["band_id"] for b in sched.bands
                   if b.get("tier") == 0 and b["band"] == L.Band.TOWER.value and b["band_id"] != phase5)
roof0 = sched.levels["roof0"]

cases = {
    "KB0 clean tower": (lambda: tower_case(), set()),
    "KB1 floor2 +30 mm": (lambda: tower_case(edit=change("floor2", level=lambda z: z + 30.0)), {"V8", "V1", "V2"}),
    "KB2 floor7 missing": (lambda: tower_case(edit=drop("floor7")), {"T0", "V4"}),
    "KB3 floor13 tier-0 band": (lambda: tower_case(edit=change("floor13", ref=("band", "tier0-phase0"))),
                                {"T0", "V8", "V2", "V4"}),
    "KB4 parapet1 on roof 0": (lambda: tower_case(edit=change("parapet1", level=roof0)), {"V8", "V1", "V2"}),
    "KB5 floor-style roof slab 0": (lambda: tower_case(edit=change("slab-roof0", level=roof0)), {"V8", "V2"}),
    "KB6 floor5 wrong phase": (lambda: tower_case(edit=change("floor5", ref=("band", other_phase))), {"T0", "V4"}),
    "KB7 floor20 ungrounded": (lambda: tower_case(unground=("floor20",)), {"T0"}),
    "KB8 slab-floor2 +40 mm E": (lambda: tower_case(edit=change("slab-floor2", xy=(40.0, 0.0))), {"T1", "V2"}),
    "KB9 floor3 turned 90": (lambda: tower_case(edit=change("floor3", rot=90.0, centre=centre)), {"T1", "V1", "V5"}),
    "KB10 dirty warm rebuild": (solve_case, {"A2"}),
}
assert first13["ref"][1].startswith("tier1-"), first13
only = sys.argv[1:]
wrong = []
for name, (run, gates) in cases.items():
    if only and not any(name.startswith(o + " ") for o in only):
        continue
    failures = run()
    fired = {f.split()[0] for f in failures}
    ok = fired == gates if not gates else gates <= fired
    print(f"--- {name:28s} => {'pass' if not failures else 'fail ' + '+'.join(sorted(fired))} "
          f"({'as designed' if ok else 'GATE BROKEN, want ' + '+'.join(sorted(gates))})"
          + ("" if not failures else f"   first: {failures[0]}  [+{len(failures) - 1}]"), flush=True)
    if not ok:
        wrong.append(name)
sys.exit(report("S5 known-bad", [f"{name}: gate did not discriminate" for name in wrong]))
