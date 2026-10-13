"""S1 known-bad proof: check_s1 must FAIL on each deliberately corrupted schedule and PASS on the clean one.

  KB0 clean CHAMFER schedule                          -> must pass
  KB1 one standard panel 1 mm narrower                -> C1 (edge sum) + C2 (inner width)
  KB2 closers made asymmetric (+/- 300)               -> C2
  KB3 closer turned into a vision panel               -> C2
  KB4 every south solid flipped to vision             -> C4 (WWR S overshoots)
  KB5 fin moved off its bin by 1 degree               -> C6
  KB6 a fin on the north edge                         -> C6
  KB7 floor 13 levelled one floor too low             -> C8
  KB8 tier 1 setback 2999 instead of 3000             -> C8
  KB9 one fin record dropped                          -> C6
  KB10 lobby as a single 5400 row                     -> C10
"""
import copy
import sys

from _common import report  # noqa: F401  (sys.path setup)
from s1_verify import check_s1

import layout as L

CLEAN = L.build_schedule(L.default_params(plan_kind=L.PlanKind.CHAMFER))


def mutate(fn):
    sched = copy.deepcopy(CLEAN)
    fn(sched)
    return sched


def _tower(sched, band_id="tier0-phase0"):
    return sched.band(band_id)


def kb1(s):
    r = next(r for r in _tower(s)["panels"] if r["slot"] == 3)
    r["w"] -= 1.0


def kb2(s):
    recs = [r for r in _tower(s)["panels"] if r["edge"] == 0]
    recs[0]["w"] += 300.0
    recs[-1]["w"] -= 300.0
    for r in recs[1:]:
        r["s0"] += 300.0


def kb3(s):
    _tower(s)["panels"][0]["kind"] = "vision"


def kb4(s):
    for b in s.bands:
        if b["band"] == "tower":
            last = {}
            for r in b["panels"]:
                last[r["edge"]] = max(last.get(r["edge"], 0), r["slot"])
            for r in b["panels"]:
                if r["orientation"] == "S" and r["kind"] == "solid" and 0 < r["slot"] < last[r["edge"]]:
                    r["kind"] = "vision"


def kb5(s):
    r = next(r for r in _tower(s)["panels"] if r.get("fin") is not None)
    r["fin"] += 1.0
    next(f for f in _tower(s)["fins"] if (f["edge"], f["slot"]) == (r["edge"], r["slot"]))["angle"] = r["fin"]


def kb6(s):
    frames = L.edge_frames(s.tiers[0])
    north = next(e for e, fr in enumerate(frames) if not L.edge_has_fins(fr["n"], s.params))
    r = next(r for r in _tower(s)["panels"] if r["edge"] == north and r["kind"] == "vision")
    r["fin"], r["fin_raw"] = 9.0, 9.0
    _tower(s)["fins"].append({"edge": north, "slot": r["slot"], "s": L.fin_root_s(r["s0"], r["w"], s.params),
                              "angle": 9.0, "type_id": _tower(s)["fins"][0]["type_id"]})


def kb7(s):
    s.floors[12]["level"] -= s.params.floor_h


def kb8(s):
    s.tiers[1] = [list(v) for v in L.offset_polygon([tuple(v) for v in s.tiers[0]], 2999.0)]


def kb9(s):
    _tower(s)["fins"].pop()


def kb10(s):
    lobby = s.band("lobby")
    lobby["rows"], lobby["height"] = 1, s.params.lobby_h


cases = {
    "KB0 clean": (CLEAN, True),
    "KB1 panel 1 mm narrow": (mutate(kb1), False),
    "KB2 closers asymmetric": (mutate(kb2), False),
    "KB3 closer as vision": (mutate(kb3), False),
    "KB4 south all vision": (mutate(kb4), False),
    "KB5 fin off bin": (mutate(kb5), False),
    "KB6 fin on north edge": (mutate(kb6), False),
    "KB7 floor 13 level": (mutate(kb7), False),
    "KB8 tier1 setback 2999": (mutate(kb8), False),
    "KB9 fin record dropped": (mutate(kb9), False),
    "KB10 lobby single row": (mutate(kb10), False),
}
wrong = []
for name, (sched, should_pass) in cases.items():
    failures = check_s1(sched)
    passed = not failures
    verdict = "as designed" if passed == should_pass else "GATE BROKEN"
    print(f"--- {name:26s} => {'pass' if passed else 'fail'} ({verdict})"
          + ("" if passed else f"   first: {failures[0]}  [+{len(failures) - 1}]"))
    if passed != should_pass:
        wrong.append(name)
sys.exit(report("S1 known-bad", [f"{name}: gate did not discriminate" for name in wrong]))
