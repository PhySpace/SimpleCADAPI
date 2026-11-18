"""Build and audit a declared engineering drawing from STEP."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf
import numpy as np
from simplecadapi.inspect import brep

from .inspection import frames, rigid_shape
from .details import place_details, render_print_page, use_diameter_font


def validate_intent(plan, declaration):
    from simplecadapi.dxf_engine.bind import fmt_number
    from simplecadapi.dxf_engine.checks import Issue

    if declaration is None:
        return None, []
    measured = {d.caption: d for d in plan.dims}
    declared = {d.caption: d for d in plan.d.dims}
    parameters, issues = [], []
    for entry in declaration["parameters"]:
        linked = []
        for row in entry.get("dimensions", []):
            cap, expected = row["caption"], row["expected_mm"]
            dim = measured.get(cap)
            actual = dim._measured if dim is not None else None
            matches = actual is not None and abs(actual - expected) <= 0.001
            # Keeping the declaration, the SDK measurement and the original binding together
            # makes removal/edits of a carrier dimension visible on replay.
            matches = (
                matches
                and entry["name"] in declared[cap].covers
                and dim._bound
                and fmt_number(actual, dim.dec) == fmt_number(expected, dim.dec)
            )
            linked.append(row | dict(measured_mm=actual, matches=matches))
            if not matches:
                issues.append(
                    Issue(
                        "DESIGN_INTENT_MISMATCH",
                        "error",
                        f"dim:{cap}",
                        f"{entry['name']} expects {expected:g} mm from its bound geometry; got {actual}",
                        "Correct the model or feature reference, then regenerate the notebook declaration.",
                    )
                )
        state = (
            ("verified" if all(d["matches"] for d in linked) else "mismatch")
            if linked
            else entry["status"]
        )
        parameters.append(entry | dict(status=state, dimensions=linked))
    return dict(source=declaration["source"], parameters=parameters), issues


def fields(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    unknown = value.keys() - set(allowed.split())
    if unknown:
        raise ValueError(f"{label}: unknown fields {', '.join(sorted(unknown))}")
    return value


def vector(value, size, label):
    if not isinstance(value, (tuple, list)) or len(value) != size:
        raise ValueError(f"{label} must have {size} coordinates")
    if not all(
        isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
        for x in value
    ):
        raise ValueError(f"{label} must contain finite numbers")
    return tuple(float(x) for x in value)


def positive(value, label):
    (number,) = vector([value], 1, label)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def view_definition(row, shape, standard_frames):
    from simplecadapi.dxf_engine import ViewDecl

    fields(row, "name frame normal right align section auxiliary", "view")
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Each view needs a nonempty name")
    frame = row.get("frame")
    if frame is not None:
        if frame not in standard_frames or "normal" in row or "right" in row:
            raise ValueError(f"{name}: use one named frame, or normal and right")
        normal, right = (
            tuple(standard_frames[frame][key]) for key in ("projector_normal", "right")
        )
    else:
        normal = vector(row.get("normal"), 3, f"{name}.normal")
        right = vector(row.get("right"), 3, f"{name}.right")
        if (
            math.hypot(*normal) == 0
            or math.hypot(*right) == 0
            or abs(np.dot(normal, right))
            > 1e-8 * math.hypot(*normal) * math.hypot(*right)
        ):
            raise ValueError(
                f"{name}: normal and right must be nonzero and perpendicular"
            )
        normal = tuple(x / math.hypot(*normal) for x in normal)
        right = tuple(x / math.hypot(*right) for x in right)

    align = fields(row.get("align", {}), "to side gap", f"{name}.align")
    if align and (
        not align.get("to")
        or align.get("side", "below") not in ("below", "above", "left", "right")
    ):
        raise ValueError(f"{name}.align requires a parent and a valid side")
    if "gap" in align:
        positive(align["gap"], f"{name}.align.gap")
    options = {}
    if "section" in row:
        section = fields(row["section"], "point label mark_in kind", f"{name}.section")
        if section.get("kind", "full") not in ("full", "removed"):
            raise ValueError(f"{name}.section.kind must be full or removed")
        label = section.get("label")
        if (
            not isinstance(label, str)
            or not label.strip()
            or not section.get("mark_in")
        ):
            raise ValueError(
                f"{name}.section requires a label and a mark_in parent view"
            )
        options = dict(
            section=vector(section.get("point"), 3, f"{name}.section.point"),
            label=label,
            mark_in=section["mark_in"],
        )
    return ViewDecl(name, shape, normal, right, align=align, **options)


def cylinder_reference(model, spec):
    from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface
    from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Cylinder

    fields(spec, "axis_point axis radius_mm tolerance_mm", "cylinder reference")
    point = np.array(vector(spec.get("axis_point"), 3, "cylinder.axis_point"))
    axis = np.array(vector(spec.get("axis"), 3, "cylinder.axis"))
    length = math.hypot(*axis)
    if length == 0:
        raise ValueError("cylinder.axis must be nonzero")
    axis /= length
    tol = positive(spec.get("tolerance_mm", 0.01), "cylinder.tolerance_mm")
    radius = (
        positive(spec["radius_mm"], "cylinder.radius_mm")
        if "radius_mm" in spec
        else None
    )
    matches = []
    for face in model.faces:
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_Cylinder:
            continue
        cylinder = surface.Cylinder()
        loc = np.array(cylinder.Location().Coord())
        direction = np.array(cylinder.Axis().Direction().Coord())
        offset = point - loc
        depth = float(offset @ direction)
        if (
            abs(float(axis @ direction)) >= 1 - 1e-8
            and np.linalg.norm(np.cross(offset, direction)) <= tol
            and surface.FirstVParameter() - tol
            <= depth
            <= surface.LastVParameter() + tol
            and (radius is None or abs(cylinder.Radius() - radius) <= tol)
        ):
            matches.append(face)
    if len(matches) != 1:
        ids = [model.id_for_shape("face", face) for face in matches]
        raise ValueError(
            f"cylinder reference matches {len(matches)} model faces {ids}; specify a point inside a unique axial span, a radius filter, or an entity ID"
        )
    return matches[0]


def reference_resolver(shape):
    model = None

    def resolve(ref):
        nonlocal model
        fields(ref, "entity cylinder plane circle", "model reference")
        if len(ref) != 1:
            raise ValueError(
                "A model reference needs one entity ID or a cylinder, plane or circle selector"
            )
        if model is None:
            model = brep.index_shape_rbrepmodel(shape=shape)
        if "entity" in ref:
            kind, _, entity = model.resolve_entity(ref["entity"])
            if kind == "body":
                raise ValueError("A dimension reference must be a face, edge or vertex")
            return kind, entity
        if "cylinder" in ref:
            return "face", cylinder_reference(model, ref["cylinder"])
        kind = next(iter(ref))
        return analytic_reference(model, kind, ref[kind])

    return resolve


def analytic_reference(model, kind, spec):
    from simplecadapi._cpp.occt.BRepAdaptor import (
        BRepAdaptor_Curve,
        BRepAdaptor_Surface,
    )
    from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from simplecadapi._cpp.occt.BRepExtrema import BRepExtrema_DistShapeShape
    from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Circle, GeomAbs_Plane
    from simplecadapi._cpp.occt.gp import gp_Pnt

    plane = kind == "plane"
    fields(
        spec,
        "point normal tolerance_mm" if plane else "center axis radius_mm tolerance_mm",
        kind,
    )
    tol = positive(spec.get("tolerance_mm", 0.001), f"{kind}.tolerance_mm")
    point = vector(spec.get("point" if plane else "center"), 3, f"{kind} point")
    direction = np.array(
        vector(spec.get("normal" if plane else "axis"), 3, f"{kind} direction")
    )
    norm = np.linalg.norm(direction)
    if norm < 1e-9:
        raise ValueError(f"{kind}: select a nonzero direction")
    direction /= norm
    witness = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex() if plane else None
    radius = None if plane else positive(spec.get("radius_mm"), "circle.radius_mm")
    matches = []
    for entity in model.faces if plane else model.edges:
        adaptor = BRepAdaptor_Surface(entity) if plane else BRepAdaptor_Curve(entity)
        if adaptor.GetType() != (GeomAbs_Plane if plane else GeomAbs_Circle):
            continue
        geom = adaptor.Plane() if plane else adaptor.Circle()
        if abs(np.dot(direction, geom.Axis().Direction().Coord())) < 1 - 1e-8:
            continue
        if plane:
            distance = BRepExtrema_DistShapeShape(witness, entity)
            matched = distance.IsDone() and distance.Value() <= tol
        else:
            matched = (
                math.dist(geom.Location().Coord(), point) <= tol
                and abs(geom.Radius() - radius) <= tol
            )
        if matched:
            matches.append(entity)
    if len(matches) != 1:
        raise ValueError(
            f"{kind} selector at {point} resolved to {len(matches)} entities, expected one"
        )
    return ("face" if plane else "edge"), matches[0]


def dimension_declarations(rows, views, resolve):
    from simplecadapi.dxf_engine import DimDecl

    dims = []
    names = set()
    for row in rows:
        values = fields(
            row,
            "kind view semantic caption value of between axis extent tol fit count at datum side row out dec prefix covers name",
            "dimension",
        ).copy()
        caption = values.get("caption")
        if not isinstance(caption, str) or not caption.strip() or caption in names:
            raise ValueError("Every dimension needs a unique nonempty caption")
        names.add(caption)
        if values.get("view") not in views or values.get("kind") not in (
            "overall",
            "size",
            "position",
        ):
            raise ValueError(
                f"{caption}: specify a declared view and kind overall, size or position"
            )
        if values.get("value") is not None:
            (values["value"],) = vector([values["value"]], 1, f"{caption}.value")
        if values.get("tol") is not None:
            values["tol"] = vector(values["tol"], 2, f"{caption}.tol")
        if "of" in values:
            values["of"] = resolve(values["of"])[1]
        if "between" in values:
            refs = values["between"]
            if not isinstance(refs, list) or len(refs) != 2:
                raise ValueError(f"{caption}.between requires two model references")
            values["between"] = tuple(resolve(ref)[1] for ref in refs)
        dims.append(DimDecl(**values))
    return dims


def apply_drawing_action(plan, action):
    """Apply an SDK action, with a paper-space extension for outside diameter text."""
    if action.get("op") != "dia" or "extend_mm" not in action:
        (result,) = plan.apply([action])["results"]
        return result

    from simplecadapi.dxf_engine.agent import _place
    from simplecadapi.dxf_engine.dims import dia_geometry, dia_segs

    caption = action.get("name")
    dimension = next(
        (
            dim
            for dim in plan.dims
            if dim.caption == caption and dim.semantic == "diameter"
        ),
        None,
    )
    if dimension is None:
        raise ValueError(f"Unknown diameter dimension {caption!r}")
    extension = positive(action["extend_mm"], "dia.extend_mm")
    (angle,) = vector([action.get("at")], 1, "dia.at")
    resolved = next(
        item for item in plan.resolved if item.kind == "dim" and item.name == caption
    )
    geometry = dia_geometry(plan, dimension, angle, "outside", resolved.draw["text"])
    direction = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def extend(point):
        return tuple(x + extension * d for x, d in zip(point, direction))

    geometry["anchor"] = extend(geometry["anchor"])
    geometry["insert"] = extend(geometry["insert"])
    start, end = geometry["line"]
    geometry["line"] = start, extend(end)
    # Preserve circle contacts and measurement. The solver checks the new text and full line before committing.
    checked_action = dict(op="dia", name=caption, at=angle)
    _, result = _place(
        plan,
        checked_action,
        f"dim:{caption}",
        dimension,
        geometry,
        dia_segs(geometry),
        f"at={angle:g}° outside, extend={extension:g} mm",
    )
    return result


def annotation_declarations(spec, views, resolve):
    from simplecadapi.dxf_engine import CenterDecl, DatumDecl, LeaderDecl, RoughDecl
    from simplecadapi.dxf_engine.refs import project, view_frame

    def table(key, allowed):
        for row in spec.get(key, []):
            values = fields(row, allowed, key).copy()
            if values.get("view") not in views:
                raise ValueError(f"{key} requires a declared view")
            yield values

    def anchor(point, view, label):
        if isinstance(point, (list, tuple)) and len(point) == 3:
            frame = view_frame(views[view].n, views[view].xd)
            return project(vector(point, 3, label), frame)
        return vector(point, 2, label)

    datums, roughs, leaders, centers = [], [], [], []
    for row in table("datums", "letter kind view at box_off desc"):
        row["at"] = anchor(row.get("at"), row["view"], "datum.at")
        datums.append(DatumDecl(**row))
    for row in table("roughness", "view on text name"):
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError("roughness.text requires an explicit surface requirement")
        value = row.get("on")
        row["on"] = (
            resolve(value)[1]
            if isinstance(value, dict)
            else anchor(value, row["view"], "roughness.on")
        )
        roughs.append(RoughDecl(**row))
    for row in table("leaders", "view anchor lines off alt_offs dx_dir name"):
        lines = row.get("lines")
        if (
            not isinstance(lines, list)
            or not lines
            or not all(
                isinstance(line, str)
                and line.strip()
                and "\n" not in line
                and "\r" not in line
                for line in lines
            )
        ):
            raise ValueError(
                "leaders.lines requires one or more nonempty single-line strings"
            )
        row["anchor"] = anchor(row.get("anchor"), row["view"], "leader.anchor")
        if "off" in row:
            row["off"] = vector(row["off"], 2, "leader.off")
        if "alt_offs" in row:
            row["alt_offs"] = [
                vector(off, 2, "leader.alt_offs") for off in row["alt_offs"]
            ]
        row.setdefault("name", f"note-{len(leaders) + 1}")
        leaders.append(LeaderDecl(**row))
    for row in table("centerlines", "view p1 p2 arc"):
        if "arc" in row:
            row["arc"] = vector(row["arc"], 5, "centerline.arc")
            if row.keys() & {"p1", "p2"} or row["arc"][2] <= 0:
                raise ValueError(
                    "A centerline arc requires a positive radius and no p1/p2"
                )
        else:
            row["p1"] = anchor(row.get("p1"), row["view"], "centerline.p1")
            row["p2"] = anchor(row.get("p2"), row["view"], "centerline.p2")
            if math.dist(row["p1"], row["p2"]) < 1e-8:
                raise ValueError("Centerline endpoints must be distinct in the view")
        centers.append(CenterDecl(**row))
    controls = []
    if spec.get("control_frames"):
        from .control_frames import SYMBOLS

        names = set()
        known_datums = {datum.letter for datum in datums}
        for row in table(
            "control_frames",
            "name view anchor characteristic value datums diameter_zone offset",
        ):
            name, characteristic = row.get("name"), row.get("characteristic")
            if (
                not isinstance(name, str)
                or not name.strip()
                or name in names
                or characteristic not in SYMBOLS
            ):
                raise ValueError(
                    "Control frames require a unique name and supported characteristic"
                )
            names.add(name)
            ordered = row.get("datums", [])
            if not isinstance(ordered, list) or not all(
                isinstance(datum, str) and datum in known_datums for datum in ordered
            ):
                raise ValueError(f"{name}: use datum letters declared on this sheet")
            if len(ordered) > 3 or len(set(ordered)) != len(ordered):
                raise ValueError(f"{name}: use at most three distinct datum references")
            if characteristic == "flatness" and ordered:
                raise ValueError(f"{name}: flatness has no datum reference")
            if characteristic in ("parallelism", "perpendicularity") and not ordered:
                raise ValueError(f"{name}: specify a datum reference")
            diameter_zone = row.get("diameter_zone", False)
            if not isinstance(diameter_zone, bool) or (
                diameter_zone and characteristic != "position"
            ):
                raise ValueError(
                    f"{name}: diameter_zone is available on a position frame"
                )
            offset = vector(row.get("offset", [22, 16]), 2, "control frame offset")
            if abs(offset[0]) < 1e-8 or abs(offset[1]) < 2.5:
                raise ValueError(
                    f"{name}: use a nonzero horizontal offset and at least 2.5 mm vertically for the arrow"
                )
            controls.append(
                row
                | dict(
                    value=positive(row.get("value"), "control frame value"),
                    anchor=anchor(
                        row.get("anchor"), row["view"], "control frame anchor"
                    ),
                    datums=ordered,
                    diameter_zone=diameter_zone,
                    offset=offset,
                )
            )
    return dict(
        datums=datums, roughs=roughs, leaders=leaders, centers=centers
    ), controls


def build_plan(shape, spec, title, *, projector=None):
    from simplecadapi.dxf_engine import SheetDecl
    from simplecadapi.inspect.brep.io import measure_shape_mass_rtuple
    from .control_frames import place_control_frames
    from .projection import DrawingProjection, MESH_DEFLECTION_MM, physical_shape
    from .sheet import ExtendedSheetPlan, auxiliary_frame, removed_section

    fields(
        spec,
        "sheet views dimensions datums details actions roughness leaders centerlines control_frames hlr design_intent",
        "drawing",
    )
    hlr = spec.get("hlr", "exact")
    if hlr not in ("exact", "polygonal"):
        raise ValueError("drawing.hlr must be exact or polygonal")
    if projector is None:
        projector = DrawingProjection(physical_shape(shape), hlr, MESH_DEFLECTION_MM)
    view_rows = spec.get("views")
    if not isinstance(view_rows, list) or not view_rows:
        raise ValueError("drawing.views must be a nonempty list")
    sheet = fields(
        spec.get("sheet", {}),
        "title dwg_no scale front anchor sheet notes params material designer revision auto_centers general_rough projection",
        "sheet",
    )
    defaults = dict(title=title, dwg_no=title, scale=None, anchor=None)
    options = defaults | sheet
    projection = options.pop("projection", None)
    if projection not in (None, "first", "third"):
        raise ValueError("sheet.projection must be first or third")
    if options["scale"] is not None:
        positive(options["scale"], "sheet.scale")
    if options["anchor"] is not None:
        options["anchor"] = vector(options["anchor"], 2, "sheet.anchor")
    standard_frames = frames()
    views, by_name, auxiliary, removed = [], {}, {}, {}
    resolve = reference_resolver(shape)
    volume = None
    for row in view_rows:
        fields(row, "name frame normal right align section auxiliary", "view")
        if "auxiliary" in row:
            aux = fields(row["auxiliary"], "mark_in label face reverse", "auxiliary")
            label, parent = aux.get("label"), aux.get("mark_in")
            if (
                "section" in row
                or parent not in by_name
                or not isinstance(label, str)
                or not re.fullmatch(r"[A-Z][A-Z0-9]{0,5}", label)
            ):
                raise ValueError(
                    "Auxiliary views require a unique label and an earlier mark_in view"
                )
            if "face" in aux:
                if row.keys() & {"frame", "normal", "right"}:
                    raise ValueError(
                        "Use a planar face reference or an explicit auxiliary direction"
                    )
                if not isinstance(aux.get("reverse", False), bool):
                    raise ValueError("auxiliary.reverse must be a boolean")
                n, r = auxiliary_frame(
                    resolve(aux["face"]),
                    by_name[parent],
                    reverse=aux.get("reverse", False),
                )
                row = row | dict(normal=n, right=r)
            elif "reverse" in aux:
                raise ValueError(
                    "auxiliary.reverse applies to a face-derived direction"
                )
        view = view_definition(row, projector.shape, standard_frames)
        if "auxiliary" in row:
            if abs(np.dot(by_name[parent].n, view.n)) > 1e-8:
                raise ValueError(
                    f"{view.name}: auxiliary mark_in must see the target direction edge-on"
                )
            auxiliary[view.name] = parent, label
        if "section" in row and row["section"].get("kind") == "removed":
            if volume is None:
                volume, _ = measure_shape_mass_rtuple(projector.shape, kind="volume")
            point = view.section
            view, loops, bounds = removed_section(view, volume)
            removed[view.name] = point, loops, bounds
        views.append(view)
        by_name[view.name] = view
    front = options.setdefault("front", views[0].name)
    if len(views) != len(by_name) or front not in by_name or by_name[front].align:
        raise ValueError(
            "Views need unique names and a declared front view without align"
        )
    positioned = {front}
    for view in views:
        if view.name != front and view.align.get("to") not in positioned:
            raise ValueError(
                f"{view.name}.align must name the front or an earlier view"
            )
        positioned.add(view.name)
        if view.section is not None or view.name in removed:
            parent = by_name.get(view.mark_in)
            if parent is None or abs(np.dot(parent.n, view.n)) > 1e-8:
                raise ValueError(
                    f"{view.name}.section.mark_in must name a view perpendicular to the section view"
                )
    labels = [v.label.upper() for v in views if v.label] + [
        label for _, label in auxiliary.values()
    ]
    if len(labels) != len(set(labels)):
        raise ValueError("Section and auxiliary labels must be unique")
    for key in (
        "dimensions",
        "datums",
        "details",
        "actions",
        "roughness",
        "leaders",
        "centerlines",
        "control_frames",
    ):
        if not isinstance(spec.get(key, []), list):
            raise ValueError(f"drawing.{key} must be a list")
    annotations, controls = annotation_declarations(spec, by_name, resolve)
    dims = dimension_declarations(spec.get("dimensions", []), by_name, resolve)
    plan = ExtendedSheetPlan(
        SheetDecl(**options, views=views, dims=dims, **annotations),
        removed,
        auxiliary,
        projection,
        projector,
    ).solve()
    plan.design_intent, plan.intent_issues = validate_intent(
        plan, spec.get("design_intent")
    )
    if actions := spec.get("actions"):
        if not all(isinstance(action, dict) for action in actions):
            raise ValueError("drawing.actions must contain SDK action objects")
        for action in actions:
            result = apply_drawing_action(plan, action)
            if not result["ok"]:
                reason = result.get("error", result.get("violations", []))
                raise ValueError(
                    f"Drawing action rejected for {action.get('name', 'unknown element')}: {reason}"
                )
    plan.control_frames = place_control_frames(plan, controls)
    return plan


def check_issues(plan):
    issues = [issue.as_dict() for issue in plan.issues()]
    errors = [
        f"{i['code']}: {i['message']}" for i in issues if i["severity"] == "error"
    ]
    if errors:
        raise ValueError("Engineering drawing failed validation: " + " | ".join(errors))
    return issues


def detail_declarations(rows, plan):
    labels = {view.label.upper() for view in plan.by_name.values() if view.label}
    labels.update(label for _, label in plan.auxiliary.values())
    for row in rows:
        fields(row, "label parent center size_mm position_mm scale hidden", "detail")
        label, parent = row.get("label"), row.get("parent")
        if (
            not isinstance(label, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9]{0,5}", label)
            or label in labels
        ):
            raise ValueError(
                "Detail labels must be unique uppercase letters or letter-number labels, separate from section labels"
            )
        labels.add(label)
        if (
            parent not in plan.views
            or plan.by_name[parent].section is not None
            or parent in plan.removed
        ):
            raise ValueError(f"Detail {label} needs an ordinary parent view")
        center = vector(row.get("center"), 3, f"detail {label}.center")
        size = vector(row.get("size_mm"), 2, f"detail {label}.size_mm")
        if min(size) <= 0:
            raise ValueError(f"Detail {label}: both crop dimensions must be positive")
        at = vector(row.get("position_mm"), 2, f"detail {label}.position_mm")
        scale = positive(row.get("scale"), f"detail {label}.scale")
        if scale <= plan.s:
            raise ValueError(
                f"Detail {label}: scale must be larger than the parent scale {plan.s:g}"
            )
        hidden = row.get("hidden", False)
        if not isinstance(hidden, bool):
            raise ValueError(f"Detail {label}: hidden must be a boolean")
        yield dict(
            label=label,
            parent=parent,
            center=center,
            size=size,
            at=at,
            scale=scale,
            hidden=hidden,
        )


def load_engineering_shape(step, transform=None):
    shape = brep.load_step_rshape(
        path=step, require_single_root=False, require_valid=True
    )
    return shape if transform is None else rigid_shape(shape, transform)


def export_engineering_sheet(step, output, spec, *, transform=None, pdf=False):
    """Export an engineering DXF, its reopened preview and a reproducible declaration audit."""
    step = Path(step).resolve()
    shape = load_engineering_shape(step, transform)
    plan = build_plan(shape, spec, step.stem)
    return write_engineering_sheet(
        step, output, spec, plan, transform=transform, pdf=pdf
    )


def write_engineering_sheet(step, output, spec, plan, *, transform=None, pdf=False):
    from simplecadapi.dxf_engine.render import verify_dxf
    from .control_frames import draw_control_frames
    from ..render import build_dxf
    from .sheet import decorate_views

    step, output = Path(step).resolve(), Path(output).resolve()
    if output.suffix.lower() != ".dxf":
        raise ValueError("Engineering output must have a .dxf extension")
    check_issues(plan)
    declared_details = list(detail_declarations(spec.get("details", []), plan))

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp) / output.name
        doc, handles = build_dxf(plan)
        use_diameter_font(doc)
        decorate_views(doc, plan)
        draw_control_frames(doc, plan.control_frames)
        details = place_details(doc, plan, declared_details) if declared_details else []
        doc.saveas(staged)
        plan.render_issues = verify_dxf(plan, staged, handles)
        issues = check_issues(plan)
        doc = ezdxf.readfile(staged)
        audit = doc.audit()
        if audit.has_errors:
            raise ValueError(f"Engineering DXF audit errors: {len(audit.errors)}")
        preview = render_print_page(doc, staged, plan.fmt, pdf=pdf)
        counts = Counter(entity.dxftype() for entity in doc.modelspace())
        metadata = dict(
            mode="engineering",
            sdk_version=version("simplecadapi"),
            source_step=str(step),
            source_sha256=hashlib.sha256(step.read_bytes()).hexdigest(),
            output_dxf=str(output),
            transform=transform,
            declaration=spec,
            sheet=plan.fmt.name,
            scale=plan.s,
            units="mm",
            sheet_size_mm=[plan.fmt.w, plan.fmt.h],
            views=list(plan.views),
            issues=issues,
            details=details,
            projection=plan.draft_projection or "first",
            preview=preview,
            hlr=plan.projector.mode,
            projection_bounds=plan.projection_bounds(),
            control_frames=plan.control_frames,
            dimensions=[
                dict(caption=d.caption, view=d.view, value_mm=d._measured)
                for d in plan.dims
            ],
            reopen_audit=dict(
                entity_count=sum(counts.values()),
                entity_types=dict(counts),
                audit_errors=0,
            ),
        )
        if pdf:
            metadata["output_pdf"] = str(output.with_suffix(".pdf"))
        if plan.design_intent is not None:
            metadata["design_intent"] = plan.design_intent
        staged.with_suffix(".json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        staged.with_suffix(".txt").write_text(plan.report(), encoding="utf-8")
        staged.replace(output)
        suffixes = (
            (".pdf", ".png", ".txt", ".json") if pdf else (".png", ".txt", ".json")
        )
        for suffix in suffixes:
            staged.with_suffix(suffix).replace(output.with_suffix(suffix))
    return metadata
