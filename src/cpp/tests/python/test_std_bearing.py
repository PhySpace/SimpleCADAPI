"""simplecadapi.std.bearing against the reference SDK.

The assembly comes back as a product Assembly; the tests read it through the same accessors
in both implementations (component ids, parts, constraints, metadata)."""

import pytest
from std_support import compare

import simplecadapi._cpp as scad

pytestmark = pytest.mark.skipif(not hasattr(scad, "Assembly"), reason="product bindings are not built")

DESCRIBE_ASSEMBLY = '''
def describe_part(part):
    body = part.body
    return {"shape": describe(body, detail=False), "connectors": list(part.connector_ids()),
            "material": None if part.material is None else part.material.material_id}

def describe_bearing(b):
    c = b.get_constraint("inner_outer_revolute")
    return {
        "components": list(b.component_ids()),
        "constraints": list(b.constraint_ids()),
        "public": list(b.public_connector_ids()),
        "grounded": list(b.grounded_component_ids),
        "constraint": [c.constraint_kind, c.connector_a.component_id, c.connector_a.connector_id,
                       c.connector_b.component_id, c.connector_b.connector_id, c.drive_angle_degrees],
        "outer": describe_part(b.get_component("outer_ring").item),
        "inner": describe_part(b.get_component("inner_ring").item),
        "ball": describe_part(b.get_component(b.component_ids()[2]).item) if len(b.component_ids()) > 2 else None,
        "ring_meta": meta(b.get_component("outer_ring").item.body, "std.bearing.ring"),
        "inner_ring_meta": meta(b.get_component("inner_ring").item.body, "std.bearing.ring"),
        "meta": b.get_metadata("std.bearing.ball_bearing"),
    }
'''


def test_basic_ball_bearing_assembly():
    compare("bearing_basic", DESCRIBE_ASSEMBLY, """
        b = std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.05, "bearing_basic_test", 30.0)
        result = describe_bearing(b)
    """)


def test_ball_bearing_variants():
    compare("bearing_variants", DESCRIBE_ASSEMBLY, """
        out = {}
        out["inferred"] = describe_bearing(std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5))
        out["no_chamfer"] = describe_bearing(std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.0, "plain"))
        out["fused"] = describe_bearing(std.bearing.make_ball_bearing_rassembly(
            8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.0, "fz", fuse_rolling_elements=True, rolling_element_fuse_overlap=0.02))
        out["many"] = describe_bearing(std.bearing.make_ball_bearing_rassembly(60.0, 100.0, 18.0, 8.0, assembly_id="big"))
        result = out
    """)


def test_ball_bearing_material():
    compare("bearing_material", DESCRIBE_ASSEMBLY, """
        steel = scad.make_material_rmaterial("bearing_steel", density=7.85, density_unit="g/cm3")
        b = std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.0, "mat", material=steel)
        result = describe_bearing(b)
    """)


def test_ball_bearing_errors():
    compare("bearing_errors", """
        g = std.bearing.make_ball_bearing_rassembly
        result = [
            refuse(lambda: g(22.0, 8.0, 7.0, 3.5)),
            refuse(lambda: g(8.0, 22.0, 3.0, 3.5)),
            refuse(lambda: g(8.0, 22.0, 7.0, 8.0)),
            refuse(lambda: g(8.0, 22.0, 7.0, 3.5, 100)),
            refuse(lambda: g(8.0, 22.0, 7.0, 3.5, 2)),
            refuse(lambda: g(8.0, 22.0, 7.0, 3.5, 7, 0.05, 2.0)),
            refuse(lambda: g(0.0, 22.0, 7.0, 3.5)),
            refuse(lambda: g(8.0, 22.0, 7.0, 3.5, raceway_clearance=-1.0)),
            refuse(lambda: g(8.0, 22.0, 7.0, 3.5, edge_chamfer=float("nan"))),
            refuse(lambda: g(8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.0, "e", fuse_rolling_elements=True, rolling_element_fuse_overlap=0.0)),
            refuse(lambda: g(8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.0, "e", fuse_rolling_elements=True, rolling_element_fuse_overlap=5.0)),
        ]
    """)


def test_bearing_is_recorded_as_its_operators():
    compare("graph_bearing", """
        with scad.GraphSession() as session:
            std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.05, "rec", 30.0)
        nodes = nodes_of(session)
        ops = [n["op"] for n in nodes]
        result = {"sphere": ops.count("make_sphere_rsolid"), "arcs": ops.count("make_three_point_arc_redge"),
                  "revolves": ops.count("make_revolve_rsolid"), "revolute": ops.count("make_revolute_constraint_rassembly"),
                  "public": ops.count("make_set_public_connector_rassembly"),
                  "deltas": sum("topo_delta" in n for n in nodes)}
    """)


def test_bearing_assembly_composes_with_external_constraints():
    bearing = scad.std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, 7, 0.05, 0.0, "bearing_bind_test")
    shaft = scad.make_cylinder_rsolid(radius=3.8, height=14.0, bottom_face_center=(0.0, 0.0, -7.0), axis=(0.0, 0.0, 1.0))
    shaft_part = scad.make_part_rpart("shaft", shaft)
    top_face = max(shaft.faces(), key=lambda f: f.get_center().z if f.get_normal_at().z > 0.7 else -999.0)
    shaft_part = scad.add_connector_rpart(shaft_part, scad.make_face_connector_rconnector("axis", top_face))
    bearing = scad.add_component_rassembly(bearing, shaft_part, component_id="shaft",
                                           placement=scad.identity_placement_rplacement())
    bearing = scad.add_fixed_constraint_rassembly(bearing, "shaft_to_inner_ring",
                                                  scad.make_connector_ref_rconnectorref("inner_ring", "axis"),
                                                  scad.make_connector_ref_rconnectorref("shaft", "axis"))
    bearing = scad.ground_component_rassembly(assembly=bearing, component_id="outer_ring")
    bearing = scad.solve_assembly_constraints_rassembly(bearing, strict=False)
    assert scad.measure_constraint_residual_rconstraintresidual(bearing, "shaft_to_inner_ring").within_tolerance


def test_bearing_module_surface():
    assert scad.std.bearing.__all__ == ("make_ball_bearing_rassembly",)
    assert isinstance(scad.std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5), scad.Assembly)
