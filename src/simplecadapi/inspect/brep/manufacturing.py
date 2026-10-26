"""Geometry-only manufacturing feature hints for indexed BREP models."""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHAPE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape

from .model import (
    BRepModel,
    _bounding_box,
    index_shape_rbrepmodel,
    load_step_rbrepmodel,
)
from .feature_hints import (
    extrusion_hints,
    hole_hints,
    loft_hints,
    revolution_hints,
    sweep_hints,
)
from .feature_hints.section_families import (
    local_section_families,
    whole_body_point_families,
    whole_body_section_families,
)


ModelInput = BRepModel | TopoDS_Shape | str | Path
FEATURE_KINDS = ("fillet", "chamfer", "sheet_metal")
_SUPPORTED_FEATURE_KINDS = FEATURE_KINDS + (
    "hole",
    "extrusion",
    "revolution",
    "loft",
    "sweep",
)


def _model(value: ModelInput) -> BRepModel:
    if isinstance(value, BRepModel):
        return value
    if isinstance(value, TopoDS_Shape):
        return index_shape_rbrepmodel(value)
    if isinstance(value, (str, Path)):
        return load_step_rbrepmodel(value)
    raise TypeError("model_or_path must be a BRepModel, TopoDS_Shape, or STEP path")


def _entity_index(entity_id: str) -> int:
    return int(entity_id.split(":", 1)[1])


def _unit(values: Sequence[float]) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    magnitude = float(np.linalg.norm(result))
    if magnitude <= 1.0e-15:
        raise ValueError("direction must be non-zero")
    return result / magnitude


def _angle_degrees(first: Sequence[float], second: Sequence[float]) -> float:
    cosine = float(np.dot(_unit(first), _unit(second)))
    return math.degrees(math.acos(min(1.0, max(-1.0, abs(cosine)))))


def _axes_coaxial(
    first: dict[str, Any],
    second: dict[str, Any],
    linear_tolerance: float,
    angular_tolerance_degrees: float,
) -> bool:
    first_direction = _unit(first["direction"])
    second_direction = _unit(second["direction"])
    if _angle_degrees(first_direction, second_direction) > angular_tolerance_degrees:
        return False
    offset = np.asarray(second["point"], dtype=float) - np.asarray(
        first["point"], dtype=float
    )
    cross = np.cross(first_direction, second_direction)
    cross_magnitude = float(np.linalg.norm(cross))
    distance = (
        abs(float(np.dot(offset, cross))) / cross_magnitude
        if cross_magnitude > 1.0e-12
        else float(np.linalg.norm(np.cross(offset, first_direction)))
    )
    return distance <= linear_tolerance


def _axis_descriptor(axis: dict[str, Any]) -> dict[str, list[float]]:
    direction = _unit(axis["direction"])
    first_nonzero = next(
        (value for value in direction if abs(float(value)) > 1.0e-12), 1.0
    )
    if first_nonzero < 0.0:
        direction = -direction
    point = np.asarray(axis["point"], dtype=float)
    closest = point - np.dot(point, direction) * direction
    return {
        "point": [round(float(value), 9) for value in closest],
        "direction": [round(float(value), 9) for value in direction],
    }


def _shape_distance(first: TopoDS_Shape, second: TopoDS_Shape) -> float:
    operation = BRepExtrema_DistShapeShape(first, second)
    operation.Perform()
    if not operation.IsDone():
        raise ValueError("OpenCascade could not measure candidate skin separation")
    return float(operation.Value())


def _cylinder_radial_direction(fact: dict[str, Any]) -> np.ndarray | None:
    axis = fact["parameters"]["axis"]
    direction = _unit(axis["direction"])
    offset = fact["centroid"] - np.asarray(axis["point"], dtype=float)
    radial = offset - np.dot(offset, direction) * direction
    magnitude = float(np.linalg.norm(radial))
    if magnitude <= 1.0e-9:
        return None
    return radial / magnitude


def _cylinder_material_side(fact: dict[str, Any]) -> int:
    radial = _cylinder_radial_direction(fact)
    if radial is not None and fact["normal"] is not None:
        dot = float(np.dot(fact["normal"], radial))
        if abs(dot) > 0.5:
            return 1 if dot > 0.0 else -1
    return 1 if fact["shape"].Orientation().name.endswith("FORWARD") else -1


def _cylinder_trim_overlap(
    first: dict[str, Any],
    second: dict[str, Any],
    linear_tolerance: float,
    angular_tolerance: float,
    expected_separation: float,
) -> bool:
    first_axis = first["parameters"]["axis"]
    direction = _unit(first_axis["direction"])
    first_projection = float(np.dot(first["centroid"], direction))
    second_projection = float(np.dot(second["centroid"], direction))
    first_v = first["parameters"]["v_range"]
    second_v = second["parameters"]["v_range"]
    first_length = abs(float(first_v[1]) - float(first_v[0]))
    second_length = abs(float(second_v[1]) - float(second_v[0]))
    if abs(first_projection - second_projection) > max(
        linear_tolerance,
        1.0e-4 * max(first_length, second_length, 1.0),
    ):
        return False
    first_u = first["parameters"]["u_range"]
    second_u = second["parameters"]["u_range"]
    first_sweep = abs(float(first_u[1]) - float(first_u[0]))
    second_sweep = abs(float(second_u[1]) - float(second_u[0]))
    if abs(first_sweep - second_sweep) > max(1.0e-4, math.radians(angular_tolerance)):
        return False
    first_radial = _cylinder_radial_direction(first)
    second_radial = _cylinder_radial_direction(second)
    if first_radial is None or second_radial is None:
        angular_overlap = min(first_sweep, second_sweep) >= 2.0 * math.pi - 1.0e-4
    else:
        cosine = float(np.dot(first_radial, second_radial))
        angle = math.degrees(math.acos(min(1.0, max(-1.0, cosine))))
        angular_overlap = angle <= angular_tolerance
    if not angular_overlap:
        return False
    actual_separation = _shape_distance(first["shape"], second["shape"])
    return abs(actual_separation - expected_separation) <= max(
        10.0 * linear_tolerance,
        1.0e-5 * max(expected_separation, 1.0),
    )


