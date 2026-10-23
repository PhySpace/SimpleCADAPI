"""The assembly constraint solver against the reference: placements, residuals, reports, failures."""

import pytest

import simplecadapi._cpp as scad
from product_support import parity


def test_fixed_constraint_places_the_follower():
    parity("solve_fixed", """
        part = axis_part("p")
        assembly = add(add(scad.make_assembly_rassembly("fixed_asm"), part, "base", (1.0, 2.0, 3.0)), part, "follower")
        assembly = scad.ground_component_rassembly(assembly, "base")
        assembly = scad.add_fixed_constraint_rassembly(assembly, "fixed", ref("base"), ref("follower"))
        solved = scad.solve_assembly_constraints_rassembly(assembly)
        residual = scad.measure_constraint_residual_rconstraintresidual(solved, "fixed")
        report = scad.inspect_assembly_constraints_rconstraintreport(solved)
        result = {
            "solved": solved_summary(solved),
            "residual": residual.to_dict(),
            "report": report.to_dict(),
            "report_fields": [report.solved, list(report.grounded_component_ids), list(report.solved_component_ids),
                              list(report.unsolved_component_ids), len(report.residuals)],
            "unsolved_report": scad.inspect_assembly_constraints_rconstraintreport(assembly).to_dict(),
        }
    """)


def test_face_connectors_drive_fixed_revolute_and_prismatic_joints():
    parity("solve_joints", """
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        part = scad.add_connector_rpart(
            scad.make_part_rpart("constraint_part", box), scad.make_face_connector_rconnector("axis", top_face(box)))

        def pair(other):
            assembly = add(add(scad.make_assembly_rassembly("pair"), part, "base"), part, other)
            return scad.ground_component_rassembly(assembly, "base")

        fixed = scad.add_fixed_constraint_rassembly(pair("follower"), "fixed", ref("base"), ref("follower"))
        hinge = scad.add_revolute_constraint_rassembly(pair("arm"), "hinge", ref("base"), ref("arm"), drive_angle_degrees=90.0)
        slide = scad.add_prismatic_constraint_rassembly(pair("slider"), "slide", ref("base"), ref("slider"), drive_distance=5.0)
        reverse = scad.add_prismatic_constraint_rassembly(pair("slider"), "slide", ref("slider"), ref("base"), drive_distance=5.0)
        result = {name: solved_summary(scad.solve_assembly_constraints_rassembly(asm))
                  for name, asm in (("fixed", fixed), ("hinge", hinge), ("slide", slide), ("reverse", reverse))}
    """, abs_=1e-9)


def test_limits_clamp_and_project():
    parity("solve_limits", """
        part = axis_part("p")

        def pair(other, origin=None):
            assembly = add(add(scad.make_assembly_rassembly("pair"), part, "base", origin), part, other)
            return scad.ground_component_rassembly(assembly, "base")

        limit = scad.make_scalar_limit_rscalarlimit
        clamp_high = scad.add_prismatic_constraint_rassembly(
            pair("slider"), "slide", ref("base"), ref("slider"), drive_distance=100.0, distance_limit=limit(0.0, 5.0))
        in_range = scad.add_prismatic_constraint_rassembly(
            pair("slider"), "slide", ref("base"), ref("slider"), drive_distance=3.0, distance_limit=limit(0.0, 10.0))
        clamp_angle = scad.add_revolute_constraint_rassembly(
            pair("arm"), "hinge", ref("base"), ref("arm"), drive_angle_degrees=999.0, angle_limit=limit(0.0, 45.0))
        projected = scad.add_prismatic_constraint_rassembly(
            pair("slider", (0.0, 0.0, 9.0)), "slide", ref("base"), ref("slider"), distance_limit=limit(-5.0, 5.0))
        undriven = scad.add_revolute_constraint_rassembly(
            pair("arm"), "hinge", ref("base"), ref("arm"), angle_limit=limit(0.0, 90.0))
        result = {name: solved_summary(scad.solve_assembly_constraints_rassembly(asm, strict=False))
                  for name, asm in (("clamp_high", clamp_high), ("in_range", in_range), ("clamp_angle", clamp_angle),
                                    ("projected", projected), ("undriven", undriven))}
    """)


