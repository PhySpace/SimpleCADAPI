#!/usr/bin/env python3
"""Regenerate the reviewed STEP feature examples with formal SimpleCADAPI."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import runpy

import numpy as np
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.model import _bounding_box


APPROVED_OUTPUT_ROOT = Path(r"D:\Code\step-feat\feat\math-vis-eg")
V3_FEATURE_KINDS = (
    "hole",
    "extrusion",
    "revolution",
    "fillet",
    "chamfer",
    "sheet_metal",
)
V4_FEATURE_KINDS = (
    "hole",
    "extrusion",
    "revolution",
    "loft",
    "sweep",
    "fillet",
    "chamfer",
    "sheet_metal",
)


def _meridian_face(inner: float, outer: float, start: float, end: float):
    wire = scad.make_polyline_rwire(
        points=[
            (inner, 0.0, start),
            (outer, 0.0, start),
            (outer, 0.0, end),
            (inner, 0.0, end),
        ],
        closed=True,
    )
    return scad.make_face_from_wire_rface(wire=wire, normal=(0.0, 1.0, 0.0))


def _revolved(inner=2.0, outer=4.0, start=-2.0, end=2.0, angle=360.0):
    return scad.revolve_rsolid(
        _meridian_face(inner, outer, start, end),
        axis=(0.0, 0.0, 1.0),
        angle=angle,
        origin=(0.0, 0.0, 0.0),
    )


def _box(depth=16.0):
    return scad.make_box_rsolid(
        width=50.0,
        height=36.0,
        depth=depth,
        bottom_face_center=(0.0, 0.0, 0.0),
    )


def _extrusion_case(form: str):
    if form == "whole_body_prism":
        return _box()
    if form in {"local_boss", "rib_or_web"}:
        width, height = (18.0, 12.0) if form == "local_boss" else (30.0, 4.0)
        boss = scad.make_box_rsolid(
            width=width,
            height=height,
            depth=8.0,
            bottom_face_center=(0.0, 0.0, 8.0),
        )
        return scad.union_rsolid(_box(depth=8.0), boss, clean=False)
    if form == "blind_pocket":
        cutter = scad.make_box_rsolid(
            width=24.0,
            height=16.0,
            depth=10.0,
            bottom_face_center=(0.0, 0.0, 7.0),
        )
    elif form == "open_slot_or_notch":
        cutter = scad.make_box_rsolid(
            width=28.0,
            height=10.0,
            depth=9.0,
            bottom_face_center=(18.0, 0.0, 8.0),
        )
    else:
        cutter = scad.make_box_rsolid(
            width=18.0,
            height=14.0,
            depth=18.0,
            bottom_face_center=(20.0, 0.0, -1.0),
        )
    return scad.cut_rsolid(_box(), cutter, skip_non_intersecting=False)


def _shaft(radius=4.0):
    return scad.make_cylinder_rsolid(
        radius=radius,
        height=12.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )


def _full_revolved_local(additive: bool):
    feature = _revolved(
        inner=4.0,
        outer=6.0 if additive else 7.0,
        start=4.0,
        end=7.0,
    )
    if additive:
        return scad.union_rsolid(_shaft(), feature, clean=False)
    return scad.cut_rsolid(_shaft(radius=6.0), feature, skip_non_intersecting=False)


def _partial_revolved_boss():
    feature = _revolved(inner=4.0, outer=6.0, start=4.0, end=7.0, angle=90.0)
    return scad.union_rsolid(_shaft(), feature, clean=False)


def _circular_hole():
    cutter = scad.make_cylinder_rsolid(
        radius=3.0,
        height=18.0,
        bottom_face_center=(0.0, 0.0, -1.0),
    )
    return scad.cut_rsolid(_box(), cutter, skip_non_intersecting=False)


def _loft(scale: float, twist_degrees: float):
    bottom = [(-8.0, -5.0, 0.0), (8.0, -5.0, 0.0), (8.0, 5.0, 0.0), (-8.0, 5.0, 0.0)]
    angle = math.radians(twist_degrees)
    top = [
        (
            scale * (x * math.cos(angle) - y * math.sin(angle)),
            scale * (x * math.sin(angle) + y * math.cos(angle)),
            16.0,
        )
        for x, y, _ in bottom
    ]
    wires = [
        scad.make_polyline_rwire(points=bottom, closed=True),
        scad.make_polyline_rwire(points=top, closed=True),
    ]
    return scad.loft_rsolid(wires)


def _noncoaxial_compound():
    first = _shaft()
    second = scad.make_cylinder_rsolid(
        radius=4.0,
        height=12.0,
        bottom_face_center=(20.0, 0.0, 0.0),
    )
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, first.wrapped)
    builder.Add(compound, second.wrapped)
    return compound


def _fillet_case():
    body = scad.make_box_rsolid(width=30.0, height=22.0, depth=14.0)
    return scad.fillet_rsolid(body, [body.get_edges(0)], 3.0)


def _profile_loft_case():
    first = scad.make_rectangle_rwire(8.0, 4.0, center=(0.0, 0.0, 0.0))
    second = scad.make_rectangle_rwire(3.0, 7.0, center=(1.0, 0.5, 10.0))
    return scad.loft_rsolid([first, second])


def _point_loft_case():
    base = scad.make_rectangle_rwire(6.0, 4.0, center=(0.0, 0.0, 0.0))
    apex = scad.make_point_rvertex(0.5, 0.25, 8.0)
    return scad.loft_rsolid([base, apex])


def _local_loft_case(*, additive: bool):
    base = scad.make_box_rsolid(30.0, 24.0, 10.0, bottom_face_center=(0.0, 0.0, 0.0))
    start = scad.make_rectangle_rwire(
        10.0 if additive else 9.0,
        8.0 if additive else 7.0,
        center=(0.0, 0.0, 10.0),
    )
    end = scad.make_rectangle_rwire(
        5.0 if additive else 4.0,
        3.0,
        center=(1.0 if additive else 0.5, 0.0, 16.0 if additive else 4.0),
    )
    feature = scad.loft_rsolid([start, end])
    return (
        scad.union_rsolid(base, feature, clean=False)
        if additive
        else scad.cut_rsolid(base, feature)
    )


def _path_sweep_case():
    profile = scad.make_rectangle_rface(2.0, 1.0)
    path = scad.make_interpolated_spline_rwire(
        points=[(0, 0, 0), (1, 0, 2), (3, 1, 4), (5, 0, 6)]
    )
    return scad.sweep_rsolid(profile, path, is_frenet=True)


def _local_sweep_case(*, additive: bool):
    base = scad.make_box_rsolid(30.0, 24.0, 10.0, bottom_face_center=(0.0, 0.0, 0.0))
    profile = scad.make_rectangle_rface(3.0, 2.0, center=(0.0, 0.0, 10.0))
    middle = (0.5, 0.4, 12.0 if additive else 8.0)
    end = (4.0, -0.5, 14.0 if additive else 6.0)
    path = scad.make_interpolated_spline_rwire(points=[(0.0, 0.0, 10.0), middle, end])
    feature = scad.sweep_rsolid(profile, path, is_frenet=True)
    return (
        scad.union_rsolid(base, feature, clean=False)
        if additive
        else scad.cut_rsolid(base, feature)
    )


def _twisted_sweep_case():
    return scad.twisted_sweep_rsolid(
        scad.make_rectangle_rface(4.0, 2.0),
        distance=9.0,
        twist_angle=70.0,
    )


def _helical_sweep_case():
    profile = scad.make_circle_rwire((3.0, 0.0, 0.0), 0.35, normal=(0.0, 1.0, 0.0))
    return scad.helical_sweep_rsolid(profile, pitch=2.0, height=5.0, radius=3.0)


V3_CASES = (
    (
        "E1",
        lambda: _extrusion_case("whole_body_prism"),
        "extrusion",
        "whole_body_prism",
        1,
    ),
    ("E2", lambda: _extrusion_case("local_boss"), "extrusion", "local_boss", 1),
    ("E3", lambda: _extrusion_case("rib_or_web"), "extrusion", "rib_or_web", 1),
    ("E4", lambda: _extrusion_case("blind_pocket"), "extrusion", "blind_pocket", 1),
    (
        "E5",
        lambda: _extrusion_case("open_slot_or_notch"),
        "extrusion",
        "open_slot_or_notch",
        1,
    ),
    (
        "E6",
        lambda: _extrusion_case("through_cut_region"),
        "extrusion",
        "through_cut_region",
        1,
    ),
    ("R1", lambda: _revolved(inner=0.0), "revolution", "whole_body_full_revolution", 1),
    (
        "R2",
        lambda: scad.make_cone_rsolid(bottom_radius=6.0, top_radius=3.0, height=12.0),
        "revolution",
        "whole_body_full_revolution",
        1,
    ),
    (
        "R3",
        lambda: _revolved(inner=0.0, angle=120.0),
        "revolution",
        "whole_body_partial_revolution",
        1,
    ),
    (
        "R4",
        lambda: _full_revolved_local(True),
        "revolution",
        "local_full_revolved_boss",
        1,
    ),
    (
        "R5",
        lambda: _full_revolved_local(False),
        "revolution",
        "local_full_revolved_groove",
        1,
    ),
    ("R6", _partial_revolved_boss, "revolution", "local_partial_revolved_boss", 1),
    ("A1", lambda: _shaft(), "revolution", "whole_body_full_revolution", 1),
    ("A2", _circular_hole, "hole", "circular_through", 1),
    ("N1", lambda: _loft(0.65, 0.0), None, None, 0),
    ("N2", lambda: _loft(1.0, 30.0), None, None, 0),
    ("N3", _noncoaxial_compound, "revolution", "whole_body_full_revolution", 2),
    ("N4", _fillet_case, "fillet", "cylindrical_constant", 1),
)

V4_CASES = (
    ("L1", _profile_loft_case, "loft", "whole_body_profile_loft", 1),
    ("L2", _point_loft_case, "loft", "whole_body_point_loft", 1),
    ("L3", lambda: _local_loft_case(additive=True), "loft", "local_lofted_boss", 1),
    ("L4", lambda: _local_loft_case(additive=False), "loft", "local_lofted_cut", 1),
    ("S1", _path_sweep_case, "sweep", "whole_body_path_sweep", 1),
    ("S2", lambda: _local_sweep_case(additive=True), "sweep", "local_swept_boss", 1),
    ("S3", lambda: _local_sweep_case(additive=False), "sweep", "local_swept_cut", 1),
    ("S4", _twisted_sweep_case, "sweep", "twisted_sweep", 1),
    ("S5", _helical_sweep_case, "sweep", "helical_sweep", 1),
)


def _raw_shape(value):
    return value.wrapped if hasattr(value, "wrapped") else value


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _section_planes(feature, summary):
    center = np.asarray(summary["bounding_box"]["center"], dtype=float)
    if feature and feature["category"] == "revolution":
        axis = feature["location"]["axis"]
        direction = np.asarray(axis["direction"], dtype=float)
        reference = min(
            np.eye(3), key=lambda value: abs(float(np.dot(value, direction)))
        )
        normal = np.cross(direction, reference)
        planes = [("meridian", axis["point"], normal)]
        consistency = next(
            (
                item["observed"]
                for item in feature["evidence"]
                if item["code"] == "revolution.meridian_correspondence"
            ),
            {},
        )
        for measurement in consistency.get("measurements", []):
            plane = measurement.get("plane")
            if plane:
                angle = measurement["angle_degrees"]
                label = str(round(float(angle), 6)).replace(".", "p")
                planes.append((f"angle-{label}", plane["origin"], plane["normal"]))
        return planes
    if feature and feature["category"] == "extrusion":
        direction = np.asarray(feature["location"]["direction"], dtype=float)
        length = feature["dimensions"]["length"]["value"]
        origin = np.asarray(feature["location"]["local_origin"], dtype=float)
        return [
            (
                f"extrusion-{int(station * 100)}",
                origin + station * length * direction,
                direction,
            )
            for station in (0.25, 0.5, 0.75)
        ]
    if feature and feature["category"] == "hole":
        direction = np.asarray(feature["location"]["direction"], dtype=float)
        return [("hole-transverse", center, direction)]
    if feature and feature["category"] in {"loft", "sweep"}:
        flow = next(
            (
                item["observed"]
                for item in feature["evidence"]
                if item["code"]
                in {
                    "loft.actual_section_flow",
                    "loft.local_non_rigid_section_flow",
                    "sweep.actual_section_flow",
                    "sweep.local_rigid_section_flow",
                }
            ),
            {},
        )
        planes = []
        for item in flow.get("stations", []):
            plane = item.get("plane") or {}
            if plane.get("origin") and plane.get("normal"):
                label = str(round(float(item["station"]), 3)).replace(".", "p")
                planes.append((f"station-{label}", plane["origin"], plane["normal"]))
        if planes:
            return planes
    return [
        ("global-xy", center, (0.0, 0.0, 1.0)),
        ("global-xz", center, (0.0, 1.0, 0.0)),
        ("global-yz", center, (1.0, 0.0, 0.0)),
    ]


def _render_profile(feature, output_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    samples = feature.get("profile", {}).get("samples_2d") or []
    figure, axes = plt.subplots(figsize=(5.0, 4.0), dpi=100)
    if samples:
        values = np.asarray(samples, dtype=float)
        axes.plot(values[:, 0], values[:, 1], color="#172334", linewidth=2.0)
        axes.scatter(values[:, 0], values[:, 1], color="#06b6d4", s=14)
    axes.set_aspect("equal", adjustable="box")
    axes.grid(True, color="#d8e0e8")
    axes.set_title(f"{feature['feature_id']} | {feature['subtype']}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, bbox_inches="tight")
    plt.close(figure)


def _generate_cases(
    output_root: Path,
    *,
    version: str,
    cases,
    feature_kinds,
) -> None:
    root = output_root / version
    records = []
    for case_id, builder, category, subtype, expected_count in cases:
        case_root = root / case_id
        case_root.mkdir(parents=True, exist_ok=True)
        shape = builder()
        raw_shape = _raw_shape(shape)
        report = brep.inspect_geometric_features_rdescriptor(
            model_or_path=raw_shape,
            feature_kinds=feature_kinds,
            max_features=200,
        )
        _write_json(case_root / "feature-index.json", report)
        matching = (
            [
                feature
                for feature in report["features"]
                if feature["category"] == category and feature["subtype"] == subtype
            ]
            if category
            else [
                feature
                for feature in report["features"]
                if feature["category"] in {"extrusion", "revolution"}
            ]
        )
        if len(matching) != expected_count:
            raise RuntimeError(
                f"{case_id}: expected {expected_count} {category}/{subtype}, got {len(matching)}"
            )
        selected = matching[0] if matching else None
        _write_json(
            case_root / "expected-summary.json",
            {
                "case_id": case_id,
                "expected_category": category,
                "expected_subtype": subtype,
                "expected_count": expected_count,
                "actual_feature_ids": [feature["feature_id"] for feature in matching],
                "target_sha256": report["target_sha256"],
            },
        )
        brep.render_shape_views_rpath(
            shape=raw_shape,
            output_path=case_root / "context.png",
            title=f"{case_id} context",
            views=((28.0, -45.0, "isometric"),),
            image_size=(5.0, 4.0),
            dpi=80,
        )
        if report["features"]:
            brep.render_geometric_features_rpath(
                model_or_path=raw_shape,
                feature_report=case_root / "feature-index.json",
                output_path=case_root / "highlight.png",
                views=((28.0, -45.0, "isometric"),),
                image_size=(7.5, 4.0),
                dpi=80,
            )
        else:
            brep.render_shape_views_rpath(
                shape=raw_shape,
                output_path=case_root / "highlight.png",
                title=f"{case_id} unresolved",
                views=((28.0, -45.0, "isometric"),),
                image_size=(5.0, 4.0),
                dpi=80,
            )
        if selected:
            _render_profile(selected, case_root / "profile.png")
        summary = {"bounding_box": _bounding_box(raw_shape)}
        section_descriptors = []
        section_records = []
        for section_id, origin, normal in _section_planes(selected, summary):
            descriptor = brep.inspect_section_rdescriptor(
                model_or_path=raw_shape,
                origin=origin,
                normal=normal,
                compact=False,
            )
            descriptor["section_id"] = section_id
            data_path = case_root / "sections" / f"{section_id}.json"
            _write_json(data_path, descriptor)
            section_descriptors.append(descriptor)
            section_records.append(
                {
                    "section_id": section_id,
                    "path": data_path.relative_to(case_root).as_posix(),
                }
            )
        brep.render_sections_rpath(
            sections=section_descriptors,
            output_path=case_root / "sections.png",
            titles=[item["section_id"] for item in section_descriptors],
            columns=min(3, len(section_descriptors)),
            image_size_per_panel=(4.0, 3.5),
            dpi=80,
        )
        _write_json(
            case_root / "section-index.json",
            {
                "target_sha256": report["target_sha256"],
                "sections": section_records,
            },
        )
        records.append(
            {
                "case_id": case_id,
                "category": category,
                "subtype": subtype,
                "target_sha256": report["target_sha256"],
                "feature_count": len(report["features"]),
                "feature_ids": [feature["feature_id"] for feature in matching],
            }
        )
    record_by_case = {record["case_id"]: record for record in records}
    artifacts = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "target_sha256": record_by_case[path.relative_to(root).parts[0]][
                "target_sha256"
            ],
            "feature_ids": (
                record_by_case[path.relative_to(root).parts[0]]["feature_ids"]
                if path.suffix.lower() == ".png"
                else "not_applicable"
            ),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name not in {"artifact-manifest.json", "case-index.json"}
    ]
    _write_json(root / "case-index.json", {"cases": records})
    artifacts.append(
        {
            "path": "case-index.json",
            "bytes": (root / "case-index.json").stat().st_size,
            "sha256": _sha256(root / "case-index.json"),
            "target_sha256": "not_applicable",
            "feature_ids": "not_applicable",
        }
    )
    _write_json(root / "artifact-manifest.json", {"artifacts": artifacts})


def generate_v3_cases(output_root: Path) -> None:
    _generate_cases(
        output_root,
        version="v3",
        cases=V3_CASES,
        feature_kinds=V3_FEATURE_KINDS,
    )


def generate_v4_cases(output_root: Path) -> None:
    _generate_cases(
        output_root,
        version="v4",
        cases=V4_CASES,
        feature_kinds=V4_FEATURE_KINDS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate the reviewed computational-geometry examples."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help=f"must be exactly {APPROVED_OUTPUT_ROOT}",
    )
    versions = parser.add_mutually_exclusive_group()
    versions.add_argument(
        "--v3-only",
        action="store_true",
        help="generate only the v3 E/R/A/N review cases",
    )
    versions.add_argument(
        "--v4-only",
        action="store_true",
        help="generate only the v4 loft/sweep review cases",
    )
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    if output_root != APPROVED_OUTPUT_ROOT.resolve():
        parser.error(f"--output-root must be exactly {APPROVED_OUTPUT_ROOT}")
    if not args.v3_only and not args.v4_only:
        reviewed_source = output_root / "_work" / "generate_examples.py"
        if not reviewed_source.is_file():
            parser.error(f"reviewed generator source is missing: {reviewed_source}")
        namespace = runpy.run_path(str(reviewed_source), run_name="reviewed_examples")
        namespace["main"]()
    if not args.v4_only:
        generate_v3_cases(output_root)
    if not args.v3_only:
        generate_v4_cases(output_root)


if __name__ == "__main__":
    main()
