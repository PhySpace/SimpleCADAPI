"""Tests for Phase 7: serialization and replay."""

import json
import unittest
from copy import deepcopy

import simplecadapi as scad
from simplecadapi.topology import OperationGraph, TopoDelta
from simplecadapi.recording.graph import GraphSession, record_operation
from simplecadapi.recording.serializer import (
    export_graph_json,
    import_graph_json,
    import_model_json,
    replay_graph,
    PUBLIC_API_COVERAGE,
    CANONICAL_CORE_OP_SET,
)


class TestGraphSerialization(unittest.TestCase):
    def test_roundtrip_empty(self):
        graph = OperationGraph()
        data = graph.to_dict()
        restored = OperationGraph.from_dict(data)
        self.assertEqual(restored.node_count, 0)
        self.assertEqual(restored.graph_id, graph.graph_id)

    def test_roundtrip_with_nodes(self):
        graph = OperationGraph()
        n1 = graph.add_node("make_line_redge", {"start": (0, 0, 0), "end": (10, 0, 0)})
        n2 = graph.add_node(
            "make_line_redge", {"start": (10, 0, 0), "end": (10, 20, 0)}
        )
        n3 = graph.add_node(
            "make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[n1, n2]
        )

        data = graph.to_dict()
        restored = OperationGraph.from_dict(data)

        self.assertEqual(restored.node_count, 3)
        self.assertEqual(restored.edge_count, 2)

        # Verify node order is preserved
        r_nodes = restored.topological_order()
        r_ops = [n.op for n in r_nodes]
        self.assertIn("make_line_redge", r_ops)
        self.assertIn("make_wire_from_edges_rwire", r_ops)

    def test_roundtrip_json(self):
        graph = OperationGraph()
        n1 = graph.add_node("make_line_redge", {"start": (0, 0, 0), "end": (10, 0, 0)})
        n2 = graph.add_node(
            "make_wire_from_edges_rwire", {"edge_count": 1}, inputs=[n1]
        )

        json_str = graph.to_json()
        restored = OperationGraph.from_json(json_str)

        self.assertEqual(restored.node_count, 2)
        self.assertEqual(restored.graph_id, graph.graph_id)

    def test_json_is_valid_json(self):
        graph = OperationGraph()
        graph.add_node("make_line_redge", {"start": (0, 0, 0), "end": (10, 20, 0)})
        json_str = graph.to_json()
        parsed = json.loads(json_str)
        self.assertIn("graph_id", parsed)
        self.assertIn("nodes", parsed)
        self.assertIn("edges", parsed)

    def test_roundtrip_preserves_params(self):
        graph = OperationGraph()
        graph.add_node(
            "make_translate_rshape",
            {"vector": [10.5, 20.0, 30.0], "center": [1, 2, 3]},
        )
        json_str = graph.to_json()
        restored = OperationGraph.from_json(json_str)
        node = restored.nodes[0]
        self.assertEqual(node.params["vector"], [10.5, 20.0, 30.0])
        self.assertEqual(node.params["center"], [1, 2, 3])

    def test_roundtrip_preserves_tags(self):
        graph = OperationGraph()
        graph.add_node("make_line_redge", {}, tags={"primitive", "profile"})
        json_str = graph.to_json()
        restored = OperationGraph.from_json(json_str)
        self.assertIn("primitive", restored.nodes[0].tags)
        self.assertIn("profile", restored.nodes[0].tags)