def test_gear_belt_and_rack_pinion_couplings():
    parity("solve_couplings", """
        part = axis_part("rotor")

        def rotors(asm_id, ids):
            assembly = scad.make_assembly_rassembly(asm_id)
            for component in ids:
                assembly = add(assembly, part, component)
            return scad.ground_component_rassembly(assembly, "base")

        def joints(assembly):
            assembly = scad.add_revolute_constraint_rassembly(assembly, "drive_a", ref("base"), ref("gear_a"), drive_angle_degrees=90.0)
            return scad.add_revolute_constraint_rassembly(assembly, "free_b", ref("base"), ref("gear_b"))

        gear = scad.add_gear_constraint_rassembly(
            joints(rotors("gear_asm", ("base", "gear_a", "gear_b"))), "mesh", ref("gear_a"), ref("gear_b"),
            pitch_radius_a=1.0, pitch_radius_b=2.0)
        belt = scad.add_belt_constraint_rassembly(
            joints(rotors("belt_asm", ("base", "gear_a", "gear_b"))), "belt", ref("gear_a"), ref("gear_b"),
            pulley_radius_a=1.0, pulley_radius_b=2.0)

        rack = rotors("rack_asm", ("base", "rack", "pinion"))
        rack = scad.add_prismatic_constraint_rassembly(rack, "rack_slide", ref("base"), ref("rack"))
        rack = scad.add_revolute_constraint_rassembly(rack, "pinion_axis", ref("base"), ref("pinion"), drive_angle_degrees=90.0)
        rack = scad.add_rack_pinion_constraint_rassembly(rack, "rack_mesh", ref("rack"), ref("pinion"), pitch_radius=2.0)

        # The other joint driven instead: the coupling sets the first.
        reverse = scad.add_revolute_constraint_rassembly(
            scad.add_revolute_constraint_rassembly(
                rotors("rev_asm", ("base", "gear_a", "gear_b")), "free_a", ref("base"), ref("gear_a")),
            "drive_b", ref("base"), ref("gear_b"), drive_angle_degrees=40.0)
        reverse = scad.add_gear_constraint_rassembly(reverse, "mesh", ref("gear_a"), ref("gear_b"), 3.0, 1.5, phase_offset=0.25)

        solved = {name: scad.solve_assembly_constraints_rassembly(asm)
                  for name, asm in (("gear", gear), ("belt", belt), ("rack", rack), ("reverse", reverse))}
        result = {name: solved_summary(asm) for name, asm in solved.items()}
        result["residuals"] = {
            "gear": scad.measure_constraint_residual_rconstraintresidual(solved["gear"], "mesh").to_dict(),
            "belt": scad.measure_constraint_residual_rconstraintresidual(solved["belt"], "belt").to_dict(),
            "rack": scad.measure_constraint_residual_rconstraintresidual(solved["rack"], "rack_mesh").to_dict(),
            "reverse": scad.measure_constraint_residual_rconstraintresidual(solved["reverse"], "mesh").to_dict(),
        }
        result["phases"] = {
            "gear": solved["gear"].get_constraint("mesh").phase_offset,
            "belt": solved["belt"].get_constraint("belt").phase_offset,
            "rack": solved["rack"].get_constraint("rack_mesh").phase_offset,
            "reverse": solved["reverse"].get_constraint("mesh").phase_offset,
        }
        result["angles"] = {"gear_b": z_angle(solved["gear"].get_component("gear_b").placement),
                            "belt_b": z_angle(solved["belt"].get_component("gear_b").placement),
                            "rack_z": solved["rack"].get_component("rack").placement.origin[2]}
    """)


