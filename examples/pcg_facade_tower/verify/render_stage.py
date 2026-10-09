"""Per-stage render -> verify/renders/<stage>_*.png (Z up).

    ../../../.venv/bin/python render_stage.py s1 [rect|chamfer|l_shape ...]   # massing four-view + plan + unrolled elevation
    ../../../.venv/bin/python render_stage.py s2                               # panel types + the K fin row
    ../../../.venv/bin/python render_stage.py s3                               # corner fits, slab skeletons, canopy
    ../../../.venv/bin/python render_stage.py s4                               # band subassemblies (solved placements)
    ../../../.venv/bin/python render_stage.py s5                               # tower four-view, south, setback

S2 renders mount panel-local parts as on a south facade (x -> +X, y up -> +Z, outward z -> -Y).
"""
from __future__ import annotations

import math
import sys
from dataclasses import replace

import simplecadapi as scad
from _common import OUT, tight_bbox

import layout as L

MASSING_VIEWS = [(25, 215, "iso from SW"), (25, 35, "iso from NE"), (0, 180, "south elevation"),
                 (90, 0, "plan (from +Z)")]


def _prism(poly, z0: float, z1: float):
    wire = scad.make_polyline_rwire(points=[(x, y, z0) for x, y in poly], closed=True)
    face = scad.make_face_from_wire_rface(wire=wire, normal=(0.0, 0.0, 1.0))
    return scad.extrude_rsolid(profile=face, direction=(0.0, 0.0, 1.0), distance=z1 - z0)


def massing(sched: L.FacadeSchedule) -> list:
    """Tier prisms: building line from the tier below's roof up to this tier's roof (tier 0 includes the lobby)."""
    solids, z0 = [], 0.0
    for k, poly in enumerate(sched.tiers):
        z1 = sched.levels[f"roof{k}"]
        solids.append(_prism(poly, z0, z1))
        z0 = z1
    return solids


def plan_figure(sched: L.FacadeSchedule, path) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    p = sched.params
    depth = 400.0  # band drawn ~2.7x frame_d so it reads at plan scale (corner reserve must stay > depth)
    drawn = replace(p, frame_d=depth)
    fig, axes = plt.subplots(1, len(sched.tiers), figsize=(6.2 * len(sched.tiers), 5.6))
    axes = [axes] if len(sched.tiers) == 1 else list(axes)
    shades = {"vision": "#d9d9d9", "solid": "#555555"}
    for k, ax in enumerate(axes):
        band = sched.band(f"tier{k}-phase0")
        poly = sched.tiers[k]
        frames = L.edge_frames(poly)
        ax.add_patch(Polygon(poly, closed=True, fill=False, lw=0.6, ls="--", ec="#888888"))
        for r in band["panels"]:
            fr = frames[r["edge"]]
            a = L._add(fr["v0"], L._mul(fr["t"], r["s0"] + p.joint / 2.0))
            b = L._add(fr["v0"], L._mul(fr["t"], r["s0"] + r["w"] - p.joint / 2.0))
            quad = [a, b, L._add(b, L._mul(fr["n"], depth)), L._add(a, L._mul(fr["n"], depth))]
            closer = r["slot"] in (0, max(q["slot"] for q in band["panels"] if q["edge"] == r["edge"]))
            ax.add_patch(Polygon(quad, closed=True, lw=0.2, ec="white",
                                 fc="#e8743b" if closer else shades[r["kind"]]))
            if r.get("fin") is not None:  # fin at the right jamb, rotated about the jamb by the bin angle
                th = math.radians(r["fin"])
                root = L._add(b, L._mul(fr["n"], depth))
                tip_dir = L._add(L._mul(fr["n"], math.cos(th)), L._mul(fr["t"], math.sin(th)))
                tip = L._add(root, L._mul(tip_dir, 2.0 * depth))
                ax.plot([root[0], tip[0]], [root[1], tip[1]], color="black", lw=0.7)
        for c in band["corners"]:
            prof = L.corner_profile_local(c["turn"], drawn)
            fr = frames[c["vertex"] - 1]
            v = tuple(poly[c["vertex"]])
            world = [L._add(L._add(v, L._mul(fr["t"], x)), L._mul(fr["n"], z)) for x, z in prof]
            ax.add_patch(Polygon(world, closed=True, fc="black", ec="black", lw=0.3))
        xs = [v[0] for v in sched.tiers[0]]
        ys = [v[1] for v in sched.tiers[0]]
        ax.set_xlim(min(xs) - 3000, max(xs) + 3000)
        ax.set_ylim(min(ys) - 3000, max(ys) + 3000)
        ax.set_aspect("equal")
        ax.set_title(f"tier {k}  (setback {k * p.setback_depth:.0f})  phase 0", fontsize=10)
        ax.tick_params(labelsize=7)
    fig.suptitle(f"{p.plan_kind.value}: grey = vision, dark = solid, orange = closer, black = corner piece, "
                 f"line = fin (bin angle); band depth exaggerated", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path)


