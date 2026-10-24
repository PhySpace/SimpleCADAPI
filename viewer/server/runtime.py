"""Case-directory runtime for the reverse-engineering studio server.

Layout inside a case directory::

    <case>/
      target.step            # first *.step / *.stp found (sorted)
      re_work/
        annotations.jsonl    # append-only annotation events (UI authoritative)
        submission.json      # atomic handoff to the waiting agent
        submission.seq       # monotonically increasing submission counter
        session.ndjson       # full side recording of every UI/server event
        snapshots/snap-N.png # viewport snapshot submitted with round N
        rebuild.py           # agent artifact: FTC reconstruction source
        rebuilt.step         # agent artifact: rebuilt STEP
        rebuilt.scadpkg      # agent artifact: captured v3 product package
        comparison.png       # agent artifact: shared-camera visual diff
        evaluation.json      # agent artifact: external verification report

Governance rule (mirrors the ppt-master confirm UI): only the human's browser
produces ``submission.json``. The agent waits on it and writes artifacts; it
must never POST /api/submit or author the submission file itself.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

WORK_DIRNAME = "re_work"
ARTIFACT_NAMES = (
    "rebuild.py",
    "rebuilt.step",
    "rebuilt.scadpkg",
    "comparison.png",
    "evaluation.json",
)
MAX_ADJACENCY_IDS = 40


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    try:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


@dataclass
class ReCase:
    """One reverse-engineering case directory bound to a server instance."""

    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    @property
    def work(self) -> Path:
        return self.root / WORK_DIRNAME

    @property
    def annotations_path(self) -> Path:
        return self.work / "annotations.jsonl"

    @property
    def submission_path(self) -> Path:
        return self.work / "submission.json"

    @property
    def submission_seq_path(self) -> Path:
        return self.work / "submission.seq"

    @property
    def session_log_path(self) -> Path:
        return self.work / "session.ndjson"

    @property
    def snapshots_dir(self) -> Path:
        return self.work / "snapshots"

    @classmethod
    def open_case(cls, root: str | Path) -> "ReCase":
        case = cls(Path(root))
        if not case.root.is_dir():
            raise FileNotFoundError(f"case directory does not exist: {case.root}")
        if case.target_path is None:
            raise FileNotFoundError(
                f"no STEP target (*.step / *.stp) found in {case.root}"
            )
        case.work.mkdir(parents=True, exist_ok=True)
        case.snapshots_dir.mkdir(parents=True, exist_ok=True)
        return case

    @property
    def target_path(self) -> Path | None:
        candidates = sorted(
            [*self.root.glob("*.step"), *self.root.glob("*.stp")],
            key=lambda item: item.name.lower(),
        )
        return candidates[0] if candidates else None

    def append_ndjson(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {"ts": _utc_now(), "type": event_type, **payload}
        with self.session_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def annotation_event(self, action: str, annotation: dict[str, Any]) -> None:
        self.append_ndjson("annotate", {"action": action, "annotation": annotation})

    def read_submission_seq(self) -> int:
        try:
            return int(self.submission_seq_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0

    def annotation_count(self) -> int:
        try:
            return sum(
                1
                for line in self.annotations_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        except OSError:
            return 0

    def append_annotations(self, events: Sequence[dict[str, Any]]) -> None:
        with self.annotations_path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def trim_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Bound one describe_entity result so submissions stay context-sized."""

    trimmed = dict(descriptor)
    adjacency = trimmed.get("adjacency")
    if isinstance(adjacency, dict):
        trimmed["adjacency"] = {
            key: value[:MAX_ADJACENCY_IDS] if isinstance(value, list) else value
            for key, value in adjacency.items()
        }
    return trimmed


def _truncated(items: list[Any], source_count: int) -> dict[str, Any]:
    """A context list that names when it was cut (never silently truncated)."""

    if source_count > MAX_ADJACENCY_IDS:
        return {"items": items, "total": source_count, "truncated": True}
    return {"items": items, "total": source_count, "truncated": False}


def _face_ref(descriptor: dict[str, Any]) -> dict[str, Any]:
    geometry = descriptor.get("geometry") or {}
    return {
        "topo_id": descriptor.get("entity_id"),
        "surface_type": geometry.get("type"),
        "area": geometry.get("area"),
    }


def _edge_ref(descriptor: dict[str, Any]) -> dict[str, Any]:
    geometry = descriptor.get("geometry") or {}
    return {
        "topo_id": descriptor.get("entity_id"),
        "curve_type": geometry.get("type"),
        "length": geometry.get("length"),
    }