def test_a_coupling_without_supports_has_the_unmeasurable_residual():
    parity("solve_unsupported_coupling", """
        part = axis_part("p")
        assembly = add(add(scad.make_assembly_rassembly("lonely"), part, "a"), part, "b")
        assembly = scad.add_gear_constraint_rassembly(assembly, "mesh", ref("a"), ref("b"), 1.0, 1.0)
        result = {
            "phase": assembly.get_constraint("mesh").phase_offset,
            "residual": scad.measure_constraint_residual_rconstraintresidual(assembly, "mesh").to_dict(),
            "report": scad.inspect_assembly_constraints_rconstraintreport(assembly).to_dict(),
            "unknown": failure(lambda: scad.measure_constraint_residual_rconstraintresidual(assembly, "ghost")),
            "bad_assembly": failure(lambda: scad.inspect_assembly_constraints_rconstraintreport(part)),
        }
    """)


def test_nested_public_connectors_solve_at_the_parent():
    parity("solve_nested", """
        inner_part = axis_part("public_inner_part", (2.0, 0.0, 0.0))
        base_part = axis_part("public_base_part")
        child = add(scad.make_assembly_rassembly("public_child"), inner_part, "inner", (5.0, 0.0, 0.0))
        child = scad.set_public_connector_rassembly(child, "public_axis", "inner", "axis")
        root = add(scad.make_assembly_rassembly("public_root"), base_part, "base", (10.0, 0.0, 0.0))
        root = scad.add_component_rassembly(root, child, "child", scad.identity_placement_rplacement())
        root = scad.ground_component_rassembly(root, "base")
        root = scad.add_fixed_constraint_rassembly(root, "bind_public_axis", ref("base"), ref("child", "public_axis"))
        solved = scad.solve_assembly_constraints_rassembly(root)

        ring = axis_part("nested_bearing_ring")
        bearing = scad.make_assembly_rassembly("nested_bearing")
        bearing = add(add(bearing, ring, "outer_ring"), ring, "inner_ring")
        bearing = scad.ground_component_rassembly(bearing, "outer_ring")
        bearing = scad.add_revolute_constraint_rassembly(bearing, "inner_outer_revolute", ref("outer_ring"), ref("inner_ring"))
        bearing = scad.set_public_connector_rassembly(bearing, "outer_axis", "outer_ring", "axis")
        bearing = scad.set_public_connector_rassembly(bearing, "inner_axis", "inner_ring", "axis")
        quarter_turn = scad.make_placement_rplacement((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
        fixture = scad.make_assembly_rassembly("nested_bearing_fixture")
        fixture = add(fixture, ring, "housing")
        fixture = scad.add_component_rassembly(fixture, ring, "shaft", quarter_turn)
        fixture = add(fixture, bearing, "bearing")
        fixture = scad.ground_component_rassembly(scad.ground_component_rassembly(fixture, "housing"), "shaft")
        fixture = scad.add_fixed_constraint_rassembly(fixture, "outer_ring_to_housing", ref("housing"), ref("bearing", "outer_axis"))
        fixture = scad.add_fixed_constraint_rassembly(fixture, "inner_ring_to_shaft", ref("shaft"), ref("bearing", "inner_axis"))
        closed = scad.solve_assembly_constraints_rassembly(fixture)
        nested = closed.get_component("bearing").item
        result = {
            "public": solved_summary(solved),
            "closed": solved_summary(closed),
            "nested_placements": placements(nested),
        }
    """)


def test_a_residual_failure_is_structured():
    parity("solve_residual_failure", """
        base = scad.add_connector_rpart(axis_part("base_part"), scad.make_placement_connector_rconnector(
            "far", scad.make_placement_rplacement(origin=(15.0, 0.0, 0.0))))
        moving = axis_part("moving_part", (5.0, 0.0, 0.0))
        assembly = add(add(scad.make_assembly_rassembly("residual_fixture"), base, "base"), moving, "moving")
        assembly = scad.ground_component_rassembly(assembly, "base")
        assembly = scad.add_fixed_constraint_rassembly(assembly, "hold", ref("base"), ref("moving"))
        assembly = scad.add_fixed_constraint_rassembly(assembly, "hold2", ref("base", "far"), ref("moving"))
        lenient = scad.solve_assembly_constraints_rassembly(assembly, strict=False)
        result = {
            "failure": failure(lambda: scad.solve_assembly_constraints_rassembly(assembly)),
            "lenient": solved_summary(lenient),
        }
    """)


