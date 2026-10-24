"""Materials, placements, parts and connectors against the reference."""

import pytest

import simplecadapi._cpp as scad
from product_support import parity


def test_material_values_and_assignment():
    parity("material_basic", """
        material = scad.make_material_rmaterial(
            "aluminum_6061", name=" Aluminum 6061 ", density=2.7e-6, density_unit="kg/mm^3", color=(0.7, 0.7, 0.75))
        bare = scad.make_material_rmaterial("bare")
        part = scad.make_part_rpart("base_plate", scad.make_box_rsolid(2.0, 3.0, 1.0), name="Base plate")
        assigned = scad.assign_material_rpart(part, material)
        result = {
            "material": material.to_dict(),
            "bare": bare.to_dict(),
            "equal": material == scad.make_material_rmaterial(
                "aluminum_6061", name="Aluminum 6061", density=2.7e-6, density_unit="kg/mm^3", color=(0.7, 0.7, 0.75)),
            "part": part.to_dict(),
            "assigned": assigned.to_dict(),
            "original_unchanged": part.material is None,
            "assigned_material_equal": assigned.material == material,
        }
    """)


def test_material_failures():
    parity("material_failures", """
        result = {
            "density_without_unit": failure(lambda: scad.make_material_rmaterial("m", density=1.0)),
            "unit_without_density": failure(lambda: scad.make_material_rmaterial("m", density_unit="kg")),
            "negative_density": failure(lambda: scad.make_material_rmaterial("m", density=-2.0, density_unit="kg")),
            "bad_color": failure(lambda: scad.make_material_rmaterial("m", color=(1.2, 0.0, 0.0))),
            "short_color": failure(lambda: scad.make_material_rmaterial("m", color=(1.0, 0.0))),
            "bad_id": failure(lambda: scad.make_material_rmaterial("1bad")),
            "empty_name": failure(lambda: scad.make_material_rmaterial("m", name="  ")),
            "non_string_id": failure(lambda: scad.make_material_rmaterial(7)),
        }
    """)


def test_placement_is_a_canonical_frame():
    parity("placement_frames", """
        quarter = scad.make_placement_rplacement(origin=(10.0, 20.0, 30.0), x_axis=(0.0, 1.0, 0.0), y_axis=(-1.0, 0.0, 0.0))
        tilted = scad.make_placement_rplacement((1.0, 2.0, 3.0), (2.0, 0.0, 0.0), (0.0, 0.0, 5.0))
        result = {
            "quarter": quarter.to_dict(),
            "tilted": tilted.to_dict(),
            "point": list(quarter.transform_point((1.0, 2.0, 3.0))),
            "vector": list(quarter.transform_vector((1.0, 2.0, 3.0))),
            "composed": quarter.compose(tilted).to_dict(),
            "identity": scad.identity_placement_rplacement().to_dict(),
            "equal": quarter == scad.make_placement_rplacement((10.0, 20.0, 30.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
        }
    """)


def test_placement_follows_the_workplane():
    parity("placement_workplane", """
        with scad.SimpleWorkplane(origin=(1, 2, 3), normal=(1, 0, 0), x_dir=(0, 1, 0)):
            placed = scad.make_placement_rplacement(origin=(1.0, 0.0, 0.0), x_axis=(1.0, 0.0, 0.0))
            identity = scad.identity_placement_rplacement()
        result = {"placed": placed.to_dict(), "identity": identity.to_dict()}
    """)


def test_placement_failures():
    parity("placement_failures", """
        result = {
            "parallel": failure(lambda: scad.make_placement_rplacement((0, 0, 0), (1, 0, 0), (1, 0, 0))),
            "zero_axis": failure(lambda: scad.make_placement_rplacement((0, 0, 0), x_axis=(0, 0, 0))),
            "direct_zero": failure(lambda: scad.Placement((0, 0, 0), x_axis=(0, 0, 0))),
            "short_origin": failure(lambda: scad.Placement((0, 0))),
        }
    """, ignore=("message",))


def test_placement_rejects_a_nan_origin_with_the_coordinate_system_error():
    with pytest.raises(scad.SimpleCADError) as info:
        scad.make_placement_rplacement((float("nan"), 0, 0))
    assert info.value.operation == "CoordinateSystem.transform_point"


def test_placement_is_hashable_and_reprs_like_a_dataclass():
    placement = scad.Placement((1.0, 2.0, 3.0))
    assert hash(placement) == hash(scad.Placement((1.0, 2.0, 3.0)))
    assert repr(placement) == (
        "Placement(origin=(1.0, 2.0, 3.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 1.0, 0.0), z_axis=(0.0, 0.0, 1.0))"
    )
    placement.set_metadata("k", {"a": 1})
    assert placement.get_metadata("k") == {"a": 1}
    assert placement.get_metadata("missing", 5) == 5


def test_part_creation_and_errors():
    parity("part_basic", """
        body = scad.make_box_rsolid(2.0, 3.0, 1.0)
        part = scad.make_part_rpart("base_plate", body, name=" Plate ")
        result = {
            "part": part.to_dict(),
            "ids": list(part.connector_ids()),
            "bad_id": failure(lambda: scad.make_part_rpart("", body)),
            "non_solid": failure(lambda: scad.make_part_rpart("p", body.get_faces(0))),
            "bad_name": failure(lambda: scad.make_part_rpart("p", body, name="")),
            "bad_material": failure(lambda: scad.assign_material_rpart(part, "steel")),
            "bad_part": failure(lambda: scad.assign_material_rpart(body, scad.make_material_rmaterial("m"))),
        }
    """)


