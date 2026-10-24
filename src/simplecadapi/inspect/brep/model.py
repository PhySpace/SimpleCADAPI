"""Stable STEP entity indexing and agent-oriented BREP inspection."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Any, Literal, Sequence

from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Fuse
from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.Bnd import Bnd_Box
from simplecadapi._cpp.occt.TopAbs import (
    TopAbs_COMPOUND,
    TopAbs_COMPSOLID,
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_SHELL,
    TopAbs_SHAPE,
    TopAbs_SOLID,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from simplecadapi._cpp.occt.TopExp import TopExp, TopExp_Explorer
from simplecadapi._cpp.occt.TopTools import TopTools_IndexedMapOfShape, TopTools_ListOfShape
from simplecadapi._cpp.occt.TopoDS import (
    TopoDS,
    TopoDS_Edge,
    TopoDS_Face,
    TopoDS_Shape,
    TopoDS_Solid,
    TopoDS_Vertex,
)
from simplecadapi._cpp.occt.gp import gp_Pnt, gp_Vec

from ...errors import SimpleCADMessageError
from ...kernel.ocp_properties import face_normal_at
from ...kernel.ocp_topology import inner_wires_of, outer_wire_of, vertex_point
from .io import load_step_rshape, measure_shape_mass_rtuple, xyz


EntityKind = Literal["body", "face", "edge", "vertex"]
ENTITY_KINDS: tuple[EntityKind, ...] = ("body", "face", "edge", "vertex")

_ENTITY_PATTERN = re.compile(
    r"^\s*(body|solid|b|face|f|edge|e|vertex|v)\s*" r"(?::|#|_|\[)?\s*(\d+)\s*\]?\s*$",
    re.IGNORECASE,
)
_KIND_ALIASES: dict[str, EntityKind] = {
    "body": "body",
    "solid": "body",
    "b": "body",
    "face": "face",
    "f": "face",
    "edge": "edge",
    "e": "edge",
    "vertex": "vertex",
    "v": "vertex",
}
_SURFACE_TYPE_NAMES = {
    "Plane": "PLANE",
    "Cylinder": "CYLINDER",
    "Cone": "CONE",
    "Sphere": "SPHERE",
    "Torus": "TORUS",
    "BezierSurface": "BEZIER",
    "BSplineSurface": "BSPLINE",
    "SurfaceOfRevolution": "REVOLUTION",
    "SurfaceOfExtrusion": "EXTRUSION",
    "OffsetSurface": "OFFSET",
    "OtherSurface": "OTHER",
}
_CURVE_TYPE_NAMES = {
    "Line": "LINE",
    "Circle": "CIRCLE",
    "Ellipse": "ELLIPSE",
    "Hyperbola": "HYPERBOLA",
    "Parabola": "PARABOLA",
    "BezierCurve": "BEZIER",
    "BSplineCurve": "BSPLINE",
    "OffsetCurve": "OFFSET",
    "OtherCurve": "OTHER",
}
_ROOT_TYPE_NAMES = {
    TopAbs_SHAPE: "Shape",
    TopAbs_VERTEX: "Vertex",
    TopAbs_EDGE: "Edge",
    TopAbs_WIRE: "Wire",
    TopAbs_FACE: "Face",
    TopAbs_SHELL: "Shell",
    TopAbs_SOLID: "Solid",
    TopAbs_COMPSOLID: "CompSolid",
    TopAbs_COMPOUND: "Compound",
}


class BRepEntityError(SimpleCADMessageError):
    """Raised when a STEP model or stable entity query cannot be processed."""

    operation = "brep_entity"


def _enum_suffix(value: Any, prefix: str) -> str:
    return str(value).split(".")[-1].removeprefix(prefix)


def _canonical_entity_id(kind: EntityKind, index: int) -> str:
    return f"{kind}:{index}"


def _parse_entity_id(entity_id: str) -> tuple[EntityKind, int]:
    match = _ENTITY_PATTERN.match(entity_id)
    if not match:
        raise BRepEntityError(
            "Entity id must look like body:0, face:12, edge:4, or vertex:8"
        )
    return _KIND_ALIASES[match.group(1).lower()], int(match.group(2))


def _entity_sort_key(entity_id: str) -> tuple[int, int]:
    kind, index = _parse_entity_id(entity_id)
    return ENTITY_KINDS.index(kind), index


def _indexed_map(shape: TopoDS_Shape, kind: Any) -> TopTools_IndexedMapOfShape:
    result = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, result)
    return result


def _mapped_solids(indexed: TopTools_IndexedMapOfShape) -> tuple[TopoDS_Solid, ...]:
    return tuple(
        TopoDS.Solid_s(indexed.FindKey(index))
        for index in range(1, indexed.Extent() + 1)
    )


def _mapped_faces(indexed: TopTools_IndexedMapOfShape) -> tuple[TopoDS_Face, ...]:
    return tuple(
        TopoDS.Face_s(indexed.FindKey(index))
        for index in range(1, indexed.Extent() + 1)
    )


def _mapped_edges(indexed: TopTools_IndexedMapOfShape) -> tuple[TopoDS_Edge, ...]:
    return tuple(
        TopoDS.Edge_s(indexed.FindKey(index))
        for index in range(1, indexed.Extent() + 1)
    )


def _mapped_vertices(
    indexed: TopTools_IndexedMapOfShape,
) -> tuple[TopoDS_Vertex, ...]:
    return tuple(
        TopoDS.Vertex_s(indexed.FindKey(index))
        for index in range(1, indexed.Extent() + 1)
    )


def _subshape_count(shape: TopoDS_Shape, kind: Any) -> int:
    return _indexed_map(shape, kind).Extent()


def _bounding_box(shape: TopoDS_Shape) -> dict[str, Any]:
    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape, box)
    if box.IsVoid():
        raise BRepEntityError("OpenCascade produced a void bounding box")
    xmin, ymin, zmin, xmax, ymax, zmax = (float(value) for value in box.Get())
    minimum = [xmin, ymin, zmin]
    maximum = [xmax, ymax, zmax]
    size = [maximum[index] - minimum[index] for index in range(3)]
    return {
        "min": minimum,
        "max": maximum,
        "size": size,
        "diagonal": math.sqrt(sum(component * component for component in size)),
        "center": [(minimum[index] + maximum[index]) * 0.5 for index in range(3)],
    }


def _root_shape_type(shape: TopoDS_Shape) -> str:
    return _ROOT_TYPE_NAMES.get(shape.ShapeType(), str(shape.ShapeType()))


def _surface_type(adaptor: BRepAdaptor_Surface) -> str:
    raw = _enum_suffix(adaptor.GetType(), "GeomAbs_")
    return _SURFACE_TYPE_NAMES.get(raw, raw.upper())


def _curve_type(edge: TopoDS_Edge) -> str:
    if BRep_Tool.Degenerated_s(edge):
        return "DEGENERATE"
    adaptor = BRepAdaptor_Curve(edge)
    raw = _enum_suffix(adaptor.GetType(), "GeomAbs_")
    return _CURVE_TYPE_NAMES.get(raw, raw.upper())


def _underlying_curve_type(edge: TopoDS_Edge) -> str | None:
    try:
        adaptor = BRepAdaptor_Curve(edge)
    except Exception:
        return None
    raw = _enum_suffix(adaptor.GetType(), "GeomAbs_")
    return _CURVE_TYPE_NAMES.get(raw, raw.upper())


def _rounded_parameter(value: float, digits: int = 6) -> float:
    rounded = round(float(value), digits)
    return 0.0 if rounded == 0.0 else rounded


def _surface_group_parameters(face: TopoDS_Face) -> tuple[str, dict[str, Any]]:
    adaptor = BRepAdaptor_Surface(face, True)
    geometry_type = _surface_type(adaptor)
    parameters: dict[str, Any] = {}
    try:
        if geometry_type == "CYLINDER":
            parameters["radius"] = _rounded_parameter(adaptor.Cylinder().Radius())
        elif geometry_type == "CONE":
            cone = adaptor.Cone()
            parameters.update(
                reference_radius=_rounded_parameter(cone.RefRadius()),
                semi_angle_degrees=_rounded_parameter(
                    math.degrees(float(cone.SemiAngle()))
                ),
            )
        elif geometry_type == "SPHERE":
            parameters["radius"] = _rounded_parameter(adaptor.Sphere().Radius())
        elif geometry_type == "TORUS":
            torus = adaptor.Torus()
            parameters.update(
                major_radius=_rounded_parameter(torus.MajorRadius()),
                minor_radius=_rounded_parameter(torus.MinorRadius()),
            )
        elif geometry_type in {"BEZIER", "BSPLINE"}:
            parameters.update(
                u_degree=int(adaptor.UDegree()),
                v_degree=int(adaptor.VDegree()),
                u_pole_count=int(adaptor.NbUPoles()),
                v_pole_count=int(adaptor.NbVPoles()),
            )
            if geometry_type == "BSPLINE":
                parameters.update(
                    u_knot_count=int(adaptor.NbUKnots()),
                    v_knot_count=int(adaptor.NbVKnots()),
                )
        elif geometry_type == "OFFSET":
            parameters["offset"] = _rounded_parameter(adaptor.OffsetValue())
    except Exception:
        # The carrier type is still useful when an uncommon adaptor cannot
        # expose all optional parameters.
        parameters = {}
    return geometry_type, parameters


def _curve_group_parameters(edge: TopoDS_Edge) -> tuple[str, dict[str, Any]]:
    geometry_type = _curve_type(edge)
    if geometry_type == "DEGENERATE":
        return geometry_type, {
            "underlying_curve_type": _underlying_curve_type(edge) or "UNKNOWN"
        }
    adaptor = BRepAdaptor_Curve(edge)
    parameters: dict[str, Any] = {}
    try:
        if geometry_type == "CIRCLE":
            parameters["radius"] = _rounded_parameter(adaptor.Circle().Radius())
        elif geometry_type == "ELLIPSE":
            ellipse = adaptor.Ellipse()
            parameters.update(
                major_radius=_rounded_parameter(ellipse.MajorRadius()),
                minor_radius=_rounded_parameter(ellipse.MinorRadius()),
            )
        elif geometry_type in {"BEZIER", "BSPLINE"}:
            parameters.update(
                degree=int(adaptor.Degree()),
                pole_count=int(adaptor.NbPoles()),
            )
            if geometry_type == "BSPLINE":
                parameters["knot_count"] = int(adaptor.NbKnots())
    except Exception:
        parameters = {}
    return geometry_type, parameters


def _parameter_group_key(
    geometry_type: str, parameters: dict[str, Any]
) -> tuple[str, tuple[tuple[str, Any], ...]]:
    return geometry_type, tuple(sorted(parameters.items()))


def _bounded_parameter_groups(
    groups: dict[tuple[str, tuple[tuple[str, Any], ...]], list[str]],
    *,
    max_groups: int,
    examples_per_group: int,
) -> dict[str, Any]:
    ordered = sorted(
        groups.items(),
        key=lambda item: (-len(item[1]), item[0][0], item[0][1]),
    )
    return {
        "groups": [
            {
                "geometry_type": key[0],
                "parameters": dict(key[1]),
                "count": len(entity_ids),
                "example_entity_ids": entity_ids[:examples_per_group],
            }
            for key, entity_ids in ordered[:max_groups]
        ],
        "group_count": len(ordered),
        "omitted_group_count": max(len(ordered) - max_groups, 0),
    }


def _canonical_direction(values: Sequence[float]) -> tuple[float, float, float]:
    return tuple(
        _rounded_parameter(value) for value in _canonical_direction_values(values)
    )


def _canonical_direction_values(values: Sequence[float]) -> list[float]:
    magnitude = math.sqrt(sum(float(value) ** 2 for value in values))
    if magnitude <= 1.0e-15:
        raise ValueError("Axis direction must be non-zero")
    direction = [float(value) / magnitude for value in values]
    first_significant = next(
        (
            rounded
            for value in direction
            if (rounded := _rounded_parameter(value)) != 0.0
        ),
        1.0,
    )
    if first_significant < 0.0:
        direction = [-value for value in direction]
    return direction


def _canonical_axis(
    point: Sequence[float],
    direction: Sequence[float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    direction_values = _canonical_direction_values(direction)
    projection = sum(
        float(point[index]) * direction_values[index] for index in range(3)
    )
    closest = tuple(
        _rounded_parameter(float(point[index]) - projection * direction_values[index])
        for index in range(3)
    )
    return closest, tuple(_rounded_parameter(value) for value in direction_values)


def _entity_geometry_type(kind: EntityKind, shape: TopoDS_Shape) -> str:
    if kind == "body":
        return "SOLID"
    if kind == "face":
        return _surface_type(BRepAdaptor_Surface(TopoDS.Face_s(shape), True))
    if kind == "edge":
        return _curve_type(TopoDS.Edge_s(shape))
    return "POINT"


def _axis_group_descriptor(
    kind: EntityKind,
    shape: TopoDS_Shape,
) -> tuple[str, tuple[float, float, float] | None, tuple[float, float, float]] | None:
    if kind == "face":
        adaptor = BRepAdaptor_Surface(TopoDS.Face_s(shape), True)
        geometry_type = _surface_type(adaptor)
        if geometry_type == "PLANE":
            return (
                "normal_direction",
                None,
                _canonical_direction(xyz(adaptor.Plane().Axis().Direction())),
            )
        if geometry_type == "CYLINDER":
            axis = adaptor.Cylinder().Axis()
        elif geometry_type == "CONE":
            axis = adaptor.Cone().Axis()
        elif geometry_type == "TORUS":
            axis = adaptor.Torus().Axis()
        elif geometry_type == "REVOLUTION":
            axis = adaptor.AxeOfRevolution()
        elif geometry_type == "EXTRUSION":
            return (
                "extrusion_direction",
                None,
                _canonical_direction(xyz(adaptor.Direction())),
            )
        else:
            return None
        point, direction = _canonical_axis(
            xyz(axis.Location()),
            xyz(axis.Direction()),
        )
        return "axis_line", point, direction

    if kind == "edge":
        edge = TopoDS.Edge_s(shape)
        geometry_type = _curve_type(edge)
        if geometry_type == "DEGENERATE":
            return None
        adaptor = BRepAdaptor_Curve(edge)
        if geometry_type == "LINE":
            carrier = adaptor.Line()
            point, direction = _canonical_axis(
                xyz(carrier.Location()),
                xyz(carrier.Direction()),
            )
        elif geometry_type == "CIRCLE":
            carrier = adaptor.Circle()
            point, direction = _canonical_axis(
                xyz(carrier.Location()),
                xyz(carrier.Axis().Direction()),
            )
        elif geometry_type == "ELLIPSE":
            carrier = adaptor.Ellipse()
            point, direction = _canonical_axis(
                xyz(carrier.Location()),
                xyz(carrier.Axis().Direction()),
            )
        else:
            return None
        return "axis_line", point, direction
    return None


def _bounded_axis_groups(
    groups: dict[
        tuple[str, tuple[float, float, float] | None, tuple[float, float, float]],
        list[tuple[str, str]],
    ],
    *,
    max_groups: int,
    examples_per_group: int,
) -> dict[str, Any]:
    ordered = sorted(
        groups.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    result = []
    for (role, point, direction), entries in ordered[:max_groups]:
        result.append(
            {
                "axis": {
                    "role": role,
                    "point": list(point) if point is not None else None,
                    "direction": list(direction),
                },
                "count": len(entries),
                "geometry_type_counts": dict(
                    sorted(Counter(geometry for _, geometry in entries).items())
                ),
                "example_entity_ids": [
                    entity_id for entity_id, _ in entries[:examples_per_group]
                ],
            }
        )
    return {
        "groups": result,
        "group_count": len(ordered),
        "omitted_group_count": max(len(ordered) - max_groups, 0),
    }


def _bounded_adjacency_groups(
    groups: dict[tuple[Any, ...], list[str]],
    *,
    max_groups: int,
    examples_per_group: int,
) -> dict[str, Any]:
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    result = []
    for key, entity_ids in ordered[:max_groups]:
        geometry_type, neighbor_counts, neighbor_geometry = key
        result.append(
            {
                "geometry_type": geometry_type,
                "signature": {
                    "direct_neighbor_counts": dict(neighbor_counts),
                    "neighbor_geometry_types": dict(neighbor_geometry),
                },
                "count": len(entity_ids),
                "example_entity_ids": entity_ids[:examples_per_group],
            }
        )
    return {
        "groups": result,
        "group_count": len(ordered),
        "omitted_group_count": max(len(ordered) - max_groups, 0),
    }


def _axis_parameters(axis: Any) -> dict[str, list[float]]:
    return {
        "point": xyz(axis.Location()),
        "direction": xyz(axis.Direction()),
    }


def _surface_parameters(
    face: TopoDS_Face,
    *,
    include_definition: bool = False,
    max_control_points: int = 256,
) -> dict[str, Any]:
    adaptor = BRepAdaptor_Surface(face, True)
    geometry_type = _surface_type(adaptor)
    parameters: dict[str, Any] = {
        "u_range": [
            float(adaptor.FirstUParameter()),
            float(adaptor.LastUParameter()),
        ],
        "v_range": [
            float(adaptor.FirstVParameter()),
            float(adaptor.LastVParameter()),
        ],
        "u_periodic": bool(adaptor.IsUPeriodic()),
        "v_periodic": bool(adaptor.IsVPeriodic()),
    }

    if geometry_type == "PLANE":
        plane = adaptor.Plane()
        parameters.update(
            {
                "origin": xyz(plane.Location()),
                "normal": xyz(plane.Axis().Direction()),
                "x_direction": xyz(plane.Position().XDirection()),
                "y_direction": xyz(plane.Position().YDirection()),
            }
        )
    elif geometry_type == "CYLINDER":
        cylinder = adaptor.Cylinder()
        parameters.update(
            {
                "axis": _axis_parameters(cylinder.Axis()),
                "radius": float(cylinder.Radius()),
            }
        )
    elif geometry_type == "CONE":
        cone = adaptor.Cone()
        parameters.update(
            {
                "axis": _axis_parameters(cone.Axis()),
                "apex": xyz(cone.Apex()),
                "reference_radius": float(cone.RefRadius()),
                "semi_angle_degrees": math.degrees(float(cone.SemiAngle())),
            }
        )
    elif geometry_type == "SPHERE":
        sphere = adaptor.Sphere()
        parameters.update(
            {
                "center": xyz(sphere.Location()),
                "radius": float(sphere.Radius()),
                "axis_direction": xyz(sphere.Position().Direction()),
            }
        )
    elif geometry_type == "TORUS":
        torus = adaptor.Torus()
        parameters.update(
            {
                "axis": _axis_parameters(torus.Axis()),
                "major_radius": float(torus.MajorRadius()),
                "minor_radius": float(torus.MinorRadius()),
            }
        )
    elif geometry_type in {"BEZIER", "BSPLINE"}:
        u_pole_count = int(adaptor.NbUPoles())
        v_pole_count = int(adaptor.NbVPoles())
        parameters.update(
            {
                "u_degree": int(adaptor.UDegree()),
                "v_degree": int(adaptor.VDegree()),
                "u_pole_count": u_pole_count,
                "v_pole_count": v_pole_count,
            }
        )
        if geometry_type == "BSPLINE":
            parameters.update(
                {
                    "u_knot_count": int(adaptor.NbUKnots()),
                    "v_knot_count": int(adaptor.NbVKnots()),
                }
            )
        if include_definition:
            control_point_count = u_pole_count * v_pole_count
            if control_point_count > max_control_points:
                raise BRepEntityError(
                    "Surface definition contains "
                    f"{control_point_count} control points; maximum is "
                    f"{max_control_points}"
                )
            surface = (
                adaptor.BSpline() if geometry_type == "BSPLINE" else adaptor.Bezier()
            )
            u_rational = bool(surface.IsURational())
            v_rational = bool(surface.IsVRational())
            parameters.update(
                {
                    "surface_definition_scope": "untrimmed_carrier",
                    "rational": u_rational or v_rational,
                    "u_rational": u_rational,
                    "v_rational": v_rational,
                    "control_point_count": control_point_count,
                    "control_points": [
                        [
                            xyz(surface.Pole(u_index, v_index))
                            for v_index in range(1, v_pole_count + 1)
                        ]
                        for u_index in range(1, u_pole_count + 1)
                    ],
                    "weights": (
                        [
                            [
                                float(surface.Weight(u_index, v_index))
                                for v_index in range(1, v_pole_count + 1)
                            ]
                            for u_index in range(1, u_pole_count + 1)
                        ]
                        if u_rational or v_rational
                        else None
                    ),
                }
            )
            if geometry_type == "BSPLINE":
                parameters.update(
                    {
                        "u_knot_values": [
                            float(surface.UKnot(index))
                            for index in range(1, surface.NbUKnots() + 1)
                        ],
                        "v_knot_values": [
                            float(surface.VKnot(index))
                            for index in range(1, surface.NbVKnots() + 1)
                        ],
                        "u_multiplicities": [
                            int(surface.UMultiplicity(index))
                            for index in range(1, surface.NbUKnots() + 1)
                        ],
                        "v_multiplicities": [
                            int(surface.VMultiplicity(index))
                            for index in range(1, surface.NbVKnots() + 1)
                        ],
                    }
                )
    elif geometry_type == "REVOLUTION":
        parameters["axis"] = _axis_parameters(adaptor.AxeOfRevolution())
    elif geometry_type == "EXTRUSION":
        parameters["direction"] = xyz(adaptor.Direction())
    elif geometry_type == "OFFSET":
        parameters["offset"] = float(adaptor.OffsetValue())

    return parameters


def _curve_parameters(
    edge: TopoDS_Edge,
    *,
    include_definition: bool = False,
) -> dict[str, Any]:
    adaptor = BRepAdaptor_Curve(edge)
    geometry_type = _curve_type(edge)
    parameters: dict[str, Any] = {
        "parameter_range": [
            float(adaptor.FirstParameter()),
            float(adaptor.LastParameter()),
        ],
        "periodic": bool(adaptor.IsPeriodic()),
    }

    if geometry_type == "LINE":
        line = adaptor.Line()
        parameters.update(
            {
                "origin": xyz(line.Location()),
                "direction": xyz(line.Direction()),
            }
        )
    elif geometry_type == "CIRCLE":
        circle = adaptor.Circle()
        parameters.update(
            {
                "center": xyz(circle.Location()),
                "axis_direction": xyz(circle.Axis().Direction()),
                "x_direction": xyz(circle.XAxis().Direction()),
                "radius": float(circle.Radius()),
            }
        )
    elif geometry_type == "ELLIPSE":
        ellipse = adaptor.Ellipse()
        parameters.update(
            {
                "center": xyz(ellipse.Location()),
                "axis_direction": xyz(ellipse.Axis().Direction()),
                "x_direction": xyz(ellipse.XAxis().Direction()),
                "major_radius": float(ellipse.MajorRadius()),
                "minor_radius": float(ellipse.MinorRadius()),
            }
        )
    elif geometry_type == "HYPERBOLA":
        hyperbola = adaptor.Hyperbola()
        parameters.update(
            {
                "center": xyz(hyperbola.Location()),
                "axis_direction": xyz(hyperbola.Axis().Direction()),
                "x_direction": xyz(hyperbola.XAxis().Direction()),
                "major_radius": float(hyperbola.MajorRadius()),
                "minor_radius": float(hyperbola.MinorRadius()),
            }
        )
    elif geometry_type == "PARABOLA":
        parabola = adaptor.Parabola()
        parameters.update(
            {
                "vertex": xyz(parabola.Location()),
                "axis_direction": xyz(parabola.Axis().Direction()),
                "x_direction": xyz(parabola.XAxis().Direction()),
                "focal_length": float(parabola.Focal()),
            }
        )
    elif geometry_type in {"BEZIER", "BSPLINE"}:
        parameters.update(
            {
                "degree": int(adaptor.Degree()),
                "pole_count": int(adaptor.NbPoles()),
            }
        )
        if geometry_type == "BSPLINE":
            parameters["knot_count"] = int(adaptor.NbKnots())
        if include_definition:
            curve = (
                adaptor.BSpline() if geometry_type == "BSPLINE" else adaptor.Bezier()
            )
            rational = bool(curve.IsRational())
            parameters.update(
                {
                    "rational": rational,
                    "control_points": [
                        xyz(curve.Pole(index))
                        for index in range(1, curve.NbPoles() + 1)
                    ],
                    "weights": (
                        [
                            float(curve.Weight(index))
                            for index in range(1, curve.NbPoles() + 1)
                        ]
                        if rational
                        else None
                    ),
                }
            )
            if geometry_type == "BSPLINE":
                parameters.update(
                    {
                        "knot_values": [
                            float(curve.Knot(index))
                            for index in range(1, curve.NbKnots() + 1)
                        ],
                        "multiplicities": [
                            int(curve.Multiplicity(index))
                            for index in range(1, curve.NbKnots() + 1)
                        ],
                    }
                )

    return parameters


def _curve_definition_available(geometry_type: str) -> bool:
    return geometry_type in {
        "LINE",
        "CIRCLE",
        "ELLIPSE",
        "HYPERBOLA",
        "PARABOLA",
        "BEZIER",
        "BSPLINE",
    }


def _endpoint_differential(
    edge: TopoDS_Edge,
    *,
    first: bool,
) -> dict[str, Any]:
    """Evaluate derivatives using an edge-oriented curve parameter."""

    adaptor = BRepAdaptor_Curve(edge)
    reversed_edge = edge.Orientation() == TopAbs_REVERSED
    direction = -1.0 if reversed_edge else 1.0
    parameter = float(
        adaptor.LastParameter() if first == reversed_edge else adaptor.FirstParameter()
    )
    point = gp_Pnt()
    first_derivative = gp_Vec()
    second_derivative = gp_Vec()
    third_derivative = gp_Vec()
    second_available = True
    third_available = True
    try:
        adaptor.D3(
            parameter,
            point,
            first_derivative,
            second_derivative,
            third_derivative,
        )
    except Exception:
        third_available = False
        try:
            adaptor.D2(parameter, point, first_derivative, second_derivative)
        except Exception:
            second_available = False
            adaptor.D1(parameter, point, first_derivative)

    oriented_first = first_derivative.Multiplied(direction)
    oriented_second = second_derivative if second_available else None
    oriented_third = third_derivative.Multiplied(direction) if third_available else None
    magnitude = float(oriented_first.Magnitude())
    unit_tangent = None
    if magnitude > 1.0e-15:
        unit_tangent = xyz(oriented_first.Multiplied(1.0 / magnitude))
    outward_tangent = (
        ([-value for value in unit_tangent] if first else unit_tangent)
        if unit_tangent is not None
        else None
    )
    return {
        "curve_parameter": parameter,
        "curve_parameter_direction": int(direction),
        "point": xyz(point),
        "d1": xyz(oriented_first),
        "d2": xyz(oriented_second) if oriented_second is not None else None,
        "d3": xyz(oriented_third) if oriented_third is not None else None,
        "unit_tangent": unit_tangent,
        "outward_unit_tangent": outward_tangent,
    }


def _endpoint_differentials(edge: TopoDS_Edge) -> dict[str, Any]:
    return {
        "derivative_parameterization": "edge_oriented_curve_parameter",
        "start": _endpoint_differential(edge, first=True),
        "end": _endpoint_differential(edge, first=False),
    }


def _normalized_tangent(edge: TopoDS_Edge) -> list[float] | None:
    adaptor = BRepAdaptor_Curve(edge)
    parameter = 0.5 * (float(adaptor.FirstParameter()) + float(adaptor.LastParameter()))
    point = gp_Pnt()
    derivative = gp_Vec()
    adaptor.D1(parameter, point, derivative)
    magnitude = float(derivative.Magnitude())
    if magnitude <= 1.0e-15:
        return None
    derivative.Normalize()
    return xyz(derivative)


def _face_normal(face: TopoDS_Face) -> list[float] | None:
    for u, v in (
        (0.5, 0.5),
        (0.25, 0.5),
        (0.75, 0.5),
        (0.5, 0.25),
        (0.5, 0.75),
    ):
        try:
            return list(face_normal_at(face, u, v))
        except ValueError:
            continue
    return None


def _wire_edge_count(wire: TopoDS_Shape) -> int:
    if wire.IsNull():
        return 0
    edges = _mapped_edges(_indexed_map(wire, TopAbs_EDGE))
    return sum(not BRep_Tool.Degenerated_s(edge) for edge in edges)


def _edge_endpoint(edge: TopoDS_Edge, *, first: bool) -> list[float]:
    vertex = (
        TopExp.FirstVertex_s(edge, True) if first else TopExp.LastVertex_s(edge, True)
    )
    if not vertex.IsNull():
        return list(vertex_point(vertex))
    adaptor = BRepAdaptor_Curve(edge)
    parameter = (
        float(adaptor.FirstParameter()) if first else float(adaptor.LastParameter())
    )
    return xyz(adaptor.Value(parameter))


def _describe_geometry(
    kind: EntityKind,
    entity: TopoDS_Shape,
    *,
    include_curve_definition: bool = False,
    include_surface_definition: bool = False,
    max_surface_control_points: int = 256,
) -> dict[str, Any]:
    if kind == "body":
        body = TopoDS.Solid_s(entity)
        volume, centroid = measure_shape_mass_rtuple(body, "volume")
        area, _ = measure_shape_mass_rtuple(body, "area")
        return {
            "type": "SOLID",
            "volume": volume,
            "surface_area": area,
            "centroid": centroid.tolist(),
            "face_count": _subshape_count(body, TopAbs_FACE),
            "edge_count": sum(
                not BRep_Tool.Degenerated_s(edge)
                for edge in _mapped_edges(_indexed_map(body, TopAbs_EDGE))
            ),
            "vertex_count": _subshape_count(body, TopAbs_VERTEX),
            "valid": bool(BRepCheck_Analyzer(body).IsValid()),
        }

    if kind == "face":
        face = TopoDS.Face_s(entity)
        area, centroid = measure_shape_mass_rtuple(face, "area")
        adaptor = BRepAdaptor_Surface(face, True)
        return {
            "type": _surface_type(adaptor),
            "area": area,
            "centroid": centroid.tolist(),
            "normal_at_center": _face_normal(face),
            "outer_edge_count": _wire_edge_count(outer_wire_of(face)),
            "inner_boundary_count": len(inner_wires_of(face)),
            "parameters": _surface_parameters(
                face,
                include_definition=include_surface_definition,
                max_control_points=max_surface_control_points,
            ),
        }

    if kind == "edge":
        edge = TopoDS.Edge_s(entity)
        if BRep_Tool.Degenerated_s(edge):
            vertices = _indexed_map(edge, TopAbs_VERTEX)
            coordinates = (
                list(vertex_point(TopoDS.Vertex_s(vertices.FindKey(1))))
                if vertices.Extent()
                else [0.0, 0.0, 0.0]
            )
            return {
                "type": "DEGENERATE",
                "underlying_curve_type": _underlying_curve_type(edge),
                "length": 0.0,
                "start": coordinates,
                "end": coordinates,
                "centroid": coordinates,
                "tangent_at_midpoint": None,
                "endpoint_differentials": None,
                "closed": True,
                "degenerated": True,
                "parameters": {},
            }

        length, centroid = measure_shape_mass_rtuple(edge, "length")
        adaptor = BRepAdaptor_Curve(edge)
        return {
            "type": _curve_type(edge),
            "length": length,
            "start": _edge_endpoint(edge, first=True),
            "end": _edge_endpoint(edge, first=False),
            "centroid": centroid.tolist(),
            "tangent_at_midpoint": _normalized_tangent(edge),
            "endpoint_differentials": _endpoint_differentials(edge),
            "closed": bool(adaptor.IsClosed()),
            "degenerated": False,
            "parameters": _curve_parameters(
                edge,
                include_definition=include_curve_definition,
            ),
        }

    vertex = TopoDS.Vertex_s(entity)
    return {
        "type": "POINT",
        "coordinates": list(vertex_point(vertex)),
    }


def _fuse_bodies(bodies: Sequence[TopoDS_Solid]) -> TopoDS_Shape:
    """Union material without modifying the original bodies or their pcurves."""
    if not bodies:
        raise BRepEntityError("Model has no solid bodies")
    result: TopoDS_Shape = bodies[0]
    for body in bodies[1:]:
        # The two-shape constructor builds immediately, before options can be
        # set. Configure an empty operation before its first and only Build.
        arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        arguments.Append(result)
        tools.Append(body)
        operation = BRepAlgoAPI_Fuse()
        operation.SetArguments(arguments)
        operation.SetTools(tools)
        operation.SetNonDestructive(True)
        operation.Build()
        if not operation.IsDone():
            raise BRepEntityError(
                "OpenCascade failed to union model bodies for material properties"
            )
        result = operation.Shape()
    return result


@dataclass
class BRepModel:
    """One BREP with deterministic zero-based topology ids and incidence data."""

    root: TopoDS_Shape
    source: str | None
    bodies: tuple[TopoDS_Solid, ...]
    faces: tuple[TopoDS_Face, ...]
    edges: tuple[TopoDS_Edge, ...]
    vertices: tuple[TopoDS_Vertex, ...]
    adjacency: dict[str, set[str]]
    _maps: dict[EntityKind, TopTools_IndexedMapOfShape] = field(repr=False)
    _material_union_cache: TopoDS_Shape | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @classmethod
    def from_shape(
        cls,
        shape: TopoDS_Shape,
        *,
        source: str | Path | None = None,
    ) -> "BRepModel":
        if shape.IsNull():
            raise BRepEntityError("Cannot index a null BREP shape")

        body_map = _indexed_map(shape, TopAbs_SOLID)
        face_map = _indexed_map(shape, TopAbs_FACE)
        edge_map = _indexed_map(shape, TopAbs_EDGE)
        vertex_map = _indexed_map(shape, TopAbs_VERTEX)
        model = cls(
            root=shape,
            source=str(source) if source is not None else None,
            bodies=_mapped_solids(body_map),
            faces=_mapped_faces(face_map),
            edges=_mapped_edges(edge_map),
            vertices=_mapped_vertices(vertex_map),
            adjacency=defaultdict(set),
            _maps={
                "body": body_map,
                "face": face_map,
                "edge": edge_map,
                "vertex": vertex_map,
            },
        )
        model._build_adjacency()
        return model

    def entity_list(self, kind: EntityKind) -> Sequence[TopoDS_Shape]:
        return {
            "body": self.bodies,
            "face": self.faces,
            "edge": self.edges,
            "vertex": self.vertices,
        }[kind]

    def resolve_entity(self, entity_id: str) -> tuple[EntityKind, int, TopoDS_Shape]:
        kind, index = _parse_entity_id(entity_id)
        entities = self.entity_list(kind)
        if index < 0 or index >= len(entities):
            maximum = len(entities) - 1
            raise BRepEntityError(
                f"{kind} index {index} is out of range; valid range is 0..{maximum}"
            )
        return kind, index, entities[index]

    def id_for_shape(self, kind: EntityKind, shape: TopoDS_Shape) -> str:
        mapped_index = int(self._maps[kind].FindIndex(shape))
        if mapped_index <= 0:
            raise BRepEntityError(
                f"Could not map {kind} shape back to a stable entity id"
            )
        return _canonical_entity_id(kind, mapped_index - 1)

    def _link(self, left: str, right: str) -> None:
        self.adjacency[left].add(right)
        self.adjacency[right].add(left)

    def _build_adjacency(self) -> None:
        for kind in ENTITY_KINDS:
            for index in range(len(self.entity_list(kind))):
                self.adjacency[_canonical_entity_id(kind, index)]

        for body_index, body in enumerate(self.bodies):
            body_id = _canonical_entity_id("body", body_index)
            explorer = TopExp_Explorer(body, TopAbs_FACE)
            while explorer.More():
                self._link(body_id, self.id_for_shape("face", explorer.Current()))
                explorer.Next()

        for face_index, face in enumerate(self.faces):
            face_id = _canonical_entity_id("face", face_index)
            explorer = TopExp_Explorer(face, TopAbs_EDGE)
            while explorer.More():
                self._link(face_id, self.id_for_shape("edge", explorer.Current()))
                explorer.Next()

        for edge_index, edge in enumerate(self.edges):
            edge_id = _canonical_entity_id("edge", edge_index)
            explorer = TopExp_Explorer(edge, TopAbs_VERTEX)
            while explorer.More():
                self._link(
                    edge_id,
                    self.id_for_shape("vertex", explorer.Current()),
                )
                explorer.Next()

    def direct_neighbors(self, entity_id: str) -> list[str]:
        kind, index, _ = self.resolve_entity(entity_id)
        canonical = _canonical_entity_id(kind, index)
        return sorted(self.adjacency[canonical], key=_entity_sort_key)

    def adjacency_details(self, entity_id: str) -> dict[str, Any]:
        kind, index, _ = self.resolve_entity(entity_id)
        canonical = _canonical_entity_id(kind, index)
        direct = self.direct_neighbors(canonical)
        details: dict[str, Any] = {"direct": direct}

        if kind == "body":
            details["faces"] = [item for item in direct if item.startswith("face:")]
        elif kind == "face":
            edge_ids = [item for item in direct if item.startswith("edge:")]
            body_ids = [item for item in direct if item.startswith("body:")]
            neighboring_faces = {
                neighbor
                for edge_id in edge_ids
                for neighbor in self.adjacency[edge_id]
                if neighbor.startswith("face:") and neighbor != canonical
            }
            details.update(
                {
                    "bodies": body_ids,
                    "edges": edge_ids,
                    "neighboring_faces": sorted(
                        neighboring_faces,
                        key=_entity_sort_key,
                    ),
                }
            )
        elif kind == "edge":
            face_ids = [item for item in direct if item.startswith("face:")]
            vertex_ids = [item for item in direct if item.startswith("vertex:")]
            adjacent_edges = {
                neighbor
                for vertex_id in vertex_ids
                for neighbor in self.adjacency[vertex_id]
                if neighbor.startswith("edge:") and neighbor != canonical
            }
            details.update(
                {
                    "faces": face_ids,
                    "vertices": vertex_ids,
                    "adjacent_edges": sorted(
                        adjacent_edges,
                        key=_entity_sort_key,
                    ),
                }
            )
        else:
            edge_ids = [item for item in direct if item.startswith("edge:")]
            face_ids = {
                neighbor
                for edge_id in edge_ids
                for neighbor in self.adjacency[edge_id]
                if neighbor.startswith("face:")
            }
            details.update(
                {
                    "edges": edge_ids,
                    "faces": sorted(face_ids, key=_entity_sort_key),
                }
            )
        return details

    def describe_entity(
        self,
        entity_id: str,
        *,
        include_curve_definition: bool = False,
        include_surface_definition: bool = False,
        max_surface_control_points: int = 256,
    ) -> dict[str, Any]:
        if max_surface_control_points < 1:
            raise ValueError("max_surface_control_points must be at least one")
        kind, index, entity = self.resolve_entity(entity_id)
        canonical = _canonical_entity_id(kind, index)
        return {
            "entity_id": canonical,
            "kind": kind,
            "geometry": _describe_geometry(
                kind,
                entity,
                include_curve_definition=include_curve_definition,
                include_surface_definition=include_surface_definition,
                max_surface_control_points=max_surface_control_points,
            ),
            "bounding_box": _bounding_box(entity),
            "adjacency": self.adjacency_details(canonical),
        }

    def _material_union(self) -> TopoDS_Shape:
        if self._material_union_cache is None:
            self._material_union_cache = _fuse_bodies(self.bodies)
        return self._material_union_cache

    def parameter_groups(
        self,
        *,
        max_groups: int = 24,
        examples_per_group: int = 3,
    ) -> dict[str, Any]:
        """Return bounded scalar carrier groups without inferring a pattern."""

        if max_groups < 1:
            raise ValueError("max_groups must be at least one")
        if examples_per_group < 1:
            raise ValueError("examples_per_group must be at least one")
        surface_groups: dict[tuple[str, tuple[tuple[str, Any], ...]], list[str]] = (
            defaultdict(list)
        )
        curve_groups: dict[tuple[str, tuple[tuple[str, Any], ...]], list[str]] = (
            defaultdict(list)
        )
        axis_groups: dict[
            tuple[
                str,
                tuple[float, float, float] | None,
                tuple[float, float, float],
            ],
            list[tuple[str, str]],
        ] = defaultdict(list)
        face_adjacency_groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        edge_adjacency_groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for index, face in enumerate(self.faces):
            entity_id = f"face:{index}"
            geometry_type, parameters = _surface_group_parameters(face)
            surface_groups[_parameter_group_key(geometry_type, parameters)].append(
                entity_id
            )
            axis = _axis_group_descriptor("face", face)
            if axis is not None:
                axis_groups[axis].append((entity_id, f"face:{geometry_type}"))
        for index, edge in enumerate(self.edges):
            entity_id = f"edge:{index}"
            geometry_type, parameters = _curve_group_parameters(edge)
            curve_groups[_parameter_group_key(geometry_type, parameters)].append(
                entity_id
            )
            axis = _axis_group_descriptor("edge", edge)
            if axis is not None:
                axis_groups[axis].append((entity_id, f"edge:{geometry_type}"))

        for kind, groups in (
            ("face", face_adjacency_groups),
            ("edge", edge_adjacency_groups),
        ):
            for index, shape in enumerate(self.entity_list(kind)):
                entity_id = f"{kind}:{index}"
                neighbor_counts: Counter[str] = Counter()
                neighbor_geometry: Counter[str] = Counter()
                for neighbor_id in self.direct_neighbors(entity_id):
                    neighbor_kind, _, neighbor_shape = self.resolve_entity(neighbor_id)
                    neighbor_counts[neighbor_kind] += 1
                    neighbor_geometry[
                        f"{neighbor_kind}:{_entity_geometry_type(neighbor_kind, neighbor_shape)}"
                    ] += 1
                key = (
                    _entity_geometry_type(kind, shape),
                    tuple(sorted(neighbor_counts.items())),
                    tuple(sorted(neighbor_geometry.items())),
                )
                groups[key].append(entity_id)
        return {
            "surfaces": _bounded_parameter_groups(
                surface_groups,
                max_groups=max_groups,
                examples_per_group=examples_per_group,
            ),
            "curves": _bounded_parameter_groups(
                curve_groups,
                max_groups=max_groups,
                examples_per_group=examples_per_group,
            ),
            "axes": _bounded_axis_groups(
                axis_groups,
                max_groups=max_groups,
                examples_per_group=examples_per_group,
            ),
            "adjacency_signatures": {
                "faces": _bounded_adjacency_groups(
                    face_adjacency_groups,
                    max_groups=max_groups,
                    examples_per_group=examples_per_group,
                ),
                "edges": _bounded_adjacency_groups(
                    edge_adjacency_groups,
                    max_groups=max_groups,
                    examples_per_group=examples_per_group,
                ),
            },
            "pattern_inference": "not_performed",
            "interpretation": (
                "Equal carrier parameters, canonical axes, and adjacency signatures "
                "are descriptive multiplicities, not proof of a linear, radial, or "
                "repeated feature pattern."
            ),
        }

    def summary(
        self,
        *,
        include_parameter_groups: bool = False,
        max_parameter_groups: int = 24,
        examples_per_group: int = 3,
    ) -> dict[str, Any]:
        has_solid_material = bool(self.bodies)
        if has_solid_material:
            material = self._material_union()
            total_volume, centroid = measure_shape_mass_rtuple(material, "volume")
            material_surface_area, _ = measure_shape_mass_rtuple(material, "area")
            material_bounding_box = _bounding_box(material)
            material_body_count = _subshape_count(material, TopAbs_SOLID)
        else:
            total_volume, centroid = measure_shape_mass_rtuple(self.root, "volume")
            material_surface_area, surface_centroid = measure_shape_mass_rtuple(self.root, "area")
            if abs(total_volume) <= 1.0e-12:
                centroid = (
                    surface_centroid
                    if material_surface_area > 1.0e-12
                    else _bounding_box(self.root)["center"]
                )
            material_bounding_box = _bounding_box(self.root)
            material_body_count = 0

        body_summaries = []
        for index, body in enumerate(self.bodies):
            volume, center = measure_shape_mass_rtuple(body, "volume")
            area, _ = measure_shape_mass_rtuple(body, "area")
            body_summaries.append(
                {
                    "entity_id": _canonical_entity_id("body", index),
                    "volume": volume,
                    "surface_area": area,
                    "centroid": center.tolist(),
                    "bounding_box": _bounding_box(body),
                    "face_count": _subshape_count(body, TopAbs_FACE),
                    "edge_count": _subshape_count(body, TopAbs_EDGE),
                    "vertex_count": _subshape_count(body, TopAbs_VERTEX),
                }
            )

        surface_types = Counter(
            _surface_type(BRepAdaptor_Surface(face, True)) for face in self.faces
        )
        curve_types = Counter(_curve_type(edge) for edge in self.edges)
        centroid_list = (
            centroid.tolist() if hasattr(centroid, "tolist") else list(centroid)
        )
        result = {
            "model_path": self.source,
            "length_unit": "mm",
            "valid": bool(BRepCheck_Analyzer(self.root).IsValid()),
            "root_shape_type": _root_shape_type(self.root),
            "body_count": len(self.bodies),
            "material_body_count": material_body_count,
            "face_count": len(self.faces),
            "edge_count": len(self.edges),
            "vertex_count": len(self.vertices),
            "bounding_box": material_bounding_box,
            "root_bounding_box": _bounding_box(self.root),
            "volume": total_volume,
            "volume_is_solid_material": has_solid_material,
            "material_operations_supported": has_solid_material,
            "surface_area": material_surface_area,
            "centroid": centroid_list,
            "surface_type_statistics": dict(sorted(surface_types.items())),
            "curve_type_statistics": dict(sorted(curve_types.items())),
            "bodies": body_summaries,
            "entity_id_format": {
                "body": "body:<zero-based-index>",
                "face": "face:<zero-based-index>",
                "edge": "edge:<zero-based-index>",
                "vertex": "vertex:<zero-based-index>",
            },
        }
        if include_parameter_groups:
            result["parameter_groups"] = self.parameter_groups(
                max_groups=max_parameter_groups,
                examples_per_group=examples_per_group,
            )
        return result


def index_shape_rbrepmodel(
    shape: TopoDS_Shape,
    *,
    source: str | Path | None = None,
) -> BRepModel:
    """Build stable entity maps for one in-memory OCP shape."""

    return BRepModel.from_shape(shape, source=source)


@lru_cache(maxsize=8)
def _load_step_model_cached(
    resolved_path: str,
    modified_ns: int,
    file_size: int,
) -> BRepModel:
    del modified_ns, file_size
    try:
        shape = load_step_rshape(
            resolved_path,
            require_single_root=False,
            require_valid=False,
        )
    except ValueError as exc:
        raise BRepEntityError(str(exc)) from exc
    return BRepModel.from_shape(shape, source=resolved_path)


def load_step_rbrepmodel(path: str | Path) -> BRepModel:
    """Load and cache a STEP model with deterministic topology ids."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise BRepEntityError(f"STEP file does not exist: {source}")
    if source.suffix.lower() not in {".step", ".stp"}:
        raise BRepEntityError(
            f"Expected a .step or .stp file, got: {source.suffix or '<none>'}"
        )
    stat = source.stat()
    return _load_step_model_cached(
        str(source),
        stat.st_mtime_ns,
        stat.st_size,
    )


