"""Versioned, JSON-safe reconstruction contracts for geometric candidates."""

from __future__ import annotations

from typing import Any


def _operation_candidates(
    category: str, geometry: dict[str, Any], specialist: dict[str, Any]
) -> list[dict[str, Any]]:
    result_kind = specialist.get("result_kind", "solid")
    strategy = specialist.get("construction_strategy", "section_only")
    interpolation = specialist.get("interpolation", geometry.get("interpolation"))
    ruled = interpolation == "ruled"
    boundary_conditions = specialist.get("boundary_conditions") or {}
    unsupported_boundary_conditions = [
        endpoint
        for endpoint, condition in boundary_conditions.items()
        if isinstance(condition, dict)
        and condition.get("type") not in {None, "free", "unknown", "singular"}
    ]
    candidates: list[dict[str, Any]] = []
    if category == "sweep":
        form = geometry.get("form")
        if form == "helical_sweep":
            helix = geometry.get("helix_fit") or {}
            axis = helix.get("axis") or {}
            candidates.append(
                {
                    "operation": "helical_sweep",
                    "api": "helical_sweep_rsolid",
                    "capability": "native",
                    "score": 1.0,
                    "parameters": {
                        "pitch": helix.get("pitch"),
                        "height": helix.get("axial_span"),
                        "radius": helix.get("radius"),
                        "center": axis.get("point"),
                        "dir": axis.get("direction"),
                        "handedness": str(helix.get("handedness", "right")).capitalize(),
                    },
                }
            )
        elif form == "twisted_sweep":
            candidates.append(
                {
                    "operation": "twisted_sweep",
                    "api": "twisted_sweep_rsolid",
                    "capability": "native",
                    "score": 1.0,
                    "parameters": {
                        "distance": geometry.get("path_chord_length"),
                        "twist_angle": geometry.get("twist_angle_degrees"),
                    },
                }
            )
        else:
            candidates.append(
                {
                    "operation": "path_sweep",
                    "api": "sweep_rsolid",
                    "capability": "native",
                    "score": 1.0,
                    "parameters": {
                        "is_frenet": False,
                    },
                    "path_evidence": specialist.get("spine"),
                }
            )
    else:
        candidates.append(
            {
                "operation": "section_loft",
                "api": "loft_rsolid" if result_kind == "solid" else "loft_rshell",
                "capability": (
                    "emulated"
                    if unsupported_boundary_conditions or strategy == "path_constrained"
                    else "native"
                ),
                "score": 1.0 if strategy == "section_only" else 0.8,
                "parameters": {"ruled": ruled},
                "unsupported_parameters": [
                    *unsupported_boundary_conditions,
                    *(["path_constraint"] if strategy == "path_constrained" else []),
                ],
                "rejection_reason": (
                    "upstream section loft cannot enforce recovered path or endpoint constraints"
                    if unsupported_boundary_conditions or strategy == "path_constrained"
                    else None
                ),
            }
        )
        if specialist.get("guides"):
            candidates.append(
                {
                    "operation": "guided_surface_network",
                    "api": "guided_surface_network_rshell",
                    "capability": "planned",
                    "score": 0.7,
                    "parameters": {
                        "guides": specialist.get("guides"),
                        "guide_attachment_map": specialist.get(
                            "guide_attachment_map"
                        ),
                    },
                }
            )
    return candidates


