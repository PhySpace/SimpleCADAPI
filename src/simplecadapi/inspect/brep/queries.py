"""OCP-native local topology and geometry queries for indexed BREP models.

The functions in this module intentionally return only JSON-compatible values.
They accept an already indexed :class:`BRepModel`, an in-memory OCP shape, or a
local STEP path; entity identifiers always use the stable zero-based model ids.
"""

from __future__ import annotations

from collections import Counter, deque
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from simplecadapi._cpp.occt.BRep import BRep_Builder, BRep_Tool
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Section
from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from simplecadapi._cpp.occt.BRepExtrema import BRepExtrema_DistShapeShape
from simplecadapi._cpp.occt.BRepGProp import BRepGProp
from simplecadapi._cpp.occt.BRepTools import BRepTools, BRepTools_WireExplorer
from simplecadapi._cpp.occt.GProp import GProp_GProps
from simplecadapi._cpp.occt.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from simplecadapi._cpp.occt.TopExp import TopExp, TopExp_Explorer
from simplecadapi._cpp.occt.TopTools import TopTools_IndexedMapOfShape
from simplecadapi._cpp.occt.TopoDS import (
    TopoDS,
    TopoDS_Compound,
    TopoDS_Edge,
    TopoDS_Face,
    TopoDS_Shape,
    TopoDS_Wire,
)
from simplecadapi._cpp.occt.gp import gp_Dir, gp_Pln, gp_Pnt

from .io import xyz
from .model import (
    BRepEntityError,
    BRepModel,
    ENTITY_KINDS,
    _bounding_box,
    _curve_definition_available,
    _curve_parameters,
    _curve_type,
    index_shape_rbrepmodel,
    load_step_rbrepmodel,
)


def _model(value: BRepModel | TopoDS_Shape | str | Path) -> BRepModel:
    if isinstance(value, BRepModel):
        return value
    if isinstance(value, TopoDS_Shape):
        return index_shape_rbrepmodel(value)
    if isinstance(value, (str, Path)):
        return load_step_rbrepmodel(value)
    raise TypeError("model_or_path must be a BRepModel, TopoDS_Shape, or STEP path")


def _entity_key(entity_id: str) -> tuple[int, int]:
    kind, index = entity_id.split(":", 1)
    return ENTITY_KINDS.index(kind), int(index)


def _canonical_id(
    model: BRepModel, entity_id: str
) -> tuple[str, str, int, TopoDS_Shape]:
    kind, index, shape = model.resolve_entity(entity_id)
    return f"{kind}:{index}", kind, index, shape


def _require_nonnegative(value: int, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_positive(value: float, name: str) -> None:
    if value <= 0.0:
        raise ValueError(f"{name} must be greater than zero")


def _point(value: Sequence[float], name: str) -> np.ndarray:
    if len(value) != 3:
        raise ValueError(f"{name} must contain exactly three coordinates")
    result = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain finite coordinates")
    return result


def _distance(
    first: TopoDS_Shape, second: TopoDS_Shape
) -> tuple[float, list[dict[str, list[float]]]]:
    operation = BRepExtrema_DistShapeShape(first, second)
    operation.Perform()
    if not operation.IsDone():
        raise BRepEntityError("OpenCascade could not compute the closest distance")
    points = [
        {
            "first": xyz(operation.PointOnShape1(index)),
            "second": xyz(operation.PointOnShape2(index)),
        }
        for index in range(1, operation.NbSolution() + 1)
    ]
    points.sort(key=lambda item: tuple(item["first"] + item["second"]))
    return float(operation.Value()), points


def _linear_length(edge: TopoDS_Edge) -> float:
    properties = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, properties)
    return float(properties.Mass())


def _sample_edge(edge: TopoDS_Edge, samples_per_edge: int) -> list[list[float]]:
    if BRep_Tool.Degenerated_s(edge):
        explorer = TopExp_Explorer(edge, TopAbs_VERTEX)
        if explorer.More():
            return [xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(explorer.Current())))]
        return []
    curve = BRepAdaptor_Curve(edge)
    first, last = float(curve.FirstParameter()), float(curve.LastParameter())
    if edge.Orientation() == TopAbs_REVERSED:
        first, last = last, first
    return [
        xyz(curve.Value(float(parameter)))
        for parameter in np.linspace(first, last, samples_per_edge)
    ]


def _sample_length(points: Sequence[Sequence[float]]) -> float:
    return float(
        sum(
            np.linalg.norm(np.asarray(right) - np.asarray(left))
            for left, right in zip(points, points[1:])
        )
    )


