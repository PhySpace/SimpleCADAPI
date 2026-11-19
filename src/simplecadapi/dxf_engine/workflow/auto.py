"""Propose a reviewable engineering drawing from a single STEP solid."""

from __future__ import annotations

import hashlib
import json
import math
from importlib.metadata import version
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface
from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder
from simplecadapi._cpp.occt.TopAbs import TopAbs_REVERSED
from simplecadapi.dxf_engine import ViewDecl
from simplecadapi.dxf_engine.refs import project, view_frame
from simplecadapi.dxf_engine.views import BIG, _cut_near_half, _section_loops
from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.model import _bounding_box

from .declaration import (
    apply_drawing_action,
    build_plan,
    load_engineering_shape,
    write_engineering_sheet,
)
from .projection import (
    DrawingProjection,
    MESH_DEFLECTION_MM,
    physical_shape,
    projection_mode,
)
from .inspection import frames

SHEETS = ("A4", "A3", "A2", "A1", "A0")
ORTHOGRAPHIC_FRAMES = tuple(name for name in frames() if name != "iso")
ALGORITHM = "1.1.0"


@dataclass(frozen=True)
class Bore:
    entity: str
    center: tuple[float, float, float]
    axis: tuple[float, float, float]
    radius: float
    length: float


def find_bores(model, faces):
    bores, unresolved = [], []
    for face in faces:
        surface = BRepAdaptor_Surface(face)
        if (
            surface.GetType() != GeomAbs_Cylinder
            or face.Orientation() != TopAbs_REVERSED
        ):
            continue
        cylinder = surface.Cylinder()
        first, last = surface.FirstVParameter(), surface.LastVParameter()
        sweep = surface.LastUParameter() - surface.FirstUParameter()
        entity = model.id_for_shape("face", face)
        if sweep < math.tau - 1e-5 or last - first < 1e-6:
            unresolved.append(entity)
            continue
        axis = cylinder.Axis().Direction().Coord()
        center = tuple(
            x + (first + last) / 2 * d
            for x, d in zip(cylinder.Location().Coord(), axis)
        )
        bores.append(Bore(entity, center, axis, cylinder.Radius(), last - first))
    return bores, unresolved


def visible_bores(view, bores):
    """Require an end-on cylindrical face and matching visible HLR circle/arc evidence."""
    circles = []
    for adaptor, _, visible in view["edges"]:
        if visible and adaptor.GetType() == GeomAbs_Circle:
            circle = adaptor.Circle()
            circles.append((circle.Location().Coord()[:2], circle.Radius()))
    result = []
    for bore in bores:
        if abs(np.dot(bore.axis, view["frame"][2])) < 1 - 1e-8:
            continue
        center = project(bore.center, view["frame"])
        tolerance = max(1e-5, min(0.025, bore.radius * 0.02))
        if any(
            abs(radius - bore.radius) <= tolerance
            and math.dist(center, point) <= tolerance
            for point, radius in circles
        ):
            result.append((bore, center))
    return result


def choose_views(projector, bores, primary, projection, layout):
    observations = []
    for name, basis in frames().items():
        if name == "iso":
            continue
        n, right = tuple(basis["projector_normal"]), tuple(basis["right"])
        view = projector.view(ViewDecl(name, projector.shape, n, right))
        x0, y0, x1, y1 = view["lbox"]
        width, height = x1 - x0, y1 - y0
        hidden = math.fsum(
            math.dist(a, b)
            for _, pts, visible in view["edges"]
            if not visible
            for a, b in zip(pts, pts[1:])
        )
        total = math.fsum(
            math.dist(a, b) for _, pts, _ in view["edges"] for a, b in zip(pts, pts[1:])
        )
        observations.append(
            dict(
                frame=name,
                normal=n,
                right=right,
                area_mm2=width * height,
                bounds_mm=view["lbox"],
                visible_bores=len(visible_bores(view, bores)),
                visible_fraction=1 - hidden / total if total else 0.0,
            )
        )
    max_area = max(o["area_mm2"] for o in observations)
    for o in observations:
        # Round the score so tiny kernel noise cannot change an otherwise tied ordering.
        o["score"] = round(
            2 * o["visible_bores"]
            + 2 * o["area_mm2"] / max_area
            + o["visible_fraction"],
            6,
        )
    observations.sort(key=lambda o: -o["score"])
    selected = (
        next(o for o in observations if o["frame"] == primary)
        if primary
        else observations[0]
    )
    x0, y0, x1, y1 = selected["bounds_mm"]
    longitudinal = y1 - y0 > 1.6 * (x1 - x0)
    r, u, n = view_frame(selected["normal"], selected["right"])
    if longitudinal:
        r, u = u, tuple(-component for component in r)
    vertical, horizontal = (
        ("below", "left") if projection == "first" else ("above", "right")
    )
    gap = 24 if layout == "compact" else 30
    views = [
        dict(name="front", normal=n, right=r),
        dict(
            name="top",
            normal=u,
            right=r,
            align=dict(to="front", side=vertical, gap=gap),
        ),
        dict(
            name="right",
            normal=r,
            right=tuple(-v for v in n),
            align=dict(to="front", side=horizontal, gap=gap + 2),
        ),
    ]
    decision = dict(
        primary_source_frame=selected["frame"],
        forced=primary is not None,
        rolled_to_landscape=longitudinal,
        rule="Rank six STEP axis views by visible end-on bores, projected area and visible edge fraction.",
        candidates=observations,
    )
    return views, decision


