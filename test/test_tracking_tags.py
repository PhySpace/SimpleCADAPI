"""Tests for evidence-gated semantic projections from TopoDelta."""

import unittest

import simplecadapi as scad
from simplecadapi import ql as Q
from simplecadapi.topology import TopoDelta
from simplecadapi.topology.tracking import tracked_cut, tracked_union, tracked_extrude
from simplecadapi.topology.autotag import apply_tracking_tags_to_delta


def proven_event(op: str, event: str):
    return Q.and_(
        Q.operation_event(op, event),
        Q.meta("track.status", "==", "proven"),
    )


class TestAutoTagCut(unittest.TestCase):
    def setUp(self):
        self.body = scad.make_box_rsolid(10, 10, 10)
        self.tool = scad.make_cylinder_rsolid(
            2.0, 15.0, bottom_face_center=(3, 3, -2.5)
        )

    def test_cut_result_faces_get_typed_operation_evidence(self):
        result = tracked_cut(self.body, self.tool)
        tagged_solid = apply_tracking_tags_to_delta(
            result.solid, result.delta, result.delta_entries, op="cut"
        )
        faces = tagged_solid._iter_faces()
        has_change = any(
            proven_event("cut", "modified")(face)
            or proven_event("cut", "generated")(face)
            for face in faces
        )
        self.assertTrue(has_change)

    def test_cut_preserved_faces_have_typed_evidence(self):
        result = tracked_cut(self.body, self.tool)
        tagged_solid = apply_tracking_tags_to_delta(
            result.solid, result.delta, result.delta_entries, op="cut"
        )
        faces = tagged_solid._iter_faces()
        preserved = [face for face in faces if proven_event("cut", "preserved")(face)]
        self.assertGreater(len(preserved), 0)

    def test_cut_all_faces_have_tracking_envelopes_not_flat_tracking_tags(self):
        result = tracked_cut(self.body, self.tool)
        tagged_solid = apply_tracking_tags_to_delta(
            result.solid, result.delta, result.delta_entries, op="cut"
        )
        faces = tagged_solid._iter_faces()
        for face in faces:
            track = face.get_metadata("track")
            self.assertEqual(track["schema_version"], "1.0")
            self.assertEqual(track["kind"], "topology_change")
            self.assertEqual(track["operation"], "cut")
            self.assertEqual(track["topo_kind"], "FACE")
            self.assertIn(track["coverage"], {"complete", "partial"})
            self.assertIn(track["status"], {"proven", "unknown"})
            self.assertFalse(
                any(
                    tag.startswith(("op.", "origin."))
                    for tag in scad.list_tags(face)
                )
            )

    def test_cut_origin_roles_are_typed_evidence(self):
        result = tracked_cut(self.body, self.tool)
        tagged_solid = apply_tracking_tags_to_delta(
            result.solid, result.delta, result.delta_entries, op="cut"
        )
        faces = tagged_solid._iter_faces()
        proven = Q.meta("track.status", "==", "proven")
        has_body = any(Q.origin_role("body")(face) and proven(face) for face in faces)
        has_tool = any(Q.origin_role("tool")(face) and proven(face) for face in faces)
        self.assertTrue(has_body)
        self.assertTrue(has_tool)

    def test_unmatched_faces_remain_partial_and_unknown(self):
        solid = scad.make_box_rsolid(1.0, 1.0, 1.0)
        tagged = apply_tracking_tags_to_delta(solid, TopoDelta(), op="cut")

        for face in tagged._iter_faces():
            track = face.get_metadata("track")
            self.assertEqual(track["coverage"], "partial")
            self.assertEqual(track["status"], "unknown")
            self.assertEqual(track["events"], [])
            self.assertEqual(track["origin_roles"], [])
            self.assertEqual(track["witnesses"], [])
            self.assertFalse(Q.operation_event("cut")(face))


class TestAutoTagUnion(unittest.TestCase):
    def setUp(self):
        self.body = scad.make_box_rsolid(10, 10, 10)
        self.tool = scad.make_cylinder_rsolid(4.0, 10.0, bottom_face_center=(3, 3, 0))

    def test_union_faces_have_typed_operation_evidence(self):
        result = tracked_union(self.body, self.tool, glue=False)
        tagged_solid = apply_tracking_tags_to_delta(
            result.solid, result.delta, result.delta_entries, op="union"
        )
        faces = tagged_solid._iter_faces()
        has_union_evidence = any(
            proven_event("union", "modified")(face)
            or proven_event("union", "preserved")(face)
            for face in faces
        )
        self.assertTrue(has_union_evidence)

        section_tracks = [
            edge.get_metadata("track")
            for edge in tagged_solid._iter_edges()
            if edge.get_metadata("track").get("section")
        ]
        self.assertTrue(section_tracks)
        self.assertTrue(
            all(
                {"body", "tool"}.issubset(track["origin_roles"])
                and len(track["witnesses"]) >= 2
                for track in section_tracks
            )
        )


class TestAutoTagExtrude(unittest.TestCase):
    def setUp(self):
        self.profile = scad.make_rectangle_rface(5.0, 3.0)

    def test_extrude_roles_are_kernel_proven_without_geometry_guesses(self):
        result = tracked_extrude(self.profile, (0, 0, 1), 10.0)
        tagged_solid = apply_tracking_tags_to_delta(
            result.shape, result.delta, result.delta_entries, op="extrude"
        )
        faces = tagged_solid._iter_faces()
        self.assertTrue(faces)
        roles = [
            role
            for face in faces
            for role in face.get_metadata("track")["result_roles"]
        ]
        self.assertEqual(roles.count("extrusion.start"), 1)
        self.assertEqual(roles.count("extrusion.end"), 1)
        self.assertEqual(roles.count("extrusion.side"), 4)
        self.assertTrue(all(Q.output_role(role)(face) for face in faces for role in face.get_metadata("track")["result_roles"]))


class TestAutoTagPreservesExisting(unittest.TestCase):
    def test_user_semantics_are_available_only_through_proven_lineage(self):
        body = scad.make_box_rsolid(10, 10, 10)
        for face in body._iter_faces():
            scad.apply_tag(face, "role.source_face")
        tool = scad.make_cylinder_rsolid(2.0, 15.0, bottom_face_center=(3, 3, -2.5))
        result = tracked_cut(body, tool)
        tagged_solid = apply_tracking_tags_to_delta(
            result.solid,
            result.delta,
            result.delta_entries,
            op="cut",
            source_solid=body,
        )
        body_descendants = [
            face
            for face in tagged_solid._iter_faces()
            if Q.origin_role("body")(face)
            and face.get_metadata("track")["status"] == "proven"
        ]

        self.assertTrue(body_descendants)
        self.assertTrue(
            any(
                "role.source_face" in scad.list_tags(face, scope="lineage")
                for face in body_descendants
            )
        )
        self.assertTrue(
            all(
                "role.source_face" not in scad.list_tags(face, scope="effective")
                for face in body_descendants
            )
        )


if __name__ == "__main__":
    unittest.main()