def _plane_basis(
    origin: np.ndarray, normal: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    magnitude = float(np.linalg.norm(normal))
    if magnitude <= 1.0e-15:
        raise ValueError("normal must be non-zero")
    z_axis = normal / magnitude
    reference = np.asarray([1.0, 0.0, 0.0])
    if abs(float(np.dot(reference, z_axis))) > 0.9:
        reference = np.asarray([0.0, 1.0, 0.0])
    x_axis = np.cross(reference, z_axis)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    return origin, x_axis, y_axis


def _plane_coordinates(
    point: Sequence[float], origin: np.ndarray, x_axis: np.ndarray, y_axis: np.ndarray
) -> list[float]:
    offset = np.asarray(point, dtype=float) - origin
    return [float(np.dot(offset, x_axis)), float(np.dot(offset, y_axis))]


def _polygon_area(points: Sequence[Sequence[float]]) -> float:
    if len(points) < 4:
        return 0.0
    values = np.asarray(points, dtype=float)
    return float(
        0.5
        * abs(
            np.dot(values[:-1, 0], values[1:, 1])
            - np.dot(values[:-1, 1], values[1:, 0])
        )
    )


def _point_in_polygon(
    point: Sequence[float],
    polygon: Sequence[Sequence[float]],
) -> bool:
    x_value, y_value = point
    inside = False
    for first, second in zip(polygon, polygon[1:]):
        x_first, y_first = first
        x_second, y_second = second
        crosses = (y_first > y_value) != (y_second > y_value)
        if crosses:
            intersection = (x_second - x_first) * (y_value - y_first) / (
                y_second - y_first
            ) + x_first
            if x_value < intersection:
                inside = not inside
    return inside


def _classify_closed_contours(contours: list[dict[str, Any]]) -> float:
    closed = [
        contour
        for contour in contours
        if contour["closed"] and contour["area"] is not None
    ]
    for contour in closed:
        points = np.asarray(contour["samples_2d"][:-1], dtype=float)
        mean = np.mean(points, axis=0)
        probe = points[0] * 0.999 + mean * 0.001
        nesting_depth = sum(
            _point_in_polygon(probe, other["samples_2d"])
            for other in closed
            if other is not contour and other["area"] > contour["area"]
        )
        contour["nesting_depth"] = nesting_depth
        contour["role"] = "material" if nesting_depth % 2 == 0 else "hole"
    return float(
        sum(
            contour["area"] if contour["role"] == "material" else -contour["area"]
            for contour in closed
        )
    )


def _shape_geometry(shape: TopoDS_Shape, kind: str) -> dict[str, Any]:
    """Extract only analytic directions/axes needed for conservative relations."""
    if kind == "face":
        adaptor = BRepAdaptor_Surface(TopoDS.Face_s(shape), True)
        name = str(adaptor.GetType()).split(".")[-1].removeprefix("GeomAbs_")
        if name == "Plane":
            plane = adaptor.Plane()
            return {
                "type": "plane",
                "direction": np.asarray(plane.Axis().Direction().Coord(), dtype=float),
                "point": np.asarray(plane.Location().Coord(), dtype=float),
                "direction_role": "normal",
            }
        if name == "Cylinder":
            cylinder = adaptor.Cylinder()
            return {
                "type": "cylinder",
                "direction": np.asarray(
                    cylinder.Axis().Direction().Coord(), dtype=float
                ),
                "point": np.asarray(cylinder.Location().Coord(), dtype=float),
                "radius": float(cylinder.Radius()),
                "direction_role": "axis",
            }
        return {"type": name.lower()}

    if kind == "edge":
        edge = TopoDS.Edge_s(shape)
        if BRep_Tool.Degenerated_s(edge):
            return {"type": "degenerate"}
        adaptor = BRepAdaptor_Curve(edge)
        name = str(adaptor.GetType()).split(".")[-1].removeprefix("GeomAbs_")
        if name == "Line":
            line = adaptor.Line()
            return {
                "type": "line",
                "direction": np.asarray(line.Direction().Coord(), dtype=float),
                "point": np.asarray(line.Location().Coord(), dtype=float),
                "direction_role": "axis",
            }
        if name == "Circle":
            circle = adaptor.Circle()
            return {
                "type": "circle",
                "direction": np.asarray(circle.Axis().Direction().Coord(), dtype=float),
                "point": np.asarray(circle.Location().Coord(), dtype=float),
                "radius": float(circle.Radius()),
                "direction_role": "axis",
            }
        return {"type": name.lower()}
    return {"type": kind}


def _angle_degrees(first: np.ndarray, second: np.ndarray) -> float:
    cosine = float(
        np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second))
    )
    return math.degrees(math.acos(min(1.0, max(-1.0, abs(cosine)))))


def _axes_coaxial(
    first: dict[str, Any], second: dict[str, Any], tolerance: float, angular: float
) -> bool:
    if "direction" not in first or "direction" not in second:
        return False
    if _angle_degrees(first["direction"], second["direction"]) > angular:
        return False
    direction = first["direction"] / np.linalg.norm(first["direction"])
    offset = second["point"] - first["point"]
    return float(np.linalg.norm(np.cross(offset, direction))) <= tolerance


