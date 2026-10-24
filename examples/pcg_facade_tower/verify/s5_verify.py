"""S5 gate: the tower assembly (band subassemblies + slabs + canopy), measured on the solved, composed placements.

Band pieces are placed in world here as tower placement x band placement (gp_Trsf product, not the SDK path);
levels and setbacks are recomputed from the parameters, not read back from the schedule.

  T0 contents   tower component ids / items == tower_components; all grounded; one definition per unique ref;
                leaf part set == schedule type table; flattened piece count == schedule instance count
  T1 placement  every tower placement is a pure translation (0, 0, level); the SDK projection of the whole tower
                has pieces + slabs + canopy solids, the summed volume and the bbox z [0, height - j/2]
  V8 levels     floor f at lobby_h + (f - 1) floor_h with a band of tier (f - 1) // setback_every; parapet k and
                roof slab k top at tier k's roof; measured on sampled realizations: building-line plane of every edge
                at k x setback_depth inside tier 0's
  V1 closure    sampled realizations (lobby, first floor of each floor type, both floors of every setback, the top
                floor, every parapet): S4 closure at the tower level
  V2 clash      windows around every sampled junction (element below | element | slabs at the junction | parapet on a
                setback | canopy on the lobby), plus every component whose measured z range overlaps the window:
                Common volume == 0 on every bbox-touching pair
  V4 glass      whole-building WWR per orientation from the tagged definition glass x realizations == design (1e-6)
                and within 0.03 of the target
  V5 envelope   sampled realizations: panels span exactly [0, frame_d] off their edge's building line, corners
                <= frame_d, fin tips <= frame_d + fin_depth + 1
  V6 types      standard panel types (w_std x floor_h, vision + solid) == 2; fin types <= fin_bins
  A2 solve      warm rebuild: no dirty instances, no corrupt entries, identical definition hash

    ../../../.venv/bin/python s5_verify.py
"""
from __future__ import annotations

import sys
import time

from _common import report, tight_bbox
from s3_verify import TOL
from s4_verify import _points, _volume, check_clash, check_closure, check_solve, placed, trsf

import floor as F
import layout as L
import panels as P
import slabs as S
import simplecadapi as scad
from simplecadapi import Part
from tower import make_tower, tower_components

WWR_TOL = 0.03


def item_id(item) -> str:
    return item.part_id if isinstance(item, Part) else item.assembly_id


def expected_item_id(ref) -> str:
    kind, key = ref
    return F.band_assembly_id(key) if kind == "band" else S.slab_type_id(key) if kind == "slab" else S.CANOPY_ID


def level_of(p: L.FacadeParams, floor: int) -> float:
    return p.lobby_h + (floor - 1) * p.floor_h


def roof_of(p: L.FacadeParams, tier: int) -> float:
    return level_of(p, min(p.n_floors, (tier + 1) * p.setback_every) + 1)


def realize(component) -> dict:
    """World shapes of one tower component: band pieces keyed by their band id, a part by ''."""
    outer = trsf(component.placement)
    if isinstance(component.item, Part):
        from simplecadapi._cpp.occt.TopLoc import TopLoc_Location
        return {"": component.item.body.wrapped.Moved(TopLoc_Location(outer))}
    return {c.component_id: placed(c, outer) for c in component.item.components}


def band_of(sched: L.FacadeSchedule, component):
    return sched.band(component.item.assembly_id.removeprefix("band-"))


# ---------------------------------------------------------------- contents, placements, levels (every component)