def choose_section(shape, bounds, views, bores):
    if max(bounds["size"]) >= BIG:
        return None, dict(
            status="not_proposed",
            reason="Model span exceeds the SDK section cutter range.",
            candidates=[],
        )
    center = np.array(bounds["center"])
    records = []
    for base in views[1:]:
        frame = view_frame(base["normal"], base["right"])
        normal = np.array(frame[2])
        start, end = sorted(
            float(normal @ endpoint) for endpoint in (bounds["min"], bounds["max"])
        )
        span = end - start
        if span < 1e-6:
            continue
        parallel_axes = [
            bore for bore in bores if abs(float(normal @ bore.axis)) < 1e-8
        ]
        bore_planes = defaultdict(list)
        for bore in parallel_axes:
            offset = float(normal @ bore.center)
            if start + 0.05 * span < offset < end - 0.05 * span:
                bore_planes[round(offset, 4)].append(offset)
        ordered = sorted(
            bore_planes.values(),
            key=lambda group: (-len(group), abs(group[0] - (start + end) / 2)),
        )
        offsets = [start + fraction * span for fraction in (0.5, 0.25, 0.75)] + [
            group[0] for group in ordered[:2]
        ]
        offsets = list(dict.fromkeys(round(offset, 6) for offset in offsets))
        for offset in offsets:
            point = tuple(
                (center + normal * (offset - float(normal @ center))).tolist()
            )
            record = dict(
                sibling=base["name"],
                point_mm=point,
                offset_mm=offset,
                distance_from_middle_mm=abs(offset - (start + end) / 2),
            )
            try:
                cut = _cut_near_half(shape, point, frame)
                loops = _section_loops(cut, point, frame)
            except (ValueError, RuntimeError) as error:
                records.append(record | dict(status="cut_failed", reason=str(error)))
                continue
            axis_hits = [
                b.entity
                for b in parallel_axes
                if abs(float(normal @ b.center) - offset) < max(0.001, 0.05 * b.radius)
            ]
            perimeter = math.fsum(
                math.dist(a, b)
                for loop in loops
                for a, b in zip(loop, loop[1:] + loop[:1])
            )
            # A single ordinary hatch loop by itself is also what a rectangular block would show.
            useful = bool(loops and (axis_hits or len(loops) > 1))
            records.append(
                record
                | dict(
                    status="candidate" if useful else "limited_evidence",
                    hatch_loops=len(loops),
                    perimeter_mm=round(perimeter, 4),
                    bore_axis_refs=axis_hits,
                )
            )
    useful = [record for record in records if record["status"] == "candidate"]
    if not useful:
        return None, dict(
            status="not_proposed",
            reason="No cut crossed a verified bore axis or produced multiple material boundary loops.",
            candidates=records,
        )
    picked = max(
        useful,
        key=lambda row: (
            len(row["bore_axis_refs"]),
            row["hatch_loops"],
            row["perimeter_mm"],
            -row["distance_from_middle_mm"],
        ),
    )
    base = next(v for v in views if v["name"] == picked["sibling"])
    declaration = dict(
        name="section",
        normal=base["normal"],
        right=base["right"],
        align=dict(to=base["name"], side=base["align"]["side"], gap=34),
        section=dict(label="A", mark_in="front", point=picked["point_mm"]),
    )
    return declaration, dict(
        status="proposed",
        selected=picked,
        candidates=records,
        rule="Rank cuts by intersected bore axes, hatch boundary loops, boundary perimeter and centrality.",
    )


