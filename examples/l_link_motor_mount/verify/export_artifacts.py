"""Reopen every artifact written by ``export.py`` (no live solids) and compare with the export facts.

    uv run python examples/l_link_motor_mount/export.py
    uv run python examples/l_link_motor_mount/verify/export_artifacts.py

  X0 every expected product exported (export.py records capture failures as "blocked")
  X1 package: read_product_package validates each .scadpkg; root kind single_solid/assembly, root id as built
     (l-link-motor-mount-<preset> / l-link-body / l-link-shell / l-link-adapter-<preset>) and the content
     hash of the notebook product it was captured from
  X2 STEP: load_step_rshape (valid BREP, single root) -> solid count == product bodies and total volume == the
     reference volumes recorded at export from the notebook products (rel 1e-4)
  X3 STL: binary header triangle count == export report, > 0; every vertex inside the STEP bbox + 0.05
  X4 assembly facts: components == (body, shell, plate), strict-solve residuals within tolerance
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

import simplecadapi as scad
from simplecadapi.inspect import brep

OUT_DIR = Path(__file__).resolve().parents[1] / "out"
ROOT_IDS = {"l_link_body": ("single_solid", "l-link-body"), "l_link_shell": ("single_solid", "l-link-shell")}
EXPECTED = ["l_link_body", "l_link_shell", "adapter_plate_star3", "adapter_plate_center4",
            "l_link_assembly_star3", "l_link_assembly_center4"]


def _solids(shape) -> list:
    ex, out = TopExp_Explorer(shape, TopAbs_SOLID), []
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def _volume(shape) -> float:
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


def _bbox(shape) -> tuple:
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    return b.Get()


def _stl(path: Path) -> tuple[int, list]:
    raw = path.read_bytes()
    n = struct.unpack_from("<I", raw, 80)[0]
    assert len(raw) == 84 + 50 * n, f"{path.name}: not a binary STL of {n} triangles ({len(raw)} bytes)"
    verts = [struct.unpack_from("<3f", raw, 84 + 50 * i + 12 + 12 * k) for i in range(n) for k in range(3)]
    return n, verts


def main() -> int:
    facts = json.loads((OUT_DIR / "export_facts.json").read_text())
    failures = []

    def ck(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
        if not ok:
            failures.append(name)

    for stem in EXPECTED:
        entry = facts["products"].get(stem, {"blocked": "not in export_facts.json"})
        ck(f"X0 {stem} exported", "blocked" not in entry, entry.get("blocked", "")[:300])
        if "blocked" in entry:
            continue
        pkg = scad.read_product_package(OUT_DIR / entry["package"])
        if stem.startswith("l_link_assembly_"):
            want = ("assembly", f"l-link-motor-mount-{stem.rsplit('_', 1)[1]}")
        elif stem.startswith("adapter_plate_"):
            want = ("single_solid", f"l-link-adapter-{stem.rsplit('_', 1)[1]}")
        else:
            want = ROOT_IDS[stem]
        root_hash = pkg.root_definition.content_hash
        ck(f"X1 {stem} package", (pkg.root_kind, pkg.root_id) == want and root_hash == entry["content_hash"],
           f"root=({pkg.root_kind}, {pkg.root_id}) want={want} root_hash={root_hash[7:19]} "
           f"built={entry['content_hash'][7:19]}")

        shape = brep.load_step_rshape(OUT_DIR / Path(entry["package"]).with_suffix(".step").name)
        solids, vref = _solids(shape), entry["volumes"]
        v, v0 = sum(_volume(s) for s in solids), sum(vref.values())
        ck(f"X2 {stem} STEP", len(solids) == len(vref) and abs(v - v0) <= 1e-4 * v0,
           f"solids={len(solids)} want={len(vref)} V={v:.3f} ref={v0:.3f}")

        n, verts = _stl(OUT_DIR / Path(entry["package"]).with_suffix(".stl").name)
        x0, y0, z0, x1, y1, z1 = _bbox(shape)
        out = [q for q in verts if not (x0 - 0.05 <= q[0] <= x1 + 0.05 and y0 - 0.05 <= q[1] <= y1 + 0.05
                                        and z0 - 0.05 <= q[2] <= z1 + 0.05)]
        ck(f"X3 {stem} STL", n == entry["stl"]["triangle_count"] and n > 0 and not out,
           f"tri={n} report={entry['stl']['triangle_count']} outside_step_bbox={len(out)} "
           f"bbox={[round(c, 2) for c in (x0, y0, z0, x1, y1, z1)]}")

        if stem.startswith("l_link_assembly_"):
            ck(f"X4 {stem} assembly", entry["components"] == ["body", "shell", "plate"] and entry["residuals_ok"],
               f"components={entry['components']} residuals_ok={entry['residuals_ok']}")

    print(f"export artifacts: {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
