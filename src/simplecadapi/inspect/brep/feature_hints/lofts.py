"""Variable-section loft geometry recognition from final BRep evidence."""

from __future__ import annotations

from typing import Any, Sequence

from .common import confidence, evidence
from .loft_sweep_specialist import analyze_loft_sweep_family
from .ruled_sides import side_faces_are_ruled
from .section_families import (
    local_section_families,
    variable_section_evidence,
    whole_body_point_families,
    whole_body_section_families,
)


def _variation_law(family: dict[str, Any]) -> str:
    alignment = family["alignment"]
    area_values = [
        float(contour.get("area") or 0.0)
        for station in family["section_family"]["stations"]
        for contour in station["contours"][:1]
    ]
    area_change = bool(area_values) and min(area_values) / max(area_values) < 0.98
    shape_change = alignment["similarity_maximum_error"] > family["rigid_error_limit"]
    if area_change and shape_change:
        return "area_and_shape"
    if area_change:
        return "area"
    if shape_change:
        return "shape"
    return "unknown"


def loft_hints(
    model,
    facts: dict[str, dict[str, Any]],
    tolerances: dict[str, float | str],
    *,
    whole_families: Sequence[dict[str, Any]] | None = None,
    local_families: Sequence[dict[str, Any]] | None = None,
    point_families: Sequence[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return conservative whole-body loft candidates and diagnostics."""

    hints: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    section_families = (
        whole_body_section_families(model, facts, tolerances)
        if whole_families is None
        else whole_families
    )
    local_values = (
        local_section_families(model, facts, tolerances)
        if local_families is None
        else local_families
    )
    point_values = (
        whole_body_point_families(model, facts, tolerances)
        if point_families is None
        else point_families
    )
    variation = [
        variable_section_evidence(model, facts, family) for family in section_families
    ]
    rigid_bodies = {
        family["body_id"]
        for family, spacing_change in zip(section_families, variation)
        if family["rigid_profile"] and spacing_change is None
    }
    for family, spacing_change in zip(section_families, variation):
        if family["rigid_profile"] and spacing_change is None:
            continue
        if family["body_id"] in rigid_bodies:
            continue
        section_family = family["section_family"]
        safe = section_family["tracking"]["summary"]["single_loft_safe"]
        if not safe and spacing_change is None:
            diagnostics.append(
                {
                    "code": "loft.section_topology_change",
                    "body_id": family["body_id"],
                    "entity_ids": family["entity_ids"],
                    "events": section_family["tracking"]["events"],
                }
            )
            continue
        side_types = {facts[face_id]["type"] for face_id in family["side_face_ids"]}
        interpolation = (
            "ruled"
            if side_faces_are_ruled(
                facts, family, linear_tolerance=float(tolerances["linear"])
            )
            else "smooth"
        )
        specialist = analyze_loft_sweep_family(
            model,
            facts,
            (
                {
                    **family,
                    "rigid_profile": False,
                    "variable_section_evidence": spacing_change,
                }
                if spacing_change
                else family
            ),
            linear_tolerance=float(tolerances["linear"]),
            angular_tolerance_degrees=float(tolerances["angular_degrees"]),
            feature_family="loft",
            side_types=sorted(side_types),
            interpolation=interpolation,
        )
        level = (
            "strong"
            if safe and section_family["actual_intermediate_section_count"] >= 2
            else "medium"
        )
        geometry = {
            "form": "whole_body_profile_loft",
            "coverage": family["coverage"],
            "region_role": family["region_role"],
            "terminal_kind": "profile",
            "interpolation": interpolation,
            "variation_law": (
                "corner_spacing"
                if spacing_change and family["rigid_profile"]
                else _variation_law(family)
            ),
            "variable_section_evidence": spacing_change,
            "start_face_id": family["start_face_id"],
            "end_face_id": family["end_face_id"],
            "side_face_ids": family["side_face_ids"],
            "direction": family["path_chord"],
            "length": family["path_chord_length"],
            "profile": family["profile"],
            "endpoint_alignment": family["alignment"],
            "section_family": section_family,
            "specialist_analysis": specialist,
        }
        hints.append(
            {
                "kind": "loft_region_candidate",
                "claim": "geometric_candidate",
                "body_id": family["body_id"],
                "entity_ids": family["entity_ids"],
                "highlight_entity_ids": family["highlight_entity_ids"],
                "support_entity_ids": family["support_entity_ids"],
                "geometry": geometry,
                "confidence": confidence(level),
                "evidence": [
                    evidence(
                        "loft.complete_cap_to_cap_side_coverage",
                        entity_ids_value=[
                            family["start_face_id"],
                            family["end_face_id"],
                            *family["side_face_ids"],
                        ],
                    ),
                    evidence(
                        (
                            "loft.variable_longitudinal_spacing"
                            if spacing_change
                            else "loft.non_rigid_endpoint_profiles"
                        ),
                        entity_ids_value=[
                            family["start_face_id"],
                            family["end_face_id"],
                        ],
                        observed=spacing_change or family["alignment"],
                        criterion=(
                            {"minimum_median_relative_change": 0.15}
                            if spacing_change
                            else {"minimum_rigid_error": family["rigid_error_limit"]}
                        ),
                    ),
                    evidence(
                        "loft.actual_section_flow",
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
                        criterion={"single_loft_safe": True} if safe else {},
                        required=safe,
                    ),
                ],
            }
        )
    for family in local_values:
        spacing_change = variable_section_evidence(model, facts, family)
        if family["rigid_profile"] and spacing_change is None:
            continue
        section_family = family["section_family"]
        if (
            not section_family["tracking"]["summary"]["single_loft_safe"]
            and spacing_change is None
        ):
            diagnostics.append(
                {
                    "code": "loft.local_section_topology_change",
                    "body_id": family["body_id"],
                    "entity_ids": family["entity_ids"],
                    "events": section_family["tracking"]["events"],
                }
            )
            continue
        form = (
            "local_lofted_boss"
            if family["region_role"] == "additive"
            else "local_lofted_cut"
        )
        side_types = {facts[value]["type"] for value in family["side_face_ids"]}
        interpolation = (
            "ruled"
            if side_faces_are_ruled(
                facts, family, linear_tolerance=float(tolerances["linear"])
            )
            else "smooth"
        )
        specialist = analyze_loft_sweep_family(
            model,
            facts,
            (
                {
                    **family,
                    "rigid_profile": False,
                    "variable_section_evidence": spacing_change,
                }
                if spacing_change
                else family
            ),
            linear_tolerance=float(tolerances["linear"]),
            angular_tolerance_degrees=float(tolerances["angular_degrees"]),
            feature_family="loft",
            side_types=sorted(side_types),
            interpolation=interpolation,
        )
        hints.append(
            {
                "kind": "loft_region_candidate",
                "claim": "geometric_candidate",
                "body_id": family["body_id"],
                "entity_ids": family["entity_ids"],
                "highlight_entity_ids": family["highlight_entity_ids"],
                "support_entity_ids": family["support_entity_ids"],
                "geometry": {
                    "form": form,
                    "coverage": "local",
                    "region_role": family["region_role"],
                    "terminal_kind": "profile",
                    "interpolation": interpolation,
                    "variation_law": (
                        "corner_spacing"
                        if spacing_change and family["rigid_profile"]
                        else _variation_law(family)
                    ),
                    "variable_section_evidence": spacing_change,
                    "start_face_id": family["start_face_id"],
                    "end_face_id": family["end_face_id"],
                    "side_face_ids": family["side_face_ids"],
                    "direction": family["path_chord"],
                    "length": family["path_chord_length"],
                    "profile": family["profile"],
                    "endpoint_alignment": family["alignment"],
                    "section_family": section_family,
                    "specialist_analysis": specialist,
                },
                "confidence": confidence(
                    "strong"
                    if section_family["tracking"]["summary"]["single_loft_safe"]
                    and section_family["actual_intermediate_section_count"] >= 2
                    else "medium"
                ),
                "evidence": [
                    evidence(
                        "loft.local_inner_loop_and_terminal",
                        entity_ids_value=[
                            *family["support_entity_ids"],
                            family["end_face_id"],
                            *family["side_face_ids"],
                        ],
                    ),
                    evidence(
                        (
                            "loft.variable_longitudinal_spacing"
                            if spacing_change
                            else "loft.local_non_rigid_section_flow"
                        ),
                        entity_ids_value=family["entity_ids"],
                        observed={
                            "alignment": family["alignment"],
                            "variable_section_evidence": spacing_change,
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
                        criterion=(
                            {"minimum_median_relative_change": 0.15}
                            if spacing_change
                            else {"minimum_rigid_error": family["rigid_error_limit"]}
                        ),
                    ),
                ],
            }
        )
    for family in point_values:
        terminal_mode = family.get("terminal_mode", "end_point")
        if family.get("section_family"):
            specialist = analyze_loft_sweep_family(
                model,
                facts,
                {
                    **family,
                    "rigid_profile": False,
                },
                linear_tolerance=float(tolerances["linear"]),
                angular_tolerance_degrees=float(tolerances["angular_degrees"]),
                feature_family="loft",
                side_types=sorted(
                    {facts[face_id]["type"] for face_id in family["side_face_ids"]}
                ),
            )
        else:
            specialist = {
                "version": "1.0",
                "status": "partial",
                "loft_control_mode": "sections_only",
                "construction_strategy": "section_only",
                "result_kind": "solid",
                "path_profile_mode": "variable",
                "terminal_mode": terminal_mode,
                "interpolation": "unknown",
                "interpolation_by_span": [],
                "section_alignment": {
                    "status": "not_applicable_to_point_family",
                    "profiles": [],
                },
                "profile_law": {"type": "point_terminal"},
                "spine": None,
                "guides": [],
                "guide_attachment_map": [],
                "boundary_conditions": {
                    "start": {"type": "unknown", "identifiability": "none"},
                    "end": {"type": "singular", "identifiability": "high"},
                },
                "reconstruction_support": "native",
            }
        specialist["terminal_mode"] = terminal_mode
        boundary_conditions = specialist.setdefault("boundary_conditions", {})
        if terminal_mode in {"start_point", "both_points"}:
            boundary_conditions["start"] = {
                "type": "singular",
                "identifiability": "high",
                "evidence_level": "shared_terminal_vertex",
            }
        if terminal_mode in {"end_point", "both_points"}:
            boundary_conditions["end"] = {
                "type": "singular",
                "identifiability": "high",
                "evidence_level": "shared_terminal_vertex",
            }
        apex_vertex_ids = list(
            family.get("apex_vertex_ids") or [family["apex_vertex_id"]]
        )
        hints.append(
            {
                "kind": "loft_region_candidate",
                "claim": "geometric_candidate",
                "body_id": family["body_id"],
                "entity_ids": family["entity_ids"],
                "highlight_entity_ids": family["highlight_entity_ids"],
                "support_entity_ids": family["support_entity_ids"],
                "geometry": {
                    "form": "whole_body_point_loft",
                    "coverage": "whole_body",
                    "region_role": "neutral",
                    "terminal_kind": "point",
                    "terminal_mode": terminal_mode,
                    "interpolation": "unknown",
                    "variation_law": "area_to_zero",
                    "start_face_id": family["start_face_id"],
                    "end_face_id": None,
                    "apex_vertex_id": family["apex_vertex_id"],
                    "apex_vertex_ids": apex_vertex_ids,
                    "side_face_ids": family["side_face_ids"],
                    "profile": family["profile"],
                    "section_family": family.get("section_family"),
                    "specialist_analysis": specialist,
                },
                "confidence": confidence(
                    "strong"
                    if terminal_mode != "both_points"
                    or (
                        family.get("section_family", {}).get(
                            "actual_intermediate_section_count", 0
                        )
                        >= 2
                    )
                    else "medium"
                ),
                "evidence": [
                    evidence(
                        (
                            "loft.double_point_terminals_with_sections"
                            if terminal_mode == "both_points"
                            else "loft.single_shared_apex"
                        ),
                        entity_ids_value=[
                            *(
                                [family["start_face_id"]]
                                if family["start_face_id"] is not None
                                else []
                            ),
                            *apex_vertex_ids,
                            *family["side_face_ids"],
                        ],
                        observed={
                            "apex_vertex_ids": apex_vertex_ids,
                            "actual_intermediate_section_count": (
                                family.get("section_family", {}).get(
                                    "actual_intermediate_section_count", 0
                                )
                            ),
                        },
                        criterion={
                            "shared_terminal_vertex_count": len(apex_vertex_ids)
                        },
                    )
                ],
            }
        )
    return hints, diagnostics


__all__ = ["loft_hints"]
