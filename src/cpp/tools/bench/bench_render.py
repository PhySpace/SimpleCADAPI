"""Soft renderer vs VTK: images, metrics and timings.

Run with the *SDK's* venv (it has vtk, OCP, PIL, numpy) and the native build on PYTHONPATH:

    PYTHONPATH=build/render/python ../SimpleCADAPI-native/.venv/bin/python tools/bench/bench_render.py compare
    PYTHONPATH=build/render/python ../SimpleCADAPI-native/.venv/bin/python tools/bench/bench_render.py bench --runs 7

`compare`  renders the same meshes with the soft renderer and with VTK (the SDK's own `_render_polydata_views_in_process`,
           fed from the same native tessellation), writes side-by-side PNGs to docs/render/ and prints image metrics.
`bench`    times soft / VTK in-process / the current SDK path (a subprocess per call, SCA_BACKEND unset).

Machine load varies: every number is the median of --runs repetitions; CPU time is process CPU (children included for
the subprocess paths).
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get("SCA_SDK_ROOT", ROOT.parent / "SimpleCADAPI-native"))
SDK_PYTHON = SDK / ".venv" / "bin" / "python"
DOCS = ROOT / "docs" / "render"

VIEWS4 = [(28.0, -45.0, "isometric"), (90.0, -90.0, "top / X-Y"), (0.0, -90.0, "front / X-Z"), (0.0, 0.0, "side / Y-Z")]
STUDIO_COLOR = (0.66, 0.68, 0.72)
STANDARD_COLOR = (0.55, 0.64, 0.73)
INK = (0.16, 0.21, 0.27)


# --------------------------------------------------------------------------------------------------
# scenes (native shapes)
# --------------------------------------------------------------------------------------------------
def make_shapes(sc, name: str):
    """-> list of native shapes."""
    if name == "box":
        return [sc.make_box_rsolid(10, 8, 4)]
    if name == "fillet":
        return [sc.fillet_rsolid(sc.make_box_rsolid(10, 8, 4), sc.ql.edges(), 1.0)]
    if name == "gear":
        return [sc.std.gear.make_spur_gear_rsolid(20, 2.0, gear_height=6.0)]
    if name == "bolt":
        return [sc.std.fastener.make_bolt_rsolid(8.0, 24.0)]
    if name == "many":
        gear = sc.std.gear.make_spur_gear_rsolid(20, 2.0, gear_height=6.0)
        return [sc.translate_shape(gear, (45.0 * (i % 6), 45.0 * (i // 6), 0.0)) for i in range(30)]
    raise SystemExit(f"unknown case {name}")


def tessellate(sc, shapes, linear=0.35, angular=0.22):
    """-> list of (mesh, edge_points, edge_starts)."""
    out = []
    for s in shapes:
        pts, starts = sc.render_edge_polylines(s, min(linear, 0.04))
        out.append((sc.mesh(s, linear, angular), pts, starts))
    return out


# --------------------------------------------------------------------------------------------------
# soft renderer
# --------------------------------------------------------------------------------------------------
def soft_scene(sc, parts, style, groups=(), edge_groups=(), edge_width_px=4.5):
    scene = sc.RenderScene()
    color = STUDIO_COLOR if style == "studio" else STANDARD_COLOR
    for mesh, pts, starts in parts:
        scene.add_mesh(mesh, color=color, studio_material=(style == "studio"))
        scene.add_polylines(pts, starts, color=INK, ink=True)
    for mesh, rgb, opacity in groups:
        scene.add_mesh(mesh, color=rgb, opacity=opacity)
    for pts, starts, rgb in edge_groups:
        scene.add_polylines(pts, starts, color=rgb, width_px=edge_width_px)
    return scene


def soft_render(sc, scene, w, h, ss, style, views, show_axes=False, zoom=1.0, threads=0, **kw):
    return sc.render_scene(scene, w, h, supersample=ss, style=style, views=views, show_axes=show_axes, zoom=zoom, threads=threads, **kw)


# --------------------------------------------------------------------------------------------------
# VTK in-process (the SDK's own drawing code, same meshes)
# --------------------------------------------------------------------------------------------------
class Vtk:
    def __init__(self):
        from simplecadapi.inspect.brep import render as R

        self.R = R
        self.vtk, self.n2v, self.n2vid = R._vtk_modules()
        import numpy as np

        self.np = np

    def mesh_poly(self, m):
        np = self.np
        pts = np.ascontiguousarray(m.vertices)
        nrm = np.ascontiguousarray(m.normals)
        tri = np.ascontiguousarray(m.triangles.astype(np.int64))
        pd = self.vtk.vtkPolyData()
        p = self.vtk.vtkPoints()
        p.SetData(self.n2v(pts, deep=False))
        pd.SetPoints(p)
        off = np.arange(0, 3 * (len(tri) + 1), 3, dtype=np.int64)
        c = self.vtk.vtkCellArray()
        c.SetData(self.n2vid(off, deep=False), self.n2vid(tri.reshape(-1), deep=False))
        pd.SetPolys(c)
        vn = self.n2v(nrm, deep=False)
        vn.SetName("Normals")
        pd.GetPointData().SetNormals(vn)
        pd._refs = (pts, nrm, tri, off)
        return pd

    def lines_poly(self, pts, starts):
        np = self.np
        pts = np.ascontiguousarray(pts)
        pd = self.vtk.vtkPolyData()
        p = self.vtk.vtkPoints()
        p.SetData(self.n2v(pts, deep=False))
        pd.SetPoints(p)
        conn = np.arange(len(pts), dtype=np.int64)
        off = np.asarray(starts, dtype=np.int64)
        ln = self.vtk.vtkCellArray()
        ln.SetData(self.n2vid(off, deep=False), self.n2vid(conn, deep=False))
        pd.SetLines(ln)
        pd._refs = (pts, off, conn)
        return pd

    def merged(self, polys):
        ap = self.vtk.vtkAppendPolyData()
        for p in polys:
            ap.AddInputData(p)
        ap.Update()
        pd = self.vtk.vtkPolyData()
        pd.DeepCopy(ap.GetOutput())
        return pd

    def render(self, parts, w, h, ss, style, views, out, show_axes=False, zoom=None, groups=(), edge_groups=(), legend=None,
               callouts=None, edge_width=4.5, context_opacity=1.0):
        """parts: [(mesh, edge_pts, edge_starts)]; groups: [(mesh, rgb, opacity)]; edge_groups: [(pts, starts, rgb)]."""
        base = self.merged([self.mesh_poly(m) for m, _, _ in parts]) if parts else None
        eds = [self.lines_poly(p, s) for _, p, s in parts]
        edges = self.merged(eds) if eds else None
        gpoly = [(self.mesh_poly(m), rgb, op) for m, rgb, op in groups]
        epoly = [(self.lines_poly(p, s), rgb) for p, s, rgb in edge_groups]
        self.R._render_polydata_views_in_process(
            base, str(out), title="", views=tuple(views), image_size=(w / 100.0, h / 100.0), dpi=100,
            brep_edge_polydata=edges, highlighted_groups=gpoly or None, highlighted_edge_groups=epoly or None,
            highlight_edge_width=edge_width, show_axes=show_axes, edge_width_scale=0.0019, supersample=ss, style=style,
            zoom=zoom, legend=legend, callouts=callouts, context_opacity=context_opacity,
        )
        from PIL import Image

        return self.np.asarray(Image.open(out).convert("RGB"))


# --------------------------------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------------------------------
def metrics(np, vtk_img, soft_img, bg_img, text_mask=None):
    """Silhouette IoU, mean abs colour diff, ink-edge pixel agreement.  Images are (h, w, 3) uint8."""
    keep = np.ones(vtk_img.shape[:2], bool) if text_mask is None else ~text_mask
    dv = np.abs(vtk_img.astype(int) - bg_img.astype(int)).max(axis=2) > 12
    ds = np.abs(soft_img.astype(int) - bg_img.astype(int)).max(axis=2) > 12
    dv &= keep
    ds &= keep
    union = dv | ds
    iou = float((dv & ds).sum() / max(1, union.sum()))
    both = dv & ds
    diff = np.abs(vtk_img.astype(int) - soft_img.astype(int)).mean(axis=2)
    mad_union = float(diff[union].mean()) if union.any() else 0.0
    mad_both = float(diff[both].mean()) if both.any() else 0.0

    def ink(img):
        d = np.abs(img.astype(int) - np.array([41, 54, 69])).max(axis=2)
        return (d < 28) & keep

    iv, is_ = ink(vtk_img), ink(soft_img)

    def dil(m):
        o = m.copy()
        o[1:] |= m[:-1]; o[:-1] |= m[1:]; o[:, 1:] |= m[:, :-1]; o[:, :-1] |= m[:, 1:]
        return o

    prec = float((is_ & dil(iv)).sum() / max(1, is_.sum()))
    rec = float((iv & dil(is_)).sum() / max(1, iv.sum()))
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    return {"silhouette_iou": round(iou, 4), "mad_union": round(mad_union, 2), "mad_both": round(mad_both, 2),
            "edge_f1": round(f1, 3), "edge_precision": round(prec, 3), "edge_recall": round(rec, 3),
            "vtk_ink_px": int(iv.sum()), "soft_ink_px": int(is_.sum())}


def text_mask(np, shape, views_n, w, h, legend_fraction=0.0):
    """Regions where VTK draws text (title/view label bottom-left of every panel, legend strip)."""
    m = np.zeros(shape[:2], bool)
    cols = min(2, views_n)
    rows = (views_n + cols - 1) // cols
    rw = int(round(w * (1 - legend_fraction)))
    for i in range(views_n):
        c, r = i % cols, i // cols
        x0 = int(round(c * rw / cols)); y1 = int(round((r + 1) * h / rows))
        pw = int(round((c + 1) * rw / cols)) - x0; ph = int(round((r + 1) * h / rows)) - int(round(r * h / rows))
        m[y1 - int(ph * 0.16): y1, x0: x0 + int(pw * 0.30)] = True
    if legend_fraction:
        m[:, rw:] = True
    return m


def side_by_side(np, imgs, labels, path):
    from PIL import Image, ImageDraw

    a, b = imgs
    diff = np.clip(np.abs(a.astype(int) - b.astype(int)) * 4, 0, 255).astype("uint8")
    row = np.concatenate([a, b, diff], axis=1)
    im = Image.fromarray(row)
    d = ImageDraw.Draw(im)
    for i, t in enumerate(labels + ["abs diff x4"]):
        d.text((8 + i * a.shape[1], 6), t, fill=(255, 220, 0))
    im.save(path)


# --------------------------------------------------------------------------------------------------
# compare
# --------------------------------------------------------------------------------------------------
def cmd_compare(args):
    import numpy as np
    import simplecadapi._cpp as sc

    DOCS.mkdir(parents=True, exist_ok=True)
    vtk = Vtk()
    results = {}
    tmp = Path(tempfile.mkdtemp())
    for case, style, ss, views in [
        ("box", "studio", 2, VIEWS4), ("fillet", "studio", 2, VIEWS4), ("gear", "studio", 2, VIEWS4), ("bolt", "studio", 2, VIEWS4),
        ("gear", "standard", 2, VIEWS4), ("fillet", "standard", 1, [VIEWS4[0]]),
    ]:
        if args.only and case not in args.only:
            continue
        parts = tessellate(sc, make_shapes(sc, case))
        w, h = 1400, 900
        zoom_vtk = 4.0 if len(views) == 1 else None
        v = vtk.render(parts, w, h, ss, style, views, tmp / "v.png", zoom=zoom_vtk)
        scene = soft_scene(sc, parts, style)
        f = soft_render(sc, scene, w, h, ss, style, views, zoom=1.0)
        s = np.asarray(f.rgba)[:, :, :3]
        empty = soft_render(sc, sc.RenderScene(), w, h, ss, style, views)
        bg = np.asarray(empty.rgba)[:, :, :3]
        m = metrics(np, v, s, bg, text_mask(np, v.shape, len(views), w, h))
        key = f"{case}-{style}-ss{ss}-{len(views)}v"
        results[key] = m
        side_by_side(np, (v, s), ["VTK (in-process)", "soft"], DOCS / f"{key}.png")
        print(key, m, flush=True)
    (DOCS / "metrics.json").write_text(json.dumps(results, indent=1))
    os._exit(0)


def cmd_highlight(args):
    """Highlight groups, translucent context, highlighted edges/points and axes against VTK."""
    import numpy as np
    import simplecadapi._cpp as sc

    DOCS.mkdir(parents=True, exist_ok=True)
    vtk = Vtk()
    tmp = Path(tempfile.mkdtemp())
    solid = sc.fillet_rsolid(sc.make_box_rsolid(10, 8, 4), sc.ql.edges(), 1.0)
    parts = tessellate(sc, [solid])
    face_groups = [(sc.mesh(solid.get_faces(i)), rgb, 1.0) for i, rgb in [(0, (0.953, 0.612, 0.071)), (3, (0.608, 0.349, 0.714))]]
    pts, starts = sc.render_edge_polylines(solid.get_edges(5), 0.04)
    results = {}
    for name, ss, opacity, wpx in [("highlight-opaque", 2, 1.0, 4.5), ("highlight-context", 2, 0.18, 4.5),
                                   ("highlight-opaque-thin", 2, 1.0, 1.0)]:
        if opacity < 1.0:
            base_parts = [(parts[0][0], parts[0][1], parts[0][2])]
        else:
            base_parts = parts
        views = VIEWS4[:2]
        v = vtk.render(base_parts, 1400, 900, ss, "standard", views, tmp / "v.png", groups=face_groups,
                       edge_groups=[(pts, starts, (0.953, 0.612, 0.071))], show_axes=True, context_opacity=opacity)
        scene = sc.RenderScene()
        scene.add_mesh(parts[0][0], color=STANDARD_COLOR, opacity=opacity)
        scene.add_polylines(parts[0][1], parts[0][2], color=INK, ink=True)
        for m, rgb, op in face_groups:
            scene.add_mesh(m, color=rgb, opacity=op)
        scene.add_polylines(pts, starts, color=(0.953, 0.612, 0.071), width_px=wpx)
        f = soft_render(sc, scene, 1400, 900, ss, "standard", views, show_axes=True)
        s_img = np.asarray(f.rgba)[:, :, :3]
        bg = np.asarray(soft_render(sc, sc.RenderScene(), 1400, 900, ss, "standard", views).rgba)[:, :, :3]
        m = metrics(np, v, s_img, bg, text_mask(np, v.shape, len(views), 1400, 900))
        results[name] = m
        side_by_side(np, (v, s_img), ["VTK (in-process)", "soft"], DOCS / f"{name}.png")
        print(name, m, flush=True)
    (DOCS / "metrics-highlight.json").write_text(json.dumps(results, indent=1))
    os._exit(0)


# --------------------------------------------------------------------------------------------------
# timings
# --------------------------------------------------------------------------------------------------
def _cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def cmd_inner(args):
    """One measuring process: prints a JSON list, one record per call (ms)."""
    mode, case, n, ss = args.mode, args.case, args.n, args.ss
    out = Path(tempfile.mkdtemp()) / "shot.png"
    rec = []
    if mode == "sdk":
        import simplecadapi as scad

        def build():
            if case == "box":
                return scad.make_box_rsolid(10, 8, 4)
            if case == "fillet":
                return scad.fillet_rsolid(scad.make_box_rsolid(10, 8, 4), scad.ql.edges(), 1.0)
            if case == "gear":
                return scad.std.gear.make_spur_gear_rsolid(20, 2.0, gear_height=6.0)
            if case == "bolt":
                return scad.std.fastener.make_bolt_rsolid(8.0, 24.0)
            g = scad.std.gear.make_spur_gear_rsolid(20, 2.0, gear_height=6.0)
            return [scad.translate_shape(g, (45.0 * (i % 6), 45.0 * (i // 6), 0.0)) for i in range(30)]

        solid = build()
        for _ in range(n):
            t, c = time.perf_counter(), _cpu()
            scad.render_screenshot_rpath(solid, str(out), image_size=(1400, 900))
            rec.append({"wall": (time.perf_counter() - t) * 1e3, "cpu_self": (_cpu() - c) * 1e3})
    else:
        import numpy as np
        import simplecadapi._cpp as sc
        from PIL import Image

        shapes = make_shapes(sc, case)
        vtk = Vtk() if mode == "vtk" else None
        for _ in range(n):
            t, c = time.perf_counter(), _cpu()
            parts = tessellate(sc, shapes)
            t_mesh = time.perf_counter()
            if mode == "soft":
                scene = soft_scene(sc, parts, "studio")
                f = soft_render(sc, scene, 1400, 900, ss, "studio", VIEWS4, show_axes=True)
                t_render = time.perf_counter()
                Image.fromarray(np.asarray(f.rgba)[:, :, :3]).save(out)
            else:
                t_render = t_mesh
                vtk.render(parts, 1400, 900, 2, "studio", VIEWS4, out, show_axes=True)
            t_end = time.perf_counter()
            rec.append({"wall": (t_end - t) * 1e3, "cpu_self": (_cpu() - c) * 1e3, "mesh": (t_mesh - t) * 1e3,
                        "render": (t_render - t_mesh) * 1e3, "encode_or_vtk": (t_end - t_render) * 1e3})
    sys.stdout.write("JSON" + json.dumps(rec) + "\n")
    sys.stdout.flush()
    os._exit(0)


def _run_inner(mode, case, n, ss=2):
    env = dict(os.environ)
    env.pop("SCA_BACKEND", None)
    py = SDK_PYTHON
    if mode == "sdk":
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(ROOT / "build" / "render" / "python") if "PYTHONPATH" not in os.environ else os.environ["PYTHONPATH"]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t = time.perf_counter()
    r = subprocess.run([str(py), __file__, "inner", "--mode", mode, "--case", case, "--n", str(n), "--ss", str(ss)],
                       env=env, capture_output=True, text=True)
    wall = (time.perf_counter() - t) * 1e3
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e3
    line = [l for l in r.stdout.splitlines() if l.startswith("JSON")]
    if not line:
        raise RuntimeError(f"{mode}/{case} failed:\n{r.stderr[-800:]}")
    return json.loads(line[0][4:]), wall, cpu


def med(xs):
    return statistics.median(xs)


def cmd_bench(args):
    cases = args.cases or ["box", "fillet", "gear", "bolt", "many"]
    table = {}
    runs = args.runs
    for case in cases:
        row = {}
        for label, mode, ss in [("soft ss1", "soft", 1), ("soft ss2", "soft", 2), ("soft ss3", "soft", 3), ("vtk in-process ss2", "vtk", 2),
                                ("sdk render_screenshot_rpath", "sdk", 2)]:
            if mode == "sdk" and case == "many" and not args.sdk_many:
                continue
            warm_runs, _, _ = _run_inner(mode, case, runs + 2, ss)
            warm = warm_runs[2:]
            cold_wall, cold_cpu = [], []
            for _ in range(runs):
                rec, wall, cpu = _run_inner(mode, case, 1, ss)
                cold_wall.append(wall); cold_cpu.append(cpu)
            row[label] = {
                "warm_wall_ms": round(med([w["wall"] for w in warm]), 1),
                "warm_cpu_self_ms": round(med([w["cpu_self"] for w in warm]), 1),
                "warm_parts_ms": {k: round(med([w[k] for w in warm]), 1) for k in ("mesh", "render", "encode_or_vtk") if k in warm[0]},
                "cold_process_wall_ms": round(med(cold_wall), 1),
                "cold_process_cpu_ms": round(med(cold_cpu), 1),
                "runs": runs,
            }
            print(case, label, row[label], flush=True)
        table[case] = row
    (DOCS / "bench.json").write_text(json.dumps(table, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--only", nargs="*")
    c.set_defaults(fn=cmd_compare)
    b = sub.add_parser("bench")
    b.add_argument("--runs", type=int, default=7)
    b.add_argument("--cases", nargs="*")
    b.add_argument("--sdk-many", action="store_true")
    b.set_defaults(fn=cmd_bench)
    i = sub.add_parser("inner")
    i.add_argument("--mode"); i.add_argument("--case"); i.add_argument("--n", type=int); i.add_argument("--ss", type=int, default=2)
    i.set_defaults(fn=cmd_inner)
    sub.add_parser("highlight").set_defaults(fn=cmd_highlight)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
