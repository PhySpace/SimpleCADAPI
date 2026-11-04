"""Tests for tracking transforms and feature operations."""

import unittest
import numpy as np

import simplecadapi as scad
from simplecadapi.topology import TopoKind, TopoEvent, TopoRef, TopoDelta
from simplecadapi.topology.tracking import (
    tracked_translate,
    tracked_rotate,
    tracked_extrude,
    tracked_fillet,
    tracked_chamfer,
    TrackedResult,
)


class TestTrackedTranslate(unittest.TestCase):
    def setUp(self):
        self.box = scad.make_box_rsolid(10, 10, 10)

    def test_translate_returns_tracked_result(self):
        result = tracked_translate(self.box, (5, 0, 0))
        self.assertIsInstance(result, TrackedResult)
        self.assertIsNotNone(result.shape)

    def test_translate_preserves_volume(self):
        result = tracked_translate(self.box, (5, 0, 0))
        self.assertAlmostEqual(
            result.shape.get_volume(), self.box.get_volume(), places=6
        )

    def test_translate_all_faces_modified(self):
        result = tracked_translate(self.box, (5, 0, 0))
        modified = [r for r in result.delta.modified if r.kind == TopoKind.FACE]
        original_faces = len(self.box._iter_faces())
        self.assertEqual(len(modified), original_faces)

    def test_translate_no_generated(self):
        result = tracked_translate(self.box, (5, 0, 0))
        self.assertEqual(len(result.delta.generated), 0)
        self.assertEqual(len(result.delta.deleted), 0)

    def test_translate_result_is_solid(self):
        result = tracked_translate(self.box, (5, 0, 0))
        self.assertIsInstance(result.shape, scad.Solid)


class TestTrackedRotate(unittest.TestCase):
    def setUp(self):
        self.box = scad.make_box_rsolid(10, 10, 10)

    def test_rotate_returns_tracked_result(self):
        result = tracked_rotate(self.box, 45.0, (0, 0, 1))
        self.assertIsInstance(result, TrackedResult)
        self.assertIsNotNone(result.shape)

    def test_rotate_preserves_volume(self):
        result = tracked_rotate(self.box, 45.0, (0, 0, 1))
        self.assertAlmostEqual(
            result.shape.get_volume(), self.box.get_volume(), places=4
        )

    def test_rotate_all_faces_modified(self):
        result = tracked_rotate(self.box, 45.0, (0, 0, 1))
        modified = [r for r in result.delta.modified if r.kind == TopoKind.FACE]
        original_faces = len(self.box._iter_faces())
        self.assertEqual(len(modified), original_faces)

    def test_rotate_no_generated(self):
        result = tracked_rotate(self.box, 45.0, (0, 0, 1))
        self.assertEqual(len(result.delta.generated), 0)


class TestTrackedExtrude(unittest.TestCase):
    def setUp(self):
        self.profile = scad.make_rectangle_rface(5.0, 3.0)

    def test_extrude_returns_tracked_result(self):
        result = tracked_extrude(self.profile, (0, 0, 1), 10.0)
        self.assertIsInstance(result, TrackedResult)
        self.assertIsNotNone(result.shape)

    def test_extrude_has_correct_volume(self):
        result = tracked_extrude(self.profile, (0, 0, 1), 10.0)
        expected_vol = self.profile.get_area() * 10.0
        self.assertAlmostEqual(result.shape.get_volume(), expected_vol, places=5)

    def test_extrude_generates_new_faces(self):
        result = tracked_extrude(self.profile, (0, 0, 1), 10.0)
        self.assertGreater(len(result.delta.generated), 0)

    def test_extrude_has_modified_or_preserved_face(self):
        result = tracked_extrude(self.profile, (0, 0, 1), 10.0)
        # The profile face becomes part of the extruded solid (either modified or
        # generated depending on OCC version)
        has_changes = (
            len(result.delta.modified) > 0
            or len(result.delta.preserved) > 0
            or len(result.delta.generated) > 0
        )
        self.assertTrue(has_changes)


class TestTrackedFillet(unittest.TestCase):
    def setUp(self):
        self.box = scad.make_box_rsolid(10, 10, 10)
        # Select some edges for filleting
        self.edges = [self.box.get_edges(i) for i in range(4)]

    def test_fillet_returns_tracked_result(self):
        result = tracked_fillet(self.box, self.edges, 0.5)
        self.assertIsInstance(result, TrackedResult)
        self.assertIsNotNone(result.shape)

    def test_fillet_volume_decreased(self):
        result = tracked_fillet(self.box, self.edges, 0.5)
        self.assertLess(result.shape.get_volume(), self.box.get_volume())

    def test_fillet_has_modified_faces(self):
        result = tracked_fillet(self.box, self.edges, 0.5)
        # Fillet modifies edge-adjacent faces; OCC may report new toroidal faces
        # as Modified rather than Generated
        total_changes = len(result.delta.modified) + len(result.delta.generated)
        self.assertGreater(total_changes, 0)


class TestTrackedChamfer(unittest.TestCase):
    def setUp(self):
        self.box = scad.make_box_rsolid(10, 10, 10)
        self.edges = [self.box.get_edges(i) for i in range(4)]

    def test_chamfer_returns_tracked_result(self):
        result = tracked_chamfer(self.box, self.edges, 0.5)
        self.assertIsInstance(result, TrackedResult)
        self.assertIsNotNone(result.shape)

    def test_chamfer_volume_decreased(self):
        result = tracked_chamfer(self.box, self.edges, 0.5)
        self.assertLess(result.shape.get_volume(), self.box.get_volume())


if __name__ == "__main__":
    unittest.main()