def test_structural_failures_carry_the_connectivity_verdict():
    parity("solve_structural_failure", """
        part = axis_part("p")
        assembly = scad.make_assembly_rassembly("structural_fixture")
        for component in ("base", "floating", "island"):
            assembly = add(assembly, part, component)
        assembly = scad.ground_component_rassembly(assembly, "base")
        assembly = scad.add_revolute_constraint_rassembly(assembly, "link", ref("base"), ref("floating"))

        unreachable = scad.make_assembly_rassembly("unreachable")
        for component in ("base", "x", "y"):
            unreachable = add(unreachable, part, component)
        unreachable = scad.ground_component_rassembly(unreachable, "base")
        unreachable = scad.add_fixed_constraint_rassembly(unreachable, "orphan", ref("x"), ref("y"))

        ungrounded = scad.add_prismatic_constraint_rassembly(
            add(add(scad.make_assembly_rassembly("ungrounded_asm"), part, "base"), part, "slider"),
            "slide_ungrounded", ref("base"), ref("slider"), drive_distance=1.0)
        result = {
            "island": failure(lambda: scad.solve_assembly_constraints_rassembly(assembly)),
            "island_lenient": solved_summary(scad.solve_assembly_constraints_rassembly(assembly, strict=False)),
            "orphan": failure(lambda: scad.solve_assembly_constraints_rassembly(unreachable)),
            "orphan_lenient": solved_summary(scad.solve_assembly_constraints_rassembly(unreachable, strict=False)),
            "ungrounded": failure(lambda: scad.solve_assembly_constraints_rassembly(ungrounded)),
            "not_an_assembly": failure(lambda: scad.solve_assembly_constraints_rassembly(part)),
            "no_constraints": scad.solve_assembly_constraints_rassembly(add(scad.make_assembly_rassembly("plain"), part, "only")).to_dict(),
        }
    """)


def test_solving_is_idempotent():
    parity("solve_twice", """
        part = axis_part("p")
        assembly = add(add(scad.make_assembly_rassembly("twice"), part, "base", (1.0, 0.0, 0.0)), part, "arm")
        assembly = scad.ground_component_rassembly(assembly, "base")
        assembly = scad.add_revolute_constraint_rassembly(assembly, "hinge", ref("base"), ref("arm"), drive_angle_degrees=33.0)
        once = scad.solve_assembly_constraints_rassembly(assembly)
        again = scad.solve_assembly_constraints_rassembly(once)
        result = {"once": solved_summary(once), "again": solved_summary(again)}
    """)


def test_solved_report_is_a_runtime_value_of_the_result():
    part = scad.add_connector_rpart(
        scad.make_part_rpart("p", scad.make_box_rsolid(1, 1, 1)),
        scad.make_placement_connector_rconnector("axis", scad.make_placement_rplacement((0, 0, 0))),
    )
    assembly = scad.make_assembly_rassembly("a")
    for name in ("base", "slider"):
        assembly = scad.add_component_rassembly(assembly, part, name, scad.identity_placement_rplacement())
    assembly = scad.ground_component_rassembly(assembly, "base")
    assembly = scad.add_prismatic_constraint_rassembly(
        assembly,
        "slide",
        scad.make_connector_ref_rconnectorref("base", "axis"),
        scad.make_connector_ref_rconnectorref("slider", "axis"),
        drive_distance=4.0,
    )
    assert assembly._get_runtime("constraint_report") is None
    solved = scad.solve_assembly_constraints_rassembly(assembly)
    assert solved._get_runtime("constraint_report")["solved"] is True
    assert solved.get_component("slider").placement.origin == (0.0, 0.0, 4.0)
    # Editing the result's components starts a fresh runtime.
    assert solved.with_component_placement("slider", scad.Placement((0, 0, 0)))._get_runtime("constraint_report") is None
    assert solved.with_constraint(
        scad.Constraint("c2", "fixed", scad.ConnectorRef("base", "axis"), scad.ConnectorRef("slider", "axis"))
    )._get_runtime("assembly.authored_component_placements") is not None
