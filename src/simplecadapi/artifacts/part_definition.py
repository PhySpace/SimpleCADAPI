"""Persistent PartDefinition contract: one evaluated Solid, or several named bodies.

A one-body part is what every PartDefinition was: ``solid_cache.body_ref`` is the BRep of its Solid and
``topology_snapshot_ref`` the semantic state of that Solid.  A multi-body part also lists ``solid_cache.bodies``:
one :class:`BodyRef` per body (its own BRep and topology snapshot, so each body keeps its tags), in body order.  Its
``body_ref`` is then a BRep Compound of every body (what a geometry-only reader such as STEP needs, and what a reader
that expects exactly one Solid refuses), and ``topology_snapshot_ref`` repeats the first body's snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .canonical import (
    ARTIFACT_SCHEMA_VERSION,
    PART_DEFINITION_PROFILE,
    ArtifactValidationError,
    canonical_bytes,
    content_hash,
    validate_hash,
    validate_json_value,
    validate_logical_id,
    validate_revision,
)
from .references import (
    BlobRef,
    ConnectorInterface,
    FileInputSnapshot,
    InterfaceHashes,
    MaterialRef,
)


@dataclass(frozen=True, slots=True)
class BodyRef:
    """One body of a multi-body PartDefinition: its id, display name, BRep and topology snapshot."""

    body_id: str
    name: str | None
    body_ref: BlobRef
    topology_snapshot_ref: BlobRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "body_id", validate_logical_id(self.body_id, "/solid_cache/bodies/body_id"))
        if self.name is not None and (not isinstance(self.name, str) or not self.name):
            raise ArtifactValidationError("name_invalid", "/solid_cache/bodies/name", "expected a name or null")
        if not isinstance(self.body_ref, BlobRef) or not isinstance(self.topology_snapshot_ref, BlobRef):
            raise ArtifactValidationError("reference_invalid", "/solid_cache/bodies", "expected BlobRef values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_id": self.body_id,
            "name": self.name,
            "body_ref": self.body_ref.to_dict(),
            "topology_snapshot_ref": self.topology_snapshot_ref.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "BodyRef":
        return cls(
            body_id=str(data["body_id"]),
            name=data.get("name"),
            body_ref=BlobRef.from_dict(data["body_ref"], f"{path}/body_ref"),
            topology_snapshot_ref=BlobRef.from_dict(data["topology_snapshot_ref"], f"{path}/topology_snapshot_ref"),
        )


@dataclass(frozen=True, slots=True)
class PartDefinition:
    """Validated durable definition for exactly one evaluated Solid."""

    definition_id: str
    revision: str
    tolerance_profile: str
    generator: Mapping[str, Any]
    feature_graph_ref: BlobRef
    solid_cache_ref: BlobRef
    topology_snapshot_ref: BlobRef
    connectors: tuple[ConnectorInterface, ...]
    material_ref: MaterialRef | None
    file_inputs: tuple[FileInputSnapshot, ...]
    interface_hashes: InterfaceHashes
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    blobs: Mapping[str, bytes] = field(default_factory=dict, compare=False, repr=False)
    bodies: tuple[BodyRef, ...] = ()  # empty for a one-body part; else every body, in order (at least two)
    _validated_manifest: bytes | None = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )
    _validated_body: Any = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )
    _validated_feature_graph: Any = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )

    schema_version: str = field(default=ARTIFACT_SCHEMA_VERSION, init=False)
    artifact_kind: str = field(default="part_definition", init=False)
    definition_kind: str = field(default="single_solid", init=False)
    units: str = field(default="mm", init=False)
    profile: str = field(default=PART_DEFINITION_PROFILE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definition_id",
            validate_logical_id(self.definition_id, "/definition_id"),
        )
        object.__setattr__(self, "revision", validate_revision(self.revision))
        if (
            not isinstance(self.tolerance_profile, str)
            or not self.tolerance_profile
            or len(self.tolerance_profile) > 128
        ):
            raise ArtifactValidationError(
                "profile_invalid", "/tolerance_profile", "invalid tolerance profile"
            )
        if not isinstance(self.feature_graph_ref, BlobRef):
            raise ArtifactValidationError(
                "reference_invalid", "/feature_graph_ref", "expected BlobRef"
            )
        if not isinstance(self.solid_cache_ref, BlobRef):
            raise ArtifactValidationError(
                "reference_invalid", "/solid_cache_ref", "expected BlobRef"
            )
        if not isinstance(self.topology_snapshot_ref, BlobRef):
            raise ArtifactValidationError(
                "reference_invalid", "/topology_snapshot_ref", "expected BlobRef"
            )
        connectors = tuple(self.connectors)
        if not all(isinstance(item, ConnectorInterface) for item in connectors):
            raise ArtifactValidationError(
                "connector_invalid", "/connectors", "expected ConnectorInterface values"
            )
        connector_ids = [item.connector_id for item in connectors]
        if len(set(connector_ids)) != len(connector_ids):
            raise ArtifactValidationError(
                "connector_invalid", "/connectors", "connector IDs must be unique"
            )
        object.__setattr__(self, "connectors", connectors)
        bodies = tuple(self.bodies)
        if bodies:
            if len(bodies) < 2 or not all(isinstance(item, BodyRef) for item in bodies):
                raise ArtifactValidationError(
                    "bodies_invalid", "/solid_cache/bodies", "expected two or more BodyRef values"
                )
            body_ids = [item.body_id for item in bodies]
            if len(set(body_ids)) != len(body_ids):
                raise ArtifactValidationError("bodies_invalid", "/solid_cache/bodies", "body IDs must be unique")
            if connectors:
                raise ArtifactValidationError(
                    "bodies_invalid", "/connectors", "connectors on a multi-body part are not supported yet"
                )
        object.__setattr__(self, "bodies", bodies)
        if self.material_ref is not None and not isinstance(
            self.material_ref, MaterialRef
        ):
            raise ArtifactValidationError(
                "material_invalid", "/material_ref", "expected MaterialRef or null"
            )
        inputs = tuple(self.file_inputs)
        if not all(isinstance(item, FileInputSnapshot) for item in inputs):
            raise ArtifactValidationError(
                "file_input_invalid",
                "/file_inputs",
                "expected FileInputSnapshot values",
            )
        input_paths = [item.path for item in inputs]
        if len(set(input_paths)) != len(input_paths) or input_paths != sorted(
            input_paths, key=lambda item: item.encode("utf-8")
        ):
            raise ArtifactValidationError(
                "array_order_invalid",
                "/file_inputs",
                "file inputs must be unique and sorted",
            )
        object.__setattr__(self, "file_inputs", inputs)
        if not isinstance(self.interface_hashes, InterfaceHashes):
            raise ArtifactValidationError(
                "interface_invalid", "/interface_hashes", "expected InterfaceHashes"
            )
        expected_connectors = {
            item.connector_id: item.interface_hash for item in connectors
        }
        expected_bindings = {
            item.connector_id: item.binding_hash for item in connectors
        }
        if dict(self.interface_hashes.connectors) != expected_connectors:
            raise ArtifactValidationError(
                "interface_invalid",
                "/interface_hashes/connectors",
                "connector hashes differ",
            )
        if dict(self.interface_hashes.bindings) != expected_bindings:
            raise ArtifactValidationError(
                "interface_invalid",
                "/interface_hashes/bindings",
                "binding hashes differ",
            )
        generator = dict(self.generator)
        expected_generator = {
            "simplecadapi_version",
            "ocp_version",
            "python_abi",
            "platform_tag",
            "semantic_registry_version",
        }
        if set(generator) != expected_generator or not all(
            isinstance(value, str) and value for value in generator.values()
        ):
            raise ArtifactValidationError(
                "generator_invalid", "/generator", "generator fields are incomplete"
            )
        object.__setattr__(self, "generator", MappingProxyType(generator))
        metadata = dict(self.metadata)
        validate_json_value(metadata, "/metadata")
        object.__setattr__(self, "metadata", MappingProxyType(metadata))
        blob_map = {str(path): bytes(payload) for path, payload in self.blobs.items()}
        object.__setattr__(self, "blobs", MappingProxyType(blob_map))
        expected_hash = content_hash(self._manifest(content_hash_value=""))
        if (
            self.content_hash
            and validate_hash(self.content_hash, "/content_hash") != expected_hash
        ):
            raise ArtifactValidationError(
                "hash_invalid",
                "/content_hash",
                "content hash does not match definition",
            )
        object.__setattr__(self, "content_hash", expected_hash)

    def _manifest(self, *, content_hash_value: str) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": self.artifact_kind,
            "definition_kind": self.definition_kind,
            "definition_id": self.definition_id,
            "revision": self.revision,
            "content_hash": content_hash_value,
            "units": self.units,
            "tolerance_profile": self.tolerance_profile,
            "profile": self.profile,
            "generator": dict(self.generator),
            "definition": {
                "kind": "feature_graph",
                "feature_graph_ref": self.feature_graph_ref.to_dict(),
            },
            "solid_cache": {
                "evaluator_profile": "ocp-evaluated-solid-1",
                "body_ref": self.solid_cache_ref.to_dict(),
                # a one-body part writes the manifest it always wrote (same bytes, same content hash)
                **({"bodies": [item.to_dict() for item in self.bodies]} if self.bodies else {}),
            },
            "topology_snapshot_ref": self.topology_snapshot_ref.to_dict(),
            "connectors": [item.to_dict() for item in self.connectors],
            "material_ref": (
                self.material_ref.to_dict() if self.material_ref is not None else None
            ),
            "file_inputs": [item.to_dict() for item in self.file_inputs],
            "interface_hashes": self.interface_hashes.to_dict(),
            "metadata": dict(self.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self._manifest(content_hash_value=self.content_hash)

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        blobs: Mapping[str, bytes] | None = None,
    ) -> "PartDefinition":
        from .validation import validate_manifest

        validate_manifest(data, "part_definition")
        definition = data["definition"]
        cache = data["solid_cache"]
        return cls(
            definition_id=str(data["definition_id"]),
            revision=str(data["revision"]),
            tolerance_profile=str(data["tolerance_profile"]),
            generator=dict(data["generator"]),
            feature_graph_ref=BlobRef.from_dict(
                definition["feature_graph_ref"], "/definition/feature_graph_ref"
            ),
            solid_cache_ref=BlobRef.from_dict(
                cache["body_ref"], "/solid_cache/body_ref"
            ),
            topology_snapshot_ref=BlobRef.from_dict(
                data["topology_snapshot_ref"], "/topology_snapshot_ref"
            ),
            connectors=tuple(
                ConnectorInterface.from_dict(item, f"/connectors/{index}")
                for index, item in enumerate(data["connectors"])
            ),
            material_ref=(
                MaterialRef.from_dict(data["material_ref"])
                if data["material_ref"] is not None
                else None
            ),
            file_inputs=tuple(
                FileInputSnapshot.from_dict(item, f"/file_inputs/{index}")
                for index, item in enumerate(data["file_inputs"])
            ),
            interface_hashes=InterfaceHashes.from_dict(data["interface_hashes"]),
            metadata=dict(data["metadata"]),
            content_hash=str(data["content_hash"]),
            blobs=blobs or {},
            bodies=tuple(
                BodyRef.from_dict(item, f"/solid_cache/bodies/{index}")
                for index, item in enumerate(cache.get("bodies") or ())
            ),
        )


def mark_part_definition_validated(
    definition: PartDefinition,
    *,
    body: Any = None,
    feature_graph: Any = None,
) -> None:
    object.__setattr__(definition, "_validated_manifest", definition.canonical_bytes)
    object.__setattr__(definition, "_validated_body", body)
    object.__setattr__(definition, "_validated_feature_graph", feature_graph)


def part_definition_is_validated(definition: PartDefinition) -> bool:
    return definition._validated_manifest == definition.canonical_bytes


def take_validated_part_body(definition: PartDefinition) -> Any:
    if not part_definition_is_validated(definition):
        object.__setattr__(definition, "_validated_body", None)
        object.__setattr__(definition, "_validated_feature_graph", None)
        return None
    body = definition._validated_body
    object.__setattr__(definition, "_validated_body", None)
    return body


def validated_part_feature_graph(definition: PartDefinition) -> Any:
    if not part_definition_is_validated(definition):
        object.__setattr__(definition, "_validated_feature_graph", None)
        return None
    return definition._validated_feature_graph


__all__ = ["BodyRef", "PartDefinition"]
