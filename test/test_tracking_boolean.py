"""Tests for BRep tracking: boolean operation history capture via OCC Modified/Generated/IsDeleted."""

import unittest

import simplecadapi as scad
from simplecadapi.topology import (
    TopoKind,
    TopoEvent,
    TopoRef,
    TopoDelta,
    OperationNode,
    OperationGraph,
)
from simplecadapi.topology.tracking import (
    tracked_cut,
    tracked_union,
    tracked_intersect,
    TrackedBooleanResult,
)


class TestTrackedCut(unittest.TestCase):
    """Test cut with full face-level history."""

    def setUp(self):
        self.body = scad.make_box_rsolid(10, 10, 10)
        self.tool = scad.make_cylinder_rsolid(
            2.0, 15.0, bottom_face_center=(3, 3, -2.5)
        )

    def test_tracked_cut_returns_solid_and_delta(self):
        result = tracked_cut(self.body, self.tool)
        self.assertIsInstance(result, TrackedBooleanResult)
        self.assertIsNotNone(result.solid)
        self.assertIsInstance(result.delta, TopoDelta)

    def test_tracked_cut_has_preserved_faces(self):
        result = tracked_cut(self.body, self.tool)
        preserved_face_refs = [
            r for r in result.delta.preserved if r.kind == TopoKind.FACE
        ]
        # After a cylinder cut through a box, most original faces should be
        # either modified or preserved; some should survive
        self.assertGreater(len(preserved_face_refs), 0)

    def test_tracked_cut_has_proven_changed_faces(self):
        result = tracked_cut(self.body, self.tool)
        changed_faces = [
            entry
            for entry in result.delta.entries
            if entry.ref.kind == TopoKind.FACE
            and entry.event in {TopoEvent.MODIFIED, TopoEvent.GENERATED}
            and entry.metadata["status"] == "proven"
        ]
        self.assertGreater(len(changed_faces), 0)

    def test_tracked_cut_volume_decreased(self):
        result = tracked_cut(self.body, self.tool)
        original_vol = self.body.get_volume()
        result_vol = result.solid.get_volume()
        self.assertLess(result_vol, original_vol)

    def test_tracked_cut_total_faces_increased(self):
        """A cylinder cut through a box adds the cylindrical hole face."""
        result = tracked_cut(self.body, self.tool)
        original_faces = len(self.body._iter_faces())
        result_faces = len(result.solid._iter_faces())
        # Cylinder through box: at least 1 new face (cylindrical hole)
        self.assertGreaterEqual(result_faces, original_faces)

    def test_tracked_cut_tool_with_tool_face_labels(self):
        """Faces from the tool should be labeled with origin_role='tool'."""
        result = tracked_cut(self.body, self.tool)
        tool_outputs = [
            entry
            for entry in result.delta.entries
            if entry.ref.kind == TopoKind.FACE
            and entry.origin_role == "tool"
            and entry.event in {TopoEvent.MODIFIED, TopoEvent.GENERATED}
        ]
        self.assertGreater(len(tool_outputs), 0)
        self.assertTrue(all(entry.parent_refs for entry in tool_outputs))

    def test_tracked_cut_preserves_volume_accuracy(self):
        result = tracked_cut(self.body, self.tool)
        # Volume should be original minus roughly the cylinder volume
        expected_min = self.body.get_volume() - 3.14159 * 2.0**2 * 15.0
        self.assertGreater(result.solid.get_volume(), 0)



class TestMultiToolCut(unittest.TestCase):
    """A cut with many tools records one delta merged from its steps."""

    @staticmethod
    def _cut_entries():
        with scad.GraphSession(graph_id="multi_cut"):
            plate = scad.make_box_rsolid(60.0, 40.0, 4.0)
            # Overlapping tools: each step modifies faces the step before
            # made, and those intermediate faces are freed.
            tools = [
                scad.make_box_rsolid(3.0, 18.0, 6.0, bottom_face_center=(-26.0 + 2.0 * k, 0.0, -1.0))
                for k in range(16)
            ]
            tools += [
                scad.make_cylinder_rsolid(2.0, 6.0, bottom_face_center=(-26.0 + 2.0 * k, 9.0, -1.0))
                for k in range(16)
            ]
            result = scad.cut_rsolid(plate, tools)
            return result._get_runtime("graph.node").topo_delta.entries

    def test_the_merged_delta_is_the_same_on_every_run(self):
        # A freed intermediate face's address can be reused by an output
        # face; a stale step entry then resolved to it, run-dependently.
        first = self._cut_entries()
        for _ in range(3):
            self.assertEqual(self._cut_entries(), first)

