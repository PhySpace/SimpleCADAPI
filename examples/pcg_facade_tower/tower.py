"""pcg_facade_tower tower assembly: band subassembly instances by level + slabs + the entrance canopy.

Tower frame = world. Band subassemblies are band-local (plan axes = world, z = 0 at the band's level), so every
instance is a pure translation to its level: the lobby at 0 (it holds both rows), each floor at its floor level
(floor type tier{k}-phase{j}), each tier's parapet at its roof. Slabs translate by their instance level
(`layout.slab_instances`); the canopy is built where it stands. Everything is grounded (A2).

Component ids: lobby, floor{f}, parapet{k}, slab-{role}, canopy.

    ../../.venv/bin/python tower.py [rect|chamfer|l_shape]     # build + print counts
"""
from __future__ import annotations

import sys
import time

import simplecadapi as scad

import floor as F
import layout as L
import panels as P
import slabs as S

TOWER_ID = "facade-tower"


def tower_components(sched: L.FacadeSchedule) -> list[dict]:
    """[{component_id, ref, level}]: ref = ("band", band_id) | ("slab", tier) | ("canopy", None)."""
    out = [{"component_id": "lobby", "ref": ("band", "lobby"), "level": 0.0}]
    out += [{"component_id": f"floor{r['floor']}", "ref": ("band", r["floor_type"]), "level": r["level"]}
            for r in sched.floors]
    out += [{"component_id": b["band_id"], "ref": ("band", b["band_id"]), "level": b["level"]}
            for b in sched.bands if b["band"] == L.Band.PARAPET.value]
    out += [{"component_id": f"slab-{i['role']}", "ref": ("slab", i["tier"]), "level": i["level"]}
            for i in L.slab_instances(sched)]
    out.append({"component_id": "canopy", "ref": ("canopy", None), "level": 0.0})
    return out


def definitions(sched: L.FacadeSchedule, comps: list[dict]) -> dict:
    """ref -> build result (band AssemblyBuildResult / slab or canopy PartBuildResult), each built once."""
    out = {}
    for ref in dict.fromkeys(c["ref"] for c in comps):
        kind, key = ref
        out[ref] = (F.make_band_assembly(sched, key) if kind == "band"
                    else S.make_slab_part(sched, key) if kind == "slab" else S.make_canopy_part(sched))
    return out


def make_tower(sched: L.FacadeSchedule) -> scad.AssemblyBuildResult:
    comps = tower_components(sched)
    defs = definitions(sched, comps)

    @scad.assemble(id=TOWER_ID, revision="1.0.0", definitions=tuple(defs.values()), project_root=P.ROOT)
    def build(plan_kind: str, n_floors: int) -> scad.Assembly:
        # ---- feature: tower-stack (assemble) ----
        # band instances, slabs and canopy translated to their levels (world axes) and grounded
        asm = scad.make_assembly_rassembly(assembly_id=TOWER_ID, name=f"facade tower {plan_kind} {n_floors}F")
        for c in comps:
            asm = scad.add_component_rassembly(
                assembly=asm, item=defs[c["ref"]].value, component_id=c["component_id"],
                placement=scad.make_placement_rplacement(origin=(0.0, 0.0, c["level"]), x_axis=(1.0, 0.0, 0.0),
                                                         y_axis=(0.0, 1.0, 0.0)))
            asm = scad.ground_component_rassembly(assembly=asm, component_id=c["component_id"])
        return asm

    return build(plan_kind=sched.params.plan_kind.value, n_floors=sched.params.n_floors)


if __name__ == "__main__":
    kind = L.PlanKind(sys.argv[1]) if len(sys.argv) > 1 else L.PlanKind.CHAMFER
    start = time.perf_counter()
    s = L.build_schedule(L.default_params(plan_kind=kind))
    r = make_tower(s)
    print(f"{kind.value}: {len(r.value.components)} tower components, {len(r.definition.definition_refs)} definitions, "
          f"{s.stats['n_instances']} facade pieces, {time.perf_counter() - start:.1f}s")
