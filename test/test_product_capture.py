from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.artifacts.canonical import canonical_bytes, content_hash, sha256_bytes
from simplecadapi.product.packages import ProductPackage, ProductPackageError
from simplecadapi.scene import (
    ProductScenePackage,
    canonical_json_bytes,
    canonical_zip_bytes,
    compute_scene_revision,
    parse_canonical_json,
    preflight_zip_bytes,
    read_scene_package,
)
from test_product_packages import _build_named_part, _build_nested_assembly


def _entity_documents(scene: ProductScenePackage) -> list[dict]:
    return [
        parse_canonical_json(scene.blobs[record["uri"]])
        for record in scene.manifest["entity_assets"]
    ]


def test_capture_part_embeds_one_complete_independent_scene(tmp_path: Path) -> None:
    result = _build_named_part("captured_part")
    path = tmp_path / "out" / "captured_part.scadpkg"

    captured = scad.capture(result, path)
    payload = path.read_bytes()
    loaded = scad.read_product_package(payload)
    scene = read_scene_package(loaded.scene_bytes)

    assert captured.package.manifest["schema_version"] == "3.0"
    assert captured.scene.manifest["schema_version"] == "2.0"
    assert loaded.scene_path == "projections/scene/scene.json"
    assert scene.manifest == captured.scene.manifest
    assert dict(scene.blobs) == dict(captured.scene.blobs)
    assert [item["definition_id"] for item in scene.manifest["definitions"]] == [
        "captured_part"
    ]
    assert len(scene.manifest["product_assets"]) == 1
    assert len(scene.manifest["feature_graph_assets"]) == 1
    assert scene.manifest["feature_index"]
    assert scene.manifest["source_index"]
    assert loaded.occurrence_graph.root_definition_id == "captured_part"
    assert loaded.occurrence_graph.root_node_id == "node/captured_part"

def test_capture_federates_definition_graphs_sources_connectors_and_joints(
    tmp_path: Path,
) -> None:
    _part, _child, root = _build_nested_assembly()
    path = tmp_path / "out" / "root.scadpkg"

    scene = scad.capture(root, path).scene
    manifest = scene.manifest

    assert {item["definition_id"] for item in manifest["definitions"]} == {
        "linked",
        "child",
        "root",
    }
    assert {item["definition_id"] for item in manifest["feature_graph_assets"]} == {
        "linked",
        "child",
        "root",
    }
    assert {item["definition_id"] for item in manifest["feature_index"]} == {
        "linked",
        "child",
        "root",
    }
    assert len({item["uri"] for item in manifest["source_index"]}) <= len(
        manifest["source_index"]
    )
    assert {item["connector_id"] for item in manifest["connectors"]} == {
        "mount",
        "public_mount",
    }
    assert len(manifest["joints"]) == 1
    joint = manifest["joints"][0]
    assert joint["joint_id"] == "joint/root/nested/joint"
    assert joint["connector_a"]["definition_id"] == "linked"
    assert joint["connector_b"]["definition_id"] == "linked"
    assert joint["source_feature_id"] is not None
    feature = next(
        item
        for item in manifest["feature_index"]
        if item["feature_id"] == joint["source_feature_id"]
    )
    assert feature["op"] == "make_revolute_constraint_rassembly"


