"""Atomic STEP persistence with explicit round-trip evidence."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import tempfile
from typing import Any

from simplecadapi._cpp.occt.TopoDS import TopoDS_Shape

from ...kernel.ocp_export import export_step_shapes
from .io import load_step_rshape
from .model import (
    BRepModel,
    clear_step_model_cache_rnone,
    index_shape_rbrepmodel,
    load_step_rbrepmodel,
)
from .topology_inspection import inspect_topology_rdescriptor


ModelInput = BRepModel | TopoDS_Shape | str | Path


def _model(value: ModelInput) -> BRepModel:
    if isinstance(value, BRepModel):
        return value
    if isinstance(value, TopoDS_Shape):
        return index_shape_rbrepmodel(value)
    if isinstance(value, (str, Path)):
        return load_step_rbrepmodel(value)
    raise TypeError("Expected a BRepModel, TopoDS_Shape, or STEP path")


def _relative_delta(before: float, after: float) -> float:
    return (after - before) / max(abs(before), 1.0e-12)


def _topology_count(report: dict[str, Any], name: str) -> int:
    return int(report["edge_classification_counts"].get(name, 0))


def _edge_evidence_count(report: dict[str, Any], name: str) -> int:
    return int(report["edge_evidence_counts"].get(name, 0))


def _shell_fact_counts(report: dict[str, Any]) -> dict[str, int]:
    shells = report["shells"]
    return {
        "closed": sum(bool(shell["closed"]) for shell in shells),
        "open": sum(not bool(shell["closed"]) for shell in shells),
        "oriented": sum(
            shell["orientation_status"] == "BRepCheck_NoError" for shell in shells
        ),
        "orientation_defect": sum(
            shell["orientation_status"] != "BRepCheck_NoError" for shell in shells
        ),
    }


def _compact_summary(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("bodies", None)
    return result


def _compact_topology(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    for key in (
        "problem_edges",
        "small_faces",
        "shells",
        "internal_face_ids",
        "external_face_ids",
        "orphan_vertex_ids",
    ):
        result.pop(key, None)
    return result


def validate_step_roundtrip_rdescriptor(
    model_or_shape: ModelInput,
    output_path: str | Path,
    *,
    relative_property_tolerance: float = 1.0e-7,
    position_tolerance: float = 1.0e-6,
    protected_input_paths: tuple[str | Path, ...] = (),
    compact: bool = True,
) -> dict[str, Any]:
    """Atomically write and reload STEP, publishing only a verified result.

    Relative tolerance bounds candidate-before/after volume and surface-area
    drift. Position tolerance, in model length units, bounds candidate-before/
    after centroid distance and both material and root bounding-box coordinate
    drift. These are STEP serialization integrity checks, not candidate-to-target
    similarity metrics. The returned descriptor records each measured delta.
    Topology acceptance compares defect counts and shell facts, preserving
    existing open topology while rejecting newly introduced defects and shell
    closure, orientation, or closed-manifold regressions.
    """

    if (
        not math.isfinite(relative_property_tolerance)
        or relative_property_tolerance < 0.0
    ):
        raise ValueError("relative_property_tolerance must be finite and non-negative")
    if not math.isfinite(position_tolerance) or position_tolerance < 0.0:
        raise ValueError("position_tolerance must be finite and non-negative")
    destination = Path(output_path).expanduser().resolve()
    if destination.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("output_path must end in .step or .stp")
    if not destination.parent.is_dir():
        raise ValueError(f"output_path parent does not exist: {destination.parent}")
    protected = {Path(path).expanduser().resolve() for path in protected_input_paths}
    if isinstance(model_or_shape, BRepModel) and model_or_shape.source is not None:
        protected.add(Path(model_or_shape.source).expanduser().resolve())
    if isinstance(model_or_shape, (str, Path)):
        protected.add(Path(model_or_shape).expanduser().resolve())
    if destination in protected:
        raise ValueError(
            "output_path must differ from the input STEP path and every protected "
            "input STEP path"
        )

    before_model = _model(model_or_shape)
    before = before_model.summary()
    topology_before = inspect_topology_rdescriptor(before_model)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.stem}-",
            suffix=destination.suffix,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        export_step_shapes([before_model.root], str(temporary_path))
        reloaded = load_step_rshape(
            temporary_path,
            require_single_root=False,
            require_valid=False,
        )
        after_model = index_shape_rbrepmodel(reloaded, source=destination)
        after = after_model.summary()
        topology_after = inspect_topology_rdescriptor(after_model)
        payload = temporary_path.read_bytes()
        volume_delta = float(after["volume"] - before["volume"])
        area_delta = float(after["surface_area"] - before["surface_area"])
        relative_volume = _relative_delta(
            float(before["volume"]), float(after["volume"])
        )
        relative_area = _relative_delta(
            float(before["surface_area"]), float(after["surface_area"])
        )
        property_deltas = {
            "volume": volume_delta,
            "relative_volume": relative_volume,
            "surface_area": area_delta,
            "relative_surface_area": relative_area,
            "centroid_distance": float(math.dist(before["centroid"], after["centroid"])),
            "bounding_box_max_coordinate_delta": max(
                abs(
                    float(after["bounding_box"][side][axis])
                    - float(before["bounding_box"][side][axis])
                )
                for side in ("min", "max")
                for axis in range(3)
            ),
            "root_bounding_box_max_coordinate_delta": max(
                abs(
                    float(after["root_bounding_box"][side][axis])
                    - float(before["root_bounding_box"][side][axis])
                )
                for side in ("min", "max")
                for axis in range(3)
            ),
        }
        shell_facts_before = _shell_fact_counts(topology_before)
        shell_facts_after = _shell_fact_counts(topology_after)
        topology_deltas = {
            "faces": int(after["face_count"] - before["face_count"]),
            "edges": int(after["edge_count"] - before["edge_count"]),
            "vertices": int(after["vertex_count"] - before["vertex_count"]),
            "free_edges": _topology_count(topology_after, "free")
            - _topology_count(topology_before, "free"),
            "non_manifold_edges": _topology_count(topology_after, "non_manifold")
            - _topology_count(topology_before, "non_manifold"),
            "degenerate_edges": _edge_evidence_count(topology_after, "degenerate")
            - _edge_evidence_count(topology_before, "degenerate"),
            "orphan_edges": _edge_evidence_count(topology_after, "orphan")
            - _edge_evidence_count(topology_before, "orphan"),
            "orientation_defect_edges": _topology_count(
                topology_after, "orientation_defect"
            )
            - _topology_count(topology_before, "orientation_defect"),
            "orphan_vertices": int(topology_after["orphan_vertex_count"])
            - int(topology_before["orphan_vertex_count"]),
            "closed_shells": shell_facts_after["closed"]
            - shell_facts_before["closed"],
            "open_shells": shell_facts_after["open"] - shell_facts_before["open"],
            "oriented_shells": shell_facts_after["oriented"]
            - shell_facts_before["oriented"],
            "shell_orientation_defects": shell_facts_after["orientation_defect"]
            - shell_facts_before["orientation_defect"],
            "closed_manifold": int(bool(topology_after["closed_manifold"]))
            - int(bool(topology_before["closed_manifold"])),
        }
        shell_closure_regressed = bool(topology_before["shells"]) and (
            topology_deltas["closed_shells"] < 0
            or topology_deltas["open_shells"] > 0
            or len(topology_after["shells"]) < len(topology_before["shells"])
        )
        shell_orientation_regressed = bool(topology_before["shells"]) and (
            topology_deltas["oriented_shells"] < 0
            or topology_deltas["shell_orientation_defects"] > 0
        )
        passed = (
            bool(before["valid"])
            and bool(after["valid"])
            and before["body_count"] == after["body_count"]
            and (
                before["body_count"] == 0
                or (float(before["volume"]) > 0.0 and float(after["volume"]) > 0.0)
            )
            and before["face_count"] == after["face_count"]
            and before["edge_count"] == after["edge_count"]
            and before["vertex_count"] == after["vertex_count"]
            and abs(relative_volume) <= relative_property_tolerance
            and abs(relative_area) <= relative_property_tolerance
            and property_deltas["centroid_distance"] <= position_tolerance
            and property_deltas["bounding_box_max_coordinate_delta"] <= position_tolerance
            and property_deltas["root_bounding_box_max_coordinate_delta"]
            <= position_tolerance
            and all(
                topology_deltas[name] <= 0
                for name in (
                    "free_edges",
                    "non_manifold_edges",
                    "degenerate_edges",
                    "orphan_edges",
                    "orientation_defect_edges",
                    "orphan_vertices",
                )
            )
            and not shell_closure_regressed
            and not shell_orientation_regressed
            and (
                not topology_before["closed_manifold"]
                or topology_after["closed_manifold"]
            )
        )
        output_replaced = False
        if passed:
            temporary_path.replace(destination)
            temporary_path = None
            output_replaced = True
            clear_step_model_cache_rnone()
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return {
        "report_version": 1,
        "tool": "validate_step_roundtrip_rdescriptor",
        "passed": passed,
        "output_path": str(destination),
        "file_size": len(payload),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "before": _compact_summary(before) if compact else before,
        "after": _compact_summary(after) if compact else after,
        "topology_before": (
            _compact_topology(topology_before) if compact else topology_before
        ),
        "topology_after": (
            _compact_topology(topology_after) if compact else topology_after
        ),
        "property_deltas": property_deltas,
        "topology_deltas": topology_deltas,
        "output_replaced": output_replaced,
        "strict_material_equality_checked": False,
        "strict_brep_equality_checked": False,
        "preserved_metadata_claimed": False,
    }


__all__ = ["validate_step_roundtrip_rdescriptor"]