def propose_dimensions(projector, views, bores, policy):
    dims = []
    if policy != "none":
        depth = (
            ("top", "y", "right")
            if any(row["name"] == "top" for row in views)
            else ("right", "x", "top")
        )
        for caption, view, axis, side in [
            ("overall width", "front", "x", "top"),
            ("overall height", "front", "y", "right"),
            ("overall depth", *depth),
        ]:
            dims.append(
                dict(
                    caption=caption,
                    kind="overall",
                    view=view,
                    semantic="linear",
                    extent=axis,
                    side=side,
                )
            )
    groups = defaultdict(list)
    for bore in bores:
        groups[round(2 * bore.radius, 4)].append(bore)
    candidates = defaultdict(list)
    if policy == "auto":
        for row in views:
            if "section" in row:
                continue
            name = row["name"]
            drawing = projector.view(
                ViewDecl(name, projector.shape, row["normal"], row["right"])
            )
            x0, y0, x1, y1 = drawing["lbox"]
            for bore, (x, y) in visible_bores(drawing, bores):
                side = "left" if x - x0 < x1 - x else "right"
                edge_clearance = min(x - x0, x1 - x)
                angles = (200, 160) if side == "left" else (340, 20)
                angle = angles[y >= (y0 + y1) / 2]
                candidates[round(2 * bore.radius, 4)].append(
                    (max(0, edge_clearance), name, bore.entity, angle)
                )
    coverage = []
    for diameter, group in sorted(groups.items()):
        options = sorted(candidates[diameter])
        entry = dict(
            diameter_mm=diameter,
            model_faces=[bore.entity for bore in group],
            visible_options=len(options),
            status="not_visible" if policy == "auto" else "disabled_by_policy",
        )
        if options:
            _, name, entity, angle = options[0]
            caption = f"bore diameter {diameter:g}"
            entry.update(status="proposed", entity=entity, view=name, caption=caption)
            decimals = len(f"{diameter:.4f}".rstrip("0").partition(".")[2])
            dims.append(
                dict(
                    caption=caption,
                    kind="size",
                    view=name,
                    semantic="diameter",
                    of=dict(entity=entity),
                    at=angle,
                    dec=decimals,
                )
            )
        coverage.append(entry)
    return dims, dict(
        policy=policy,
        bore_groups=coverage,
        rule="Measure three extents and one geometrically verified example per visible bore diameter. No quantity is inferred.",
    )


def adjust_diameter_labels(plan, issues):
    """Try SDK-validated angle changes only for reported diameter placement issues."""
    warned = set()
    for issue in issues:
        if issue.severity == "warning":
            warned.add(issue.element)
            warned.update(issue.data.get("with", []))
    actions = []
    for resolved in plan.resolved:
        if (
            resolved.kind != "dim"
            or resolved.draw.get("kind") != "dia-man"
            or f"dim:{resolved.name}" not in warned
        ):
            continue
        initial = resolved.draw["at"]
        angles = sorted(
            (0, 15, 30, 45, 135, 150, 165, 180, 195, 210, 225, 315, 330, 345),
            key=lambda angle: abs((angle - initial + 180) % 360 - 180),
        )
        proposals = (
            dict(op="dia", name=resolved.name, at=angle, extend_mm=extension)
            for extension in (6, 12, 20)
            for angle in angles
        )
        accepted = next(
            (
                action
                for action in proposals
                if apply_drawing_action(plan, action)["ok"]
            ),
            None,
        )
        if accepted:
            actions.append(accepted)
    return actions