def inspect_topology_neighborhood_rdescriptor(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    entity_id: str,
    depth: int = 1,
    max_entities: int = 100,
) -> dict[str, Any]:
    """Return a deterministic, bounded breadth-first topology neighborhood."""
    _require_nonnegative(depth, "depth")
    if max_entities < 1:
        raise ValueError("max_entities must be at least one")
    model = _model(model_or_path)
    root, _, _, _ = _canonical_id(model, entity_id)
    seen = {root}
    queue: deque[tuple[str, int]] = deque([(root, 0)])
    levels = {root: 0}
    truncated = False
    omitted = 0
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for neighbor in model.direct_neighbors(current):
            if neighbor in seen:
                continue
            if len(seen) >= max_entities:
                truncated = True
                omitted += 1
                continue
            seen.add(neighbor)
            levels[neighbor] = current_depth + 1
            queue.append((neighbor, current_depth + 1))

    ids = sorted(seen, key=_entity_key)
    links = [
        {"first": entity, "second": neighbor}
        for entity in ids
        for neighbor in model.direct_neighbors(entity)
        if neighbor in seen and _entity_key(entity) < _entity_key(neighbor)
    ]
    return {
        "root": root,
        "depth": depth,
        "max_entities": max_entities,
        "entities": [
            {
                "entity_id": entity,
                "distance": levels[entity],
                "description": model.describe_entity(entity),
            }
            for entity in ids
        ],
        "adjacency": {
            entity: [
                neighbor
                for neighbor in model.direct_neighbors(entity)
                if neighbor in seen
            ]
            for entity in ids
        },
        "links": links,
        "truncated": truncated,
        "returned_entity_count": len(ids),
        "omitted_neighbor_count": omitted,
        "truncation": {
            "truncated": truncated,
            "max_entities": max_entities,
            "returned_entity_count": len(ids),
            "omitted_neighbor_count": omitted,
        },
    }


