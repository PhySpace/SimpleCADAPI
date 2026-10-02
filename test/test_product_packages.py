from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.product.packages import ProductPackage, ProductPackageError
from simplecadapi.product.occurrence import ProductOccurrenceError, ProductOccurrenceGraph
from simplecadapi.artifacts.canonical import canonical_bytes, content_hash, sha256_bytes
import simplecadapi.artifacts.assembly_io as assembly_io
import simplecadapi.artifacts.part_io as part_io
import simplecadapi.product.packages as product_packages
from simplecadapi.scene import (
    canonical_zip_bytes,
    parse_canonical_json,
    preflight_zip_bytes,
)


def _build_named_part(part_id: str = "box") -> scad.PartBuildResult:
    @scad.part(id=part_id)
    def build() -> scad.Part:
        body = scad.make_box_rsolid(width=1.0, height=2.0, depth=3.0)
        named_face = body.get_faces(0)
        named_face = scad.apply_tag(named_face, "interface.mount_face")
        part = scad.make_part_rpart(
            part_id=part_id,
            body=body,
            name=f"Part {part_id}",
        )
        return scad.add_connector_rpart(
            part=part,
            connector=scad.make_face_connector_rconnector(
                connector_id="mount",
                face=named_face,
            ),
        )

    return build()


def _build_nested_assembly():
    part = _build_named_part("linked")

    @scad.assemble(id="child", definitions=(part,))
    def build_child() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(
            assembly_id="child", name="Child assembly"
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=part.value,
            component_id="inner_a",
            placement=scad.identity_placement_rplacement(),
            name="Inner linked part A",
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=part.value,
            component_id="inner_b",
            placement=scad.identity_placement_rplacement(),
            name="Inner linked part B",
        )
        assembly = scad.ground_component_rassembly(assembly, "inner_a")
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id="joint",
            connector_a=scad.make_connector_ref_rconnectorref("inner_a", "mount"),
            connector_b=scad.make_connector_ref_rconnectorref("inner_b", "mount"),
            drive_angle_degrees=15.0,
        )
        assembly = scad.solve_assembly_constraints_rassembly(assembly=assembly)
        return scad.set_public_connector_rassembly(assembly=assembly,
        public_connector_id="public_mount",
        source_component_id="inner_b",
        source_connector_id="mount",)

    child = build_child()

    @scad.assemble(id="root", definitions=(child, part))
    def build_root() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(
            assembly_id="root", name="Root assembly"
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=child.value,
            component_id="nested",
            placement=scad.make_placement_rplacement(origin=(10.0, 0.0, 0.0)),
            name="Nested child assembly",
        )
        return scad.add_component_rassembly(
            assembly=assembly,
            item=part.value,
            component_id="direct",
            placement=scad.make_placement_rplacement(origin=(0.0, 5.0, 0.0)),
            name="Direct linked part",
        )

    return part, child, build_root()


def test_part_package_wraps_canonical_prt_and_preserves_naming_binding() -> None:
    part = _build_named_part()
    package = scad.build_product_package(part)
    payload = scad.encode_product_package(package)

    loaded_package = scad.read_product_package(payload)
    loaded_definition = scad.load_product_package(payload)
    rebuilt = scad.materialize_definition(loaded_definition)

    assert loaded_package.root_kind == "single_solid"
    assert loaded_package.root_id == "box"
    assert isinstance(loaded_definition, scad.PartDefinition)
    assert rebuilt.part_id == "box"
    definition_paths = [
        path for path in loaded_package.objects if path.startswith("definitions/")
    ]
    assert len(definition_paths) == 1
    assert definition_paths[0].endswith(".json")
    assert loaded_package.scene_path == "projections/scene/scene.json"
    assert loaded_package.scene_path in loaded_package.objects

    topology = parse_canonical_json(
        loaded_definition.blobs[loaded_definition.topology_snapshot_ref.path]
    )
    assert list(topology["name_index"]) == ["interface.mount_face"]
    named_ref = topology["name_index"]["interface.mount_face"][0]
    connector_ref = loaded_definition.connectors[0].binding["resolved_entities"][0]
    assert named_ref == connector_ref
    assert rebuilt.connectors[0].anchor_kind == "geometry"


