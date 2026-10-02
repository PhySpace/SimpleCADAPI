"""Check the FreeCAD translation written by ``export_fcstd.py``.

    uv run python examples/ap242_gmsh_volume_mesh/export_fcstd.py
    uv run python examples/ap242_gmsh_volume_mesh/verify/fcstd_check.py

  F1 the .FCStd exists and is not empty
  F2 the package reopens in this process, and the FCStd reopens in the
     FreeCAD runtime as an editable feature tree: parametric document
     objects (not a single dumb import), App::Part result volume within
     0.1 % of the delivered 10097.790499 mm^3

Needs a FreeCAD runtime (FreeCADCmd); without one F2 stops with
"checks-not-run".
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
OUT_DIR = HERE / "out"
FCSTD_PATH = OUT_DIR / "ap242_gmsh_bracket.FCStd"
PACKAGE_PATH = OUT_DIR / "ap242_gmsh_bracket.scadpkg"
EXPECTED_VOLUME = 10097.790499

REOPEN_SCRIPT = """
import FreeCAD
doc = FreeCAD.openDocument("__FCSTD_PATH__")
objects = list(doc.Objects)
print("FCSTD_OBJECTS", len(objects))
editable = 0
for obj in objects:
    print("OBJ", obj.Name, obj.TypeId, obj.Label)
    if not obj.TypeId.startswith("App::"):
        editable += 1
print("FCSTD_EDITABLE", editable)
final = [obj for obj in objects if obj.TypeId == "App::Part"]
if len(final) != 1:
    raise SystemExit("expected exactly one App::Part result container, got " + str(len(final)))
volume = float(final[0].Shape.Volume)
print("FCSTD_RESULT_VOLUME", volume)
FreeCAD.closeDocument(doc.Name)
"""


def discover_freecad() -> str:
    import os
    import shutil

    candidates = [
        shutil.which("FreeCADCmd"),
        shutil.which("freecadcmd"),
        shutil.which("FreeCAD"),
        "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd",
        "/Applications/FreeCAD.app/Contents/MacOS/FreeCAD",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise SystemExit("F2 no FreeCAD runtime found -> record checks-not-run")


def main() -> None:
    assert FCSTD_PATH.is_file() and FCSTD_PATH.stat().st_size > 0, f"F1 {FCSTD_PATH}"
    print(f"F1 PASS fcstd exists {FCSTD_PATH.stat().st_size} bytes")

    import simplecadapi as scad

    package = scad.read_product_package(PACKAGE_PATH)
    scad.validate_product_package(package)
    part = scad.materialize_definition(package.root_definition)
    assert isinstance(part, scad.Part)
    sdk_volume = part.body.get_volume()
    print(f"F2 PASS sdk fresh-process reopen volume={sdk_volume:.6f} @{package.root_definition.revision}")

    executable = discover_freecad()
    with tempfile.NamedTemporaryFile(mode="w", suffix="_fcstd_reopen.py", delete=False) as handle:
        handle.write(REOPEN_SCRIPT.replace("__FCSTD_PATH__", str(FCSTD_PATH)))
        script_path = handle.name
    completed = subprocess.run(
        [executable, script_path], check=True, text=True, capture_output=True, timeout=120
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith(("FCSTD_", "OBJ "))]
    summary = [line for line in lines if line.startswith("FCSTD_")]
    print("freecad_runtime", executable)
    for line in summary:
        print(line)
    object_count = int(next(l for l in summary if l.startswith("FCSTD_OBJECTS")).split()[1])
    editable = int(next(l for l in summary if l.startswith("FCSTD_EDITABLE")).split()[1])
    volume = float(next(l for l in summary if l.startswith("FCSTD_RESULT_VOLUME")).split()[1])
    assert object_count >= 5, f"F2 feature tree too small: {object_count} objects"
    assert editable >= 5, f"F2 not an editable feature tree: {editable} non-App objects"
    assert abs(volume - EXPECTED_VOLUME) / EXPECTED_VOLUME <= 1e-3, (
        f"F2 fcstd result volume {volume} vs {EXPECTED_VOLUME}"
    )
    print(f"F2 PASS fcstd reopens: {object_count} document objects ({editable} editable features), "
          f"App::Part result volume {volume:.4f} matches ({abs(volume - EXPECTED_VOLUME) / EXPECTED_VOLUME:.2e})")
    for line in lines:
        if line.startswith("OBJ "):
            print("  ", line)
    print("fcstd check: ALL PASS")


if __name__ == "__main__":
    main()
