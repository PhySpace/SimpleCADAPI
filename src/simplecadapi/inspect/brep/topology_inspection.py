"""Explicit closure, manifoldness, orientation, and tolerance diagnostics."""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import Any

from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer, BRepCheck_Shell
from simplecadapi._cpp.occt.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
from simplecadapi._cpp.occt.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_FORWARD,
    TopAbs_REVERSED,
    TopAbs_SHAPE,
    TopAbs_SHELL,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from simplecadapi._cpp.occt.TopExp import TopExp, TopExp_Explorer
from simplecadapi._cpp.occt.TopTools import TopTools_IndexedMapOfShape
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Shape

from .io import measure_shape_mass_rtuple
from .model import BRepModel, index_shape_rbrepmodel, load_step_rbrepmodel


ModelInput = BRepModel | TopoDS_Shape | str | Path


def _model(value: ModelInput) -> BRepModel:
    if isinstance(value, BRepModel):
        return value
    if isinstance(value, TopoDS_Shape):
        return index_shape_rbrepmodel(value)
    if isinstance(value, (str, Path)):
        return load_step_rbrepmodel(value)
    raise TypeError("Expected a BRepModel, TopoDS_Shape, or STEP path")


def _mapped_shapes(shape: TopoDS_Shape, kind: Any) -> list[TopoDS_Shape]:
    mapping = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, mapping)
    return [mapping.FindKey(index) for index in range(1, mapping.Extent() + 1)]


def _enum_name(value: Any) -> str:
    return str(value).rsplit(".", 1)[-1]


def _orientation_name(shape: TopoDS_Shape) -> str:
    return _enum_name(shape.Orientation()).removeprefix("TopAbs_").lower()


def _tolerance_report(shape: TopoDS_Shape) -> dict[str, dict[str, float]]:
    analysis = ShapeAnalysis_ShapeTolerance()
    return {
        name: {
            "minimum": float(analysis.Tolerance(shape, -1, kind)),
            "average": float(analysis.Tolerance(shape, 0, kind)),
            "maximum": float(analysis.Tolerance(shape, 1, kind)),
        }
        for name, kind in (
            ("all", TopAbs_SHAPE),
            ("vertices", TopAbs_VERTEX),
            ("edges", TopAbs_EDGE),
            ("faces", TopAbs_FACE),
        )
    }


