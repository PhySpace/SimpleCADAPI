"""Tests for the standard-parts library bearing assemblies."""

import inspect
import json
import unittest

import simplecadapi as scad


class TestStdBearingSurface(unittest.TestCase):
    def test_preferred_nested_std_export_surface(self):
        assembly = scad.std.bearing.make_ball_bearing_rassembly(
            8.0,
            22.0,
            7.0,
            3.5,
            7,
            0.05,
            0.0,
            "bearing_surface_test",
        )

        self.assertIsInstance(assembly, scad.Assembly)

    def test_public_bearing_factories_follow_naming(self):
        factory_names = [
            name
            for name in scad.std.bearing.__all__
            if callable(getattr(scad.std.bearing, name, None))
        ]

        self.assertGreater(len(factory_names), 0)
        for name in factory_names:
            self.assertTrue(
                name.startswith("make_") or name.startswith("build_"), name
            )
            if name.startswith("make_"):
                self.assertIn("_r", name, name)

    def test_ball_bearing_signature_has_no_keyword_only_separator(self):
        signature = inspect.signature(scad.std.bearing.make_ball_bearing_rassembly)

        self.assertNotIn(
            inspect.Parameter.KEYWORD_ONLY,
            {parameter.kind for parameter in signature.parameters.values()},
        )


