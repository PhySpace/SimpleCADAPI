"""Durable definition-owned feature graph artifacts and source snapshots."""

from __future__ import annotations

import json
import os
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from ..scene.archive import canonical_zip_bytes, preflight_zip_bytes
from ..recording.source_mapping import canonical_source_payload
from .._internal.os_compat import with_binary_flag
from ..topology import OperationGraph, semantic_delta_to_dict, topo_delta_to_dict
from .canonical import (
    DEFAULT_ARTIFACT_LIMITS,
    ArtifactLimits,
    ArtifactValidationError,
    canonical_bytes,
    content_hash,
    parse_canonical_json,
    sha256_bytes,
    validate_hash,
    validate_json_value,
    validate_logical_id,
    validate_relative_path,
    validate_revision,
)

FEATURE_GRAPH_SCHEMA_VERSION = "1.0"
FEATURE_GRAPH_PROFILE = "simplecad-feature-graph-1"
FEATURE_GRAPH_MEDIA_TYPE = "application/vnd.simplecad.feature-graph+zip"
_FEATURE_GRAPH_MANIFEST = "feature-graph.json"

# Content-addressed memo for load_feature_graph_artifact (bounded LRU).
_LOAD_CACHE: "OrderedDict[str, FeatureGraphArtifact]" = OrderedDict()
_LOAD_CACHE_LOCK = threading.Lock()
_LOAD_CACHE_MAX = 32


@lru_cache(maxsize=1)
def _schema() -> Mapping[str, Any]:
    resource = files("simplecadapi").joinpath(
        "contracts", "feature-graph-1.schema.json"
    )
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def _pointer(parts: Sequence[Any]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _schema_validate(manifest: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(dict(manifest)),
        key=lambda item: (list(item.absolute_path), item.message),
    )
    if errors:
        error = errors[0]
        raise ArtifactValidationError(
            "schema_invalid", _pointer(list(error.absolute_path)), error.message
        )


def _stable_source_bytes(path: Path, *, max_bytes: int, error_path: str) -> bytes:
    flags = with_binary_flag(os.O_RDONLY)
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactValidationError(
            "source_unavailable", error_path, str(exc)
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactValidationError(
                "source_unsafe", error_path, "source must be a regular file"
            )
        if before.st_size > max_bytes:
            raise ArtifactValidationError(
                "resource_limit", error_path, "source exceeds byte limit"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) > max_bytes
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(payload) != after.st_size
        ):
            raise ArtifactValidationError(
                "source_changed", error_path, "source changed while being read"
            )
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactValidationError(
                "source_invalid", error_path, "Python source must be UTF-8"
            ) from exc
        return payload
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class SourceFileSnapshot:
    """One immutable Python source revision referenced by graph nodes."""

    source_file_id: str
    display_path: str
    path_kind: str
    content_hash: str
    byte_length: int
    uri: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_file_id",
            validate_hash(self.source_file_id, "/source_file/source_file_id"),
        )
        if not isinstance(self.display_path, str) or not self.display_path:
            raise ArtifactValidationError(
                "path_invalid", "/source_file/display_path", "path must be non-empty"
            )
        if self.path_kind not in {"project_relative", "external"}:
            raise ArtifactValidationError(
                "source_invalid", "/source_file/path_kind", "unsupported path kind"
            )
        if self.path_kind == "project_relative":
            validate_relative_path(self.display_path, "/source_file/display_path")
        object.__setattr__(
            self,
            "content_hash",
            validate_hash(self.content_hash, "/source_file/content_hash"),
        )
        if (
            isinstance(self.byte_length, bool)
            or not isinstance(self.byte_length, int)
            or self.byte_length < 0
        ):
            raise ArtifactValidationError(
                "size_invalid", "/source_file/byte_length", "must be non-negative"
            )
        object.__setattr__(
            self, "uri", validate_relative_path(self.uri, "/source_file/uri")
        )
        expected_uri = (
            "sources/sha256/"
            + self.content_hash.removeprefix("sha256:")
            + ".py"
        )
        if self.uri != expected_uri:
            raise ArtifactValidationError(
                "path_invalid", "/source_file/uri", "source URI is not content-addressed"
            )
        expected_id = sha256_bytes(
            canonical_bytes(
                {
                    "display_path": self.display_path,
                    "content_hash": self.content_hash,
                }
            )
        )
        if self.source_file_id != expected_id:
            raise ArtifactValidationError(
                "hash_invalid",
                "/source_file/source_file_id",
                "source identity does not match path and content",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_id": self.source_file_id,
            "display_path": self.display_path,
            "path_kind": self.path_kind,
            "content_hash": self.content_hash,
            "byte_length": self.byte_length,
            "uri": self.uri,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], path: str = "/source_file"
    ) -> "SourceFileSnapshot":
        required = {
            "source_file_id",
            "display_path",
            "path_kind",
            "content_hash",
            "byte_length",
            "uri",
        }
        if not isinstance(data, Mapping) or set(data) != required:
            raise ArtifactValidationError(
                "fields_invalid", path, "source file fields are not closed"
            )
        return cls(
            source_file_id=str(data["source_file_id"]),
            display_path=str(data["display_path"]),
            path_kind=str(data["path_kind"]),
            content_hash=str(data["content_hash"]),
            byte_length=data["byte_length"],
            uri=str(data["uri"]),
        )