def build_reconstruction_contract(
    *,
    category: str,
    geometry: dict[str, Any],
    feature_id: str | None = None,
    entity_ids: list[str] | None = None,
    confidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a stable handoff contract for loft/sweep candidates."""

    if category not in {"loft", "sweep"}:
        return None
    specialist = geometry.get("specialist_analysis") or {}
    operation_candidates = _operation_candidates(category, geometry, specialist)
    recommended = operation_candidates[0] if operation_candidates else None
    section_family = geometry.get("section_family") or {}
    boundary_conditions = specialist.get("boundary_conditions") or {}
    boundary_proxy_required = category == "loft" and any(
        isinstance(condition, dict)
        and condition.get("type") not in {None, "free", "unknown", "singular"}
        for condition in boundary_conditions.values()
    )
    path_proxy_required = (
        category == "loft"
        and specialist.get("construction_strategy") == "path_constrained"
    )
    roi_face_ids = sorted(
        {
            *geometry.get("side_face_ids", ()),
            *(
                [geometry["start_face_id"]]
                if geometry.get("start_face_id") is not None
                else []
            ),
            *(
                [geometry["end_face_id"]]
                if geometry.get("end_face_id") is not None
                else []
            ),
        }
    )
    return {
        "schema_version": "1.0",
        "feature_id": feature_id,
        "family": category,
        "subtype": geometry.get("form"),
        "roi_face_ids": roi_face_ids,
        "roi_entity_ids": list(entity_ids or []),
        "excluded_modifier_face_ids": [],
        "boolean_role": geometry.get("region_role"),
        "confidence": dict(confidence or {}),
        "evidence_level": "derived_from_brep_sections",
        "exactness": (
            "approximate" if boundary_proxy_required or path_proxy_required else "tolerance_fit"
        ),
        "reconstruction_support": (
            "emulated"
            if boundary_proxy_required or path_proxy_required
            else specialist.get("reconstruction_support", "unsupported")
        ),
        "result_kind": specialist.get("result_kind", "solid"),
        "interpolation": specialist.get(
            "interpolation", geometry.get("interpolation", "unknown")
        ),
        "interpolation_by_span": specialist.get("interpolation_by_span", []),
        "loft_control_mode": specialist.get("loft_control_mode"),
        "construction_strategy": specialist.get("construction_strategy"),
        "terminal_mode": specialist.get("terminal_mode"),
        "path_profile_mode": specialist.get("path_profile_mode"),
        "sections": [
            {
                "station_id": f"station:{index}",
                "station": item.get("station"),
                "plane": item.get("plane"),
                "source": item.get("source"),
                "contour_count": len(item.get("contours") or []),
            }
            for index, item in enumerate(section_family.get("stations") or [])
        ],
        "section_alignment": specialist.get("section_alignment"),
        "profile_tracks": [
            {
                "track_id": "profile_track:0",
                "role": "primary",
                "station_profile_map": [
                    {
                        "station_id": f"station:{index}",
                        "profile_id": f"station:{index}:contour:0",
                    }
                    for index, _item in enumerate(section_family.get("stations") or [])
                ],
                "topology_events": (
                    (section_family.get("tracking") or {}).get("events") or []
                ),
                "global_alignment_error": (
                    (specialist.get("section_alignment") or {}).get("global_cost")
                ),
            }
        ],
        "profile_law": specialist.get("profile_law"),
        "frame_law": specialist.get("frame_law"),
        "adaptive_station_plan": specialist.get("adaptive_station_plan"),
        "specialist_trigger": specialist.get("specialist_trigger"),
        "spine": specialist.get("spine"),
        "guides": specialist.get("guides", []),
        "guide_attachment_map": specialist.get("guide_attachment_map", []),
        "boundary_conditions": boundary_conditions,
        "operation_candidates": operation_candidates,
        "recommended_operation": recommended,
        "preflight_checks": [
            "section_order",
            "section_orientation",
            "seam_stability",
            "self_intersection",
            "solid_closure",
            "step_roundtrip",
        ],
        "fallback_order": [
            item["operation"] for item in operation_candidates[1:]
        ],
        "limitations": [
            "final BRep geometry cannot prove the original CAD authoring history",
            "fitted paths and guides are reconstruction hypotheses unless marked explicit_brep",
            "boundary magnitude is kernel-specific when identifiability is low",
            "multi-rail guide constraints require a separate validated surface-network implementation",
            "upstream loft does not support a path constraint or explicit endpoint continuity",
        ],
    }


__all__ = ["build_reconstruction_contract"]