def _confidence(level: str, support: float, evaluated: float = 1.0) -> dict[str, Any]:
    return {
        "level": level,
        "support_fraction": float(support),
        "evaluated_fraction": float(evaluated),
        "calibrated_probability": False,
    }


def _evidence(
    code: str,
    outcome: str,
    *,
    observed: dict[str, Any] | None = None,
    criterion: dict[str, Any] | None = None,
    entity_ids: Sequence[str] = (),
    required: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "outcome": outcome,
        "required": required,
        "entity_ids": list(entity_ids),
        "observed": observed or {},
        "criterion": criterion or {},
    }


def _effective_tolerances(
    model: BRepModel,
    tolerance: float | None,
    angular_tolerance_degrees: float,
) -> dict[str, float | str]:
    if tolerance is not None and (not math.isfinite(tolerance) or tolerance <= 0.0):
        raise ValueError("tolerance must be finite and greater than zero")
    if (
        not math.isfinite(angular_tolerance_degrees)
        or angular_tolerance_degrees < 0.0
        or angular_tolerance_degrees >= 90.0
    ):
        raise ValueError(
            "angular_tolerance_degrees must be finite and in the range [0, 90)"
        )
    bounds = _bounding_box(model.root)
    analysis = ShapeAnalysis_ShapeTolerance()
    maximum = float(analysis.Tolerance(model.root, 1, TopAbs_SHAPE))
    if not math.isfinite(maximum) or maximum < 0.0:
        maximum = 0.0
    derived = max(maximum, float(bounds["diagonal"]) * 1.0e-9, 1.0e-9)
    linear = max(float(tolerance), derived) if tolerance is not None else derived
    radius = max(20.0 * linear, float(bounds["diagonal"]) * 1.0e-7)
    if not all(math.isfinite(value) for value in (linear, radius)):
        raise ValueError("tolerance is too large to derive finite feature tolerances")
    return {
        "linear": linear,
        "radius": radius,
        "thickness": radius,
        "angular_degrees": float(angular_tolerance_degrees),
        "maximum_entity_tolerance": maximum,
        "source": "user_and_derived" if tolerance is not None else "derived",
    }


def _face_facts(model: BRepModel) -> dict[str, dict[str, Any]]:
    facts = {}
    for index, face in enumerate(model.faces):
        entity_id = f"face:{index}"
        descriptor = model.describe_entity(entity_id)
        geometry = descriptor["geometry"]
        normal = geometry.get("normal_at_center")
        facts[entity_id] = {
            "entity_id": entity_id,
            "shape": face,
            "type": geometry["type"],
            "area": float(geometry["area"]),
            "centroid": np.asarray(geometry["centroid"], dtype=float),
            "normal": _unit(normal) if normal is not None else None,
            "parameters": geometry["parameters"],
            "edges": descriptor["adjacency"]["edges"],
            "neighbors": descriptor["adjacency"]["neighboring_faces"],
        }
    return facts


def _body_closed_manifold(body: TopoDS_Shape) -> bool:
    if not BRepCheck_Analyzer(body).IsValid():
        return False
    edges = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(body, TopAbs_EDGE, edges)
    edge_uses = [0] * edges.Extent()
    face_explorer = TopExp_Explorer(body, TopAbs_FACE)
    while face_explorer.More():
        edge_explorer = TopExp_Explorer(face_explorer.Current(), TopAbs_EDGE)
        while edge_explorer.More():
            edge = edge_explorer.Current()
            edge_index = edges.FindIndex(edge) - 1
            if edge_index >= 0:
                edge_uses[edge_index] += 1
            edge_explorer.Next()
        face_explorer.Next()
    return bool(edge_uses) and all(
        count == 2 or BRep_Tool.Degenerated_s(TopoDS.Edge_s(edges.FindKey(index + 1)))
        for index, count in enumerate(edge_uses)
    )


def _plane_pair_candidates(
    face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    angular_tolerance: float,
    linear_tolerance: float,
) -> list[dict[str, Any]]:
    planes = [
        face_id
        for face_id in face_ids
        if facts[face_id]["type"] == "PLANE" and facts[face_id]["normal"] is not None
    ]
    cosine_limit = math.cos(math.radians(angular_tolerance))
    candidates = []
    for offset, first_id in enumerate(planes):
        first = facts[first_id]
        first_normal = first["normal"]
        for second_id in planes[offset + 1 :]:
            second = facts[second_id]
            dot = float(np.dot(first_normal, second["normal"]))
            if dot > -cosine_limit:
                continue
            area_similarity = min(first["area"], second["area"]) / max(
                first["area"], second["area"], 1.0e-15
            )
            if area_similarity < 0.70:
                continue
            thickness = abs(
                float(np.dot(second["centroid"] - first["centroid"], first_normal))
            )
            if thickness <= linear_tolerance:
                continue
            centroid_delta = second["centroid"] - first["centroid"]
            projected = (
                centroid_delta - np.dot(centroid_delta, first_normal) * first_normal
            )
            characteristic = math.sqrt(max(first["area"], second["area"], 1.0e-15))
            projected_ratio = float(np.linalg.norm(projected)) / characteristic
            if projected_ratio > 0.20:
                continue
            actual_separation = _shape_distance(first["shape"], second["shape"])
            if abs(actual_separation - thickness) > max(
                10.0 * linear_tolerance,
                1.0e-5 * max(thickness, 1.0),
            ):
                continue
            candidates.append(
                {
                    "kind": "plane",
                    "face_ids": [first_id, second_id],
                    "thickness": thickness,
                    "boundary_area": first["area"] + second["area"],
                    "midsurface_area": 0.5 * (first["area"] + second["area"]),
                    "area_similarity": area_similarity,
                    "projected_centroid_ratio": projected_ratio,
                    "score": area_similarity - projected_ratio,
                }
            )
    return _greedy_pairs(candidates)


