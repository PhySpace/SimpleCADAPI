import pickle
from copy import deepcopy

import pytest

import simplecadapi as scad
import simplecadapi.ql as ql
from simplecadapi.artifacts.brep import read_brep_solid, write_brep_bytes
from simplecadapi.artifacts.canonical import ArtifactValidationError
from simplecadapi.artifacts.topology_snapshot import (
    capture_topology_snapshot,
    encode_topology_snapshot,
    restore_topology_snapshot,
)


def _tagged_box():
    return scad.apply_tag(scad.make_box_rsolid(2.0, 3.0, 4.0), "role.body")


def test_topology_snapshot_is_deterministic_across_independent_builds():
    assert encode_topology_snapshot(_tagged_box()) == encode_topology_snapshot(_tagged_box())


@pytest.mark.parametrize(
    "factory",
    [
        lambda offset: scad.make_cylinder_rsolid(
            radius=2.0,
            height=4.0,
            bottom_face_center=(offset, 0.0, 0.0),
            axis=(0.0, offset, 0.0),
        ),
        lambda offset: scad.make_cone_rsolid(
            bottom_radius=3.0,
            top_radius=1.0,
            height=4.0,
            bottom_face_center=(offset, 0.0, 0.0),
            axis=(0.0, offset, 0.0),
        ),
        lambda offset: scad.make_sphere_rsolid(
            radius=2.0,
            center=(offset, 0.0, 0.0),
        ),
    ],
)
def test_topology_snapshot_evaluates_expression_driven_primitive_positions(factory):
    offset = scad.var(name="primitive_offset", default=1.0)
    solid = factory(offset)

    snapshot = capture_topology_snapshot(solid)
    geo_values = [
        entity["metadata"]["geo"]
        for entity in snapshot["entities"]
        if "geo" in entity["metadata"]
    ]

    assert encode_topology_snapshot(solid)
    assert geo_values
    assert all(
        not isinstance(value, (scad.Var, scad.Expr))
        for geo in geo_values
        for value in _flatten_metadata_values(geo)
    )