def test_part_package_is_byte_deterministic() -> None:
    @scad.part(id="deterministic_part")
    def build() -> scad.Part:
        body = scad.make_box_rsolid(width=1.0, height=2.0, depth=3.0)
        tagged_face = scad.apply_tag(
            shape=body.get_faces(0),
            tag="interface.mount_face",
        )
        part = scad.make_part_rpart(part_id="deterministic_part", body=body)
        return scad.add_connector_rpart(
            part=part,
            connector=scad.make_face_connector_rconnector(
                connector_id="mount",
                face=tagged_face,
            ),
        )

    first = build()
    second = build()

    assert first.definition.canonical_bytes == second.definition.canonical_bytes
    assert scad.encode_product_package(
        scad.build_product_package(first)
    ) == scad.encode_product_package(scad.build_product_package(second))


def test_nested_assembly_package_preserves_hierarchy_relations_and_dedup() -> None:
    part, child, root = _build_nested_assembly()
    package = scad.build_product_package(root)
    payload = scad.encode_product_package(package)
    loaded = scad.load_product_package(payload)
    rebuilt = scad.materialize_definition(loaded)

    assert isinstance(loaded, scad.AssemblyDefinition)
    assert isinstance(rebuilt, scad.Assembly)
    assert rebuilt.component_ids() == ("direct", "nested")
    nested = rebuilt.get_component("nested").item
    assert isinstance(nested, scad.Assembly)
    assert nested.component_ids() == ("inner_a", "inner_b")
    assert nested.get_component("inner_a").item is nested.get_component("inner_b").item
    assert nested.get_component("inner_a").item is rebuilt.get_component("direct").item
    assert nested.public_connector_ids() == ("public_mount",)
    assert rebuilt.name == "Root assembly"
    assert rebuilt.get_component("direct").name == "Direct linked part"
    assert rebuilt.get_component("direct").item.name == "Part linked"
    assert rebuilt.get_component("nested").name == "Nested child assembly"
    assert nested.name == "Child assembly"
    assert nested.get_component("inner_a").name == "Inner linked part A"
    assert nested.get_component("inner_b").name == "Inner linked part B"
    assert nested.constraints[0].constraint_kind == "revolute"
    assert nested.constraints[0].drive_angle_degrees == 15.0

    records = package.manifest["definitions"]
    assert len(records) == 3
    assert [item["definition_id"] for item in records].count(
        part.definition.definition_id
    ) == 1
    assert [item["definition_id"] for item in records].count(
        child.definition.definition_id
    ) == 1
    assert sum(path.startswith("definitions/part/") for path in package.objects) == 1


def test_rebuilt_named_part_package_is_byte_deterministic() -> None:
    first = _build_named_part("rebuilt_part")
    second = _build_named_part("rebuilt_part")

    assert scad.encode_product_package(
        scad.build_product_package(first)
    ) == scad.encode_product_package(scad.build_product_package(second))


def test_product_package_rejects_mutation_missing_and_extra_objects() -> None:
    _part, _child, root = _build_nested_assembly()
    package = scad.build_product_package(root)
    target_path = next(
        path for path in package.objects if path.startswith("definitions/")
    )

    mutated = dict(package.objects)
    mutated[target_path] += b"x"
    with pytest.raises(ProductPackageError, match="identity differs"):
        scad.validate_product_package(
            ProductPackage(package.manifest, mutated, package.root_definition)
        )

    missing = dict(package.objects)
    del missing[target_path]
    with pytest.raises(ProductPackageError, match="member set"):
        scad.validate_product_package(
            ProductPackage(package.manifest, missing, package.root_definition)
        )

    extra = dict(package.objects)
    extra["extra/member"] = b"unused"
    with pytest.raises(ProductPackageError, match="member set"):
        scad.validate_product_package(
            ProductPackage(package.manifest, extra, package.root_definition)
        )


def test_product_package_encode_round_trip_is_byte_identical() -> None:
    package = scad.build_product_package(_build_named_part())
    first = scad.encode_product_package(package)
    loaded = scad.read_product_package(first)
    second = scad.encode_product_package(loaded)

    assert first == second


