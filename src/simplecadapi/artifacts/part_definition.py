"""Persistent PartDefinition contract: one evaluated Solid.

``solid_cache.body_ref`` is the BRep of the Part's Solid and ``topology_snapshot_ref`` the semantic state of that Solid.

``appearance`` (optional) holds the display appearance of the body when it has one (``set_body_appearance_rpart``):
``{"bodies": [{"body_id", "color", "opacity", "name"}]}``, one row at most.  A definition whose body has no appearance
writes no ``appearance`` key, so its bytes and content hash are what they always were.
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


def _color(value: Any, path: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(isinstance(c, (int, float)) and not isinstance(c, bool) and 0.0 <= float(c) <= 1.0 for c in value)
    ):
        raise ArtifactValidationError("appearance_invalid", path, "expected three numbers in [0, 1] or null")
    return (float(value[0]), float(value[1]), float(value[2]))


@dataclass(frozen=True, slots=True)
class BodyAppearance:
    """The display appearance of the body of a PartDefinition: colour (RGB in [0, 1]), opacity and display name.
    ``None`` fields are unset (the material colour, opaque, the body id)."""

    body_id: str
    color: tuple[float, float, float] | None = None
    opacity: float | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "body_id", validate_logical_id(self.body_id, "/appearance/bodies/body_id"))
        object.__setattr__(self, "color", _color(self.color, "/appearance/bodies/color"))
        if self.opacity is not None:
            if isinstance(self.opacity, bool) or not isinstance(self.opacity, (int, float)) or not 0.0 <= float(self.opacity) <= 1.0:
                raise ArtifactValidationError("appearance_invalid", "/appearance/bodies/opacity", "expected a number in [0, 1] or null")
            object.__setattr__(self, "opacity", float(self.opacity))
        if self.name is not None and (not isinstance(self.name, str) or not self.name):
            raise ArtifactValidationError("name_invalid", "/appearance/bodies/name", "expected a name or null")

    @classmethod
    def of_body(cls, body: Any) -> "BodyAppearance | None":
        """The appearance of a runtime ``Body``, or ``None`` when it has nothing to record."""

        if body.color is None and body.opacity is None and body.name is None:
            return None
        return cls(body_id=body.body_id, color=body.color, opacity=body.opacity, name=body.name)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "body_id": self.body_id,
            "color": list(self.color) if self.color is not None else None,
            "opacity": self.opacity,
        }
        if self.name is not None:
            out["name"] = self.name
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BodyAppearance":
        return cls(body_id=str(data["body_id"]), color=data.get("color"), opacity=data.get("opacity"), name=data.get("name"))


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
    appearance: tuple[BodyAppearance, ...] = ()  # the body's display appearance, when it has one (usually none)
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
        appearance = tuple(self.appearance)
        if not all(isinstance(item, BodyAppearance) for item in appearance):
            raise ArtifactValidationError("appearance_invalid", "/appearance/bodies", "expected BodyAppearance values")
        if len(appearance) > 1:
            raise ArtifactValidationError("appearance_invalid", "/appearance/bodies", "a part has one body")
        object.__setattr__(self, "appearance", appearance)
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
            },
            "topology_snapshot_ref": self.topology_snapshot_ref.to_dict(),
            "connectors": [item.to_dict() for item in self.connectors],
            "material_ref": (
                self.material_ref.to_dict() if self.material_ref is not None else None
            ),
            "file_inputs": [item.to_dict() for item in self.file_inputs],
            "interface_hashes": self.interface_hashes.to_dict(),
            "metadata": dict(self.metadata),
            # only when a body has an appearance: every other definition keeps its bytes
            **({"appearance": {"bodies": [item.to_dict() for item in self.appearance]}} if self.appearance else {}),
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
            appearance=tuple(
                BodyAppearance.from_dict(item) for item in ((data.get("appearance") or {}).get("bodies") or ())
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


def with_definition_appearance(definition: PartDefinition, body: Any) -> Any:
    """The body of *definition* with its appearance: *body* is the Solid ``read_part_body`` gives.  Without an
    appearance it is returned as it is; with one it becomes a ``Body`` (which ``Part(body=...)`` takes) carrying the
    id, display name, colour and opacity."""

    if not definition.appearance:
        return body
    from simplecadapi._cpp import Body

    row = definition.appearance[0]
    return Body(row.body_id, body, row.name, row.color, row.opacity)


__all__ = ["BodyAppearance", "PartDefinition", "with_definition_appearance"]