class TestBallBearingAssembly(unittest.TestCase):
    def test_basic_ball_bearing_assembly(self):
        with scad.GraphSession() as session:
            bearing = scad.std.bearing.make_ball_bearing_rassembly(
                8.0,
                22.0,
                7.0,
                3.5,
                7,
                0.05,
                0.05,
                "bearing_basic_test",
                30.0,
            )
            preview = scad.make_compound_from_assembly_rcompound(bearing)
            model_json = scad.export_model_json(session)

        meta = bearing.get_metadata("std.bearing.ball_bearing")
        self.assertEqual(meta["ball_count"], 7)
        self.assertEqual(meta["outer_component_id"], "outer_ring")
        self.assertEqual(meta["inner_component_id"], "inner_ring")
        self.assertEqual(len(meta["ball_component_ids"]), 7)
        self.assertIn("ball_00", meta["ball_component_ids"])

        self.assertEqual(
            bearing.component_ids(),
            (
                "outer_ring",
                "inner_ring",
                "ball_00",
                "ball_01",
                "ball_02",
                "ball_03",
                "ball_04",
                "ball_05",
                "ball_06",
            ),
        )
        self.assertEqual(bearing.constraint_ids(), ("inner_outer_revolute",))
        self.assertEqual(bearing.public_connector_ids(), ("outer_axis", "inner_axis"))
        self.assertEqual(bearing.grounded_component_ids, ())
        constraint = bearing.get_constraint("inner_outer_revolute")
        self.assertEqual(constraint.constraint_kind, "revolute")
        self.assertEqual(constraint.connector_a.component_id, "outer_ring")
        self.assertEqual(constraint.connector_b.component_id, "inner_ring")
        self.assertEqual(constraint.connector_a.connector_id, "axis")
        self.assertEqual(constraint.connector_b.connector_id, "axis")
        self.assertEqual(constraint.drive_angle_degrees, 30.0)

        outer_part = bearing.get_component("outer_ring").item
        inner_part = bearing.get_component("inner_ring").item
        ball_part = bearing.get_component("ball_00").item
        self.assertEqual(outer_part.connector_ids(), ("axis",))
        self.assertEqual(inner_part.connector_ids(), ("axis",))
        self.assertEqual(ball_part.connector_ids(), ())
        self.assertGreater(outer_part.body.get_volume(), 0.0)
        self.assertGreater(inner_part.body.get_volume(), 0.0)

        outer_ring_meta = outer_part.body.get_metadata("std.bearing.ring")
        inner_ring_meta = inner_part.body.get_metadata("std.bearing.ring")
        ball_radius = meta["ball_diameter"] / 2.0
        self.assertAlmostEqual(
            outer_ring_meta["inner_radius"],
            meta["ball_pitch_radius"] + ball_radius * 0.75,
        )
        self.assertAlmostEqual(
            inner_ring_meta["outer_radius"],
            meta["ball_pitch_radius"] - ball_radius * 0.75,
        )
        self.assertLess(
            outer_ring_meta["raceway_mouth_z"], outer_ring_meta["groove_radius"]
        )
        self.assertLess(
            inner_ring_meta["raceway_mouth_z"], inner_ring_meta["groove_radius"]
        )

        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Sphere, GeomAbs_Torus

        self.assertTrue(
            any(
                BRepAdaptor_Surface(face.wrapped).GetType() == GeomAbs_Torus
                for face in outer_part.body._iter_faces()
            )
        )
        self.assertTrue(
            any(
                BRepAdaptor_Surface(face.wrapped).GetType() == GeomAbs_Torus
                for face in inner_part.body._iter_faces()
            )
        )
        self.assertTrue(
            all(
                BRepAdaptor_Surface(face.wrapped).GetType() == GeomAbs_Sphere
                for face in ball_part.body._iter_faces()
            )
        )

        self.assertEqual(len(preview._iter_solids()), 9)
        self.assertGreater(preview.get_volume(), 0.0)
        self.assertTrue(
            scad.measure_constraint_residual_rconstraintresidual(
                bearing,
                "inner_outer_revolute",
            ).within_tolerance
        )

        payload = json.loads(model_json)
        ops = [node["op"] for node in payload["graph"]["nodes"]]
        self.assertIn("make_sphere_rsolid", ops)
        self.assertEqual(ops.count("make_three_point_arc_redge"), 2)
        self.assertEqual(ops.count("make_revolve_rsolid"), 2)
        self.assertIn("make_revolute_constraint_rassembly", ops)
        self.assertEqual(ops.count("make_set_public_connector_rassembly"), 2)
        self.assertIn("make_compound_from_assembly_rcompound", ops)
        stdlib_nodes = [
            node
            for node in payload["graph"]["nodes"]
            if node["op"] != "make_compound_from_assembly_rcompound"
        ]
        self.assertTrue(all("topo_delta" not in node for node in stdlib_nodes))

    def test_inferred_ball_count_is_recorded(self):
        bearing = scad.std.bearing.make_ball_bearing_rassembly(
            8.0,
            22.0,
            7.0,
            3.5,
        )
        meta = bearing.get_metadata("std.bearing.ball_bearing")

        self.assertGreaterEqual(meta["ball_count"], 3)
        self.assertEqual(len(meta["ball_component_ids"]), meta["ball_count"])

    def test_external_constraints_can_bind_to_internal_connectors(self):
        bearing = scad.std.bearing.make_ball_bearing_rassembly(
            8.0,
            22.0,
            7.0,
            3.5,
            7,
            0.05,
            0.0,
            "bearing_bind_test",
        )

        shaft = scad.make_cylinder_rsolid(
            radius=3.8,
            height=14.0,
            bottom_face_center=(0.0, 0.0, -7.0),
            axis=(0.0, 0.0, 1.0),
        )
        shaft_part = scad.make_part_rpart("shaft", shaft)
        top_face = max(
            shaft._iter_faces(),
            key=lambda face: (
                face.get_center().z if face.get_normal_at().z > 0.7 else -999.0
            ),
        )
        shaft_axis = scad.make_face_connector_rconnector("axis", top_face)
        shaft_part = scad.add_connector_rpart(shaft_part, shaft_axis)
        bearing = scad.add_component_rassembly(
            bearing,
            shaft_part,
            component_id="shaft",
            placement=scad.identity_placement_rplacement(),
        )
        bearing = scad.add_fixed_constraint_rassembly(
            bearing,
            "shaft_to_inner_ring",
            scad.make_connector_ref_rconnectorref("inner_ring", "axis"),
            scad.make_connector_ref_rconnectorref("shaft", "axis"),
        )
        bearing = scad.ground_component_rassembly(
            assembly=bearing,
            component_id="outer_ring",
        )
        bearing = scad.solve_assembly_constraints_rassembly(bearing, strict=False)

        self.assertIn("shaft", bearing.component_ids())
        self.assertTrue(
            scad.measure_constraint_residual_rconstraintresidual(
                bearing,
                "shaft_to_inner_ring",
            ).within_tolerance
        )

    def test_parent_assembly_can_bind_to_bearing_public_connectors(self):
        bearing = scad.std.bearing.make_ball_bearing_rassembly(
            8.0,
            22.0,
            7.0,
            3.5,
            7,
            0.05,
            0.0,
            "bearing_parent_bind_test",
        )
        shaft = scad.make_cylinder_rsolid(
            radius=3.8,
            height=14.0,
            bottom_face_center=(0.0, 0.0, -7.0),
            axis=(0.0, 0.0, 1.0),
        )
        shaft_part = scad.make_part_rpart("parent_bind_shaft", shaft)
        top_face = max(
            shaft._iter_faces(),
            key=lambda face: (
                face.get_center().z if face.get_normal_at().z > 0.7 else -999.0
            ),
        )
        shaft_axis = scad.make_face_connector_rconnector("axis", top_face)
        shaft_part = scad.add_connector_rpart(shaft_part, shaft_axis)
        parent = scad.make_assembly_rassembly("bearing_parent_bind_asm")
        parent = scad.add_component_rassembly(
            parent,
            shaft_part,
            component_id="shaft",
            placement=scad.identity_placement_rplacement(),
        )
        parent = scad.add_component_rassembly(
            parent,
            bearing,
            component_id="bearing",
            placement=scad.identity_placement_rplacement(),
        )
        parent = scad.ground_component_rassembly(parent, "shaft")
        parent = scad.add_fixed_constraint_rassembly(
            parent,
            "shaft_to_bearing_inner_axis",
            scad.make_connector_ref_rconnectorref("shaft", "axis"),
            scad.make_connector_ref_rconnectorref("bearing", "inner_axis"),
        )
        parent = scad.solve_assembly_constraints_rassembly(parent)

        self.assertTrue(
            scad.measure_constraint_residual_rconstraintresidual(
                parent,
                "shaft_to_bearing_inner_axis",
            ).within_tolerance
        )

    def test_durable_bearing_keeps_separate_balls(self):
        bearing = scad.std.bearing.build_ball_bearing(
            bore_diameter=3.2,
            outer_diameter=6.6,
            bearing_width=2.0,
            ball_diameter=0.55,
            ball_count=8,
            raceway_clearance=0.03,
            assembly_id="durable_ball_bearing",
            fuse_rolling_elements=False,
        )
        self.assertEqual(
            sorted(ref.definition_id for ref in bearing.definition.definition_refs),
            [
                "durable_ball_bearing_ball",
                "durable_ball_bearing_inner_ring",
                "durable_ball_bearing_outer_ring",
            ],
        )
        balls = [
            c for c in bearing.assembly.components if c.component_id.startswith("ball_")
        ]
        self.assertEqual(len(balls), 8)
        self.assertEqual({c.item.part_id for c in balls}, {"durable_ball_bearing_ball"})

    def test_durable_bearing_accepts_material_recorded_in_caller_graph(self):
        # A notebook cell records into its own graph; the bearing's rings are
        # recorded in theirs, so the material must cross by value.
        with scad.GraphSession():
            steel = scad.make_material_rmaterial(
                "bearing_steel_in_caller_graph", density=7.85, density_unit="g/cm3"
            )
            bearing = scad.std.bearing.build_ball_bearing(
                bore_diameter=3.0,
                outer_diameter=6.0,
                bearing_width=2.0,
                ball_diameter=0.7,
                ball_count=8,
                assembly_id="caller_graph_material_bearing",
                material=steel,
            )
        outer = bearing.assembly.get_component("outer_ring").item
        self.assertEqual(outer.material.material_id, "bearing_steel_in_caller_graph")

    def test_durable_bearing_definition_supports_external_dual_fixed(self):
        from pathlib import Path

        bearing = scad.std.bearing.build_ball_bearing(
            bore_diameter=8.0,
            outer_diameter=16.0,
            bearing_width=5.0,
            ball_diameter=2.0,
            ball_count=8,
            raceway_clearance=0.0,
            edge_chamfer=0.0,
            assembly_id="durable_std_bearing",
        )
        self.assertEqual(bearing.definition.definition_kind, "assembly")
        self.assertEqual(
            sorted(c.connector_id for c in bearing.definition.public_connectors),
            ["inner_axis", "outer_axis"],
        )
        self.assertEqual(
            [r["constraint_id"] for r in bearing.definition.relations],
            ["inner_outer_revolute"],
        )

        hub = scad.make_part_rpart(
            "durable_hub", scad.make_cylinder_rsolid(radius=10.0, height=5.0)
        )
        hub = scad.add_connector_rpart(
            hub,
            scad.make_placement_connector_rconnector(
                "seat", scad.identity_placement_rplacement()
            ),
        )
        shaft = scad.make_part_rpart(
            "durable_shaft", scad.make_cylinder_rsolid(radius=3.0, height=20.0)
        )
        shaft = scad.add_connector_rpart(
            shaft,
            scad.make_placement_connector_rconnector(
                "axis", scad.identity_placement_rplacement()
            ),
        )

        host = scad.make_assembly_rassembly("durable_bearing_host")
        host = scad.add_component_rassembly(
            host, hub, component_id="hub", placement=scad.identity_placement_rplacement()
        )
        host = scad.add_component_rassembly(
            host,
            shaft,
            component_id="shaft",
            placement=scad.make_placement_rplacement(
                origin=(0.0, 0.0, 0.0), x_axis=(0, 1, 0), y_axis=(-1, 0, 0)
            ),
        )
        host = scad.add_component_rassembly(
            host,
            bearing.value,
            component_id="bearing",
            placement=scad.identity_placement_rplacement(),
        )
        host = scad.ground_component_rassembly(host, "hub")
        host = scad.add_fixed_constraint_rassembly(
            host,
            "bearing_outer",
            scad.make_connector_ref_rconnectorref("hub", "seat"),
            scad.make_connector_ref_rconnectorref("bearing", "outer_axis"),
        )
        host = scad.add_fixed_constraint_rassembly(
            host,
            "bearing_inner",
            scad.make_connector_ref_rconnectorref("shaft", "axis"),
            scad.make_connector_ref_rconnectorref("bearing", "inner_axis"),
        )

        solved = scad.solve_assembly_constraints_rassembly(host)
        report = solved._get_runtime("constraint_report")
        self.assertTrue(report["solved"])
        self.assertTrue(all(r["within_tolerance"] for r in report["residuals"]))
        inner_ring = (
            solved.get_component("bearing").item.get_component("inner_ring")
        )
        shaft_component = solved.get_component("shaft")
        self.assertEqual(inner_ring.placement.x_axis, shaft_component.placement.x_axis)
        self.assertEqual(inner_ring.placement.y_axis, shaft_component.placement.y_axis)

    def test_invalid_params(self):
        with self.assertRaises(Exception):
            scad.std.bearing.make_ball_bearing_rassembly(22.0, 8.0, 7.0, 3.5)
        with self.assertRaises(Exception):
            scad.std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 3.0, 3.5)
        with self.assertRaises(Exception):
            scad.std.bearing.make_ball_bearing_rassembly(8.0, 22.0, 7.0, 8.0)
        with self.assertRaises(Exception):
            scad.std.bearing.make_ball_bearing_rassembly(
                8.0,
                22.0,
                7.0,
                3.5,
                100,
            )
        with self.assertRaises(Exception):
            scad.std.bearing.make_ball_bearing_rassembly(
                8.0,
                22.0,
                7.0,
                3.5,
                7,
                0.05,
                2.0,
            )


if __name__ == "__main__":
    unittest.main()