def measure_entity_relation_rdescriptor(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    first_entity_id: str,
    second_entity_id: str,
    tolerance: float = 1.0e-7,
    angular_tolerance_degrees: float = 1.0e-4,
    second_model_or_path: BRepModel | TopoDS_Shape | str | Path | None = None,
) -> dict[str, Any]:
    """Measure exact distance and conservatively report supported analytic relations."""
    _require_positive(tolerance, "tolerance")
    _require_nonnegative(angular_tolerance_degrees, "angular_tolerance_degrees")
    first_model = _model(model_or_path)
    second_model = (
        first_model if second_model_or_path is None else _model(second_model_or_path)
    )
    first_id, first_kind, _, first = _canonical_id(first_model, first_entity_id)
    second_id, second_kind, _, second = _canonical_id(
        second_model,
        second_entity_id,
    )
    distance, closest = _distance(first, second)
    first_geometry = _shape_geometry(first, first_kind)
    second_geometry = _shape_geometry(second, second_kind)
    same_model = first_model is second_model
    topologically_identical = bool(same_model and first.IsSame(second))
    if first_kind == second_kind == "vertex":
        coincident_value: bool | None = distance <= tolerance
        coincident_supported = True
        coincident_reason = "Vertex coincidence is defined by exact point distance."
    elif same_model:
        coincident_value = topologically_identical
        coincident_supported = True
        coincident_reason = (
            "The two ids reference the same topological shape."
            if topologically_identical
            else "The two ids reference different topological shapes."
        )
    else:
        coincident_value = None
        coincident_supported = False
        coincident_reason = (
            "Closest distance alone cannot prove full edge or face coincidence "
            "across different models."
        )
    touching = bool(
        distance <= tolerance
        and not (coincident_supported and coincident_value is True)
    )
    relation: dict[str, dict[str, Any]] = {
        "coincident": {
            "value": coincident_value,
            "supported": coincident_supported,
            "reason": coincident_reason,
            "evidence": {"distance": distance, "tolerance": tolerance},
        },
        "touching": {
            "value": touching,
            "supported": True,
            "reason": (
                "Exact closest distance is within tolerance and the entities are "
                "not known to be coincident."
                if touching
                else "Exact closest distance exceeds tolerance or coincidence is established."
            ),
            "evidence": {"distance": distance, "tolerance": tolerance},
        },
    }
    same_direction_role = first_geometry.get("direction_role") == second_geometry.get(
        "direction_role"
    ) and first_geometry.get("direction_role") in {"axis", "normal"}
    angle = (
        _angle_degrees(first_geometry["direction"], second_geometry["direction"])
        if same_direction_role
        else None
    )
    parallel = angle is not None and angle <= angular_tolerance_degrees
    perpendicular = angle is not None and abs(angle - 90.0) <= angular_tolerance_degrees
    for name, value, target in (
        ("parallel", parallel, 0.0),
        ("perpendicular", perpendicular, 90.0),
    ):
        relation[name] = {
            "value": bool(value),
            "supported": same_direction_role,
            "reason": (
                f"Acute angle between supported {first_geometry.get('direction_role')} directions."
                if same_direction_role
                else "This entity pair has no comparable analytic directions."
            ),
            "evidence": {
                "angle_degrees": angle,
                "target_angle_degrees": target,
                "angular_tolerance_degrees": angular_tolerance_degrees,
            },
        }

    plane_pair = first_geometry["type"] == second_geometry["type"] == "plane"
    coplanar = bool(
        plane_pair
        and parallel
        and abs(
            float(
                np.dot(
                    second_geometry["point"] - first_geometry["point"],
                    first_geometry["direction"],
                )
            )
        )
        <= tolerance
    )
    relation["coplanar"] = {
        "value": coplanar,
        "supported": plane_pair,
        "reason": (
            "Parallel plane normals and zero signed plane separation."
            if plane_pair
            else "Coplanarity is currently supported only for analytic planar faces."
        ),
        "evidence": {"tolerance": tolerance},
    }
    axial = {"line", "circle", "cylinder"}
    axis_pair = first_geometry["type"] in axial and second_geometry["type"] in axial
    coaxial = bool(
        axis_pair
        and _axes_coaxial(
            first_geometry, second_geometry, tolerance, angular_tolerance_degrees
        )
    )
    relation["coaxial"] = {
        "value": coaxial,
        "supported": axis_pair,
        "reason": (
            "Analytic axes are parallel and have zero perpendicular separation."
            if axis_pair
            else "Coaxiality is currently supported for analytic lines, circles, and cylinders."
        ),
        "evidence": {"tolerance": tolerance},
    }
    circle_pair = first_geometry["type"] == second_geometry["type"] == "circle"
    cylinder_pair = first_geometry["type"] == second_geometry["type"] == "cylinder"
    concentric = bool(
        (
            circle_pair
            and float(
                np.linalg.norm(first_geometry["point"] - second_geometry["point"])
            )
            <= tolerance
        )
        or (cylinder_pair and coaxial)
    )
    relation["concentric"] = {
        "value": concentric,
        "supported": circle_pair or cylinder_pair,
        "reason": (
            "Circle centers match or cylinder axes are coaxial."
            if circle_pair or cylinder_pair
            else "Concentricity is currently supported for analytic circles and cylinders."
        ),
        "evidence": {"tolerance": tolerance},
    }
    tangent = False
    if circle_pair:
        center_distance = float(
            np.linalg.norm(first_geometry["point"] - second_geometry["point"])
        )
        radius_sum = first_geometry["radius"] + second_geometry["radius"]
        radius_difference = abs(first_geometry["radius"] - second_geometry["radius"])
        circle_coplanar = (
            _angle_degrees(first_geometry["direction"], second_geometry["direction"])
            <= angular_tolerance_degrees
            and abs(
                float(
                    np.dot(
                        second_geometry["point"] - first_geometry["point"],
                        first_geometry["direction"],
                    )
                )
            )
            <= tolerance
        )
        tangent = (
            circle_coplanar
            and distance <= tolerance
            and (
                abs(center_distance - radius_sum) <= tolerance
                or (
                    radius_difference > tolerance
                    and abs(center_distance - radius_difference) <= tolerance
                )
            )
        )
    relation["tangent"] = {
        "value": tangent,
        "supported": circle_pair,
        "reason": (
            "Coplanar analytic circles have an internal or external tangent contact."
            if circle_pair
            else "Tangency is currently supported only for analytic circle edges."
        ),
        "evidence": {"distance": distance, "tolerance": tolerance},
    }
    return {
        "first": {
            "model_path": first_model.source,
            "entity_id": first_id,
            "kind": first_kind,
            "geometry_type": first_geometry["type"],
        },
        "second": {
            "model_path": second_model.source,
            "entity_id": second_id,
            "kind": second_kind,
            "geometry_type": second_geometry["type"],
        },
        "distance": distance,
        "closest_points": closest,
        "angle_degrees": angle,
        "tolerance": tolerance,
        "angular_tolerance_degrees": angular_tolerance_degrees,
        "relations": relation,
    }


