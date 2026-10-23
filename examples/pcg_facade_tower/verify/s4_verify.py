"""S4 gate: band subassemblies (floor types, lobby, parapets), measured on the solved component placements.

Every component is placed here from its solved `Placement` (columns x, y, z, origin -> gp_Trsf), independently of
the layout frames, then:
  A0 contents   component ids / types == schedule (panels + fins + corners per row); definitions == the band's
                unique type ids; every component grounded (assembly and definition)
  A1 placement  placement == layout frame (origin, x = t, y = +Z) and z_axis == outward normal n; the SDK's own
                projection (make_compound_from_assembly) has the same volume and bbox as ours
  V1 closure    per row and edge, corner v_e | panels by slot | corner v_e+1 in that order along t (vertex
                projection), consecutive gap == joint (A7 tolerance), no overlap; fins excluded. Every piece spans
                z [row + j/2, row + h - j/2]; stacked lobby rows meet at a joint
  V2 clash      all component pairs whose boxes touch: Common volume == 0 (panels, fins, corners, both rows)
  V4 glass      band glass == sum of tagged glass area on the definition bodies (tags stay local, SDK scope rule)
                == layout design glass; WWR of this band per orientation is reported
  A2 solve      rebuild is deterministic: a second build of the same band carries the identical definition hash

    ../../../.venv/bin/python s4_verify.py [band_id ...]      (default: every band of the default schedule)
"""
from __future__ import annotations

import sys
import time

from _common import report, tight_bbox
from s3_verify import JOINT_TOL, TOL

import floor as F
import layout as L
import panels as P
import simplecadapi as scad
from simplecadapi import ql

CLASH_TOL = 1.0e-3  # mm^3 of Common volume


def trsf(pl):
    """gp_Trsf of a solved Placement (columns x, y, z, origin)."""
    from simplecadapi._cpp.occt.gp import gp_Trsf

    (xx, xy, xz), (yx, yy, yz), (zx, zy, zz), (ox, oy, oz) = pl.x_axis, pl.y_axis, pl.z_axis, pl.origin
    out = gp_Trsf()
    out.SetValues(xx, yx, zx, ox, xy, yy, zy, oy, xz, yz, zz, oz)
    return out


def placed(component, outer=None):
    """World shape of a band component from its solved placement (diagnostic, not the SDK path); `outer` = the
    parent's gp_Trsf when the band is itself placed (tower)."""
    from simplecadapi._cpp.occt.TopLoc import TopLoc_Location

    t = trsf(component.placement)
    if outer is not None:
        t = outer.Multiplied(t)
    return component.item.body.wrapped.Moved(TopLoc_Location(t))


def _points(shape) -> list[tuple]:
    from simplecadapi._cpp.occt.BRep import BRep_Tool
    from simplecadapi._cpp.occt.TopAbs import TopAbs_VERTEX
    from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
    from simplecadapi._cpp.occt.TopoDS import TopoDS

    out, it = [], TopExp_Explorer(shape, TopAbs_VERTEX)
    while it.More():
        pnt = BRep_Tool.Pnt_s(TopoDS.Vertex_s(it.Current()))
        out.append((pnt.X(), pnt.Y(), pnt.Z()))
        it.Next()
    return out


def _volume(shape) -> float:
    from simplecadapi._cpp.occt.BRepGProp import BRepGProp
    from simplecadapi._cpp.occt.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _common_volume(a, b) -> float:
    from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Common

    op = BRepAlgoAPI_Common(a, b)
    if not op.IsDone():
        raise RuntimeError("Common failed")
    return _volume(op.Shape())


def expected_components(sched: L.FacadeSchedule, band: dict) -> dict:
    return {c["component_id"]: c for c in F.band_components(sched, band)}


def check_contents(sched: L.FacadeSchedule, band: dict, asm, definition=None) -> list[str]:
    bad, want = [], expected_components(sched, band)
    got = {c.component_id: c for c in asm.components}
    if set(got) != set(want):
        bad.append(f"A0 {band['band_id']}: missing {sorted(set(want) - set(got))[:4]} "
                   f"extra {sorted(set(got) - set(want))[:4]}")
    for cid in sorted(set(got) & set(want)):
        if got[cid].item.part_id != want[cid]["type_id"]:
            bad.append(f"A0 {band['band_id']} {cid}: type {got[cid].item.part_id} != {want[cid]['type_id']}")
    if set(asm.grounded_component_ids) != set(got):
        bad.append(f"A0 {band['band_id']}: ungrounded {sorted(set(got) - set(asm.grounded_component_ids))[:4]}")
    if definition is not None:
        if set(definition.grounded_instance_ids) != set(got):
            bad.append(f"A0 {band['band_id']}: definition grounds {len(definition.grounded_instance_ids)}/{len(got)}")
        refs = {getattr(r, "definition_id", r) for r in definition.definition_refs}
        types = {c["type_id"] for c in want.values()}
        if len(refs) != len(types):
            bad.append(f"A0 {band['band_id']}: {len(refs)} definitions for {len(types)} types")
    return bad


