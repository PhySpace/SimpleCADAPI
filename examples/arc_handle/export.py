"""Check bolt insertion, then write the arched handle's package and render.

    uv run python examples/arc_handle/export.py

The model is the ``arc_handle.py`` notebook. Before exporting, this script
checks that each countersunk bolt can be inserted from +Y: the bolt's swept
envelope must not overlap the finished body. The product package and a
render go to ``out/``; ``fem_analysis.py`` reads the package from there.
"""

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

from arc_handle import countersunk_bolt_insertion_envelope

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
PACKAGE_PATH = OUT_DIR / "arc_handle.scadpkg"
RENDER_PATH = OUT_DIR / "arc_handle.png"


def check_insertion(*, body: scad.Solid, center_x: float, diameter: float, label: str) -> float:
    """Return the overlap of the bolt's insertion envelope with *body*; raise if any."""
    envelope = countersunk_bolt_insertion_envelope(center_x=center_x, through_diameter=diameter, label=label)
    remaining = scad.cut_rsolid(envelope, body, skip_non_intersecting=True, tracking_policy="graph")
    overlap = max(0.0, envelope.get_volume() - remaining.get_volume())
    if overlap > 1.0e-7:
        raise ValueError(f"{label} bolt insertion overlap={overlap:.9f} mm^3")
    print(f"{label}_countersunk_bolt_insertion: path=+Y_to_-Y overlap_volume={overlap:.9f}")
    return overlap


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "arc_handle.py")
    body = run.product.body
    hole_span = float(body.get_metadata("hole_span_mm"))
    for sign, label in ((-1.0, "left"), (1.0, "right")):
        check_insertion(
            body=body,
            center_x=sign * hole_span / 2.0,
            diameter=float(body.get_metadata(f"{label}_hole_diameter_mm")),
            label=label,
        )
    scad.capture(run.definition, PACKAGE_PATH)
    scad.render_screenshot_rpath(shapes=body, output_path=str(RENDER_PATH), view="auto", image_size=(1568, 1176), show_axes=True, show_legend=True, zoom=3.2)
    print(f"package={PACKAGE_PATH}")
    print(f"render={RENDER_PATH}")
    print(f"content_hash={run.definition.content_hash}")
    print(f"hole_axis={body.get_metadata('hole_axis')}")
    print(f"countersink_face={body.get_metadata('countersink_opening_face')}")
    print(f"tags={','.join(scad.list_tags(shape=body))}")
    print(f"package_bytes={PACKAGE_PATH.stat().st_size}")


if __name__ == "__main__":
    main()
