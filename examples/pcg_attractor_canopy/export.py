"""Animate, analyze, and export the attractor canopy.

Runs ``attractor_canopy.py`` once per animation frame with the attractor
overridden, renders the frames into a GIF, then packages and exports the
default canopy.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

from attractor import report, write_report

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE / "attractor_canopy.py"
OUT_DIR = HERE / "out"


def _frame_overrides(index: int, count: int) -> dict[str, float]:
    # The attractor cell defines all four values, so they are overridden together.
    angle = 2.0 * math.pi * index / count
    return {
        "ATTRACTOR_X_MM": 24.0 * math.cos(angle),
        "ATTRACTOR_Y_MM": 24.0 * math.sin(angle),
        "ATTRACTOR_STRENGTH": 0.9 * math.sin(angle * 1.5),
        "TWIST_DEGREES": 28.0,
    }


def _render_frame(part: scad.Part, path: Path) -> None:
    scad.render_screenshot_rpath(
        shapes=part.body,
        output_path=str(path),
        view="auto",
        image_size=(700, 700),
        style="studio",
        show_axes=False,
        show_legend=False,
    )


def _make_gif(frame_paths: list[Path], reports: list[dict[str, Any]], output: Path) -> None:
    from PIL import Image, ImageDraw

    frames: list[Image.Image] = []
    for path, frame_report in zip(frame_paths, reports):
        image = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(image)
        params = frame_report["parameters"]
        draw.rectangle((12, 12, 300, 76), fill=(18, 22, 28))
        draw.text((24, 22), f"attractor ({params['attractor_x_mm']:.1f}, {params['attractor_y_mm']:.1f}) mm", fill=(238, 242, 246))
        draw.text((24, 48), f"strength {params['attractor_strength']:.2f}  porosity {frame_report['nominal_porosity']:.2f}", fill=(238, 242, 246))
        frames.append(image)
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=160, loop=0, optimize=False)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame_dir = OUT_DIR / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    frame_reports: list[dict[str, Any]] = []
    for index in range(12):
        run = run_notebook(NOTEBOOK, overrides=_frame_overrides(index, 12))
        assert isinstance(run.product, scad.Part)
        frame_report = report(run.values["canopy_params"], run.product)
        frame_report["frame"] = index
        frame_reports.append(frame_report)
        frame_path = frame_dir / f"frame_{index:03d}.png"
        _render_frame(run.product, frame_path)
        frame_paths.append(frame_path)
    _make_gif(frame_paths, frame_reports, OUT_DIR / "attractor_canopy.gif")
    write_report(OUT_DIR / "animation_report.json", {"frames": frame_reports, "gif": "attractor_canopy.gif"})

    run = run_notebook(NOTEBOOK)
    assert isinstance(run.product, scad.Part)
    package = OUT_DIR / "attractor_canopy.scadpkg"
    capture = scad.capture(run.definition, package, include_scene=True)
    step = scad.exporter.step.export_product_package_to_step(data=package, output_path=OUT_DIR / "attractor_canopy.step")
    obj = scad.exporter.obj.export_product_package_to_obj(data=package, output_path=OUT_DIR / "attractor_canopy.obj", linear_deflection=0.15, angular_deflection_degrees=8.0)
    stl = scad.exporter.stl.export_product_package_to_stl(data=package, output_path=OUT_DIR / "attractor_canopy.stl", linear_deflection=0.15, angular_deflection_degrees=8.0)
    default_report = report(run.values["canopy_params"], run.product)
    default_report.update({
        "package": str(package),
        "capture_type": type(capture).__name__,
        "step": str(step.output_path),
        "obj": {"path": str(obj.output_path), "triangles": obj.triangle_count},
        "stl": {"path": str(stl.output_path), "triangles": stl.triangle_count},
        "gif": str(OUT_DIR / "attractor_canopy.gif"),
    })
    write_report(OUT_DIR / "canopy_report.json", default_report)
    print(json.dumps(default_report, indent=2, sort_keys=True))
    print("ATTRACTOR CANOPY FTC BUILD AND GIF OK")


if __name__ == "__main__":
    main()
