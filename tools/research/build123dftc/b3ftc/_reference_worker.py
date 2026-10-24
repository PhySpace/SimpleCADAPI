"""Compare two STEP files in an independently selected OCCT environment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _validate_worker import _compare_reference, _read_step, _solid_count, _volume


def run(actual_step, reference_step):
    from simplecadapi._cpp import occt as _occt
    from simplecadapi._cpp.occt.Bnd import Bnd_Box
    from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
    actual = _read_step(actual_step)
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(actual, bounds, False, False)
    low, high = bounds.CornerMin(), bounds.CornerMax()
    bbox = [float(getattr(point, axis)()) for point in (low, high) for axis in "XYZ"]
    return {"status": "ok", **_compare_reference([actual], reference_step),
            "reference_kernel": _occt.__version__,
            "roundtrip_actual_volume": _volume(actual),
            "roundtrip_actual_bbox": bbox,
            "roundtrip_actual_solid_count": _solid_count(actual),
            "roundtrip_actual_valid": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual-step", type=Path, required=True)
    parser.add_argument("--reference-step", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.actual_step, args.reference_step)
    except Exception as exc:
        result = {"status": "reference_error", "reference_status": "error",
                  "reference_error": f"{type(exc).__name__}: {exc}"}
    args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
