"""S4 known-bad proof: the S4 checks must FAIL on each deliberately wrong band assembly and PASS on the clean ones.

Assemblies are rebuilt from the layout component list with one edit, then checked against the unchanged schedule.
Each bad case must fire (at least) the listed gates; the clean ones none.

  KB0 clean tier0-phase0 / lobby                        -> must pass
  KB1 one panel 1 mm along the edge                    -> A1 + V1 (joints 21 / 19)
  KB2 one panel 30 mm along the edge (into neighbour)  -> A1 + V1 (overlap) + V2
  KB3 one panel missing                                -> A0 + V1
  KB4 one panel not grounded                           -> A0
  KB5 a vision panel swapped for a solid of its width  -> A0 + V4
  KB6 a fin root pushed into its panel (frame_d in)    -> A1 + V2
  KB7 a panel turned inside out (x = -t)               -> A1
  KB8 a corner piece with the wrong turn               -> A0 + V1
  KB9 lobby upper row dropped 30 mm (joint is 20)      -> A1 + V1 (z span, row joint) + V2
  KB10 a warm rebuild of a different design            -> A2
"""
import sys

from _common import report
from s4_verify import check_band, check_solve

import floor as F
import layout as L
import simplecadapi as scad

sched = L.build_schedule(L.default_params())
p = sched.params
FLOOR, LOBBY = sched.band("tier0-phase0"), sched.band("lobby")


def assembly(band: dict, edit=None, unground=()) -> scad.Assembly:
    comps = F.band_components(sched, band)
    if edit:
        comps = edit([dict(c, frame=dict(c["frame"])) for c in comps])
    parts = F.type_parts(sched, [c["type_id"] for c in comps])
    asm = scad.make_assembly_rassembly(assembly_id=F.band_assembly_id(band["band_id"]))
    for c in comps:
        f = c["frame"]
        asm = scad.add_component_rassembly(
            assembly=asm, item=parts[c["type_id"]].value, component_id=c["component_id"],
            placement=scad.make_placement_rplacement(origin=f["origin"], x_axis=f["x_axis"], y_axis=f["y_axis"]))
        if c["component_id"] not in unground:
            asm = scad.ground_component_rassembly(assembly=asm, component_id=c["component_id"])
    return asm


def _find(comps, cid):
    return next(c for c in comps if c["component_id"] == cid)


def shift(cid, d, dz=0.0, axis=None):
    def edit(comps):
        for c in comps:
            if c["component_id"] == cid or (cid.endswith("*") and c["component_id"].startswith(cid[:-1])):
                a = axis or c["frame"]["x_axis"]
                o = c["frame"]["origin"]
                c["frame"]["origin"] = (o[0] + d * a[0], o[1] + d * a[1], o[2] + dz)
        return comps
    return edit


def drop(cid):
    return lambda comps: [c for c in comps if c["component_id"] != cid]


def retype(cid, type_id):
    def edit(comps):
        _find(comps, cid)["type_id"] = type_id
        return comps
    return edit


def flip(cid):
    def edit(comps):
        c = _find(comps, cid)
        rec = next(r for r in FLOOR["panels"] if f"r0-e{r['edge']}-s{r['slot']}" == cid)
        o, (tx, ty, _) = c["frame"]["origin"], c["frame"]["x_axis"]
        c["frame"]["origin"] = (o[0] + rec["w"] * tx, o[1] + rec["w"] * ty, o[2])
        c["frame"]["x_axis"] = (-tx, -ty, 0.0)
        return comps
    return edit


vision = next(r for r in FLOOR["panels"] if r["kind"] == "vision" and r["edge"] == 0 and r["fin"] is not None)
VISION_ID = f"r0-e0-s{vision['slot']}"
SOLID_SAME_W = L.solid_type_id(vision["w"], FLOOR["height"])
sched.types.setdefault(SOLID_SAME_W, {"family": "solid", "w": L._r(vision["w"]), "h": L._r(FLOOR["height"])})
n0 = L.edge_frames(sched.tiers[0])[0]["n"]
other_turn = next(r["type_id"] for r in FLOOR["corners"] if r["type_id"] != FLOOR["corners"][0]["type_id"])


def band_case(band, **kw) -> list[str]:
    return check_band(sched, band, assembly(band, **kw))[0]


def solve_case() -> list[str]:
    """A warm rebuild that is not the same design (different band) must not pass A2."""
    cold = F.make_band_assembly(sched, "parapet0")
    warm = F.make_band_assembly(sched, "lobby")
    return check_solve("parapet0", cold, warm)


cases = {
    "KB0 clean tier0-phase0": (lambda: band_case(FLOOR), set()),
    "KB0 clean lobby": (lambda: band_case(LOBBY), set()),
    "KB0 clean solve": (lambda: check_solve("parapet0", F.make_band_assembly(sched, "parapet0"),
                                            F.make_band_assembly(sched, "parapet0")), set()),
    "KB1 panel +1 mm": (lambda: band_case(FLOOR, edit=shift("r0-e0-s4", 1.0)), {"A1", "V1"}),
    "KB2 panel +30 mm": (lambda: band_case(FLOOR, edit=shift("r0-e0-s4", 30.0)), {"A1", "V1", "V2"}),
    "KB3 panel missing": (lambda: band_case(FLOOR, edit=drop("r0-e3-s5")), {"A0", "V1"}),
    "KB4 panel ungrounded": (lambda: band_case(FLOOR, unground=("r0-e1-s3",)), {"A0"}),
    "KB5 vision -> solid": (lambda: band_case(FLOOR, edit=retype(VISION_ID, SOLID_SAME_W)), {"A0", "V4"}),
    "KB6 fin into its panel": (lambda: band_case(FLOOR, edit=shift(VISION_ID + "-fin", -p.frame_d,
                                                                   axis=(n0[0], n0[1], 0.0))), {"A1", "V2"}),
    "KB7 panel inside out": (lambda: band_case(FLOOR, edit=flip("r0-e0-s6")), {"A1"}),
    "KB8 corner wrong turn": (lambda: band_case(FLOOR, edit=retype("r0-v0", other_turn)), {"A0", "V1"}),
    "KB9 lobby row 1 -30 mm": (lambda: band_case(LOBBY, edit=shift("r1-*", 0.0, dz=-30.0)), {"A1", "V1", "V2"}),
    "KB10 warm rebuild, different design": (solve_case, {"A2"}),
}
wrong = []
for name, (run, gates) in cases.items():
    failures = run()
    fired = {f.split()[0] for f in failures}
    ok = fired == gates if not gates else gates <= fired
    print(f"--- {name:26s} => {'pass' if not failures else 'fail ' + '+'.join(sorted(fired))} "
          f"({'as designed' if ok else 'GATE BROKEN, want ' + '+'.join(sorted(gates))})"
          + ("" if not failures else f"   first: {failures[0]}  [+{len(failures) - 1}]"))
    if not ok:
        wrong.append(name)
sys.exit(report("S4 known-bad", [f"{name}: gate did not discriminate" for name in wrong]))