def _section_contours(
    edges: list[dict[str, Any]],
    tolerance: float,
    origin: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
) -> list[dict[str, Any]]:
    unused = {edge["index"] for edge in edges}
    by_index = {edge["index"]: edge for edge in edges}

    def endpoint_matches(point: Sequence[float], candidate: Sequence[float]) -> bool:
        return (
            float(np.linalg.norm(np.asarray(point) - np.asarray(candidate)))
            <= tolerance
        )

    def endpoint_degree(point: Sequence[float]) -> int:
        return sum(
            endpoint_matches(point, edge["samples_3d"][0])
            + endpoint_matches(point, edge["samples_3d"][-1])
            for edge in edges
        )

    contours = []
    while unused:
        first_index = min(unused)
        first = by_index[first_index]
        reverse = False
        if (
            endpoint_degree(first["samples_3d"][0]) == 2
            and endpoint_degree(first["samples_3d"][-1]) != 2
        ):
            reverse = True
        elif endpoint_degree(first["samples_3d"][0]) == endpoint_degree(
            first["samples_3d"][-1]
        ):
            reverse = tuple(first["samples_3d"][-1]) < tuple(first["samples_3d"][0])
        ordered: list[tuple[dict[str, Any], bool]] = [(first, reverse)]
        unused.remove(first_index)
        end = (first["samples_3d"][::-1] if reverse else first["samples_3d"])[-1]
        while unused:
            matches = []
            for index in sorted(unused):
                candidate = by_index[index]
                if endpoint_matches(end, candidate["samples_3d"][0]):
                    matches.append((index, False))
                elif endpoint_matches(end, candidate["samples_3d"][-1]):
                    matches.append((index, True))
            if not matches:
                break
            index, reverse = min(matches)
            candidate = by_index[index]
            ordered.append((candidate, reverse))
            unused.remove(index)
            end = (
                candidate["samples_3d"][::-1] if reverse else candidate["samples_3d"]
            )[-1]
        points_3d: list[list[float]] = []
        ordered_indices = []
        exact_length = 0.0
        for edge, reverse in ordered:
            samples = edge["samples_3d"][::-1] if reverse else edge["samples_3d"]
            points_3d.extend(samples if not points_3d else samples[1:])
            ordered_indices.append(edge["index"])
            exact_length += edge["length_exact"]
        closed = len(points_3d) > 2 and endpoint_matches(points_3d[0], points_3d[-1])
        if closed:
            points_3d[-1] = points_3d[0]
        points_2d = [
            _plane_coordinates(point, origin, x_axis, y_axis) for point in points_3d
        ]
        contours.append(
            {
                "index": len(contours),
                "edge_indices": ordered_indices,
                "closed": closed,
                "samples_3d": points_3d,
                "samples_2d": points_2d,
                "length_exact": exact_length,
                "length_sampled": _sample_length(points_3d),
                "area": _polygon_area(points_2d) if closed else None,
            }
        )
    return contours


def _section_source(
    model: BRepModel, face_ids: Sequence[str] | None
) -> tuple[TopoDS_Shape, list[str] | None]:
    if face_ids is None:
        return (model._material_union() if model.bodies else model.root), None
    if not face_ids:
        raise ValueError("face_ids must not be empty")
    canonical_ids: list[str] = []
    faces: list[TopoDS_Face] = []
    for entity_id in face_ids:
        canonical, kind, _, shape = _canonical_id(model, entity_id)
        if kind != "face":
            raise BRepEntityError("face_ids must identify faces")
        if canonical not in canonical_ids:
            canonical_ids.append(canonical)
            faces.append(TopoDS.Face_s(shape))
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for face in faces:
        builder.Add(compound, face)
    return compound, canonical_ids


