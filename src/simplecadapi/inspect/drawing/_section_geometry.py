"""Continuous section geometry; no sampling residual is an error bound."""

from __future__ import annotations

import math

import numpy as np
from simplecadapi._cpp.occt.BRep import BRep_Builder, BRep_Tool
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Common
from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_Transform
from simplecadapi._cpp.occt.BRepExtrema import BRepExtrema_DistShapeShape
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.Bnd import Bnd_Box
from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Circle
from simplecadapi._cpp.occt.TopAbs import TopAbs_EDGE, TopAbs_SOLID
from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Compound
from simplecadapi._cpp.occt.TopTools import TopTools_ListOfShape
from simplecadapi._cpp.occt.gp import gp_Pnt, gp_Trsf

from ..brep.queries import (
    _inspect_section_geometry,
    _model,
    _section_source,
    _linear_length,
    _point,
    _plane_basis,
)
from ._material_geometry import material_section_geometry
from ._section_validation import validate_section, shapes


def section_geometry(
    model,
    plane,
    tolerance=1e-7,
    samples_per_edge=64,
    *,
    section_strategy="auto",
    section_checks=None,
):
    if not isinstance(samples_per_edge, int) or samples_per_edge < 4:
        raise ValueError("samples_per_edge must be an integer of at least four")
    if section_strategy not in ("auto", "material", "edges"):
        raise ValueError("section_strategy must be auto, material or edges")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    origin, normal = _point(plane["origin"], "origin"), _point(
        plane["normal"], "normal"
    )
    origin, x_axis, y_axis = _plane_basis(origin, normal)
    section = {
        "plane": {
            "origin": origin.tolist(),
            "normal": (normal / np.linalg.norm(normal)).tolist(),
            "x_direction": x_axis.tolist(),
            "y_direction": y_axis.tolist(),
        },
        "tolerance": tolerance,
    }
    for key in ("x_direction", "y_direction"):
        if key in plane and (
            np.shape(plane[key]) != (3,)
            or not np.allclose(plane[key], section["plane"][key], atol=1e-12, rtol=0)
        ):
            raise ValueError(f"plane {key} differs from the canonical section basis")
    indexed = _model(model)
    if not BRepCheck_Analyzer(indexed.root).IsValid():
        raise ValueError(
            "source geometry is invalid; section intersection was not attempted"
        )
    source, _ = _section_source(indexed, None)
    has_solids = bool(shapes(source, TopAbs_SOLID))
    if section_strategy == "material" and not has_solids:
        raise ValueError("material section strategy requires a solid source")
    material, faces, holes = None, [], []
    if section_strategy == "material" or (section_strategy == "auto" and has_solids):
        section, edges, faces, holes = material_section_geometry(
            source, section, samples_per_edge, tolerance
        )
        material = section
    else:
        section, edges = _inspect_section_geometry(
            model, origin, normal, tolerance, samples_per_edge
        )
        section["contour_method"] = "section_edges"
        if section_checks is not None and has_solids:
            material, _, faces, holes = material_section_geometry(
                source, section, samples_per_edge, tolerance
            )
    section["section_strategy"] = section_strategy
    section["validation"] = validate_section(
        indexed.root, section, material, faces, holes, section_checks
    )
    return section, edges


def compound(edges):
    builder = BRep_Builder()
    shape = TopoDS_Compound()
    builder.MakeCompound(shape)
    for edge in edges:
        builder.Add(shape, edge)
    return shape


def edge_diagnostics(edges):
    return {
        "geometry_types": sorted(
            {str(BRepAdaptor_Curve(e).GetType()).split(".")[-1] for e in edges}
        ),
        "kernel_edge_tolerance_mm_max": max(
            (BRep_Tool.Tolerance_s(e) for e in edges), default=None
        ),
    }


def local_point(point, plane):
    delta = np.asarray(point) - plane["origin"]
    return [
        float(np.dot(delta, plane[axis])) for axis in ("x_direction", "y_direction")
    ]