def check_contents(sched: L.FacadeSchedule, asm, definition=None) -> tuple[list[str], dict]:
    bad, want = [], {c["component_id"]: c for c in tower_components(sched)}
    got = {c.component_id: c for c in asm.components}
    if set(got) != set(want):
        bad.append(f"T0 missing {sorted(set(want) - set(got))[:4]} extra {sorted(set(got) - set(want))[:4]}")
    for cid in sorted(set(got) & set(want)):
        if item_id(got[cid].item) != expected_item_id(want[cid]["ref"]):
            bad.append(f"T0 {cid}: item {item_id(got[cid].item)} != {expected_item_id(want[cid]['ref'])}")
    if set(asm.grounded_component_ids) != set(got):
        bad.append(f"T0 ungrounded {sorted(set(got) - set(asm.grounded_component_ids))[:4]}")
    if definition is not None:
        refs = {getattr(r, "definition_id", r) for r in definition.definition_refs}
        if len(refs) != len({c["ref"] for c in want.values()}):
            bad.append(f"T0 {len(refs)} definitions for {len({c['ref'] for c in want.values()})} refs")
        if set(definition.grounded_instance_ids) != set(got):
            bad.append(f"T0 definition grounds {len(definition.grounded_instance_ids)}/{len(got)}")
    leaves, pieces = set(), 0
    for c in asm.components:
        if not isinstance(c.item, Part):
            leaves |= {sub.item.part_id for sub in c.item.components}
            pieces += len(c.item.components)
    if leaves != set(sched.types):
        bad.append(f"T0 leaf parts: missing {sorted(set(sched.types) - leaves)[:3]} extra {sorted(leaves - set(sched.types))[:3]}")
    if pieces != sched.stats["n_instances"]:
        bad.append(f"T0 {pieces} facade pieces != schedule {sched.stats['n_instances']}")
    return bad, {"components": len(got), "pieces": pieces, "leaf_types": len(leaves)}


def check_levels(sched: L.FacadeSchedule, asm) -> list[str]:
    """T1 pure translations + V8 levels / tiers (placement values, every component)."""
    bad, p = [], sched.params
    n_tiers = (p.n_floors - 1) // p.setback_every + 1
    for c in asm.components:
        pl = c.placement
        axes = max(max(abs(a - b) for a, b in zip(pl.x_axis, (1, 0, 0))),
                   max(abs(a - b) for a, b in zip(pl.y_axis, (0, 1, 0))),
                   max(abs(a - b) for a, b in zip(pl.z_axis, (0, 0, 1))), abs(pl.origin[0]), abs(pl.origin[1]))
        if axes > TOL:
            bad.append(f"T1 {c.component_id}: placement is not a pure z translation ({axes:.3g})")
        cid, z = c.component_id, pl.origin[2]
        if cid.startswith("floor"):
            f = int(cid[5:])
            band = band_of(sched, c)
            if abs(z - level_of(p, f)) > TOL:
                bad.append(f"V8 {cid}: at z {z:.3f} != {level_of(p, f):.3f}")
            if band.get("tier") != (f - 1) // p.setback_every or band["band"] != L.Band.TOWER.value:
                bad.append(f"V8 {cid}: band {band['band_id']} is not a tier {(f - 1) // p.setback_every} floor band")
        elif cid.startswith("parapet"):
            k = int(cid[7:])
            if abs(z - roof_of(p, k)) > TOL or band_of(sched, c).get("tier") != k:
                bad.append(f"V8 {cid}: {band_of(sched, c)['band_id']} at z {z:.3f} != tier {k} roof {roof_of(p, k):.3f}")
        elif cid.startswith("slab-roof"):
            k = int(cid[9:])
            top = z + tight_bbox(c.item.body)[5]
            if abs(top - roof_of(p, k)) > TOL:
                bad.append(f"V8 {cid}: top {top:.3f} != tier {k} roof {roof_of(p, k):.3f}")
    roofs = sorted(c.component_id for c in asm.components if c.component_id.startswith("parapet"))
    if roofs != [f"parapet{k}" for k in range(n_tiers)]:
        bad.append(f"V8 parapets {roofs} != one per tier ({n_tiers})")
    return bad