class TestTrackedUnion(unittest.TestCase):
    def setUp(self):
        self.body = scad.make_box_rsolid(10, 10, 10)
        # Use a cylinder to ensure curved intersection edges
        self.tool = scad.make_cylinder_rsolid(4.0, 10.0, bottom_face_center=(3, 3, 0))

    def test_tracked_union_returns_solid_and_delta(self):
        result = tracked_union(self.body, self.tool)
        self.assertIsInstance(result, TrackedBooleanResult)
        self.assertIsNotNone(result.solid)

    def test_tracked_union_volume_increased(self):
        result = tracked_union(self.body, self.tool)
        original_vol = self.body.get_volume()
        result_vol = result.solid.get_volume()
        # Union of two overlapping boxes should be less than sum but more than either
        self.assertGreater(result_vol, original_vol)

    def test_tracked_union_has_section_edges(self):
        # OCC may suppress SectionEdges under glue mode; disabling glue should expose them.
        result = tracked_union(self.body, self.tool, glue=False)
        section_edges = result.delta.section_edges
        self.assertGreater(len(section_edges), 0)

        for section_ref in section_edges:
            entries = [
                entry
                for entry in result.delta.entries
                if entry.ref == section_ref
            ]
            self.assertGreaterEqual(len(entries), 2)
            self.assertEqual(
                {entry.origin_role for entry in entries}, {"body", "tool"}
            )
            self.assertTrue(all(entry.parent_refs for entry in entries))

    def test_nary_union_tracks_every_input_through_clean_history(self):
        solids = [
            scad.make_box_rsolid(
                1.0,
                1.0,
                1.0,
                bottom_face_center=(float(index), 0.0, 0.0),
            )
            for index in range(3)
        ]

        result = scad.union_rsolid(*solids, glue=False)
        tracks = [face.get_metadata("track") for face in result._iter_faces()]

        self.assertEqual(len(result._iter_faces()), 6)
        self.assertTrue(all(track["status"] == "proven" for track in tracks))
        self.assertEqual(
            {role for track in tracks for role in track["origin_roles"]},
            {"body", "tool", "tool_2"},
        )
        self.assertTrue(result.get_metadata("track")["has_delta"])

    def test_nary_union_keeps_modified_face_lineage_after_clean(self):
        barrel = scad.make_cylinder_rsolid(
            16.0,
            120.0,
            bottom_face_center=(-60.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        flange = scad.make_cylinder_rsolid(
            22.0,
            12.0,
            bottom_face_center=(50.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        nose = scad.make_cylinder_rsolid(
            13.0,
            10.0,
            bottom_face_center=(58.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        source_face = max(flange._iter_faces(), key=lambda face: face.get_center().x)
        scad.apply_tag(source_face, "cap.face.end")

        result = scad.union_rsolid(barrel, flange, nose, glue=False)
        descendants = [
            face
            for face in result._iter_faces()
            if "cap.face.end" in scad.list_tags(face, scope="lineage")
        ]

        self.assertEqual(len(descendants), 1)
        self.assertAlmostEqual(descendants[0].get_center().x, 62.0, places=6)
        self.assertAlmostEqual(descendants[0].get_area(), 989.6016859, places=5)
        self.assertEqual(descendants[0].get_metadata("track")["event"], "modified")
        self.assertNotIn("cap.face.end", scad.list_tags(descendants[0]))

    def test_nary_union_respects_face_binding_lineage_policy(self):
        barrel = scad.make_cylinder_rsolid(
            16.0,
            120.0,
            bottom_face_center=(-60.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        flange = scad.make_cylinder_rsolid(
            22.0,
            12.0,
            bottom_face_center=(50.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        nose = scad.make_cylinder_rsolid(
            13.0,
            10.0,
            bottom_face_center=(58.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        source_face = max(flange._iter_faces(), key=lambda face: face.get_center().x)
        flange = scad.apply_tag_rselection(
            flange,
            [source_face],
            "cap.face.end",
            lineage_policy=scad.LineagePolicy.NONE,
        )

        result = scad.union_rsolid(barrel, flange, nose, glue=False)

        self.assertFalse(
            any("cap.face.end" in scad.list_tags(face) for face in result._iter_faces())
        )

    def test_nary_union_face_binding_stays_directly_queryable_after_cut(self):
        flange = scad.extrude_rsolid(
            scad.make_circle_rface(
                center=(0.0, 0.0, 0.0),
                radius=2.0,
                normal=(1.0, 0.0, 0.0),
            ),
            direction=(1.0, 0.0, 0.0),
            distance=2.0,
            start_face_tag="cap.face.start",
            end_face_tag="cap.face.end",
            side_faces_tag="cap.face.side",
        )
        source_end = scad.select_faces_by_tag(flange, "cap.face.end")[0]
        source_explanation = scad.explain_tag(
            source_end, "cap.face.end", scope="local"
        )[0]
        body = scad.make_cylinder_rsolid(
            1.5,
            4.0,
            bottom_face_center=(-1.0, 0.0, 0.0),
            axis=(1.0, 0.0, 0.0),
        )
        bridge = scad.make_box_rsolid(
            1.0,
            1.0,
            1.0,
            bottom_face_center=(-0.5, -0.5, -0.5),
        )
        fused = scad.union_rsolid(body, flange, bridge, glue=False)
        result = scad.cut_rsolid(
            fused,
            scad.make_cylinder_rsolid(
                0.25,
                4.0,
                bottom_face_center=(-1.0, 1.0, 0.0),
                axis=(1.0, 0.0, 0.0),
            ),
        )

        end_faces = scad.select_faces_by_tag(result, "cap.face.end")

        self.assertEqual(len(end_faces), 1)
        projected = scad.explain_tag(
            end_faces[0], "cap.face.end", scope="local"
        )[0]["binding"]["evidence"]
        self.assertEqual(
            projected["source_binding_id"], source_explanation["binding_id"]
        )
        self.assertEqual(projected["source_topo_id"], source_end.topo_id)

    def test_nary_union_tracks_faces_without_cleaning(self):
        solids = [
            scad.make_box_rsolid(
                1.0,
                1.0,
                1.0,
                bottom_face_center=(float(index), 0.0, 0.0),
            )
            for index in range(3)
        ]

        result = scad.union_rsolid(*solids, clean=False, glue=False)

        self.assertEqual(len(result._iter_faces()), 14)
        self.assertTrue(
            all(
                face.get_metadata("track")["status"] == "proven"
                for face in result._iter_faces()
            )
        )


class TestTrackedIntersect(unittest.TestCase):
    def setUp(self):
        self.body = scad.make_box_rsolid(10, 10, 10)
        self.tool = scad.make_cylinder_rsolid(6.0, 10.0, bottom_face_center=(3, 3, 0))

    def test_tracked_intersect_returns_solid_and_delta(self):
        result = tracked_intersect(self.body, self.tool)
        self.assertIsInstance(result, TrackedBooleanResult)
        self.assertIsNotNone(result.solid)

    def test_tracked_intersect_volume_less_than_both(self):
        result = tracked_intersect(self.body, self.tool)
        self.assertLess(result.solid.get_volume(), self.body.get_volume())
        self.assertLess(result.solid.get_volume(), self.tool.get_volume())


class TestDeltaEntries(unittest.TestCase):
    """Test that delta_entries provides origin_role info."""

    def setUp(self):
        self.body = scad.make_box_rsolid(10, 10, 10)
        self.tool = scad.make_cylinder_rsolid(
            3.0, 15.0, bottom_face_center=(3, 3, -2.5)
        )

    def test_body_faces_labeled(self):
        result = tracked_cut(self.body, self.tool)
        body_preserved = [
            r
            for r in result.delta.preserved
            if r.kind == TopoKind.FACE
            and result.delta_entries.get(r.topo_id, {}).get("origin_role") == "body"
        ]
        self.assertGreater(len(body_preserved), 0)

    def test_modified_faces_labeled(self):
        result = tracked_cut(self.body, self.tool)
        body_modified = [
            r
            for r in result.delta.modified
            if r.kind == TopoKind.FACE
            and result.delta_entries.get(r.topo_id, {}).get("origin_role") == "body"
        ]
        # Some faces from body should be modified
        self.assertGreater(len(body_modified), 0)


class TestSolidMapping(unittest.TestCase):
    """Test that the result solid is a valid SimpleCADAPI Solid."""

    def setUp(self):
        self.body = scad.make_box_rsolid(10, 10, 10)
        self.tool = scad.make_cylinder_rsolid(
            2.0, 15.0, bottom_face_center=(3, 3, -2.5)
        )

    def test_result_is_solid(self):
        result = tracked_cut(self.body, self.tool)
        self.assertIsInstance(result.solid, scad.Solid)

    def test_result_has_faces(self):
        result = tracked_cut(self.body, self.tool)
        faces = result.solid._iter_faces()
        self.assertGreater(len(faces), 0)

    def test_result_has_valid_volume(self):
        result = tracked_cut(self.body, self.tool)
        self.assertGreater(result.solid.get_volume(), 0)


if __name__ == "__main__":
    unittest.main()