def check_placements(sched: L.FacadeSchedule, band: dict, asm, shapes: dict) -> list[str]:
    bad, want = [], expected_components(sched, band)
    normals = [fr["n"] for fr in L.edge_frames(sched.tiers[band["tier"]])]
    for c in asm.components:
        if c.component_id not in want:
            continue
        f, pl = want[c.component_id]["frame"], c.placement
        edge = (int(c.component_id.split("-v")[1]) if "-v" in c.component_id
                else int(c.component_id.split("-e")[1].split("-")[0]))
        n = normals[edge - 1] if "-v" in c.component_id else normals[edge]  # corner x = incoming edge
        dev = max(max(abs(a - b) for a, b in zip(pl.origin, f["origin"])),
                  1.0e3 * max(abs(a - b) for a, b in zip(pl.x_axis, f["x_axis"])),
                  1.0e3 * max(abs(a - b) for a, b in zip(pl.y_axis, f["y_axis"])),
                  1.0e3 * max(abs(a - b) for a, b in zip(pl.z_axis, (n[0], n[1], 0.0))))
        if dev > TOL:
            bad.append(f"A1 {band['band_id']} {c.component_id}: placement off layout frame by {dev:.3g}")
    compound = scad.make_compound_from_assembly_rcompound(assembly=asm)
    vol = sum(_volume(s) for s in shapes.values())
    sdk_vol = _volume(compound.wrapped)
    if abs(sdk_vol - vol) > TOL * vol:
        bad.append(f"A1 {band['band_id']}: SDK projection volume {sdk_vol:.6g} != {vol:.6g}")
    ours = [tight_bbox(s) for s in shapes.values()]
    box = tuple(min(b[i] for b in ours) for i in range(3)) + tuple(max(b[i] for b in ours) for i in range(3, 6))
    if max(abs(a - b) for a, b in zip(tight_bbox(compound), box)) > TOL:
        bad.append(f"A1 {band['band_id']}: SDK projection bbox != ours")
    return bad


def check_closure(sched: L.FacadeSchedule, band: dict, shapes: dict, z_base: float = 0.0,
                  label: str | None = None) -> list[str]:
    """`z_base` = the band's level when the shapes are tower-placed; `label` names the realization in messages."""
    bad, p = [], sched.params
    name = label or band["band_id"]
    frames = L.edge_frames(sched.tiers[band["tier"]])
    j, h, n = p.joint, band["height"], len(frames)
    spans = {}
    for cid, shape in shapes.items():
        z = [pt[2] for pt in _points(shape)]
        spans[cid] = (min(z), max(z))
    for row in range(band["rows"]):
        z0 = z_base + row * h
        for cid in (c for c in shapes if c.startswith(f"r{row}-")):
            lo, hi = spans[cid]
            if abs(lo - (z0 + j / 2.0)) > TOL or abs(hi - (z0 + h - j / 2.0)) > TOL:
                bad.append(f"V1 {name} {cid}: z span [{lo:.6f}, {hi:.6f}] != row {row} band")
        for e, fr in enumerate(frames):
            order = ([f"r{row}-v{e}"] + [f"r{row}-e{e}-s{r['slot']}" for r in
                                         sorted((r for r in band["panels"] if r["edge"] == e), key=lambda r: r["slot"])]
                     + [f"r{row}-v{(e + 1) % n}"])
            missing = [cid for cid in order if cid not in shapes]
            if missing:
                bad.append(f"V1 {name} r{row} e{e}: no piece at {missing[:3]}")
                order = [cid for cid in order if cid in shapes]
            v0, t = fr["v0"], fr["t"]
            ext = {}
            for cid in order:
                s = [(x - v0[0]) * t[0] + (y - v0[1]) * t[1] for x, y, _ in _points(shapes[cid])]
                ext[cid] = (min(s), max(s))
            ext[order[0]] = (float("-inf"), ext[order[0]][1])  # corner at the edge start: only its max faces edge e
            ext[order[-1]] = (ext[order[-1]][0], float("inf"))  # corner at the edge end: only its min
            by_pos = sorted(order, key=lambda cid: ext[cid][0])
            if by_pos != order:
                bad.append(f"V1 {name} r{row} e{e}: order along t {by_pos[:3]}... != schedule")
                continue
            for a, b in zip(order, order[1:]):
                gap = ext[b][0] - ext[a][1]
                if abs(gap - j) > JOINT_TOL:
                    bad.append(f"V1 {name} {a} | {b}: gap {gap:.6f} != joint {j}")
    for row in range(1, band["rows"]):  # stacked lobby rows
        below = max(spans[c][1] for c in shapes if c.startswith(f"r{row - 1}-"))
        above = min(spans[c][0] for c in shapes if c.startswith(f"r{row}-"))
        if abs(above - below - j) > TOL:
            bad.append(f"V1 {name} rows {row - 1}|{row}: gap {above - below:.6f} != joint {j}")
    return bad


