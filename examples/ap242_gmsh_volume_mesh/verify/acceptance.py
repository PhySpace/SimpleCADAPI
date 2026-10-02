"""Acceptance checks for the ``bracket.py`` notebook and its exchange files.

    uv run python examples/ap242_gmsh_volume_mesh/export_step.py
    uv run python examples/ap242_gmsh_volume_mesh/export_obj.py
    uv run python examples/ap242_gmsh_volume_mesh/export_stl.py
    uv run python examples/ap242_gmsh_volume_mesh/verify/acceptance.py

The reference facts are those of the legacy direct-script bracket; the
rebuild must match them, because the Gmsh/CalculiX chain selects faces by
the interface tags and their geometry.

  A1 L body + ribs (the ``gusset_ribs`` cell): volume 10368 (analytic) and
     bbox [-2,-20,0] x [26,20,36]
  A2 final volume: analytic S1 - 270.177 within 0.1 %, legacy within 0.1 %
  A3 exactly three cylindrical faces matching the legacy hole cards
  A4 the body carries ``role.structural_l_bracket``
  A5 the package reopens and validates; root ``ap242_gmsh_bracket`` with the
     content hash of the current run; the BRep is one valid closed solid
  A6 package scene: the interface tag set is the legacy five-tag set, each
     face area within 1e-4 relative and centroid within 1e-3 mm
  A7 STEP / OBJ / STL exist and are not empty
  A8 parameter guards reject infeasible values
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import simplecadapi as scad
from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.GeomAbs import GeomAbs_SurfaceType
from simplecadapi import ql
from simplecadapi.inspect import brep
from simplecadapi.scene import parse_canonical_json, read_scene_package
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parents[1]
NOTEBOOK = HERE / "bracket.py"
OUT_DIR = HERE / "out"
PACKAGE_PATH = OUT_DIR / "ap242_gmsh_bracket.scadpkg"
EXPORTS = {suffix: OUT_DIR / f"ap242_gmsh_bracket.{suffix}" for suffix in ("step", "obj", "stl")}

ANALYTIC_S1 = 10368.0  # 5760 wall + 4480 shelf - 640 overlap + 2*486 ribs - 2*102 rib/wall
ANALYTIC_S2 = ANALYTIC_S1 - (2 * math.pi * 2.5**2 * 4.0 + math.pi * 3.0**2 * 4.0)
LEGACY_VOLUME = 10097.790499
LEGACY_BBOX = (-2.0, -20.0, 0.0, 26.0, 20.0, 36.0)
# (radius, axis, face centre) of the legacy hole faces
LEGACY_CYLINDERS = (
    (2.5, (1.0, 0.0, 0.0), (0.007508, -11.0, 22.311072)),
    (2.5, (1.0, 0.0, 0.0), (0.007508, 11.0, 22.311072)),
    (3.0, (0.0, 0.0, 1.0), (12.0, 0.0, 2.0)),
)
# tag -> (area, centroid) of the legacy interface faces
LEGACY_INTERFACES = {
    "interface.fixed_support": (1400.730092, (-2.0, 0.0, 17.878887)),
    "interface.load_surface": (835.725666, (14.527145, 0.0, 4.0)),
    "interface.mount_hole_1": (63.060366, (0.007508, -11.0, 22.311072)),
    "interface.mount_hole_2": (63.060366, (0.007508, 11.0, 22.311072)),
    "interface.load_hole": (75.398224, (12.0, 0.0, 2.0)),
}
# The notebook's params cells: an override must name every variable of a cell.
PARAM_CELLS = (
    ("BRACKET_WIDTH", "BRACKET_HEIGHT", "BRACKET_DEPTH", "PLATE_THICKNESS"),
    ("MOUNT_HOLE_RADIUS", "MOUNT_HOLE_SPACING", "MOUNT_HOLE_HEIGHT_RATIO",
     "LOAD_HOLE_RADIUS", "LOAD_HOLE_X", "CUT_OVERSHOOT"),
    ("RIB_THICKNESS", "RIB_HEIGHT", "RIB_DEPTH", "RIB_OFFSET_Y"),
)

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


def bbox(solid: scad.Solid) -> tuple[float, ...]:
    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(solid.wrapped, box, useTriangulation=False)
    return box.Get()


def close(a: tuple[float, ...], b: tuple[float, ...], tol: float) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def cylinder_cards(body: scad.Solid) -> list[tuple[float, tuple[float, ...], tuple[float, ...]]]:
    cards = []
    for face in ql.faces().where(ql.prop("geom.type", "==", "CYLINDER")).resolve(body):
        adaptor = BRepAdaptor_Surface(face.wrapped)
        if adaptor.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cylinder = adaptor.Cylinder()
        axis = cylinder.Axis().Direction()
        center = face.get_center()
        cards.append((cylinder.Radius(), (axis.X(), axis.Y(), axis.Z()),
                      (center.x, center.y, center.z)))
    return cards


def scene_interfaces(package: scad.ProductPackage) -> dict[str, tuple[float, tuple[float, ...]]]:
    """Interface-tagged faces of the package scene: tag -> (area, centroid)."""
    scene = read_scene_package(package.scene_bytes)
    found: dict[str, tuple[float, tuple[float, ...]]] = {}
    for record in scene.manifest["entity_assets"]:
        document = parse_canonical_json(scene.blobs[record["uri"]])
        for entity in document["entities"]:
            if entity["kind"] != "face":
                continue
            for tag in (str(t) for t in entity["tags"]):
                if tag.startswith("interface."):
                    properties = entity["properties"]
                    found[tag] = (float(properties["area"]),
                                  tuple(float(v) for v in properties["centroid"]))
    return found


run = run_notebook(NOTEBOOK)
bracket = run.product
assert isinstance(bracket, scad.Part)
body = bracket.body

ribbed = run.values["gusset_ribs"]
check("A1 L body + ribs", abs(ribbed.get_volume() - ANALYTIC_S1) / ANALYTIC_S1 <= 1e-3
      and close(bbox(ribbed), LEGACY_BBOX, 0.05),
      f"volume={ribbed.get_volume():.3f} bbox={tuple(round(v, 3) for v in bbox(ribbed))}")

volume = body.get_volume()
check("A2 final volume", abs(volume - ANALYTIC_S2) / ANALYTIC_S2 <= 1e-3
      and abs(volume - LEGACY_VOLUME) / LEGACY_VOLUME <= 1e-3,
      f"volume={volume:.6f} analytic={ANALYTIC_S2:.4f} legacy={LEGACY_VOLUME}")

cards = cylinder_cards(body)
matched = all(
    any(abs(radius - r) <= 0.01 and close(axis, a, 0.01) and close(center, c, 0.05)
        for r, a, c in LEGACY_CYLINDERS)
    for radius, axis, center in cards
)
check("A3 hole cylinders", len(cards) == 3 and matched,
      f"radii={sorted(round(card[0], 3) for card in cards)}")

tags = scad.list_tags(shape=body)
check("A4 role tag", "role.structural_l_bracket" in tags, tags)

package = scad.read_product_package(PACKAGE_PATH)
scad.validate_product_package(package)
root = package.root_definition
part = scad.materialize_definition(root)
assert isinstance(part, scad.Part)
inspection = brep.inspect_shape_rbrepinspection(part.body.wrapped, source=str(PACKAGE_PATH))
counts = inspection.counts
check("A5 package reopens as the current product",
      root.definition_id == "ap242_gmsh_bracket" and root.content_hash == run.definition.content_hash
      and inspection.valid and counts.get("solid", 0) == 1
      and counts.get("closed_shell", 0) == 1 and counts.get("open_shell", 0) == 0,
      f"id={root.definition_id}@{root.revision} solids={counts.get('solid', 0)}")

interfaces = scene_interfaces(package)
problems = [] if set(interfaces) == set(LEGACY_INTERFACES) else [f"tags {sorted(interfaces)}"]
for tag, (area, centroid) in LEGACY_INTERFACES.items():
    if tag not in interfaces:
        continue
    new_area, new_centroid = interfaces[tag]
    if abs(new_area - area) / area > 1e-4 or not close(new_centroid, centroid, 1e-3):
        problems.append(f"{tag} area={new_area:.4f} centroid={new_centroid}")
check("A6 interface faces", not problems, problems or f"{len(interfaces)} tags match legacy")

sizes = {name: (path.stat().st_size if path.is_file() else 0) for name, path in EXPORTS.items()}
check("A7 exports", all(sizes.values()), sizes)

nominal = {name: float(run.values[name]) for cell in PARAM_CELLS for name in cell}


def guard_message(**changes: float) -> str | None:
    """Run the notebook with *changes*; the guard's message, or None if it passed."""
    overrides: dict[str, float] = {}
    for cell in PARAM_CELLS:
        if any(name in changes for name in cell):
            overrides.update({name: changes.get(name, nominal[name]) for name in cell})
    try:
        run_notebook(NOTEBOOK, overrides=overrides)
    except AssertionError as exc:
        return str(exc)
    return None


# changes -> the guard message they must trigger
bad_sets = (
    (dict(PLATE_THICKNESS=15.0), "plate thickness must fit all spans"),
    (dict(MOUNT_HOLE_SPACING=4.0), "mount holes would merge"),
    (dict(LOAD_HOLE_X=27.0), "load hole outside shelf footprint"),
    (dict(LOAD_HOLE_RADIUS=1.0, RIB_OFFSET_Y=1.0), "ribs would overlap at the symmetry plane"),
    (dict(RIB_HEIGHT=34.0), "rib would overtop the wall"),
)
rejected = [(expected, guard_message(**changes)) for changes, expected in bad_sets]
check("A8 guards reject infeasible parameters",
      all(message == expected for expected, message in rejected),
      [message or f"NOT REJECTED ({expected})" for expected, message in rejected])

print(f"acceptance: {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
sys.exit(1 if failures else 0)