@dataclass(frozen=True, slots=True)
class FeatureGraphArtifact:
    """Closed, replayable feature DAG owned by one durable definition."""

    owner_definition_kind: str
    owner_definition_id: str
    owner_revision: str
    graph: Mapping[str, Any]
    result_node_ids: tuple[str, ...]
    external_definitions: tuple[Mapping[str, Any], ...]
    expression_graph: Mapping[str, Any]
    tolerance_graph: Mapping[str, Any]
    frame_graph: Mapping[str, Any]
    semantic_index: Mapping[str, Any]
    source_files: tuple[SourceFileSnapshot, ...]
    content_hash: str = ""
    blobs: Mapping[str, bytes] = field(default_factory=dict, compare=False, repr=False)

    # Lazily-filled cache for `canonical_bytes` (frozen+slots: bypass both via
    # object.__setattr__; excluded from init/repr/compare on purpose).
    _canonical_bytes_memo: bytes | None = field(
        default=None, init=False, repr=False, compare=False
    )

    schema_version: str = field(default=FEATURE_GRAPH_SCHEMA_VERSION, init=False)
    artifact_kind: str = field(default="feature_graph", init=False)
    profile: str = field(default=FEATURE_GRAPH_PROFILE, init=False)

    def __post_init__(self) -> None:
        if self.owner_definition_kind not in {"single_solid", "assembly"}:
            raise ArtifactValidationError(
                "definition_kind_invalid", "/owner/definition_kind", "unsupported kind"
            )
        object.__setattr__(
            self,
            "owner_definition_id",
            validate_logical_id(self.owner_definition_id, "/owner/definition_id"),
        )
        object.__setattr__(
            self,
            "owner_revision",
            validate_revision(self.owner_revision, "/owner/revision"),
        )
        graph = json.loads(canonical_bytes(dict(self.graph)).decode("utf-8"))
        operation_graph = OperationGraph.from_dict(graph)
        if operation_graph.graph_id != self.owner_definition_id:
            raise ArtifactValidationError(
                "graph_owner_invalid",
                "/graph/graph_id",
                "graph_id must equal the owning definition_id",
            )
        if not operation_graph.is_dag():
            raise ArtifactValidationError(
                "graph_invalid", "/graph", "operation graph contains a cycle"
            )
        object.__setattr__(self, "graph", MappingProxyType(graph))

        result_ids = tuple(str(item) for item in self.result_node_ids)
        if len(result_ids) != 1 or len(set(result_ids)) != 1:
            raise ArtifactValidationError(
                "result_invalid", "/result_node_ids", "exactly one result node is required"
            )
        if operation_graph.get_node(result_ids[0]) is None:
            raise ArtifactValidationError(
                "result_invalid", "/result_node_ids/0", "result node does not exist"
            )
        object.__setattr__(self, "result_node_ids", result_ids)

        refs = tuple(MappingProxyType(dict(item)) for item in self.external_definitions)
        for index, ref in enumerate(refs):
            required = {
                "definition_kind",
                "definition_id",
                "revision",
                "content_hash",
            }
            if set(ref) != required:
                raise ArtifactValidationError(
                    "fields_invalid",
                    f"/external_definitions/{index}",
                    "external definition fields are not closed",
                )
            if ref["definition_kind"] not in {"single_solid", "assembly"}:
                raise ArtifactValidationError(
                    "definition_kind_invalid",
                    f"/external_definitions/{index}/definition_kind",
                    "unsupported kind",
                )
            validate_logical_id(
                ref["definition_id"],
                f"/external_definitions/{index}/definition_id",
            )
            validate_revision(
                ref["revision"], f"/external_definitions/{index}/revision"
            )
            validate_hash(
                ref["content_hash"],
                f"/external_definitions/{index}/content_hash",
            )
        ref_ids = [str(item["definition_id"]) for item in refs]
        if ref_ids != sorted(ref_ids, key=lambda item: item.encode("utf-8")) or len(
            ref_ids
        ) != len(set(ref_ids)):
            raise ArtifactValidationError(
                "array_order_invalid",
                "/external_definitions",
                "external definitions must be unique and sorted",
            )
        if self.owner_definition_kind == "single_solid" and refs:
            raise ArtifactValidationError(
                "reference_invalid",
                "/external_definitions",
                "Part feature graphs cannot reference external definitions",
            )
        object.__setattr__(self, "external_definitions", refs)

        for name in (
            "expression_graph",
            "tolerance_graph",
            "frame_graph",
            "semantic_index",
        ):
            value = json.loads(canonical_bytes(dict(getattr(self, name))).decode("utf-8"))
            object.__setattr__(self, name, MappingProxyType(value))

        snapshots = tuple(self.source_files)
        if not all(isinstance(item, SourceFileSnapshot) for item in snapshots):
            raise ArtifactValidationError(
                "source_invalid", "/source_files", "expected SourceFileSnapshot values"
            )
        source_ids = [item.source_file_id for item in snapshots]
        if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
            raise ArtifactValidationError(
                "array_order_invalid",
                "/source_files",
                "source files must be unique and sorted by source_file_id",
            )
        object.__setattr__(self, "source_files", snapshots)
        source_id_set = set(source_ids)
        for index, node in enumerate(graph.get("nodes", [])):
            source = node.get("source") if isinstance(node, Mapping) else None
            if not isinstance(source, Mapping):
                continue
            if "local_path" in source:
                raise ArtifactValidationError(
                    "source_invalid",
                    f"/graph/nodes/{index}/source/local_path",
                    "runtime paths cannot enter a durable graph",
                )
            source_file_id = source.get("source_file_id")
            if source_file_id is not None and source_file_id not in source_id_set:
                raise ArtifactValidationError(
                    "reference_missing",
                    f"/graph/nodes/{index}/source/source_file_id",
                    "source_file_id does not resolve",
                )

        blob_map = {str(path): bytes(payload) for path, payload in self.blobs.items()}
        expected_uris = {item.uri for item in snapshots}
        if set(blob_map) != expected_uris:
            raise ArtifactValidationError(
                "blob_unreferenced",
                "/blobs",
                "source blob set differs from source file records",
            )
        total = 0
        for index, snapshot in enumerate(snapshots):
            payload = blob_map[snapshot.uri]
            total += len(payload)
            if total > DEFAULT_ARTIFACT_LIMITS.max_total_file_input_bytes:
                raise ArtifactValidationError(
                    "resource_limit", "/source_files", "source bytes exceed total limit"
                )
            if len(payload) != snapshot.byte_length:
                raise ArtifactValidationError(
                    "blob_size_mismatch",
                    f"/source_files/{index}/byte_length",
                    "source size differs",
                )
            if sha256_bytes(payload) != snapshot.content_hash:
                raise ArtifactValidationError(
                    "blob_hash_mismatch",
                    f"/source_files/{index}/content_hash",
                    "source hash differs",
                )
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArtifactValidationError(
                    "source_invalid",
                    f"/source_files/{index}",
                    "Python source must be UTF-8",
                ) from exc
        object.__setattr__(self, "blobs", MappingProxyType(blob_map))

        expected_hash = content_hash(self._manifest(content_hash_value=""))
        if self.content_hash and validate_hash(
            self.content_hash, "/content_hash"
        ) != expected_hash:
            raise ArtifactValidationError(
                "hash_invalid", "/content_hash", "feature graph hash differs"
            )
        object.__setattr__(self, "content_hash", expected_hash)
        _schema_validate(self.to_dict())

    def _manifest(self, *, content_hash_value: str) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": self.artifact_kind,
            "profile": self.profile,
            "owner": {
                "definition_kind": self.owner_definition_kind,
                "definition_id": self.owner_definition_id,
                "revision": self.owner_revision,
            },
            "graph": dict(self.graph),
            "result_node_ids": list(self.result_node_ids),
            "external_definitions": [dict(item) for item in self.external_definitions],
            "expression_graph": dict(self.expression_graph),
            "tolerance_graph": dict(self.tolerance_graph),
            "frame_graph": dict(self.frame_graph),
            "semantic_index": dict(self.semantic_index),
            "source_files": [item.to_dict() for item in self.source_files],
            "content_hash": content_hash_value,
        }

    def to_dict(self) -> dict[str, Any]:
        return self._manifest(content_hash_value=self.content_hash)

    @property
    def canonical_bytes(self) -> bytes:
        """Canonical serialization, memoized per instance (artifacts are
        closed payloads; the canonical form is deterministic from fields)."""
        if self._canonical_bytes_memo is None:
            object.__setattr__(self, "_canonical_bytes_memo", canonical_bytes(self.to_dict()))
        return self._canonical_bytes_memo

    def restore_session(self):
        """Restore a detached GraphSession from the durable payload."""

        from ..params.expr import ExpressionGraph
        from ..params.frame import FrameGraph
        from ..recording.graph import GraphSession
        from ..params.tolerance import ToleranceGraph

        expression_graph = ExpressionGraph.from_dict(dict(self.expression_graph))
        tolerance_graph = ToleranceGraph.from_dict(
            dict(self.tolerance_graph), expression_graph
        )
        tolerance_graph.validate(raise_on_failure=True)
        session = GraphSession(graph_id=self.owner_definition_id)
        session.graph = OperationGraph.from_dict(dict(self.graph))
        session.expression_graph = expression_graph
        session.tolerance_graph = tolerance_graph
        session.frame_graph = FrameGraph.from_dict(dict(self.frame_graph))
        session._result_node_ids.extend(self.result_node_ids)
        session._has_explicit_results = True
        return session

    def replay(
        self,
        *,
        strict: bool = True,
        external_definitions: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        from ..recording.serializer import replay_feature_graph

        return replay_feature_graph(
            self,
            strict=strict,
            external_definitions=external_definitions,
        )

    def source_dependencies_match(self, *, project_root: str | Path) -> bool:
        """Return whether every project-relative mapped source still has these bytes."""

        root = Path(project_root).expanduser().resolve()
        for index, snapshot in enumerate(self.source_files):
            if snapshot.path_kind != "project_relative":
                continue
            try:
                path = (root / snapshot.display_path).resolve(strict=True)
                path.relative_to(root)
                payload = _stable_source_bytes(
                    path,
                    max_bytes=DEFAULT_ARTIFACT_LIMITS.max_file_input_bytes,
                    error_path=f"/source_files/{index}",
                )
            except (ArtifactValidationError, OSError, ValueError):
                return False
            if sha256_bytes(payload) != snapshot.content_hash:
                return False
        return True

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        blobs: Mapping[str, bytes] | None = None,
    ) -> "FeatureGraphArtifact":
        _schema_validate(data)
        expected_hash = content_hash(data)
        if data["content_hash"] != expected_hash:
            raise ArtifactValidationError(
                "hash_invalid", "/content_hash", "feature graph hash differs"
            )
        owner = data["owner"]
        return cls(
            owner_definition_kind=str(owner["definition_kind"]),
            owner_definition_id=str(owner["definition_id"]),
            owner_revision=str(owner["revision"]),
            graph=dict(data["graph"]),
            result_node_ids=tuple(str(item) for item in data["result_node_ids"]),
            external_definitions=tuple(
                dict(item) for item in data["external_definitions"]
            ),
            expression_graph=dict(data["expression_graph"]),
            tolerance_graph=dict(data["tolerance_graph"]),
            frame_graph=dict(data["frame_graph"]),
            semantic_index=dict(data["semantic_index"]),
            source_files=tuple(
                SourceFileSnapshot.from_dict(item, f"/source_files/{index}")
                for index, item in enumerate(data["source_files"])
            ),
            content_hash=str(data["content_hash"]),
            blobs=blobs or {},
        )