def inspect_topology_rdescriptor(
    model_or_shape: ModelInput,
    *,
    max_problem_edges: int = 100,
    small_face_area_threshold: float = 1.0e-8,
    max_small_faces: int = 100,
) -> dict[str, Any]:
    """Report topology use counts independently from generic BREP validity.

    Edge classifications use face-local occurrences, so a seam used twice by
    one face is distinct from a free edge that merely has one unique ancestor.
    ``edge_evidence_counts`` preserves degenerate-and-orphan combinations;
    ``orphan_vertex_count`` and ``orphan_vertex_ids`` report isolated vertices.
    """

    if max_problem_edges < 1:
        raise ValueError("max_problem_edges must be at least one")
    if not math.isfinite(small_face_area_threshold) or small_face_area_threshold < 0:
        raise ValueError("small_face_area_threshold must be finite and non-negative")
    if max_small_faces < 1:
        raise ValueError("max_small_faces must be at least one")
    model = _model(model_or_shape)
    root = model.root
    shells = [TopoDS.Shell_s(shape) for shape in _mapped_shapes(root, TopAbs_SHELL)]
    wires = _mapped_shapes(root, TopAbs_WIRE)
    wire_counts = Counter(
        "closed" if BRep_Tool.IsClosed_s(wire) else "open" for wire in wires
    )
    face_orientation_counts = Counter(_orientation_name(face) for face in model.faces)
    edge_orientation_counts = Counter(_orientation_name(edge) for edge in model.edges)
    small_faces = []
    for face_index, face in enumerate(model.faces):
        area = measure_shape_mass_rtuple(face, "area")[0]
        if area <= small_face_area_threshold:
            small_faces.append(
                {
                    "face_id": f"face:{face_index}",
                    "area": area,
                    "orientation": _orientation_name(face),
                    "tolerance": float(BRep_Tool.Tolerance_s(face)),
                }
            )

    uses: list[list[dict[str, Any]]] = [[] for _ in model.edges]
    seam_edges: set[int] = set()
    for face_index, face in enumerate(model.faces):
        explorer = TopExp_Explorer(face, TopAbs_EDGE)
        while explorer.More():
            occurrence = TopoDS.Edge_s(explorer.Current())
            edge_index = model._maps["edge"].FindIndex(occurrence) - 1
            if edge_index >= 0:
                uses[edge_index].append(
                    {
                        "face_id": f"face:{face_index}",
                        "orientation": _orientation_name(occurrence),
                    }
                )
                if BRep_Tool.IsClosed_s(occurrence, face):
                    seam_edges.add(edge_index)
            explorer.Next()

    classification_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    use_histogram: Counter[int] = Counter()
    problem_edges = []
    for edge_index, (edge, edge_uses) in enumerate(zip(model.edges, uses)):
        use_count = len(edge_uses)
        use_histogram[use_count] += 1
        orientations = [item["orientation"] for item in edge_uses]
        unique_faces = sorted({item["face_id"] for item in edge_uses})
        degenerate = bool(BRep_Tool.Degenerated_s(edge))
        orphan = use_count == 0
        seam = edge_index in seam_edges
        evidence_counts["degenerate"] += degenerate
        evidence_counts["orphan"] += orphan
        if degenerate:
            classification = "degenerate"
        elif orphan:
            classification = "orphan"
        elif use_count == 1:
            classification = "free"
        elif use_count > 2:
            classification = "non_manifold"
        elif (
            seam
            and len(unique_faces) == 1
            and Counter(orientations) == Counter({"forward": 1, "reversed": 1})
        ):
            classification = "seam"
        elif Counter(orientations) == Counter({"forward": 1, "reversed": 1}):
            classification = "manifold"
        else:
            classification = "orientation_defect"
        classification_counts[classification] += 1
        if classification not in {"manifold", "seam"}:
            problem_edges.append(
                {
                    "edge_id": f"edge:{edge_index}",
                    "classification": classification,
                    "use_count": use_count,
                    "unique_face_count": len(unique_faces),
                    "face_ids": unique_faces,
                    "orientations": orientations,
                    "degenerated": degenerate,
                    "orphan": orphan,
                    "seam": seam,
                    "tolerance": float(BRep_Tool.Tolerance_s(edge)),
                }
            )

    shell_reports = []
    for index, shell in enumerate(shells):
        checker = BRepCheck_Shell(shell)
        closure_status = checker.Closed(False)
        orientation_status = checker.Orientation(False)
        shell_reports.append(
            {
                "shell_index": index,
                "closed": _enum_name(closure_status) == "BRepCheck_NoError",
                "closure_status": _enum_name(closure_status),
                "orientation_status": _enum_name(orientation_status),
            }
        )

    ordered_counts = {
        name: classification_counts.get(name, 0)
        for name in (
            "degenerate",
            "free",
            "manifold",
            "non_manifold",
            "orientation_defect",
            "orphan",
            "seam",
        )
    }
    edge_evidence_counts = {
        name: evidence_counts.get(name, 0) for name in ("degenerate", "orphan")
    }
    edge_vertex_indices: set[int] = set()
    for edge in model.edges:
        for vertex in _mapped_shapes(edge, TopAbs_VERTEX):
            vertex_index = model._maps["vertex"].FindIndex(vertex) - 1
            if vertex_index >= 0:
                edge_vertex_indices.add(vertex_index)
    orphan_vertex_ids = [
        f"vertex:{index}"
        for index in range(len(model.vertices))
        if index not in edge_vertex_indices
    ]
    valid = bool(BRepCheck_Analyzer(root).IsValid())
    closed_manifold = (
        bool(shell_reports)
        and all(
            item["closed"] and item["orientation_status"] == "BRepCheck_NoError"
            for item in shell_reports
        )
        and not any(
            ordered_counts[name]
            for name in ("free", "non_manifold", "orientation_defect")
        )
        and not edge_evidence_counts["orphan"]
        and not orphan_vertex_ids
    )
    return {
        "model_path": model.source,
        "valid": valid,
        "closed_manifold": closed_manifold,
        "counts": {
            "bodies": len(model.bodies),
            "shells": len(shells),
            "faces": len(model.faces),
            "wires": len(wires),
            "edges": len(model.edges),
            "vertices": len(model.vertices),
            "edge_occurrences": sum(len(items) for items in uses),
        },
        "edge_use_histogram": {
            str(count): total for count, total in sorted(use_histogram.items())
        },
        "edge_classification_counts": ordered_counts,
        "edge_evidence_counts": edge_evidence_counts,
        "orphan_vertex_count": len(orphan_vertex_ids),
        "orphan_vertex_ids": orphan_vertex_ids,
        "wire_counts": {
            "closed": wire_counts.get("closed", 0),
            "open": wire_counts.get("open", 0),
        },
        "face_orientation_counts": dict(sorted(face_orientation_counts.items())),
        "edge_orientation_counts": dict(sorted(edge_orientation_counts.items())),
        "internal_face_ids": [
            f"face:{index}"
            for index, face in enumerate(model.faces)
            if _orientation_name(face) == "internal"
        ],
        "external_face_ids": [
            f"face:{index}"
            for index, face in enumerate(model.faces)
            if _orientation_name(face) == "external"
        ],
        "problem_edge_count": len(problem_edges),
        "problem_edges_truncated": len(problem_edges) > max_problem_edges,
        "problem_edges": problem_edges[:max_problem_edges],
        "small_face_area_threshold": float(small_face_area_threshold),
        "small_face_count": len(small_faces),
        "small_faces_truncated": len(small_faces) > max_small_faces,
        "small_faces": small_faces[:max_small_faces],
        "shells": shell_reports,
        "tolerances": _tolerance_report(root),
        "interpretation": (
            "valid checks the OpenCascade geometric BREP contract; "
            "closed_manifold independently requires closed, consistently oriented "
            "shells, no free, orphan, orientation-defect, or more-than-two-use "
            "edges, and no isolated vertices."
        ),
    }


__all__ = ["inspect_topology_rdescriptor"]
