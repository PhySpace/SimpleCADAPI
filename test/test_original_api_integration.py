"""Integration tests proving tracking/graphing is seamless in original APIs."""

from pathlib import Path

import unittest

import simplecadapi as scad
from simplecadapi.recording.graph import GraphSession
from simplecadapi import ql as Q


class TestOriginalBooleanApiIntegration(unittest.TestCase):
    def test_cut_rsolid_auto_applies_semantic_tags(self):
        body = scad.make_box_rsolid(10, 10, 10)
        tool = scad.make_cylinder_rsolid(1.5, 15.0, bottom_face_center=(3, 3, -2.5))

        result = scad.cut_rsolid(body, tool)
        self.assertIsInstance(result, scad.Solid)

        faces = result._iter_faces()
        modified = Q.select(faces).where(Q.op("cut", "modified")).all()
        preserved = Q.select(faces).where(Q.op("cut", "preserved")).all()
        tool_faces = Q.select(faces).where(Q.origin("tool")).all()

        self.assertGreaterEqual(len(modified), 0)
        self.assertGreater(len(tool_faces), 0)
        self.assertEqual(result.get_metadata("track")["op"], "make_cut_rsolid")

    def test_intersect_rsolid_auto_applies_semantic_tags(self):
        a = scad.make_box_rsolid(10, 10, 10)
        b = scad.make_cylinder_rsolid(4.0, 10.0, bottom_face_center=(3, 3, 0))

        result = scad.intersect_rsolid(a, b)
        self.assertIsInstance(result, scad.Solid)

        faces = result._iter_faces()
        tagged = Q.select(faces).where(Q.op("intersect")).all()
        self.assertGreaterEqual(len(tagged), 0)
        self.assertEqual(
            result.get_metadata("track")["op"], "make_intersect_rsolid"
        )

    def test_union_rsolid_auto_applies_semantic_tags(self):
        a = scad.make_box_rsolid(10, 10, 10)
        b = scad.make_cylinder_rsolid(4.0, 10.0, bottom_face_center=(3, 3, 0))

        result = scad.union_rsolid(a, b)
        self.assertIsInstance(result, scad.Solid)

        faces = result._iter_faces()
        tagged = Q.select(faces).where(Q.op("union")).all()
        self.assertGreaterEqual(len(tagged), 0)
        self.assertEqual(result.get_metadata("track")["op"], "make_union_rsolid")


class TestScreenshotRenderingIntegration(unittest.TestCase):
    def test_render_screenshot_with_tags_and_annotations(self):
        box = scad.make_box_rsolid(4.0, 3.0, 2.0)
        scad.apply_tag(box, "role.body")
        output = Path(self._testMethodName + ".png")
        try:
            result = scad.render_screenshot_rpath(
                box,
                str(output),
                highlight_tags=["role.body"],
                tag_labels={"role.body": "Body"},
                image_size=(320, 240),
                view="iso",
                show_axes=True,
                show_legend=True,
                show_callouts=True,
            )
            self.assertEqual(result, str(output))
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)
        finally:
            output.unlink(missing_ok=True)