def _semantic_index(session: Any) -> dict[str, Any]:
    geometry_registry: list[dict[str, Any]] = []
    semantic_entity_registry: list[dict[str, Any]] = []
    sketch_profile_registry: list[dict[str, Any]] = []
    semantic_delta_log: list[dict[str, Any]] = []
    topology_delta_log: list[dict[str, Any]] = []
    semantic_bindings: list[dict[str, Any]] = []
    sketch_ops = {
        "make_point_rvertex",
        "make_line_redge",
        "make_circle_redge",
        "make_three_point_arc_redge",
        "make_angle_arc_redge",
        "make_spline_redge",
        "make_interpolated_spline_redge",
        "make_helix_redge",
        "make_wire_from_edges_rwire",
        "make_face_from_wire_rface",
        "make_face_from_wires_rface",
        "make_wire_from_sketch_rwire",
        "make_face_from_sketch_rface",
    }
    for node in session.graph.topological_order():
        binding = node.params.get("tag_binding")
        if node.op == "apply_tag_rselection" and isinstance(binding, Mapping):
            semantic_bindings.append(dict(binding))
        if node.semantic_delta is not None:
            delta = semantic_delta_to_dict(node.semantic_delta)
            semantic_delta_log.append(
                {"node_id": node.node_id, "op": node.op, "delta": delta}
            )
            for ref in node.semantic_delta.created:
                record = {
                    "graph_id": ref.graph_id,
                    "node_id": ref.node_id,
                    "entity_type": ref.entity_type,
                    "entity_id": ref.entity_id,
                    "source_op": node.op,
                }
                geometry_registry.append(record)
                semantic_entity_registry.append(dict(record))
        else:
            for slot in range(node.output_count):
                geometry_registry.append(
                    {
                        "graph_id": session.graph.graph_id,
                        "node_id": node.node_id,
                        "entity_type": "ShapeOutput",
                        "entity_id": f"{node.op}:{slot}",
                        "source_op": node.op,
                    }
                )
        if node.topo_delta is not None:
            topology_delta_log.append(
                {
                    "node_id": node.node_id,
                    "op": node.op,
                    "delta": topo_delta_to_dict(node.topo_delta),
                }
            )
        if node.op in sketch_ops:
            sketch_profile_registry.append(
                {
                    "graph_id": session.graph.graph_id,
                    "node_id": node.node_id,
                    "op": node.op,
                    "params": dict(node.params),
                }
            )
    return {
        "geometry_registry": geometry_registry,
        "semantic_entity_registry": semantic_entity_registry,
        "sketch_profile_registry": sketch_profile_registry,
        "semantic_delta_log": semantic_delta_log,
        "topology_delta_log": topology_delta_log,
        "semantic_bindings": semantic_bindings,
    }


