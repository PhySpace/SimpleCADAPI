"""pcg_facade_tower band subassemblies: one `scad.assemble` definition per schedule band.

A band (tier x phase floor band, the lobby, a tier's parapet) is realized many times up the tower, so it is built once
in band-local coordinates (plan axes = world, z = 0 at the band's level) and the tower places it by level.
Contents: every panel, fin and corner piece of the band, placed from the layout frames and grounded (A2); the lobby
holds its stacked rows. Slabs and the canopy are placed by the tower, not here: a tier's first floor stands on the roof
below, so a slab is not a property of the floor band.

Component ids: r{row}-e{edge}-s{slot} (panel), r{row}-e{edge}-s{slot}-fin, r{row}-v{vertex} (corner).
"""
from __future__ import annotations

import simplecadapi as scad

import corners as C
import layout as L
import panels as P


def band_assembly_id(band_id: str) -> str:
    return f"band-{band_id}"


def band_components(sched: L.FacadeSchedule, band: dict) -> list[dict]:
    """[{component_id, type_id, frame}] in band-local coordinates (layout frames at the in-band row offsets)."""
    out = []
    for row in range(band["rows"]):
        z = row * band["height"]
        out += [{"component_id": f"r{row}-e{r['edge']}-s{r['slot']}", "type_id": r["type_id"],
                 "frame": L.panel_frame(sched, band, r, z)} for r in band["panels"]]
        out += [{"component_id": f"r{row}-e{r['edge']}-s{r['slot']}-fin", "type_id": r["type_id"],
                 "frame": L.fin_frame(sched, band, r, z)} for r in band["fins"]]
        out += [{"component_id": f"r{row}-v{r['vertex']}", "type_id": r["type_id"],
                 "frame": L.corner_frame(sched, band, r, z)} for r in band["corners"]]
    return out


def type_parts(sched: L.FacadeSchedule, type_ids) -> dict:
    """type id -> PartBuildResult (content-cached Part factories)."""
    out = {}
    for tid in sorted(set(type_ids)):
        spec = sched.types[tid]
        make = C.make_corner_part if spec["family"] == "corner" else P.make_panel_part
        out[tid] = make(tid, spec, sched.params)
    return out


def make_band_assembly(sched: L.FacadeSchedule, band_id: str) -> scad.AssemblyBuildResult:
    band = sched.band(band_id)
    comps = band_components(sched, band)
    parts = type_parts(sched, (c["type_id"] for c in comps))
    aid = band_assembly_id(band_id)

    @scad.assemble(id=aid, revision="1.0.0", definitions=tuple(parts.values()), project_root=P.ROOT)
    def build(band_id: str) -> scad.Assembly:
        # ---- feature: band-components (assemble) ----
        # every piece placed from its layout frame (x = edge tangent, y = up, z = outward) and grounded
        asm = scad.make_assembly_rassembly(assembly_id=aid, name=f"facade band {band_id}")
        for c in comps:
            f = c["frame"]
            asm = scad.add_component_rassembly(
                assembly=asm, item=parts[c["type_id"]].value, component_id=c["component_id"],
                placement=scad.make_placement_rplacement(origin=f["origin"], x_axis=f["x_axis"], y_axis=f["y_axis"]))
            asm = scad.ground_component_rassembly(assembly=asm, component_id=c["component_id"])
        return asm

    return build(band_id=band_id)
