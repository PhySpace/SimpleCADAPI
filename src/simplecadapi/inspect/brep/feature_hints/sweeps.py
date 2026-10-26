"""Rigid-section path, twist, and helical sweep geometry recognition."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from .common import confidence, entity_ids, evidence, unit, vector
from .loft_sweep_specialist import analyze_loft_sweep_family
from .profiles import local_axes, sample_edge_points
from .section_families import (
    local_section_families,
    variable_section_evidence,
    whole_body_section_families,
)


def _helix_fit(points: np.ndarray) -> dict[str, Any] | None:
    if len(points) < 16:
        return None
    center = np.mean(points, axis=0)
    covariance = (points - center).T @ (points - center) / len(points)
    _, axes = np.linalg.eigh(covariance)
    best: tuple[tuple[float, float, float], dict[str, Any]] | None = None
    for column in range(3):
        axis = unit(axes[:, column])
        first_nonzero = next(
            (value for value in axis if abs(float(value)) > 1.0e-12), 1.0
        )
        if first_nonzero < 0.0:
            axis = -axis
        x_axis, y_axis, _ = local_axes(axis)
        relative = points - center
        x = relative @ x_axis
        y = relative @ y_axis
        matrix = np.column_stack([2.0 * x, 2.0 * y, np.ones(len(x))])
        try:
            solution, *_ = np.linalg.lstsq(matrix, x * x + y * y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        circle_center = center + solution[0] * x_axis + solution[1] * y_axis
        radial_vectors = points - circle_center
        axial = radial_vectors @ axis
        radial_vectors = radial_vectors - axial[:, None] * axis
        radii = np.linalg.norm(radial_vectors, axis=1)
        radius = float(np.mean(radii))
        if radius <= 1.0e-9:
            continue
        radius_cv = float(np.std(radii) / radius)
        angles = np.unwrap(np.arctan2(radial_vectors @ y_axis, radial_vectors @ x_axis))
        angle_span = float(angles[-1] - angles[0])
        if abs(angle_span) <= math.pi:
            continue
        design = np.column_stack([angles, np.ones(len(angles))])
        coefficients, *_ = np.linalg.lstsq(design, axial, rcond=None)
        predicted = design @ coefficients
        residual = float(np.sum((axial - predicted) ** 2))
        total = float(np.sum((axial - np.mean(axial)) ** 2))
        linear_r2 = 1.0 - residual / max(total, 1.0e-30)
        axial_span = float(np.ptp(axial))
        turn_count = abs(angle_span) / (2.0 * math.pi)
        pitch = abs(float(coefficients[0])) * 2.0 * math.pi
        payload = {
            "axis": {"point": vector(circle_center), "direction": vector(axis)},
            "radius": radius,
            "radius_coefficient_of_variation": radius_cv,
            "turn_count": turn_count,
            "pitch": pitch,
            "axial_span": axial_span,
            "linear_r_squared": linear_r2,
            "handedness": "right" if coefficients[0] >= 0.0 else "left",
        }
        key = (-linear_r2, radius_cv, -turn_count)
        if best is None or key < best[0]:
            best = (key, payload)
    return None if best is None else best[1]


def _longitudinal_helix(
    model,
    facts: dict[str, dict[str, Any]],
    family: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    cap_edges = set(family["start_loop"]["edge_ids"]) | set(
        family["end_loop"]["edge_ids"]
    )
    longitudinal = entity_ids(
        {
            edge_id
            for face_id in family["side_face_ids"]
            for edge_id in facts[face_id]["edges"]
            if edge_id not in cap_edges
        }
    )
    fits = []
    for edge_id in longitudinal:
        _, _, edge = model.resolve_entity(edge_id)
        points = sample_edge_points(edge, count=193)
        fit = _helix_fit(points)
        if fit is None:
            continue
        if (
            fit["turn_count"] >= 0.75
            and fit["radius_coefficient_of_variation"] <= 0.03
            and fit["linear_r_squared"] >= 0.995
            and fit["pitch"] > 0.0
        ):
            fits.append((edge_id, fit))
    if not fits:
        return None, longitudinal
    fits.sort(
        key=lambda item: (
            -item[1]["linear_r_squared"],
            item[1]["radius_coefficient_of_variation"],
            -item[1]["turn_count"],
            int(item[0].split(":")[1]),
        )
    )
    return fits[0][1], longitudinal


def sweep_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
    *,
    whole_families: Sequence[dict[str, Any]] | None = None,
    local_families: Sequence[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return whole-body rigid-section sweep candidates."""

    angular = float(tolerances["angular_degrees"])
    hints: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    whole_values = (
        whole_body_section_families(model, facts, tolerances)
        if whole_families is None
        else whole_families
    )
    local_values = (
        local_section_families(model, facts, tolerances)
        if local_families is None
        else local_families
    )
    for family in whole_values:
        if not family["rigid_profile"] or family["pure_translation"]:
            continue
        section_family = family["section_family"]
        helix_fit, longitudinal_edge_ids = _longitudinal_helix(model, facts, family)
        variable_section = variable_section_evidence(model, facts, family)
        if helix_fit is None and variable_section is not None:
            diagnostics.append(
                {
                    "code": "sweep.variable_section_spacing",
                    "body_id": family["body_id"],
                    "entity_ids": family["entity_ids"],
                    "observed": variable_section,
                }
            )
            continue
        alignment = family["alignment"]
        chord_direction = unit(family["path_chord"])
        start_normal = unit(facts[family["start_face_id"]]["normal"])
        tangent_alignment = abs(float(np.dot(chord_direction, start_normal)))
        if helix_fit is not None:
            form = "helical_sweep"
        elif tangent_alignment < math.cos(math.radians(max(angular, 1.0))):
            form = "whole_body_path_sweep"
        elif family["parallel_caps"] and alignment["rotation_angle_degrees"] > max(
            2.0 * angular, 1.0
        ):
            form = "twisted_sweep"
        else:
            form = "whole_body_path_sweep"
        strong_sections = section_family["actual_intermediate_section_count"] >= 2
        specialist = analyze_loft_sweep_family(
            model,
            facts,
            family,
            linear_tolerance=float(tolerances["linear"]),
            angular_tolerance_degrees=angular,
            feature_family="sweep",
            side_types=sorted(
                {facts[face_id]["type"] for face_id in family["side_face_ids"]}
            ),
        )
        geometry = {
            "form": form,
            "coverage": family["coverage"],
            "region_role": family["region_role"],
            "start_face_id": family["start_face_id"],
            "end_face_id": family["end_face_id"],
            "side_face_ids": family["side_face_ids"],
            "longitudinal_edge_ids": longitudinal_edge_ids,
            "direction": family["path_chord"],
            "path_chord_length": family["path_chord_length"],
            "endpoint_tangent_chord_alignment": tangent_alignment,
            "profile": family["profile"],
            "endpoint_alignment": alignment,
            "twist_angle_degrees": (
                alignment["rotation_angle_degrees"] if form == "twisted_sweep" else None
            ),
            "helix_fit": helix_fit,
            "section_family": section_family,
            "specialist_analysis": specialist,
        }
        evidence_items = [
            evidence(
                "sweep.complete_cap_to_cap_side_coverage",
                entity_ids_value=[
                    family["start_face_id"],
                    family["end_face_id"],
                    *family["side_face_ids"],
                ],
            ),
            evidence(
                "sweep.rigid_endpoint_profile",
                entity_ids_value=[family["start_face_id"], family["end_face_id"]],
                observed=alignment,
                criterion={"maximum_rigid_error": family["rigid_error_limit"]},
            ),
            evidence(
                "sweep.actual_section_flow",
                entity_ids_value=family["side_face_ids"],
                observed={
                    "station_count": section_family["station_count"],
                    "actual_intermediate_section_count": section_family[
                        "actual_intermediate_section_count"
                    ],
                    "tracking_summary": section_family["tracking"]["summary"],
                    "stations": [
                        {
                            "station": item["station"],
                            "plane": item["plane"],
                            "source": item["source"],
                        }
                        for item in section_family["stations"]
                    ],
                },
                required=False,
            ),
        ]
        if helix_fit is not None:
            evidence_items.append(
                evidence(
                    "sweep.longitudinal_helix_fit",
                    entity_ids_value=longitudinal_edge_ids,
                    observed=helix_fit,
                    criterion={
                        "maximum_radius_coefficient_of_variation": 0.03,
                        "minimum_linear_r_squared": 0.995,
                        "minimum_turn_count": 0.75,
                    },
                )
            )
        hints.append(
            {
                "kind": "sweep_region_candidate",
                "claim": "geometric_candidate",
                "body_id": family["body_id"],
                "entity_ids": family["entity_ids"],
                "highlight_entity_ids": family["highlight_entity_ids"],
                "support_entity_ids": family["support_entity_ids"],
                "geometry": geometry,
                "confidence": confidence(
                    "strong" if strong_sections or helix_fit is not None else "medium"
                ),
                "evidence": evidence_items,
            }
        )
    for family in local_values:
        if not family["rigid_profile"] or family["pure_translation"]:
            continue
        section_family = family["section_family"]
        helix_fit, longitudinal_edge_ids = _longitudinal_helix(model, facts, family)
        variable_section = variable_section_evidence(model, facts, family)
        if helix_fit is None and variable_section is not None:
            diagnostics.append(
                {
                    "code": "sweep.variable_section_spacing",
                    "body_id": family["body_id"],
                    "entity_ids": family["entity_ids"],
                    "observed": variable_section,
                }
            )
            continue
        alignment = family["alignment"]
        chord_direction = unit(family["path_chord"])
        start_normal = unit(facts[family["start_face_id"]]["normal"])
        tangent_alignment = abs(float(np.dot(chord_direction, start_normal)))
        if helix_fit is not None:
            form = "helical_sweep"
        elif (
            family["parallel_caps"]
            and tangent_alignment >= math.cos(math.radians(max(angular, 1.0)))
            and alignment["rotation_angle_degrees"] > max(2.0 * angular, 1.0)
        ):
            form = "twisted_sweep"
        else:
            form = (
                "local_swept_boss"
                if family["region_role"] == "additive"
                else "local_swept_cut"
            )
        specialist = analyze_loft_sweep_family(
            model,
            facts,
            family,
            linear_tolerance=float(tolerances["linear"]),
            angular_tolerance_degrees=angular,
            feature_family="sweep",
            side_types=sorted(
                {facts[face_id]["type"] for face_id in family["side_face_ids"]}
            ),
        )
        hints.append(
            {
                "kind": "sweep_region_candidate",
                "claim": "geometric_candidate",
                "body_id": family["body_id"],
                "entity_ids": family["entity_ids"],
                "highlight_entity_ids": family["highlight_entity_ids"],
                "support_entity_ids": family["support_entity_ids"],
                "geometry": {
                    "form": form,
                    "coverage": "local",
                    "region_role": family["region_role"],
                    "start_face_id": family["start_face_id"],
                    "end_face_id": family["end_face_id"],
                    "side_face_ids": family["side_face_ids"],
                    "longitudinal_edge_ids": longitudinal_edge_ids,
                    "direction": family["path_chord"],
                    "path_chord_length": family["path_chord_length"],
                    "endpoint_tangent_chord_alignment": tangent_alignment,
                    "profile": family["profile"],
                    "endpoint_alignment": alignment,
                    "twist_angle_degrees": (
                        alignment["rotation_angle_degrees"]
                        if form == "twisted_sweep"
                        else None
                    ),
                    "helix_fit": helix_fit,
                    "section_family": section_family,
                    "specialist_analysis": specialist,
                },
                "confidence": confidence(
                    "strong"
                    if section_family["actual_intermediate_section_count"] >= 2
                    or helix_fit is not None
                    else "medium"
                ),
                "evidence": [
                    evidence(
                        "sweep.local_inner_loop_and_terminal",
                        entity_ids_value=[
                            *family["support_entity_ids"],
                            family["end_face_id"],
                            *family["side_face_ids"],
                        ],
                    ),
                    evidence(
                        "sweep.local_rigid_section_flow",
                        entity_ids_value=family["entity_ids"],
                        observed={
                            "alignment": alignment,
                            "tracking_summary": section_family["tracking"]["summary"],
                            "helix_fit": helix_fit,
                            "stations": [
                                {
                                    "station": item["station"],
                                    "plane": item["plane"],
                                    "source": item["source"],
                                }
                                for item in section_family["stations"]
                            ],
                        },
                        criterion={"maximum_rigid_error": family["rigid_error_limit"]},
                    ),
                ],
            }
        )
    return hints, diagnostics


__all__ = ["sweep_hints"]