def test_validated_package_skips_repeated_decode_validation(monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = scad.build_product_package(_build_named_part())
    payload = scad.encode_product_package(package)
    loaded = scad.read_product_package(payload)
    assert loaded._validated_manifest is not None
    assert loaded._validated_limits is not None
    assert scad.encode_product_package(loaded) == payload


def test_unvalidated_package_is_checked_before_encoding() -> None:
    package = scad.build_product_package(_build_named_part())
    target_path = next(iter(package.objects))
    mutated = dict(package.objects)
    mutated[target_path] += b"x"

    with pytest.raises(ProductPackageError, match="identity differs|member set"):
        scad.encode_product_package(
            ProductPackage(package.manifest, mutated, package.root_definition)
        )


def test_materialize_reuses_validated_dag_and_checks_unvalidated_once(monkeypatch: pytest.MonkeyPatch,
) -> None:
    _part, _child, root = _build_nested_assembly()
    validation_calls = 0
    original = assembly_io.validate_assembly_definition_graph

    def count_validation(*args, **kwargs):
        nonlocal validation_calls
        validation_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        assembly_io,
        "validate_assembly_definition_graph",
        count_validation,
    )

    validated = scad.materialize_definition(root.definition)
    assert isinstance(validated, scad.Assembly)
    assert validation_calls == 0

    unvalidated_definition = replace(root.definition)
    unvalidated = scad.materialize_definition(unvalidated_definition)
    assert isinstance(unvalidated, scad.Assembly)
    assert validation_calls == 1


def test_validated_package_manifest_mutation_forces_revalidation() -> None:
    package = scad.build_product_package(_build_named_part())
    draft = dict(package.manifest)
    draft["root"] = {**draft["root"], "revision": "changed"}
    mutated = ProductPackage(draft, package.objects, package.root_definition)

    with pytest.raises(ProductPackageError, match="content_hash|root definition"):
        scad.encode_product_package(mutated)


def test_build_package_validates_definition_and_occurrence_closure() -> None:
    _part, _child, root = _build_nested_assembly()
    package = scad.build_product_package(root)

    assert package.root_id == "root"
    assert package.occurrence_graph.root_definition_id == "root"
    assert package.occurrence_graph.root_node_id == "node/root"
    assert {
        item["definition_id"] for item in package.manifest["definitions"]
    } == {"linked", "child", "root"}



def _minimal_occurrence_manifest(
    nodes: list[dict[str, object]],
    connectors: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "artifact_kind": "product_occurrence_graph",
        "root_definition_id": "root",
        "root_node_id": "node-0",
        "definitions": [
            {
                "definition_id": "root",
                "definition_kind": "single_solid",
                "revision": "r1",
                "content_hash": "sha256:" + "0" * 64,
            }
        ],
        "nodes": nodes,
        "connectors": connectors or [],
        "joints": [],
        "ground_edges": [],
    }
    manifest["content_hash"] = content_hash(manifest, omit=())
    return manifest


def _minimal_occurrence_node(
    node_id: str,
    parent_node_id: str | None,
) -> dict[str, object]:
    return {
        "node_id": node_id,
        "parent_node_id": parent_node_id,
        "definition_id": "root",
        "definition_kind": "single_solid",
        "properties": {
            "content_hash": "sha256:" + "0" * 64,
            "revision": "r1",
        },
    }


def test_occurrence_validation_handles_deep_hierarchy_iteratively() -> None:
    nodes = [
        _minimal_occurrence_node(
            f"node-{index}", None if index == 0 else f"node-{index - 1}"
        )
        for index in range(1024)
    ]

    graph = ProductOccurrenceGraph(_minimal_occurrence_manifest(nodes))

    assert len(graph.nodes) == 1024


def test_occurrence_validation_rejects_node_hierarchy_cycle() -> None:
    nodes = [
        _minimal_occurrence_node("node-0", None),
        _minimal_occurrence_node("node-1", "node-2"),
        _minimal_occurrence_node("node-2", "node-1"),
    ]

    with pytest.raises(
        ProductOccurrenceError, match="occurrence node hierarchy contains a cycle"
    ):
        ProductOccurrenceGraph(_minimal_occurrence_manifest(nodes))


