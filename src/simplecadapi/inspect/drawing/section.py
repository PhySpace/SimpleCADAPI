"""Model-side section evidence: cut the rebuilt model where the drawing cuts it.

The drawing's section views are cross-sections of the real part; the
reconstruction workflow verifies them by cutting the rebuilt model at the
same planes and pairing the rendered section with the original view for
isolated review. Plane parsing from drawing conventions lives in the skill
layer; these functions take an explicit plane and stay factual.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    import pymupdf
else:
    from ._pymupdf import pymupdf

import numpy as np

from ._provenance import digest, model_metadata, pixel_transform, file_hash
from ._measurement_contract import measurement_contract
from ._circle_fit import fit_circle_diagnostics, fit_circle_legacy
from ._section_geometry import (
    section_geometry,
    compound,
    continuous_bounds,
    analytic_circle,
    continuous_gap,
    directional_material,
    edge_diagnostics,
)

_HATCH_SPACING_MM = 2.0
_GEOMETRY_COLOR = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class DrawingSectionDimensions:
    """Candidate dimensions measured from one model section.

    Entries are candidates, not verdicts: the caller picks the ones that
    correspond to ledger rows and passes them back to
    :func:`render_model_section_rpath` with ``dim_id`` / ``nominal`` filled
    in. ``thickness`` candidates arise only from nested contour pairs; wall
    thickness of side-by-side strips shows up as a contour ``extent``.
    ``section_validation`` separately reports closure, material topology and
    solid/section/display point checks; ``circle_diagnostics`` includes open
    contours and rejected fits. Neither output turns an uncertain value into
    a verified dimension.
    """

    source: str
    plane: dict[str, Any]
    closed_contour_count: int
    open_contour_count: int
    measurements: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)
    section_validation: dict[str, Any] = field(default_factory=dict)
    circle_diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output


def _contour_points(contour: Mapping[str, Any]) -> list[tuple[float, float]]:
    points = [(float(p[0]), float(p[1])) for p in contour["samples_2d"]]
    if contour.get("closed") and len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def _subsample(points: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    """Historical audit helper; production continuous measurements do not use it."""
    step = max(1, len(points) // 120)
    return [(float(p[0]), float(p[1])) for p in points[::step]]


def _point_in_polygon(
    point: Sequence[float], polygon: Sequence[Sequence[float]]
) -> bool:
    inside = False
    x, y = float(point[0]), float(point[1])
    count = len(polygon)
    for index in range(count):
        x0, y0 = polygon[index]
        x1, y1 = polygon[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            cross = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0)
            if cross > 0 if y1 > y0 else cross < 0:
                inside = not inside
    return inside


def _min_distance(points_a, points_b) -> float:
    return min(math.hypot(a[0] - b[0], a[1] - b[1]) for a in points_a for b in points_b)


def _fit_circle(points):
    """Historical numerical helper; use circle diagnostics for acceptance."""
    return fit_circle_legacy(points)


def measure_model_section_rdimensions(
    model: Any,
    plane: Mapping[str, Sequence[float]],
    *,
    tolerance: float = 1.0e-7,
    samples_per_edge: int = 64,
    circle_tolerance: float = 0.02,
    directional_thickness: Sequence[Mapping[str, Any]] | None = None,
    section_strategy: str = "auto",
    section_checks: Mapping[str, Any] | None = None,
    circle_min_coverage_degrees: float = 270.0,
) -> DrawingSectionDimensions:
    """Cut the model at one plane and measure candidate dimensions.

    ``plane`` is ``{"origin": [x, y, z], "normal": [nx, ny, nz]}`` in model
    coordinates; ``model`` is a live shape or a STEP path. Candidates come
    from actual section edges: analytic circles precede fitted-circle
    candidates, extents use continuous BREP bounds and nested contour gaps
    use continuous BREP distance. Pair nesting remains a sampled association
    candidate in edges mode; material mode uses topological outer/inner wires.
    ``directional_thickness`` entries require ``id``, a local 2D
    ``point`` and nonzero ``direction``; each connected material interval on
    that line is reported separately. A radial query uses a center as point
    and the specified radial direction; select the intended interval explicitly.
    Records contain method, contour/edge IDs, configuration, accuracy class,
    residuals, source/model/section hashes and content-derived measurement IDs.
    ``measurement_contract`` identifies kind, definition, direction, line point,
    units and coordinate space separately from target_geometry. The ledger must
    independently specify that contract; width and height on one contour differ.
    Error bounds are unknown unless independently established: neither kernel
    tolerance nor circle-fit residual proves total dimensional accuracy.

    ``section_strategy`` selects auto (material faces for solids, edges for
    non-solid diagnostics), material (solid/plane face intersection), or edges
    (section edges). It replaces the environment-variable fallback; even closed
    contours may use material mode. The actual contour_method is recorded.
    ``section_checks`` supplies independently resolved expected_origin/normal/
    x_direction/y_direction, expected_solid_count/face_count/hole_count, lists of
    material_points and void_points ({id, point:[u,v]}), point_tolerance_mm,
    tolerance_basis and evidence. Every face and hole needs representative point
    coverage. Edges mode also computes a material-face reference for these checks.
    The same contract must appear in each corresponding ledger row. Missing or
    uncertain checks keep formal evidence pending. No mass, centroid, inertia or
    high-precision volume-equivalence gates are added.
    ``circle_min_coverage_degrees`` defaults to 270 for sampled fit candidates.
    Diagnostics include coverage, maximum angular gap, conditioning and RMS/max
    residual; open contours and degenerate samples never establish a full circle.
    Analytic full-circle geometry has its own exact angular-coverage check.
    """
    if not math.isfinite(circle_tolerance) or circle_tolerance < 0:
        raise ValueError("circle_tolerance must be finite and non-negative")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    if (
        not math.isfinite(circle_min_coverage_degrees)
        or not 0 < circle_min_coverage_degrees <= 360
    ):
        raise ValueError("circle_min_coverage_degrees must be in (0, 360]")
    section, edge_shapes = section_geometry(
        model,
        plane,
        tolerance,
        samples_per_edge,
        section_strategy=section_strategy,
        section_checks=section_checks,
    )
    configuration = {
        "tolerance": tolerance,
        "samples_per_edge": samples_per_edge,
        "circle_tolerance": circle_tolerance,
        "directional_thickness": [dict(q) for q in directional_thickness or ()],
        "contour_method": section.get("contour_method", "section_edges"),
        "section_strategy": section_strategy,
        "section_checks": dict(section_checks) if section_checks is not None else None,
        "circle_min_coverage_degrees": circle_min_coverage_degrees,
    }
    if len({q["id"] for q in configuration["directional_thickness"]}) != len(
        configuration["directional_thickness"]
    ):
        raise ValueError("directional thickness request IDs must be unique")
    metadata = model_metadata(model)
    metadata["section_id"] = digest(section["plane"])

    closed = [
        contour
        for contour in section["contours"]
        if contour["closed"] and contour["area"] is not None
    ]
    measurements: list[dict[str, Any]] = []
    circle_diagnostics = []
    for contour in section["contours"]:
        fit = fit_circle_diagnostics(
            _contour_points(contour), min_coverage_degrees=circle_min_coverage_degrees
        )
        fit.update(contour=contour["index"], closed=contour["closed"])
        if not contour["closed"]:
            fit.update(
                status="open_contour",
                reason="open or gapped contours cannot establish a complete circular feature",
            )
        circle_diagnostics.append(fit)
    fits_by_contour = {fit["contour"]: fit for fit in circle_diagnostics}

    polygon_cache: dict[int, list[tuple[float, float]]] = {}
    shape_cache = {}
    for contour in closed:
        index = contour["index"]
        points = _contour_points(contour)
        count = len(points)
        if count < 3:
            continue
        polygon_cache[index] = points
        fit = fits_by_contour[index]
        edges = [edge_shapes[e] for e in contour["edge_indices"]] if edge_shapes else []
        circle = analytic_circle(edges, section["plane"])
        if circle:
            fit.update(
                status="analytic_circle",
                reason="closed analytic circular BREP edges",
                analytic_coverage_degrees=360.0,
            )
            measurements.append({"kind": "diameter", "contour": index, **circle})
        elif (
            fit["status"] == "candidate"
            and fit["relative_rms"] <= circle_tolerance
            and fit["residual_max_mm"] / fit["radius"] <= circle_tolerance
        ):
            measurements.append(
                {
                    "kind": "diameter",
                    "value": 2.0 * fit["radius"],
                    "center": fit["center"],
                    "contour": index,
                    "radius_deviation": fit["relative_rms"],
                    "fit_residual_rms_mm": fit["residual_rms_mm"],
                    "fit_residual_max_mm": fit["residual_max_mm"],
                    "circle_coverage_degrees": fit["coverage_degrees"],
                    "method": "least_squares_circle_candidate",
                    "accuracy_class": "fit_candidate",
                }
            )
        elif fit["status"] == "candidate":
            fit.update(
                status="residual_rejected",
                reason="circle residual exceeds candidate threshold",
            )
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        if edges:
            shape_cache[index] = compound(edges)
            bounds = continuous_bounds(shape_cache[index], section["plane"])
            min_x, min_y, max_x, max_y = bounds[0], bounds[1], bounds[3], bounds[4]
        extent_method = "brep_continuous_bounds" if edges else "sampled_bounds"
        extent_accuracy = "continuous_numeric" if edges else "sampled_approximation"
        measurements.append(
            {
                "kind": "extent_width",
                "value": max_x - min_x,
                "contour": index,
                "span": [min_x, max_x],
                "direction": [1.0, 0.0],
                "method": extent_method,
                "accuracy_class": extent_accuracy,
            }
        )
        measurements.append(
            {
                "kind": "extent_height",
                "value": max_y - min_y,
                "contour": index,
                "span": [min_y, max_y],
                "direction": [0.0, 1.0],
                "method": extent_method,
                "accuracy_class": extent_accuracy,
            }
        )

    indices = list(polygon_cache)
    closed_by_id = {contour["index"]: contour for contour in closed}
    for position, i in enumerate(indices):
        for j in indices[position + 1 :]:
            if section["contour_method"] == "material_face_intersection":
                a, b = closed_by_id[i], closed_by_id[j]
                if a["face_index"] != b["face_index"] or a["role"] == b["role"]:
                    continue
                outer, inner = (i, j) if a["role"] == "material" else (j, i)
                pair_method = "brep_face_inner_outer_wires"
            elif _point_in_polygon(polygon_cache[j][0], polygon_cache[i]):
                inner, outer = j, i
                pair_method = "sampled_polygon_nesting"
            elif _point_in_polygon(polygon_cache[i][0], polygon_cache[j]):
                inner, outer = i, j
                pair_method = "sampled_polygon_nesting"
            else:
                continue
            if shape_cache:
                gap = continuous_gap(
                    shape_cache[outer], shape_cache[inner], section["plane"]
                )
            else:
                gap = {
                    "value": _min_distance(polygon_cache[inner], polygon_cache[outer]),
                    "method": "sampled_point_distance",
                    "accuracy_class": "sampled_approximation",
                }
            measurements.append(
                {
                    "kind": "thickness",
                    **gap,
                    "contours": [outer, inner],
                    "definition": "minimum_boundary_gap",
                    "association_status": "candidate",
                    "pair_selection_method": pair_method,
                }
            )

    for query in configuration["directional_thickness"]:
        measurements.extend(directional_material(model, section["plane"], query))
    contours_by_id = {c["index"]: c for c in closed}
    for measurement in measurements:
        ids = measurement.get(
            "contours", [measurement["contour"]] if "contour" in measurement else []
        )
        measurement["target_geometry"] = {
            "contours": ids,
            "edge_indices": [e for c in ids for e in contours_by_id[c]["edge_indices"]],
            "request_id": measurement.get("request_id"),
            "interval": measurement.get("interval"),
        }
        measurement.update(
            edge_diagnostics(
                [edge_shapes[e] for e in measurement["target_geometry"]["edge_indices"]]
            )
            if edge_shapes
            else {"geometry_types": [], "kernel_edge_tolerance_mm_max": None}
        )
        measurement.update(
            {
                "model_hash": metadata["model_hash"],
                "section_id": metadata["section_id"],
                "plane": section["plane"],
                "source_id": metadata["source_id"],
                "result_version": metadata["result_version"],
                "coordinate_space": "section_local",
                "units": "mm",
                "configuration": configuration,
                "section_validation": section["validation"],
                "error_bound_mm": None,
                "error_bound_basis": "unknown; intersection tolerance and fit residual are not total error bounds",
            }
        )
        measurement.setdefault(
            "definition",
            (
                "circle_diameter"
                if measurement["kind"] == "diameter"
                else "axis_aligned_extent"
            ),
        )
        measurement["measurement_contract"] = measurement_contract(measurement)
        measurement["measurement_id"] = digest(measurement)
    return DrawingSectionDimensions(
        source=str(model) if isinstance(model, (str, Path)) else "in_memory_brep",
        plane=section["plane"],
        closed_contour_count=section["closed_contour_count"],
        open_contour_count=section["open_contour_count"],
        measurements=measurements,
        metadata=metadata,
        configuration=configuration,
        section_validation=section["validation"],
        circle_diagnostics=circle_diagnostics,
    )


def _hatch_segments(
    polygons: Sequence[Sequence[Sequence[float]]], spacing: float
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Even-odd 45-degree hatch spans across nested polygon sets."""
    if not polygons:
        return []
    offsets = []
    for polygon in polygons:
        for point in polygon:
            offsets.append(float(point[1]) - float(point[0]))
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    start = math.floor(min(offsets) / spacing) * spacing
    count = int((max(offsets) - start) / spacing) + 1
    for index in range(count + 1):
        c = start + index * spacing
        crossings: list[float] = []
        for polygon in polygons:
            total = len(polygon)
            for k in range(total):
                x0, y0 = polygon[k]
                x1, y1 = polygon[(k + 1) % total]
                d0, d1 = y0 - x0 - c, y1 - x1 - c
                if (d0 > 0) == (d1 > 0) or d0 == d1:
                    continue
                u = d0 / (d0 - d1)
                crossings.append(x0 + u * (x1 - x0))
        crossings.sort()
        for k in range(0, len(crossings) - 1, 2):
            xa, xb = crossings[k], crossings[k + 1]
            segments.append(((xa, xa + c), (xb, xb + c)))
    return segments


