from __future__ import annotations
from copy import deepcopy

from dataclasses import replace
from pathlib import Path

import pytest
from simplecadapi.product.placement import placement_ticks

import simplecadapi as scad
from simplecadapi.artifacts.canonical import (
    ArtifactValidationError,
    content_hash,
    sha256_bytes,
)
from simplecadapi.artifacts.feature_graph import (
    FEATURE_GRAPH_MEDIA_TYPE,
    capture_feature_graph,
)


GENERATOR = {
    "simplecadapi_version": "2.0.4b1",
    "ocp_version": "7.9.3.1",
    "python_abi": "cp313",
    "platform_tag": "darwin-arm64",
    "semantic_registry_version": "simplecad-operations-2.0",
}


def _build_nested_gear_train():
    @scad.part(id="train_base")
    def build_base() -> scad.Part:
        body = scad.make_box_rsolid(width=30.0, height=8.0, depth=2.0)
        part = scad.make_part_rpart(part_id="train_base", body=body)
        left = scad.make_placement_connector_rconnector(
            connector_id="left_axis",
            placement=scad.make_placement_rplacement(origin=(5.0, 4.0, 2.0)),
        )
        right = scad.make_placement_connector_rconnector(
            connector_id="right_axis",
            placement=scad.make_placement_rplacement(origin=(25.0, 4.0, 2.0)),
        )
        part = scad.add_connector_rpart(part=part, connector=left)
        return scad.add_connector_rpart(part=part, connector=right)

    @scad.part(id="train_gear")
    def build_gear() -> scad.Part:
        body = scad.make_cylinder_rsolid(radius=4.0, height=3.0)
        part = scad.make_part_rpart(part_id="train_gear", body=body)
        axis = scad.make_placement_connector_rconnector(
            connector_id="axis",
            placement=scad.make_placement_rplacement(origin=(0.0, 0.0, 0.0)),
        )
        return scad.add_connector_rpart(part=part, connector=axis)

    base = build_base()
    gear = build_gear()

    @scad.assemble(
        id="gear_train",
        definitions=(base, gear),
    )
    def build_train() -> scad.Assembly:
        identity = scad.identity_placement_rplacement()
        assembly = scad.make_assembly_rassembly(assembly_id="gear_train")
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=base.value,
            component_id="base",
            placement=identity,
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=gear.value,
            component_id="gear_a",
            placement=identity,
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=gear.value,
            component_id="gear_b",
            placement=identity,
        )
        assembly = scad.ground_component_rassembly(
            assembly=assembly,
            component_id="base",
        )
        base_left = scad.make_connector_ref_rconnectorref("base", "left_axis")
        base_right = scad.make_connector_ref_rconnectorref("base", "right_axis")
        gear_a = scad.make_connector_ref_rconnectorref("gear_a", "axis")
        gear_b = scad.make_connector_ref_rconnectorref("gear_b", "axis")
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id="support_a",
            connector_a=base_left,
            connector_b=gear_a,
            drive_angle_degrees=30.0,
        )
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id="support_b",
            connector_a=base_right,
            connector_b=gear_b,
        )
        assembly = scad.add_gear_constraint_rassembly(
            assembly=assembly,
            constraint_id="mesh",
            connector_a=gear_a,
            connector_b=gear_b,
            pitch_radius_a=4.0,
            pitch_radius_b=8.0,
        )
        assembly = scad.solve_assembly_constraints_rassembly(assembly=assembly)
        return scad.set_public_connector_rassembly(
            assembly=assembly,
            public_connector_id="output_axis",
            source_component_id="gear_b",
            source_connector_id="axis",
        )

    train = build_train()

    @scad.assemble(
        id="nested_train_pair",
        definitions=(train,),
    )
    def build_pair() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(assembly_id="nested_train_pair")
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=train.value,
            component_id="train_left",
            placement=scad.identity_placement_rplacement(),
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=train.value,
            component_id="train_right",
            placement=scad.make_placement_rplacement(origin=(50.0, 0.0, 0.0)),
        )
        return scad.set_public_connector_rassembly(
            assembly=assembly,
            public_connector_id="service_axis",
            source_component_id="train_right",
            source_connector_id="output_axis",
        )

    return base, gear, train, build_pair()