def _cylinder_pair_candidates(
    face_ids: Sequence[str],
    facts: dict[str, dict[str, Any]],
    angular_tolerance: float,
    linear_tolerance: float,
    radius_tolerance: float,
) -> list[dict[str, Any]]:
    cylinders = [
        face_id for face_id in face_ids if facts[face_id]["type"] == "CYLINDER"
    ]
    candidates = []
    for offset, first_id in enumerate(cylinders):
        first = facts[first_id]
        first_radius = float(first["parameters"]["radius"])
        first_axis = first["parameters"]["axis"]
        for second_id in cylinders[offset + 1 :]:
            second = facts[second_id]
            second_axis = second["parameters"]["axis"]
            if not _axes_coaxial(
                first_axis,
                second_axis,
                linear_tolerance,
                angular_tolerance,
            ):
                continue
            if _cylinder_material_side(first) == _cylinder_material_side(second):
                continue
            second_radius = float(second["parameters"]["radius"])
            thickness = abs(first_radius - second_radius)
            if thickness <= radius_tolerance:
                continue
            normalized_areas = (
                first["area"] / first_radius,
                second["area"] / second_radius,
            )
            span_similarity = min(normalized_areas) / max(*normalized_areas, 1.0e-15)
            if span_similarity < 0.90:
                continue
            if not _cylinder_trim_overlap(
                first,
                second,
                linear_tolerance,
                angular_tolerance,
                thickness,
            ):
                continue
            first_u = first["parameters"]["u_range"]
            second_u = second["parameters"]["u_range"]
            first_v = first["parameters"]["v_range"]
            second_v = second["parameters"]["v_range"]
            first_sweep = abs(float(first_u[1]) - float(first_u[0]))
            second_sweep = abs(float(second_u[1]) - float(second_u[0]))
            first_length = abs(float(first_v[1]) - float(first_v[0]))
            second_length = abs(float(second_v[1]) - float(second_v[0]))
            if abs(first_length - second_length) > max(
                linear_tolerance,
                1.0e-4 * max(first_length, second_length, 1.0),
            ):
                continue
            sweep_degrees = math.degrees(0.5 * (first_sweep + second_sweep))
            bend_length = 0.5 * (first_length + second_length)
            inside_id, outside_id = (
                (first_id, second_id)
                if first_radius < second_radius
                else (second_id, first_id)
            )
            inside_radius, outside_radius = sorted((first_radius, second_radius))
            candidates.append(
                {
                    "kind": "cylinder",
                    "face_ids": [inside_id, outside_id],
                    "inside_face_id": inside_id,
                    "outside_face_id": outside_id,
                    "inside_radius": inside_radius,
                    "outside_radius": outside_radius,
                    "mid_radius": 0.5 * (inside_radius + outside_radius),
                    "thickness": thickness,
                    "boundary_area": first["area"] + second["area"],
                    "midsurface_area": 0.5 * (first["area"] + second["area"]),
                    "span_similarity": span_similarity,
                    "sweep_angle_degrees": sweep_degrees,
                    "bend_length": bend_length,
                    "axis": _axis_descriptor(first_axis),
                    "score": span_similarity,
                }
            )
    return _greedy_pairs(candidates)


