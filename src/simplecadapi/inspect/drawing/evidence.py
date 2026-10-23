"""Independent DIM gates and bindings between measurements and annotations."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Mapping, Sequence

from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from simplecadapi._cpp.occt.BRepExtrema import BRepExtrema_DistShapeShape
from simplecadapi._cpp.occt.gp import gp_Pnt
import numpy as np

from ._provenance import RESULT_VERSION, digest
from ._section_geometry import section_geometry, compound
from ._measurement_contract import contract_errors, display_precision
from ._review_evidence import validate_review


def _original_errors(ledger):
    errors = []
    for key in (
        "dim_id",
        "feature_id",
        "view",
        "source_id",
        "raw_word_ids",
        "association_evidence",
        "datum",
        "tolerance_basis",
    ):
        if not ledger.get(key):
            errors.append(f"missing {key}")
    for key in ("coordinate_status", "value_status", "association_status"):
        if ledger.get(key) != "verified":
            errors.append(f"{key} is not verified")
    return errors


def assess_dimension_rverdict(
    ledger: Mapping[str, Any],
    measurement: Mapping[str, Any],
    *,
    error_assessment: Mapping[str, Any] | None = None,
    output_evidence: Mapping[str, Any] | None = None,
    output_annotation: Mapping[str, Any] | None = None,
    binding_validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess original interpretation, model conformance and output independently.

    Ledger fields: dim_id, feature_id, view, source_id, raw_word_ids,
    association_evidence, datum, tolerance_basis, tolerance_min/max, and
    coordinate_status/value_status/association_status (all ``verified``).
    An independently reviewed ``measurement_contract`` must specify kind,
    definition, normalized local direction (or null), line point (or null),
    units and coordinate_space. A shared contour does not identify an observable.
    Ledger section_checks must independently match the measurement configuration;
    section validity, ring topology, frame and material/void/display probes must
    pass before a DIM can pass model measurement.
    An external uncertainty assessment needs measurement_id, bound_mm, basis
    and evidence; it must bound total measurement error, not just fit residual.
    Unknown bounds or intervals crossing a tolerance boundary remain pending.
    Output needs the current ``output_annotation`` and the corresponding per-DIM
    ``binding_validation`` from validate_section_annotations_rreport. The unchanged
    ``output_evidence`` review records layout_status=reviewed, association_status=
    verified, evidence and the DIM/measurement/model/section IDs seen at review time.
    Its render_artifact contains absolute image_path/sidecar_path and the reviewed
    image_sha256/sidecar_sha256. Current files, source IDs and annotation content
    must match; stale reviews are never relabeled. This checks evidence contracts;
    it does not independently establish the truth of a caller's review or bound.
    """
    original_errors = _original_errors(ledger)
    reasons = contract_errors(ledger, measurement)
    section_validation = measurement.get("section_validation", {})
    if section_validation.get("status") != "passed":
        reasons.append(
            "section validity/material/void/direction checks have not passed"
        )
    if not ledger.get("section_checks") or ledger.get(
        "section_checks"
    ) != measurement.get("configuration", {}).get("section_checks"):
        reasons.append(
            "independent ledger section_checks contract is missing or differs"
        )
    bound = measurement.get("error_bound_mm")
    if error_assessment is not None:
        if (
            error_assessment.get("measurement_id") == measurement.get("measurement_id")
            and error_assessment.get("basis")
            and error_assessment.get("evidence")
        ):
            bound = error_assessment.get("bound_mm")
        else:
            reasons.append("uncertainty assessment lacks matching ID/basis/evidence")
    value = measurement.get("value")
    lower, upper = ledger.get("tolerance_min"), ledger.get("tolerance_max")
    interval = None
    model_status = "pending"
    if measurement.get("accuracy_class") == "fit_candidate":
        reasons.append("fitted circle is a candidate, not verified circular geometry")
    if not ledger.get("tolerance_basis"):
        reasons.append("tolerance basis is missing")
    valid_numbers = all(
        isinstance(v, (float, int)) and math.isfinite(v)
        for v in (value, lower, upper, bound)
    )
    if not valid_numbers or (valid_numbers and (bound < 0 or lower > upper)):
        reasons.append("missing or invalid tolerance/value/total error bound")
    elif not reasons:
        interval = [value - bound, value + bound]
        if lower <= interval[0] and interval[1] <= upper:
            model_status = "passed"
        elif interval[1] < lower or interval[0] > upper:
            model_status = "failed"
            reasons.append("measurement interval is outside tolerance")
        else:
            reasons.append("measurement interval crosses tolerance boundary")
    output = dict(output_evidence or {})
    review_validation = validate_review(
        output, ledger, measurement, output_annotation or {}, binding_validation or {}
    )
    output_pass = review_validation["status"] == "verified"
    original_status = "passed" if not original_errors else "pending"
    output_failed = review_validation["status"] == "rejected"
    output_status = (
        "passed" if output_pass else "failed" if output_failed else "pending"
    )
    return {
        "result_version": RESULT_VERSION,
        "dim_id": ledger.get("dim_id"),
        "original_interpretation": {
            "status": original_status,
            "reasons": original_errors,
        },
        "model_measurement": {
            "status": model_status,
            "interval": interval,
            "reasons": reasons,
        },
        "output_expression": {
            "status": output_status,
            "evidence": output,
            "validation": review_validation,
        },
        "value_verified": ledger.get("value_status") == "verified",
        "association_verified": ledger.get("association_status") == "verified",
        "layout_reviewed": review_validation.get("identity_verified", False)
        and output.get("layout_status") == "reviewed",
        "status": (
            "passed"
            if original_status == model_status == "passed" and output_pass
            else "failed" if model_status == "failed" or output_failed else "pending"
        ),
    }