def test_assemble_external_reference_round_trip_preserves_hierarchy_and_coupling(
    tmp_path: Path,
) -> None:
    _base, gear, train, pair = _build_nested_gear_train()

    assert len(train.definition.definition_refs) == 2
    assert [item.definition_id for item in train.definition.instances].count(
        "train_gear"
    ) == 2
    assert [item.constraint_kind for item in train.value.constraints] == [
        "revolute",
        "revolute",
        "gear",
    ]
    assert scad.inspect_assembly_constraints_rconstraintreport(train.value).solved

    output = scad.export_assembly_definition(
        pair.definition,
        tmp_path / "pair.assembly-definition.zip",
    )
    loaded = scad.load_assembly_definition(output)
    rebuilt = scad.materialize_definition(loaded)

    assert loaded.canonical_bytes == pair.definition.canonical_bytes
    assert isinstance(rebuilt, scad.Assembly)
    assert rebuilt.component_ids() == ("train_left", "train_right")
    assert rebuilt.public_connector_ids() == ("service_axis",)
    left = rebuilt.get_component("train_left").item
    right = rebuilt.get_component("train_right").item
    assert left is right
    assert isinstance(left, scad.Assembly)
    assert left.get_component("gear_a").item is left.get_component("gear_b").item
    assert left.get_component("gear_a").item.part_id == gear.value.part_id
    assert left.constraint_ids() == ("mesh", "support_a", "support_b")
    assert scad.inspect_assembly_constraints_rconstraintreport(left).solved

    written = {item.name for item in tmp_path.glob("*.zip")}
    assert "pair.assembly-definition.zip" in written
    assert any(name.endswith(".part-definition.zip") for name in written)
    assert any(
        name.endswith(".assembly-definition.zip")
        and name != "pair.assembly-definition.zip"
        for name in written
    )


def test_assemble_keeps_authored_placements_separate_from_solved_snapshot() -> None:
    _base, _gear, train, _pair = _build_nested_gear_train()

    authored = {
        instance.instance_id: instance.placement
        for instance in train.definition.instances
    }
    solved = {
        item["instance_id"]: item["placement"]
        for item in train.definition.solved_snapshot["component_placements"]
    }

    identity = placement_ticks(scad.identity_placement_rplacement())
    assert authored["gear_a"] == identity
    assert solved["gear_a"]["origin"] == placement_ticks(
        scad.make_placement_rplacement(origin=(5.0, 4.0, 2.0))
    )["origin"]
    assert solved["gear_b"]["origin"] == placement_ticks(
        scad.make_placement_rplacement(origin=(25.0, 4.0, 2.0))
    )["origin"]
    assert train.definition.interface_hashes.geometry == content_hash(
        {
            "instances": [
                {
                    "instance_id": instance.instance_id,
                    "definition_id": instance.definition_id,
                    "geometry_hash": train.definition.resolved_definitions[
                        instance.definition_id
                    ].interface_hashes.geometry,
                    "placement": instance.placement,
                }
                for instance in train.definition.instances
            ]
        }
    )

    rebuilt = scad.materialize_definition(train.definition)
    assert isinstance(rebuilt, scad.Assembly)
    assert placement_ticks(rebuilt.get_component("gear_a").placement) == solved["gear_a"]
    assert placement_ticks(rebuilt.get_component("gear_b").placement) == solved["gear_b"]


