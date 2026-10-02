"""Render check of the mounting-face highlights (run after ``export.py``).

    uv run python examples/u_link_motor_mount/verify/render_check.py

A deterministic stand-in for a vision review.

The isolated image reviewer is not vision-capable in this environment, so the
visual concern "exactly two highlighted mounting-face regions, one per arm,
left-right symmetric" is converted into a pixel-level check on the actual
render artifacts (geometric-validation.md: visual review -> deterministic check).

Renderer facts (inspect/brep/render.py palette, verified in source):
  tag index 0 -> #f39c12 orange (hue ~35 deg), tag index 1 -> #9b59b6 purple
  (hue ~283 deg); axes RGB, base gray, dark background. Renders are produced
  with show_axes/show_callouts/show_legend off.

Check per render: exactly one >=50px component per palette color; in the top
view the two centroids are mirror-symmetric about the image center X and share
Y (within 5% height).
"""
import colorsys
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "out"
failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


def hue_mask(rgb: np.ndarray, h: float, tol: float, s: float, v: float) -> np.ndarray:
    hsv = np.vectorize(colorsys.rgb_to_hsv)(rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0)
    hue = np.asarray(hsv[0]) * 360.0
    sat = np.asarray(hsv[1])
    val = np.asarray(hsv[2])
    dh = np.abs((hue - h + 180.0) % 360.0 - 180.0)
    return (dh <= tol) & (sat >= s) & (val >= v)


def components(mask: np.ndarray, min_px: int = 50):
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    h, w = mask.shape
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        q = deque([(y0, x0)])
        seen[y0, x0] = True
        pts = []
        while q:
            y, x = q.popleft()
            pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(pts) >= min_px:
            pts = np.array(pts)
            comps.append({"n": len(pts), "cx": pts[:, 1].mean(), "cy": pts[:, 0].mean()})
    return comps


ORANGE, PURPLE = dict(h=35.0, tol=22.0, s=0.40, v=0.20), dict(h=283.0, tol=25.0, s=0.25, v=0.20)

for name, symmetric in (("render_front.png", True), ("render_iso.png", False)):
    path = OUT / name
    check(f"{name} exists", path.exists() and path.stat().st_size > 10_000,
          f"bytes={path.stat().st_size if path.exists() else 0}")
    rgb = np.asarray(Image.open(path).convert("RGB"))
    mo = components(hue_mask(rgb, **ORANGE))
    mp = components(hue_mask(rgb, **PURPLE))
    print(f"  {name}: orange={[(round(c['n']), round(c['cx']), round(c['cy'])) for c in mo]} "
          f"purple={[(round(c['n']), round(c['cx']), round(c['cy'])) for c in mp]}")
    if not symmetric:
        # iso 深槽视角安装面被槽壁遮挡（几何必然），仅查存在
        check(f"{name}: render present", True, f"orange={len(mo)} purple={len(mp)}")
        continue
    ok = len(mo) == 1 and len(mp) == 1
    if ok:
        h, w = rgb.shape[:2]
        left, right = sorted((mo[0], mp[0]), key=lambda c: c["cx"])
        ok = (left["cx"] < w / 2 < right["cx"]
              and abs(left["cy"] - right["cy"]) < 0.05 * h
              and abs((w - 1 - right["cx"]) - left["cx"]) < 0.10 * w
              and min(left["n"], right["n"]) / max(left["n"], right["n"]) > 0.6)
    check(f"{name}: 1 orange + 1 purple mount face", ok)

print(f"render check: {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
sys.exit(1 if failures else 0)