def fit_sheet(shape, spec, sheet, preferred_scale, projector):
    attempts = []
    best = None
    for fmt in (sheet,) if sheet else SHEETS:
        for gap_delta in (0, 8):
            # Freeze the actual per-view gaps and sheet scale for replay.
            trial_views = [
                v | {"align": v["align"] | {"gap": v["align"]["gap"] + gap_delta}}
                if "align" in v
                else v
                for v in spec["views"]
            ]
            declaration = spec | dict(
                sheet=spec["sheet"] | dict(sheet=fmt), views=trial_views
            )
            try:
                plan = build_plan(
                    shape, declaration, spec["sheet"]["title"], projector=projector
                )
            except (ValueError, RuntimeError) as error:
                attempts.append(
                    dict(sheet=fmt, gap_delta_mm=gap_delta, error=str(error))
                )
                continue
            issues = plan.issues()
            actions = (
                adjust_diameter_labels(plan, issues)
                if plan.s >= preferred_scale
                else []
            )
            if actions:
                declaration["actions"] = actions
                issues = plan.issues()
            errors = sum(i.severity == "error" for i in issues)
            warnings = [
                i.code
                for i in issues
                if i.severity == "warning" and i.code != "UNDIMENSIONED_CYLINDER"
            ]
            unreadable = plan.s < preferred_scale
            outside = warnings.count("OUTSIDE_FRAME") + warnings.count(
                "IN_KEEPOUT_ZONE"
            )
            score = (
                errors,
                outside,
                unreadable,
                len(warnings),
                SHEETS.index(fmt),
                -plan.s,
                gap_delta,
            )
            attempts.append(
                dict(
                    sheet=fmt,
                    gap_delta_mm=gap_delta,
                    scale=plan.s,
                    errors=errors,
                    layout_warnings=warnings,
                    meets_preferred_scale=not unreadable,
                    actions=actions,
                )
            )
            if best is None or score < best[0]:
                best = (score, declaration, plan, len(attempts) - 1)
            if errors == 0 and not warnings and (plan.s >= preferred_scale or sheet):
                break
        if best and best[0][:4] == (0, 0, False, 0):
            break
    if best is None:
        reasons = dict.fromkeys(row["error"] for row in attempts)
        raise ValueError(
            "No sheet with resolved drawing geometry: " + " | ".join(reasons)
        )
    _, declaration, plan, index = best
    declaration["sheet"]["scale"] = plan.s
    return (
        declaration,
        plan,
        dict(
            preferred_scale=preferred_scale,
            selected_attempt=index,
            attempts=attempts,
            rule="Prefer valid placement inside the sheet, then readable scale, fewer warning conflicts and the smaller sheet.",
        ),
    )