def test_nested_occurrence_placements_survive_materialization_and_replay() -> None:
    @scad.part(id="durable_nested_ring")
    def build_ring() -> scad.Part:
        part = scad.make_part_rpart(
            part_id="durable_nested_ring",
            body=scad.make_cylinder_rsolid(radius=2.0, height=1.0),
        )
        return scad.add_connector_rpart(
            part=part,
            connector=scad.make_placement_connector_rconnector(
                connector_id="axis",
                placement=scad.identity_placement_rplacement(),
            ),
        )

    ring = build_ring()

    @scad.assemble(
        id="durable_nested_bearing",
        definitions=(ring,),
    )
    def build_bearing() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(assembly_id="durable_nested_bearing")
        for component_id in ("outer_ring", "inner_ring"):
            assembly = scad.add_component_rassembly(
                assembly=assembly,
                item=ring.value,
                component_id=component_id,
                placement=scad.identity_placement_rplacement(),
            )
        assembly = scad.ground_component_rassembly(
            assembly=assembly,
            component_id="outer_ring",
        )
        assembly = scad.add_revolute_constraint_rassembly(
            assembly=assembly,
            constraint_id="inner_outer_revolute",
            connector_a=scad.make_connector_ref_rconnectorref(
                component_id="outer_ring",
                connector_id="axis",
            ),
            connector_b=scad.make_connector_ref_rconnectorref(
                component_id="inner_ring",
                connector_id="axis",
            ),
            drive_angle_degrees=90.0,
        )
        assembly = scad.solve_assembly_constraints_rassembly(assembly=assembly)
        assembly = scad.set_public_connector_rassembly(
            assembly=assembly,
            public_connector_id="outer_axis",
            source_component_id="outer_ring",
            source_connector_id="axis",
        )
        return scad.set_public_connector_rassembly(
            assembly=assembly,
            public_connector_id="inner_axis",
            source_component_id="inner_ring",
            source_connector_id="axis",
        )

    bearing = build_bearing()
    quarter_turn = scad.make_placement_rplacement(
        origin=(0.0, 0.0, 0.0),
        x_axis=(0.0, 1.0, 0.0),
        y_axis=(-1.0, 0.0, 0.0),
    )

    @scad.assemble(
        id="durable_nested_fixture",
        definitions=(bearing, ring),
    )
    def build_fixture() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(assembly_id="durable_nested_fixture")
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=ring.value,
            component_id="housing",
            placement=scad.identity_placement_rplacement(),
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=ring.value,
            component_id="shaft",
            placement=quarter_turn,
        )
        assembly = scad.add_component_rassembly(
            assembly=assembly,
            item=bearing.value,
            component_id="bearing",
            placement=scad.identity_placement_rplacement(),
        )
        assembly = scad.ground_component_rassembly(
            assembly=assembly,
            component_id="housing",
        )
        assembly = scad.ground_component_rassembly(
            assembly=assembly,
            component_id="shaft",
        )
        assembly = scad.add_fixed_constraint_rassembly(
            assembly=assembly,
            constraint_id="outer_ring_to_housing",
            connector_a=scad.make_connector_ref_rconnectorref(
                component_id="housing",
                connector_id="axis",
            ),
            connector_b=scad.make_connector_ref_rconnectorref(
                component_id="bearing",
                connector_id="outer_axis",
            ),
        )
        return scad.add_fixed_constraint_rassembly(
            assembly=assembly,
            constraint_id="inner_ring_to_shaft",
            connector_a=scad.make_connector_ref_rconnectorref(
                component_id="shaft",
                connector_id="axis",
            ),
            connector_b=scad.make_connector_ref_rconnectorref(
                component_id="bearing",
                connector_id="inner_axis",
            ),
        )

    fixture = build_fixture()
    rebuilt_fixture = build_fixture()
    assert rebuilt_fixture.value is not fixture.value
    assert rebuilt_fixture.definition.content_hash == fixture.definition.content_hash
    occurrence_placements = {
        tuple(record["component_path"]): record["placement"]
        for record in fixture.definition.solved_snapshot["occurrence_placements"]
    }

    assert occurrence_placements[("bearing", "inner_ring")]["x_axis"] == [
        round(value * 1.0e9) for value in quarter_turn.x_axis
    ]

    for restored in (
        fixture.value,
        rebuilt_fixture.value,
        scad.materialize_definition(fixture.definition),
        fixture.replay(),
    ):
        assert isinstance(restored, scad.Assembly)
        restored_bearing = restored.get_component("bearing").item
        assert isinstance(restored_bearing, scad.Assembly)
        assert restored_bearing.get_component(
            "inner_ring"
        ).placement.x_axis == pytest.approx(quarter_turn.x_axis)
        assert scad.inspect_assembly_constraints_rconstraintreport(restored).solved