def capture_feature_graph(
    *,
    session: Any,
    owner_definition_kind: str,
    owner_definition_id: str,
    owner_revision: str,
    project_root: str | Path,
    external_definitions: Sequence[Mapping[str, Any]] = (),
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> FeatureGraphArtifact:
    """Freeze one live definition-local session and every resolvable source file."""

    if session.graph.graph_id != owner_definition_id:
        raise ArtifactValidationError(
            "graph_owner_invalid", "/graph/graph_id", "session graph owner differs"
        )
    root = Path(project_root).expanduser().resolve()
    graph_payload = session.graph.to_dict()
    payload_nodes = {
        str(item["node_id"]): item for item in graph_payload.get("nodes", [])
    }
    source_records: dict[str, SourceFileSnapshot] = {}
    source_blobs: dict[str, bytes] = {}
    total = 0
    for node_index, node in enumerate(session.graph.topological_order()):
        source = node.source
        if not isinstance(source, Mapping):
            continue
        durable = canonical_source_payload(dict(source)) or {}
        local_path = source.get("local_path")
        if isinstance(local_path, str) and local_path:
            resolved = Path(local_path).expanduser().resolve()
            payload = _stable_source_bytes(
                resolved,
                max_bytes=limits.max_file_input_bytes,
                error_path=f"/graph/nodes/{node_index}/source",
            )
            total += len(payload)
            if total > limits.max_total_file_input_bytes:
                raise ArtifactValidationError(
                    "resource_limit", "/source_files", "source bytes exceed total limit"
                )
            try:
                display_path = resolved.relative_to(root).as_posix()
                path_kind = "project_relative"
            except ValueError:
                display_path = str(durable.get("path") or resolved.name)
                path_kind = "external"
            content_digest = sha256_bytes(payload)
            source_file_id = sha256_bytes(
                canonical_bytes(
                    {
                        "display_path": display_path,
                        "content_hash": content_digest,
                    }
                )
            )
            uri = (
                "sources/sha256/"
                + content_digest.removeprefix("sha256:")
                + ".py"
            )
            snapshot = SourceFileSnapshot(
                source_file_id=source_file_id,
                display_path=display_path,
                path_kind=path_kind,
                content_hash=content_digest,
                byte_length=len(payload),
                uri=uri,
            )
            prior = source_records.get(source_file_id)
            if prior is not None and prior != snapshot:
                raise ArtifactValidationError(
                    "source_invalid",
                    f"/graph/nodes/{node_index}/source",
                    "source identity collision",
                )
            source_records[source_file_id] = snapshot
            source_blobs[uri] = payload
            durable["source_file_id"] = source_file_id
            durable["path"] = display_path
            durable["path_kind"] = path_kind
        payload_nodes[node.node_id]["source"] = durable

    artifact = FeatureGraphArtifact(
        owner_definition_kind=owner_definition_kind,
        owner_definition_id=owner_definition_id,
        owner_revision=owner_revision,
        graph=graph_payload,
        result_node_ids=tuple(session.result_node_ids),
        external_definitions=tuple(
            sorted(
                (dict(item) for item in external_definitions),
                key=lambda item: str(item["definition_id"]).encode("utf-8"),
            )
        ),
        expression_graph=session.expression_graph.to_dict(),
        tolerance_graph=session.tolerance_graph.to_dict(),
        frame_graph=session.frame_graph.to_dict(),
        semantic_index=_semantic_index(session),
        source_files=tuple(
            source_records[key] for key in sorted(source_records)
        ),
        blobs=source_blobs,
    )
    return artifact


def encode_feature_graph_artifact(artifact: FeatureGraphArtifact) -> bytes:
    """Encode one feature graph and its source snapshots canonically."""

    if not isinstance(artifact, FeatureGraphArtifact):
        raise TypeError("artifact must be a FeatureGraphArtifact")
    return canonical_zip_bytes(
        {_FEATURE_GRAPH_MANIFEST: artifact.canonical_bytes, **artifact.blobs},
        manifest_name=_FEATURE_GRAPH_MANIFEST,
    )


def load_feature_graph_artifact(
    data: bytes | bytearray | memoryview | str | Path,
) -> FeatureGraphArtifact:
    """Read and fully validate one canonical feature graph archive.

    Archives are content-addressed, so loads are memoized by SHA-256 of the
    raw bytes: repeated loads of the same artifact (scene compilation and
    package validation both re-read definitions) return the same closed
    instance instead of re-running zip preflight, schema validation, and
    graph reconstruction. The returned artifact is shared — treat it as
    read-only (the artifact contract already requires this).
    """
    raw = Path(data).read_bytes() if isinstance(data, (str, Path)) else bytes(data)
    key = sha256_bytes(raw)
    with _LOAD_CACHE_LOCK:
        cached = _LOAD_CACHE.get(key)
        if cached is not None:
            _LOAD_CACHE.move_to_end(key)
            return cached
    artifact = _load_feature_graph_artifact(raw)
    with _LOAD_CACHE_LOCK:
        _LOAD_CACHE[key] = artifact
        while len(_LOAD_CACHE) > _LOAD_CACHE_MAX:
            _LOAD_CACHE.popitem(last=False)
    return artifact


def _load_feature_graph_artifact(raw: bytes) -> FeatureGraphArtifact:
    """Uncached load: fully validate and reconstruct one feature graph."""
    archive = preflight_zip_bytes(raw, manifest_name=_FEATURE_GRAPH_MANIFEST)
    manifest = parse_canonical_json(archive.members[_FEATURE_GRAPH_MANIFEST])
    if not isinstance(manifest, Mapping):
        raise ArtifactValidationError(
            "type_invalid", "/", "feature graph manifest must be an object"
        )
    _schema_validate(manifest)
    records = manifest["source_files"]
    expected = {
        _FEATURE_GRAPH_MANIFEST,
        *(str(item["uri"]) for item in records),
    }
    if set(archive.members) != expected:
        raise ArtifactValidationError(
            "blob_unreferenced",
            "/blobs",
            "archive member set differs from source file records",
        )
    blobs = {
        str(item["uri"]): archive.members[str(item["uri"])] for item in records
    }
    return FeatureGraphArtifact.from_dict(manifest, blobs=blobs)


__all__ = [
    "FEATURE_GRAPH_MEDIA_TYPE",
    "FEATURE_GRAPH_PROFILE",
    "FEATURE_GRAPH_SCHEMA_VERSION",
    "FeatureGraphArtifact",
    "SourceFileSnapshot",
    "capture_feature_graph",
    "encode_feature_graph_artifact",
    "load_feature_graph_artifact",
]
