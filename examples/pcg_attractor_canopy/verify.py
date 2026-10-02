"""Verify canopy package reopen, animation evidence, and parameter response.

Reads the artifacts written by ``export.py``; run that first.
"""
from __future__ import annotations

import json
from pathlib import Path

import simplecadapi as scad

OUT = Path(__file__).resolve().parent / "out"


def main() -> None:
    package = OUT / "attractor_canopy.scadpkg"
    if not package.is_file():
        raise FileNotFoundError(package)
    definition = scad.load_product_package(package)
    materialized = scad.materialize_definition(definition)
    if definition.definition_kind != "single_solid":
        raise AssertionError(definition.definition_kind)
    assert isinstance(materialized, scad.Part)
    volume = materialized.body.get_volume()
    if volume <= 0.0:
        raise AssertionError("reopened canopy volume is not positive")
    animation = json.loads((OUT / "animation_report.json").read_text(encoding="utf-8"))
    frames = animation["frames"]
    frame_paths = sorted((OUT / "frames").glob("frame_*.png"))
    if len(frames) != 12 or len(frame_paths) != 12:
        raise AssertionError(f"expected 12 synchronized frames, got reports={len(frames)} images={len(frame_paths)}")
    volumes = [float(frame["solid_volume_mm3"]) for frame in frames]
    if max(volumes) - min(volumes) < 1.0:
        raise AssertionError("attractor animation did not change the solid geometry")
    gif = OUT / "attractor_canopy.gif"
    if not gif.is_file() or gif.stat().st_size == 0:
        raise AssertionError("canopy GIF is missing or empty")
    result = {
        "definition_id": definition.definition_id,
        "definition_kind": definition.definition_kind,
        "reopened_volume_mm3": volume,
        "frame_count": len(frames),
        "volume_range_mm3": [min(volumes), max(volumes)],
        "gif_bytes": gif.stat().st_size,
        "artifacts_reopened": True,
    }
    (OUT / "verification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    print("PCG ATTRACTOR CANOPY VERIFY OK")


if __name__ == "__main__":
    main()