def summarize_dimension_coverage_rreport(
    verdicts: Sequence[Mapping[str, Any]],
    *,
    expected_dim_ids: Sequence[str],
) -> dict[str, Any]:
    """Count value, association and layout against every expected ledger DIM ID.

    Missing verdict rows count as unverified in all columns. Duplicate or
    unexpected IDs raise, so coverage cannot hide omitted ledger entries.
    """
    ids = [row["dim_id"] for row in verdicts]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate DIM IDs in coverage")
    if len(expected_dim_ids) != len(set(expected_dim_ids)) or set(ids) - set(
        expected_dim_ids
    ):
        raise ValueError("duplicate expected or unexpected DIM IDs")
    verdicts = list(verdicts) + [
        {"dim_id": dim} for dim in expected_dim_ids if dim not in ids
    ]
    return {
        "total": len(expected_dim_ids),
        **{
            key: {
                "count": sum(bool(row.get(key)) for row in verdicts),
                "missing": [row["dim_id"] for row in verdicts if not row.get(key)],
            }
            for key in ("value_verified", "association_verified", "layout_reviewed")
        },
    }


def build_section_annotation_rrecord(
    measurement: Mapping[str, Any],
    ledger: Mapping[str, Any],
    *,
    error_assessment: Mapping[str, Any] | None = None,
    anchor: Sequence[float] | None = None,
    display_decimals: int | None = None,
) -> dict[str, Any]:
    """Build a bound annotation from a verified DIM and measurement record.

    Pass a continuous measurement with its total error assessment and the
    verified ledger schema of assess_dimension_rverdict. ``anchor`` is a local
    section point on the selected target geometry. Without it the renderer
    uses a placeholder and formal association validation cannot pass.
    Display decimals default to one guard digit beyond tolerance-band width.
    The formatter's step must not exceed band width, rounding error must not
    exceed half its width, and the displayed number must remain in the band.
    A zero-width band requires exact decimal representation. Insufficient
    precision raises even for an explicit display_decimals override.
    Independent validation against the current model is still required.
    A measurement whose section_validation is missing, pending or failed cannot
    produce a verified annotation, even if its numerical value fits tolerance.
    """
    verdict = assess_dimension_rverdict(
        ledger, measurement, error_assessment=error_assessment
    )
    if (
        verdict["original_interpretation"]["status"] != "passed"
        or verdict["model_measurement"]["status"] != "passed"
    ):
        raise ValueError(f"DIM cannot be annotated as verified: {verdict}")
    if ledger.get("target_geometry") != measurement.get("target_geometry"):
        raise ValueError("measurement target does not match reviewed ledger geometry")
    if display_decimals is None:
        width = float(ledger["tolerance_max"]) - float(ledger["tolerance_min"])
        display_decimals = (
            max(0, min(12, 1 - math.floor(math.log10(width)))) if width > 0 else 12
        )
    precision = display_precision(measurement["value"], display_decimals, ledger)
    if precision["status"] != "verified":
        raise ValueError(f"insufficient display precision: {precision['errors']}")
    return deepcopy(
        {
            "result_version": RESULT_VERSION,
            "dim_id": ledger["dim_id"],
            "feature_id": ledger["feature_id"],
            "view": ledger["view"],
            "kind": measurement["kind"],
            "measurement_contract": measurement["measurement_contract"],
            "measured": measurement["value"],
            "nominal": ledger.get("nominal"),
            "tol": ledger.get("tol"),
            "measurement_id": measurement["measurement_id"],
            "model_hash": measurement["model_hash"],
            "section_id": measurement["section_id"],
            "plane": measurement["plane"],
            "target_geometry": measurement["target_geometry"],
            "configuration": measurement["configuration"],
            "error_assessment": dict(error_assessment or {}),
            "anchor": list(anchor) if anchor is not None else None,
            "anchor_kind": "feature" if anchor is not None else "placeholder",
            "display_decimals": display_decimals,
            "units": "mm",
            "coordinate_space": "section_local",
        }
    )