def test_assemble_rejects_undeclared_and_wrong_runtime_definition_identity() -> None:
    @scad.part(id="declared_part")
    def declared(width: float = 1.0) -> scad.Part:
        body = scad.make_box_rsolid(width=width, height=1.0, depth=1.0)
        return scad.make_part_rpart(part_id="declared_part", body=body)

    expected = declared(1.0)
    wrong = declared(2.0)

    @scad.assemble(id="wrong_identity", definitions=(expected,))
    def build_wrong() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly("wrong_identity")
        return scad.add_component_rassembly(
            assembly,
            wrong.value,
            "part",
            scad.identity_placement_rplacement(),
        )

    @scad.assemble(id="undeclared", definitions=())
    def build_undeclared() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly("undeclared")
        return scad.add_component_rassembly(
            assembly,
            expected.value,
            "part",
            scad.identity_placement_rplacement(),
        )

    with pytest.raises(ArtifactValidationError, match="reference_identity_mismatch"):
        build_wrong()
    with pytest.raises(ArtifactValidationError, match="reference_missing"):
        build_undeclared()


def test_assembly_graph_validation_rejects_hash_and_connector_mismatches() -> None:
    _base, _gear, train, _pair = _build_nested_gear_train()
    definition = train.definition

    first_ref = definition.definition_refs[0]
    wrong_ref = replace(first_ref, content_hash="sha256:" + "0" * 64)
    wrong_hash = replace(
        definition,
        definition_refs=(wrong_ref, *definition.definition_refs[1:]),
        content_hash="",
    )
    with pytest.raises(ArtifactValidationError) as hash_error:
        scad.validate_assembly_definition_graph(wrong_hash)
    assert hash_error.value.reason == "reference_identity_mismatch"
    assert hash_error.value.path == "/definition_refs/0"

    relations = [dict(item) for item in definition.relations]
    relations[0] = {
        **relations[0],
        "connector_b": {
            **relations[0]["connector_b"],
            "connector_id": "missing_axis",
        },
    }
    missing_connector = replace(
        definition,
        relations=tuple(relations),
        content_hash="",
    )
    with pytest.raises(ArtifactValidationError) as connector_error:
        scad.validate_assembly_definition_graph(missing_connector)
    assert connector_error.value.reason == "reference_missing"
    assert connector_error.value.path == "/relations/0/connector_b/connector_id"


def test_assembly_loader_reports_cycle_with_instance_path(tmp_path: Path) -> None:
    cycle_ref = scad.PartRef(
        definition_id="cycle_child",
        definition_kind="assembly",
        path="cycle.assembly-definition.zip",
        revision="r1",
        content_hash="sha256:" + "1" * 64,
        byte_length=0,
    )
    with scad.GraphSession(graph_id="cycle_root") as session:
        root = scad.make_assembly_rassembly(assembly_id="cycle_root")
        session.capture_result(value=root)
    feature_graph = capture_feature_graph(
        session=session,
        owner_definition_kind="assembly",
        owner_definition_id="cycle_root",
        owner_revision="r1",
        project_root=Path(__file__).resolve().parents[1],
        external_definitions=(
            {
                "definition_kind": cycle_ref.definition_kind,
                "definition_id": cycle_ref.definition_id,
                "revision": cycle_ref.revision,
                "content_hash": cycle_ref.content_hash,
            },
        ),
    )
    feature_payload = scad.encode_feature_graph_artifact(feature_graph)
    feature_path = (
        "features/"
        + feature_graph.content_hash.removeprefix("sha256:")
        + ".feature-graph.zip"
    )
    definition = scad.AssemblyDefinition(
        definition_id="cycle_root",
        revision="r1",
        tolerance_profile="simplecad-default",
        generator=GENERATOR,
        definition_refs=(cycle_ref,),
        instances=(
            scad.PartInstance(
                instance_id="child",
                definition_id="cycle_child",
                name=None,
                placement=scad.Placement((0.0, 0.0, 0.0)).to_dict(),
            ),
        ),
        relations=(),
        grounded_instance_ids=(),
        public_connectors=(),
        interface_hashes=scad.InterfaceHashes(
            geometry=content_hash({"instances": []}),
            connectors={},
            bindings={},
            material=None,
        ),
        feature_graph_ref=scad.BlobRef(
            path=feature_path,
            sha256=sha256_bytes(feature_payload),
            byte_length=len(feature_payload),
            media_type=FEATURE_GRAPH_MEDIA_TYPE,
        ),
        blobs={feature_path: feature_payload},
    )
    path = tmp_path / "cycle.assembly-definition.zip"
    path.write_bytes(scad.encode_assembly_definition(definition))

    with pytest.raises(ArtifactValidationError) as error:
        scad.load_assembly_definition(path)
    assert error.value.reason == "reference_cycle"
    assert "child" in error.value.message


