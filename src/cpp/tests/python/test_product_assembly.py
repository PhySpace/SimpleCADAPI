"""Assembly structure, constraints (construction) and projection against the reference."""

import pytest

import simplecadapi._cpp as scad
from product_support import parity


def test_components_are_added_and_placed():
    parity("assembly_components", """
        bolt = scad.make_part_rpart("bolt", scad.make_cylinder_rsolid(1.0, 2.0))
        empty = scad.make_assembly_rassembly("fixture", name=" Fixture ")
        assembly = add(add(empty, bolt, "bolt_left", (-5.0, 0.0, 0.0)), bolt, "bolt_right", (5.0, 0.0, 0.0))
        moved = scad.place_component_rassembly(assembly, "bolt_left", scad.make_placement_rplacement((-9.0, 0.0, 0.0)))
        result = {
            "empty": empty.to_dict(),
            "assembly": assembly.to_dict(),
            "ids": list(assembly.component_ids()),
            "moved": moved.to_dict(),
            "original_unmoved": assembly.get_component("bolt_left").placement.to_dict(),
            "named": scad.add_component_rassembly(
                empty, bolt, "named", scad.identity_placement_rplacement(), name=" Nut ").to_dict(),
        }
    """)


def test_assembly_failures():
    parity("assembly_failures", """
        body = scad.make_box_rsolid(1.0, 1.0, 1.0)
        part = scad.make_part_rpart("box_part", body)
        placement = scad.identity_placement_rplacement()
        assembly = scad.add_component_rassembly(scad.make_assembly_rassembly("root"), part, "box", placement)
        child = scad.add_component_rassembly(scad.make_assembly_rassembly("child"), assembly, "parent_instance", placement)
        result = {
            "duplicate": failure(lambda: scad.add_component_rassembly(assembly, part, "box", placement)),
            "raw_solid": failure(lambda: scad.add_component_rassembly(assembly, body, "raw", placement)),
            "cycle": failure(lambda: scad.add_component_rassembly(assembly, child, "child_instance", placement)),
            "bad_assembly": failure(lambda: scad.add_component_rassembly(part, part, "x", placement)),
            "bad_placement": failure(lambda: scad.add_component_rassembly(assembly, part, "x", (0, 0, 0))),
            "bad_id": failure(lambda: scad.add_component_rassembly(assembly, part, "1x", placement)),
            "place_missing": failure(lambda: scad.place_component_rassembly(assembly, "ghost", placement)),
            "place_bad_assembly": failure(lambda: scad.place_component_rassembly(None, "box", placement)),
            "bad_assembly_id": failure(lambda: scad.make_assembly_rassembly("bad id")),
            "get_component_missing": failure(lambda: assembly.get_component("ghost")),
        }
    """)


def test_grounding():
    parity("assembly_grounding", """
        part = axis_part("p")
        assembly = add(add(scad.make_assembly_rassembly("g"), part, "base"), part, "other")
        grounded = scad.ground_component_rassembly(assembly, "base")
        twice = scad.ground_component_rassembly(grounded, "base")
        both = scad.ground_component_rassembly(twice, "other")
        result = {
            "grounded": list(grounded.grounded_component_ids),
            "twice": list(twice.grounded_component_ids),
            "both": list(both.grounded_component_ids),
            "ungrounded": list(scad.unground_component_rassembly(both, "base").grounded_component_ids),
            "to_dict": both.to_dict(),
            "ground_missing": failure(lambda: scad.ground_component_rassembly(assembly, "ghost")),
            "unground_missing": failure(lambda: scad.unground_component_rassembly(assembly, "ghost")),
            "ground_bad_assembly": failure(lambda: scad.ground_component_rassembly(part, "base")),
        }
    """)


def test_public_connectors():
    parity("assembly_public_connectors", """
        inner = axis_part("public_inner_part", (2.0, 0.0, 0.0))
        child = add(scad.make_assembly_rassembly("public_child"), inner, "inner", (5.0, 0.0, 0.0))
        child = scad.set_public_connector_rassembly(
            child, public_connector_id="public_axis", source_component_id="inner", source_connector_id="axis", name="Axis")
        result = {
            "child": child.to_dict(),
            "ids": list(child.public_connector_ids()),
            "public": child.get_public_connector("public_axis").to_dict(),
            "missing_component": failure(lambda: scad.set_public_connector_rassembly(child, "other", "ghost", "axis")),
            "missing_connector": failure(lambda: scad.set_public_connector_rassembly(child, "other", "inner", "ghost")),
            "duplicate": failure(lambda: scad.set_public_connector_rassembly(child, "public_axis", "inner", "axis")),
            "bad_assembly": failure(lambda: scad.set_public_connector_rassembly(inner, "p", "inner", "axis")),
            "missing_public": failure(lambda: child.get_public_connector("ghost")),
        }
    """)