def check_projection(sched: L.FacadeSchedule, asm) -> tuple[list[str], dict]:
    """T1: the SDK's flattened tower vs definition volumes x counts."""
    from simplecadapi._cpp.occt.TopAbs import TopAbs_SOLID
    from simplecadapi._cpp.occt.TopExp import TopExp_Explorer

    bad, p = [], sched.params
    vol_by_item, want_vol, want_solids = {}, 0.0, 0
    for c in asm.components:
        leaves = [c.item] if isinstance(c.item, Part) else [sub.item for sub in c.item.components]
        for leaf in leaves:
            if leaf.part_id not in vol_by_item:
                vol_by_item[leaf.part_id] = _volume(leaf.body.wrapped)
            want_vol += vol_by_item[leaf.part_id]
            want_solids += 1
    compound = scad.make_compound_from_assembly_rcompound(assembly=asm)
    solids, it = 0, TopExp_Explorer(compound.wrapped, TopAbs_SOLID)
    while it.More():
        solids += 1
        it.Next()
    vol = _volume(compound.wrapped)
    box = tight_bbox(compound)
    height = roof_of(p, (p.n_floors - 1) // p.setback_every) + p.parapet_h
    if solids != want_solids:
        bad.append(f"T1 SDK projection has {solids} solids != {want_solids}")
    if abs(vol - want_vol) > TOL * want_vol:
        bad.append(f"T1 SDK projection volume {vol:.6g} != {want_vol:.6g}")
    if abs(box[2]) > TOL or abs(box[5] - (height - p.joint / 2.0)) > TOL:
        bad.append(f"T1 SDK projection z [{box[2]:.3f}, {box[5]:.3f}] != [0, {height - p.joint / 2.0:.3f}]")
    return bad, {"solids": solids, "bbox": box, "height": height}


# ---------------------------------------------------------------- sampled realizations (geometry)


def sample_ids(sched: L.FacadeSchedule) -> list[str]:
    p = sched.params
    floors = {1, p.n_floors}
    floors |= {info["floors"][0] for info in sched.floor_types.values()}
    for k in range((p.n_floors - 1) // p.setback_every):
        top = (k + 1) * p.setback_every
        floors |= {top, top + 1}
    parapets = [c["component_id"] for c in tower_components(sched) if c["component_id"].startswith("parapet")]
    return ["lobby"] + [f"floor{f}" for f in sorted(floors)] + parapets


def windows(sched: L.FacadeSchedule, asm, sampled: list[str]) -> list[tuple[str, list[str]]]:
    """(name, tower component ids) around each sampled floor's lower junction, plus each tier's roof."""
    p, ids = sched.params, {c.component_id for c in asm.components}
    out = []
    for cid in sampled:
        if not cid.startswith("floor"):
            continue
        f = int(cid[5:])
        below = "lobby" if f == 1 else f"floor{f - 1}"
        group = [below, cid, f"slab-floor{f}"]
        if f == 1:
            group += ["canopy", "slab-ground"]
        if f > 1 and (f - 1) % p.setback_every == 0:
            k = (f - 1) // p.setback_every - 1
            group += [f"parapet{k}", f"slab-roof{k}"]
        out.append((f"{below}|{cid}", [g for g in group if g in ids]))
    for k in range((p.n_floors - 1) // p.setback_every + 1):
        top = min(p.n_floors, (k + 1) * p.setback_every)
        out.append((f"floor{top}|parapet{k}", [g for g in (f"floor{top}", f"parapet{k}", f"slab-roof{k}") if g in ids]))
    return out


def check_realization(sched: L.FacadeSchedule, component, shapes: dict) -> list[str]:
    """V1 at the tower level + V8 setback depth + V5 envelope for one band realization."""
    p, band, cid = sched.params, band_of(sched, component), component.component_id
    k = band["tier"]
    z_base = (0.0 if cid == "lobby" else roof_of(p, int(cid[7:])) if cid.startswith("parapet")
              else level_of(p, int(cid[5:])))
    bad = check_closure(sched, band, shapes, z_base=z_base, label=cid)
    base = L.edge_frames(L.tier_plans(p)[0])
    own = L.edge_frames(L.tier_plans(p)[k])
    env = p.frame_d + p.fin_depth + 1.0
    inset = {}
    for pid, shape in shapes.items():
        pts = _points(shape)
        if "-v" in pid:
            v = int(pid.split("-v")[1])
            edges = [(v - 1) % len(own), v]
        else:
            edges = [int(pid.split("-e")[1].split("-")[0])]
        for e in edges:
            fr = own[e]
            d = [(x - fr["v0"][0]) * fr["n"][0] + (y - fr["v0"][1]) * fr["n"][1] for x, y, _ in pts]
            if pid.endswith("-fin"):
                if max(d) > env:
                    bad.append(f"V5 {cid} {pid}: fin tip {max(d):.3f} > {env:.3f} off the building line")
            elif "-v" in pid:
                if max(d) > p.frame_d + TOL:
                    bad.append(f"V5 {cid} {pid}: corner {max(d):.4f} > frame_d off edge {e}")
            elif abs(min(d)) > TOL or abs(max(d) - p.frame_d) > TOL:
                bad.append(f"V5 {cid} {pid}: spans [{min(d):.4f}, {max(d):.4f}] != [0, frame_d] off its edge")
            if not pid.endswith("-fin") and "-v" not in pid:
                b0 = base[e]
                s = min((x - b0["v0"][0]) * b0["n"][0] + (y - b0["v0"][1]) * b0["n"][1] for x, y, _ in pts)
                inset[e] = min(inset.get(e, 0.0), s)
    for e, s in sorted(inset.items()):
        if abs(-s - k * p.setback_depth) > TOL:
            bad.append(f"V8 {cid} e{e}: building line {-s:.4f} inside tier 0's != {k} x setback {p.setback_depth}")
    return bad


def z_ranges(asm) -> dict:
    """Measured world z range of every tower component (local item bbox through its placement)."""
    local, out = {}, {}
    for c in asm.components:
        key = item_id(c.item)
        if key not in local:
            body = c.item.body if isinstance(c.item, Part) else scad.make_compound_from_assembly_rcompound(assembly=c.item)
            local[key] = tight_bbox(body)
        b, t = local[key], trsf(c.placement)
        zs = [t.Value(3, 1) * x + t.Value(3, 2) * y + t.Value(3, 3) * z + t.Value(3, 4)
              for x in (b[0], b[3]) for y in (b[1], b[4]) for z in (b[2], b[5])]
        out[c.component_id] = (min(zs), max(zs))
    return out


def check_sampled(sched: L.FacadeSchedule, asm) -> tuple[list[str], dict]:
    comps = {c.component_id: c for c in asm.components}
    sampled = [cid for cid in sample_ids(sched) if cid in comps]
    # each window also takes whatever actually stands in its z range (a misplaced component meets its real neighbours)
    zr, groups = z_ranges(asm), []
    for name, group in windows(sched, asm, sampled):
        lo, hi = min(zr[g][0] for g in group), max(zr[g][1] for g in group)
        groups.append((name, sorted(set(group) | {cid for cid, (a, b) in zr.items() if a < hi - 1.0 and b > lo + 1.0})))
    world, bad = {}, []
    for cid in {g for _, group in groups for g in group} | set(sampled):
        world[cid] = realize(comps[cid])
    for cid in sampled:
        bad += check_realization(sched, comps[cid], world[cid])
    pairs = 0
    for name, group in groups:
        shapes = {f"{g}/{pid}" if pid else g: s for g in group for pid, s in world[g].items()}
        clash, tested = check_clash({"band_id": name}, shapes)
        bad += clash
        pairs += tested
    return bad, {"sampled": len(sampled), "windows": len(groups), "clash_pairs": pairs}


# ---------------------------------------------------------------- whole-building glass + types


def check_glass(sched: L.FacadeSchedule, asm) -> tuple[list[str], dict]:
    from s4_verify import band_glass

    bad, p = [], sched.params
    per_band, glass, gross = {}, {}, {}
    for c in asm.components:
        if not c.component_id.startswith("floor"):
            continue
        band = band_of(sched, c)
        if band["band_id"] not in per_band:
            per_band[band["band_id"]] = band_glass(sched, band, c.item)
        g, _, a = per_band[band["band_id"]]
        for o in a:
            glass[o] = glass.get(o, 0.0) + g.get(o, 0.0)
            gross[o] = gross.get(o, 0.0) + a[o]
    wwr = {o: glass.get(o, 0.0) / gross[o] for o in sorted(gross)}
    design, target = L.design_wwr(sched), dict(p.wwr_target)
    for o, v in wwr.items():
        if abs(v - design[o]) > TOL:
            bad.append(f"V4 {o}: measured WWR {v:.6f} != design {design[o]:.6f}")
        if abs(v - target[o]) > WWR_TOL:
            bad.append(f"V4 {o}: WWR {v:.3f} off target {target[o]:.2f} by more than {WWR_TOL}")
    return bad, wwr


def check_types(sched: L.FacadeSchedule, asm) -> tuple[list[str], dict]:
    p, bad = sched.params, []
    leaves = {sub.item.part_id for c in asm.components if not isinstance(c.item, Part) for sub in c.item.components}
    std = sorted(t for t in leaves if sched.types[t]["family"] in ("vision", "solid")
                 and sched.types[t]["w"] == L._r(p.w_std) and sched.types[t]["h"] == L._r(p.floor_h))
    fins = sorted(t for t in leaves if sched.types[t]["family"] == "fin")
    if len(std) != 2:
        bad.append(f"V6 {len(std)} standard panel types {std} != 2")
    if len(fins) > p.fin_bins:
        bad.append(f"V6 {len(fins)} fin types > K = {p.fin_bins}")
    return bad, {"standard": std, "fins": len(fins)}


def check_tower(sched: L.FacadeSchedule, asm, definition=None) -> tuple[list[str], dict]:
    bad, info = check_contents(sched, asm, definition)
    bad += check_levels(sched, asm)
    proj, info["projection"] = check_projection(sched, asm)
    sampled, info["sampled"] = check_sampled(sched, asm)
    glass, info["wwr"] = check_glass(sched, asm)
    types, info["types"] = check_types(sched, asm)
    return bad + proj + sampled + glass + types, info


def main() -> int:
    sched = L.build_schedule(L.default_params())
    t0 = time.perf_counter()
    cold = make_tower(sched)
    t1 = time.perf_counter()
    warm = make_tower(sched)
    t2 = time.perf_counter()
    bad, info = check_tower(sched, cold.value, cold.definition)
    bad += check_solve("tower", cold, warm)
    t3 = time.perf_counter()
    pr, sm = info["projection"], info["sampled"]
    print(f"  tower: {info['components']} components, {len(cold.definition.definition_refs)} definitions, "
          f"{info['pieces']} facade pieces of {info['leaf_types']} types; SDK projection {pr['solids']} solids, "
          f"height {pr['height']:.0f}")
    print(f"  sampled {sm['sampled']} realizations, {sm['windows']} junction windows, {sm['clash_pairs']} clash pairs")
    print(f"  WWR " + " ".join(f"{o}={v:.3f}" for o, v in info["wwr"].items())
          + f"  (target {dict(sched.params.wwr_target)})")
    print(f"  standard types {info['types']['standard']}, {info['types']['fins']} fin types")
    print(f"  build {t1 - t0:.1f}s, rebuild {t2 - t1:.1f}s, checks {t3 - t2:.1f}s")
    return report("S5", bad)


if __name__ == "__main__":
    sys.exit(main())