def test_capture_preserves_gear_coupling_joint(tmp_path: Path) -> None:
    @scad.part(id="coupling_base")
    def build_base() -> scad.Part:
        part = scad.make_part_rpart(
            part_id="coupling_base",
            body=scad.make_box_rsolid(width=12.0, height=4.0, depth=2.0),
        )
        for connector_id, origin in (
            ("left_axis", (3.0, 2.0, 2.0)),
            ("right_axis", (9.0, 2.0, 2.0)),
        ):
            part = scad.add_connector_rpart(
                part=part,
                connector=scad.make_placement_connector_rconnector(
                    connector_id=connector_id,
                    placement=scad.make_placement_rplacement(origin=origin),
                ),
            )
        return part

    @scad.part(id="coupling_wheel")
    def build_wheel() -> scad.Part:
        part = scad.make_part_rpart(
            part_id="coupling_wheel",
            body=scad.make_cylinder_rsolid(radius=2.0, height=1.0),
        )
        return scad.add_connector_rpart(
            part=part,
            connector=scad.make_placement_connector_rconnector(
                connector_id="axis",
                placement=scad.identity_placement_rplacement(),
            ),
        )

    base = build_base()
    wheel = build_wheel()

    @scad.assemble(
        id="gear_coupling",
        definitions=(base, wheel),
    )
    def build_assembly() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(assembly_id="gear_coupling")
        for component_id, item in (
            ("base", base.value),
            ("wheel_a", wheel.value),
            ("wheel_b", wheel.value),
        ):
            assembly = scad.add_component_rassembly(
                assembly=assembly,
                item=item,
                component_id=component_id,
                placement=scad.identity_placement_rplacement(),
            )
        assembly = scad.ground_component_rassembly(
            assembly=assembly,
            component_id="base",
        )
        base_left = scad.make_connector_ref_rconnectorref(
            component_id="base",
            connector_id="left_axis",
        )
        base_right = scad.make_connector_ref_rconnectorref(
            component_id="base",
            connector_id="right_axis",
        )
        wheel_a = scad.make_connector_ref_rconnectorref(
            component_id="wheel_a",
            connector_id="axis",
        )
        wheel_b = scad.make_connector_ref_rconnectorref(
            component_id="wheel_b",
            connector_id="axis",
        )
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id="support_a",
            connector_a=base_left,
            connector_b=wheel_a,
            drive_angle_degrees=30.0,
        )
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id="support_b",
            connector_a=base_right,
            connector_b=wheel_b,
        )
        assembly = scad.add_gear_constraint_rassembly(
            assembly=assembly,
            constraint_id="mesh",
            connector_a=wheel_a,
            connector_b=wheel_b,
            pitch_radius_a=2.0,
            pitch_radius_b=4.0,
        )
        return scad.solve_assembly_constraints_rassembly(assembly=assembly)

    path = tmp_path / "out" / "gear_coupling.scadpkg"
    manifest = scad.capture(build_assembly(), path).scene.manifest
    joints = {joint["joint_type"]: joint for joint in manifest["joints"]}

    assert set(joints) == {"revolute", "gear"}
    assert joints["gear"]["parameters"] == {
        "phase_offset": 0.0,
        "pitch_radius_a": 2.0,
        "pitch_radius_b": 4.0,
    }
    feature = next(
        item
        for item in manifest["feature_index"]
        if item["feature_id"] == joints["gear"]["source_feature_id"]
    )
    assert feature["op"] == "make_gear_constraint_rassembly"


def test_entity_feature_output_matches_durable_topology_snapshot(tmp_path: Path) -> None:
    result = _build_named_part("lineage_part")
    path = tmp_path / "out" / "lineage_part.scadpkg"
    scene = scad.capture(result, path).scene
    definition = result.definition
    snapshot = parse_canonical_json(
        definition.blobs[definition.topology_snapshot_ref.path]
    )
    expected = {
        (item["kind"], item["topo_id"]): item["feature_output"]
        for item in snapshot["entities"]
    }
    entity_document = _entity_documents(scene)[0]

    for entity in entity_document["entities"]:
        source = entity["source"]
        feature_output = expected[(entity["kind"], entity["topo_id"])]
        assert source["kind"] == "feature_output"
        assert source["graph_id"] == feature_output["graph_id"]
        assert source["node_id"] == feature_output["node_id"]
        assert source["output_slot"] == feature_output["output_slot"]
        assert source["topology_kind"] == feature_output["kind"]
        assert source["topo_id"] == feature_output["topo_id"]


def test_repeated_builds_capture_byte_identical_packages(tmp_path: Path) -> None:
    first = _build_named_part("deterministic_capture")
    second = _build_named_part("deterministic_capture")
    first_path = tmp_path / "out" / "first.scadpkg"
    second_path = tmp_path / "out" / "second.scadpkg"

    first_capture = scad.capture(first, first_path)
    second_capture = scad.capture(second, second_path)
    assert first_capture.package_bytes == second_capture.package_bytes
    assert first_path.read_bytes() == second_path.read_bytes()


def test_product_package_rejects_mutated_scene_projection(tmp_path: Path) -> None:
    package_path = tmp_path / "out" / "mutated_scene.scadpkg"
    captured = scad.capture(_build_named_part("mutated_scene"), package_path)
    scene_path = captured.package.scene_path
    assert scene_path is not None
    scene_manifest = parse_canonical_json(captured.package.objects[scene_path])
    scene_manifest["scene_id"] = "changed"
    scene_manifest["revision"] = compute_scene_revision(scene_manifest)
    mutated_objects = dict(captured.package.objects)
    mutated_objects[scene_path] = canonical_json_bytes(scene_manifest)
    with pytest.raises(ProductPackageError, match="scene manifest identity|scene projection identity"):
        scad.validate_product_package(
            ProductPackage(
                captured.package.manifest,
                mutated_objects,
                captured.package.root_definition,
            )
        )