def _flatten_metadata_values(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _flatten_metadata_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _flatten_metadata_values(child)
    else:
        yield value


def test_brep_bytes_are_a_fixed_point_of_decoding():
    # Four holes rotated by 90 degrees leave zeros that OCCT reads back as
    # -0.0; a cached (decoded) body must still encode like the built one.
    tool = scad.make_cylinder_rsolid(radius=2, height=15, bottom_face_center=(12, 0, -5))
    tools = scad.radial_pattern_rsolidlist(
        shape=tool, center=(0, 0, 0), axis=(0, 0, 1), count=4, total_rotation_angle=360.0
    )
    plate = scad.cut_rsolid(scad.make_cylinder_rsolid(radius=20, height=5), tools)

    payload = write_brep_bytes(plate)

    assert write_brep_bytes(read_brep_solid(payload)) == payload


def _chamfered_ribs():
    # Two triangular ribs under a slab, their hypotenuses chamfered. On the
    # OCCT build this was found with, a few doubles of this shape move by an
    # ulp on every BinTools read and alternate between two encodings.
    def triangle(a, b, c):
        return scad.make_face_from_wire_rface(
            scad.make_wire_from_edges_rwire(
                edges=[
                    scad.make_segment_redge(start=a, end=b),
                    scad.make_segment_redge(start=b, end=c),
                    scad.make_segment_redge(start=c, end=a),
                ]
            )
        )

    slab = scad.make_box_rsolid(20, 4, 20, bottom_face_center=(0, 2, -10))
    column = scad.make_cylinder_rsolid(
        radius=2.5, height=5, bottom_face_center=(0, 0, 0), axis=(0, -1, 0)
    )
    ribs = [
        scad.extrude_rsolid(
            profile=triangle((s * 2.5, 0, -0.6), (s * 5.5, 0, -0.6), (s * 2.5, -5, -0.6)),
            direction=(0, 0, 1),
            distance=1.2,
        )
        for s in (-1, 1)
    ]
    body = scad.union_rsolid(slab, column, *ribs)
    hypotenuse = 34**0.5
    edges = ql.edges().where(
        ql.and_(
            ql.prop("geom.length", ">=", hypotenuse - 0.1),
            ql.prop("geom.length", "<=", hypotenuse + 0.1),
        )
    )
    return scad.chamfer_rsolid(solid=body, edges=edges, distance=0.2)


def test_brep_bytes_settle_when_decoding_cycles():
    # Decoding never reaches a fixed point here, so the canonical bytes are a
    # member of the cycle. A body restored from a pickle (the cell cache) or
    # from a package must still encode like the built one.
    built = _chamfered_ribs()
    payload = write_brep_bytes(built)

    assert write_brep_bytes(pickle.loads(pickle.dumps(built))) == payload
    assert write_brep_bytes(read_brep_solid(payload)) == payload


def test_brep_bytes_agree_when_decoding_never_settles(monkeypatch):
    # Some orbits drift forever. With the bound below the cycle the ribs
    # stand in for such a shape: a restored body, and one restored twice,
    # must still encode like the built one.
    import simplecadapi.artifacts.brep as brep

    monkeypatch.setattr(brep, "_MAX_DECODE_ROUNDS", 1)
    built = _chamfered_ribs()
    payload = write_brep_bytes(built)
    restored = pickle.loads(pickle.dumps(built))

    assert write_brep_bytes(restored) == payload
    assert write_brep_bytes(pickle.loads(pickle.dumps(restored))) == payload
    assert write_brep_bytes(read_brep_solid(payload)) == payload


def test_topology_snapshot_restores_exact_semantic_state_after_brep_roundtrip():
    source = _tagged_box()
    snapshot = encode_topology_snapshot(source)
    restored = read_brep_solid(write_brep_bytes(source))

    restore_topology_snapshot(restored, snapshot)

    assert encode_topology_snapshot(restored) == snapshot
    assert scad.list_tags(restored) == scad.list_tags(source)


def test_topology_snapshot_restores_feature_output_lineage():
    with scad.GraphSession(graph_id="lineage_probe") as session:
        source = scad.make_box_rsolid(2.0, 3.0, 4.0)
        session.capture_result(value=source)
    snapshot = capture_topology_snapshot(source)
    restored = read_brep_solid(write_brep_bytes(source))

    restore_topology_snapshot(restored, snapshot)

    assert {item["feature_output"]["node_id"] for item in snapshot["entities"]} == {
        session.result_node_ids[0]
    }
    assert {
        child._get_runtime("topo.ref").node_id for child in restored.get_children()
    } == {session.result_node_ids[0]}


def test_topology_snapshot_restores_fused_bearing_with_symmetric_wires():
    bearing = scad.std.bearing.make_ball_bearing_rassembly(
        bore_diameter=16.0,
        outer_diameter=24.0,
        bearing_width=5.0,
        ball_diameter=2.5,
        ball_count=12,
        raceway_clearance=0.0,
        edge_chamfer=0.0,
        assembly_id="snapshot_bearing",
        drive_angle_degrees=None,
        fuse_rolling_elements=True,
        rolling_element_fuse_overlap=0.03,
        material=None,
    )
    source = bearing.get_component("outer_ring").item.body
    snapshot = encode_topology_snapshot(source)
    restored = read_brep_solid(write_brep_bytes(source))

    restore_topology_snapshot(restored, snapshot)

    assert encode_topology_snapshot(restored) == snapshot


def test_topology_snapshot_rejects_geometry_mismatch_without_partial_restore():
    source = _tagged_box()
    target = scad.make_box_rsolid(2.0, 3.0, 5.0)
    before = encode_topology_snapshot(target)

    with pytest.raises(ArtifactValidationError) as error:
        restore_topology_snapshot(target, capture_topology_snapshot(source))

    assert error.value.reason == "geometry_mismatch"
    assert encode_topology_snapshot(target) == before


def test_topology_snapshot_rejects_duplicate_restored_ids():
    source = _tagged_box()
    target = read_brep_solid(write_brep_bytes(source))
    snapshot = deepcopy(capture_topology_snapshot(source))
    snapshot["entities"][1]["topo_id"] = snapshot["entities"][0]["topo_id"]

    with pytest.raises(ArtifactValidationError) as error:
        restore_topology_snapshot(target, snapshot)

    assert error.value.reason == "topology_snapshot_invalid"