def _greedy_pairs(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    used = set()
    for candidate in sorted(
        candidates,
        key=lambda item: (
            -float(item["score"]),
            float(item["thickness"]),
            tuple(_entity_index(value) for value in item["face_ids"]),
        ),
    ):
        if any(face_id in used for face_id in candidate["face_ids"]):
            continue
        selected.append(candidate)
        used.update(candidate["face_ids"])
    return selected


def _thickness_clusters(
    pairs: Sequence[dict[str, Any]], thickness_tolerance: float
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for pair in sorted(pairs, key=lambda item: item["thickness"]):
        match = next(
            (
                cluster
                for cluster in clusters
                if abs(float(pair["thickness"]) - float(cluster["thickness"]))
                <= max(
                    thickness_tolerance,
                    1.0e-4 * max(float(pair["thickness"]), float(cluster["thickness"])),
                )
            ),
            None,
        )
        if match is None:
            clusters.append(
                {
                    "thickness": float(pair["thickness"]),
                    "pairs": [pair],
                    "weight": float(pair["boundary_area"]),
                }
            )
            continue
        total = float(match["weight"]) + float(pair["boundary_area"])
        match["thickness"] = (
            float(match["thickness"]) * float(match["weight"])
            + float(pair["thickness"]) * float(pair["boundary_area"])
        ) / total
        match["weight"] = total
        match["pairs"].append(pair)
    return sorted(clusters, key=lambda item: (-item["weight"], item["thickness"]))


def _continuity_name(value: Any) -> str:
    return str(value).rsplit(".", 1)[-1].removeprefix("GeomAbs_")


def _is_tangent_continuity(value: Any) -> bool:
    return _continuity_name(value) in {"G1", "G2", "C1", "C2", "C3", "CN"}


def _fillet_hints(
    model: BRepModel,
    facts: dict[str, dict[str, Any]],
    excluded_face_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_face_ids = excluded_face_ids or set()
    hints = []
    for body_index in range(len(model.bodies)):
        body_id = f"body:{body_index}"
        body_faces = set(model.adjacency_details(body_id)["faces"])
        for face_id in sorted(body_faces, key=_entity_index):
            fact = facts[face_id]
            if face_id in excluded_face_ids or fact["type"] not in {
                "CYLINDER",
                "TORUS",
                "SPHERE",
            }:
                continue
            tangent_supports = set()
            tangent_edges = []
            end_edges = []
            face = TopoDS.Face_s(fact["shape"])
            for edge_id in fact["edges"]:
                _, _, edge_shape = model.resolve_entity(edge_id)
                neighbors = [
                    value
                    for value in model.adjacency_details(edge_id)["faces"]
                    if value != face_id and value in body_faces
                ]
                tangent = False
                for neighbor_id in neighbors:
                    neighbor = TopoDS.Face_s(facts[neighbor_id]["shape"])
                    try:
                        continuity = BRep_Tool.Continuity_s(
                            TopoDS.Edge_s(edge_shape), face, neighbor
                        )
                    except Exception:
                        continue
                    if _is_tangent_continuity(continuity):
                        tangent = True
                        tangent_supports.add(neighbor_id)
                (tangent_edges if tangent else end_edges).append(edge_id)
            if len(tangent_supports) < 2 or any(
                facts[support_id]["type"] == fact["type"]
                for support_id in tangent_supports
            ):
                continue
            if (
                fact["type"] == "CYLINDER"
                and sum(
                    facts[support_id]["type"] == "PLANE"
                    for support_id in tangent_supports
                )
                < 2
            ):
                continue
            parameters = fact["parameters"]
            radius = (
                parameters.get("radius")
                if fact["type"] in {"CYLINDER", "SPHERE"}
                else parameters.get("minor_radius")
            )
            u_range = parameters.get("u_range") or []
            v_range = parameters.get("v_range") or []
            sweep_angle = (
                math.degrees(abs(float(u_range[1]) - float(u_range[0])))
                if len(u_range) == 2
                else None
            )
            effective_length = None
            if fact["type"] == "CYLINDER" and len(v_range) == 2:
                effective_length = abs(float(v_range[1]) - float(v_range[0]))
            elif fact["type"] == "TORUS" and len(u_range) == 2:
                effective_length = abs(float(u_range[1]) - float(u_range[0])) * float(
                    parameters["major_radius"]
                )
            support_ids = sorted(tangent_supports, key=_entity_index)
            hints.append(
                {
                    "kind": "fillet_region_candidate",
                    "claim": "geometric_candidate",
                    "body_id": body_id,
                    "entity_ids": [face_id],
                    "highlight_entity_ids": [face_id],
                    "support_entity_ids": support_ids,
                    "geometry": {
                        "carrier_type": fact["type"],
                        "radius": float(radius) if radius is not None else None,
                        "major_radius": parameters.get("major_radius"),
                        "surface_area": fact["area"],
                        "effective_length": effective_length,
                        "sweep_angle_degrees": sweep_angle,
                        "axis": parameters.get("axis"),
                        "center": parameters.get("center"),
                        "tangent_boundary_edge_ids": sorted(
                            tangent_edges, key=_entity_index
                        ),
                        "end_boundary_edge_ids": sorted(end_edges, key=_entity_index),
                    },
                    "confidence": _confidence("strong", 1.0),
                    "evidence": [
                        _evidence(
                            "fillet.g1_support_boundaries",
                            "pass",
                            entity_ids=[face_id, *support_ids],
                            observed={"tangent_support_face_count": len(support_ids)},
                            criterion={"minimum": 2},
                        ),
                        _evidence(
                            "fillet.constant_analytic_radius",
                            "pass",
                            entity_ids=[face_id],
                            observed={"radius": radius, "carrier_type": fact["type"]},
                        ),
                    ],
                }
            )
    return hints


def _paired_bend_faces_from_fillet_hints(
    model: BRepModel,
    hints: Sequence[dict[str, Any]],
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> set[str]:
    """Find opposed cylindrical bend skins among supported fillet candidates."""

    bend_faces: set[str] = set()
    body_ids = sorted({hint["body_id"] for hint in hints}, key=_entity_index)
    for body_id in body_ids:
        body_hints = [hint for hint in hints if hint["body_id"] == body_id]
        cylinder_ids = sorted(
            {
                hint["entity_ids"][0]
                for hint in body_hints
                if hint["geometry"]["carrier_type"] == "CYLINDER"
            },
            key=_entity_index,
        )
        if len(cylinder_ids) < 2:
            continue
        body_index = _entity_index(body_id)
        body = model.bodies[body_index]
        body_descriptor = model.describe_entity(body_id)
        body_geometry = body_descriptor["geometry"]
        diagonal = float(body_descriptor["bounding_box"]["diagonal"])
        if not _body_closed_manifold(body):
            continue
        cylinder_pairs = _cylinder_pair_candidates(
            cylinder_ids,
            facts,
            float(tolerances["angular_degrees"]),
            float(tolerances["linear"]),
            float(tolerances["radius"]),
        )
        local_support_ids = sorted(
            {
                support_id
                for hint in body_hints
                if hint["entity_ids"][0] in cylinder_ids
                for support_id in hint["support_entity_ids"]
                if facts[support_id]["type"] == "PLANE"
            },
            key=_entity_index,
        )
        plane_pairs = _plane_pair_candidates(
            local_support_ids,
            facts,
            float(tolerances["angular_degrees"]),
            float(tolerances["linear"]),
        )
        clusters = _thickness_clusters(
            [*plane_pairs, *cylinder_pairs], float(tolerances["thickness"])
        )
        for cluster in clusters:
            thickness = float(cluster["thickness"])
            if thickness / max(diagonal, 1.0e-15) > 0.10:
                continue
            pairs = cluster["pairs"]
            paired_ids = {face_id for pair in pairs for face_id in pair["face_ids"]}
            coverage = sum(facts[face_id]["area"] for face_id in paired_ids) / max(
                float(body_geometry["surface_area"]), 1.0e-15
            )
            if coverage < 0.65:
                continue
            midsurface_area = sum(float(pair["midsurface_area"]) for pair in pairs)
            body_volume = abs(float(body_geometry["volume"]))
            volume_error = abs(thickness * midsurface_area - body_volume) / max(
                body_volume, 1.0e-15
            )
            if volume_error > 0.20:
                continue
            planar_ids = {
                face_id
                for pair in pairs
                if pair["kind"] == "plane"
                for face_id in pair["face_ids"]
            }
            for pair in (pair for pair in pairs if pair["kind"] == "cylinder"):
                adjacent_skins = {
                    neighbor
                    for face_id in pair["face_ids"]
                    for neighbor in facts[face_id]["neighbors"]
                    if neighbor in planar_ids
                }
                if len(adjacent_skins) >= 2:
                    bend_faces.update(pair["face_ids"])
    return bend_faces


def _chamfer_hints(
    model: BRepModel,
    facts: dict[str, dict[str, Any]],
    excluded_face_ids: set[str] | None,
    angular_tolerance: float,
    linear_tolerance: float,
) -> list[dict[str, Any]]:
    excluded_face_ids = excluded_face_ids or set()
    hints = []
    for body_index in range(len(model.bodies)):
        body_id = f"body:{body_index}"
        body_faces = set(model.adjacency_details(body_id)["faces"])
        for face_id in sorted(body_faces, key=_entity_index):
            fact = facts[face_id]
            if face_id in excluded_face_ids:
                continue
            support_ids: list[str] = []
            form = None
            geometry: dict[str, Any] = {"area": fact["area"]}
            edge_lengths = []
            if hasattr(model, "resolve_entity"):
                for edge_id in fact.get("edges", []):
                    try:
                        descriptor = model.describe_entity(edge_id)
                        edge_lengths.append(float(descriptor["geometry"]["length"]))
                    except (KeyError, TypeError, ValueError):
                        continue
            chamfer_length = max(edge_lengths, default=None)
            geometry.update(
                {
                    "length": chamfer_length,
                    "face_width": (
                        fact["area"] / chamfer_length
                        if chamfer_length is not None and chamfer_length > 0.0
                        else None
                    ),
                }
            )
            if (
                fact["type"] == "PLANE"
                and fact["normal"] is not None
                and len(fact.get("edges", ())) >= 4
            ):
                candidates = []
                for neighbor_id in fact["neighbors"]:
                    if neighbor_id not in body_faces:
                        continue
                    neighbor = facts[neighbor_id]
                    if neighbor["type"] != "PLANE" or neighbor["normal"] is None:
                        continue
                    alignment = abs(float(np.dot(fact["normal"], neighbor["normal"])))
                    if 0.10 < alignment < math.cos(math.radians(angular_tolerance)):
                        candidates.append((neighbor_id, alignment, neighbor["area"]))
                for first_index, first in enumerate(candidates):
                    for second in candidates[first_index + 1 :]:
                        if abs(
                            float(
                                np.dot(
                                    facts[first[0]]["normal"],
                                    facts[second[0]]["normal"],
                                )
                            )
                        ) >= math.cos(math.radians(angular_tolerance)):
                            continue
                        if fact["area"] > 0.75 * min(first[2], second[2]):
                            continue
                        support_ids = sorted((first[0], second[0]), key=_entity_index)
                        support_angle = _angle_degrees(
                            facts[first[0]]["normal"], facts[second[0]]["normal"]
                        )
                        geometry.update(
                            {
                                "support_angle_degrees": support_angle,
                                "support_normal_alignments": [first[1], second[1]],
                                "support_setbacks": [None, None],
                            }
                        )
                        form = "planar_bevel"
                        break
                    if form:
                        break
            elif fact["type"] == "CONE":
                planes = []
                cylinders = []
                axis = fact["parameters"].get("axis")
                for neighbor_id in fact["neighbors"]:
                    if neighbor_id not in body_faces:
                        continue
                    neighbor = facts[neighbor_id]
                    if (
                        neighbor["type"] == "PLANE"
                        and axis
                        and neighbor["normal"] is not None
                        and _angle_degrees(neighbor["normal"], axis["direction"])
                        <= angular_tolerance
                    ):
                        planes.append(neighbor_id)
                    elif neighbor["type"] == "CYLINDER" and axis:
                        other_axis = neighbor["parameters"]["axis"]
                        if _axes_coaxial(
                            axis,
                            other_axis,
                            linear_tolerance,
                            angular_tolerance,
                        ):
                            cylinders.append(neighbor_id)
                if planes and cylinders:
                    support_ids = [
                        sorted(cylinders, key=_entity_index)[0],
                        sorted(planes, key=_entity_index)[0],
                    ]
                    geometry.update(
                        {
                            "semi_angle_degrees": fact["parameters"].get(
                                "semi_angle_degrees"
                            ),
                            "reference_radius": fact["parameters"].get(
                                "reference_radius"
                            ),
                            "axis": axis,
                        }
                    )
                    form = "conical_bevel"
            if form is None:
                continue
            hints.append(
                {
                    "kind": "chamfer_region_candidate",
                    "claim": "geometric_candidate",
                    "body_id": body_id,
                    "entity_ids": [face_id],
                    "highlight_entity_ids": [face_id],
                    "support_entity_ids": support_ids,
                    "geometry": {"form": form, **geometry},
                    "confidence": _confidence("moderate", 0.80),
                    "evidence": [
                        _evidence(
                            "chamfer.bridges_distinct_supports",
                            "pass",
                            entity_ids=[face_id, *support_ids],
                            observed={"support_face_count": len(support_ids)},
                            criterion={"minimum": 2},
                        ),
                        _evidence(
                            "chamfer.feature_history",
                            "unknown",
                            entity_ids=[face_id],
                            required=False,
                            observed={"final_brep_geometry_only": True},
                        ),
                    ],
                }
            )
    return hints


def _sheet_metal_hints(
    model: BRepModel,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    hints = []
    bend_face_ids: set[str] = set()
    diagnostics = []
    for body_index, body in enumerate(model.bodies):
        body_id = f"body:{body_index}"
        face_ids = model.adjacency_details(body_id)["faces"]
        planes = _plane_pair_candidates(
            face_ids,
            facts,
            float(tolerances["angular_degrees"]),
            float(tolerances["linear"]),
        )
        cylinders = _cylinder_pair_candidates(
            face_ids,
            facts,
            float(tolerances["angular_degrees"]),
            float(tolerances["linear"]),
            float(tolerances["radius"]),
        )
        clusters = _thickness_clusters(
            [*planes, *cylinders], float(tolerances["thickness"])
        )
        if not clusters:
            continue
        cluster = clusters[0]
        pairs = cluster["pairs"]
        paired_ids = sorted(
            {face_id for pair in pairs for face_id in pair["face_ids"]},
            key=_entity_index,
        )
        planar_ids = sorted(
            {
                face_id
                for pair in pairs
                if pair["kind"] == "plane"
                for face_id in pair["face_ids"]
            },
            key=_entity_index,
        )
        bend_pairs = []
        planar_id_set = set(planar_ids)
        for pair in (pair for pair in pairs if pair["kind"] == "cylinder"):
            adjacent_skins = sorted(
                {
                    neighbor
                    for face_id in pair["face_ids"]
                    for neighbor in facts[face_id]["neighbors"]
                    if neighbor in planar_id_set
                },
                key=_entity_index,
            )
            if len(adjacent_skins) < 2:
                continue
            bend_pairs.append({**pair, "adjacent_skin_face_ids": adjacent_skins})
        body_descriptor = model.describe_entity(body_id)
        body_geometry = body_descriptor["geometry"]
        thickness = float(cluster["thickness"])
        coverage = sum(facts[face_id]["area"] for face_id in paired_ids) / max(
            float(body_geometry["surface_area"]), 1.0e-15
        )
        midsurface_area = sum(float(pair["midsurface_area"]) for pair in pairs)
        volume_estimate = thickness * midsurface_area
        body_volume = abs(float(body_geometry["volume"]))
        volume_error = abs(volume_estimate - body_volume) / max(body_volume, 1.0e-15)
        diagonal = float(body_descriptor["bounding_box"]["diagonal"])
        thinness = thickness / max(diagonal, 1.0e-15)
        closed_manifold = _body_closed_manifold(body)
        thickness_values = [float(pair["thickness"]) for pair in pairs]
        thickness_spread = max(thickness_values) - min(thickness_values)
        checks = {
            "closed_manifold": closed_manifold,
            "opposed_skin_pair": bool(planar_ids or cylinders),
            "paired_area_coverage": coverage >= 0.65,
            "thinness": thinness <= 0.10,
            "volume_model": volume_error <= 0.20,
            "thickness_consistency": thickness_spread
            <= max(
                float(tolerances["thickness"]),
                1.0e-3 * max(thickness, 1.0e-15),
            ),
        }
        if not all(checks.values()):
            if coverage >= 0.35:
                diagnostics.append(
                    {
                        "code": "sheet_metal.candidate_suppressed",
                        "body_id": body_id,
                        "failed_checks": [
                            name for name, passed in checks.items() if not passed
                        ],
                        "observed": {
                            "thickness": thickness,
                            "paired_area_fraction": coverage,
                            "thinness_ratio": thinness,
                            "volume_model_relative_error": volume_error,
                        },
                    }
                )
            continue
        level = (
            "strong"
            if coverage >= 0.80 and volume_error <= 0.05 and thinness <= 0.05
            else "moderate"
        )
        sheet_index = sum(
            hint["kind"] == "sheet_metal_body_candidate" for hint in hints
        )
        sheet_id = f"sheet_metal_body_candidate:{sheet_index}"
        sidewall_ids = sorted(set(face_ids) - set(paired_ids), key=_entity_index)
        hints.append(
            {
                "hint_id": sheet_id,
                "kind": "sheet_metal_body_candidate",
                "claim": "geometric_candidate",
                "body_id": body_id,
                "entity_ids": paired_ids,
                "highlight_entity_ids": paired_ids,
                "support_entity_ids": sidewall_ids,
                "geometry": {
                    "thickness": thickness,
                    "thickness_range": [min(thickness_values), max(thickness_values)],
                    "skin_pairs": [
                        {
                            "kind": pair["kind"],
                            "face_ids": pair["face_ids"],
                            "thickness": pair["thickness"],
                        }
                        for pair in pairs
                    ],
                    "skin_face_ids": paired_ids,
                    "planar_skin_face_ids": planar_ids,
                    "sidewall_or_transition_face_ids": sidewall_ids,
                    "paired_skin_area_fraction": coverage,
                    "thinness_ratio": thinness,
                    "midsurface_area": midsurface_area,
                    "bounding_box_size": list(body_descriptor["bounding_box"]["size"]),
                    "volume_estimate": volume_estimate,
                    "volume_model_relative_error": volume_error,
                    "bend_count": len(bend_pairs),
                    "formed": bool(bend_pairs),
                },
                "confidence": _confidence(level, min(1.0, coverage)),
                "evidence": [
                    _evidence(
                        "sheet_metal.constant_thickness",
                        "pass",
                        entity_ids=paired_ids,
                        observed={
                            "nominal_thickness": thickness,
                            "maximum_spread": thickness_spread,
                        },
                        criterion={
                            "maximum_spread": max(
                                float(tolerances["thickness"]),
                                1.0e-3 * thickness,
                            )
                        },
                    ),
                    _evidence(
                        "sheet_metal.paired_skin_coverage",
                        "pass",
                        entity_ids=paired_ids,
                        observed={"fraction": coverage},
                        criterion={"minimum": 0.65},
                    ),
                    _evidence(
                        "sheet_metal.volume_model",
                        "pass",
                        entity_ids=paired_ids,
                        observed={"relative_error": volume_error},
                        criterion={"maximum": 0.20},
                    ),
                    _evidence(
                        "sheet_metal.manufacturing_intent",
                        "unknown",
                        entity_ids=[body_id],
                        required=False,
                        observed={"final_brep_geometry_only": True},
                    ),
                ],
            }
        )
        for pair in sorted(
            bend_pairs,
            key=lambda item: tuple(_entity_index(value) for value in item["face_ids"]),
        ):
            bend_index = sum(
                hint["kind"] == "sheet_metal_bend_candidate" for hint in hints
            )
            face_pair = sorted(pair["face_ids"], key=_entity_index)
            bend_face_ids.update(face_pair)
            adjacent_skins = pair["adjacent_skin_face_ids"]
            hints.append(
                {
                    "hint_id": f"sheet_metal_bend_candidate:{bend_index}",
                    "kind": "sheet_metal_bend_candidate",
                    "claim": "geometric_candidate",
                    "parent_hint_id": sheet_id,
                    "body_id": body_id,
                    "entity_ids": face_pair,
                    "highlight_entity_ids": face_pair,
                    "support_entity_ids": adjacent_skins,
                    "geometry": {
                        "inside_face_id": pair["inside_face_id"],
                        "outside_face_id": pair["outside_face_id"],
                        "inside_radius": pair["inside_radius"],
                        "outside_radius": pair["outside_radius"],
                        "mid_radius": pair["mid_radius"],
                        "thickness": pair["thickness"],
                        "axis": pair["axis"],
                        "geometric_sweep_angle_degrees": pair["sweep_angle_degrees"],
                        "bend_length": pair["bend_length"],
                        "adjacent_skin_face_ids": adjacent_skins,
                    },
                    "confidence": _confidence(level, pair["span_similarity"]),
                    "evidence": [
                        _evidence(
                            "sheet_metal_bend.coaxial_radius_difference",
                            "pass",
                            entity_ids=face_pair,
                            observed={
                                "radius_difference": pair["thickness"],
                                "nominal_thickness": thickness,
                            },
                            criterion={
                                "maximum_delta": max(
                                    float(tolerances["thickness"]),
                                    1.0e-3 * thickness,
                                )
                            },
                        )
                    ],
                }
            )
    return hints, bend_face_ids, diagnostics


def inspect_manufacturing_hints_rdescriptor(
    model_or_path: ModelInput,
    *,
    feature_kinds: Sequence[str] = FEATURE_KINDS,
    tolerance: float | None = None,
    angular_tolerance_degrees: float = 0.5,
    max_hints: int = 500,
) -> dict[str, Any]:
    """Return deterministic, highlightable manufacturing-feature candidates.

    Fillet and chamfer hints require supported analytic carrier evidence.
    Sheet-metal hints require opposed constant-thickness skins, a thin-body
    ratio, and a matching thickness-times-midsurface volume model. Hole and
    non-circular holes, local or whole-body extrusion/revolution geometry, and
    loft/sweep geometry are available only when their category is explicitly
    included in ``feature_kinds``; they describe
    geometric explanations and do not recover the original feature history.
    Every hint includes stable entity IDs, measurements, evidence, and
    non-probabilistic confidence. The result describes final BREP geometry only;
    it does not infer process choice, bend allowance, tooling, or manufacturing
    intent.
    """

    if max_hints < 1:
        raise ValueError("max_hints must be at least one")
    requested = tuple(dict.fromkeys(str(value) for value in feature_kinds))
    unknown = sorted(set(requested) - set(_SUPPORTED_FEATURE_KINDS))
    if unknown:
        raise ValueError(
            "feature_kinds contains unsupported values: " + ", ".join(unknown)
        )
    model = _model(model_or_path)
    tolerances = _effective_tolerances(model, tolerance, angular_tolerance_degrees)
    facts = _face_facts(model)
    hints: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    hole_candidates: list[dict[str, Any]] = []
    hole_face_ids: set[str] = set()
    countersink_cone_face_ids: set[str] = set()
    if "hole" in requested:
        hole_candidates = hole_hints(model, facts, tolerances)
        hints.extend(hole_candidates)
        hole_face_ids = {
            face_id
            for hint in hole_candidates
            for face_id in hint["entity_ids"]
            if face_id.startswith("face:")
        }
        countersink_cone_face_ids = {
            face_id
            for hint in hole_candidates
            if hint["geometry"]["form"] == "countersink"
            for segment in hint["geometry"]["segments"]
            if segment["carrier"] == "cone"
            for face_id in segment["face_ids"]
        }
    needs_sheet_context = "sheet_metal" in requested or "revolution" in requested
    sheet_hints: list[dict[str, Any]] = []
    bend_faces: set[str] = set()
    if needs_sheet_context:
        sheet_hints, bend_faces, sheet_diagnostics = _sheet_metal_hints(
            model, facts, tolerances
        )
        if "sheet_metal" in requested:
            hints.extend(sheet_hints)
            diagnostics.extend(sheet_diagnostics)
    sheet_faces = {
        face_id
        for hint in sheet_hints
        if hint["kind"] == "sheet_metal_body_candidate"
        for face_id in hint["entity_ids"]
    }
    if "extrusion" in requested:
        hints.extend(
            extrusion_hints(
                model,
                facts,
                tolerances,
                hole_face_ids=hole_face_ids,
            )
        )
    if "revolution" in requested:
        revolution_candidates, revolution_diagnostics = revolution_hints(
            model,
            facts,
            tolerances,
            excluded_face_ids=hole_face_ids | sheet_faces | bend_faces,
        )
        hints.extend(revolution_candidates)
        diagnostics.extend(revolution_diagnostics)
    shared_whole_families = None
    shared_local_families = None
    if {"sweep", "loft"}.intersection(requested):
        shared_whole_families = whole_body_section_families(model, facts, tolerances)
        shared_local_families = local_section_families(model, facts, tolerances)
    if "sweep" in requested:
        sweep_candidates, sweep_diagnostics = sweep_hints(
            model,
            facts,
            tolerances,
            whole_families=shared_whole_families,
            local_families=shared_local_families,
        )
        hints.extend(sweep_candidates)
        diagnostics.extend(sweep_diagnostics)
    if "loft" in requested:
        loft_candidates, loft_diagnostics = loft_hints(
            model,
            facts,
            tolerances,
            whole_families=shared_whole_families,
            local_families=shared_local_families,
            point_families=whole_body_point_families(model, facts, tolerances),
        )
        hints.extend(loft_candidates)
        diagnostics.extend(loft_diagnostics)
    if "fillet" in requested:
        fillet_hints = _fillet_hints(model, facts, bend_faces)
        if not needs_sheet_context:
            lightweight_bend_faces = _paired_bend_faces_from_fillet_hints(
                model, fillet_hints, facts, tolerances
            )
            fillet_hints = [
                hint
                for hint in fillet_hints
                if not lightweight_bend_faces.intersection(hint["entity_ids"])
            ]
        hints.extend(fillet_hints)
    if "chamfer" in requested:
        hints.extend(
            _chamfer_hints(
                model,
                facts,
                sheet_faces | countersink_cone_face_ids,
                float(tolerances["angular_degrees"]),
                float(tolerances["linear"]),
            )
        )
    counters: Counter[str] = Counter()
    for hint in hints:
        if "hint_id" not in hint:
            hint["hint_id"] = f"{hint['kind']}:{counters[hint['kind']]}"
        counters[hint["kind"]] += 1
    kind_order = {
        "sheet_metal_body_candidate": 0,
        "sheet_metal_bend_candidate": 1,
        "extrusion_region_candidate": 2,
        "revolution_region_candidate": 3,
        "sweep_region_candidate": 4,
        "loft_region_candidate": 5,
        "hole_region_candidate": 6,
        "fillet_region_candidate": 7,
        "chamfer_region_candidate": 8,
    }
    hints.sort(
        key=lambda hint: (
            kind_order[hint["kind"]],
            _entity_index(hint["body_id"]),
            tuple(_entity_index(value) for value in hint["entity_ids"]),
            tuple(
                float(value) for value in hint.get("geometry", {}).get("direction", ())
            ),
        )
    )
    truncated = len(hints) > max_hints
    returned = hints[:max_hints]
    counts = Counter(hint["kind"] for hint in returned)
    return {
        "units": {"length": "mm", "angle": "degree"},
        "tolerances": tolerances,
        "hints": returned,
        "summary": {
            "analyzed_body_count": len(model.bodies),
            "analyzed_face_count": len(model.faces),
            "hint_count": len(returned),
            "hint_counts": dict(sorted(counts.items())),
        },
        "diagnostics": diagnostics,
        "truncated": truncated,
        "omitted_hint_count": max(len(hints) - max_hints, 0),
    }


def render_manufacturing_hints_rpath(
    model_or_path: ModelInput,
    output_path: str | Path,
    *,
    feature_kinds: Sequence[str] = FEATURE_KINDS,
    tolerance: float | None = None,
    angular_tolerance_degrees: float = 0.5,
    max_hints: int = 500,
    views: Sequence[tuple[float, float, str]] | None = None,
    image_size: tuple[float, float] = (18.0, 12.0),
    dpi: int = 180,
    linear_deflection: float = 0.12,
    angular_deflection: float = 0.18,
) -> Path:
    """Render manufacturing hints as deterministic category-colored overlays.

    Sheet-metal skins are blue, bends are orange, extrusion geometry is green,
    revolution geometry is cyan, lofts are pink, sweeps are indigo, holes are
    purple, fillets are red, and chamfers are yellow. Hole, extrusion,
    revolution, loft, and sweep candidates must be explicitly enabled. They
    explain final geometry rather than original
    feature history. Analysis always runs against the current model so entity
    IDs cannot be reused across different BREP instances.
    """

    model = _model(model_or_path)
    analysis = inspect_manufacturing_hints_rdescriptor(
        model,
        feature_kinds=feature_kinds,
        tolerance=tolerance,
        angular_tolerance_degrees=angular_tolerance_degrees,
        max_hints=max_hints,
    )
    from .feature_visualization import FEATURE_COLORS

    styles = (
        (
            "sheet_metal_body_candidate",
            "Sheet-metal skins",
            FEATURE_COLORS["sheet_metal"],
        ),
        (
            "sheet_metal_bend_candidate",
            "Sheet-metal bends",
            FEATURE_COLORS["sheet_metal_bend"],
        ),
        (
            "extrusion_region_candidate",
            "Extrusion candidates",
            FEATURE_COLORS["extrusion"],
        ),
        (
            "revolution_region_candidate",
            "Revolution candidates",
            FEATURE_COLORS["revolution"],
        ),
        ("loft_region_candidate", "Loft candidates", FEATURE_COLORS["loft"]),
        ("sweep_region_candidate", "Sweep candidates", FEATURE_COLORS["sweep"]),
        ("hole_region_candidate", "Hole candidates", FEATURE_COLORS["hole"]),
        ("fillet_region_candidate", "Fillet candidates", FEATURE_COLORS["fillet"]),
        ("chamfer_region_candidate", "Chamfer candidates", FEATURE_COLORS["chamfer"]),
    )
    from .render import (
        DEFAULT_VIEWS,
        _edge_polydata,
        _mesh_polydata,
        _render_polydata_views,
    )

    groups = []
    legend = []
    for kind, label, color in styles:
        ids = sorted(
            {
                entity_id
                for hint in analysis.get("hints", [])
                if hint.get("kind") == kind
                for entity_id in hint.get("highlight_entity_ids", hint["entity_ids"])
                if entity_id.startswith("face:")
            },
            key=_entity_index,
        )
        if not ids:
            continue
        shapes = [model.resolve_entity(entity_id)[2] for entity_id in ids]
        groups.append(
            (
                _mesh_polydata(shapes, linear_deflection, angular_deflection),
                color,
                1.0,
            )
        )
        legend.append((label, color))
    if not groups:
        raise ValueError("The manufacturing analysis contains no highlightable faces")
    return _render_polydata_views(
        _mesh_polydata([model.root], linear_deflection, angular_deflection),
        output_path,
        title="BREP manufacturing-feature hints",
        views=tuple(views or DEFAULT_VIEWS),
        image_size=image_size,
        dpi=dpi,
        context_opacity=0.16,
        brep_edge_polydata=_edge_polydata([model.root], deflection=linear_deflection),
        highlighted_groups=groups,
        legend=legend,
        legend_columns=1,
        legend_panel=True,
    )


__all__ = [
    "inspect_manufacturing_hints_rdescriptor",
    "render_manufacturing_hints_rpath",
]