def elevation_figure(sched: L.FacadeSchedule, path) -> str:
    """Unrolled perimeter elevation, every floor: the Bayer WWR dither and the quantized fin wave."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    from matplotlib.patches import Rectangle

    p = sched.params
    cmap = plt.get_cmap("coolwarm")
    norm = Normalize(-L.FIN_LIMIT, L.FIN_LIMIT)
    fig, ax = plt.subplots(figsize=(18, 7.5))
    width = 0.0
    for rec in sched.floors:
        band = sched.band(rec["floor_type"])
        frames = L.edge_frames(sched.tiers[rec["tier"]])
        starts, u = [], 0.0
        for fr in frames:
            starts.append(u)
            u += fr["length"]
        width = max(width, u)
        for r in band["panels"]:
            x = starts[r["edge"]] + r["s0"]
            if r["kind"] == "solid":
                fc = "#444444"
            elif r.get("fin") is None:
                fc = "#e6e6e6"
            else:
                fc = cmap(norm(r["fin"]))
            ax.add_patch(Rectangle((x, rec["level"]), r["w"], p.floor_h, fc=fc, ec="white", lw=0.15))
        for e, s in enumerate(starts):
            ax.add_patch(Rectangle((s - p.corner_c, rec["level"]), 2 * p.corner_c, p.floor_h, fc="black", lw=0))
    ax.set_xlim(-1000, width + 1000)
    ax.set_ylim(p.lobby_h - 1000, sched.stats["height"])
    ax.set_xlabel("perimeter u (mm), from SW corner CCW: S -> E -> ... ")
    ax.set_ylabel("level z (mm)")
    ax.set_title(f"{p.plan_kind.value}: unrolled elevation, {p.n_floors} floors. dark = solid, light = vision no fin, "
                 f"colour = fin bin angle (K={p.fin_bins}); WWR "
                 + " ".join(f"{o} {v:.3f}" for o, v in sched.stats["design_wwr"].items()), fontsize=10)
    fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, label="fin angle (deg)", fraction=0.02)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return str(path)


# (elev, azim) are world-fixed (elev toward +Z, azim from +X); panel-local renders use view_up +y
PANEL_VIEWS_LOCAL = [(30, 35, "iso, outside"), (90, 0, "outside (+z)"), (-90, 0, "inside (-z)"),
                     (0, 0, "side (+x): depth profile")]


def _south(shape, dx: float = 0.0):
    """Panel-local -> world as mounted on a south edge, shifted dx along the facade."""
    upright = scad.rotate_shape(shape=shape, angle=90.0, axis=(1.0, 0.0, 0.0), origin=(0.0, 0.0, 0.0))
    return scad.translate_shape(shape=upright, vector=(dx, 0.0, 0.0))


def _fin_on_panel(fin_body, w: float, p) -> object:
    """Fin-local -> panel-local: root on the right-jamb centreline of the frame outer face (A6)."""
    return scad.translate_shape(shape=fin_body, vector=(w - p.joint / 2.0 - p.frame_sight / 2.0, 0.0, p.frame_d))


def render_s2() -> list[str]:
    import panels as P
    from s2_verify import all_types

    OUT.mkdir(exist_ok=True)
    p = L.default_params()
    types = all_types()
    body = {tid: P.make_panel_part(tid, spec, p).value.body for tid, spec in types.items()}
    out = []
    for tid, spec in sorted(types.items()):  # one four-view per vision type (glass tag highlighted)
        if spec["family"] == "vision":
            # panel-local, untransformed: a moved shape keeps its tags only in lineage scope, and the renderer
            # highlights effective tags
            out.append(scad.render_screenshot_rpath(
                shapes=[body[tid]], output_path=str(OUT / f"s2_{tid}.png"), views=PANEL_VIEWS_LOCAL,
                view_up=(0.0, 1.0, 0.0), highlight_tags=[P.GLASS_TAG], show_callouts=False, show_legend=False))
    solids = sorted((t for t, s in types.items() if s["family"] == "solid"), key=lambda t: (types[t]["h"], types[t]["w"]))
    row, x = [], 0.0
    for tid in solids:  # every solid type side by side, 300 apart
        row.append(_south(body[tid], x))
        x += types[tid]["w"] + 300.0
    out.append(scad.render_screenshot_rpath(shapes=row, output_path=str(OUT / "s2_solid_types.png"),
                                            views=[(20, 235, "iso, outside"), (0, 270, "outside (south)")],
                                            view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
    std = L.vision_type_id(p.w_std, p.floor_h, p.spandrel_h)
    fins = sorted((t for t, s in types.items() if s["family"] == "fin"), key=lambda t: types[t]["angle"])
    row = []
    for i, tid in enumerate(fins):  # the K bins, each on a standard vision panel, adjacent modules
        row.append(_south(body[std], i * p.w_std))
        row.append(_south(_fin_on_panel(body[tid], p.w_std, p), i * p.w_std))
    out.append(scad.render_screenshot_rpath(
        shapes=row, output_path=str(OUT / "s2_fin_bins.png"),
        views=[(25, 235, "iso, outside"), (0, 270, "outside (south)"), (60, 270, "high, outside"),
               (90, 0, "plan from +Z")],
        view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
    # blade sections alone, fin-local, 500 apart in x, looking down the extrusion (+y -> viewer)
    sections = [scad.translate_shape(shape=body[tid], vector=(i * 500.0, 0.0, 0.0)) for i, tid in enumerate(fins)]
    out.append(scad.render_screenshot_rpath(
        shapes=sections, output_path=str(OUT / "s2_fin_sections.png"),
        views=[(0, 90, "from +y (x runs left): " + " ".join(f"{types[t]['angle']:g}" for t in fins)),
               (30, 60, "iso")],
        view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
    return out


def _corner_assembly(sched: L.FacadeSchedule, band: dict, rec: dict, n_side: int = 2) -> tuple[list, tuple]:
    """World-placed corner + n_side panels each side (s3_verify placement), shifted so the vertex is the origin.
    Returns (shapes, outward bisector)."""
    from _common import place_shape
    from s3_verify import Parts

    parts, level = Parts(sched), L.band_levels(sched, band["band_id"])[0]
    poly = [tuple(v) for v in sched.tiers[band["tier"]]]
    i, frames = rec["vertex"], L.edge_frames(poly)
    e_in = (i - 1) % len(poly)
    near = sorted((r for r in band["panels"] if r["edge"] == e_in), key=lambda r: r["slot"])[-n_side:]
    near += sorted((r for r in band["panels"] if r["edge"] == i), key=lambda r: r["slot"])[:n_side]
    shapes = [parts.corner(band, rec, level)] + [parts.panel(band, r, level) for r in near]
    v = poly[i]
    moved = [scad.translate_shape(shape=sh, vector=(-v[0], -v[1], -level)) for sh in shapes]
    return moved, L._add(frames[e_in]["n"], frames[i]["n"])


def render_s3() -> list[str]:
    import slabs as S
    from s3_verify import Parts, fit_bands

    OUT.mkdir(exist_ok=True)
    out = []
    picks = [(L.PlanKind.RECT, 90.0, "p90"), (L.PlanKind.CHAMFER, 45.0, "p45"), (L.PlanKind.L_SHAPE, -90.0, "m90")]
    for kind, turn, tag in picks:  # corner + two panels each side, tier-0 tower band, vertex at the origin
        sched = L.build_schedule(L.default_params(plan_kind=kind))
        band = next(b for b in fit_bands(sched) if b["band"] == L.Band.TOWER.value and b["tier"] == 0)
        rec = next(r for r in band["corners"] if abs(r["turn"] - turn) < 1.0e-9)
        shapes, bis = _corner_assembly(sched, band, rec)
        az = math.degrees(math.atan2(bis[1], bis[0])) % 360.0
        out.append(scad.render_screenshot_rpath(
            shapes=shapes, output_path=str(OUT / f"s3_corner_{tag}.png"),
            views=[(25, az, f"{kind.value} v{rec['vertex']} turn {turn:+g}: outside"),
                   (25, (az + 180.0) % 360.0, "inside"), (90, 0, "plan from +Z"), (-90, 0, "plan from below")],
            view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
        close, _ = _corner_assembly(sched, band, rec, n_side=1)
        out.append(scad.render_screenshot_rpath(
            shapes=close, output_path=str(OUT / f"s3_corner_{tag}_plan.png"), view=(90.0, 0.0), zoom=10.0,
            view_up=(0.0, 1.0, 0.0), show_callouts=False, show_legend=False))

    for kind in L.PlanKind:  # slab stack + every corner column: the structural skeleton of the facade
        sched = L.build_schedule(L.default_params(plan_kind=kind))
        parts = Parts(sched)
        slab = {k: S.make_slab_part(sched, k).value.body for k in range(len(sched.tiers))}
        shapes = [scad.translate_shape(shape=slab[i["tier"]], vector=(0.0, 0.0, i["level"]))
                  for i in L.slab_instances(sched)]
        for band in sched.bands:
            for level in L.band_levels(sched, band["band_id"]):
                shapes += [parts.corner(band, rec, level) for rec in band["corners"]]
        out.append(scad.render_screenshot_rpath(
            shapes=shapes, output_path=str(OUT / f"s3_skeleton_{kind.value}.png"), views=MASSING_VIEWS,
            view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))

    sched = L.build_schedule(L.default_params())  # entrance: south lobby rows + corners + canopy + ground slab
    parts, lobby = Parts(sched), sched.band("lobby")
    shapes = [S.make_canopy_part(sched).value.body]
    for level in L.band_levels(sched, "lobby"):
        shapes += [parts.panel(lobby, r, level) for r in lobby["panels"] if r["edge"] == 0]
        shapes += [parts.corner(lobby, r, level) for r in lobby["corners"] if r["vertex"] in (0, 1)]
    shapes.append(S.make_slab_part(sched, 0).value.body)
    out.append(scad.render_screenshot_rpath(
        shapes=shapes, output_path=str(OUT / "s3_canopy.png"),
        views=[(15, 240, "iso, south-west"), (0, 270, "south elevation"), (0, 0, "from east: canopy on the row joint"),
               (55, 300, "high, south-east")],
        view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
    return out


def _near(sched: L.FacadeSchedule, band: dict, shapes: dict, vertex: int, radius: float) -> list:
    """Placed band components whose frame origin lies within radius (plan) of a tier vertex."""
    import floor as F

    vx, vy = sched.tiers[band["tier"]][vertex]
    near = {c["component_id"] for c in F.band_components(sched, band)
            if math.hypot(c["frame"]["origin"][0] - vx, c["frame"]["origin"][1] - vy) < radius}
    return [s for cid, s in shapes.items() if cid in near]


def render_s4() -> list[str]:
    import floor as F
    from s4_verify import placed

    OUT.mkdir(exist_ok=True)
    out = []
    sched = L.build_schedule(L.default_params())
    for band_id, views in (
            ("tier0-phase0", [(25, 225, "tier0-phase0 (floor 1): iso south-west"), (25, 45, "iso north-east (chamfer)"),
                              (0, 270, "south elevation"), (90, 0, "plan from +Z")]),
            ("lobby", [(20, 225, "lobby, 2 rows: iso south-west"), (0, 270, "south elevation")])):
        band = sched.band(band_id)
        asm = F.make_band_assembly(sched, band_id).value  # rendered from the solved placements
        shapes = {c.component_id: placed(c) for c in asm.components}
        out.append(scad.render_screenshot_rpath(
            shapes=list(shapes.values()), output_path=str(OUT / f"s4_band_{band_id}.png"), views=views,
            view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
        if band_id != "tier0-phase0":
            continue
        chamfer = next(r["vertex"] for r in band["corners"] if abs(r["turn"] - 45.0) < 1.0e-9)
        out.append(scad.render_screenshot_rpath(  # joints at plan scale: chamfer corner, fins on the east face
            shapes=_near(sched, band, shapes, chamfer, 3500.0), output_path=str(OUT / "s4_plan_chamfer.png"),
            view=(90.0, 0.0), view_up=(0.0, 1.0, 0.0), show_callouts=False, show_legend=False))
        sw = next(r["vertex"] for r in band["corners"] if abs(r["turn"] - 90.0) < 1.0e-9)
        out.append(scad.render_screenshot_rpath(
            shapes=_near(sched, band, shapes, sw, 2600.0), output_path=str(OUT / "s4_corner_sw.png"),
            views=[(20, 225, f"v{sw} +90 corner: outside"), (20, 45, "inside"), (90, 0, "plan from +Z"),
                   (0, 270, "south elevation")],
            view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
    return out


def _clip(shape, lo: tuple, hi: tuple):
    """Diagnostic: shape ∩ axis box (for close-ups of whole-plan slabs)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepAlgoAPI_Common(shape, BRepPrimAPI_MakeBox(gp_Pnt(*lo), gp_Pnt(*hi)).Shape()).Shape()