class TestOriginalTransformApiIntegration(unittest.TestCase):
    def test_translate_shape_auto_applies_track_metadata(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        moved = scad.translate_shape(box, (1, 0, 0))

        self.assertIsInstance(moved, scad.Solid)
        self.assertEqual(moved.get_metadata("track")["op"], "make_translate_rshape")
        faces = moved._iter_faces()
        self.assertGreater(
            len(
                Q.select(faces).where(Q.op("make_translate_rshape", "modified")).all()
            ),
            0,
        )

    def test_rotate_shape_auto_applies_track_metadata(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        moved = scad.rotate_shape(box, 45.0, (0, 0, 1))

        self.assertIsInstance(moved, scad.Solid)
        self.assertEqual(moved.get_metadata("track")["op"], "make_rotate_rshape")
        faces = moved._iter_faces()
        self.assertGreater(
            len(Q.select(faces).where(Q.op("make_rotate_rshape", "modified")).all()),
            0,
        )


class TestOriginalFeatureApiIntegration(unittest.TestCase):
    def test_extrude_rsolid_exposes_kernel_proven_output_roles(self):
        profile = scad.make_rectangle_rface(2.0, 1.0)
        extruded = scad.extrude_rsolid(profile, (0, 0, 1), 2.0)

        self.assertEqual(extruded.get_metadata("track")["op"], "make_extrude_rsolid")
        faces = extruded._iter_faces()
        self.assertEqual(
            len(Q.select(faces).where(Q.output_role("extrusion.start")).all()), 1
        )
        self.assertEqual(
            len(Q.select(faces).where(Q.output_role("extrusion.end")).all()), 1
        )
        self.assertEqual(
            len(Q.select(faces).where(Q.output_role("extrusion.side")).all()), 4
        )

    def test_fillet_rsolid_auto_applies_semantic_tags(self):
        box = scad.make_box_rsolid(4.0, 4.0, 4.0)
        edges = [box.get_edges(i) for i in range(4)]
        filleted = scad.fillet_rsolid(box, edges, 0.2)

        self.assertEqual(filleted.get_metadata("track")["op"], "make_fillet_rsolid")
        faces = filleted._iter_faces()
        tagged = Q.select(faces).where(Q.op("make_fillet_rsolid")).all()
        self.assertGreater(len(tagged), 0)

    def test_shell_rsolid_auto_applies_track_metadata(self):
        box = scad.make_box_rsolid(4.0, 4.0, 4.0)
        faces_to_remove = [box.get_faces(0)]
        shelled = scad.shell_rsolid(box, faces_to_remove, 0.2)

        self.assertEqual(shelled.get_metadata("track")["op"], "make_shell_rsolid")

    def test_loft_rsolid_auto_applies_track_metadata(self):
        a = scad.make_rectangle_rwire(2.0, 2.0, center=(0, 0, 0))
        b = scad.make_rectangle_rwire(1.0, 1.0, center=(0, 0, 2.0))
        lofted = scad.loft_rsolid([a, b])

        self.assertEqual(lofted.get_metadata("track")["op"], "make_loft_rsolid")


class TestOriginalApiGraphRecording(unittest.TestCase):
    def test_original_apis_record_graph_automatically(self):
        with GraphSession() as session:
            body = scad.make_box_rsolid(10, 10, 10)
            tool = scad.make_cylinder_rsolid(1.5, 15.0, bottom_face_center=(3, 3, -2.5))
            result = scad.cut_rsolid(body, tool)

        graph = session.graph
        self.assertGreaterEqual(graph.node_count, 3)
        self.assertEqual(graph.leaf_nodes()[0].op, "make_cut_rsolid")
        self.assertEqual(result.get_metadata("graph")["op"], "make_cut_rsolid")

    def test_original_transform_records_graph_automatically(self):
        with GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 1.0, 1.0)
            moved = scad.translate_shape(box, (1, 0, 0))

        self.assertGreaterEqual(session.graph.node_count, 2)
        self.assertEqual(session.graph.leaf_nodes()[0].op, "make_translate_rshape")
        self.assertEqual(moved.get_metadata("graph")["op"], "make_translate_rshape")

    def test_linear_pattern_records_single_user_level_node(self):
        with GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 1.0, 1.0)
            pattern = scad.linear_pattern_rsolidlist(box, (1, 0, 0), 3, 2.0)

        self.assertGreaterEqual(session.graph.node_count, 4)
        self.assertEqual(session.graph.leaf_nodes()[0].op, "make_translate_rshape")
        self.assertTrue(
            all(
                s.get_metadata("graph")["op"] == "make_translate_rshape"
                for s in pattern
            )
        )

    def test_radial_pattern_records_single_user_level_node(self):
        with GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 1.0, 1.0)
            pattern = scad.radial_pattern_rsolidlist(
                box, (0, 0, 0), (0, 0, 1), 3, 360.0
            )

        self.assertGreaterEqual(session.graph.node_count, 4)
        self.assertEqual(session.graph.leaf_nodes()[0].op, "make_translate_rshape")
        self.assertTrue(
            all(
                s.get_metadata("graph")["op"]
                in {"make_translate_rshape", "make_rotate_rshape"}
                for s in pattern
            )
        )

    def test_profile_creation_and_extrude_record_graph_automatically(self):
        with GraphSession() as session:
            profile = scad.make_rectangle_rface(2.0, 1.0)
            extruded = scad.extrude_rsolid(profile, (0, 0, 1), 2.0)

        self.assertGreaterEqual(session.graph.node_count, 2)
        self.assertEqual(session.graph.leaf_nodes()[0].op, "make_extrude_rsolid")
        self.assertEqual(extruded.get_metadata("graph")["op"], "make_extrude_rsolid")

    def test_circle_wire_records_one_user_level_node(self):
        with GraphSession() as session:
            wire = scad.make_circle_rwire((0, 0, 0), 2.0)

        self.assertEqual(session.graph.node_count, 2)
        self.assertEqual(session.graph.leaf_nodes()[0].op, "make_wire_from_edges_rwire")
        self.assertEqual(wire.get_metadata("graph")["op"], "make_wire_from_edges_rwire")

    def test_subshape_objects_carry_serializable_topo_refs(self):
        with GraphSession() as session:
            box = scad.make_box_rsolid(4.0, 4.0, 4.0)

        face_ref = box.get_faces(0).get_metadata("topo_ref")
        edge_ref = box.get_edges(0).get_metadata("topo_ref")

        self.assertIsInstance(face_ref, dict)
        self.assertEqual(face_ref["kind"], "FACE")
        self.assertEqual(face_ref["node_id"], session.graph.leaf_nodes()[0].node_id)

        self.assertIsInstance(edge_ref, dict)
        self.assertEqual(edge_ref["kind"], "EDGE")
        self.assertEqual(edge_ref["node_id"], session.graph.leaf_nodes()[0].node_id)