def test_assemble_rejects_dependency_tolerance_profile_conflict() -> None:
    @scad.part(id="profile_part", tolerance_profile="alternate-profile")
    def build_part() -> scad.Solid:
        return scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)

    part = build_part()

    with pytest.raises(ArtifactValidationError, match="profile_incompatible"):

        @scad.assemble(id="profile_conflict", definitions=(part,))
        def build() -> scad.Assembly:
            return scad.make_assembly_rassembly("profile_conflict")


def test_assemble_resolves_every_call_and_follows_child_connector_edits() -> None:
    @scad.part(id="pair_base")
    def build_base() -> scad.Part:
        part = scad.make_part_rpart(
            "pair_base",
            scad.make_box_rsolid(width=2.0, height=2.0, depth=2.0),
        )
        return scad.add_connector_rpart(
            part,
            scad.make_placement_connector_rconnector(
                "mate",
                scad.identity_placement_rplacement(),
            ),
        )

    @scad.part(id="pair_tool_a")
    def build_tool_a(connector_x: float) -> scad.Part:
        part = scad.make_part_rpart(
            "pair_tool_a",
            scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0),
        )
        return scad.add_connector_rpart(
            part,
            scad.make_placement_connector_rconnector(
                "mate",
                scad.make_placement_rplacement(origin=(connector_x, 0.0, 0.0)),
            ),
        )

    @scad.part(id="pair_tool_b")
    def build_tool_b() -> scad.Part:
        part = scad.make_part_rpart(
            "pair_tool_b",
            scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0),
        )
        return scad.add_connector_rpart(
            part,
            scad.make_placement_connector_rconnector(
                "mate",
                scad.identity_placement_rplacement(),
            ),
        )

    base = build_base()
    tool_b = build_tool_b()

    def assembly_builder(tool_a: scad.PartBuildResult):
        @scad.assemble(
            id="pair_assembly",
            definitions=(base, tool_a, tool_b),
        )
        def build_pair() -> scad.Assembly:
            assembly = scad.make_assembly_rassembly("pair_assembly")
            for component_id, item, origin in (
                ("base_a", base.value, (0.0, 0.0, 0.0)),
                ("tool_a", tool_a.value, (4.0, 0.0, 0.0)),
                ("base_b", base.value, (20.0, 0.0, 0.0)),
                ("tool_b", tool_b.value, (24.0, 0.0, 0.0)),
            ):
                assembly = scad.add_component_rassembly(
                    assembly,
                    item,
                    component_id,
                    scad.make_placement_rplacement(origin=origin),
                )
            assembly = scad.ground_component_rassembly(assembly, "base_a")
            assembly = scad.ground_component_rassembly(assembly, "base_b")
            assembly = scad.add_fixed_constraint_rassembly(
                assembly,
                "constraint_a",
                scad.make_connector_ref_rconnectorref("base_a", "mate"),
                scad.make_connector_ref_rconnectorref("tool_a", "mate"),
            )
            return scad.add_fixed_constraint_rassembly(
                assembly,
                "constraint_b",
                scad.make_connector_ref_rconnectorref("base_b", "mate"),
                scad.make_connector_ref_rconnectorref("tool_b", "mate"),
            )

        return build_pair

    initial_builder = assembly_builder(build_tool_a(0.0))
    first = initial_builder()
    again = initial_builder()
    changed = assembly_builder(build_tool_a(2.0))()

    def origin(result: scad.AssemblyBuildResult, component_id: str):
        return tuple(result.value.get_component(component_id).placement.origin)

    # Nothing is reused: every call solves again and yields the same definition.
    assert again.value is not first.value
    assert again.definition.content_hash == first.definition.content_hash

    # Moving tool_a's connector moves tool_a and changes the definition;
    # the independent tool_b pair solves to the same place.
    assert changed.definition.content_hash != first.definition.content_hash
    assert origin(first, "tool_a") == pytest.approx((0.0, 0.0, 0.0))
    assert origin(changed, "tool_a") == pytest.approx((-2.0, 0.0, 0.0))
    assert origin(changed, "tool_b") == pytest.approx(origin(first, "tool_b"))
    assert scad.inspect_assembly_constraints_rconstraintreport(changed.value).solved