def entity_neighborhood(
    describe: Any,
    adjacency: Any,
    entity_id: str,
) -> dict[str, Any]:
    """One-level adjacency card for a selected entity.

    ``describe`` is ``BRepModel.describe_entity`` and ``adjacency`` is
    ``BRepModel.adjacency_details``. The card carries the entity itself plus
    exactly one level of neighbors: a face lists its edges, and because the
    edges are listed each edge also lists its adjacent faces; vertices come
    along the same way. Lists are capped at ``MAX_ADJACENCY_IDS`` with the
    cut named in the payload.
    """

    descriptor = describe(entity_id)
    kind = descriptor.get("kind")
    card: dict[str, Any] = {"entity": trim_descriptor(descriptor), "level": 1}

    if kind == "face":
        details = adjacency(entity_id)
        edge_ids: list[str] = list(details.get("edges", []))
        vertices: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        for edge_id in edge_ids[:MAX_ADJACENCY_IDS]:
            edge_descriptor = describe(edge_id)
            edge_details = adjacency(edge_id)
            for vertex_id in edge_details.get("vertices", []):
                if vertex_id in vertices:
                    continue
                vertex_geometry = describe(vertex_id).get("geometry") or {}
                vertices[vertex_id] = {
                    "topo_id": vertex_id,
                    "coordinates": vertex_geometry.get("coordinates"),
                }
            adjacent_face_ids: list[str] = list(edge_details.get("faces", []))
            edges.append(
                {
                    **_edge_ref(edge_descriptor),
                    "adjacent_faces": _truncated(
                        [_face_ref(describe(face_id)) for face_id in adjacent_face_ids[:MAX_ADJACENCY_IDS]],
                        len(adjacent_face_ids),
                    ),
                }
            )
        neighboring_face_ids: list[str] = list(details.get("neighboring_faces", []))
        card["edges"] = _truncated(edges, len(edge_ids))
        card["vertices"] = _truncated(
            [vertices[key] for key in sorted(vertices)], len(vertices)
        )
        card["neighboring_faces"] = _truncated(
            [_face_ref(describe(face_id)) for face_id in neighboring_face_ids[:MAX_ADJACENCY_IDS]],
            len(neighboring_face_ids),
        )
    elif kind == "edge":
        details = adjacency(entity_id)
        face_ids: list[str] = list(details.get("faces", []))
        vertex_ids: list[str] = list(details.get("vertices", []))
        adjacent_edge_ids: list[str] = list(details.get("adjacent_edges", []))
        card["vertices"] = _truncated(
            [
                {
                    "topo_id": vertex_id,
                    "coordinates": (describe(vertex_id).get("geometry") or {}).get("coordinates"),
                }
                for vertex_id in vertex_ids[:MAX_ADJACENCY_IDS]
            ],
            len(vertex_ids),
        )
        # one incident face = free/boundary edge, two = interior edge
        card["adjacent_faces"] = _truncated(
            [_face_ref(describe(face_id)) for face_id in face_ids[:MAX_ADJACENCY_IDS]],
            len(face_ids),
        )
        card["adjacent_edges"] = _truncated(
            [_edge_ref(describe(edge_id)) for edge_id in adjacent_edge_ids[:MAX_ADJACENCY_IDS]],
            len(adjacent_edge_ids),
        )
    elif kind == "vertex":
        details = adjacency(entity_id)
        edge_ids = list(details.get("edges", []))
        face_ids = list(details.get("faces", []))
        card["adjacent_edges"] = _truncated(
            [_edge_ref(describe(edge_id)) for edge_id in edge_ids[:MAX_ADJACENCY_IDS]],
            len(edge_ids),
        )
        card["adjacent_faces"] = _truncated(
            [_face_ref(describe(face_id)) for face_id in face_ids[:MAX_ADJACENCY_IDS]],
            len(face_ids),
        )
    return card


def compose_submission(
    case: ReCase,
    describe: Any,
    summary: dict[str, Any],
    payload: dict[str, Any],
    adjacency: Any | None = None,
) -> dict[str, Any]:
    """Assemble submission.json from the UI payload plus server-side context.

    ``describe`` is ``BRepModel.describe_entity``; unresolved entity ids are
    reported per annotation instead of being silently dropped. When
    ``adjacency`` (``BRepModel.adjacency_details``) is provided, each
    annotated entity's context becomes a one-level neighborhood card
    (``entity_neighborhood``) instead of a bare descriptor.
    """

    seq = case.read_submission_seq() + 1
    annotations_out: list[dict[str, Any]] = []
    referenced_ops: list[str] = []
    for annotation in payload.get("annotations", []):
        record = dict(annotation)
        # every picked entity goes through — a silent cap would drop the
        # human's selection without a trace (ruling 2026-09-06: never
        # truncate user selections)
        entity_ids = [
            str(item) for item in record.get("entity_ids", []) if isinstance(item, str)
        ]
        record["entity_ids"] = entity_ids
        operations = [
            str(item)
            for item in record.get("operations", [])
            if isinstance(item, str) and item not in referenced_ops
        ]
        record["operations"] = operations
        referenced_ops.extend(operations)
        context: dict[str, Any] = {}
        unresolved: list[str] = []
        for entity_id in entity_ids:
            try:
                if adjacency is not None:
                    context[entity_id] = entity_neighborhood(describe, adjacency, entity_id)
                else:
                    context[entity_id] = trim_descriptor(describe(entity_id))
            except Exception:
                unresolved.append(entity_id)
        if unresolved:
            record["unresolved_entity_ids"] = unresolved
        record["context"] = context
        annotations_out.append(record)

    from .operation_tips import operation_context_for

    operation_context = operation_context_for(referenced_ops)

    snapshot_path: str | None = None
    snapshot = payload.get("snapshot_png")
    if isinstance(snapshot, str) and snapshot.startswith("data:image/png;base64,"):
        import base64

        target = case.snapshots_dir / f"snap-{seq}.png"
        target.write_bytes(base64.b64decode(snapshot.split(",", 1)[1]))
        snapshot_path = str(target.relative_to(case.root))

    target = case.target_path
    submission = {
        "schema_version": "1.0",
        "submission_seq": seq,
        "submitted_at": _utc_now(),
        "target": {
            "path": str(target) if target else None,
            "name": target.name if target else None,
            "summary": summary,
        },
        "annotations": annotations_out,
        "operation_context": operation_context,
        "note": str(payload.get("note") or ""),
        "snapshot": snapshot_path,
    }
    write_json_atomic(case.submission_path, submission)
    write_json_atomic(case.submission_seq_path, seq)
    case.append_ndjson(
        "submit",
        {
            "submission_seq": seq,
            "annotation_count": len(annotations_out),
            "note": submission["note"],
            "snapshot": snapshot_path,
        },
    )
    return submission


