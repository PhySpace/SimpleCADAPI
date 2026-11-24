"""Zebra-stripe (reflection-line) renderer for B-rep files.

Judges surface continuity visually: across a G0-only junction the stripes break,
across a G1 junction they stay connected but kink, across a G2 junction they flow
smoothly.  Pure numpy software rasterizer (z-buffer, perspective camera,
per-pixel interpolated surface normals, 2x2 supersampling); OCCT, through the
SimpleCAD native module, only reads and tessellates the shapes.

    python tools/render/zebra.py a.brep [b.brep ...] --out out.png
        [--view x,y,z] [--up x,y,z] [--target x,y,z] [--fov deg] [--fit]
        [--focus x,y,z --radius r] [--stripes N] [--stripe-angle deg]
        [--size WxH] [--titles A B ...] [--mode zebra|shaded|both]

--view is the direction from the target toward the eye.  Without --focus the
camera frames all inputs (one shared camera, so panels are comparable); with
--focus/--radius it frames the sphere (focus, radius) for a close-up.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SS = 2  # supersampling factor per axis
BACKGROUND = np.array([0.965, 0.968, 0.975])
EDGE_COLOR = np.array([0.10, 0.12, 0.16])
SILHOUETTE_COLOR = np.array([0.25, 0.27, 0.30])
ZEBRA_EDGE_COLOR = np.array([0.90, 0.30, 0.12])  # readable on both stripe colours


# --------------------------------------------------------------------------- loading


@dataclass
class Model:
    name: str
    vertices: np.ndarray  # (n, 3) float64
    normals: np.ndarray  # (n, 3) float64, unit, from the surface
    triangles: np.ndarray  # (m, 3) int64
    edges: list[np.ndarray]  # B-rep edge polylines, each (k, 3)


def load_model(path: str, deflection: float, angular: float) -> Model:
    from simplecadapi import _cpp

    shape = _cpp.import_brep(path)
    # Faces keep their own vertices and the normals are evaluated on the
    # surface, so normals are never averaged across B-rep face boundaries.
    mesh = _cpp.mesh(shape, deflection, angular, relative=False)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = np.asarray(mesh.normals, dtype=np.float64)
    triangles = np.asarray(mesh.triangles, dtype=np.int64)
    points, starts = _cpp.render_edge_polylines(shape, deflection=deflection)
    points = np.asarray(points, dtype=np.float64)
    starts = np.asarray(starts, dtype=np.int64)
    edges = [points[starts[i] : starts[i + 1]] for i in range(len(starts) - 1)]
    edges = [e for e in edges if len(e) >= 2]
    return Model(Path(path).stem, vertices, normals, triangles, edges)


# --------------------------------------------------------------------------- camera


@dataclass
class Camera:
    eye: np.ndarray
    forward: np.ndarray
    right: np.ndarray
    up: np.ndarray
    focal: float  # pixels (at render resolution)
    width: int
    height: int

    def to_view(self, p: np.ndarray) -> np.ndarray:
        d = p - self.eye
        return np.stack([d @ self.right, d @ self.up, d @ self.forward], axis=-1)

    def project(self, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """View coords -> (screen x, screen y) in pixels (pixel centres at i+0.5)."""
        z = v[..., 2]
        sx = self.width * 0.5 + self.focal * v[..., 0] / z
        sy = self.height * 0.5 - self.focal * v[..., 1] / z
        return sx, sy


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if n == 0:
        raise SystemExit("zero-length vector")
    return v / n


def _basis(view_dir, up):
    forward = -_unit(view_dir)
    up = _unit(up)
    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-6:  # view parallel to up: pick any up
        right = np.cross(forward, [0.0, 1.0, 0.0] if abs(forward[1]) < 0.9 else [1.0, 0.0, 0.0])
    right = _unit(right)
    return forward, right, np.cross(right, forward)


def make_camera(models, args, width, height) -> Camera:
    fov = math.radians(args.fov)
    focal = (height * 0.5) / math.tan(fov * 0.5)
    forward, right, up = _basis(args.view, args.up)
    if args.focus is not None:
        target = np.asarray(args.focus, dtype=np.float64)
        dist = args.radius / math.sin(fov * 0.5)
        return Camera(target - forward * dist, forward, right, up, focal, width, height)

    pts = np.concatenate([m.vertices for m in models])
    lo, hi = pts.min(0), pts.max(0)
    target = np.asarray(args.target, dtype=np.float64) if args.target is not None else (lo + hi) * 0.5
    if args.target is None:
        # centre the projected extents in the image plane
        rel = pts - target
        x, y = rel @ right, rel @ up
        target = target + right * (x.max() + x.min()) * 0.5 + up * (y.max() + y.min()) * 0.5
    rel = pts - target
    x, y, z = rel @ right, rel @ up, rel @ (-forward)
    margin = 1.0 + args.margin
    ty = math.tan(fov * 0.5) / margin
    tx = ty * width / height
    dist = float(np.max(np.maximum(z + np.abs(x) / tx, z + np.abs(y) / ty)))
    return Camera(target - forward * dist, forward, right, up, focal, width, height)


# --------------------------------------------------------------------------- raster


def rasterize(cam: Camera, verts: np.ndarray, tris: np.ndarray):
    """Z-buffer.  Returns (inverse depth buffer, triangle id buffer), flat arrays."""
    W, H = cam.width, cam.height
    zbuf = np.zeros(W * H, dtype=np.float64)  # 1/z, 0 = background
    tid = np.full(W * H, -1, dtype=np.int64)

    v = cam.to_view(verts)
    near = 1e-6 * max(1.0, float(np.abs(v[:, 2]).max()))
    sx, sy = cam.project(v)
    tz = v[tris, 2]
    keep = np.all(tz > near, axis=1)
    ids = np.nonzero(keep)[0]
    X, Y, IZ = sx[tris[ids]], sy[tris[ids]], 1.0 / tz[ids]

    area = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0])
    x0 = np.clip(np.ceil(X.min(1) - 0.5), 0, W).astype(np.int64)
    x1 = np.clip(np.floor(X.max(1) - 0.5), -1, W - 1).astype(np.int64)
    y0 = np.clip(np.ceil(Y.min(1) - 0.5), 0, H).astype(np.int64)
    y1 = np.clip(np.floor(Y.max(1) - 0.5), -1, H - 1).astype(np.int64)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    ok = (bw > 0) & (bh > 0) & (np.abs(area) > 1e-12)
    ids, X, Y, IZ, area = ids[ok], X[ok], Y[ok], IZ[ok], area[ok]
    x0, y0, bw, bh = x0[ok], y0[ok], bw[ok], bh[ok]

    # bucket by power-of-two bbox so each batch is a dense (n, sy, sx) grid
    kx = np.ceil(np.log2(bw)).astype(np.int64)
    ky = np.ceil(np.log2(bh)).astype(np.int64)
    key = kx * 64 + ky
    budget = 1 << 22
    for k in np.unique(key):
        sel = np.nonzero(key == k)[0]
        gx, gy = 1 << int(k // 64), 1 << int(k % 64)
        step = max(1, budget // (gx * gy))
        ax, ay = np.arange(gx), np.arange(gy)
        for c in range(0, len(sel), step):
            s = sel[c : c + step]
            px = x0[s, None, None] + ax[None, None, :]  # (n,1,gx)
            py = y0[s, None, None] + ay[None, :, None]  # (n,gy,1)
            inside_box = (px < (x0[s] + bw[s])[:, None, None]) & (py < (y0[s] + bh[s])[:, None, None])
            cx, cy = px + 0.5, py + 0.5
            Xs, Ys = X[s], Y[s]
            sign = np.sign(area[s])[:, None, None]
            inv_area = 1.0 / np.abs(area[s])[:, None, None]

            def edge(a, b):
                return sign * (
                    (Xs[:, b, None, None] - Xs[:, a, None, None]) * (cy - Ys[:, a, None, None])
                    - (Ys[:, b, None, None] - Ys[:, a, None, None]) * (cx - Xs[:, a, None, None])
                )

            w0, w1, w2 = edge(1, 2), edge(2, 0), edge(0, 1)
            inside = inside_box & (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            n_idx, iy, ix = np.nonzero(inside)
            if n_idx.size == 0:
                continue
            b0 = w0[n_idx, iy, ix] * inv_area[n_idx, 0, 0]
            b1 = w1[n_idx, iy, ix] * inv_area[n_idx, 0, 0]
            b2 = 1.0 - b0 - b1
            iz = IZ[s][n_idx]
            depth = b0 * iz[:, 0] + b1 * iz[:, 1] + b2 * iz[:, 2]
            pix = (y0[s][n_idx] + iy) * W + (x0[s][n_idx] + ix)
            order = np.lexsort((-depth, pix))
            pix, depth, tri = pix[order], depth[order], ids[s][n_idx][order]
            first = np.ones(pix.size, dtype=bool)
            first[1:] = pix[1:] != pix[:-1]
            pix, depth, tri = pix[first], depth[first], tri[first]
            better = depth > zbuf[pix]
            zbuf[pix[better]] = depth[better]
            tid[pix[better]] = tri[better]
    return zbuf, tid


def surface_attributes(cam: Camera, verts, norms, tris, tid):
    """Per covered pixel: exact ray/triangle barycentrics -> interpolated normal."""
    W, H = cam.width, cam.height
    pix = np.nonzero(tid >= 0)[0]
    N = np.zeros((pix.size, 3))
    D = np.zeros((pix.size, 3))
    chunk = 1 << 20
    for c in range(0, pix.size, chunk):
        p = pix[c : c + chunk]
        t = tris[tid[p]]
        px, py = p % W + 0.5, p // W + 0.5
        d = (
            cam.forward[None]
            + ((px - W * 0.5) / cam.focal)[:, None] * cam.right[None]
            - ((py - H * 0.5) / cam.focal)[:, None] * cam.up[None]
        )
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        a, b, cc = verts[t[:, 0]], verts[t[:, 1]], verts[t[:, 2]]
        e1, e2 = b - a, cc - a
        pv = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, pv)
        det = np.where(np.abs(det) < 1e-30, 1e-30, det)
        tv = cam.eye[None] - a
        u = np.einsum("ij,ij->i", tv, pv) / det
        qv = np.cross(tv, e1)
        v = np.einsum("ij,ij->i", d, qv) / det
        u, v = np.clip(u, 0, 1), np.clip(v, 0, 1)
        s = u + v
        over = s > 1
        u[over] /= s[over]
        v[over] /= s[over]
        n = (1 - u - v)[:, None] * norms[t[:, 0]] + u[:, None] * norms[t[:, 1]] + v[:, None] * norms[t[:, 2]]
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        # show back sides (open shells, inner walls) as if facing the viewer
        back = np.einsum("ij,ij->i", n, d) > 0
        n[back] = -n[back]
        N[c : c + chunk], D[c : c + chunk] = n, d
    return pix, N, D


def _box_square_wave(f, w):
    """Box-filtered square wave of period 2 (light on [0,1), dark on [1,2))."""

    def integral(x):
        return np.floor(x * 0.5) + np.clip(2.0 * (x * 0.5 - np.floor(x * 0.5)), 0.0, 1.0)

    return (integral(f + w * 0.5) - integral(f - w * 0.5)) / w


def _footprint(img, mask, period=None):
    """Screen-space footprint |df/dx|+|df/dy| of a scalar image, ignoring background."""
    out = np.zeros_like(img)
    for axis in (0, 1):
        d = np.diff(img, axis=axis)
        if period is not None:
            d -= np.round(d / period) * period
        m = np.logical_and(np.take(mask, range(0, mask.shape[axis] - 1), axis), np.take(mask, range(1, mask.shape[axis]), axis))
        d = np.where(m, np.abs(d), 0.0)
        pad_lo = [(0, 0), (0, 0)]
        pad_hi = [(0, 0), (0, 0)]
        pad_lo[axis] = (1, 0)
        pad_hi[axis] = (0, 1)
        out += np.maximum(np.pad(d, pad_lo), np.pad(d, pad_hi))
    return out


def shade(cam: Camera, model: Model, mode: str, stripes: int, stripe_angle: float):
    W, H = cam.width, cam.height
    zbuf, tid = rasterize(cam, model.vertices, model.triangles)
    pix, N, D = surface_attributes(cam, model.vertices, model.normals, model.triangles, tid)
    mask = (tid >= 0).reshape(H, W)
    img = np.broadcast_to(BACKGROUND, (H * W, 3)).copy()

    light = _unit(-cam.forward + 0.55 * cam.up - 0.35 * cam.right)
    ndl = np.clip(N @ light, 0.0, 1.0)
    ndv = np.clip(-np.einsum("ij,ij->i", N, D), 0.0, 1.0)

    if mode == "zebra":
        R = D - 2.0 * np.einsum("ij,ij->i", D, N)[:, None] * N
        ang = math.radians(stripe_angle)
        axis_b = math.cos(ang) * cam.up - math.sin(ang) * cam.right  # perpendicular to the light tubes
        phi = np.arctan2(R @ axis_b, R @ (-cam.forward))
        f = np.zeros(H * W)
        f[pix] = phi * (stripes / math.pi)  # `stripes` bands per 180 deg of reflection
        f2 = f.reshape(H, W)
        fw = _footprint(f2, mask, period=2.0 * stripes).reshape(-1)[pix]
        fw = np.maximum(fw, 1e-3)
        light_amt = _box_square_wave(f[pix], fw)
        light_amt = np.where(fw > 1.0, 0.5, light_amt)
        dark, bright = np.array([0.10, 0.11, 0.13]), np.array([0.99, 0.99, 0.99])
        k = 0.72 + 0.28 * ndl
        col = (dark[None] + (bright - dark)[None] * light_amt[:, None]) * k[:, None]
    else:
        albedo = np.array([0.62, 0.70, 0.80])
        fill = _unit(-cam.forward - 0.4 * cam.up + 0.6 * cam.right)
        h = _unit(light - cam.forward)
        spec = np.clip(N @ h, 0.0, 1.0) ** 60
        diffuse = 0.28 + 0.60 * ndl + 0.18 * np.clip(N @ fill, 0.0, 1.0)
        col = albedo[None] * diffuse[:, None] + 0.35 * spec[:, None]
        col = col * (0.85 + 0.15 * ndv)[:, None]
    img[pix] = np.clip(col, 0.0, 1.0)
    img = img.reshape(H, W, 3)

    # silhouette against the background
    sil = np.zeros_like(mask)
    sil[:-1] |= mask[:-1] != mask[1:]
    sil[1:] |= mask[:-1] != mask[1:]
    sil[:, :-1] |= mask[:, :-1] != mask[:, 1:]
    sil[:, 1:] |= mask[:, :-1] != mask[:, 1:]
    img[sil] = img[sil] * 0.3 + SILHOUETTE_COLOR * 0.7

    cover = edge_coverage(cam, model.edges, zbuf.reshape(H, W))
    ink = ZEBRA_EDGE_COLOR if mode == "zebra" else EDGE_COLOR
    img = img * (1 - cover[..., None]) + ink[None, None] * cover[..., None]
    return img


def edge_coverage(cam: Camera, edges, zbuf, width_px: float = 1.5 * SS):
    """Anti-aliased coverage of the visible B-rep edges (depth-tested)."""
    W, H = cam.width, cam.height
    cover = np.zeros((H, W))
    if not edges:
        return cover
    a = np.concatenate([e[:-1] for e in edges])
    b = np.concatenate([e[1:] for e in edges])
    va, vb = cam.to_view(a), cam.to_view(b)
    ok = (va[:, 2] > 1e-9) & (vb[:, 2] > 1e-9)
    va, vb = va[ok], vb[ok]
    ax, ay = cam.project(va)
    bx, by = cam.project(vb)
    n = np.maximum(1, np.ceil(np.hypot(bx - ax, by - ay) / 0.5)).astype(np.int64)
    n = np.minimum(n, 4 * (W + H))
    seg = np.repeat(np.arange(n.size), n + 1)
    t = np.arange(seg.size) - np.repeat(np.cumsum(n + 1) - (n + 1), n + 1)
    t = t / n[seg]
    sx = ax[seg] + (bx - ax)[seg] * t
    sy = ay[seg] + (by - ay)[seg] * t
    iz = (1 - t) / va[seg, 2] + t / vb[seg, 2]
    inb = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
    sx, sy, iz = sx[inb], sy[inb], iz[inb]

    # depth test against the farthest surface in a 3x3 neighbourhood
    depth = np.where(zbuf > 0, 1.0 / np.maximum(zbuf, 1e-300), np.inf)
    pad = np.pad(depth, 1, constant_values=np.inf)
    far = np.max([pad[dy : dy + H, dx : dx + W] for dy in range(3) for dx in range(3)], axis=0)
    ix, iy = sx.astype(np.int64), sy.astype(np.int64)
    zs = 1.0 / iz
    vis = zs <= far[iy, ix] * (1.0 + 2e-3)
    sx, sy = sx[vis], sy[vis]

    r = width_px * 0.5
    R = int(math.ceil(r + 1))
    cx, cy = np.floor(sx).astype(np.int64), np.floor(sy).astype(np.int64)
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            px, py = cx + dx, cy + dy
            ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
            d = np.hypot(px + 0.5 - sx, py + 0.5 - sy)
            c = np.clip(r + 0.5 - d, 0.0, 1.0)
            ok &= c > 0
            np.maximum.at(cover, (py[ok], px[ok]), c[ok])
    return cover * 0.9


# --------------------------------------------------------------------------- compose


def _font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(args) -> Image.Image:
    width, height = args.size
    models = [load_model(p, args.deflection, args.angular) for p in args.inputs]
    cam = make_camera(models, args, width * SS, height * SS)
    modes = ["shaded", "zebra"] if args.mode == "both" else [args.mode]
    titles = list(args.titles or [])
    title_h = int(height * 0.06) if titles else 0
    gap = 8
    cols, rows = len(models), len(modes)
    canvas = Image.new(
        "RGB",
        (cols * width + (cols - 1) * gap, rows * (height + title_h) + (rows - 1) * gap),
        (255, 255, 255),
    )
    font = _font(max(14, int(height * 0.035)))
    draw = ImageDraw.Draw(canvas)
    for r, mode in enumerate(modes):
        for c, model in enumerate(models):
            img = shade(cam, model, mode, args.stripes, args.stripe_angle)
            img = img.reshape(height, SS, width, SS, 3).mean(axis=(1, 3))
            tile = Image.fromarray((np.clip(img, 0, 1) ** (1 / 1.0) * 255 + 0.5).astype(np.uint8))
            x, y = c * (width + gap), r * (height + title_h + gap)
            canvas.paste(tile, (x, y + title_h))
            if c < len(titles) and titles[c]:
                draw.rectangle([x, y, x + width - 1, y + title_h - 1], fill=(255, 255, 255))
                draw.text((x + width // 2, y + title_h // 2), titles[c], fill=(30, 34, 40), font=font, anchor="mm")
            print(f"rendered {model.name} [{mode}] ({len(model.triangles)} triangles)", file=sys.stderr)
    return canvas


def _vec(text):
    parts = [float(t) for t in text.replace(" ", "").split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected x,y,z")
    return np.array(parts)


def _size(text):
    w, h = text.lower().split("x")
    return int(w), int(h)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="BREP files (one panel each)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--view", type=_vec, default=np.array([1.0, -1.4, 1.0]), help="direction target->eye")
    ap.add_argument("--up", type=_vec, default=np.array([0.0, 0.0, 1.0]))
    ap.add_argument("--target", type=_vec, default=None, help="look-at point (default: model centre)")
    ap.add_argument("--fov", type=float, default=30.0, help="vertical field of view, degrees")
    ap.add_argument("--fit", action="store_true", help="frame all inputs (default unless --focus)")
    ap.add_argument("--margin", type=float, default=0.06, help="fit margin fraction")
    ap.add_argument("--focus", type=_vec, default=None, help="close-up centre")
    ap.add_argument("--radius", type=float, default=25.0, help="close-up radius")
    ap.add_argument("--stripes", type=int, default=16, help="stripe count (light+dark) per 180 deg of reflection")
    ap.add_argument("--stripe-angle", type=float, default=0.0, help="rotate light tubes about the view axis, degrees")
    ap.add_argument("--size", type=_size, default=(1200, 900), help="panel size WxH")
    ap.add_argument("--titles", nargs="*", default=None)
    ap.add_argument("--mode", choices=("zebra", "shaded", "both"), default="zebra")
    ap.add_argument("--deflection", type=float, default=0.01, help="linear tessellation deflection, mm")
    ap.add_argument("--angular", type=float, default=0.05, help="angular tessellation deflection, rad")
    args = ap.parse_args(argv)
    if args.fit:
        args.focus = None
    canvas = render(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(out)


if __name__ == "__main__":
    main()