def test_constraint_construction():
    parity("constraints_construction", """
        part = axis_part("p")
        assembly = add(add(scad.make_assembly_rassembly("c"), part, "a"), part, "b")
        a, b = ref("a"), ref("b")
        limit = scad.make_scalar_limit_rscalarlimit(0.0, 90.0)
        built = scad.add_fixed_constraint_rassembly(assembly, "f", a, b, name=" Weld ")
        built = scad.add_revolute_constraint_rassembly(built, "r", a, b, drive_angle_degrees=30.0, angle_limit=limit)
        built = scad.add_prismatic_constraint_rassembly(built, "p", a, b, drive_distance=2.0, distance_limit=limit)
        built = scad.add_gear_constraint_rassembly(built, "g", a, b, 1.0, 2.0, phase_offset=0.5)
        built = scad.add_belt_constraint_rassembly(built, "t", a, b, pulley_radius_a=3.0, pulley_radius_b=4.0)
        built = scad.add_rack_pinion_constraint_rassembly(built, "k", a, b, pitch_radius=2.0, phase_offset=1.0)
        result = {
            "assembly": built.to_dict(),
            "ids": list(built.constraint_ids()),
            "constraint": built.get_constraint("g").to_dict(),
            "equal": built.get_constraint("f") == built.get_constraint("f"),
        }
    """)


def test_constraint_failures():
    parity("constraints_failures", """
        part = axis_part("p")
        assembly = add(add(scad.make_assembly_rassembly("c"), part, "a"), part, "b")
        a, b, ghost = ref("a"), ref("b"), ref("b", "ghost")
        limit = scad.make_scalar_limit_rscalarlimit(0.0, 1.0)
        fixed = scad.add_fixed_constraint_rassembly(assembly, "f", a, b)
        result = {
            "missing_connector": failure(lambda: scad.add_fixed_constraint_rassembly(assembly, "m", a, ghost)),
            "duplicate_id": failure(lambda: scad.add_fixed_constraint_rassembly(fixed, "f", a, b)),
            "bad_assembly": failure(lambda: scad.add_fixed_constraint_rassembly(part, "x", a, b)),
            "same_ref": failure(lambda: scad.add_fixed_constraint_rassembly(assembly, "x", a, a)),
            "bad_ref": failure(lambda: scad.add_fixed_constraint_rassembly(assembly, "x", "a", b)),
            "revolute_distance_limit": failure(lambda: scad.add_revolute_constraint_rassembly(assembly, "x", a, b, angle_limit=3)),
            "gear_zero": failure(lambda: scad.add_gear_constraint_rassembly(assembly, "x", a, b, 0.0, 1.0)),
            "belt_negative": failure(lambda: scad.add_belt_constraint_rassembly(assembly, "x", a, b, 1.0, -1.0)),
            "rack_zero": failure(lambda: scad.add_rack_pinion_constraint_rassembly(assembly, "x", a, b, 0.0)),
            "gear_bad_assembly": failure(lambda: scad.add_gear_constraint_rassembly(part, "x", a, b, 1.0, 1.0, 0.0)),
            "limit_ok": scad.add_prismatic_constraint_rassembly(assembly, "x", a, b, 1.0, limit).get_constraint("x").to_dict(),
        }
    """)