class TestExportImport(unittest.TestCase):
    def test_export_graph_json(self):
        with GraphSession() as session:
            record_operation("make_line_redge", {"start": (0, 0, 0), "end": (10, 0, 0)})
        json_str = export_graph_json(session.graph)
        parsed = json.loads(json_str)
        self.assertEqual(len(parsed["nodes"]), 1)

    def test_export_graph_json_includes_display_payload(self):
        with scad.GraphSession() as session:
            body = scad.make_box_rsolid(10, 10, 10)
            tool = scad.make_cylinder_rsolid(2.0, 15.0, bottom_face_center=(3, 3, -2.5))
            scad.cut_rsolid(body, tool)

        payload = json.loads(export_graph_json(session.graph))
        leaf = next(
            node for node in payload["nodes"] if node["op"] == "make_cut_rsolid"
        )

        self.assertIn("display", leaf)
        self.assertEqual(leaf["display"]["category"], "boolean")
        self.assertIn("label", leaf["display"])
        self.assertIn("summary", leaf["display"])

    def test_export_graph_json_display_payload_includes_selection_counts(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            edges = [box.get_edges(i) for i in range(4)]
            scad.fillet_rsolid(box, edges, 0.2)

        payload = json.loads(export_graph_json(session.graph))
        fillet_node = next(
            node for node in payload["nodes"] if node["op"] == "make_fillet_rsolid"
        )

        self.assertIn("display", fillet_node)
        self.assertEqual(fillet_node["display"]["selection_count"], 4)

    def test_export_graph_json_includes_schema_metadata(self):
        with scad.GraphSession() as session:
            scad.make_box_rsolid(1.0, 1.0, 1.0)

        payload = json.loads(export_graph_json(session.graph))
        self.assertIn("schema_version", payload)
        self.assertIn("producer_version", payload)
        self.assertIn("capabilities", payload)
        self.assertTrue(payload["capabilities"]["selection_ref_strategies"])
        self.assertTrue(payload["capabilities"]["geo_select_nodes"])
        self.assertTrue(payload["capabilities"]["display_payload"])
        self.assertTrue(payload["capabilities"]["sketch_solve_snapshots"])

    def test_sdf_field_surface_api_is_not_public(self):
        self.assertFalse(hasattr(scad, "field"))
        self.assertFalse(hasattr(scad, "make_field_surface_rsolid"))


class TestCoverageMatrix(unittest.TestCase):
    def test_public_api_coverage_accounts_for_current_geometry_exports(self):
        expected = {
            "make_box_rsolid",
            "make_cylinder_rsolid",
            "make_sphere_rsolid",
            "make_cone_rsolid",
            "make_circle_rwire",
            "make_rectangle_rface",
            "make_wire_from_edges_rwire",
            "translate_shape",
            "rotate_shape",
            "mirror_shape",
            "extrude_rsolid",
            "revolve_rsolid",
            "loft_rsolid",
            "loft_rshell",
            "sweep_rsolid",
            "twisted_sweep_rsolid",
            "helical_sweep_rsolid",
            "union_rsolid",
            "cut_rsolid",
            "intersect_rsolid",
            "fillet_rsolid",
            "chamfer_rsolid",
            "shell_rsolid",
            "linear_pattern_rsolidlist",
            "radial_pattern_rsolidlist",
            "make_material_rmaterial",
            "make_placement_rplacement",
            "identity_placement_rplacement",
            "make_part_rpart",
            "assign_material_rpart",
            "make_assembly_rassembly",
            "add_component_rassembly",
            "place_component_rassembly",
            "make_compound_from_assembly_rcompound",
            "make_face_connector_rconnector",
            "make_edge_connector_rconnector",
            "make_vertex_connector_rconnector",
            "make_placement_connector_rconnector",
            "add_connector_rpart",
            "set_public_connector_rassembly",
            "make_connector_ref_rconnectorref",
            "make_scalar_limit_rscalarlimit",
            "ground_component_rassembly",
            "unground_component_rassembly",
            "add_fixed_constraint_rassembly",
            "add_revolute_constraint_rassembly",
            "add_prismatic_constraint_rassembly",
            "add_gear_constraint_rassembly",
            "add_belt_constraint_rassembly",
            "add_rack_pinion_constraint_rassembly",
            "solve_assembly_constraints_rassembly",
        }
        self.assertTrue(expected.issubset(PUBLIC_API_COVERAGE.keys()))

    def test_replayable_public_api_coverage_targets_canonical_ops(self):
        canonical = set(CANONICAL_CORE_OP_SET)
        for api_name, coverage in PUBLIC_API_COVERAGE.items():
            if coverage.get("status") != "replayable":
                continue
            with self.subTest(api_name=api_name):
                self.assertIn(coverage.get("op"), canonical)

    def test_sdf_entries_are_not_part_of_public_api_coverage(self):
        self.assertNotIn("make_field_surface_rsolid", PUBLIC_API_COVERAGE)

    def test_import_graph_json(self):
        json_str = '{"schema_version": "2.0", "graph_id": "test", "nodes": [{"node_id": "n1", "op": "make_line_redge", "params": {"start": [0, 0, 0], "end": [10, 0, 0]}, "inputs": [], "output_count": 1, "tags": []}], "edges": []}'
        graph = import_graph_json(json_str)
        self.assertEqual(graph.node_count, 1)
        self.assertEqual(graph.nodes[0].op, "make_line_redge")

    def test_import_graph_json_rejects_unsupported_schema(self):
        json_str = (
            '{"schema_version": "1.0", "graph_id": "test", "nodes": [], "edges": []}'
        )
        with self.assertRaises(ValueError):
            import_graph_json(json_str)

        future = json.loads(json_str)
        future["schema_version"] = "2.999"
        with self.assertRaises(ValueError):
            import_graph_json(json.dumps(future))

    def test_import_graph_json_rejects_inconsistent_structure(self):
        payload = {
            "schema_version": "2.0",
            "graph_id": "test",
            "nodes": [
                {
                    "node_id": "n1",
                    "op": "make_line_redge",
                    "params": {"start": [0, 0, 0], "end": [1, 0, 0]},
                    "inputs": [],
                    "output_count": 1,
                    "tags": [],
                },
                {
                    "node_id": "n2",
                    "op": "make_wire_from_edges_rwire",
                    "params": {"edge_count": 1},
                    "inputs": ["n1"],
                    "output_count": 1,
                    "tags": [],
                },
            ],
            "edges": [],
        }
        with self.assertRaises(ValueError):
            import_graph_json(json.dumps(payload))

        payload["edges"] = [["n1", "n2"]]
        payload["nodes"][1]["output_count"] = -1
        with self.assertRaises(ValueError):
            import_graph_json(json.dumps(payload))

    def test_canonical_core_op_set_is_exact_contract(self):
        expected = {
            "load_brep_region_rshell",
            "load_brep_region_rsolid",
            "make_point_rvertex",
            "make_line_redge",
            "make_circle_redge",
            "make_ellipse_redge",
            "make_three_point_arc_redge",
            "make_angle_arc_redge",
            "make_spline_redge",
            "make_interpolated_spline_redge",
            "make_helix_redge",
            "make_wire_from_edges_rwire",
            "make_face_from_wire_rface",
            "make_face_from_wires_rface",
            "make_sketch_rsketch",
            "add_point_rsketch",
            "add_line_rsketch",
            "add_circle_rsketch",
            "add_arc_rsketch",
            "add_bspline_rsketch",
            "make_constrain_coincident_rsketch",
            "make_constrain_point_on_rsketch",
            "make_constrain_horizontal_rsketch",
            "make_constrain_vertical_rsketch",
            "make_constrain_points_horizontal_rsketch",
            "make_constrain_points_vertical_rsketch",
            "make_constrain_line_distance_rsketch",
            "make_constrain_normal_rsketch",
            "make_constrain_mirror_rsketch",
            "make_constrain_midpoint_points_rsketch",
            "make_constrain_major_radius_rsketch",
            "make_constrain_minor_radius_rsketch",
            "add_ellipse_rsketch",
            "make_constrain_parallel_rsketch",
            "make_constrain_perpendicular_rsketch",
            "make_constrain_collinear_rsketch",
            "make_constrain_tangent_rsketch",
            "make_constrain_concentric_rsketch",
            "make_constrain_midpoint_rsketch",
            "make_constrain_symmetric_rsketch",
            "make_constrain_equal_length_rsketch",
            "make_constrain_equal_radius_rsketch",
            "make_constrain_distance_rsketch",
            "make_constrain_distance_x_rsketch",
            "make_constrain_distance_y_rsketch",
            "make_constrain_length_rsketch",
            "make_constrain_angle_rsketch",
            "make_constrain_radius_rsketch",
            "make_constrain_diameter_rsketch",
            "make_constrain_fix_rsketch",
            "make_wire_from_sketch_rwire",
            "make_face_from_sketch_rface",
            "make_box_rsolid",
            "make_cylinder_rsolid",
            "make_cone_rsolid",
            "make_sphere_rsolid",
            "make_material_rmaterial",
            "make_placement_rplacement",
            "make_identity_placement_rplacement",
            "make_part_rpart",
            "make_assign_material_rpart",
            "make_assembly_rassembly",
            "make_add_component_rassembly",
            "reference_definition",
            "make_place_component_rassembly",
            "make_compound_from_assembly_rcompound",
            "make_face_connector_rconnector",
            "make_edge_connector_rconnector",
            "make_vertex_connector_rconnector",
            "make_placement_connector_rconnector",
            "make_add_connector_rpart",
            "make_set_public_connector_rassembly",
            "make_connector_ref_rconnectorref",
            "make_scalar_limit_rscalarlimit",
            "make_ground_component_rassembly",
            "make_unground_component_rassembly",
            "make_fixed_constraint_rassembly",
            "make_revolute_constraint_rassembly",
            "make_prismatic_constraint_rassembly",
            "make_gear_constraint_rassembly",
            "make_belt_constraint_rassembly",
            "make_rack_pinion_constraint_rassembly",
            "make_solve_assembly_constraints_rassembly",
            "evaluate_assembly_definition",
            "make_extrude_rsolid",
            "make_revolve_rsolid",
            "make_loft_rsolid",
            "make_sweep_rsolid",
            "make_twisted_sweep_rsolid",
            "make_translate_rshape",
            "make_rotate_rshape",
            "make_scale_rsolid",
            "make_transform_rsolid",
            "make_offset_rsolid",
            "make_extrude_taper_rsolid",
            "make_loft_multisection_rsolid",
            "make_extrude_until_rsolid",
            "make_draft_rsolid",
            "make_boolean_rsolidlist",
            "make_mirror_rshape",
            "make_cut_rsolid",
            "make_union_rsolid",
            "make_intersect_rsolid",
            "make_2d_cut_rface",
            "make_2d_union_rface",
            "make_2d_intersect_rface",
            "make_fillet_rsolid",
            "make_chamfer_rsolid",
            "make_shell_rsolid",
            "make_bezier_surface_rface",
            "make_cylindrical_surface_rface",
            "fit_point_grid_rface",
            "make_ruled_surface_rface",
            "make_gordon_surface_rface",
            "make_surface_patch_rface",
            "trim_surface_rface",
            "make_loft_rshell",
            "sew_faces_rshell",
            "make_solid_from_shell_rsolid",
            "free_boundaries_rwirelist",
            "fill_holes_rshell",
            "make_select_rvertex",
            "make_select_redge",
            "make_select_rwire",
            "make_select_rface",
            "make_select_rshell",
            "make_select_rsolid",
        }

        self.assertEqual(set(CANONICAL_CORE_OP_SET), expected)

    def test_import_graph_json_rejects_legacy_op_name(self):
        payload = {
            "schema_version": "2.0",
            "graph_id": "test",
            "nodes": [
                {
                    "node_id": "n1",
                    "op": "make_line",
                    "params": {"start": [0, 0, 0], "end": [1, 0, 0]},
                    "inputs": [],
                    "output_count": 1,
                    "tags": [],
                }
            ],
            "edges": [],
        }

        with self.assertRaises(ValueError):
            import_graph_json(json.dumps(payload))

    def test_export_graph_json_rejects_legacy_op_name(self):
        graph = OperationGraph()
        graph.add_node("make_line", {"start": (0, 0, 0), "end": (1, 0, 0)})

        with self.assertRaises(ValueError):
            export_graph_json(graph)


class TestReplay(unittest.TestCase):
    @staticmethod
    def _tag_node(payload, tag):
        return next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "apply_tag_rselection"
            and node["params"]["tag_binding"]["tag"] == tag
        )

    @staticmethod
    def _topology_ref_map(shape):
        refs = {}
        for entity in shape._topology_cache.entities():
            wrapper = entity.wrappers[0]
            ref = wrapper.get_metadata("topo_ref")
            if isinstance(ref, dict):
                refs[(entity.kind, entity.topo_id)] = (
                    ref["graph_id"],
                    ref["node_id"],
                    ref["output_slot"],
                    ref["kind"],
                    ref["topo_id"],
                )
        return refs

    def test_replay_builds_graph(self):
        """A simple low-level graph can be replayed."""
        with GraphSession() as session:
            n1 = record_operation(
                "make_line_redge", {"start": (0, 0, 0), "end": (1, 0, 0)}
            )
            n2 = record_operation(
                "make_line_redge", {"start": (1, 0, 0), "end": (1, 1, 0)}
            )
            record_operation(
                "make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[n1, n2]
            )

        results = replay_graph(session.graph)
        self.assertIsNotNone(results)
        self.assertGreater(len(results), 0)

    def test_terminal_tag_selector_roundtrip_preserves_binding_and_topology_refs(self):
        tag = "role.selector_target"
        selector = (
            scad.ql.faces()
            .order_by(scad.ql.key("geom.center.z"), desc=True)
            .take(1)
            .exactly(1)
        )
        with scad.GraphSession() as session:
            source = scad.make_box_rsolid(2.0, 3.0, 4.0)
            source_refs = self._topology_ref_map(source)
            geometry_node_id = source.get_metadata("graph")["node_id"]
            tagged = scad.apply_tag_rselection(source, selector, tag)

        self.assertEqual(self._topology_ref_map(tagged), source_refs)
        self.assertEqual(scad.select_faces_by_tag(source, tag, scope="local"), [])
        self.assertEqual(len(scad.select_faces_by_tag(tagged, tag, scope="local")), 1)

        payload = json.loads(scad.export_model_json(session))
        node = self._tag_node(payload, tag)
        binding = node["params"]["tag_binding"]
        self.assertEqual(payload["leaf_ids"], [node["node_id"]])
        self.assertEqual(node["inputs"], [geometry_node_id])
        self.assertEqual(binding["producer"]["node_id"], node["node_id"])
        self.assertEqual(binding["scope"]["node_id"], geometry_node_id)
        self.assertEqual(binding["target"]["kind"], "selection_query")
        self.assertEqual(binding["evidence"]["selected_count"], 1)
        self.assertEqual(payload["semantic_bindings"], [binding])

        replayed = scad.replay_model_json(json.dumps(payload))
        self.assertEqual(len(replayed), 1)
        result = replayed[0]
        self.assertEqual(result.get_metadata("graph")["node_id"], node["node_id"])
        self.assertEqual(result.get_metadata("topo_ref")["node_id"], geometry_node_id)
        selected = scad.select_faces_by_tag(result, tag, scope="local")
        self.assertEqual(len(selected), 1)
        explanation = scad.explain_tag(selected[0], tag, scope="local")
        self.assertEqual(explanation[0]["binding_id"], binding["binding_id"])

    def test_terminal_tag_explicit_refs_roundtrip(self):
        tag = "role.explicit_target"
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(2.0, 3.0, 4.0)
            top_face = max(box._iter_faces(), key=lambda face: face.get_center().z)
            expected_ref = top_face.get_metadata("topo_ref")
            scad.apply_tag_rselection(box, [top_face], tag)

        payload = json.loads(scad.export_model_json(session))
        node = self._tag_node(payload, tag)
        binding = node["params"]["tag_binding"]
        self.assertEqual(binding["target"]["kind"], "explicit_refs")
        self.assertEqual(
            binding["target"]["refs"][0]["topo_id"], expected_ref["topo_id"]
        )
        self.assertFalse(
            any(
                item["op"].startswith("make_select_")
                for item in payload["graph"]["nodes"]
            )
        )

        result = scad.replay_model_json(json.dumps(payload))[0]
        selected = scad.select_faces_by_tag(result, tag, scope="local")
        self.assertEqual(len(selected), 1)
        self.assertEqual(
            selected[0].get_metadata("topo_ref")["topo_id"], expected_ref["topo_id"]
        )

    def test_apply_tag_chain_roundtrip_preserves_nodes_bindings_and_topology_refs(self):
        tags = ("role.alpha", "role.beta", "role.alpha")
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(2.0, 3.0, 4.0)
            geometry_node_id = box.get_metadata("graph")["node_id"]
            source_refs = self._topology_ref_map(box)
            for tag in tags:
                self.assertIs(scad.apply_tag(box, tag), box)

        self.assertEqual(self._topology_ref_map(box), source_refs)
        payload = json.loads(scad.export_model_json(session))
        tag_nodes = [
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "apply_tag_rselection"
        ]
        self.assertEqual(
            [node["params"]["tag_binding"]["tag"] for node in tag_nodes],
            list(tags),
        )

        previous_node_id = geometry_node_id
        binding_ids = []
        for node in tag_nodes:
            binding = node["params"]["tag_binding"]
            self.assertEqual(node["inputs"], [previous_node_id])
            self.assertEqual(binding["scope"]["node_id"], previous_node_id)
            self.assertEqual(binding["producer"]["node_id"], node["node_id"])
            binding_ids.append(binding["binding_id"])
            previous_node_id = node["node_id"]

        self.assertEqual(len(binding_ids), len(set(binding_ids)))
        self.assertEqual(payload["leaf_ids"], [previous_node_id])
        self.assertEqual(box.get_metadata("graph")["node_id"], previous_node_id)
        self.assertEqual(
            [binding["binding_id"] for binding in payload["semantic_bindings"]],
            binding_ids,
        )

        replayed = scad.replay_model_json(json.dumps(payload))
        self.assertEqual(len(replayed), 1)
        result = replayed[0]
        self.assertTrue(
            {"role.alpha", "role.beta"}.issubset(scad.list_tags(result, scope="local"))
        )
        self.assertEqual(
            len(scad.explain_tag(result, "role.alpha", scope="local")),
            2,
        )
        self.assertEqual(self._topology_ref_map(result), source_refs)

    def test_tag_semantic_branches_are_isolated_after_replay(self):
        selector = (
            scad.ql.faces()
            .order_by(scad.ql.key("geom.center.z"), desc=True)
            .take(1)
            .exactly(1)
        )
        with scad.GraphSession() as session:
            source = scad.make_box_rsolid(2.0, 3.0, 4.0)
            left = scad.apply_tag_rselection(source, selector, "role.left_branch")
            right = scad.apply_tag_rselection(source, selector, "role.right_branch")

        self.assertEqual(
            len(scad.select_faces_by_tag(left, "role.left_branch", scope="local")), 1
        )
        self.assertEqual(
            scad.select_faces_by_tag(left, "role.right_branch", scope="local"), []
        )
        self.assertEqual(
            scad.select_faces_by_tag(right, "role.left_branch", scope="local"), []
        )
        self.assertEqual(
            len(scad.select_faces_by_tag(right, "role.right_branch", scope="local")),
            1,
        )

        payload = json.loads(scad.export_model_json(session))
        left_node = self._tag_node(payload, "role.left_branch")
        right_node = self._tag_node(payload, "role.right_branch")
        replayed = {
            shape.get_metadata("graph")["node_id"]: shape
            for shape in scad.replay_model_json(json.dumps(payload))
        }
        replayed_left = replayed[left_node["node_id"]]
        replayed_right = replayed[right_node["node_id"]]
        self.assertEqual(
            len(
                scad.select_faces_by_tag(
                    replayed_left, "role.left_branch", scope="local"
                )
            ),
            1,
        )
        self.assertEqual(
            scad.select_faces_by_tag(replayed_left, "role.right_branch", scope="local"),
            [],
        )
        self.assertEqual(
            scad.select_faces_by_tag(replayed_right, "role.left_branch", scope="local"),
            [],
        )
        self.assertEqual(
            len(
                scad.select_faces_by_tag(
                    replayed_right, "role.right_branch", scope="local"
                )
            ),
            1,
        )

    def test_strict_tag_replay_rejects_binding_tampering(self):
        selector = (
            scad.ql.faces()
            .order_by(scad.ql.key("geom.center.z"), desc=True)
            .take(1)
            .exactly(1)
        )
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(2.0, 3.0, 4.0)
            scad.apply_tag_rselection(box, selector, "role.target")

        raw = json.loads(scad.export_model_json(session))

        damaged = deepcopy(raw)
        node = self._tag_node(damaged, "role.target")
        node["params"]["tag_binding"]["producer"]["node_id"] = node["inputs"][0]
        damaged["semantic_bindings"] = [node["params"]["tag_binding"]]
        with self.assertRaisesRegex(ValueError, "does not match binding producer"):
            scad.replay_model_json(json.dumps(damaged))

        damaged = deepcopy(raw)
        node = self._tag_node(damaged, "role.target")
        node["params"]["tag_binding"]["target"]["selector"]["order_keys"][0][
            "desc"
        ] = False
        damaged["semantic_bindings"] = [node["params"]["tag_binding"]]
        with self.assertRaisesRegex(ValueError, "target evidence drifted"):
            scad.replay_model_json(json.dumps(damaged))

    def test_replay_preserves_volume(self):
        with GraphSession() as session:
            record_operation(
                "make_extrude_rsolid", {"direction": (0, 0, 1), "distance": 10.0}
            )

        results = replay_graph(session.graph, strict=False)
        self.assertGreaterEqual(len(results), 0)

    def test_replay_empty_graph(self):
        graph = OperationGraph()
        results = replay_graph(graph)
        self.assertEqual(results, [])

    def test_replay_original_api_rectangle_extrude_roundtrip(self):
        with scad.GraphSession() as session:
            profile = scad.make_rectangle_rface(2.0, 1.0)
            solid = scad.extrude_rsolid(profile, (0, 0, 1), 3.0)

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), solid.get_volume(), places=5)

    def test_replay_original_api_circle_wire_roundtrip(self):
        with scad.GraphSession() as session:
            wire = scad.make_circle_rwire((0, 0, 0), 2.0)

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Wire)
        self.assertTrue(results[0].is_closed())

    def test_replay_original_api_loft_roundtrip(self):
        with scad.GraphSession() as session:
            a = scad.make_rectangle_rwire(2.0, 2.0, center=(0, 0, 0))
            b = scad.make_rectangle_rwire(1.0, 1.0, center=(0, 0, 2.0))
            lofted = scad.loft_rsolid([a, b])

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), lofted.get_volume(), places=5)

    def test_replay_public_connector_roundtrip(self):
        with scad.GraphSession() as session:
            body = scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)
            part = scad.make_part_rpart(part_id="public_part", body=body)
            connector = scad.make_placement_connector_rconnector(
                connector_id="axis",
                placement=scad.make_placement_rplacement(origin=(1.0, 2.0, 3.0)),
            )
            part = scad.add_connector_rpart(part=part, connector=connector)
            assembly = scad.make_assembly_rassembly(assembly_id="public_parent")
            assembly = scad.add_component_rassembly(
                assembly=assembly,
                item=part,
                component_id="child",
                placement=scad.identity_placement_rplacement(),
            )
            scad.set_public_connector_rassembly(assembly=assembly,
            public_connector_id="public_axis",
            source_component_id="child",
            source_connector_id="axis",)

        replayed = scad.replay_model_json(
            json_str=scad.export_model_json(session=session)
        )
        assemblies = [item for item in replayed if isinstance(item, scad.Assembly)]

        self.assertTrue(assemblies)
        public = assemblies[-1].get_public_connector("public_axis")
        self.assertEqual(
            (public.component_id, public.connector_id),
            ("child", "axis"),
        )

    def test_replay_public_connector_rejects_removed_offset(self):
        with scad.GraphSession() as session:
            body = scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)
            part = scad.make_part_rpart(part_id="public_part", body=body)
            connector = scad.make_placement_connector_rconnector(
                connector_id="axis",
                placement=scad.identity_placement_rplacement(),
            )
            part = scad.add_connector_rpart(part=part, connector=connector)
            assembly = scad.make_assembly_rassembly(assembly_id="public_parent")
            assembly = scad.add_component_rassembly(
                assembly=assembly,
                item=part,
                component_id="child",
                placement=scad.identity_placement_rplacement(),
            )
            scad.set_public_connector_rassembly(
                assembly=assembly,
                public_connector_id="public_axis",
                source_component_id="child",
                source_connector_id="axis",
            )

        payload = json.loads(scad.export_model_json(session=session))
        public_node = next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_set_public_connector_rassembly"
        )
        public_node["params"]["offset"] = scad.identity_placement_rplacement().to_dict()

        with self.assertRaisesRegex(Exception, r"unsupported parameter\(s\): offset"):
            scad.replay_model_json(json_str=json.dumps(payload))

    def test_replay_wire_face_extrude_edit_chain_roundtrip(self):
        with scad.GraphSession() as session:
            e1 = scad.make_line_redge((0, 0, 0), (1, 0, 0))
            e2 = scad.make_line_redge((1, 0, 0), (1, 1, 0))
            e3 = scad.make_line_redge((1, 1, 0), (0, 1, 0))
            e4 = scad.make_line_redge((0, 1, 0), (0, 0, 0))
            wire = scad.make_wire_from_edges_rwire([e1, e2, e3, e4])
            face = scad.make_face_from_wire_rface(wire)
            solid = scad.extrude_rsolid(face, (0, 0, 1), 2.0)

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), solid.get_volume(), places=5)

    def test_replay_multi_loop_face_extrude_roundtrip(self):
        with scad.GraphSession() as session:
            outer = scad.make_circle_rwire(center=(0, 0, 0), radius=5.0)
            inner = scad.make_circle_rwire(center=(0, 0, 0), radius=2.0)
            face = scad.make_face_from_wires_rface(outer, [inner])
            solid = scad.extrude_rsolid(face, (0, 0, 1), 3.0)

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), solid.get_volume(), places=5)

    def test_replay_sketch_face_with_explicit_holes_roundtrip(self):
        with scad.GraphSession() as session:
            sketch = scad.make_sketch_rsketch("serialized_ring", plane="YZ")
            sketch = scad.add_point_rsketch(sketch, "outer_center", 0.0, 0.0)
            sketch = scad.add_circle_rsketch(sketch, "outer", "outer_center", 5.0)
            sketch = scad.add_point_rsketch(sketch, "inner_center", 0.0, 0.0)
            sketch = scad.add_circle_rsketch(sketch, "inner", "inner_center", 2.0)
            face = scad.make_face_from_sketch_rface(
                sketch,
                profile="outer",
                inner_profiles=("inner",),
            )
            solid = scad.extrude_rsolid(face, (1.0, 0.0, 0.0), 3.0)

        payload = json.loads(scad.export_model_json(session))
        promotion = next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_face_from_sketch_rface"
        )
        self.assertEqual(promotion["params"]["inner_profiles"], ["inner"])
        self.assertEqual(
            [loop["role"] for loop in promotion["params"]["promotion_map"]["loops"]],
            ["outer", "inner"],
        )

        results = scad.replay_model_json(json.dumps(payload))
        rebuilt = next(item for item in results if isinstance(item, scad.Solid))
        self.assertAlmostEqual(rebuilt.get_volume(), solid.get_volume(), places=5)

    def test_replay_sketch_bspline_point_refs_roundtrip(self):
        with scad.GraphSession() as session:
            sketch = scad.make_sketch_rsketch("referenced_spline", plane="YZ")
            sketch = scad.add_point_rsketch(sketch, "start", 0.0, 0.0)
            sketch = scad.add_point_rsketch(sketch, "end", 4.0, 0.0)
            sketch = scad.add_bspline_rsketch(
                sketch,
                "curve",
                "start",
                "end",
                control_points=("start", (1.0, 1.5), (3.0, 1.5), "end"),
                knots=(0.0, 1.0),
                multiplicities=(4, 4),
            )
            sketch = scad.add_line_rsketch(sketch, "close", "end", "start")
            face = scad.make_face_from_sketch_rface(sketch)

        payload = scad.export_model_json(session)
        results = scad.replay_model_json(payload)
        rebuilt = next(item for item in results if isinstance(item, scad.Face))
        self.assertAlmostEqual(rebuilt.get_area(), face.get_area(), places=6)
        normal = rebuilt.get_normal_at()
        self.assertAlmostEqual(normal.x, 1.0, places=6)

    def test_replay_fillet_roundtrip_with_selected_edges(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            edges = [box.get_edges(i) for i in range(4)]
            filleted = scad.fillet_rsolid(box, edges, 0.2)

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), filleted.get_volume(), places=5)

    def test_indexed_edge_access_records_geo_select_nodes(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            edge = box.get_edges(0)
            filleted = scad.fillet_rsolid(box, [edge], 0.2)

        payload = json.loads(export_graph_json(session.graph))
        fillet_node = next(
            node for node in payload["nodes"] if node["op"] == "make_fillet_rsolid"
        )
        selection_node_ids = fillet_node["params"]["selected_edge_node_ids"]
        self.assertEqual(len(selection_node_ids), 1)
        selection_node = next(
            node
            for node in payload["nodes"]
            if node["node_id"] == selection_node_ids[0]
        )
        self.assertEqual(selection_node["op"], "make_select_redge")
        self.assertNotIn("source_index", selection_node["params"]["geo_selector"])
        self.assertNotIn("selected_edge_indices", fillet_node["params"])

        results = replay_graph(import_graph_json(json.dumps(payload)))
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), filleted.get_volume(), places=5)

    def test_indexed_edge_getter_records_multiple_geo_select_nodes(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            edges = [box.get_edges(i) for i in range(2)]
            filleted = scad.fillet_rsolid(box, edges, 0.2)

        payload = json.loads(export_graph_json(session.graph))
        fillet_node = next(
            node for node in payload["nodes"] if node["op"] == "make_fillet_rsolid"
        )
        selection_node_ids = fillet_node["params"]["selected_edge_node_ids"]
        self.assertEqual(len(selection_node_ids), 2)
        selection_nodes = [
            node for node in payload["nodes"] if node["node_id"] in selection_node_ids
        ]
        self.assertTrue(
            all(node["op"] == "make_select_redge" for node in selection_nodes)
        )

        results = replay_graph(import_graph_json(json.dumps(payload)))
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), filleted.get_volume(), places=5)

    def test_replay_chamfer_roundtrip_with_selected_edges(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            edges = [box.get_edges(i) for i in range(4)]
            chamfered = scad.chamfer_rsolid(box, edges, 0.2)

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(
            results[0].get_volume(), chamfered.get_volume(), places=5
        )

    def test_replay_shell_roundtrip_with_selected_faces(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            shelled = scad.shell_rsolid(box, [box.get_faces(0)], 0.2)

        graph_json = export_graph_json(session.graph)
        restored = import_graph_json(graph_json)
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), shelled.get_volume(), places=5)

    def test_indexed_face_access_records_geo_select_nodes(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            face = box.get_faces(0)
            shelled = scad.shell_rsolid(box, [face], 0.2)

        payload = json.loads(export_graph_json(session.graph))
        shell_node = next(
            node for node in payload["nodes"] if node["op"] == "make_shell_rsolid"
        )
        selection_node_ids = shell_node["params"]["selected_face_node_ids"]
        self.assertEqual(len(selection_node_ids), 1)
        selection_node = next(
            node
            for node in payload["nodes"]
            if node["node_id"] == selection_node_ids[0]
        )
        self.assertEqual(selection_node["op"], "make_select_rface")
        self.assertNotIn("source_index", selection_node["params"]["geo_selector"])
        self.assertNotIn("selected_face_indices", shell_node["params"])

        results = replay_graph(import_graph_json(json.dumps(payload)))
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), shelled.get_volume(), places=5)

    def test_nested_indexed_edge_access_records_source_face_select_node(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            face = box.get_faces(0)
            edge = face.get_edges(0)
            filleted = scad.fillet_rsolid(box, [edge], 0.2)

        payload = json.loads(export_graph_json(session.graph))
        select_face_nodes = [
            node for node in payload["nodes"] if node["op"] == "make_select_rface"
        ]
        self.assertEqual(len(select_face_nodes), 1)

        fillet_node = next(
            node for node in payload["nodes"] if node["op"] == "make_fillet_rsolid"
        )
        selection_node_id = fillet_node["params"]["selected_edge_node_ids"][0]
        selection_node = next(
            node for node in payload["nodes"] if node["node_id"] == selection_node_id
        )
        self.assertEqual(selection_node["op"], "make_select_redge")
        self.assertEqual(selection_node["inputs"], [select_face_nodes[0]["node_id"]])
        self.assertNotIn("source_index", selection_node["params"]["geo_selector"])

        results = replay_graph(import_graph_json(json.dumps(payload)))
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), filleted.get_volume(), places=5)

    def test_indexed_child_geometry_getters_record_select_nodes(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            face = box.get_faces(0)
            wire = face.get_wires(0)
            edge = wire.get_edges(0)
            vertex = edge.get_vertices(0)

        payload = json.loads(export_graph_json(session.graph))
        ops = [node["op"] for node in payload["nodes"]]

        self.assertIsInstance(face, scad.Face)
        self.assertIsInstance(wire, scad.Wire)
        self.assertIsInstance(edge, scad.Edge)
        self.assertIsInstance(vertex, scad.Vertex)
        self.assertIn("make_select_rface", ops)
        self.assertIn("make_select_rwire", ops)
        self.assertIn("make_select_redge", ops)
        self.assertIn("make_select_rvertex", ops)

    def test_replay_fillet_roundtrip_with_selector_hint_fallback(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            edges = [box.get_edges(i) for i in range(4)]
            filleted = scad.fillet_rsolid(box, edges, 0.2)

        payload = json.loads(export_graph_json(session.graph))
        fillet_node = next(
            node for node in payload["nodes"] if node["op"] == "make_fillet_rsolid"
        )
        self.assertGreater(len(fillet_node["params"]["selected_edges"]), 0)
        self.assertIn("selector_hint", fillet_node["params"]["selected_edges"][0])

        damaged = deepcopy(payload)
        damaged_fillet = next(
            node for node in damaged["nodes"] if node["op"] == "make_fillet_rsolid"
        )
        for ref in damaged_fillet["params"]["selected_edges"]:
            ref["topo_id"] = "missing_edge_ref"
        damaged_fillet["params"]["selected_edge_node_ids"] = []
        damaged_fillet["params"]["selected_edge_indices"] = []

        restored = import_graph_json(json.dumps(damaged))
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), filleted.get_volume(), places=5)

    def test_replay_shell_roundtrip_with_selector_hint_fallback(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            shelled = scad.shell_rsolid(box, [box.get_faces(0)], 0.2)

        payload = json.loads(export_graph_json(session.graph))
        shell_node = next(
            node for node in payload["nodes"] if node["op"] == "make_shell_rsolid"
        )
        self.assertGreater(len(shell_node["params"]["selected_faces"]), 0)
        self.assertIn("selector_hint", shell_node["params"]["selected_faces"][0])

        damaged = deepcopy(payload)
        damaged_shell = next(
            node for node in damaged["nodes"] if node["op"] == "make_shell_rsolid"
        )
        for ref in damaged_shell["params"]["selected_faces"]:
            ref["topo_id"] = "missing_face_ref"
        damaged_shell["params"]["selected_face_node_ids"] = []
        damaged_shell["params"]["selected_face_indices"] = []

        restored = import_graph_json(json.dumps(damaged))
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), shelled.get_volume(), places=5)

    def test_replay_fillet_roundtrip_with_ql_selector(self):
        with scad.GraphSession() as session:
            rod = scad.make_cylinder_rsolid(1.0, 5.0, bottom_face_center=(0, 0, 0))
            selector = (
                scad.ql.edges()
                .where(scad.ql.curve_type("circle"))
                .order_by(scad.ql.center_axis("z"))
                .take(1)
                .exactly(1)
            )
            filleted = scad.fillet_rsolid(rod, selector, 0.15)

        payload = json.loads(export_graph_json(session.graph))
        fillet_node = next(
            node for node in payload["nodes"] if node["op"] == "make_fillet_rsolid"
        )
        self.assertNotIn("selection_query", fillet_node["params"])
        selection_node_ids = fillet_node["params"]["selected_edge_node_ids"]
        self.assertEqual(len(selection_node_ids), 1)
        selection_node = next(
            node
            for node in payload["nodes"]
            if node["node_id"] == selection_node_ids[0]
        )
        self.assertEqual(selection_node["op"], "make_select_redge")
        self.assertEqual(selection_node["params"]["target_kind"], "edge")
        self.assertEqual(selection_node["params"]["geo_selector"]["kind"], "edge")
        self.assertNotIn("tags", selection_node["params"]["geo_selector"])

        restored = import_graph_json(json.dumps(payload))
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), filleted.get_volume(), places=5)

    def test_ql_tag_filter_records_geo_select_node_not_tag_selector(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            scad.apply_tag(box.get_edges(0), "role.target_edge")
            selector = scad.ql.edges().where(scad.ql.tag("role.target_edge")).exactly(1)
            filleted = scad.fillet_rsolid(box, selector, 0.2)

        payload = json.loads(export_graph_json(session.graph))
        fillet_node = next(
            node for node in payload["nodes"] if node["op"] == "make_fillet_rsolid"
        )
        select_node = next(
            node
            for node in payload["nodes"]
            if node["node_id"] == fillet_node["params"]["selected_edge_node_ids"][0]
        )

        self.assertNotIn("selection_query", fillet_node["params"])
        self.assertNotIn("tags", select_node["params"]["geo_selector"])
        self.assertNotIn("source_index", select_node["params"]["geo_selector"])

        fillet_node["params"]["selected_edges"] = []
        fillet_node["params"]["selected_edge_indices"] = []
        results = replay_graph(import_graph_json(json.dumps(payload)))

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), filleted.get_volume(), places=5)

    def test_replay_chamfer_roundtrip_with_traversal_selector(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(2.0, 3.0, 4.0)
            selector = (
                scad.ql.faces()
                .where(scad.ql.prop("geom.normal.z", ">", 0.9))
                .order_by(scad.ql.key("geom.center.z"), desc=True)
                .take(1)
                .exactly(1)
                .boundary("wire")
                .where(scad.ql.prop("topo.loop_role", "==", "outer"))
                .take(1)
                .exactly(1)
                .boundary("edge")
                .exactly(4)
            )
            chamfered = scad.chamfer_rsolid(box, selector, 0.15)

        payload = json.loads(export_graph_json(session.graph))
        chamfer_node = next(
            node for node in payload["nodes"] if node["op"] == "make_chamfer_rsolid"
        )
        self.assertNotIn("selection_query", chamfer_node["params"])
        selection_node_ids = chamfer_node["params"]["selected_edge_node_ids"]
        self.assertEqual(len(selection_node_ids), 4)
        selection_nodes = [
            node for node in payload["nodes"] if node["node_id"] in selection_node_ids
        ]
        self.assertTrue(
            all(node["op"] == "make_select_redge" for node in selection_nodes)
        )
        self.assertTrue(
            all(
                node["params"]["geo_selector"]["kind"] == "edge"
                for node in selection_nodes
            )
        )
        self.assertTrue(
            all(
                "tags" not in node["params"]["geo_selector"] for node in selection_nodes
            )
        )

        restored = import_graph_json(json.dumps(payload))
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(
            results[0].get_volume(), chamfered.get_volume(), places=5
        )

    def test_replay_mirror_roundtrip(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(2.0, 3.0, 4.0)
            mirrored = scad.mirror_shape(box, (0, 0, 0), (1, 0, 0))

        restored = import_graph_json(export_graph_json(session.graph))
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), mirrored.get_volume(), places=5)

    def test_replay_sweep_roundtrip(self):
        with scad.GraphSession() as session:
            profile = scad.make_circle_rface((0, 0, 0), 0.5)
            path = scad.make_segment_rwire((0, 0, 0), (0, 0, 3.0))
            swept = scad.sweep_rsolid(profile, path)

        restored = import_graph_json(export_graph_json(session.graph))
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), swept.get_volume(), places=5)

    def test_replay_twisted_sweep_roundtrip(self):
        with scad.GraphSession() as session:
            profile = scad.make_rectangle_rface(width=2.0, height=1.0)
            swept = scad.twisted_sweep_rsolid(
                profile=profile,
                distance=5.0,
                twist_angle=45.0,
            )

        payload = json.loads(export_graph_json(session.graph))
        node = next(
            item
            for item in payload["nodes"]
            if item["op"] == "make_twisted_sweep_rsolid"
        )
        self.assertEqual(len(node["inputs"]), 1)
        self.assertEqual(
            node["params"],
            {
                "axis": [0.0, 0.0, 1.0],
                "origin": [0.0, 0.0, 0.0],
                "distance": 5.0,
                "twist_angle": 45.0,
                "guide_radius": 1.0,
            },
        )

        results = replay_graph(import_graph_json(json.dumps(payload)), strict=True)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]._iter_faces()), 6)
        self.assertAlmostEqual(results[0].get_volume(), swept.get_volume(), places=8)

    def test_replay_sweep_records_ql_selected_extrude_end_face_profile(self):
        with scad.GraphSession() as session:
            base = scad.make_circle_rface((0, 0, 0), 0.25)
            body = scad.extrude_rsolid(base, (0, 0, 1), 1.0)
            profile = (
                scad.ql.faces()
                .where(scad.ql.tag("face.extrusion.end"))
                .exactly(1)
                .resolve(body)[0]
            )
            path = scad.make_segment_rwire((0, 0, 1.0), (0, 0, 2.0))
            swept = scad.sweep_rsolid(profile, path)

        payload = json.loads(export_graph_json(session.graph))
        select_nodes = [
            node for node in payload["nodes"] if node["op"] == "make_select_rface"
        ]
        self.assertEqual(len(select_nodes), 1)
        select_node = select_nodes[0]
        self.assertEqual(select_node["params"]["target_kind"], "face")
        self.assertEqual(select_node["params"]["geo_selector"]["kind"], "face")
        self.assertNotIn("source_index", select_node["params"]["geo_selector"])
        self.assertNotIn("tags", select_node["params"]["geo_selector"])

        sweep_node = next(
            node for node in payload["nodes"] if node["op"] == "make_sweep_rsolid"
        )
        self.assertEqual(sweep_node["inputs"][0], select_node["node_id"])

        restored = replay_graph(import_graph_json(json.dumps(payload)))

        self.assertEqual(len(restored), 1)
        self.assertIsInstance(restored[0], scad.Solid)
        self.assertAlmostEqual(restored[0].get_volume(), swept.get_volume(), places=5)

    def test_replay_helical_sweep_roundtrip(self):
        with scad.GraphSession() as session:
            profile = scad.make_rectangle_rwire(0.4, 0.2)
            swept = scad.helical_sweep_rsolid(
                profile, pitch=1.0, height=2.0, radius=1.0
            )

        restored = import_graph_json(export_graph_json(session.graph))
        results = replay_graph(restored)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], scad.Solid)
        self.assertAlmostEqual(results[0].get_volume(), swept.get_volume(), places=4)

    def test_replay_linear_pattern_roundtrip(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 1.0, 1.0)
            pattern = scad.linear_pattern_rsolidlist(box, (1, 0, 0), 4, 1.5)

        restored = import_graph_json(export_graph_json(session.graph))
        results = replay_graph(restored)

        self.assertEqual(len(results), 4)
        self.assertTrue(all(isinstance(shape, scad.Solid) for shape in results))
        self.assertAlmostEqual(
            sum(s.get_volume() for s in results),
            sum(s.get_volume() for s in pattern),
            places=5,
        )

    def test_replay_radial_pattern_roundtrip(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 1.0, 1.0)
            pattern = scad.radial_pattern_rsolidlist(
                box, (0, 0, 0), (0, 0, 1), 4, 360.0
            )

        restored = import_graph_json(export_graph_json(session.graph))
        results = replay_graph(restored)

        self.assertEqual(len(results), 4)
        self.assertTrue(all(isinstance(shape, scad.Solid) for shape in results))
        self.assertAlmostEqual(
            sum(s.get_volume() for s in results),
            sum(s.get_volume() for s in pattern),
            places=5,
        )

    def test_replay_missing_required_param_raises_by_default(self):
        graph = OperationGraph()
        graph.add_node("make_point_rvertex", {"x": 1.0, "y": 2.0})

        with self.assertRaises(ValueError):
            replay_graph(graph)

    def test_graph_import_missing_input_raises_by_default(self):
        payload = {
            "graph_id": "g_missing_input",
            "nodes": [
                {
                    "node_id": "n1",
                    "op": "make_translate_rshape",
                    "params": {"vector": (1.0, 0.0, 0.0)},
                    "inputs": ["missing"],
                    "output_count": 1,
                    "tags": [],
                }
            ],
            "edges": [],
        }

        with self.assertRaises(ValueError):
            OperationGraph.from_dict(payload)

    def test_replay_leaf_without_output_raises_by_default(self):
        graph = OperationGraph()
        graph.add_node(
            "make_union_rsolid",
            {"input_count": 0, "clean": True, "glue": True, "tol": None},
        )

        with self.assertRaises(ValueError):
            replay_graph(graph)

    def test_replay_unknown_op_raises_by_default(self):
        graph = OperationGraph()
        graph.add_node("make_unknown_rsolid", {})

        with self.assertRaises(ValueError):
            replay_graph(graph)

    def test_replay_cut_uses_recorded_skip_non_intersecting_flag(self):
        with scad.GraphSession() as session:
            body = scad.make_box_rsolid(1.0, 1.0, 1.0)
            tool = scad.make_box_rsolid(
                1.0, 1.0, 1.0, bottom_face_center=(10.0, 10.0, 0.0)
            )
            scad.cut_rsolid(body, tool, skip_non_intersecting=True)

        payload = json.loads(scad.export_model_json(session))
        cut_node = next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_cut_rsolid"
        )
        self.assertTrue(cut_node["params"]["skip_non_intersecting"])

        replayed = scad.replay_model_json(json.dumps(payload))
        self.assertEqual(len(replayed), 1)
        self.assertIsInstance(replayed[0], scad.Solid)

    def test_replay_cut_defaults_missing_skip_non_intersecting_to_false(self):
        with scad.GraphSession() as session:
            body = scad.make_box_rsolid(1.0, 1.0, 1.0)
            tool = scad.make_box_rsolid(
                1.0, 1.0, 1.0, bottom_face_center=(10.0, 10.0, 0.0)
            )
            scad.cut_rsolid(body, tool, skip_non_intersecting=True)

        payload = json.loads(scad.export_model_json(session))
        cut_node = next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_cut_rsolid"
        )
        del cut_node["params"]["skip_non_intersecting"]

        with self.assertRaises(ValueError):
            scad.replay_model_json(json.dumps(payload))

    def test_union_replay_preserves_clean_glue_and_tol_params(self):
        with scad.GraphSession() as session:
            a = scad.make_box_rsolid(1.0, 1.0, 1.0, bottom_face_center=(0.0, 0.0, 0.0))
            b = scad.make_box_rsolid(
                1.0, 1.0, 1.0, bottom_face_center=(1.001, 0.0, 0.0)
            )
            original = scad.union_rsolid(a, b, clean=False, glue=False, tol=1e-3)

        payload = json.loads(scad.export_model_json(session))
        union_node = next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_union_rsolid"
        )

        self.assertFalse(union_node["params"]["clean"])
        self.assertFalse(union_node["params"]["glue"])
        self.assertEqual(union_node["params"]["tol"], 1e-3)

        replayed = scad.replay_model_json(json.dumps(payload))
        self.assertAlmostEqual(
            replayed[0].get_volume(), original.get_volume(), places=5
        )

    def test_boolean_replay_defaults_missing_tracking_policy_to_full(self):
        with scad.GraphSession() as session:
            body = scad.make_box_rsolid(4.0, 4.0, 4.0)
            tool = scad.make_cylinder_rsolid(
                0.75,
                6.0,
                bottom_face_center=(0.0, 0.0, -1.0),
            )
            original = scad.cut_rsolid(body, tool)

        payload = json.loads(scad.export_model_json(session))
        cut_node = next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_cut_rsolid"
        )
        self.assertEqual(cut_node["params"].pop("tracking_policy"), "full")

        replayed = scad.replay_model_json(json.dumps(payload))
        self.assertAlmostEqual(
            replayed[0].get_volume(), original.get_volume(), places=6
        )

    def test_replay_selection_cardinality_mismatch_raises_by_default(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)
            scad.fillet_rsolid(box, [box.get_edges(0)], 0.2)

        payload = json.loads(scad.export_model_json(session))
        fillet_node = next(
            node
            for node in payload["graph"]["nodes"]
            if node["op"] == "make_fillet_rsolid"
        )
        fillet_node["params"]["selected_edge_node_ids"] = []
        fillet_node["params"]["selected_edges"] = []
        fillet_node["params"]["selected_edge_indices"] = []
        fillet_node["params"]["selection_query"] = (
            scad.ql.edges().take(2).exactly(2).to_dict()
        )
        fillet_node["params"]["edge_count"] = 1

        restored = import_model_json(json.dumps(payload))["graph"]
        with self.assertRaises(ValueError):
            replay_graph(restored)


if __name__ == "__main__":
    unittest.main()