def render_s5() -> list[str]:
    from tower import make_tower
    from s5_verify import realize

    OUT.mkdir(exist_ok=True)
    out = []
    sched = L.build_schedule(L.default_params())
    p = sched.params
    asm = make_tower(sched).value
    whole = scad.make_compound_from_assembly_rcompound(assembly=asm).wrapped  # the SDK's flattened tower (the renderer takes Solid / raw TopoDS only)
    out.append(scad.render_screenshot_rpath(
        shapes=[whole], output_path=str(OUT / "s5_tower.png"),
        views=[(20, 225, "tower: iso south-west"), (20, 45, "iso north-east (chamfer)"), (0, 270, "south elevation"),
               (90, 0, "plan from +Z")], view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
    out.append(scad.render_screenshot_rpath(
        shapes=[whole], output_path=str(OUT / "s5_south.png"), view=(0.0, 270.0), view_up=(0.0, 0.0, 1.0),
        show_callouts=False, show_legend=False))
    # setback close-up: first tier roof at the SW corner, two floors either side, parapet, roof slab
    comps = {c.component_id: c for c in asm.components}
    top0 = p.setback_every
    vx, vy = sched.tiers[0][0]
    r = 7000.0
    lo, hi = (vx - r, vy - r, sched.levels[f"floor{top0 - 1}"] - 1.0), (vx + r, vy + r, sched.levels[f"floor{top0 + 3}"])
    shapes = []
    for cid in (f"floor{top0 - 1}", f"floor{top0}", "parapet0", "slab-roof0", f"slab-floor{top0}",
                f"floor{top0 + 1}", f"floor{top0 + 2}", f"slab-floor{top0 + 2}"):
        for pid, s in realize(comps[cid]).items():
            if not pid:
                shapes.append(_clip(s, lo, hi))
                continue
            b = tight_bbox(s)
            if lo[0] < (b[0] + b[3]) / 2 < hi[0] and lo[1] < (b[1] + b[4]) / 2 < hi[1]:
                shapes.append(s)
    out.append(scad.render_screenshot_rpath(
        shapes=shapes, output_path=str(OUT / "s5_setback.png"),
        views=[(25, 225, f"tier 0 roof / tier 1 setback at v0 (floors {top0 - 1}-{top0 + 2})"),
               (25, 135, "from south-east"), (0, 270, "south elevation"), (0, 180, "west elevation")],
        view_up=(0.0, 0.0, 1.0), show_callouts=False, show_legend=False))
    return out


def render_s1(kinds) -> list[str]:
    OUT.mkdir(exist_ok=True)
    out = []
    for kind in kinds:
        sched = L.build_schedule(L.default_params(plan_kind=L.PlanKind(kind)))
        out.append(scad.render_screenshot_rpath(shapes=massing(sched), output_path=str(OUT / f"s1_massing_{kind}.png"),
                                                views=MASSING_VIEWS, view_up=(0.0, 0.0, 1.0), show_callouts=False,
                                                show_legend=False))
        out.append(plan_figure(sched, OUT / f"s1_plan_{kind}.png"))
        out.append(elevation_figure(sched, OUT / f"s1_elevation_{kind}.png"))
    return out


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "s1"
    if stage == "s1":
        for item in render_s1(sys.argv[2:] or [k.value for k in L.PlanKind]):
            print(item)
    elif stage == "s2":
        for item in render_s2():
            print(item)
    elif stage == "s3":
        for item in render_s3():
            print(item)
    elif stage == "s4":
        for item in render_s4():
            print(item)
    elif stage == "s5":
        for item in render_s5():
            print(item)
    else:
        raise SystemExit(f"unknown stage {stage}")
