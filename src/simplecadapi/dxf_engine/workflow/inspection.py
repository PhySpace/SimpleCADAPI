"""Single STEP -> editable DXF inspection sheet, powered by SimpleCADAPI HLR.

No reference model or drawing is needed. All view frames are explicit.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import ezdxf
import numpy as np
from simplecadapi.inspect import brep
from simplecadapi.dxf_engine.hlr import hlr_project, discretize_edge, arc_angles
from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Circle, GeomAbs_Line

VERSION = "1.0.0"


def frames():
    """d points observer -> object. SDK projector normal is -d."""
    definitions = [
        ("front", (0, 1, 0), (1, 0, 0)),
        ("top", (0, 0, -1), (1, 0, 0)),
        ("right", (-1, 0, 0), (0, 1, 0)),
        ("left", (1, 0, 0), (0, -1, 0)),
        ("bottom", (0, 0, 1), (1, 0, 0)),
        ("rear", (0, -1, 0), (-1, 0, 0)),
        ("iso", (-1, 1, -1), (1, 1, 0)),
    ]
    out = {}
    for name, d, r in definitions:
        d = np.array(d, dtype=float)
        d /= np.linalg.norm(d)
        r = np.array(r, dtype=float)
        r /= np.linalg.norm(r)
        u = np.cross(-d, r)
        assert np.allclose(np.cross(r, u), -d)
        out[name] = dict(
            direction=d.tolist(),
            right=r.tolist(),
            up=u.tolist(),
            projector_normal=(-d).tolist(),
        )
    return out


def rigid_shape(shape, transform):
    from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_Transform
    from simplecadapi._cpp.occt.gp import gp_Trsf
    from simplecadapi._glue.bridge import native_occt

    missing = [key for key in ("rotation", "translation_mm") if key not in transform]
    if missing:
        raise ValueError(f"Transform needs {', '.join(missing)} (rotation: 3x3, translation_mm: 3 values)")
    r = np.asarray(transform["rotation"], float)
    t = np.asarray(transform["translation_mm"], float)
    if (
        r.shape != (3, 3)
        or t.shape != (3,)
        or not np.isfinite(r).all()
        or not np.isfinite(t).all()
    ):
        raise ValueError("Expected finite 3x3 rotation and 3-vector translation_mm")
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-8) or not np.isclose(
        np.linalg.det(r), 1, atol=1e-8
    ):
        raise ValueError(
            "Only proper rigid transforms are allowed: no scale/shear/reflection"
        )
    tr = gp_Trsf()
    tr.SetValues(*[float(v) for v in np.column_stack((r, t)).ravel()])
    return BRepBuilderAPI_Transform(native_occt(shape), tr, True).Shape()


def edge_record(edge, deflection):
    ad, points = discretize_edge(edge=edge, deflection=deflection)
    if len(points) < 2:
        # Exact HLR sometimes returns an edge collapsed along the camera axis.
        # Confirm its projected extent, retain it as an audited DXF POINT.
        ts = np.linspace(ad.FirstParameter(), ad.LastParameter(), 33)
        samples = [(ad.Value(float(t)).X(), ad.Value(float(t)).Y()) for t in ts]
        span = float(np.max(np.ptp(np.asarray(samples), axis=0)))
        if span <= 1e-6:
            return dict(
                kind="POINT",
                points=[list(samples[0])],
                projected_extent_mm=span,
                reason="HLR edge projects to a point within 1e-6 mm",
            )
        points = samples
    record = dict(points=[list(map(float, p)) for p in points])
    if ad.GetType() == GeomAbs_Line:
        record.update(kind="LINE", start=record["points"][0], end=record["points"][-1])
    elif (
        ad.GetType() == GeomAbs_Circle
        and abs(ad.Circle().Axis().Direction().Z()) > 0.999999
    ):
        c = ad.Circle()
        center = c.Location()
        t0, t1 = ad.FirstParameter(), ad.LastParameter()
        record.update(center=[center.X(), center.Y()], radius=c.Radius())
        if abs(t1 - t0) >= 2 * math.pi - 1e-7:
            record["kind"] = "CIRCLE"
        else:
            a0, a1 = arc_angles(ad=ad, cxy=record["center"], t0=t0, t1=t1)
            record.update(kind="ARC", start_angle=a0, end_angle=a1)
    else:
        record["kind"] = "LWPOLYLINE"
    return record


def project_step(step, *, transform=None, deflection=0.03):
    step = Path(step).resolve()
    if not math.isfinite(deflection) or deflection <= 0:
        raise ValueError("deflection must be positive and finite")
    shape = brep.load_step_rshape(
        path=step, require_single_root=False, require_valid=True
    )
    if transform is not None:
        shape = rigid_shape(shape, transform)
    views = {}
    for name, frame in frames().items():
        vis, hid = hlr_project(
            shape=shape, view_dir=frame["projector_normal"], x_dir=frame["right"]
        )
        edges = []
        seen = set()
        duplicates = 0
        for visible, values in ((True, vis), (False, hid)):
            for index, edge in enumerate(values):
                try:
                    record = edge_record(edge, deflection)
                except Exception as exc:
                    raise RuntimeError(
                        f"{step.name}/{name}/{visible}/{index}: edge export failed"
                    ) from exc
                # Same analytic entity may be emitted as both HLR edge and outline.
                key = json.dumps(
                    {k: v for k, v in record.items() if k != "points"}, sort_keys=True
                )
                if record["kind"] in ("LWPOLYLINE", "POINT"):
                    key = json.dumps(np.round(record["points"], 8).tolist())
                key = (visible, key)
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                record["visible"] = visible
                edges.append(record)
        if not edges:
            raise ValueError(f"Empty HLR view: {name}")
        xy = np.asarray([p for e in edges for p in e["points"]])
        views[name] = dict(
            **frame,
            edges=edges,
            bounds=[xy.min(axis=0).tolist(), xy.max(axis=0).tolist()],
            input_hlr_edges=len(vis) + len(hid),
            duplicate_edges_removed=duplicates,
        )
    return dict(
        version=VERSION,
        source_step=str(step),
        source_sha256=hashlib.sha256(step.read_bytes()).hexdigest(),
        units="mm",
        transform=transform,
        deflection_mm=deflection,
        views=views,
        limitations=[
            "Geometry inspection sheet; no inferred manufacturing dimensions or sections",
            "Axes are explicit input/world axes, not recovered original drawing axes",
        ],
    )


def sheet_layout(projects, projection="first"):
    if projection not in ("first", "third"):
        raise ValueError("projection must be first or third")
    # Same model origin, shared union bounds and gap for EVERY compared sheet.
    max_span = max(
        float(np.max(np.subtract(v["bounds"][1], v["bounds"][0])))
        for p in projects
        for v in p["views"].values()
    )
    gap = max(8.0, max_span * 0.14)
    label = max(2.0, max_span * 0.025)
    if projection == "first":
        cells = dict(
            front=(1, 1),
            top=(1, 0),
            right=(0, 1),
            left=(2, 1),
            bottom=(1, 2),
            rear=(3, 1),
            iso=(3, 0),
        )
    else:
        cells = dict(
            front=(1, 1),
            top=(1, 2),
            right=(2, 1),
            left=(0, 1),
            bottom=(1, 0),
            rear=(3, 1),
            iso=(3, 2),
        )
    # Center all views on one projected world point, not each silhouette separately.
    union = {}
    for name in cells:
        bounds = np.asarray([p["views"][name]["bounds"] for p in projects])
        union[name] = (bounds[:, 0, :].min(axis=0), bounds[:, 1, :].max(axis=0))
    widths = [
        max(union[n][1][0] - union[n][0][0] for n, c in cells.items() if c[0] == x)
        + 2 * gap
        for x in range(4)
    ]
    heights = [
        max(union[n][1][1] - union[n][0][1] for n, c in cells.items() if c[1] == y)
        + 2 * gap
        + 3 * label
        for y in range(3)
    ]
    xs = np.r_[0, np.cumsum(widths)]
    ys = np.r_[0, np.cumsum(heights)]
    offsets = {}
    rects = {}
    for name, cell in cells.items():
        center = (union[name][0] + union[name][1]) / 2
        x, y = cell
        w, h = widths[x], heights[y]
        offsets[name] = [
            float(xs[x] + w / 2 - center[0]),
            float(ys[y] + (h - 3 * label) / 2 - center[1]),
        ]
        rects[name] = [float(xs[x]), float(ys[y]), float(w), float(h)]
    return dict(
        projection=projection,
        scale=1.0,
        units="mm",
        cell_rectangles=rects,
        label_height=label,
        sheet_size=[float(xs[-1]), float(ys[-1])],
        cells=cells,
        offsets=offsets,
        common_origin_and_scale=True,
        frame_contract="right cross up = minus(observer-to-object direction)",
    )


def new_document(layout):
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.linetypes.new(
        "HIDDEN_MODEL",
        dxfattribs={"description": "Hidden edges", "pattern": [3.0, 2.0, -1.0]},
    )
    for name, color, lt, weight in [
        ("VISIBLE", 7, "Continuous", 35),
        ("HIDDEN", 8, "HIDDEN_MODEL", 15),
        ("LABELS", 7, "Continuous", 15),
        ("FRAME", 8, "Continuous", 13),
        ("REFERENCE", 4, "Continuous", 25),
        ("CANDIDATE", 1, "Continuous", 25),
    ]:
        doc.layers.new(
            name, dxfattribs={"color": color, "linetype": lt, "lineweight": weight}
        )
    doc.set_modelspace_vport(
        height=layout["sheet_size"][1] * 1.06,
        center=(layout["sheet_size"][0] / 2, layout["sheet_size"][1] / 2),
    )
    return doc


def add_geometry(msp, project, layout, *, overlay_layer=None, hidden=True):
    for name, view in project["views"].items():
        ox, oy = layout["offsets"][name]

        def point(p):
            return (p[0] + ox, p[1] + oy)

        for e in view["edges"]:
            if not hidden and not e["visible"]:
                continue
            attrs = {
                "layer": overlay_layer or ("VISIBLE" if e["visible"] else "HIDDEN")
            }
            if e["kind"] == "LINE":
                msp.add_line(point(e["start"]), point(e["end"]), dxfattribs=attrs)
            elif e["kind"] == "POINT":
                msp.add_point(point(e["points"][0]), dxfattribs=attrs)
            elif e["kind"] == "CIRCLE":
                msp.add_circle(point(e["center"]), e["radius"], dxfattribs=attrs)
            elif e["kind"] == "ARC":
                msp.add_arc(
                    point(e["center"]),
                    e["radius"],
                    e["start_angle"],
                    e["end_angle"],
                    dxfattribs=attrs,
                )
            else:
                msp.add_lwpolyline([point(p) for p in e["points"]], dxfattribs=attrs)


def axis_label(v):
    return "(" + ",".join(f"{float(x):+.2g}" for x in v) + ")"


def add_labels(msp, project, layout, title):
    th = layout["label_height"]
    for name, cell in layout["cells"].items():
        x, y, w, h = layout["cell_rectangles"][name]
        f = project["views"][name]
        msp.add_lwpolyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            close=True,
            dxfattribs={"layer": "FRAME"},
        )
        for i, text in enumerate(
            [
                name.upper() + "  d=" + axis_label(f["direction"]),
                "r=" + axis_label(f["right"]) + "  u=" + axis_label(f["up"]),
            ]
        ):
            msp.add_text(
                text, dxfattribs={"layer": "LABELS", "height": th * 0.62}
            ).set_placement((x + th, y + h - th * (1 + i)))
    msp.add_text(
        title[:100], dxfattribs={"layer": "LABELS", "height": th}
    ).set_placement((th, -th * 1.5))
    msp.add_text(
        f"{layout['projection'].upper()} ANGLE / mm / 1:1 / geometry inspection, no inferred dimensions",
        dxfattribs={"layer": "LABELS", "height": th * 0.7},
    ).set_placement((th, -th * 2.8))


def render_saved_dxf(path):
    """Both previews come from the reopened, editable DXF."""
    import matplotlib

    matplotlib.use("Agg")
    from ezdxf.addons.drawing import RenderContext, Frontend, layout
    from ezdxf.addons.drawing.config import Configuration, ColorPolicy, BackgroundPolicy
    from ezdxf.addons.drawing.svg import SVGBackend
    from ezdxf.addons.drawing.matplotlib import qsave

    doc = ezdxf.readfile(path)
    audit = doc.audit()
    if audit.has_errors:
        raise ValueError(f"DXF audit errors: {len(audit.errors)}")
    config = Configuration(
        background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR
    )
    qsave(
        doc.modelspace(),
        Path(path).with_suffix(".png"),
        dpi=130,
        size_inches=(16, 11),
        bg="#ffffff",
        config=config,
    )
    backend = SVGBackend()
    Frontend(RenderContext(doc), backend, config=config).draw_layout(
        doc.modelspace(), finalize=True
    )
    svg = backend.get_string(
        layout.Page(0, 0, layout.Units.mm), settings=layout.Settings(scale=1)
    )
    Path(path).with_suffix(".svg").write_text(svg, encoding="utf-8")
    return dict(
        entity_count=len(doc.modelspace()),
        entity_types=dict(Counter(e.dxftype() for e in doc.modelspace())),
        audit_errors=len(audit.errors),
    )


def export_sheet(project, output, *, layout=None, projection="first", title=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    layout = layout or sheet_layout([project], projection)
    # Accept the metadata this exporter writes (layout nested under "layout"), so a layout can be
    # shared by passing one sheet's .json to the next (--layout-json).
    layout = layout.get("layout", layout)
    if layout.get("scale") != 1:
        raise ValueError("This exporter keeps DXF modelspace at 1:1")
    doc = new_document(layout)
    msp = doc.modelspace()
    add_geometry(msp, project, layout)
    add_labels(msp, project, layout, title or Path(project["source_step"]).stem)
    doc.saveas(output)
    audit = render_saved_dxf(output)
    metadata = dict(
        **project, layout=layout, output_dxf=str(output.resolve()), reopen_audit=audit
    )
    output.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def export_overlay(reference, candidate, output, *, layout):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = new_document(layout)
    msp = doc.modelspace()
    add_geometry(msp, reference, layout, overlay_layer="REFERENCE", hidden=False)
    add_geometry(msp, candidate, layout, overlay_layer="CANDIDATE", hidden=False)
    add_labels(
        msp,
        reference,
        layout,
        "Visible edges: CYAN = reference / RED = candidate; common frame, no extra fitting",
    )
    doc.saveas(output)
    return render_saved_dxf(output)


def drawing_templates():
    return json.loads(
        Path(__file__).with_name("drawing_templates.json").read_text(encoding="utf-8")
    )


def export_view_previews(dxf_path, layout, output_dir):
    """Write separate SVG windows from a saved shared-layout DXF."""
    import copy

    from ezdxf.addons.drawing import (
        Frontend,
        RenderContext,
        config,
        layout as page_layout,
    )
    from ezdxf.addons.drawing.svg import SVGBackend
    from ezdxf.math import BoundingBox2d

    doc = ezdxf.readfile(dxf_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    backend = SVGBackend()
    style = config.Configuration(background_policy=config.BackgroundPolicy.WHITE)
    Frontend(RenderContext(doc), backend, config=style).draw_layout(doc.modelspace())
    paths = {}
    cells = layout.get("layout", layout)["cell_rectangles"]
    for name in frames():
        if name not in cells:
            continue
        x, y, w, h = cells[name]
        svg = copy.deepcopy(backend).get_string(
            page_layout.Page(0, 0, page_layout.Units.mm),
            settings=page_layout.Settings(scale=1, crop_at_margins=True),
            render_box=BoundingBox2d([(x, y), (x + w, y + h)]),
        )
        path = output / f"{name}.svg"
        path.write_text(svg, encoding="utf-8")
        paths[name] = path
    return paths
