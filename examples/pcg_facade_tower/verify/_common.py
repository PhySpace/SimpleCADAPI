"""Shared verifier helpers (diagnostic only; never used inside the model graph)."""
from __future__ import annotations

import sys
from pathlib import Path

PART_DIR = Path(__file__).resolve().parents[1]
if str(PART_DIR) not in sys.path:
    sys.path.insert(0, str(PART_DIR))

OUT = Path(__file__).resolve().parent / "renders"


def tight_bbox(shape) -> tuple:
    """Exact bbox (AddOptimal, no gap); accepts a SimpleCAD shape or a raw TopoDS_Shape."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(getattr(shape, "wrapped", shape), box, useTriangulation=False)
    return box.Get()


def report(title: str, failures: list) -> int:
    print(f"== {title}: {'PASS' if not failures else 'FAIL'}")
    for failure in failures:
        print(f"   - {failure}")
    return 1 if failures else 0


def place_shape(shape, frame: dict):
    """Diagnostic placement (layout frame -> world) for local-frame solids: y_axis must be +Z.
    Local x -> x_axis, y -> +Z, z -> x_axis x Z (the outward normal)."""
    import math

    import simplecadapi as scad

    ox, oy, oz = frame["origin"]
    tx, ty, _ = frame["x_axis"]
    assert tuple(frame["y_axis"]) == (0.0, 0.0, 1.0)
    upright = scad.rotate_shape(shape=shape, angle=90.0, axis=(1.0, 0.0, 0.0), origin=(0.0, 0.0, 0.0))
    turned = scad.rotate_shape(shape=upright, angle=math.degrees(math.atan2(ty, tx)), axis=(0.0, 0.0, 1.0),
                               origin=(0.0, 0.0, 0.0))
    return scad.translate_shape(shape=turned, vector=(ox, oy, oz))


def min_distance(a, b) -> float:
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    dist = BRepExtrema_DistShapeShape(getattr(a, "wrapped", a), getattr(b, "wrapped", b))
    dist.Perform()
    if not dist.IsDone():
        raise RuntimeError("distance computation failed")
    return dist.Value()
