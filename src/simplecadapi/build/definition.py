"""Turn a finished recording session into a durable product definition.

Three paths produce definitions — ``@part``, ``@assemble`` and the notebook
projection — and all of them end here, so the definitions they write have
exactly the same shape:

* :func:`finish_part_definition` — one Part whose lineage lives in *session*
  becomes a ``PartDefinition`` plus its feature graph;
* :func:`finish_assembly_definition` — one authored Assembly is solved,
  recorded as an ``evaluate_assembly_definition`` node, and becomes an
  ``AssemblyDefinition`` over its declared child definitions.

Both expect *session* to be inactive: they activate it themselves when they
need to record, and they never read the caller's active session.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from ..artifacts.assembly_definition import AssemblyDefinition
from ..artifacts.assembly_io import (
    _archive_bytes,
    definition_archive_name,
    validate_assembly_definition_graph,
)
from ..artifacts.brep import write_brep_bytes
from ..artifacts.canonical import (
    ArtifactValidationError,
    canonical_bytes,
    content_hash,
    sha256_bytes,
)
from ..artifacts.feature_graph import (
    FEATURE_GRAPH_MEDIA_TYPE,
    FeatureGraphArtifact,
    capture_feature_graph,
    encode_feature_graph_artifact,
)
from ..artifacts.geometry_interface import geometry_interface_fingerprint
from ..artifacts.part_definition import PartDefinition, mark_part_definition_validated
from ..artifacts.references import (
    BlobRef,
    ConnectorInterface,
    FileInputSnapshot,
    InterfaceHashes,
    MaterialRef,
    PartInstance,
    PartRef,
)
from ..artifacts.topology_snapshot import (
    encode_topology_snapshot,
    resolve_geometry_entity_ref,
    validate_connector_entity_bindings,
)
from ..artifacts.validation import validate_artifact_blobs
from ..core import Solid
from ..product.assembly import (
    _AUTHORED_PLACEMENTS_RUNTIME_KEY,
    Assembly,
    PublicConnectorRef,
    _component_occurrence_placements,
)
from ..product.connector import (
    Connector,
    ConnectorRef,
    resolve_connector_placement,
    resolve_connector_ref_placement,
)
from ..product.material import Material
from ..product.part import Part
from ..product.placement import canonical_frame, placement_ticks
from ..product.solver import inspect_assembly_constraints, solve_assembly_constraints
from ..recording.graph import (
    GraphSession,
    attach_graph_node,
    attach_semantic_graph_node,
    record_operation_if_active,
    suspend_graph_recording,
)
from ..topology import SemanticDelta, SemanticRef
from .keys import generator_profile
from .results import AssemblyBuildResult, PartBuildResult

Definition = PartDefinition | AssemblyDefinition

_SOLVER_PROFILE = "simplecad-assembly-solver-1"


def _definition_id(item: Part | Assembly) -> str:
    return item.part_id if isinstance(item, Part) else item.assembly_id


def _feature_graph_path(feature_graph: FeatureGraphArtifact) -> str:
    digest = feature_graph.content_hash.removeprefix("sha256:")
    return f"features/{digest}.feature-graph.zip"


def _blob_ref(path: str, payload: bytes, media_type: str) -> BlobRef:
    return BlobRef(
        path=path,
        sha256=sha256_bytes(payload),
        byte_length=len(payload),
        media_type=media_type,
    )


def _require_single_result(session: GraphSession, code: str, decorator: str) -> None:
    if len(session.result_node_ids) != 1:
        raise ArtifactValidationError(
            code,
            "/result_node_ids",
            f"{decorator} must capture exactly one result node",
        )


# ---------------------------------------------------------------------------
# Part definitions
# ---------------------------------------------------------------------------


def _material_ref(
    material: Material | None,
) -> tuple[MaterialRef | None, dict[str, bytes]]:
    if material is None:
        return None, {}
    payload = canonical_bytes({"schema_version": "1.0", **material.to_dict()})
    digest = sha256_bytes(payload)
    path = f"material/{digest.removeprefix('sha256:')}.json"
    return (
        MaterialRef(
            material_id=material.material_id,
            path=path,
            revision=digest.removeprefix("sha256:")[:32],
            sha256=digest,
            byte_length=len(payload),
        ),
        {path: payload},
    )


def _connector_interface(connector: Connector, body: Solid) -> ConnectorInterface:
    anchor = cast(Any, connector.anchor)
    frame = resolve_connector_placement(connector).to_dict()
    binding: Mapping[str, Any] | None = None
    if anchor.anchor_kind == "geometry":
        geometry_ref = anchor.geometry_ref
        binding = {
            **geometry_ref.to_dict(),
            "resolved_entities": [resolve_geometry_entity_ref(body, geometry_ref)],
        }
    return ConnectorInterface(
        connector_id=connector.connector_id,
        name=connector.name,
        anchor_kind=anchor.anchor_kind,
        local_frame=frame,
        binding=binding,
    )


def _part_definition(
    *,
    part: Part,
    feature_graph: FeatureGraphArtifact,
    revision: str,
    tolerance_profile: str,
    file_inputs: tuple[Any, ...],
    generator: Mapping[str, str],
) -> PartDefinition:
    """Assemble and validate the ``PartDefinition`` of one built Part."""

    feature_payload = encode_feature_graph_artifact(feature_graph)
    body_payload = write_brep_bytes(part.body)
    topology_payload = encode_topology_snapshot(part.body)
    feature_path = _feature_graph_path(feature_graph)
    body_path = f"body/{sha256_bytes(body_payload).removeprefix('sha256:')}.brep"
    topology_path = (
        f"topology/{sha256_bytes(topology_payload).removeprefix('sha256:')}.json"
    )
    material_ref, material_blobs = _material_ref(part.material)
    connectors = tuple(
        sorted(
            (_connector_interface(item, part.body) for item in part.connectors),
            key=lambda item: item.connector_id.encode("utf-8"),
        )
    )
    interface_hashes = InterfaceHashes(
        geometry=geometry_interface_fingerprint(
            part.body,
            tolerance_profile=tolerance_profile,
        ),
        connectors={item.connector_id: item.interface_hash for item in connectors},
        bindings={item.connector_id: item.binding_hash for item in connectors},
        material=material_ref.sha256 if material_ref is not None else None,
    )
    blobs = {
        feature_path: feature_payload,
        body_path: body_payload,
        topology_path: topology_payload,
        **material_blobs,
    }
    definition = PartDefinition(
        definition_id=part.part_id,
        revision=revision,
        tolerance_profile=tolerance_profile,
        generator=generator,
        feature_graph_ref=_blob_ref(
            feature_path,
            feature_payload,
            FEATURE_GRAPH_MEDIA_TYPE,
        ),
        solid_cache_ref=_blob_ref(
            body_path, body_payload, "application/vnd.opencascade.brep"
        ),
        topology_snapshot_ref=_blob_ref(
            topology_path, topology_payload, "application/json"
        ),
        connectors=connectors,
        material_ref=material_ref,
        file_inputs=tuple(file_inputs),
        interface_hashes=interface_hashes,
        metadata={"name": part.name},
        blobs=blobs,
    )
    validate_artifact_blobs(definition.to_dict(), definition.blobs)
    validate_connector_entity_bindings(part.body, definition.connectors)
    mark_part_definition_validated(
        definition,
        body=part.body,
        feature_graph=feature_graph,
    )
    return definition


def _attach_feature_graph_result(
    part: Part,
    feature_graph: FeatureGraphArtifact,
) -> Part:
    """Point the Part's lineage at the frozen feature graph.

    The recording session is discarded after the build; the returned Part
    instead references the result node of the feature graph's own restored
    session, which is what later replays and exports validate against.
    """

    session = feature_graph.restore_session()
    result_node_id = feature_graph.result_node_ids[0]
    node = session.graph.get_node(result_node_id)
    if node is None:
        raise ArtifactValidationError(
            "result_invalid", "/result_node_ids/0", "result node does not exist"
        )
    attach_graph_node(part.body, node, graph_id=session.graph.graph_id)
    attach_semantic_graph_node(part, node, graph_id=session.graph.graph_id)
    session._captured_values.append(part)
    session.validate_graph_ownership(part)
    return part


def finish_part_definition(
    session: GraphSession,
    part: Part,
    *,
    revision: str,
    tolerance_profile: str,
    file_inputs: tuple[FileInputSnapshot, ...],
    project_root: Path,
) -> PartBuildResult:
    """Capture *part* as the only result of *session* and freeze it."""

    session.capture_result(value=part)
    _require_single_result(session, "solid_cardinality_invalid", "@part")
    feature_graph = capture_feature_graph(
        session=session,
        owner_definition_kind="single_solid",
        owner_definition_id=part.part_id,
        owner_revision=revision,
        project_root=project_root,
    )
    definition = _part_definition(
        part=part,
        feature_graph=feature_graph,
        revision=revision,
        tolerance_profile=tolerance_profile,
        file_inputs=file_inputs,
        generator=generator_profile(),
    )
    return PartBuildResult(
        value=_attach_feature_graph_result(part, feature_graph),
        definition=definition,
        feature_graph=feature_graph,
    )


# ---------------------------------------------------------------------------
# Assembly definitions
# ---------------------------------------------------------------------------


def check_declared_profiles(
    declared: Sequence[Definition], tolerance_profile: str
) -> None:
    """Reject child definitions built under a different tolerance profile."""

    for index, definition in enumerate(declared):
        if definition.tolerance_profile != tolerance_profile:
            raise ArtifactValidationError(
                "profile_incompatible",
                f"/definitions/{index}/tolerance_profile",
                "referenced definition tolerance profile differs",
            )


def _part_ref(definition: Definition) -> PartRef:
    payload = _archive_bytes(definition)
    return PartRef(
        definition_id=definition.definition_id,
        definition_kind=definition.definition_kind,
        path=definition_archive_name(definition),
        revision=definition.revision,
        content_hash=definition.content_hash,
        byte_length=len(payload),
    )


def _public_connector_interface(
    assembly: Assembly,
    public: PublicConnectorRef,
) -> ConnectorInterface:
    return ConnectorInterface(
        connector_id=public.public_connector_id,
        name=public.name,
        anchor_kind="public",
        local_frame=resolve_connector_ref_placement(
            assembly,
            ConnectorRef(public.component_id, public.connector_id),
        ).to_dict(),
        binding=None,
        source_component_id=public.component_id,
        source_connector_id=public.connector_id,
    )


def _solved_snapshot(assembly: Assembly) -> Mapping[str, Any]:
    report = inspect_assembly_constraints(assembly)
    if assembly.constraints and not report.solved:
        raise ArtifactValidationError(
            "assembly_unsolved",
            "/relations",
            "@assemble must return an assembly whose constraints pass residual verification",
        )
    return {
        "solver_profile": _SOLVER_PROFILE,
        "component_placements": [
            {
                "instance_id": component.component_id,
                "placement": placement_ticks(component.placement),
            }
            for component in sorted(
                assembly.components,
                key=lambda item: item.component_id.encode("utf-8"),
            )
        ],
        "occurrence_placements": list(_component_occurrence_placements(assembly)),
        "constraint_report": report.to_dict(),
    }


def _authored_component_placements(
    assembly: Assembly,
) -> Mapping[str, Mapping[str, Any]]:
    """Placements as authored, before the solver moved any component."""

    current = {
        component.component_id: placement_ticks(component.placement)
        for component in assembly.components
    }
    authored = assembly._get_runtime(_AUTHORED_PLACEMENTS_RUNTIME_KEY)
    if authored is None:
        return current
    if not isinstance(authored, Mapping) or set(authored) != set(current):
        raise ArtifactValidationError(
            "assembly_provenance_invalid",
            "/instances",
            "authored component placements do not match assembly instances",
        )
    normalized: dict[str, Mapping[str, Any]] = {}
    for component_id, placement in authored.items():
        if not isinstance(placement, Mapping):
            raise ArtifactValidationError(
                "assembly_provenance_invalid",
                f"/instances/{component_id}/placement",
                "authored component placement must be a frame object",
            )
        try:
            normalized[str(component_id)] = canonical_frame(placement)
        except (TypeError, ValueError) as exc:
            raise ArtifactValidationError(
                "assembly_provenance_invalid",
                f"/instances/{component_id}/placement",
                str(exc),
            ) from exc
    return normalized


def _assembly_geometry_hash(
    assembly: Assembly,
    definitions: Mapping[str, Definition],
    authored_placements: Mapping[str, Mapping[str, Any]],
) -> str:
    records = []
    for component in sorted(
        assembly.components,
        key=lambda item: item.component_id.encode("utf-8"),
    ):
        definition_id = _definition_id(component.item)
        records.append(
            {
                "instance_id": component.component_id,
                "definition_id": definition_id,
                "geometry_hash": definitions[definition_id].interface_hashes.geometry,
                "placement": dict(authored_placements[component.component_id]),
            }
        )
    return content_hash({"instances": records})


def _assembly_definition(
    *,
    assembly: Assembly,
    feature_graph: FeatureGraphArtifact,
    declared: tuple[Definition, ...],
    revision: str,
    tolerance_profile: str,
    generator: Mapping[str, str],
) -> AssemblyDefinition:
    """Assemble and validate the ``AssemblyDefinition`` of one solved Assembly."""

    definitions = {item.definition_id: item for item in declared}
    authored_placements = _authored_component_placements(assembly)
    used_ids: set[str] = set()
    instances: list[PartInstance] = []
    for component in sorted(
        assembly.components,
        key=lambda item: item.component_id.encode("utf-8"),
    ):
        definition_id = _definition_id(component.item)
        definition = definitions.get(definition_id)
        if definition is None:
            raise ArtifactValidationError(
                "reference_missing",
                f"/instances/{component.component_id}",
                f"component definition {definition_id!r} was not declared",
            )
        expected_kind = (
            "single_solid" if isinstance(component.item, Part) else "assembly"
        )
        if definition.definition_kind != expected_kind:
            raise ArtifactValidationError(
                "definition_kind_invalid",
                f"/instances/{component.component_id}",
                f"runtime component kind differs from definition {definition_id!r}",
            )
        used_ids.add(definition_id)
        instances.append(
            PartInstance(
                instance_id=component.component_id,
                definition_id=definition_id,
                name=component.name,
                placement=authored_placements[component.component_id],
            )
        )
    unused = sorted(set(definitions) - used_ids)
    if unused:
        raise ArtifactValidationError(
            "reference_unused",
            "/definition_refs",
            f"declared definition has no component instance: {unused[0]}",
        )
    connectors = tuple(
        sorted(
            (
                _public_connector_interface(assembly, public)
                for public in assembly.public_connectors
            ),
            key=lambda item: item.connector_id.encode("utf-8"),
        )
    )
    feature_payload = encode_feature_graph_artifact(feature_graph)
    feature_path = _feature_graph_path(feature_graph)
    definition = AssemblyDefinition(
        definition_id=assembly.assembly_id,
        revision=revision,
        tolerance_profile=tolerance_profile,
        generator=generator,
        definition_refs=tuple(_part_ref(item) for item in declared),
        instances=tuple(instances),
        relations=tuple(
            constraint.to_dict()
            for constraint in sorted(
                assembly.constraints,
                key=lambda item: item.constraint_id.encode("utf-8"),
            )
        ),
        grounded_instance_ids=tuple(
            sorted(
                assembly.grounded_component_ids,
                key=lambda item: item.encode("utf-8"),
            )
        ),
        public_connectors=connectors,
        interface_hashes=InterfaceHashes(
            geometry=_assembly_geometry_hash(
                assembly,
                definitions,
                authored_placements,
            ),
            connectors={item.connector_id: item.interface_hash for item in connectors},
            bindings={item.connector_id: item.binding_hash for item in connectors},
            material=None,
        ),
        solved_snapshot=_solved_snapshot(assembly),
        feature_graph_ref=_blob_ref(
            feature_path,
            feature_payload,
            FEATURE_GRAPH_MEDIA_TYPE,
        ),
        metadata={"name": assembly.name},
        blobs={feature_path: feature_payload},
        resolved_definitions=definitions,
    )
    validate_artifact_blobs(definition.to_dict(), definition.blobs)
    validate_assembly_definition_graph(definition)
    return definition


def finish_assembly_definition(
    session: GraphSession,
    raw: Assembly,
    *,
    declared: Sequence[Definition],
    revision: str,
    tolerance_profile: str,
    project_root: Path,
) -> AssemblyBuildResult:
    """Solve the authored *raw* assembly, record the solve, and freeze it.

    *declared* lists every child definition the components refer to (sorted
    by id, one entry per id). The solve is strict: an assembly whose
    constraints do not close fails here rather than producing a definition.
    """

    declared = tuple(declared)
    with suspend_graph_recording():
        solved = solve_assembly_constraints(raw, strict=True)
    snapshot = _solved_snapshot(solved)
    with session:
        record_operation_if_active(
            "evaluate_assembly_definition",
            dict(snapshot),
            outputs=solved,
            input_shapes=[raw],
            semantic_delta=SemanticDelta(
                modified=(
                    SemanticRef(
                        graph_id="pending",
                        node_id="pending",
                        entity_type="Assembly",
                        entity_id=raw.assembly_id,
                    ),
                ),
                metadata={"solver_profile": _SOLVER_PROFILE},
            ),
            source={},
        )
        session.capture_result(value=solved)
    _require_single_result(session, "assembly_cardinality_invalid", "@assemble")
    feature_graph = capture_feature_graph(
        session=session,
        owner_definition_kind="assembly",
        owner_definition_id=raw.assembly_id,
        owner_revision=revision,
        project_root=project_root,
        external_definitions=tuple(
            {
                "definition_kind": definition.definition_kind,
                "definition_id": definition.definition_id,
                "revision": definition.revision,
                "content_hash": definition.content_hash,
            }
            for definition in declared
        ),
    )
    definition = _assembly_definition(
        assembly=solved,
        feature_graph=feature_graph,
        declared=declared,
        revision=revision,
        tolerance_profile=tolerance_profile,
        generator=generator_profile(),
    )
    return AssemblyBuildResult(
        value=solved,
        definition=definition,
        feature_graph=feature_graph,
    )


__all__ = [
    "Definition",
    "check_declared_profiles",
    "finish_assembly_definition",
    "finish_part_definition",
]