def render_model_section_rpath(
    model: Any,
    plane: Mapping[str, Sequence[float]],
    *,
    dimensions: Sequence[Mapping[str, Any]] | None = None,
    hatch: bool = True,
    dpi: int = 200,
    margin_mm: float = 8.0,
    target_size_pt: tuple[float, float] = (1100.0, 850.0),
    out_dir: str | Path = ".",
    stem: str | None = None,
    validation_ledger: Sequence[Mapping[str, Any]] | None = None,
    section_strategy: str = "auto",
    section_checks: Mapping[str, Any] | None = None,
    samples_per_edge: int = 64,
) -> Path:
    """Render the model section at one plane as an annotated evidence image.

    Fixed output: ``<stem>.png`` (the annotated model-section render), plus
    ``<stem>.json`` (sidecar with plane, dimension echo, and file list).
    ``dimensions`` entries carry ``dim_id``, ``kind``, ``measured`` and
    optional ``nominal`` / ``tol`` / ``anchor`` (plane-space ``[x, y]``);
    values are caller-supplied data, not proof of correct measurement.
    ``validation_ledger`` enables formal evidence: independently remeasure and
    validate bound annotations before writing files; invalid bindings raise.
    Sidecars retain unrounded values, target/result/model/section IDs, complete
    local-to-canvas-to-pixel transforms, text boxes and leader paths. Readability
    and feature association are separate review fields. Missing anchors are
    placeholders, never feature-association evidence.
    Each annotation receives a content-derived annotation_id. The sidecar records
    the PNG's image_sha256; a visual reviewer must retain both file hashes and the
    reviewed measurement/model/section IDs for subsequent acceptance.
    ``section_strategy`` has the same meanings as in measurement; ``samples_per_edge``
    controls the actual displayed polygons. ``section_checks`` is explicit or,
    for formal output, read from the unanimous independently reviewed ledger
    contract. Formal output rejects open contours, invalid material faces, missing
    ring/probe coverage, wrong frames, and solid/section/display disagreements.
    Raw rendering is allowed for diagnostics and is labeled diagnostic_only in
    the sidecar. Check section definition/intersection/display before considering
    model changes, and require independent solid evidence of any geometry error.
    """
    from ._section_layout import label_rows, draw_annotations
    from .evidence import validate_section_annotations_rreport

    if (
        not isinstance(dpi, int)
        or dpi <= 0
        or not math.isfinite(margin_mm)
        or margin_mm <= 0
    ):
        raise ValueError(
            "dpi must be a positive integer and margin_mm finite and positive"
        )
    if len(target_size_pt) != 2 or any(
        not math.isfinite(v) or v <= 0 for v in target_size_pt
    ):
        raise ValueError("target_size_pt must contain two finite positive sizes")
    dimensions = list(dimensions or ())
    rows, label_width, label_height = label_rows(dimensions)
    binding_report = None
    if validation_ledger is not None:
        expected_checks = [row.get("section_checks") for row in validation_ledger]
        if (
            not expected_checks
            or not expected_checks[0]
            or any(c != expected_checks[0] for c in expected_checks)
        ):
            raise ValueError(
                "formal section requires one independently reviewed section_checks contract"
            )
        if section_checks is None:
            section_checks = expected_checks[0]
        elif section_checks != expected_checks[0]:
            raise ValueError("render section_checks differs from reviewed ledger")
        binding_report = validate_section_annotations_rreport(
            model, plane, dimensions, validation_ledger
        )
        if binding_report["status"] != "verified":
            raise ValueError(
                f"section annotation validation rejected: {binding_report}"
            )
    section, _ = section_geometry(
        model,
        plane,
        samples_per_edge=samples_per_edge,
        section_strategy=section_strategy,
        section_checks=section_checks,
    )
    if validation_ledger is not None:
        if section["validation"]["status"] != "passed":
            raise ValueError(
                f"formal section evidence rejected: {section['validation']}"
            )
        if any(
            d["configuration"]["contour_method"] != section["contour_method"]
            for d in dimensions
        ):
            raise ValueError("render section method differs from bound measurements")
    contours = [contour for contour in section["contours"] if contour["samples_2d"]]
    if not contours:
        raise ValueError(
            "section produced no contours at the given plane; check plane placement"
        )

    all_points = [
        (float(p[0]), float(p[1]))
        for contour in contours
        for p in contour["samples_2d"]
    ]
    for dimension in dimensions or ():
        anchor = dimension.get("anchor")
        if anchor is not None:
            all_points.append((float(anchor[0]), float(anchor[1])))
    min_x = min(p[0] for p in all_points)
    max_x = max(p[0] for p in all_points)
    min_y = min(p[1] for p in all_points)
    max_y = max(p[1] for p in all_points)

    # Slender parts read best with the long side horizontal: rotate 90° in
    # plane when the section is taller than wide.
    rotated_section = max_y - min_y > max_x - min_x
    if rotated_section:
        rotated = [((p[1]), (-p[0])) for p in all_points]
        min_x, max_x = min(p[0] for p in rotated), max(p[0] for p in rotated)
        min_y, max_y = min(p[1] for p in rotated), max(p[1] for p in rotated)
        remap = lambda p: (p[1], -p[0])  # noqa: E731
    else:
        remap = lambda p: (p[0], p[1])  # noqa: E731

    span_x = max(max_x - min_x, 1.0e-6) + 2.0 * margin_mm
    span_y = max(max_y - min_y, 1.0e-6) + 2.0 * margin_mm
    scale = min(target_size_pt[0] / span_x, target_size_pt[1] / span_y)
    canvas_w = span_x * scale
    canvas_h = span_y * scale
    geometry_w, geometry_h = canvas_w, canvas_h
    if dimensions:
        canvas_w += label_width
        canvas_h = max(canvas_h, label_height)

    def to_canvas(point: Sequence[float]) -> tuple[float, float]:
        return (
            (float(point[0]) - min_x + margin_mm) * scale,
            geometry_h - (float(point[1]) - min_y + margin_mm) * scale,
        )

    with pymupdf.open() as document:
        page = document.new_page(width=canvas_w, height=canvas_h)

        closed_polygons = [
            [remap(point) for point in _contour_points(contour)]
            for contour in contours
            if contour["closed"] and len(_contour_points(contour)) >= 3
        ]
        if hatch and closed_polygons:
            for segment in _hatch_segments(closed_polygons, _HATCH_SPACING_MM):
                page.draw_line(
                    to_canvas(segment[0]),
                    to_canvas(segment[1]),
                    color=(0.45, 0.45, 0.45),
                    width=0.5,
                )

        for contour in contours:
            points = [remap(point) for point in _contour_points(contour)]
            if len(points) < 2:
                continue
            canvas_points = [to_canvas(p) for p in points]
            if contour["closed"]:
                canvas_points.append(canvas_points[0])
            for k in range(len(canvas_points) - 1):
                page.draw_line(
                    canvas_points[k],
                    canvas_points[k + 1],
                    color=_GEOMETRY_COLOR,
                    width=1.0,
                )

        annotation_records, layout = draw_annotations(
            page,
            dimensions,
            rows,
            geometry_w,
            lambda point: to_canvas(remap(point)),
            binding_report,
        )

        preferred_bar = max((max_x - min_x) / 3, 1e-6)
        magnitude = 10 ** math.floor(math.log10(preferred_bar))
        bar_mm = max(v * magnitude for v in (1, 2, 5) if v * magnitude <= preferred_bar)
        bar_start = to_canvas((min_x, min_y - margin_mm / 2.0))
        bar_end = to_canvas((min_x + bar_mm, min_y - margin_mm / 2.0))
        page.draw_line(bar_start, bar_end, color=_GEOMETRY_COLOR, width=1.0)
        page.insert_text(
            (bar_start[0], bar_start[1] - 3.0), f"{bar_mm:g} mm", fontsize=6
        )

        output_dir = Path(out_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        name_stem = stem if stem else "section"
        png_path = output_dir / f"{name_stem}.png"
        pixmap = page.get_pixmap(dpi=dpi)
        pixmap.save(png_path)
        rotation_matrix = (
            np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
            if rotated_section
            else np.eye(3)
        )
        canvas_transform = (
            np.array(
                [
                    [scale, 0, (-min_x + margin_mm) * scale],
                    [0, -scale, geometry_h + (min_y - margin_mm) * scale],
                    [0, 0, 1],
                ]
            )
            @ rotation_matrix
        )
        pixels = pixel_transform(dpi / 72, pixmap.x, pixmap.y)
        to_pixel = np.asarray(pixels["page_to_pixel"]) @ canvas_transform
        for record in annotation_records:

            def pixel_point(point):
                return (np.asarray(pixels["page_to_pixel"]) @ [*point, 1])[:2].tolist()

            box = record["text_box_pt"]
            record["text_box_px"] = pixel_point(box[:2]) + pixel_point(box[2:])
            record["leader_path_px"] = [
                pixel_point(p) for p in record["leader_path_pt"]
            ]
        metadata = model_metadata(model)
        metadata["section_id"] = digest(section["plane"])

        written = [png_path.name]
        sidecar_path = output_dir / f"{name_stem}.json"
        sidecar_path.write_text(
            json.dumps(
                {
                    **metadata,
                    "metadata": metadata,
                    "source_model": (
                        str(model)
                        if isinstance(model, (str, Path))
                        else "in_memory_brep"
                    ),
                    "plane": section["plane"],
                    "rotation_degrees": -90 if rotated_section else 0,
                    "scale_pt_per_mm": scale,
                    "canvas_rect_pt": [0, 0, canvas_w, canvas_h],
                    "geometry_rect_pt": [0, 0, geometry_w, geometry_h],
                    "pixel_size": [pixmap.width, pixmap.height],
                    "local_to_canvas": canvas_transform.tolist(),
                    "canvas_to_local": np.linalg.inv(canvas_transform).tolist(),
                    "local_to_pixel": to_pixel.tolist(),
                    "pixel_to_local": np.linalg.inv(to_pixel).tolist(),
                    "pixel_transform": pixels,
                    "layout": layout,
                    "binding_validation": binding_report or {"status": "unverified"},
                    "section_strategy": section_strategy,
                    "contour_method": section["contour_method"],
                    "section_checks": section_checks,
                    "section_validation": section["validation"],
                    "evidence_status": (
                        "formal" if validation_ledger is not None else "diagnostic_only"
                    ),
                    "render_sampling": {
                        "samples_per_edge": samples_per_edge,
                        "accuracy": "visual approximation",
                    },
                    "closed_contour_count": section["closed_contour_count"],
                    "open_contour_count": section["open_contour_count"],
                    "dimensions": annotation_records,
                    "image_sha256": file_hash(png_path),
                    "files": written,
                    "hatch": hatch,
                    "dpi": dpi,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return png_path