def continuous_bounds(shape, plane):
    axes = np.asarray([plane["x_direction"], plane["y_direction"], plane["normal"]])
    offset = -axes @ plane["origin"]
    transform = gp_Trsf()
    transform.SetValues(*np.column_stack((axes, offset)).ravel().tolist())
    local = BRepBuilderAPI_Transform(shape, transform, True).Shape()
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(local, box, False, False)
    return list(box.Get())


def analytic_circle(edges, plane):
    curves = [BRepAdaptor_Curve(edge) for edge in edges]
    if not curves or any(curve.GetType() != GeomAbs_Circle for curve in curves):
        return None
    circles = [curve.Circle() for curve in curves]
    first = circles[0]
    # Reject near-coincident circles rather than silently fitting them together.
    if any(
        abs(c.Radius() - first.Radius()) > 1e-10
        or c.Location().Distance(first.Location()) > 1e-10
        for c in circles
    ):
        return None
    angle = sum(abs(c.LastParameter() - c.FirstParameter()) for c in curves)
    if not math.isclose(angle, 2 * math.pi, abs_tol=1e-8):
        return None
    return {
        "center": local_point(first.Location().Coord(), plane),
        "value": 2 * first.Radius(),
        "radius_deviation": 0.0,
        "method": "analytic_circle",
        "accuracy_class": "analytic_geometry",
    }


def continuous_gap(first, second, plane):
    distance = BRepExtrema_DistShapeShape(first, second)
    distance.Perform()
    if not distance.IsDone() or not distance.NbSolution():
        raise ValueError("continuous contour distance failed")
    return {
        "value": distance.Value(),
        "method": "brep_extrema_distance",
        "accuracy_class": "continuous_numeric",
        "anchors": [
            local_point(distance.PointOnShape1(1).Coord(), plane),
            local_point(distance.PointOnShape2(1).Coord(), plane),
        ],
    }


def directional_material(model, plane, request):
    """All connected material intervals on an explicitly located section line."""
    point = np.asarray(request["point"], dtype=float)
    direction = np.asarray(request["direction"], dtype=float)
    if (
        point.shape != (2,)
        or direction.shape != (2,)
        or not np.isfinite(point).all()
        or not np.isfinite(direction).all()
        or np.linalg.norm(direction) == 0
    ):
        raise ValueError(
            "directional thickness requires finite 2D point and nonzero direction"
        )
    direction /= np.linalg.norm(direction)
    source, _ = _section_source(_model(model), None)
    bounds = continuous_bounds(source, plane)
    corners = np.asarray(
        [[x, y] for x in (bounds[0], bounds[3]) for y in (bounds[1], bounds[4])]
    )
    half_length = max(np.linalg.norm(c - point) for c in corners) + 1.0
    axes = np.asarray([plane["x_direction"], plane["y_direction"]])

    def world(t):
        return np.asarray(plane["origin"]) + (point + t * direction) @ axes

    line = BRepBuilderAPI_MakeEdge(
        gp_Pnt(*world(-half_length)), gp_Pnt(*world(half_length))
    ).Edge()
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(source)
    tools.Append(line)
    operation = BRepAlgoAPI_Common()
    operation.SetArguments(arguments)
    operation.SetTools(tools)
    operation.SetNonDestructive(True)
    operation.Build()
    if not operation.IsDone():
        raise ValueError("directional material intersection failed")
    intervals = []
    explorer = TopExp_Explorer(operation.Shape(), TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge_s(explorer.Current())
        curve = BRepAdaptor_Curve(edge)
        anchors = [
            local_point(curve.Value(t).Coord(), plane)
            for t in (curve.FirstParameter(), curve.LastParameter())
        ]
        span = sorted(float(np.dot(np.asarray(p) - point, direction)) for p in anchors)
        intervals.append(
            {"value": _linear_length(edge), "span": span, "anchors": anchors}
        )
        explorer.Next()
    return [
        {
            **interval,
            "kind": "thickness_directional",
            "definition": "material_length_on_line",
            "method": "brep_line_material_common",
            "accuracy_class": "continuous_numeric",
            "point": point.tolist(),
            "direction": direction.tolist(),
            "interval": index,
            "request_id": request["id"],
        }
        for index, interval in enumerate(sorted(intervals, key=lambda v: v["span"]))
    ]