def validate_section_annotations_rreport(
    model: Any,
    plane: Mapping[str, Sequence[float]],
    dimensions: Sequence[Mapping[str, Any]],
    ledger: Sequence[Mapping[str, Any]],
    *,
    anchor_tolerance_mm: float = 1e-5,
) -> dict[str, Any]:
    """Remeasure current BREP and reject forged values, targets, IDs and stale evidence.

    The independent rerun uses the recorded algorithm configuration, comparing
    unrounded values exactly. Anchors must lie on selected continuous geometry
    within anchor_tolerance_mm (association check only, not dimensional accuracy).
    The ledger's measurement_contract separately binds kind, direction, definition
    and line point, as well as units/coordinate space. Its feature mapping and
    the actual rounding error/display step are checked independently of the number.
    The ledger is the separately reviewed feature mapping; caller-supplied raw
    annotation metadata is never its own source of truth. Layout review is separate.
    """
    from .section import measure_model_section_rdimensions

    if not math.isfinite(anchor_tolerance_mm) or anchor_tolerance_mm <= 0:
        raise ValueError("anchor_tolerance_mm must be finite and positive")
    by_dim = {row["dim_id"]: row for row in ledger}
    if len(by_dim) != len(ledger):
        raise ValueError("duplicate DIM IDs in ledger")
    cache = {}
    results = []
    seen = set()
    for annotation in dimensions:
        dim_id = annotation.get("dim_id")
        errors = []
        annotation_id = None
        if dim_id in seen:
            errors.append("duplicate DIM annotation")
        seen.add(dim_id)
        try:
            annotation_id = digest(annotation)
            entry = by_dim[dim_id]
            config = dict(annotation["configuration"])
            if not entry.get("section_checks") or entry.get(
                "section_checks"
            ) != config.get("section_checks"):
                errors.append(
                    "section_checks differs from independently reviewed ledger"
                )
            method = config.pop("contour_method")
            cache_key = str(sorted(config.items()))
            if cache_key not in cache:
                measured = measure_model_section_rdimensions(model, plane, **config)
                section, edges = section_geometry(
                    model,
                    plane,
                    config["tolerance"],
                    config["samples_per_edge"],
                    section_strategy=config["section_strategy"],
                    section_checks=config["section_checks"],
                )
                cache[cache_key] = measured, section, edges
            measured, section, edges = cache[cache_key]
            if section["validation"]["status"] != "passed":
                errors.append(f"section checks did not pass: {section['validation']}")
            if measured.configuration["contour_method"] != method:
                errors.append("section method changed")
            record = next(
                (
                    m
                    for m in measured.measurements
                    if m["measurement_id"] == annotation["measurement_id"]
                ),
                None,
            )
            if record is None:
                errors.append(
                    "measurement ID is stale or not derived from current model/section/configuration"
                )
            else:
                for key in (
                    "model_hash",
                    "section_id",
                    "plane",
                    "target_geometry",
                    "kind",
                    "measurement_contract",
                ):
                    if annotation.get(key) != record[key]:
                        errors.append(f"{key} does not match independent measurement")
                if annotation.get("measured") != record["value"]:
                    errors.append(
                        "displayed measurement differs from unrounded geometric value"
                    )
                for key in ("feature_id", "view"):
                    if annotation.get(key) != entry.get(key):
                        errors.append(f"{key} differs from reviewed ledger")
                for key in ("nominal", "tol"):
                    if annotation.get(key) != entry.get(key):
                        errors.append(f"displayed {key} differs from reviewed ledger")
                for key in ("units", "coordinate_space", "result_version"):
                    if annotation.get(key) != record[key]:
                        errors.append(f"annotation {key} differs from measurement")
                precision = display_precision(
                    record["value"], annotation.get("display_decimals"), entry
                )
                errors.extend(precision["errors"])
                errors.extend(contract_errors(entry, record))
                if entry.get("target_geometry") != record["target_geometry"]:
                    errors.append(
                        "target geometry differs from independently reviewed feature mapping"
                    )
                verdict = assess_dimension_rverdict(
                    entry,
                    record,
                    error_assessment=annotation.get("error_assessment") or None,
                )
                if any(
                    verdict[k]["status"] != "passed"
                    for k in ("original_interpretation", "model_measurement")
                ):
                    errors.append("interpretation or precision gate did not pass")
                anchor = annotation.get("anchor")
                if annotation.get("anchor_kind") != "feature" or anchor is None:
                    errors.append(
                        "placeholder anchor is not feature association evidence"
                    )
                else:
                    p = np.asarray(anchor, dtype=float)
                    if p.shape != (2,) or not np.isfinite(p).all():
                        raise ValueError("anchor must be a finite 2D point")
                    target_edges = record["target_geometry"]["edge_indices"]
                    if target_edges and edges:
                        world = np.asarray(section["plane"]["origin"]) + p @ np.asarray(
                            [
                                section["plane"]["x_direction"],
                                section["plane"]["y_direction"],
                            ]
                        )
                        vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*world)).Vertex()
                        distance = BRepExtrema_DistShapeShape(
                            vertex, compound([edges[e] for e in target_edges])
                        )
                        distance.Perform()
                        anchored = (
                            distance.IsDone()
                            and distance.Value() <= anchor_tolerance_mm
                        )
                    elif record.get("kind") == "thickness_directional":
                        anchored = any(
                            np.linalg.norm(p - np.asarray(a)) <= anchor_tolerance_mm
                            for a in record["anchors"]
                        )
                    else:
                        anchored = False
                    if not anchored:
                        errors.append(
                            "anchor is not on the selected continuous target geometry"
                        )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid binding: {exc}")
        results.append(
            {
                "dim_id": dim_id,
                "annotation_id": annotation_id,
                "status": "verified" if not errors else "rejected",
                "errors": errors,
                **{
                    k: annotation.get(k)
                    for k in ("measurement_id", "model_hash", "section_id")
                },
            }
        )
    return {
        "result_version": RESULT_VERSION,
        "status": (
            "verified"
            if results and all(r["status"] == "verified" for r in results)
            else "rejected"
        ),
        "dimensions": results,
    }