def test_constraint_class_rules():
    parity("constraints_class_rules", """
        a, b = ref("a"), ref("b")
        limit = scad.ScalarLimit(0.0, 1.0)
        result = {
            "fixed_drive": failure(lambda: scad.Constraint("c", "fixed", a, b, drive_distance=1.0)),
            "fixed_limit": failure(lambda: scad.Constraint("c", "fixed", a, b, angle_limit=limit)),
            "revolute_distance": failure(lambda: scad.Constraint("c", "revolute", a, b, drive_distance=1.0)),
            "prismatic_angle": failure(lambda: scad.Constraint("c", "prismatic", a, b, drive_angle_degrees=1.0)),
            "prismatic_radius": failure(lambda: scad.Constraint("c", "prismatic", a, b, pitch_radius=1.0)),
            "gear_missing": failure(lambda: scad.Constraint("c", "gear", a, b, pitch_radius_a=1.0)),
            "gear_extra": failure(lambda: scad.Constraint("c", "gear", a, b, pitch_radius_a=1.0, pitch_radius_b=1.0, pitch_radius=1.0)),
            "gear_drive": failure(lambda: scad.Constraint("c", "gear", a, b, pitch_radius_a=1.0, pitch_radius_b=1.0, drive_angle_degrees=1.0)),
            "belt_missing": failure(lambda: scad.Constraint("c", "belt", a, b)),
            "belt_extra": failure(lambda: scad.Constraint("c", "belt", a, b, pulley_radius_a=1.0, pulley_radius_b=1.0, pitch_radius_a=1.0)),
            "rack_missing": failure(lambda: scad.Constraint("c", "rack_pinion", a, b)),
            "rack_extra": failure(lambda: scad.Constraint("c", "rack_pinion", a, b, pitch_radius=1.0, pulley_radius_a=1.0)),
            "unknown_kind": failure(lambda: scad.Constraint("c", "weld", a, b)),
            "same_ref": failure(lambda: scad.Constraint("c", "fixed", a, a)),
            "bad_a": failure(lambda: scad.Constraint("c", "fixed", "a", b)),
            "nan_drive": failure(lambda: scad.Constraint("c", "revolute", a, b, drive_angle_degrees=float("nan"))),
            "kind_is_normalised": scad.Constraint("c", " GEAR ", a, b, pitch_radius_a=1.0, pitch_radius_b=2.0).to_dict(),
        }
    """)


def test_projection_to_a_compound():
    parity("projection", """
        body = scad.make_cylinder_rsolid(1.0, 2.0)
        bolt = scad.make_part_rpart("bolt", body)
        assembly = add(add(scad.make_assembly_rassembly("fixture"), bolt, "left", (-5.0, 0.0, 0.0)), bolt, "right", (5.0, 0.0, 0.0))
        compound = scad.make_compound_from_assembly_rcompound(assembly)
        child = add(scad.make_assembly_rassembly("child_assembly"), scad.make_part_rpart("cube", scad.make_box_rsolid(1.0, 1.0, 1.0)), "cube", (2.0, 0.0, 0.0))
        root = scad.add_component_rassembly(scad.make_assembly_rassembly("root_assembly"), child, "child", scad.make_placement_rplacement((10.0, 0.0, 0.0)))
        nested = scad.make_compound_from_assembly_rcompound(root)
        result = {
            "volume": compound.get_volume(),
            "single_volume": body.get_volume(),
            "centers": solid_centers(compound),
            "projection": compound.get_metadata("assembly_projection"),
            "nested_volume": nested.get_volume(),
            "nested_centers": solid_centers(nested),
            "nested_projection": nested.get_metadata("assembly_projection"),
            "empty": failure(lambda: scad.make_compound_from_assembly_rcompound(scad.make_assembly_rassembly("empty"))),
            "not_assembly": failure(lambda: scad.make_compound_from_assembly_rcompound(bolt)),
        }
    """)


def test_solids_of_the_projection():
    bolt = scad.make_part_rpart("bolt", scad.make_cylinder_rsolid(1.0, 2.0))
    assembly = scad.make_assembly_rassembly("fixture")
    for name, x in (("left", -5.0), ("right", 5.0)):
        assembly = scad.add_component_rassembly(assembly, bolt, name, scad.make_placement_rplacement((x, 0.0, 0.0)))
    assert len(scad.make_compound_from_assembly_rcompound(assembly).solids()) == 2
    # Components keep the identity of their item.
    assert assembly.get_component("left").item is bolt


def test_python_object_identity_of_nested_items():
    ring = scad.make_part_rpart("ring", scad.make_box_rsolid(1, 1, 1))
    inner = scad.add_component_rassembly(scad.make_assembly_rassembly("inner"), ring, "ring", scad.identity_placement_rplacement())
    outer = scad.add_component_rassembly(scad.make_assembly_rassembly("outer"), inner, "inner", scad.identity_placement_rplacement())
    assert outer.get_component("inner").item is inner
    assert outer.components[0].item.components[0].item is ring


def test_value_classes_are_exported_with_their_python_names():
    for name in ("Part", "Assembly", "Component", "PublicConnectorRef", "Connector", "ConnectorAnchor", "ConnectorRef",
                 "GeometryRef", "Constraint", "ConstraintReport", "ConstraintResidual", "ScalarLimit", "Material", "Placement"):
        assert isinstance(getattr(scad, name), type), name
