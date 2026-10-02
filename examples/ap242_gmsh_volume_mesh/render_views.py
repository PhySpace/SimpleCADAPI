"""Render the demo gallery views of the bracket notebook.

    uv run python examples/ap242_gmsh_volume_mesh/render_views.py

Views (demo/build.py gallery): isometric, top, and the mount-hole detail.
"""

from __future__ import annotations

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"

# file name -> (view, zoom)
VIEWS = {
    "render_iso.png": ((30.0, 45.0), 4.0),
    "render_top.png": ((90.0, 0.0), 4.0),
    "render_detail.png": ((25.0, 20.0), 9.0),
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bracket = run_notebook(HERE / "bracket.py").product
    assert isinstance(bracket, scad.Part)
    for name, (view, zoom) in VIEWS.items():
        path = scad.render_screenshot_rpath(
            shapes=bracket.body, output_path=str(OUT_DIR / name), view=view, zoom=zoom,
            image_size=(1400, 900), show_legend=False, show_callouts=False)
        print(f"rendered {path}")


if __name__ == "__main__":
    main()