def test_part_has_no_material_argument():
    with pytest.raises(TypeError):
        scad.make_part_rpart("p", scad.make_box_rsolid(1, 1, 1), material=scad.make_material_rmaterial("m"))


def test_placement_connector_and_add_connector():
    parity("connector_placement", """
        part = scad.make_part_rpart("p", scad.make_box_rsolid(1.0, 1.0, 1.0))
        placement = scad.make_placement_rplacement(origin=(1.0, 2.0, 3.0), x_axis=(0.0, 1.0, 0.0), y_axis=(-1.0, 0.0, 0.0))
        connector = scad.make_placement_connector_rconnector("axis", placement, name=" Main axis ")
        with_axis = scad.add_connector_rpart(part, connector)
        result = {
            "connector": connector.to_dict(),
            "kind": connector.anchor_kind,
            "frame": connector.placement.to_dict(),
            "part": with_axis.to_dict(),
            "original": part.to_dict(),
            "lookup": with_axis.get_connector("axis").to_dict(),
            "duplicate": failure(lambda: scad.add_connector_rpart(with_axis, connector)),
            "missing": failure(lambda: with_axis.get_connector("nope")),
            "bad_placement": failure(lambda: scad.make_placement_connector_rconnector("axis", (0, 0, 0))),
            "bad_id": failure(lambda: scad.make_placement_connector_rconnector("a b", placement)),
            "bad_part": failure(lambda: scad.add_connector_rpart(None, connector)),
            "bad_connector": failure(lambda: scad.add_connector_rpart(part, placement)),
        }
    """)


def test_face_edge_and_vertex_connectors():
    parity("connector_geometry", """
        box = scad.make_box_rsolid(2.0, 4.0, 6.0)
        face = top_face(box)
        edge = vertical_edge(box)
        vertex = box.get_edges(0).get_start_vertex()
        face_connector = scad.make_face_connector_rconnector("top", face)
        flipped = scad.make_face_connector_rconnector("top_flipped", face, name="Top", flip=True)
        edge_connector = scad.make_edge_connector_rconnector("rail", edge)
        vertex_connector = scad.make_vertex_connector_rconnector("corner", vertex, flip=True)
        result = {
            "face": face_connector.to_dict(),
            "face_frame": face_connector.placement.to_dict(),
            "flipped": flipped.to_dict(),
            "flipped_frame": flipped.placement.to_dict(),
            "edge": edge_connector.to_dict(),
            "edge_frame": edge_connector.placement.to_dict(),
            "vertex": vertex_connector.to_dict(),
            "vertex_frame": vertex_connector.placement.to_dict(),
        }
    """, ignore=("metadata_geo",))


def test_geometry_connector_failures():
    parity("connector_geometry_failures", """
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        face, edge = box.get_faces(0), box.get_edges(0)
        result = {
            "face_not_face": failure(lambda: scad.make_face_connector_rconnector("c", edge)),
            "edge_not_edge": failure(lambda: scad.make_edge_connector_rconnector("c", face)),
            "vertex_not_vertex": failure(lambda: scad.make_vertex_connector_rconnector("c", face)),
            "bad_id": failure(lambda: scad.make_face_connector_rconnector("bad id", face)),
        }
    """)


def test_connector_refs_and_limits():
    parity("refs_and_limits", """
        ref = scad.make_connector_ref_rconnectorref("base", "axis")
        limit = scad.make_scalar_limit_rscalarlimit(-1.0, 5.0)
        result = {
            "ref": ref.to_dict(),
            "equal": ref == scad.make_connector_ref_rconnectorref("base", "axis"),
            "limit": limit.to_dict(),
            "contains": [limit.contains(-1.0), limit.contains(5.0), limit.contains(5.5)],
            "bad_component": failure(lambda: scad.make_connector_ref_rconnectorref("", "axis")),
            "bad_connector": failure(lambda: scad.make_connector_ref_rconnectorref("base", "1x")),
            "reversed": failure(lambda: scad.make_scalar_limit_rscalarlimit(2.0, 1.0)),
            "nan": failure(lambda: scad.make_scalar_limit_rscalarlimit(float("nan"), 1.0)),
        }
    """)


def test_geometry_ref_and_anchor_validation():
    parity("anchors", """
        selector = {"center": [0.0, 0.0, 1.0], "normal": [0.0, 0.0, 1.0]}
        ref = scad.GeometryRef("FACE", "n1", selector, True)
        anchor = scad.ConnectorAnchor("geometry", geometry_ref=ref)
        connector = scad.Connector("c", anchor=anchor)
        result = {
            "ref": ref.to_dict(),
            "anchor": anchor.to_dict(),
            "connector": connector.to_dict(),
            "frame": connector.placement.to_dict(),
            "bad_kind": failure(lambda: scad.GeometryRef("shell", None, selector)),
            "bad_selector": failure(lambda: scad.GeometryRef("face", None, [1])),
            "bad_anchor_kind": failure(lambda: scad.ConnectorAnchor("magnet")),
            "geometry_needs_ref": failure(lambda: scad.ConnectorAnchor("geometry")),
            "placement_needs_placement": failure(lambda: scad.ConnectorAnchor("placement")),
            "no_anchor": failure(lambda: scad.Connector("c")),
            "mixed": failure(lambda: scad.Connector(
                "c", geometry_ref=ref, anchor=scad.ConnectorAnchor("placement", placement=scad.Placement((0, 0, 0))))),
        }
    """)