def test_occurrence_validation_rejects_connector_forwarding_cycle() -> None:
    nodes = [_minimal_occurrence_node("node-0", None)]
    connectors: list[dict[str, object]] = [
        {
            "connector_snapshot_id": "connector-a",
            "node_id": "node-0",
            "definition_id": "root",
            "definition_kind": "single_solid",
            "source_connector_snapshot_id": "connector-b",
        },
        {
            "connector_snapshot_id": "connector-b",
            "node_id": "node-0",
            "definition_id": "root",
            "definition_kind": "single_solid",
            "source_connector_snapshot_id": "connector-a",
        },
    ]

    with pytest.raises(
        ProductOccurrenceError, match="connector forwarding graph contains a cycle"
    ):
        ProductOccurrenceGraph(_minimal_occurrence_manifest(nodes, connectors))


def test_product_package_rejects_resigned_occurrence_transform() -> None:
    package = scad.build_product_package(_build_named_part())
    occurrence_path = package.occurrence_graph_path
    occurrence = parse_canonical_json(package.objects[occurrence_path])
    occurrence["nodes"][0]["transform"]["origin"][0] = 1
    occurrence["content_hash"] = content_hash(
        {key: value for key, value in occurrence.items() if key != "content_hash"},
        omit=(),
    )
    occurrence_payload = canonical_bytes(occurrence)
    objects = dict(package.objects)
    objects[occurrence_path] = occurrence_payload
    manifest = dict(package.manifest)
    manifest["occurrence_graph"] = {
        **manifest["occurrence_graph"],
        "sha256": sha256_bytes(occurrence_payload),
        "byte_length": len(occurrence_payload),
    }
    manifest["content_hash"] = content_hash(
        {key: value for key, value in manifest.items() if key != "content_hash"},
        omit=(),
    )
    payload = canonical_zip_bytes(
        {"package.json": canonical_bytes(manifest), **objects},
        manifest_name="package.json",
    )

    with pytest.raises(ProductPackageError, match="occurrence graph differs"):
        scad.read_product_package(payload)

def test_package_read_materialize_reuses_validated_part_brep(monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = scad.build_product_package(_build_named_part())
    loaded = scad.read_product_package(scad.encode_product_package(package))

    monkeypatch.setattr(
        assembly_io,
        "read_brep_solid",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("validated part BREP was read again")
        ),
    )
    rebuilt = scad.materialize_definition(loaded.root_definition)

    assert isinstance(rebuilt, scad.Part)
    assert rebuilt.part_id == "box"


def test_replaced_part_definition_does_not_inherit_validation() -> None:
    definition = _build_named_part().definition
    mutated_blobs = dict(definition.blobs)
    mutated_blobs[definition.solid_cache_ref.path] += b"x"
    mutated = replace(definition, blobs=mutated_blobs)

    with pytest.raises(scad.ArtifactValidationError, match="blob_size_mismatch"):
        scad.encode_part_definition(mutated)


def test_capture_function_exports_unified_product_package(tmp_path: Path) -> None:
    part = _build_named_part("exported")
    path = tmp_path / "out" / "exported.scadpkg"
    captured = scad.capture(part, path)

    assert path.is_file()
    assert path.read_bytes() == captured.package_bytes
    loaded = scad.load_product_package(path)
    assert isinstance(loaded, scad.PartDefinition)
    assert loaded.definition_id == "exported"


def test_capture_assembly_exports_unified_product_package(tmp_path: Path) -> None:
    _part, _child, root = _build_nested_assembly()
    path = tmp_path / "out" / "root.scadpkg"
    captured = scad.capture(root, path)

    assert path.is_file()
    assert path.read_bytes() == captured.package_bytes
    loaded = scad.load_product_package(path)
    assert isinstance(loaded, scad.AssemblyDefinition)
    assert loaded.definition_id == "root"


def test_capture_rejects_legacy_keyword_signature(tmp_path: Path) -> None:
    part = _build_named_part("no_keyword_compatibility")
    path = tmp_path / "out" / "no_keyword_compatibility.scadpkg"

    with pytest.raises(TypeError, match="positional-only"):
        scad.capture(value=part, path=path)