def inspect_section_rdescriptor(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    origin: Sequence[float],
    normal: Sequence[float],
    tolerance: float = 1.0e-7,
    samples_per_edge: int = 16,
    connection_tolerance: float | None = None,
    compact: bool = False,
    face_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Intersect a model or selected faces with a plane and assemble contours."""
    result, _ = _inspect_section_geometry(
        model_or_path, origin, normal, tolerance, samples_per_edge,
        connection_tolerance, compact, face_ids,
    )
    return result


def _inspect_section_geometry(
    model_or_path, origin, normal, tolerance=1.0e-7, samples_per_edge=16,
    connection_tolerance=None, compact=False, face_ids=None,
):
    """Internal descriptor plus the exact edges used by its contour IDs."""
    _require_positive(tolerance, "tolerance")
    connection_tolerance_value = (
        tolerance if connection_tolerance is None else float(connection_tolerance)
    )
    _require_positive(connection_tolerance_value, "connection_tolerance")
    if samples_per_edge < 4:
        raise ValueError("samples_per_edge must be at least four")
    model = _model(model_or_path)
    plane_origin = _point(origin, "origin")
    plane_normal = _point(normal, "normal")
    basis_origin, x_axis, y_axis = _plane_basis(plane_origin, plane_normal)
    plane = gp_Pln(gp_Pnt(*basis_origin), gp_Dir(*plane_normal))
    source, scope_face_ids = _section_source(model, face_ids)
    section = BRepAlgoAPI_Section(source, plane, False)
    section.SetNonDestructive(True)
    section.SetFuzzyValue(tolerance)
    section.Build()
    if not section.IsDone():
        raise BRepEntityError("OpenCascade section operation failed")
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(section.Shape(), TopAbs_EDGE, edge_map)
    edges = []
    edge_shapes = {}
    for index in range(1, edge_map.Extent() + 1):
        edge = TopoDS.Edge_s(edge_map.FindKey(index))
        if BRep_Tool.Degenerated_s(edge):
            continue
        samples = _sample_edge(edge, samples_per_edge)
        if len(samples) < 2:
            continue
        edge_shapes[index - 1] = edge
        edges.append(
            {
                "index": index - 1,
                "samples_3d": samples,
                "samples_2d": [
                    _plane_coordinates(point, basis_origin, x_axis, y_axis)
                    for point in samples
                ],
                "length_exact": _linear_length(edge),
                "length_sampled": _sample_length(samples),
            }
        )
    contours = _section_contours(
        edges,
        connection_tolerance_value,
        basis_origin,
        x_axis,
        y_axis,
    )
    material_area = _classify_closed_contours(contours)
    result = {
        "plane": {
            "origin": basis_origin.tolist(),
            "normal": (plane_normal / np.linalg.norm(plane_normal)).tolist(),
            "x_direction": x_axis.tolist(),
            "y_direction": y_axis.tolist(),
        },
        "scope": {"face_ids": scope_face_ids},
        "tolerance": tolerance,
        "connection_tolerance": connection_tolerance_value,
        "edges": edges,
        "contours": contours,
        "edge_count": len(edges),
        "closed_contour_count": sum(contour["closed"] for contour in contours),
        "open_contour_count": sum(not contour["closed"] for contour in contours),
        "total_closed_area": float(sum(contour["area"] or 0.0 for contour in contours)),
        "material_area": material_area,
    }
    if compact:
        result["compact"] = True
        result["edges"] = [
            {
                "index": edge["index"],
                "start": edge["samples_3d"][0],
                "end": edge["samples_3d"][-1],
                "length_exact": edge["length_exact"],
            }
            for edge in edges
        ]
        result["contours"] = [
            {
                key: contour[key]
                for key in (
                    "index",
                    "edge_indices",
                    "closed",
                    "length_exact",
                    "area",
                    "nesting_depth",
                    "role",
                )
                if key in contour
            }
            for contour in contours
        ]
    return result, edge_shapes


def _wire_edges(wire: TopoDS_Wire, face: TopoDS_Face) -> Iterable[TopoDS_Edge]:
    explorer = BRepTools_WireExplorer(wire, face)
    while explorer.More():
        yield TopoDS.Edge_s(explorer.Current())
        explorer.Next()


def _sample_pcurve(
    edge: TopoDS_Edge, face: TopoDS_Face, samples_per_edge: int
) -> list[list[float]] | None:
    if BRep_Tool.Degenerated_s(edge):
        return None
    first, last = BRep_Tool.Range_s(edge, face)
    curve = BRep_Tool.CurveOnSurface_s(edge, face, first, last)
    if curve is None:
        return None
    parameters = np.linspace(float(first), float(last), samples_per_edge)
    if edge.Orientation() == TopAbs_REVERSED:
        parameters = parameters[::-1]
    return [
        [
            float(curve.Value(float(parameter)).X()),
            float(curve.Value(float(parameter)).Y()),
        ]
        for parameter in parameters
    ]


def inspect_face_boundaries_rdescriptor(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    face_id: str,
    samples_per_edge: int = 16,
    compact: bool = False,
    include_curve_definitions: bool = False,
    curve_definition_edge_ids: Sequence[str] | None = None,
    max_total_control_points: int = 256,
) -> dict[str, Any]:
    """Return ordered outer and inner wire occurrences for one stable face id."""
    if samples_per_edge < 2:
        raise ValueError("samples_per_edge must be at least two")
    if max_total_control_points < 1:
        raise ValueError("max_total_control_points must be at least one")
    if include_curve_definitions and not compact:
        raise ValueError("Curve definitions require compact=True")
    if curve_definition_edge_ids is not None and not include_curve_definitions:
        raise ValueError(
            "curve_definition_edge_ids requires include_curve_definitions=True"
        )
    model = _model(model_or_path)
    canonical, kind, _, shape = _canonical_id(model, face_id)
    if kind != "face":
        raise BRepEntityError("face_id must identify a face")
    face = TopoDS.Face_s(shape)
    outer = BRepTools.OuterWire_s(face)
    wires = []
    explorer = TopExp_Explorer(face, TopAbs_WIRE)
    while explorer.More():
        wire = TopoDS.Wire_s(explorer.Current())
        wires.append(wire)
        explorer.Next()
    ordered_wires = [outer] + [wire for wire in wires if not wire.IsSame(outer)]
    boundary_edge_ids = {
        model.id_for_shape("edge", edge)
        for wire in ordered_wires
        for edge in _wire_edges(wire, face)
    }

    selected_definition_ids: list[str] = []
    if include_curve_definitions:
        if curve_definition_edge_ids is None:
            selected_definition_ids = sorted(boundary_edge_ids, key=_entity_key)
        else:
            selected = set()
            for entity_id in curve_definition_edge_ids:
                canonical_edge, edge_kind, _, _ = _canonical_id(model, entity_id)
                if edge_kind != "edge":
                    raise BRepEntityError(
                        "curve_definition_edge_ids must identify edges"
                    )
                if canonical_edge not in boundary_edge_ids:
                    raise BRepEntityError(
                        f"{canonical_edge} is not a boundary edge of {canonical}"
                    )
                selected.add(canonical_edge)
            selected_definition_ids = sorted(selected, key=_entity_key)

    total_control_points = 0
    for edge_id in selected_definition_ids:
        _, _, edge_shape = model.resolve_entity(edge_id)
        edge = TopoDS.Edge_s(edge_shape)
        if _curve_type(edge) in {"BEZIER", "BSPLINE"}:
            total_control_points += int(BRepAdaptor_Curve(edge).NbPoles())
    if total_control_points > max_total_control_points:
        raise BRepEntityError(
            "Selected curve definitions contain "
            f"{total_control_points} control points; maximum is "
            f"{max_total_control_points}"
        )

    def describe_wire(wire, role: str, loop_index: int) -> dict[str, Any]:
        edges = []
        loop_points: list[list[float]] = []
        for occurrence_index, edge in enumerate(_wire_edges(wire, face)):
            edge_id = model.id_for_shape("edge", edge)
            samples = _sample_edge(edge, samples_per_edge)
            orientation = str(edge.Orientation()).split(".")[-1].removeprefix("TopAbs_")
            length_exact = _linear_length(edge)
            if compact:
                geometry = model.describe_entity(edge_id)["geometry"]
                parameters = geometry.get("parameters", {})
                key_parameters = {
                    name: parameters[name]
                    for name in (
                        "radius",
                        "major_radius",
                        "minor_radius",
                        "degree",
                        "pole_count",
                        "knot_count",
                        "periodic",
                        "direction",
                        "axis_direction",
                    )
                    if name in parameters
                }
                edges.append(
                    {
                        "occurrence_index": occurrence_index,
                        "entity_id": edge_id,
                        "orientation": orientation,
                        "geometry_type": geometry["type"],
                        "degenerated": bool(BRep_Tool.Degenerated_s(edge)),
                        "length_exact": length_exact,
                        "start": samples[0] if samples else geometry.get("start"),
                        "end": samples[-1] if samples else geometry.get("end"),
                        "parameters": key_parameters,
                    }
                )
            else:
                edges.append(
                    {
                        "occurrence_index": occurrence_index,
                        "entity_id": edge_id,
                        "orientation": orientation,
                        "degenerated": bool(BRep_Tool.Degenerated_s(edge)),
                        "samples_3d": samples,
                        "length_exact": length_exact,
                        "length_sampled": _sample_length(samples),
                        "uv_samples": _sample_pcurve(edge, face, samples_per_edge),
                    }
                )
            if samples:
                loop_points.extend(samples if not loop_points else samples[1:])
        result = {
            "index": loop_index,
            "role": role,
            "closed": bool(BRep_Tool.IsClosed_s(wire)),
            "edges": edges,
            "length_exact": sum(edge["length_exact"] for edge in edges),
        }
        if compact:
            result["geometry_type_counts"] = dict(
                sorted(Counter(edge["geometry_type"] for edge in edges).items())
            )
        else:
            result["length_sampled"] = _sample_length(loop_points)
        return result

    outer_loop = describe_wire(ordered_wires[0], "outer", 0) if ordered_wires else None
    inner_loops = [
        describe_wire(wire, "inner", index)
        for index, wire in enumerate(ordered_wires[1:])
    ]
    result = {
        "face": canonical,
        "outer": outer_loop,
        "inner": inner_loops,
        "inner_loop_count": len(inner_loops),
        "compact": bool(compact),
    }
    if include_curve_definitions:
        definitions = {}
        for edge_id in selected_definition_ids:
            _, _, edge_shape = model.resolve_entity(edge_id)
            edge = TopoDS.Edge_s(edge_shape)
            geometry_type = _curve_type(edge)
            definition_available = _curve_definition_available(geometry_type)
            definitions[edge_id] = {
                "available": definition_available,
                "geometry_type": geometry_type,
                "definition": (
                    _curve_parameters(edge, include_definition=True)
                    if definition_available
                    else None
                ),
            }
        result["curve_definitions"] = {
            "selection": (
                "all_boundary_edges"
                if curve_definition_edge_ids is None
                else "selected_boundary_edges"
            ),
            "edge_ids": selected_definition_ids,
            "total_control_points": total_control_points,
            "max_total_control_points": max_total_control_points,
            "definitions": definitions,
        }
    return result


def inspect_point_rdescriptor(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    point: Sequence[float],
    entity_kinds: Sequence[str] = ("face", "edge", "vertex"),
    limit: int = 20,
) -> dict[str, Any]:
    """Return exact point-to-entity distances, ordered by distance then stable id."""
    if limit < 1:
        raise ValueError("limit must be at least one")
    model = _model(model_or_path)
    probe = _point(point, "point")
    kinds = tuple(entity_kinds)
    if not kinds:
        raise ValueError("entity_kinds must not be empty")
    invalid = sorted(set(kinds).difference(ENTITY_KINDS))
    if invalid:
        raise ValueError(f"Unsupported entity kinds: {', '.join(invalid)}")
    vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*probe)).Vertex()
    candidates = []
    for kind in ENTITY_KINDS:
        if kind not in kinds:
            continue
        for index, entity in enumerate(model.entity_list(kind)):
            bounds = _bounding_box(entity)
            minimum = np.asarray(bounds["min"], dtype=float)
            maximum = np.asarray(bounds["max"], dtype=float)
            nearest = np.maximum(minimum, np.minimum(probe, maximum))
            candidates.append(
                (
                    float(np.linalg.norm(nearest - probe)),
                    _entity_key(f"{kind}:{index}"),
                    kind,
                    index,
                    entity,
                )
            )
    candidates.sort(key=lambda item: (item[0], item[1]))

    hits = []
    exact_evaluations = 0
    for lower_bound, _, kind, index, entity in candidates:
        if len(hits) >= limit and lower_bound > hits[-1]["distance"]:
            break
        distance, closest = _distance(vertex, entity)
        exact_evaluations += 1
        hits.append(
            {
                "entity_id": f"{kind}:{index}",
                "kind": kind,
                "distance": distance,
                "closest_point": closest[0]["second"] if closest else None,
            }
        )
        hits.sort(key=lambda hit: (hit["distance"], _entity_key(hit["entity_id"])))
        if len(hits) > limit:
            hits.pop()
    for hit in hits:
        hit["descriptor"] = model.describe_entity(hit["entity_id"])
    return {
        "point": probe.tolist(),
        "entity_kinds": list(kinds),
        "limit": limit,
        "hits": hits,
        "candidate_count": len(candidates),
        "exact_distance_evaluation_count": exact_evaluations,
        "bbox_pruned_count": len(candidates) - exact_evaluations,
        "truncated": len(candidates) > len(hits),
    }


def select_region_entities_rdescriptor(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    entity_ids: Sequence[str] | None = None,
    center: Sequence[float] | None = None,
    radius: float | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    """Expand stable ids through topology and optionally filter them by bounds distance."""
    _require_nonnegative(depth, "depth")
    if (center is None) != (radius is None):
        raise ValueError("center and radius must be provided together")
    if radius is not None:
        _require_nonnegative(radius, "radius")
    model = _model(model_or_path)
    if entity_ids is None:
        selected = {
            f"{kind}:{index}"
            for kind in ENTITY_KINDS
            for index in range(len(model.entity_list(kind)))
        }
    else:
        selected = {_canonical_id(model, entity_id)[0] for entity_id in entity_ids}
    frontier = set(selected)
    for _ in range(depth):
        frontier = {
            neighbor
            for entity in frontier
            for neighbor in model.direct_neighbors(entity)
        }
        selected.update(frontier)
    center_array = _point(center, "center") if center is not None else None
    retained = []
    bounds = []
    for entity in sorted(selected, key=_entity_key):
        descriptor = model.describe_entity(entity)
        box = descriptor["bounding_box"]
        minimum, maximum = np.asarray(box["min"]), np.asarray(box["max"])
        if center_array is not None:
            nearest = np.maximum(minimum, np.minimum(center_array, maximum))
            if float(np.linalg.norm(nearest - center_array)) > radius:
                continue
        retained.append(entity)
        bounds.append((minimum, maximum))
    if bounds:
        minimum = np.min([item[0] for item in bounds], axis=0).tolist()
        maximum = np.max([item[1] for item in bounds], axis=0).tolist()
    else:
        minimum = maximum = None
    return {
        "entity_ids": retained,
        "depth": depth,
        "center": center_array.tolist() if center_array is not None else None,
        "radius": radius,
        "bounds": {"min": minimum, "max": maximum} if minimum is not None else None,
    }


__all__ = [
    "inspect_face_boundaries_rdescriptor",
    "inspect_topology_neighborhood_rdescriptor",
    "inspect_section_rdescriptor",
    "measure_entity_relation_rdescriptor",
    "inspect_point_rdescriptor",
    "select_region_entities_rdescriptor",
]