def check_clash(band: dict, shapes: dict) -> tuple[list[str], int]:
    from simplecadapi._cpp.occt.Bnd import Bnd_Box
    from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib

    boxes = {}
    for cid, shape in shapes.items():
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box)
        box.Enlarge(1.0e-3)
        boxes[cid] = box
    bad, ids, tested = [], sorted(shapes), 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if boxes[a].IsOut(boxes[b]):
                continue
            tested += 1
            v = _common_volume(shapes[a], shapes[b])
            if v > CLASH_TOL:
                bad.append(f"V2 {band['band_id']} {a} x {b}: Common volume {v:.4g} mm^3")
    return bad, tested


def band_glass(sched: L.FacadeSchedule, band: dict, asm) -> tuple[dict, dict, dict]:
    """(measured glass, design glass, gross facade area) per orientation, one realization of the band."""
    p, area_by_type = sched.params, {}
    orient = {f"r{row}-e{r['edge']}-s{r['slot']}": r["orientation"]
              for row in range(band["rows"]) for r in band["panels"]}
    glass, design, gross = {}, {}, {}
    for c in asm.components:
        if c.component_id not in orient:
            continue
        tid = c.item.part_id
        if tid not in area_by_type:
            area_by_type[tid] = sum(f.get_area() for f in ql.faces().where(ql.tag(P.GLASS_TAG)).resolve(c.item.body))
        o = orient[c.component_id]
        glass[o] = glass.get(o, 0.0) + area_by_type[tid]
    for rec in band["panels"]:
        if rec["kind"] == "vision":
            spandrel = sched.types[rec["type_id"]]["spandrel"]
            design[rec["orientation"]] = (design.get(rec["orientation"], 0.0)
                                          + band["rows"] * L._glass_area(rec["w"], band["height"], spandrel, p))
    for fr in L.edge_frames(sched.tiers[band["tier"]]):
        o = L.orientation(fr["n"])
        gross[o] = gross.get(o, 0.0) + (fr["length"] - 2.0 * p.corner_c) * band["height"] * band["rows"]
    return glass, design, gross


def check_glass(sched: L.FacadeSchedule, band: dict, asm) -> tuple[list[str], dict]:
    glass, design, gross = band_glass(sched, band, asm)
    bad = []
    for o in sorted(set(glass) | set(design)):
        g, d = glass.get(o, 0.0), design.get(o, 0.0)
        if abs(g - d) > TOL * max(d, 1.0):
            bad.append(f"V4 {band['band_id']} {o}: tagged glass {g:.1f} != design {d:.1f}")
    return bad, {o: glass.get(o, 0.0) / gross[o] for o in sorted(gross)}


def check_band(sched: L.FacadeSchedule, band: dict, asm, definition=None) -> tuple[list[str], dict]:
    bad = check_contents(sched, band, asm, definition)
    shapes = {c.component_id: placed(c) for c in asm.components}
    bad += check_placements(sched, band, asm, shapes)
    bad += check_closure(sched, band, shapes)
    clash, tested = check_clash(band, shapes)
    glass, wwr = check_glass(sched, band, asm)
    return bad + clash + glass, {"components": len(shapes), "clash_pairs": tested, "wwr": wwr}


def check_solve(band_id: str, cold, warm) -> list[str]:
    bad = []
    if warm.definition.content_hash != cold.definition.content_hash:
        bad.append(f"A2 {band_id}: rebuild changed the definition hash")
    return bad


def main(band_ids: list[str]) -> int:
    sched = L.build_schedule(L.default_params())
    failures = []
    for band_id in band_ids or [b["band_id"] for b in sched.bands]:
        start = time.perf_counter()
        band = sched.band(band_id)
        cold = F.make_band_assembly(sched, band_id)
        warm = F.make_band_assembly(sched, band_id)
        bad, info = check_band(sched, band, cold.value, cold.definition)
        bad += check_solve(band_id, cold, warm)
        failures += bad
        wwr = " ".join(f"{o}={v:.3f}" for o, v in info["wwr"].items())
        print(f"  {band_id:14s} {info['components']:4d} comps  {len(cold.definition.definition_refs):3d} defs  "
              f"{info['clash_pairs']:4d} clash pairs  wwr {wwr}  {'ok' if not bad else f'{len(bad)} FAIL'}  "
              f"({time.perf_counter() - start:.1f}s)")
    return report("S4", failures)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
