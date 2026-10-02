"""External-reference AssemblyDefinition archives and runtime materialization."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from ..product.assembly import (
    Assembly,
    Component,
    PublicConnectorRef,
    _restore_component_occurrence_placements,
)
from ..product.solver import (
    constraint_reports_match,
    inspect_assembly_constraints,
    solve_assembly_constraints,
)
from ..product.connector import (
    Connector,
    ConnectorAnchor,
    ConnectorRef,
    GeometryRef,
)
from ..product.constraint import Constraint, ScalarLimit
from ..product.material import Material
from ..product.part import Part
from ..product.placement import placement_from_canonical, placement_ticks
from ..scene.archive import canonical_zip_bytes, preflight_zip_bytes
from .assembly_definition import (
    AssemblyDefinition,
    assembly_definition_is_validated,
    mark_assembly_definition_validated,
    validated_assembly_feature_graph,
)
from .brep import read_brep_solid
from .canonical import (
    ArtifactLimits,
    ArtifactValidationError,
    DEFAULT_ARTIFACT_LIMITS,
    parse_canonical_json,
)
from .part_definition import (
    PartDefinition,
    mark_part_definition_validated,
    take_validated_part_body,
)
from .part_io import encode_part_definition, load_part_definition
from .references import ConnectorInterface, PartRef
from .topology_snapshot import (
    restore_topology_snapshot,
    validate_connector_entity_bindings,
)
from .feature_graph import load_feature_graph_artifact
from .validation import parse_artifact_json, validate_artifact_blobs

_ASSEMBLY_DEFINITION_MANIFEST = "assembly-definition.json"
_BLOB_PREFIX = "blobs/"
_SOLVER_PROFILE = "simplecad-assembly-solver-1"


def definition_archive_name(definition: PartDefinition | AssemblyDefinition) -> str:
    """Return the content-addressed sibling archive name used by PartRef."""

    digest = definition.content_hash.removeprefix("sha256:")
    suffix = (
        "part-definition.zip"
        if isinstance(definition, PartDefinition)
        else "assembly-definition.zip"
    )
    return f"{digest}.{suffix}"


def encode_assembly_definition(definition: AssemblyDefinition) -> bytes:
    """Encode one assembly manifest and its definition-local graph blob."""

    if not isinstance(definition, AssemblyDefinition):
        raise TypeError("definition must be an AssemblyDefinition")
    if not assembly_definition_is_validated(
        definition,
        DEFAULT_ARTIFACT_LIMITS,
    ):
        validate_artifact_blobs(definition.to_dict(), definition.blobs)
    members: dict[str, bytes] = {
        _ASSEMBLY_DEFINITION_MANIFEST: definition.canonical_bytes,
    }
    for path, payload in definition.blobs.items():
        members[_BLOB_PREFIX + path] = bytes(payload)
    return canonical_zip_bytes(
        members,
        manifest_name=_ASSEMBLY_DEFINITION_MANIFEST,
    )


def decode_assembly_definition(
    data: bytes | bytearray | memoryview,
) -> AssemblyDefinition:
    """Decode one assembly archive without resolving its external references."""

    archive = preflight_zip_bytes(
        data,
        manifest_name=_ASSEMBLY_DEFINITION_MANIFEST,
    )
    manifest = parse_artifact_json(
        archive.members[_ASSEMBLY_DEFINITION_MANIFEST],
        kind="assembly_definition",
    )
    feature_graph_ref = manifest["feature_graph_ref"]
    expected_paths = {str(feature_graph_ref["path"])}
    expected_members = {
        _ASSEMBLY_DEFINITION_MANIFEST,
        *(_BLOB_PREFIX + path for path in expected_paths),
    }
    if set(archive.members) != expected_members:
        raise ArtifactValidationError(
            "blob_unreferenced",
            "/blobs",
            "archive member set differs from definition references",
        )
    blobs = {path: archive.members[_BLOB_PREFIX + path] for path in expected_paths}
    definition = AssemblyDefinition.from_dict(manifest, blobs=blobs)
    validate_artifact_blobs(definition.to_dict(), definition.blobs)
    return definition


def _definition_identity(
    definition: PartDefinition | AssemblyDefinition,
) -> tuple[str, str, str, str]:
    return (
        definition.definition_id,
        definition.definition_kind,
        definition.revision,
        definition.content_hash,
    )


def _connector_ids(
    definition: PartDefinition | AssemblyDefinition,
) -> set[str]:
    connectors = (
        definition.connectors
        if isinstance(definition, PartDefinition)
        else definition.public_connectors
    )
    return {item.connector_id for item in connectors}


def _archive_bytes(
    definition: PartDefinition | AssemblyDefinition,
) -> bytes:
    if isinstance(definition, PartDefinition):
        return encode_part_definition(definition)
    return encode_assembly_definition(definition)


def _validate_ref_identity(
    ref: PartRef,
    definition: PartDefinition | AssemblyDefinition,
    *,
    path: str,
) -> None:
    expected = (
        ref.definition_id,
        ref.definition_kind,
        ref.revision,
        ref.content_hash,
    )
    if _definition_identity(definition) != expected:
        raise ArtifactValidationError(
            "reference_identity_mismatch",
            path,
            "resolved definition ID, kind, revision, or content hash differs",
        )
    payload = _archive_bytes(definition)
    if len(payload) != ref.byte_length:
        raise ArtifactValidationError(
            "reference_size_mismatch",
            path + "/byte_length",
            "resolved definition archive size differs",
        )


def _instance_trace(
    definition: AssemblyDefinition,
    definition_id: str,
) -> str:
    matches = sorted(
        item.instance_id
        for item in definition.instances
        if item.definition_id == definition_id
    )
    return matches[0] if matches else definition_id


def validate_assembly_definition_graph(
    definition: AssemblyDefinition,
    *,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> None:
    """Validate the complete resolved definition DAG and every connector edge."""

    if not isinstance(definition, AssemblyDefinition):
        raise TypeError("definition must be an AssemblyDefinition")
    identities: dict[str, tuple[str, str]] = {}
    visited: set[tuple[str, str]] = set()
    active: list[tuple[str, str]] = []
    validated_nodes: list[tuple[AssemblyDefinition, Any]] = []

    def visit(node: AssemblyDefinition, trace: tuple[str, ...]) -> None:
        if len(trace) > limits.max_nested_depth:
            raise ArtifactValidationError(
                "resource_limit",
                "/instances/" + "/instances/".join(trace),
                "assembly nesting exceeds the configured depth limit",
            )
        node_key = (node.definition_id, node.content_hash)
        if node_key in active:
            rendered = "/".join(trace) or node.definition_id
            raise ArtifactValidationError(
                "reference_cycle",
                "/instances/" + rendered,
                f"definition cycle along instance path {rendered}",
            )
        if node_key in visited:
            return
        if len(visited) >= limits.max_definitions:
            raise ArtifactValidationError(
                "resource_limit",
                "/definition_refs",
                "definition DAG exceeds the configured definition limit",
            )
        active.append(node_key)
        try:
            validate_artifact_blobs(node.to_dict(), node.blobs)
            feature_graph = load_feature_graph_artifact(
                node.blobs[node.feature_graph_ref.path]
            )
            if (
                feature_graph.owner_definition_kind != node.definition_kind
                or feature_graph.owner_definition_id != node.definition_id
                or feature_graph.owner_revision != node.revision
            ):
                raise ArtifactValidationError(
                    "graph_owner_invalid",
                    "/feature_graph_ref",
                    "feature graph owner differs from AssemblyDefinition identity",
                )
            refs = {item.definition_id: item for item in node.definition_refs}
            resolved = dict(node.resolved_definitions)
            if set(resolved) != set(refs):
                missing = sorted(set(refs) - set(resolved))
                extra = sorted(set(resolved) - set(refs))
                raise ArtifactValidationError(
                    "reference_missing",
                    "/definition_refs",
                    f"resolved definitions differ: missing={missing}, extra={extra}",
                )
            used = {item.definition_id for item in node.instances}
            unused = sorted(set(refs) - used)
            if unused:
                raise ArtifactValidationError(
                    "reference_unused",
                    "/definition_refs",
                    f"definition has no instance: {unused[0]}",
                )
            instance_by_id = {item.instance_id: item for item in node.instances}
            connector_sets: dict[str, set[str]] = {}
            for ref_index, ref in enumerate(node.definition_refs):
                child = resolved[ref.definition_id]
                if not isinstance(child, (PartDefinition, AssemblyDefinition)):
                    raise ArtifactValidationError(
                        "reference_invalid",
                        f"/definition_refs/{ref_index}",
                        "resolved value must be PartDefinition or AssemblyDefinition",
                    )
                _validate_ref_identity(
                    ref,
                    child,
                    path=f"/definition_refs/{ref_index}",
                )
                if "/" in ref.path:
                    raise ArtifactValidationError(
                        "path_invalid",
                        f"/definition_refs/{ref_index}/path",
                        "assembly definition references must be sibling archive names",
                    )
                if child.units != node.units:
                    raise ArtifactValidationError(
                        "units_incompatible",
                        f"/definition_refs/{ref_index}",
                        "referenced definition units differ",
                    )
                if child.tolerance_profile != node.tolerance_profile:
                    raise ArtifactValidationError(
                        "profile_incompatible",
                        f"/definition_refs/{ref_index}/tolerance_profile",
                        "referenced definition tolerance profile differs",
                    )
                prior = identities.get(child.definition_id)
                identity = (child.definition_kind, child.content_hash)
                if prior is not None and prior != identity:
                    raise ArtifactValidationError(
                        "reference_identity_conflict",
                        f"/definition_refs/{ref_index}",
                        f"definition_id {child.definition_id!r} resolves to multiple identities",
                    )
                identities[child.definition_id] = identity
                connector_sets[child.definition_id] = _connector_ids(child)
            graph_refs = tuple(
                (
                    str(item["definition_kind"]),
                    str(item["definition_id"]),
                    str(item["revision"]),
                    str(item["content_hash"]),
                )
                for item in feature_graph.external_definitions
            )
            definition_refs = tuple(
                (
                    item.definition_kind,
                    item.definition_id,
                    item.revision,
                    item.content_hash,
                )
                for item in node.definition_refs
            )
            if graph_refs != definition_refs:
                raise ArtifactValidationError(
                    "reference_identity_mismatch",
                    "/feature_graph_ref/external_definitions",
                    "feature graph external definitions differ from assembly refs",
                )

            for relation_index, relation in enumerate(node.relations):
                for side in ("connector_a", "connector_b"):
                    connector_ref = relation[side]
                    instance = instance_by_id[str(connector_ref["component_id"])]
                    connector_id = str(connector_ref["connector_id"])
                    if connector_id not in connector_sets[instance.definition_id]:
                        rendered = "/".join((*trace, instance.instance_id))
                        raise ArtifactValidationError(
                            "reference_missing",
                            f"/relations/{relation_index}/{side}/connector_id",
                            f"connector {connector_id!r} is missing along instance path {rendered}",
                        )

            for connector_index, connector in enumerate(node.public_connectors):
                component_id = str(connector.source_component_id)
                source_connector_id = str(connector.source_connector_id)
                instance = instance_by_id.get(component_id)
                if instance is None:
                    raise ArtifactValidationError(
                        "reference_missing",
                        f"/public_connectors/{connector_index}/source_component_id",
                        f"public connector references missing instance {component_id!r}",
                    )
                if source_connector_id not in connector_sets[instance.definition_id]:
                    rendered = "/".join((*trace, instance.instance_id))
                    raise ArtifactValidationError(
                        "reference_missing",
                        f"/public_connectors/{connector_index}/source_connector_id",
                        f"connector {source_connector_id!r} is missing along instance path {rendered}",
                    )

            for ref in node.definition_refs:
                child = resolved[ref.definition_id]
                if isinstance(child, AssemblyDefinition):
                    child_trace = (*trace, _instance_trace(node, ref.definition_id))
                    child_key = (child.definition_id, child.content_hash)
                    if child_key in active:
                        rendered = "/".join(child_trace)
                        raise ArtifactValidationError(
                            "reference_cycle",
                            "/instances/" + "/instances/".join(child_trace),
                            f"definition cycle along instance path {rendered}",
                        )
                    visit(child, child_trace)
            visited.add(node_key)
            validated_nodes.append((node, feature_graph))
        finally:
            active.pop()

    identities[definition.definition_id] = (
        definition.definition_kind,
        definition.content_hash,
    )
    visit(definition, ())
    for node, feature_graph in validated_nodes:
        mark_assembly_definition_validated(
            node,
            limits,
            feature_graph=feature_graph,
        )


def assembly_definition_graph_is_validated(
    definition: AssemblyDefinition,
    *,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> bool:
    visited: set[tuple[str, str]] = set()
    pending = [definition]
    while pending:
        node = pending.pop()
        key = (node.definition_id, node.content_hash)
        if key in visited:
            continue
        if not assembly_definition_is_validated(node, limits):
            return False
        visited.add(key)
        pending.extend(
            child
            for child in node.resolved_definitions.values()
            if isinstance(child, AssemblyDefinition)
        )
    return True


def load_assembly_definition(
    data: str | Path | bytes | bytearray | memoryview,
    *,
    base_dir: str | Path | None = None,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> AssemblyDefinition:
    """Load an assembly and resolve its sibling Part/Assembly definition DAG."""

    root_path: Path | None
    if isinstance(data, (str, Path)):
        root_path = Path(data).expanduser().resolve()
        raw = root_path.read_bytes()
        root_dir = root_path.parent
    else:
        root_path = None
        raw = bytes(data)
        root_dir = (
            Path(base_dir).expanduser().resolve() if base_dir is not None else None
        )
    root = decode_assembly_definition(raw)
    if root.definition_refs and root_dir is None:
        raise ArtifactValidationError(
            "reference_base_missing",
            "/definition_refs",
            "base_dir is required when loading referenced definitions from bytes",
        )

    loaded: dict[Path, PartDefinition | AssemblyDefinition] = {}
    active_paths: list[Path] = [root_path] if root_path is not None else []
    total_definitions = 1

    def resolve(node: AssemblyDefinition, trace: tuple[str, ...]) -> AssemblyDefinition:
        nonlocal total_definitions
        if len(trace) > limits.max_nested_depth:
            raise ArtifactValidationError(
                "resource_limit",
                "/instances/" + "/instances/".join(trace),
                "assembly nesting exceeds the configured depth limit",
            )
        resolved: dict[str, PartDefinition | AssemblyDefinition] = {}
        for ref_index, ref in enumerate(node.definition_refs):
            if "/" in ref.path:
                raise ArtifactValidationError(
                    "path_invalid",
                    f"/definition_refs/{ref_index}/path",
                    "assembly definition references must be sibling archive names",
                )
            assert root_dir is not None
            candidate = (root_dir / ref.path).resolve()
            try:
                candidate.relative_to(root_dir)
            except ValueError as exc:
                raise ArtifactValidationError(
                    "path_invalid",
                    f"/definition_refs/{ref_index}/path",
                    "reference resolves outside the assembly directory",
                ) from exc
            child_trace = (*trace, _instance_trace(node, ref.definition_id))
            if candidate in active_paths:
                rendered = "/".join(child_trace)
                raise ArtifactValidationError(
                    "reference_cycle",
                    "/instances/" + "/instances/".join(child_trace),
                    f"definition cycle along instance path {rendered}",
                )
            child = loaded.get(candidate)
            if child is None:
                try:
                    child_raw = candidate.read_bytes()
                except OSError as exc:
                    raise ArtifactValidationError(
                        "reference_missing",
                        f"/definition_refs/{ref_index}/path",
                        f"cannot read {candidate.name}: {exc}",
                    ) from exc
                if len(child_raw) != ref.byte_length:
                    raise ArtifactValidationError(
                        "reference_size_mismatch",
                        f"/definition_refs/{ref_index}/byte_length",
                        "referenced archive size differs",
                    )
                total_definitions += 1
                if total_definitions > limits.max_definitions:
                    raise ArtifactValidationError(
                        "resource_limit",
                        "/definition_refs",
                        "definition DAG exceeds the configured definition limit",
                    )
                if ref.definition_kind == "single_solid":
                    child = load_part_definition(child_raw)
                else:
                    active_paths.append(candidate)
                    try:
                        child = resolve(
                            decode_assembly_definition(child_raw),
                            child_trace,
                        )
                    finally:
                        active_paths.pop()
                loaded[candidate] = child
            _validate_ref_identity(
                ref,
                child,
                path=f"/definition_refs/{ref_index}",
            )
            resolved[ref.definition_id] = child
        return replace(node, resolved_definitions=resolved)

    result = resolve(root, ())
    validate_assembly_definition_graph(result, limits=limits)
    return result


def export_assembly_definition(
    value: AssemblyDefinition | Any,
    path: str | Path,
    *,
    include_dependencies: bool = True,
) -> Path:
    """Write a root assembly archive and its deduplicated sibling definitions."""

    definition = (
        value
        if isinstance(value, AssemblyDefinition)
        else getattr(value, "definition", None)
    )
    if not isinstance(definition, AssemblyDefinition):
        raise TypeError("value must be an AssemblyDefinition or AssemblyBuildResult")
    validate_assembly_definition_graph(definition)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    root_payload = encode_assembly_definition(definition)
    destination.write_bytes(root_payload)
    if not include_dependencies:
        return destination

    written: dict[Path, bytes] = {destination.resolve(): root_payload}
    visited: set[tuple[str, str]] = set()

    def write_dependencies(node: AssemblyDefinition) -> None:
        key = (node.definition_id, node.content_hash)
        if key in visited:
            return
        visited.add(key)
        for ref in node.definition_refs:
            child = node.resolved_definitions[ref.definition_id]
            payload = _archive_bytes(child)
            target = (destination.parent / ref.path).resolve()
            previous = written.get(target)
            if previous is not None and previous != payload:
                raise ArtifactValidationError(
                    "reference_path_conflict",
                    "/definition_refs",
                    f"multiple definitions target {ref.path}",
                )
            target.write_bytes(payload)
            written[target] = payload
            if isinstance(child, AssemblyDefinition):
                write_dependencies(child)

    write_dependencies(definition)
    return destination


def _runtime_connector(interface: ConnectorInterface) -> Connector:
    """Materialize a part connector without losing its authored anchor kind."""

    if interface.anchor_kind == "geometry":
        binding = dict(interface.binding or {})
        geometry_ref = GeometryRef(
            kind=str(binding["kind"]),
            source_node_id=binding.get("source_node_id"),
            geo_selector=dict(binding["geo_selector"]),
            flip=bool(binding.get("flip", False)),
        )
        return Connector(interface.connector_id, geometry_ref, name=interface.name)
    if interface.anchor_kind == "placement":
        return Connector(
            interface.connector_id,
            name=interface.name,
            anchor=ConnectorAnchor(
                "placement",
                placement=placement_from_canonical(interface.local_frame),
            ),
        )
    raise ArtifactValidationError(
        "connector_invalid",
        "/connectors",
        "part connector must use a geometry or placement anchor",
    )


def _material_from_definition(definition: PartDefinition) -> Material | None:
    ref = definition.material_ref
    if ref is None:
        return None
    payload = parse_canonical_json(definition.blobs[ref.path])
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "1.0":
        raise ArtifactValidationError(
            "material_invalid",
            "/material_ref/path",
            "material blob has an unsupported payload",
        )
    return Material(
        material_id=str(payload["material_id"]),
        name=payload.get("name"),
        density=payload.get("density"),
        density_unit=payload.get("density_unit"),
        color=(tuple(payload["color"]) if payload.get("color") is not None else None),
    )


def _constraint_from_record(record: Mapping[str, Any]) -> Constraint:
    def limit(value: Any) -> ScalarLimit | None:
        return ScalarLimit(**dict(value)) if value is not None else None

    return Constraint(
        constraint_id=str(record["constraint_id"]),
        constraint_kind=str(record["constraint_kind"]),
        connector_a=ConnectorRef(**dict(record["connector_a"])),
        connector_b=ConnectorRef(**dict(record["connector_b"])),
        drive_distance=record.get("drive_distance"),
        distance_limit=limit(record.get("distance_limit")),
        drive_angle_degrees=record.get("drive_angle_degrees"),
        angle_limit=limit(record.get("angle_limit")),
        pitch_radius_a=record.get("pitch_radius_a"),
        pitch_radius_b=record.get("pitch_radius_b"),
        pulley_radius_a=record.get("pulley_radius_a"),
        pulley_radius_b=record.get("pulley_radius_b"),
        pitch_radius=record.get("pitch_radius"),
        phase_offset=record.get("phase_offset"),
        name=record.get("name"),
    )


def _apply_verified_snapshot(
    authored: Assembly,
    snapshot: Mapping[str, Any] | None,
) -> Assembly | None:
    if snapshot is None or set(snapshot) not in (
        {"solver_profile", "component_placements", "constraint_report"},
        {
            "solver_profile",
            "component_placements",
            "occurrence_placements",
            "constraint_report",
        },
    ):
        return None
    if snapshot.get("solver_profile") != _SOLVER_PROFILE:
        return None
    raw_placements = snapshot.get("component_placements")
    if not isinstance(raw_placements, list):
        return None
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in raw_placements:
        if not isinstance(item, Mapping) or set(item) != {"instance_id", "placement"}:
            return None
        instance_id = str(item["instance_id"])
        if instance_id in by_id or not isinstance(item["placement"], Mapping):
            return None
        by_id[instance_id] = item["placement"]
    if set(by_id) != set(authored.component_ids()):
        return None
    try:
        raw_occurrences = snapshot.get("occurrence_placements")
        if raw_occurrences is not None:
            if not isinstance(raw_occurrences, list):
                return None
            candidate = _restore_component_occurrence_placements(
                authored,
                raw_occurrences,
            )
        else:
            candidate = authored
            for component_id in authored.component_ids():
                candidate = candidate.with_component_placement(
                    component_id,
                    placement_from_canonical(by_id[component_id]),
                )
        if any(
            placement_ticks(candidate.get_component(component_id).placement)
            != placement_ticks(by_id[component_id])
            for component_id in authored.component_ids()
        ):
            return None
        report = inspect_assembly_constraints(candidate)
    except (KeyError, TypeError, ValueError):
        return None
    if not report.solved or not constraint_reports_match(
        report.to_dict(), snapshot.get("constraint_report")
    ):
        return None
    return candidate


# Runtime keys a built or materialized value carries. The hash/kind/revision
# keys let another session reference the value as an external definition; the
# object key lets an assembly (or a notebook projection) reach the child
# definition itself without a separate registry.
_DEFINITION_OBJECT_KEY = "definition.object"


def attach_definition(
    value: Part | Assembly, definition: PartDefinition | AssemblyDefinition
) -> None:
    """Mark *value* as the runtime form of *definition*."""

    value._set_runtime("definition.content_hash", definition.content_hash)
    value._set_runtime("definition.kind", definition.definition_kind)
    value._set_runtime("definition.revision", definition.revision)
    value._set_runtime(_DEFINITION_OBJECT_KEY, definition)


def attached_definition(value: Any) -> PartDefinition | AssemblyDefinition | None:
    """Return the definition a Part/Assembly was built or materialized from."""

    if not isinstance(value, (Part, Assembly)):
        return None
    definition = value._get_runtime(_DEFINITION_OBJECT_KEY)
    if isinstance(definition, (PartDefinition, AssemblyDefinition)):
        return definition
    return None


def materialize_definition(
    definition: PartDefinition | AssemblyDefinition,
) -> Part | Assembly:
    """Materialize a validated product definition without replaying Python source."""
    if isinstance(
        definition, AssemblyDefinition
    ) and not assembly_definition_graph_is_validated(definition):
        validate_assembly_definition_graph(definition)

    cache: dict[tuple[str, str], Part | Assembly] = {}

    def materialize(node: PartDefinition | AssemblyDefinition) -> Part | Assembly:
        key = (node.definition_kind, node.content_hash)
        existing = cache.get(key)
        if existing is not None:
            return existing
        if isinstance(node, PartDefinition):
            body = take_validated_part_body(node)
            if body is None:
                validate_artifact_blobs(node.to_dict(), node.blobs)
                body = read_brep_solid(node.blobs[node.solid_cache_ref.path])
                restore_topology_snapshot(
                    body,
                    node.blobs[node.topology_snapshot_ref.path],
                )
                validate_connector_entity_bindings(body, node.connectors)
                mark_part_definition_validated(node)
            value: Part | Assembly = Part(
                part_id=node.definition_id,
                name=node.metadata.get("name"),
                body=body,
                material=_material_from_definition(node),
                connectors=tuple(_runtime_connector(item) for item in node.connectors),
            )
            attach_definition(value, node)
            cache[key] = value
            return value

        # The complete assembly DAG was validated once at the public boundary.
        direct = {
            definition_id: materialize(child)
            for definition_id, child in node.resolved_definitions.items()
        }
        authored = Assembly(
            assembly_id=node.definition_id,
            name=node.metadata.get("name"),
            components=tuple(
                Component(
                    component_id=item.instance_id,
                    item=direct[item.definition_id],
                    placement=placement_from_canonical(item.placement),
                    name=item.name,
                )
                for item in node.instances
            ),
            public_connectors=tuple(
                PublicConnectorRef(
                    public_connector_id=interface.connector_id,
                    component_id=str(interface.source_component_id),
                    connector_id=str(interface.source_connector_id),
                    name=interface.name,
                )
                for interface in node.public_connectors
            ),
            constraints=tuple(_constraint_from_record(item) for item in node.relations),
            grounded_component_ids=node.grounded_instance_ids,
        )
        restored = _apply_verified_snapshot(authored, node.solved_snapshot)
        if restored is None:
            restored = (
                solve_assembly_constraints(authored, strict=True)
                if authored.constraints
                else authored
            )
        attach_definition(restored, node)
        cache[key] = restored
        return restored

    return materialize(definition)


__all__ = [
    "attach_definition",
    "attached_definition",
    "decode_assembly_definition",
    "definition_archive_name",
    "encode_assembly_definition",
    "export_assembly_definition",
    "load_assembly_definition",
    "materialize_definition",
    "validate_assembly_definition_graph",
]
