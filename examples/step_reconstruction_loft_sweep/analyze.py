"""Produce a saved STEP analysis package for the three reconstruction guides."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path

from simplecadapi.inspect import brep

from case_config import CASES, CONFIG, FEATURE_KINDS, OUT
from target_fixtures import write_target


EXPECTED_CATEGORY = {"l1": "loft", "s1": "sweep", "p1": "loft"}
EXPECTED_API = {
    "l1": "loft_rsolid",
    "s1": "sweep_rsolid",
    "p1": "loft_multisection_rsolid",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_report(package: Path, catalog: dict) -> None:
    counts: dict[str, int] = {}
    for feature in catalog["features"]:
        counts[feature["category"]] = counts.get(feature["category"], 0) + 1
    lines = [
        "# STEP computational-geometry report", "",
        "Measurements use the units shown below. Confidence labels are not calibrated probabilities.",
        "", f"Recognized features: **{len(catalog['features'])}**. Categories: "
        + ", ".join(f"{name} {count}" for name, count in sorted(counts.items())) + ".", "",
    ]
    for feature in catalog["features"]:
        operation = (feature.get("reconstruction") or {}).get("recommended_operation") or {}
        location = feature["location"]
        lines.extend([
            f"## {feature['feature_id']} — {feature['display_name']}", "",
            f"- Category / subtype: `{feature['category']}` / `{feature['subtype']}`",
            f"- Confidence: `{feature['confidence']['level']}` (not a calibrated probability)",
            f"- Body: `{feature['body_id']}`",
            f"- Center / local origin: `{location['center']}` / `{location['local_origin']}` mm",
            f"- Direction: `{location['direction']}`",
            f"- Topology: `{', '.join(feature['entity_ids'])}`",
            f"- Evidence: {', '.join(item['code'] for item in feature['evidence'])}",
            f"- Candidate API: `{operation.get('api', 'unresolved')}`; capability `{operation.get('capability', 'unknown')}`",
            "- Visual: [highlight](highlights/all-features.png), [section atlas](sections/section-atlas.png)",
            "", "### Dimensions", "",
        ])
        for name, measure in feature["dimensions"].items():
            value = measure.get("value")
            if value is not None:
                lines.append(f"- `{name}`: {value:.9g} {measure['unit']}")
        lines.extend(["", "### Limits", ""])
        lines.extend(f"- {item}" for item in feature.get("limitations", []))
        lines.append("")
    (package / "parse-report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_sections(target: Path, package: Path, catalog: dict, summary: dict) -> dict:
    center = summary["bounding_box"]["center"]
    requests = [(f"global-{axis}", None, center, normal) for axis, normal in (
        ("xy", (0, 0, 1)), ("xz", (0, 1, 0)), ("yz", (1, 0, 0)),
    )]
    for feature in catalog["features"]:
        for station in (feature.get("reconstruction") or {}).get("sections", []):
            plane = station["plane"]
            requests.append((station["station_id"].replace(":", "-"), feature["feature_id"], plane["origin"], plane["normal"]))
    descriptors = []
    records = []
    for section_id, feature_id, origin, normal in requests:
        descriptor = brep.inspect_section_rdescriptor(
            model_or_path=target, origin=origin, normal=normal, compact=False,
        )
        relative = f"sections/data/{section_id}.json"
        _write_json(package / relative, descriptor)
        records.append({
            "section_id": section_id, "feature_id": feature_id,
            "status": "computed", "data_path": relative,
        })
        descriptors.append(descriptor)
    brep.render_sections_rpath(
        sections=descriptors, output_path=package / "sections/section-atlas.png",
        titles=[item["section_id"] for item in records], columns=3,
        image_size_per_panel=(3.5, 3.0), dpi=90,
    )
    return {"target_sha256": catalog["target_sha256"], "atlas": "sections/section-atlas.png", "sections": records}


def analyze_case(case: str) -> Path:
    if case not in CASES:
        raise ValueError(case)
    root = OUT / case
    target = write_target(case, root / "target.step")
    package = root / "analysis"
    package.mkdir(parents=True, exist_ok=True)
    target_sha256 = _sha256(target)
    config = {
        **CONFIG, "route": "reconstruction_prelude", "target_sha256": target_sha256,
        "render_budget": {"max_feature_visual_sets": 10, "timeout_seconds": 60},
        "section_budget": {"max_features": 10},
    }
    _write_json(package / "analysis-config.json", config)
    _write_json(package / "run-status.json", {
        "status": "running", "route": "reconstruction_prelude",
        "sdk_version": importlib.metadata.version("simplecadapi"),
        "target_sha256": target_sha256, "gaps": [],
    })
    (package / "requirement-brief.md").write_text(
        f"# {case.upper()} reconstruction brief\n\nRebuild one editable solid from the target STEP.\n",
        encoding="utf-8",
    )
    summary = brep.inspect_step_rsummary(path=target)
    _write_json(package / "target-summary.json", {"target_sha256": target_sha256, "summary": summary})
    catalog = brep.inspect_geometric_features_rdescriptor(
        model_or_path=target, feature_kinds=FEATURE_KINDS,
        tolerance=CONFIG["linear_tolerance"],
        angular_tolerance_degrees=CONFIG["angular_tolerance_degrees"],
        max_features=CONFIG["max_features"],
    )
    if catalog["truncated"] or len(catalog["features"]) != 1:
        raise RuntimeError(f"{case}: expected one complete recognized feature")
    feature = catalog["features"][0]
    operation = (feature.get("reconstruction") or {}).get("recommended_operation") or {}
    if feature["category"] != EXPECTED_CATEGORY[case] or operation.get("api") != EXPECTED_API[case]:
        raise RuntimeError(f"{case}: catalog recommended {feature['category']}/{operation.get('api')}")
    _write_json(package / "raw-feature-hints.json", {"target_sha256": target_sha256, "hints": catalog["raw_feature_hints"]})
    _write_json(package / "feature-index.json", catalog)
    _write_json(package / "feature-summary.json", {"target_sha256": target_sha256, **catalog["summary"]})
    _write_json(package / "reconstruction-hypotheses.json", {
        "target_sha256": target_sha256,
        "hypotheses": {feature["feature_id"]: feature["reconstruction"]},
    })
    _write_json(package / "loft-sweep-specialist.json", {
        "target_sha256": target_sha256,
        "entries": [{
            "feature_id": feature["feature_id"], "status": "complete", "reason": None,
            "roi_entity_ids": feature["entity_ids"],
            "specialist_analysis": feature["reconstruction"],
        }],
    })
    _write_json(package / "section-index.json", _write_sections(target, package, catalog, summary))
    brep.render_step_views_rpath(
        step_path=target, output_path=package / "highlights/context.png",
        title=f"{case.upper()} STEP target", views=((28.0, -45.0, "isometric"),),
        image_size=(5.0, 4.0), dpi=90,
    )
    brep.render_geometric_features_rpath(
        model_or_path=target, feature_report=package / "feature-index.json",
        output_path=package / "highlights/all-features.png",
        views=((28.0, -45.0, "isometric"),), image_size=(7.5, 4.0), dpi=90,
    )
    _write_json(package / "visual-index.json", {
        "target_sha256": target_sha256,
        "visuals": [{
            "feature_id": feature["feature_id"], "status": "rendered", "reason": None,
            "paths": ["highlights/all-features.png"],
            "image_sha256": _sha256(package / "highlights/all-features.png"),
            "entity_ids": feature["highlight_entity_ids"],
        }],
    })
    _write_report(package, catalog)
    unresolved = catalog["coverage"]["unowned_face_ids"]
    (package / "unresolved-features.md").write_text(
        "# Unresolved faces\n\n" + ("\n".join(f"- `{face_id}`" for face_id in unresolved) if unresolved else "None.") + "\n",
        encoding="utf-8",
    )
    _write_json(package / "run-status.json", {
        "status": "complete", "route": "reconstruction_prelude",
        "sdk_version": importlib.metadata.version("simplecadapi"),
        "target_sha256": target_sha256, "gaps": [],
    })
    _write_json(package / "artifact-manifest.json", {
        "target_sha256": target_sha256,
        "artifacts": [{
            "path": path.relative_to(package).as_posix(), "role": path.stem,
            "bytes": path.stat().st_size, "sha256": _sha256(path),
            "target_sha256": target_sha256,
        } for path in sorted(package.rglob("*")) if path.is_file() and path.name != "artifact-manifest.json"],
    })
    check = brep.inspect_analysis_package_rdescriptor(
        package_dir=package, target_path=target, expected_config=CONFIG,
    )
    if not check["may_start_reconstruction"]:
        raise RuntimeError(f"{case}: R0 failed: {check['hard_failures']}")
    return package


if __name__ == "__main__":
    for case_id in CASES:
        print(case_id, analyze_case(case_id))
