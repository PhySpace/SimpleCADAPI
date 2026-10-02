"""Render the 4-view demo set for flange_plate (8-hole, PCD 84.5).

Views (BUILD_PLAN S3 visual contract):
  render_iso.png    (30, 45)   isometric
  render_front.png  (0, 0)     front (+X toward viewer)
  render_top.png    (90, 0)    top down +Z
  render_detail.png (25, 20) zoom 9 — bolt hole + boss root fillet close-up
"""
from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(parents=True, exist_ok=True)

body = run_notebook(HERE / "flange_plate.py").product.body

views = {
    "render_iso.png": dict(view=(30.0, 45.0), zoom=4.0),
    "render_front.png": dict(view=(0.0, 0.0), zoom=4.0),
    "render_top.png": dict(view=(90.0, 0.0), zoom=4.0),
    "render_detail.png": dict(view=(25.0, 20.0), zoom=9.0),
}
for name, kw in views.items():
    path = scad.render_screenshot_rpath(
        shapes=body, output_path=str(OUT / name),
        image_size=(1400, 900), show_legend=False, show_callouts=False, **kw)
    print(f"rendered {path}")
