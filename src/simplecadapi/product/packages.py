"""Canonical v3 package for durable Part/Assembly definitions and projections."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from ..artifacts.assembly_definition import AssemblyDefinition
from ..artifacts.assembly_io import (
    encode_assembly_definition,
    validate_assembly_definition_graph,
)
from ..artifacts.canonical import (
    ArtifactLimits,
    ArtifactValidationError,
    DEFAULT_ARTIFACT_LIMITS,
    canonical_bytes,
    content_hash,
    parse_canonical_json,
    sha256_bytes,
)
from ..artifacts.feature_graph import FEATURE_GRAPH_MEDIA_TYPE, load_feature_graph_artifact
from ..artifacts.part_definition import PartDefinition
from ..artifacts.part_io import encode_part_definition, load_part_definition
from ..artifacts.validation import parse_artifact_json
from ..errors import SimpleCADMessageError
from .occurrence import (
    ProductOccurrenceGraph,
    compile_product_occurrence_graph,
    encode_product_occurrence_graph,
    read_product_occurrence_graph,
)
from ..scene.archive import canonical_zip_bytes, preflight_zip_bytes
from ..scene.canonical import canonical_json_bytes
from ..scene.product_scene import (
    ProductSceneError,
    ProductScenePackage,
    compile_product_scene,
    encode_product_scene,
    validate_product_scene_package,
)

PRODUCT_PACKAGE_SCHEMA_VERSION = "3.0"
_MANIFEST_NAME = "package.json"
_FEATURE_GRAPH_MANIFEST = "feature-graph.json"
Definition = PartDefinition | AssemblyDefinition


class ProductPackageError(SimpleCADMessageError):
    """Raised when a product package violates its closed artifact contract."""

    operation = "product_package"


@dataclass(frozen=True, slots=True)
class ProductPackage:
    """Validated package containing definitions, shared blobs, and projections."""

    manifest: Mapping[str, Any]
    objects: Mapping[str, bytes]
    root_definition: Definition = field(compare=False, repr=False)
    _validated_manifest: bytes | None = field(default=None, init=False, compare=False, repr=False)
    _validated_limits: ArtifactLimits | None = field(default=None, init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", MappingProxyType(dict(self.manifest)))
        object.__setattr__(self, "objects", MappingProxyType({str(k): bytes(v) for k, v in self.objects.items()}))
        if not isinstance(self.root_definition, (PartDefinition, AssemblyDefinition)):
            raise TypeError("root_definition must be a PartDefinition or AssemblyDefinition")

    @property
    def content_hash(self) -> str:
        return str(self.manifest["content_hash"])

    @property
    def root_path(self) -> str:
        return str(self.manifest["root"]["path"])

    @property
    def root_kind(self) -> str:
        return self.root_definition.definition_kind

    @property
    def root_id(self) -> str:
        return self.root_definition.definition_id

    @property
    def occurrence_graph_path(self) -> str:
        return str(self.manifest["occurrence_graph"]["path"])

    @property
    def occurrence_graph_bytes(self) -> bytes:
        return self.objects[self.occurrence_graph_path]

    @property
    def occurrence_graph(self) -> ProductOccurrenceGraph:
        return read_product_occurrence_graph(self.occurrence_graph_bytes)

    @property
    def scene_path(self) -> str | None:
        projection = self.manifest.get("projections", {}).get("scene")
        return None if projection is None else str(projection["manifest"]["path"])

    @property
    def scene(self) -> ProductScenePackage:
        return _materialize_scene_projection(self)

    @property
    def scene_bytes(self) -> bytes:
        return encode_product_scene(self.scene)


def _mark_package_validated(package: ProductPackage, limits: ArtifactLimits) -> None:
    object.__setattr__(package, "_validated_manifest", canonical_bytes(dict(package.manifest)))
    object.__setattr__(package, "_validated_limits", limits)


def _package_is_validated(package: ProductPackage, limits: ArtifactLimits) -> bool:
    return package._validated_limits == limits and package._validated_manifest == canonical_bytes(dict(package.manifest))


@lru_cache(maxsize=1)
def _schema() -> Mapping[str, Any]:
    resource = files("simplecadapi").joinpath("contracts/product-package-3.schema.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def _schema_validate(manifest: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(dict(manifest)),
        key=lambda item: (list(item.absolute_path), item.message),
    )
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(item) for item in error.absolute_path)
        raise ProductPackageError(f"product package schema invalid at {pointer}: {error.message}")


def _coerce_definition(value: Any) -> Definition:
    definition = value if isinstance(value, (PartDefinition, AssemblyDefinition)) else getattr(value, "definition", None)
    if not isinstance(definition, (PartDefinition, AssemblyDefinition)):
        raise TypeError("value must be a PartDefinition, AssemblyDefinition, PartBuildResult, or AssemblyBuildResult")
    return definition


def _definition_path(definition: Definition) -> str:
    kind = "part" if isinstance(definition, PartDefinition) else "assembly"
    return f"definitions/{kind}/{definition.content_hash.removeprefix('sha256:')}.json"


def _definition_bytes(definition: Definition) -> bytes:
    return encode_part_definition(definition) if isinstance(definition, PartDefinition) else encode_assembly_definition(definition)


@dataclass(frozen=True, slots=True)
class _BlobRole:
    runtime_attr: str
    manifest_path: tuple[str, ...]
    path_prefix: str
    required: bool = True


# One declarative list drives both runtime-definition and manifest extraction.
# The manifest path is relative to a PartDefinition/AssemblyDefinition JSON
# object, while path_prefix identifies the definition-local blob namespace.
_ASSEMBLY_BLOB_ROLES = (
    _BlobRole("feature_graph_ref", ("feature_graph_ref",), "features/"),
)
_PART_BLOB_ROLES = (
    _BlobRole("feature_graph_ref", ("definition", "feature_graph_ref"), "features/"),
    _BlobRole("solid_cache_ref", ("solid_cache", "body_ref"), "body/"),
    _BlobRole("topology_snapshot_ref", ("topology_snapshot_ref",), "topology/"),
    _BlobRole("material_ref", ("material_ref",), "material/", required=False),
)


def _blob_roles(kind: str) -> tuple[_BlobRole, ...]:
    return _PART_BLOB_ROLES if kind == "single_solid" else _ASSEMBLY_BLOB_ROLES


def _manifest_ref(manifest: Mapping[str, Any], path: tuple[str, ...]) -> Mapping[str, Any] | None:
    value: Any = manifest
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value if isinstance(value, Mapping) else None


def _definition_refs(definition: Definition) -> list[Mapping[str, Any]]:
    refs: list[Mapping[str, Any]] = []
    for role in _blob_roles(definition.definition_kind):
        ref = getattr(definition, role.runtime_attr, None)
        if ref is None:
            if role.required:
                raise ProductPackageError(
                    f"definition {definition.definition_id!r} is missing {role.runtime_attr}"
                )
            continue
        path = str(ref.path)
        if not path.startswith(role.path_prefix):
            raise ProductPackageError(
                f"definition blob path {path!r} outside its semantic domain {role.path_prefix!r}"
            )
        refs.append(ref.to_dict())
    return refs


def _definition_closure(root: Definition) -> dict[str, Definition]:
    definitions: dict[str, Definition] = {}
    active: set[str] = set()

    def visit(definition: Definition) -> None:
        existing = definitions.get(definition.definition_id)
        if existing is not None:
            if existing.definition_kind != definition.definition_kind or existing.content_hash != definition.content_hash:
                raise ProductPackageError(f"definition_id {definition.definition_id!r} resolves to multiple identities")
            return
        if definition.definition_id in active:
            raise ProductPackageError(f"cyclic definition graph at {definition.definition_id!r}")
        active.add(definition.definition_id)
        try:
            definitions[definition.definition_id] = definition
            if isinstance(definition, AssemblyDefinition):
                for ref in definition.definition_refs:
                    child = definition.resolved_definitions.get(ref.definition_id)
                    if not isinstance(child, (PartDefinition, AssemblyDefinition)):
                        raise ProductPackageError(f"assembly {definition.definition_id!r} has unresolved definition {ref.definition_id!r}")
                    visit(child)
        finally:
            active.remove(definition.definition_id)

    visit(root)
    return definitions


class _BlobStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.objects: dict[str, bytes] = {}

    def add_member(self, payload: bytes, *, media_type: str) -> str:
        digest = sha256_bytes(payload)
        path = f"blobs/{digest.removeprefix('sha256:')}"
        record = {
            "sha256": digest,
            "byte_length": len(payload),
            "media_type": media_type,
            "storage": {"kind": "member", "path": path},
        }
        previous = self.records.get(digest)
        if previous is not None and previous != record:
            raise ProductPackageError(f"blob {digest!r} has incompatible records")
        self.records[digest] = record
        self.objects[path] = bytes(payload)
        return digest

    def add_archive(self, payload: bytes, *, media_type: str, manifest_name: str) -> str:
        digest = sha256_bytes(payload)
        archive = preflight_zip_bytes(payload, manifest_name=manifest_name)
        members = [
            {
                "path": path,
                "sha256": self.add_member(
                    member,
                    media_type=(
                        "application/json"
                        if path == manifest_name
                        else "text/x-python; charset=utf-8"
                        if path.endswith(".py")
                        else "application/octet-stream"
                    ),
                ),
            }
            for path, member in sorted(archive.members.items())
        ]
        record = {
            "sha256": digest,
            "byte_length": len(payload),
            "media_type": media_type,
            "storage": {
                "kind": "archive",
                "manifest_name": manifest_name,
                "members": members,
            },
        }
        previous = self.records.get(digest)
        if previous is not None and previous != record:
            raise ProductPackageError(f"archive blob {digest!r} has incompatible records")
        self.records[digest] = record
        return digest

    def add_definition_blob(self, payload: bytes, ref: Mapping[str, Any]) -> str:
        media_type = str(ref.get("media_type", "application/json"))
        digest = (
            self.add_archive(payload, media_type=media_type, manifest_name=_FEATURE_GRAPH_MANIFEST)
            if media_type == FEATURE_GRAPH_MEDIA_TYPE
            else self.add_member(payload, media_type=media_type)
        )
        if digest != str(ref["sha256"]) or len(payload) != int(ref["byte_length"]):
            raise ProductPackageError("definition blob identity differs")
        return digest

    def records_sorted(self) -> list[dict[str, Any]]:
        return [self.records[key] for key in sorted(self.records)]


def _collect_blobs(definitions: Mapping[str, Definition], store: _BlobStore) -> None:
    for definition in definitions.values():
        for ref in _definition_refs(definition):
            path = str(ref["path"])
            payload = definition.blobs.get(path)
            if payload is None:
                raise ProductPackageError(f"definition {definition.definition_id!r} is missing blob {path!r}")
            store.add_definition_blob(payload, ref)


def _scene_blob_media_type(uri: str) -> str:
    if uri.endswith(".py"):
        return "text/x-python; charset=utf-8"
    if uri.endswith(".json"):
        return "application/json"
    if uri.endswith(".glb"):
        return "model/gltf-binary"
    if uri.endswith(".zip"):
        return "application/zip"
    return "application/octet-stream"


def _member_record(path: str, payload: bytes, media_type: str) -> dict[str, Any]:
    return {
        "path": path,
        "sha256": sha256_bytes(payload),
        "byte_length": len(payload),
        "media_type": media_type,
    }


def _scene_projection(root: Definition, store: _BlobStore, objects: dict[str, bytes]) -> dict[str, Any]:
    scene = compile_product_scene(root)
    manifest_path = "projections/scene/scene.json"
    manifest_payload = canonical_json_bytes(dict(scene.manifest))
    objects[manifest_path] = manifest_payload
    product_by_uri = {
        str(item["uri"]): str(item["definition_id"])
        for item in scene.manifest["product_assets"]
    }
    feature_by_uri = {
        str(item["uri"]): str(item["definition_id"])
        for item in scene.manifest["feature_graph_assets"]
    }
    assets: list[dict[str, Any]] = []
    definitions = _definition_closure(root)
    for uri, payload in sorted(scene.blobs.items()):
        if uri in product_by_uri:
            source = {"kind": "definition", "definition_id": product_by_uri[uri]}
        elif uri in feature_by_uri:
            definition = definitions[feature_by_uri[uri]]
            source = {"kind": "blob", "sha256": str(definition.feature_graph_ref.sha256)}
        else:
            digest = store.add_member(
                payload,
                media_type=_scene_blob_media_type(uri),
            )
            source = {"kind": "blob", "sha256": digest}
        assets.append({"uri": uri, "source": source})
    return {
        "manifest": _member_record(
            manifest_path,
            manifest_payload,
            "application/vnd.simplecad.scene+json",
        ),
        "scene_id": str(scene.manifest["scene_id"]),
        "revision": str(scene.manifest["revision"]),
        "assets": assets,
    }


def build_product_package(
    value: Any,
    *,
    include_scene: bool = True,
    validate: bool = True,
) -> ProductPackage:
    root = _coerce_definition(value)
    definitions = _definition_closure(root)
    store = _BlobStore()
    _collect_blobs(definitions, store)
    objects = store.objects
    definition_records: list[dict[str, Any]] = []
    for definition in definitions.values():
        payload = canonical_bytes(definition.to_dict())
        path = _definition_path(definition)
        objects[path] = payload
        definition_records.append({"path": path, "definition_kind": definition.definition_kind, "definition_id": definition.definition_id, "revision": definition.revision, "content_hash": definition.content_hash, "sha256": sha256_bytes(payload), "byte_length": len(payload)})
    occurrence_payload = encode_product_occurrence_graph(compile_product_occurrence_graph(root))
    occurrence_path = "occurrences/root.json"
    objects[occurrence_path] = occurrence_payload
    projections: dict[str, Any] = {}
    if include_scene:
        projections["scene"] = _scene_projection(root, store, objects)
    occurrence_record = _member_record(occurrence_path, occurrence_payload, "application/vnd.simplecad.occurrence+json")
    draft = {
        "schema_version": PRODUCT_PACKAGE_SCHEMA_VERSION,
        "artifact_kind": "product_package",
        "root": {"path": _definition_path(root), "definition_kind": root.definition_kind, "definition_id": root.definition_id, "revision": root.revision, "content_hash": root.content_hash},
        "definitions": sorted(definition_records, key=lambda item: item["path"].encode("ascii")),
        "blobs": store.records_sorted(),
        "occurrence_graph": occurrence_record,
        "projections": projections,
    }
    manifest = {**draft, "content_hash": content_hash(draft, omit=())}
    package = ProductPackage(manifest=manifest, objects=objects, root_definition=root)
    if validate:
        # Full decode-and-verify round-trip. Trusted in-process callers
        # (e.g. the live export path) may skip it; package LOADERS always
        # validate on their side.
        validate_product_package(package)
    else:
        # Mark trusted-by-construction so encode_product_package does not
        # silently re-run the same verification we just skipped.
        _mark_package_validated(package, DEFAULT_ARTIFACT_LIMITS)
    return package


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    _schema_validate(manifest)
    definition_records = list(manifest["definitions"])
    definition_paths = [str(item["path"]) for item in definition_records]
    if definition_paths != sorted(definition_paths, key=lambda item: item.encode("ascii")):
        raise ProductPackageError("definition records must be unique and path-sorted")
    if len(set(definition_paths)) != len(definition_paths):
        raise ProductPackageError("definition paths must be unique")
    definition_ids = [str(item["definition_id"]) for item in definition_records]
    if len(set(definition_ids)) != len(definition_ids):
        raise ProductPackageError("definition IDs must be unique")
    blob_records = list(manifest["blobs"])
    blob_hashes = [str(item["sha256"]) for item in blob_records]
    if blob_hashes != sorted(blob_hashes) or len(set(blob_hashes)) != len(blob_hashes):
        raise ProductPackageError("blob records must be unique and hash-sorted")
    if manifest["root"]["path"] not in set(definition_paths):
        raise ProductPackageError("package root does not resolve")
    blob_by_hash = {str(item["sha256"]): item for item in blob_records}
    for record in blob_records:
        storage = record["storage"]
        if storage["kind"] == "member":
            if str(storage["path"]) in definition_paths:
                raise ProductPackageError("blob member path collides with definition")
        else:
            member_paths = [str(item["path"]) for item in storage["members"]]
            if member_paths != sorted(member_paths):
                raise ProductPackageError("archive blob members must be path-sorted")
            for member in storage["members"]:
                if str(member["sha256"]) not in blob_by_hash:
                    raise ProductPackageError("archive blob member is not declared")
    projection = manifest.get("projections", {}).get("scene")
    if projection is not None:
        definition_ids_set = set(definition_ids)
        seen_uris: set[str] = set()
        for asset in projection["assets"]:
            uri = str(asset["uri"])
            if uri in seen_uris:
                raise ProductPackageError("scene projection asset URIs must be unique")
            seen_uris.add(uri)
            source = asset["source"]
            if source["kind"] == "definition" and str(source["definition_id"]) not in definition_ids_set:
                raise ProductPackageError("scene projection definition does not resolve")
            if source["kind"] == "blob" and str(source["sha256"]) not in blob_by_hash:
                raise ProductPackageError("scene projection blob does not resolve")
    expected = content_hash({key: value for key, value in manifest.items() if key != "content_hash"}, omit=())
    if manifest["content_hash"] != expected:
        raise ProductPackageError("product package content_hash is invalid")


def _blob_records(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(item["sha256"]): item for item in manifest["blobs"]}


def _resolve_blob(manifest: Mapping[str, Any], objects: Mapping[str, bytes], digest: str, active: set[str] | None = None) -> bytes:
    record = _blob_records(manifest).get(digest)
    if record is None:
        raise ProductPackageError(f"blob {digest!r} is not declared")
    seen = set() if active is None else active
    if digest in seen:
        raise ProductPackageError(f"blob storage cycle at {digest!r}")
    seen.add(digest)
    try:
        storage = record["storage"]
        if storage["kind"] == "member":
            path = str(storage["path"])
            try:
                payload = objects[path]
            except KeyError as exc:
                raise ProductPackageError(f"blob member {path!r} is missing") from exc
        else:
            members: dict[str, bytes] = {}
            for item in storage["members"]:
                member_path = str(item["path"])
                member_digest = str(item["sha256"])
                if member_path in members:
                    raise ProductPackageError(f"archive member {member_path!r} is duplicated")
                members[member_path] = _resolve_blob(manifest, objects, member_digest, active=seen)
            payload = canonical_zip_bytes(members, manifest_name=str(storage["manifest_name"]))
        if len(payload) != int(record["byte_length"]) or sha256_bytes(payload) != digest:
            raise ProductPackageError(f"blob {digest!r} identity differs")
        return payload
    finally:
        seen.remove(digest)


def _definition_archive(kind: str, manifest: Mapping[str, Any], blobs: Mapping[str, bytes]) -> bytes:
    manifest_name = "part-definition.json" if kind == "single_solid" else "assembly-definition.json"
    members = {manifest_name: canonical_bytes(dict(manifest))}
    members.update({"blobs/" + path: payload for path, payload in blobs.items()})
    return canonical_zip_bytes(members, manifest_name=manifest_name)


def _root_matches_manifest(root: Definition, root_record: Mapping[str, Any]) -> bool:
    return (
        root_record["path"] == _definition_path(root)
        and root_record["definition_kind"] == root.definition_kind
        and root_record["definition_id"] == root.definition_id
        and root_record["revision"] == root.revision
        and root_record["content_hash"] == root.content_hash
    )


def _decode_definitions(manifest: Mapping[str, Any], objects: Mapping[str, bytes], limits: ArtifactLimits) -> Definition:
    records = manifest["definitions"]
    if len(records) > limits.max_definitions:
        raise ProductPackageError("product package exceeds definition limit")
    decoded: dict[str, Definition] = {}
    identity_to_id: dict[tuple[str, str, str, str], str] = {}
    for record in records:
        path = str(record["path"])
        payload = objects.get(path)
        if payload is None or len(payload) != int(record["byte_length"]) or sha256_bytes(payload) != str(record["sha256"]):
            raise ProductPackageError(f"definition {path!r} identity differs")
        kind = str(record["definition_kind"])
        definition_manifest = parse_artifact_json(payload, kind="part_definition" if kind == "single_solid" else "assembly_definition", limits=limits)
        refs = _definition_refs_from_manifest(kind, definition_manifest)
        blobs: dict[str, bytes] = {}
        for ref in refs:
            blob = _resolve_blob(manifest, objects, str(ref["sha256"]))
            if len(blob) != int(ref["byte_length"]):
                raise ProductPackageError(f"definition {path!r} blob size differs")
            blobs[str(ref["path"])] = blob
        try:
            archive = _definition_archive(kind, definition_manifest, blobs)
            definition = load_part_definition(archive) if kind == "single_solid" else _decode_assembly_from_archive(archive)
        except (ArtifactValidationError, ValueError) as exc:
            raise ProductPackageError(f"definition {path!r} is invalid: {exc}") from exc
        actual = (definition.definition_kind, definition.definition_id, definition.revision, definition.content_hash)
        expected = (kind, str(record["definition_id"]), str(record["revision"]), str(record["content_hash"]))
        if actual != expected:
            raise ProductPackageError(f"definition {path!r} identity differs")
        decoded[definition.definition_id] = definition
        identity_to_id[actual] = definition.definition_id

    resolved: dict[str, Definition] = {}
    active: set[str] = set()
    reachable: set[str] = set()

    def resolve(definition: Definition) -> Definition:
        if definition.definition_id in resolved:
            return resolved[definition.definition_id]
        if definition.definition_id in active:
            raise ProductPackageError(f"definition cycle through {definition.definition_id!r}")
        reachable.add(definition.definition_id)
        if isinstance(definition, PartDefinition):
            resolved[definition.definition_id] = definition
            return definition
        active.add(definition.definition_id)
        try:
            children: dict[str, Definition] = {}
            for ref in definition.definition_refs:
                key = (ref.definition_kind, ref.definition_id, ref.revision, ref.content_hash)
                child_id = identity_to_id.get(key)
                if child_id is None:
                    raise ProductPackageError(f"assembly {definition.definition_id!r} references missing definition {ref.definition_id!r}")
                children[ref.definition_id] = resolve(decoded[child_id])
            result = replace(definition, resolved_definitions=children)
            resolved[definition.definition_id] = result
            return result
        finally:
            active.remove(definition.definition_id)

    root_id = str(manifest["root"]["definition_id"])
    if root_id not in decoded:
        raise ProductPackageError("root definition is missing")
    root = resolve(decoded[root_id])
    if not _root_matches_manifest(root, manifest["root"]):
        raise ProductPackageError("root definition identity differs")
    if reachable != set(decoded):
        raise ProductPackageError("unreferenced definition exists")
    if isinstance(root, AssemblyDefinition):
        try:
            validate_assembly_definition_graph(root, limits=limits)
        except ArtifactValidationError as exc:
            raise ProductPackageError(f"root assembly graph is invalid: {exc}") from exc
    return root
def _definition_refs_from_manifest(kind: str, manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    refs: list[Mapping[str, Any]] = []
    for role in _blob_roles(kind):
        ref = _manifest_ref(manifest, role.manifest_path)
        if ref is None:
            if role.required:
                raise ProductPackageError(
                    f"definition manifest is missing {'.'.join(role.manifest_path)}"
                )
            continue
        path = str(ref["path"])
        if not path.startswith(role.path_prefix):
            raise ProductPackageError(
                f"definition blob path {path!r} outside its semantic domain {role.path_prefix!r}"
            )
        refs.append(ref)
    return refs


def _decode_assembly_from_archive(data: bytes) -> AssemblyDefinition:
    from ..artifacts.assembly_io import decode_assembly_definition

    return decode_assembly_definition(data)


def _expected_paths(manifest: Mapping[str, Any]) -> set[str]:
    paths = {str(item["path"]) for item in manifest["definitions"]}
    paths.add(str(manifest["occurrence_graph"]["path"]))
    for record in manifest["blobs"]:
        if record["storage"]["kind"] == "member":
            paths.add(str(record["storage"]["path"]))
    scene = manifest.get("projections", {}).get("scene")
    if scene is not None:
        paths.add(str(scene["manifest"]["path"]))
    return paths


def _materialize_scene_projection(package: ProductPackage) -> ProductScenePackage:
    projection = package.manifest.get("projections", {}).get("scene")
    if projection is None:
        raise ProductPackageError("product package has no scene projection")
    record = projection["manifest"]
    payload = package.objects[str(record["path"])]
    if len(payload) != int(record["byte_length"]) or sha256_bytes(payload) != str(record["sha256"]):
        raise ProductPackageError("scene manifest identity differs")
    scene_manifest = parse_canonical_json(payload)
    if not isinstance(scene_manifest, Mapping):
        raise ProductPackageError("scene manifest must be an object")
    if (
        str(scene_manifest["scene_id"]) != str(projection["scene_id"])
        or str(scene_manifest["revision"]) != str(projection["revision"])
    ):
        raise ProductPackageError("scene projection identity differs")
    definitions = _definition_closure(package.root_definition)
    blobs: dict[str, bytes] = {}
    for asset in projection["assets"]:
        uri = str(asset["uri"])
        source = asset["source"]
        if source["kind"] == "definition":
            definition = definitions.get(str(source["definition_id"]))
            if definition is None:
                raise ProductPackageError("scene references unknown definition")
            asset_payload = _definition_bytes(definition)
        else:
            asset_payload = _resolve_blob(package.manifest, package.objects, str(source["sha256"]))
        blobs[uri] = asset_payload
    scene = ProductScenePackage(manifest=scene_manifest, blobs=blobs)
    try:
        validate_product_scene_package(scene)
    except (ProductSceneError, ValueError) as exc:
        raise ProductPackageError(f"scene projection is invalid: {exc}") from exc
    return scene


def _decode_package(
    manifest: Mapping[str, Any],
    objects: Mapping[str, bytes],
    *,
    limits: ArtifactLimits,
) -> ProductPackage:
    _validate_manifest(manifest)
    total_bytes = 0
    for path, payload in objects.items():
        size = len(payload)
        if size > limits.max_blob_bytes:
            raise ProductPackageError(f"package member {path!r} exceeds blob limit")
        total_bytes += size
    if total_bytes > limits.max_total_bytes:
        raise ProductPackageError("product package bytes exceed the limit")
    expected = _expected_paths(manifest)
    if set(objects) != expected:
        raise ProductPackageError(
            f"product package member set differs: missing={sorted(expected - set(objects))}, "
            f"extra={sorted(set(objects) - expected)}"
        )
    root = _decode_definitions(manifest, objects, limits)
    occurrence_record = manifest["occurrence_graph"]
    occurrence_payload = objects[str(occurrence_record["path"])]
    if len(occurrence_payload) != int(occurrence_record["byte_length"]) or sha256_bytes(occurrence_payload) != str(occurrence_record["sha256"]):
        raise ProductPackageError("occurrence graph identity differs")
    occurrence = read_product_occurrence_graph(occurrence_payload)
    expected_occurrence = compile_product_occurrence_graph(root)
    if occurrence.canonical_bytes != expected_occurrence.canonical_bytes:
        raise ProductPackageError("occurrence graph differs from definition closure")
    if manifest.get("projections", {}).get("scene") is not None:
        _materialize_scene_projection(ProductPackage(manifest=manifest, objects=objects, root_definition=root))
    return ProductPackage(manifest=manifest, objects=objects, root_definition=root)


def validate_product_package(package: ProductPackage, *, limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS) -> None:
    if not isinstance(package, ProductPackage):
        raise TypeError("package must be a ProductPackage")
    decoded = _decode_package(package.manifest, package.objects, limits=limits)
    if (
        decoded.root_definition.definition_kind != package.root_definition.definition_kind
        or decoded.root_definition.definition_id != package.root_definition.definition_id
        or decoded.root_definition.revision != package.root_definition.revision
        or decoded.root_definition.content_hash != package.root_definition.content_hash
    ):
        raise ProductPackageError("root_definition differs from packaged root")
    _mark_package_validated(package, limits)


def encode_product_package(package: ProductPackage) -> bytes:
    if not _package_is_validated(package, DEFAULT_ARTIFACT_LIMITS):
        validate_product_package(package)
    return canonical_zip_bytes(
        {_MANIFEST_NAME: canonical_bytes(dict(package.manifest)), **package.objects},
        manifest_name=_MANIFEST_NAME,
    )


def read_product_package(
    data: bytes | bytearray | memoryview | str | Path,
    *,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> ProductPackage:
    try:
        raw = Path(data).read_bytes() if isinstance(data, (str, Path)) else bytes(data)
        archive = preflight_zip_bytes(raw, manifest_name=_MANIFEST_NAME)
        manifest = parse_canonical_json(archive.members[_MANIFEST_NAME])
        if not isinstance(manifest, Mapping):
            raise ProductPackageError("package.json must contain an object")
        objects = {path: payload for path, payload in archive.members.items() if path != _MANIFEST_NAME}
        package = _decode_package(manifest, objects, limits=limits)
        _mark_package_validated(package, limits)
        return package
    except ProductPackageError:
        raise
    except (ArtifactValidationError, OSError, ValueError) as exc:
        raise ProductPackageError(f"invalid product package: {exc}") from exc


def load_product_package(
    data: bytes | bytearray | memoryview | str | Path,
    *,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> Definition:
    return read_product_package(data, limits=limits).root_definition


__all__ = [
    "PRODUCT_PACKAGE_SCHEMA_VERSION",
    "ProductPackage",
    "ProductPackageError",
    "build_product_package",
    "encode_product_package",
    "load_product_package",
    "read_product_package",
    "validate_product_package",
]