def auto_drawing(
    step,
    output,
    *,
    primary=None,
    sheet=None,
    section=True,
    dimensions="auto",
    projection=None,
    layout=None,
    section_view=None,
    template=None,
    plan_only=False,
    transform=None,
    pdf=False,
    hlr="auto",
    design_intent=None,
):
    step, output = Path(step).resolve(), Path(output).resolve()
    if output.suffix.lower() != ".dxf":
        raise ValueError("Automatic drawing output must have a .dxf extension")
    if primary not in (*ORTHOGRAPHIC_FRAMES, None) or sheet not in (*SHEETS, None):
        raise ValueError("Unknown primary view or sheet format")
    if dimensions not in ("auto", "overall", "none"):
        raise ValueError("dimensions must be auto, overall or none")
    entry = None
    if template:
        from .inspection import drawing_templates

        entry = drawing_templates()["templates"].get(template)
        if entry is None:
            raise ValueError(
                f"Unknown drawing template {template!r}; use --templates to list choices"
            )
    defaults = entry["options"] if entry else {}
    projection_label = projection or defaults.get("projection")
    projection = projection_label or "first"
    layout_preset = layout or defaults.get("layout", "aligned")
    section_view = section_view or defaults.get("section_view", "full")
    if (
        projection not in ("first", "third")
        or layout_preset not in ("aligned", "compact")
        or section_view not in ("full", "removed")
    ):
        raise ValueError("Invalid projection, layout preset or section kind")
    shape = load_engineering_shape(step, transform)
    model = brep.index_shape_rbrepmodel(shape=shape)
    if len(model.bodies) != 1:
        raise ValueError(
            f"Automatic engineering drawing requires one solid; found {len(model.bodies)}. Use a part STEP or declare views manually."
        )
    solid = physical_shape(shape, model)
    solid_model = brep.index_shape_rbrepmodel(shape=solid)
    recommended, complexity = projection_mode(solid_model)
    if hlr not in ("auto", "exact", "polygonal"):
        raise ValueError("Unknown HLR mode")
    mode = recommended if hlr == "auto" else hlr
    projector = DrawingProjection(solid, mode, MESH_DEFLECTION_MM)
    bounds = _bounding_box(solid)
    bores, unresolved = find_bores(model, solid_model.faces)
    views, view_decision = choose_views(
        projector, bores, primary, projection, layout_preset
    )
    if section and mode == "exact":
        cut, section_decision = choose_section(solid, bounds, views, bores)
    else:
        cut, section_decision = (
            None,
            dict(
                status="deferred_for_polygonal_review"
                if section
                else "disabled_by_option",
                candidates=[],
            ),
        )
    if cut:
        cut["section"]["kind"] = section_view
        sibling = section_decision["selected"]["sibling"]
        if layout_preset == "compact" and section_view == "full":
            index = next(i for i, row in enumerate(views) if row["name"] == sibling)
            cut["align"] = views[index]["align"].copy()
            views[index] = cut
            section_decision["replaces_view"] = sibling
        else:
            views.append(cut)
    dims, coverage = propose_dimensions(projector, views, bores, dimensions)
    coverage["unresolved_partial_inner_cylinders"] = unresolved
    source_name = (
        design_intent["source"]["product_id"]
        if design_intent is not None
        else step.stem
    )
    number, _, name = source_name.partition("_")
    title = name if number.isdecimal() and name else source_name
    spec = dict(
        sheet=dict(
            title=title.replace("_", " "),
            dwg_no=number if number.isdecimal() else "",
            front="front",
            scale=None,
        ),
        views=views,
        dimensions=dims,
    )
    if design_intent is not None:
        intent_dims = design_intent["dimensions"]
        intent_extents = {
            (d["view"], d["extent"]) for d in intent_dims if "extent" in d
        }
        spec["dimensions"] = [
            d for d in dims if (d["view"], d.get("extent")) not in intent_extents
        ] + intent_dims
        spec["datums"] = design_intent["datums"]
        spec["design_intent"] = {k: design_intent[k] for k in ("source", "parameters")}
    if mode != "exact":
        spec["hlr"] = mode
        spec["sheet"]["notes"] = ["TESSELLATED REVIEW VIEWS", "VERIFY THREAD CALLOUTS"]
    if projection_label:
        spec["sheet"]["projection"] = projection_label
    preferred_scale = 1.0 if max(bounds["size"]) <= 500 else 0.5
    spec, plan, layout = fit_sheet(shape, spec, sheet, preferred_scale, projector)
    issues = [issue.as_dict() for issue in plan.issues()]
    coverage["measured"] = [
        dict(caption=dim.caption, view=dim.view, value_mm=dim._measured)
        for dim in plan.dims
    ]
    status = (
        "needs_revision"
        if any(issue["severity"] == "error" for issue in issues)
        else "review_required"
    )
    spec_path, report_path = (
        output.with_suffix(".drawing.json"),
        output.with_suffix(".plan.json"),
    )
    report = dict(
        schema_version=1,
        algorithm_version=ALGORITHM,
        sdk_version=version("simplecadapi"),
        status=status,
        source=dict(
            step=str(step),
            sha256=hashlib.sha256(step.read_bytes()).hexdigest(),
            transform=transform,
        ),
        options=dict(
            primary_view=primary,
            sheet=sheet,
            section=section,
            section_view=section_view,
            dimensions=dimensions,
            projection=projection,
            layout=layout_preset,
        ),
        declaration=str(spec_path),
        view_selection=view_decision,
        section=section_decision,
        hlr=dict(
            requested=hlr,
            mode=mode,
            recommended=recommended,
            complexity=complexity,
            mesh_deflection_mm=MESH_DEFLECTION_MM if mode == "polygonal" else None,
            representation="solid-only",
            projection_bounds=plan.projection_bounds(),
        ),
        dimensions=coverage,
        layout=layout,
        issues=issues,
        review=[
            "Confirm the primary view, section and dimension scheme against design intent.",
            "Supply any needed datums, fits, tolerances, thread and hole-depth semantics explicitly.",
            "Regenerate proposals for a new STEP revision before reusing model entity IDs.",
        ],
    )
    if entry:
        report["template"] = dict(id=template, **entry)
    if plan.design_intent is not None:
        report["design_intent"] = plan.design_intent
    output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(
        status=status,
        declaration=str(spec_path),
        plan=str(report_path),
        sheet=plan.fmt.name,
        scale=plan.s,
        views=list(plan.views),
        dimension_count=len(plan.dims),
    )
    if not plan_only and status != "needs_revision":
        metadata = write_engineering_sheet(
            step, output, spec, plan, transform=transform, pdf=pdf
        )
        report["issues"] = metadata["issues"]
        result.update(
            dxf=str(output),
            preview=str(output.with_suffix(".png")),
            audit=metadata["reopen_audit"],
        )
        if pdf:
            result["pdf"] = metadata["output_pdf"]
        report["render"] = {
            key: result[key]
            for key in ("dxf", "preview", "pdf", "audit")
            if key in result
        }
    with TemporaryDirectory(dir=output.parent) as folder:
        for path, data in ((spec_path, spec), (report_path, report)):
            staged = Path(folder) / path.name
            staged.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
                encoding="utf-8",
            )
            staged.replace(path)
    return result