def clear_step_model_cache_rnone() -> None:
    """Clear the bounded STEP entity-model cache."""

    _load_step_model_cached.cache_clear()


def inspect_step_rsummary(
    path: str | Path,
    *,
    include_parameter_groups: bool = False,
    max_parameter_groups: int = 24,
    examples_per_group: int = 3,
) -> dict[str, Any]:
    """Return global material and topology facts for one STEP file."""

    return load_step_rbrepmodel(path).summary(
        include_parameter_groups=include_parameter_groups,
        max_parameter_groups=max_parameter_groups,
        examples_per_group=examples_per_group,
    )


def inspect_step_entity_rdescriptor(
    path: str | Path,
    entity_id: str,
    *,
    include_curve_definition: bool = False,
    include_surface_definition: bool = False,
    max_surface_control_points: int = 256,
) -> dict[str, Any]:
    """Return geometry, measurements, bounds, and adjacency for one entity id."""

    return load_step_rbrepmodel(path).describe_entity(
        entity_id,
        include_curve_definition=include_curve_definition,
        include_surface_definition=include_surface_definition,
        max_surface_control_points=max_surface_control_points,
    )


__all__ = [
    "BRepEntityError",
    "BRepModel",
    "ENTITY_KINDS",
    "EntityKind",
    "clear_step_model_cache_rnone",
    "inspect_step_rsummary",
    "index_shape_rbrepmodel",
    "inspect_step_entity_rdescriptor",
    "load_step_rbrepmodel",
]