def _cad_point_to_gltf(point: Sequence[float]) -> tuple[float, float, float]:
    return (point[0] / 1000.0, point[2] / 1000.0, -point[1] / 1000.0)


def _point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[float]]) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index][0], polygon[index][1]
        x2, y2 = polygon[(index + 1) % count][0], polygon[(index + 1) % count][1]
        if (y1 > y) != (y2 > y):
            cross = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < cross:
                inside = not inside
    return inside


def resolve_region(
    anchors: dict[str, dict[str, Any]],
    camera: dict[str, Any],
    polygon: Sequence[Sequence[float]],
) -> dict[str, Any]:
    """Resolve a screen-space polygon to entity ids.

    Faces are matched by centroid projection plus a front-facing normal test;
    vertices by point projection. The camera arrives from the browser already
    in glTF metres; anchors are CAD mm and are converted here.
    """

    position = tuple(float(item) for item in camera["position"])
    target = tuple(float(item) for item in camera["target"])
    up = tuple(float(item) for item in camera["up"])
    fov = float(camera["fov_deg"])
    width = float(camera["width"])
    height = float(camera["height"])
    forward = tuple(target[i] - position[i] for i in range(3))
    norm = math.sqrt(sum(item * item for item in forward)) or 1.0
    forward = tuple(item / norm for item in forward)
    right = (
        forward[1] * up[2] - forward[2] * up[1],
        forward[2] * up[0] - forward[0] * up[2],
        forward[0] * up[1] - forward[1] * up[0],
    )
    norm = math.sqrt(sum(item * item for item in right)) or 1.0
    right = tuple(item / norm for item in right)
    true_up = (
        right[1] * forward[2] - right[2] * forward[1],
        right[2] * forward[0] - right[0] * forward[2],
        right[0] * forward[1] - right[1] * forward[0],
    )
    tan_half = math.tan(math.radians(fov) * 0.5)
    aspect = width / max(height, 1.0)

    def project(point_gltf: Sequence[float]) -> tuple[float, float] | None:
        delta = tuple(point_gltf[i] - position[i] for i in range(3))
        depth = sum(delta[i] * forward[i] for i in range(3))
        if depth <= 1e-9:
            return None
        x_cam = sum(delta[i] * right[i] for i in range(3)) / depth
        y_cam = sum(delta[i] * true_up[i] for i in range(3)) / depth
        px = (width / 2.0) * (1.0 + x_cam / (tan_half * aspect))
        py = (height / 2.0) * (1.0 - y_cam / tan_half)
        return px, py

    hits: list[str] = []
    for entity_id, anchor in anchors.items():
        if anchor["kind"] == "face":
            centroid = _cad_point_to_gltf(anchor["centroid"])
            projected = project(centroid)
            if projected is None or not _point_in_polygon(projected[0], projected[1], polygon):
                continue
            normal_cad = anchor.get("normal")
            if normal_cad:
                normal = (normal_cad[0], normal_cad[2], -normal_cad[1])
                facing = sum(
                    (centroid[i] - position[i]) * normal[i] for i in range(3)
                )
                if facing > 0.0:
                    continue
            hits.append(entity_id)
        elif anchor["kind"] == "vertex":
            projected = project(_cad_point_to_gltf(anchor["position"]))
            if projected is not None and _point_in_polygon(projected[0], projected[1], polygon):
                hits.append(entity_id)
    return {"entity_ids": sorted(hits), "count": len(hits)}


__all__ = [
    "ARTIFACT_NAMES",
    "MAX_ADJACENCY_IDS",
    "MAX_ENTITIES_PER_ANNOTATION",
    "ReCase",
    "compose_submission",
    "entity_neighborhood",
    "resolve_region",
    "trim_descriptor",
    "write_json_atomic",
]