def test_nested_public_connector_change_reaches_the_parent_definition() -> None:
    @scad.part(id="nested_connector_part")
    def build_child(connector_x: float) -> scad.Part:
        part = scad.make_part_rpart(
            "nested_connector_part",
            scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0),
        )
        return scad.add_connector_rpart(
            part,
            scad.make_placement_connector_rconnector(
                "mate",
                scad.make_placement_rplacement(origin=(connector_x, 0.0, 0.0)),
            ),
        )

    def build_stage(child: scad.PartBuildResult) -> scad.AssemblyBuildResult:
        @scad.assemble(
            id="nested_connector_stage",
            definitions=(child,),
        )
        def stage() -> scad.Assembly:
            assembly = scad.make_assembly_rassembly("nested_connector_stage")
            assembly = scad.add_component_rassembly(
                assembly,
                child.value,
                "child",
                scad.identity_placement_rplacement(),
            )
            return scad.set_public_connector_rassembly(
                assembly,
                "output",
                "child",
                "mate",
            )

        return stage()

    def parent_builder(stage: scad.AssemblyBuildResult):
        @scad.assemble(
            id="nested_connector_parent",
            definitions=(stage,),
        )
        def parent() -> scad.Assembly:
            assembly = scad.make_assembly_rassembly("nested_connector_parent")
            assembly = scad.add_component_rassembly(
                assembly,
                stage.value,
                "grounded",
                scad.identity_placement_rplacement(),
            )
            assembly = scad.add_component_rassembly(
                assembly,
                stage.value,
                "moving",
                scad.make_placement_rplacement(origin=(10.0, 0.0, 0.0)),
            )
            assembly = scad.ground_component_rassembly(assembly, "grounded")
            return scad.add_fixed_constraint_rassembly(
                assembly,
                "nested_fixed",
                scad.make_connector_ref_rconnectorref("grounded", "output"),
                scad.make_connector_ref_rconnectorref("moving", "output"),
            )

        return parent

    initial_stage = build_stage(build_child(0.0))
    initial_parent_builder = parent_builder(initial_stage)
    first = initial_parent_builder()
    again = initial_parent_builder()
    changed_stage = build_stage(build_child(3.0))
    changed = parent_builder(changed_stage)()

    assert again.definition.content_hash == first.definition.content_hash
    # A connector edit two levels down changes the parent through its
    # reference to the rebuilt stage definition.
    assert changed.definition.content_hash != first.definition.content_hash
    (stage_ref,) = changed.definition.definition_refs
    assert stage_ref.content_hash == changed_stage.definition.content_hash
    assert scad.inspect_assembly_constraints_rconstraintreport(changed.value).solved


