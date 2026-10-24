"""What the product operators record in a GraphSession, and how the reactive engine treats them."""

import pytest

import simplecadapi._cpp as scad
from simplecadapi._glue.session import GraphSession
from product_support import parity

FACTS = """
PRODUCT_OPS = ("_rmaterial", "_rplacement", "_rpart", "_rassembly", "_rconnector", "_rconnectorref", "_rscalarlimit")


def graph_facts(session):
    facts = []
    for n in session.graph.nodes:
        if not n.op.endswith(PRODUCT_OPS):
            continue
        params = {k: v for k, v in n.params.items() if k != "input_refs"}
        if "geometry_ref" in params:
            params["geometry_ref"] = {k: v for k, v in params["geometry_ref"].items() if k != "source_node_id"}
            params["anchor"]["geometry_ref"].pop("source_node_id")
        facts.append({"op": n.op, "params": params})
    return facts
"""


def test_product_operations_record_their_parameters():
    parity("graph_records", """
        exec(FACTS_SOURCE)
        with scad.GraphSession() as session:
            body = scad.make_box_rsolid(2.0, 3.0, 1.0)
            material = scad.make_material_rmaterial("steel_8_8", density=7.85e-6, density_unit="kg/mm^3")
            part = scad.assign_material_rpart(scad.make_part_rpart("plate", body, name="Plate"), material)
            part = scad.add_connector_rpart(part, scad.make_face_connector_rconnector("top", top_face(body)))
            part = scad.add_connector_rpart(part, scad.make_placement_connector_rconnector(
                "axis", scad.make_placement_rplacement((0.0, 1.0, 2.0))))
            assembly = scad.make_assembly_rassembly("fixture")
            assembly = scad.add_component_rassembly(assembly, part, "plate_1", scad.identity_placement_rplacement())
            assembly = scad.add_component_rassembly(assembly, part, "plate_2", scad.make_placement_rplacement((5.0, 0.0, 0.0)))
            assembly = scad.place_component_rassembly(assembly, "plate_2", scad.make_placement_rplacement((6.0, 0.0, 0.0)))
            assembly = scad.ground_component_rassembly(assembly, "plate_1")
            assembly = scad.set_public_connector_rassembly(assembly, "pub", "plate_1", "axis")
            limit = scad.make_scalar_limit_rscalarlimit(0.0, 10.0)
            assembly = scad.add_prismatic_constraint_rassembly(
                assembly, "slide", ref("plate_1", "axis"), ref("plate_2", "axis"), drive_distance=4.0, distance_limit=limit)
            assembly = scad.add_gear_constraint_rassembly(
                assembly, "mesh", ref("plate_1", "axis"), ref("plate_2", "axis"), 1.0, 2.0, 0.5)
            assembly = scad.unground_component_rassembly(assembly, "plate_1")
            assembly = scad.ground_component_rassembly(assembly, "plate_1")
            solved = scad.solve_assembly_constraints_rassembly(assembly, strict=False)
            compound = scad.make_compound_from_assembly_rcompound(solved)
        all_ops = [n.op for n in session.graph.nodes if n.op.endswith(PRODUCT_OPS + ("_rsolid",)) or n.op.startswith("make_")]
        result = {"graph": graph_facts(session),
                  "all_ops": [op for op in all_ops if "select" not in op],
                  "compound_volume": compound.get_volume()}
    """.replace("FACTS_SOURCE", repr(FACTS)), ignore=())


def test_duplicate_ids_are_rejected_inside_a_session():
    parity("graph_duplicate_ids", """
        def twice(make):
            try:
                with scad.GraphSession():
                    make()
                    make()
            except scad.SimpleCADError as error:
                return {"operation": error.operation, "details": error.to_dict()["technical_details"]}
            return None

        box = scad.make_box_rsolid(1, 1, 1)
        result = {
            "part": twice(lambda: scad.make_part_rpart("same_part", box)),
            "assembly": twice(lambda: scad.make_assembly_rassembly("same")),
            "material": twice(lambda: scad.make_material_rmaterial("same")),
            "outside_a_session": scad.make_part_rpart("same_part", box).part_id == scad.make_part_rpart("same_part", box).part_id,
        }
    """)


def test_recompute_passes_through_product_operations():
    session = GraphSession()
    with session:
        width = scad.Var("w", 2.0) if hasattr(scad, "Var") else None
        if width is None:
            pytest.skip("no Var in this build")
        body = scad.make_box_rsolid(width, 1.0, 1.0)
        part = scad.make_part_rpart("plate", body)
        assert part.part_id == "plate"
    session.set_var("w", 5.0)
    report = session.recompute()
    assert report.ok
    box = session.graph.nodes[0]
    assert session.output(box.node_id).get_volume() == pytest.approx(5.0)
