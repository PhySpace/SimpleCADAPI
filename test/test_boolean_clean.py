"""cut / intersect unify what they leave split, and a blend never hands back an invalid solid (issue #88).

A cut through the side of a box with a cylinder splits the cylinder wall along the cylinder's parametric seam into two
faces, and the top edge of the notch into a long and a short arc.  OCCT then fillets that top edge wrongly: it returns
an invalid solid with a volume that is too small (case A), or refuses and the diagnosis blames the radius (case B).
The same geometry fillets fine once the faces are unified, which is what union already did and cut did not.
"""

from __future__ import annotations

import unittest

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi.errors import SimpleCADError
from simplecadapi.recording.graph import GraphSession

# the issue's two placements of the cylinder; volumes are what CadQuery and build123d (which clean by default) give
CASE_A = (0.0, 17.5)
CASE_B = (-12.5, -17.5)
VOLUME_A = 29604.46
VOLUME_B = 29811.31


def notch(cx: float, cy: float, **options):
    box = scad.make_box_rsolid(width=40, height=40, depth=20, bottom_face_center=(0, 0, 0))
    cylinder = scad.make_cylinder_rsolid(radius=10, height=40, bottom_face_center=(cx, cy, 10))
    return scad.cut_rsolid(box, cylinder, **options)


def top_edges(solid, z: float = 20.0):
    return [
        edge
        for edge in ql.edges().resolve(solid)
        if abs(edge.get_start_vertex().get_coordinates()[2] - z) < 1e-6
        and abs(edge.get_end_vertex().get_coordinates()[2] - z) < 1e-6
    ]


def is_valid(solid) -> bool:
    return bool(BRepCheck_Analyzer(solid.wrapped).IsValid())


def face_count(solid) -> int:
    return len(ql.faces().resolve(solid))


class TestCutCleans(unittest.TestCase):
    def test_cut_unifies_the_wall_the_seam_split(self):
        self.assertEqual(face_count(notch(*CASE_A)), 8)
        self.assertEqual(face_count(notch(*CASE_A, clean=False)), 9)

    def test_the_cleaned_cut_keeps_its_volume(self):
        self.assertAlmostEqual(notch(*CASE_A).get_volume(), notch(*CASE_A, clean=False).get_volume(), places=3)

    def test_cut_list_and_intersect_clean_by_default_too(self):
        box = scad.make_box_rsolid(width=40, height=40, depth=20, bottom_face_center=(0, 0, 0))
        cylinder = scad.make_cylinder_rsolid(radius=10, height=40, bottom_face_center=(0, 17.5, 10))
        (piece,) = scad.cut_rsolid_list(box, cylinder)
        self.assertEqual(face_count(piece), 8)
        (raw,) = scad.cut_rsolid_list(box, cylinder, clean=False)
        self.assertEqual(face_count(raw), 9)
        # the part of the box inside the cylinder: a cylinder wall cut along its seam is two faces unless unified
        inside = scad.intersect_rsolid(box, cylinder)
        raw_inside = scad.intersect_rsolid(box, cylinder, clean=False)
        self.assertLess(face_count(inside), face_count(raw_inside))
        self.assertAlmostEqual(inside.get_volume(), raw_inside.get_volume(), places=3)


class TestFilletAfterCut(unittest.TestCase):
    def test_case_a_fillets_to_a_valid_solid_with_the_right_volume(self):
        cut = notch(*CASE_A)
        filleted = scad.fillet_rsolid(solid=cut, edges=top_edges(cut), radius=3.0)
        self.assertTrue(is_valid(filleted))
        self.assertAlmostEqual(filleted.get_volume(), VOLUME_A, delta=0.05)

    def test_case_b_fillets_with_the_radius_the_diagnosis_called_too_large(self):
        cut = notch(*CASE_B)
        filleted = scad.fillet_rsolid(solid=cut, edges=top_edges(cut), radius=3.0)
        self.assertTrue(is_valid(filleted))
        self.assertAlmostEqual(filleted.get_volume(), VOLUME_B, delta=0.05)

    def test_an_unclean_cut_no_longer_yields_an_invalid_fillet(self):
        """Case A without the clean-up: OCCT's fillet is invalid. It used to be returned; now it is an error."""
        cut = notch(*CASE_A, clean=False)
        with self.assertRaises(SimpleCADError) as raised:
            scad.fillet_rsolid(solid=cut, edges=top_edges(cut), radius=3.0)
        self.assertIn("not a valid solid", str(raised.exception))

    def test_an_unclean_cut_names_the_split_faces_not_the_radius(self):
        """Case B without the clean-up: the kernel refuses, and the diagnosis says why instead of 'reduce the radius'."""
        cut = notch(*CASE_B, clean=False)
        with self.assertRaises(SimpleCADError) as raised:
            scad.fillet_rsolid(solid=cut, edges=top_edges(cut), radius=3.0)
        message = str(raised.exception)
        self.assertIn("split on a surface", message)
        self.assertIn("clean=True", message)
        self.assertNotIn("Reduce the radius", message)

    def test_a_radius_that_really_is_too_large_is_still_reported_as_such(self):
        cut = notch(*CASE_A)
        with self.assertRaises(SimpleCADError) as raised:
            scad.fillet_rsolid(solid=cut, edges=top_edges(cut), radius=50.0)
        self.assertNotIn("split on a surface", str(raised.exception))


class TestRecordedClean(unittest.TestCase):
    """``clean`` is a recorded parameter like ``skip_non_intersecting``; replay reads it, there is no default for a
    record that lacks it."""

    def record(self, **options):
        with GraphSession() as session:
            notch(*CASE_A, **options)
        return session

    def test_the_flag_is_recorded(self):
        self.assertTrue(self.record().graph.leaf_nodes()[0].params["clean"])
        self.assertFalse(self.record(clean=False).graph.leaf_nodes()[0].params["clean"])

    def test_replay_reproduces_the_recorded_result(self):
        for options, faces in (({}, 8), ({"clean": False}, 9)):
            (replayed,) = scad.replay_graph(self.record(**options).graph)  # the leaf: the cut
            self.assertEqual(face_count(replayed), faces, options)


if __name__ == "__main__":
    unittest.main()