def test_assemble_owns_replayable_deterministic_feature_graph() -> None:
    @scad.part(id="graph_child")
    def build_child() -> scad.Part:
        return scad.make_part_rpart(
            part_id="graph_child",
            body=scad.make_box_rsolid(width=2.0, height=3.0, depth=4.0),
        )

    child = build_child()

    @scad.assemble(id="graph_parent", definitions=(child,))
    def build_parent() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(assembly_id="graph_parent")
        return scad.add_component_rassembly(
            assembly=assembly,
            item=child.value,
            component_id="child",
            placement=scad.identity_placement_rplacement(),
        )

    first = build_parent()
    again = build_parent()
    nodes = list(first.feature_graph.graph["nodes"])
    reference_nodes = [item for item in nodes if item["op"] == "reference_definition"]
    terminal_nodes = [
        item for item in nodes if item["op"] == "evaluate_assembly_definition"
    ]

    assert first.feature_graph.owner_definition_kind == "assembly"
    assert first.feature_graph.owner_definition_id == "graph_parent"
    assert first.feature_graph.external_definitions == (
        {
            "definition_kind": child.definition.definition_kind,
            "definition_id": child.definition.definition_id,
            "revision": child.definition.revision,
            "content_hash": child.definition.content_hash,
        },
    )
    assert len(reference_nodes) == 1
    assert reference_nodes[0]["params"]["definition_id"] == "graph_child"
    assert len(terminal_nodes) == 1
    assert first.feature_graph.result_node_ids == (terminal_nodes[0]["node_id"],)
    assert first.feature_graph.canonical_bytes == again.feature_graph.canonical_bytes

    archived = scad.load_feature_graph_artifact(
        first.definition.blobs[first.definition.feature_graph_ref.path]
    )
    assert archived.canonical_bytes == first.feature_graph.canonical_bytes
    replayed = first.replay()
    assert replayed.component_ids() == ("child",)
    assert replayed.get_component("child").item.part_id == "graph_child"


def test_assembly_feature_replay_tolerates_only_solver_scale_residual_drift() -> None:
    _base, _gear, train, _pair = _build_nested_gear_train()
    external_definitions = train.definition.resolved_definitions

    def with_translation_drift(drift: float):
        graph = deepcopy(dict(train.feature_graph.graph))
        terminal = next(
            node
            for node in graph["nodes"]
            if node["op"] == "evaluate_assembly_definition"
        )
        terminal["params"]["constraint_report"]["residuals"][0][
            "translation_error"
        ] += drift
        return replace(train.feature_graph, graph=graph, content_hash="")

    replayed = with_translation_drift(5.0e-8).replay(
        external_definitions=external_definitions
    )
    assert replayed[0].assembly_id == "gear_train"

    with pytest.raises(ValueError, match="residual report differs"):
        with_translation_drift(2.0e-7).replay(external_definitions=external_definitions)


def test_assemble_runs_in_its_own_session_when_called_inside_a_recording() -> None:
    @scad.part(id="hosted_child")
    def build_child() -> scad.Solid:
        return scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)

    child = build_child()

    @scad.assemble(id="hosted_parent", definitions=(child,))
    def build_parent() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly(assembly_id="hosted_parent")
        return scad.add_component_rassembly(
            assembly=assembly,
            item=child.value,
            component_id="child",
            placement=scad.identity_placement_rplacement(),
        )

    standalone = build_parent()
    outer = scad.GraphSession(graph_id="host", allow_external_definitions=True)
    with outer:
        nodes_before = len(outer.graph.nodes)
        with scad.SimpleWorkplane(origin=(0.0, 0.0, 7.0)):
            hosted = build_parent()
        # The build neither recorded into the caller nor inherited its frame.
        assert scad.get_active_session() is outer
        assert len(outer.graph.nodes) == nodes_before

    assert hosted.definition.content_hash == standalone.definition.content_hash
