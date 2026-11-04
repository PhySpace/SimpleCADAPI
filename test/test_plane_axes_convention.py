"""Plane-axis convention regression tests.

`_orthonormal_plane_axes` must build the in-plane frame by projecting the
reference vector onto the plane, so a +z normal yields exactly the global
(x, y, z) frame. Planar profile makers that use the helper (currently
`make_rectangle_rwire`, session and legacy paths) then agree with
`make_box_rsolid`'s width-along-x convention. The previous cross-product
basis rotated every profile by 90 degrees for +z normals (width landed on
global y).
"""

import unittest

import numpy as np

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.operators._support import _orthonormal_plane_axes


class TestOrthonormalPlaneAxes(unittest.TestCase):
    def test_z_normal_frame_matches_box_convention(self):
        z_axis, x_axis, y_axis = _orthonormal_plane_axes((0.0, 0.0, 1.0))
        np.testing.assert_allclose(z_axis, (0.0, 0.0, 1.0), atol=1e-12)
        np.testing.assert_allclose(x_axis, (1.0, 0.0, 0.0), atol=1e-12)
        np.testing.assert_allclose(y_axis, (0.0, 1.0, 0.0), atol=1e-12)

    def test_frames_are_unit_right_handed_and_transverse(self):
        normals = [
            (0.3, -0.4, 0.86),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, -1.0),
            (0.2, 0.98, 0.05),
        ]
        for normal in normals:
            with self.subTest(normal=normal):
                z_axis, x_axis, y_axis = _orthonormal_plane_axes(normal)
                np.testing.assert_allclose(np.linalg.norm(z_axis), 1.0, atol=1e-12)
                np.testing.assert_allclose(np.linalg.norm(x_axis), 1.0, atol=1e-12)
                np.testing.assert_allclose(np.linalg.norm(y_axis), 1.0, atol=1e-12)
                np.testing.assert_allclose(x_axis @ z_axis, 0.0, atol=1e-12)
                np.testing.assert_allclose(y_axis @ z_axis, 0.0, atol=1e-12)
                np.testing.assert_allclose(
                    np.cross(x_axis, y_axis), z_axis, atol=1e-12
                )

    def test_zero_normal_is_rejected(self):
        with self.assertRaises(ValueError):
            _orthonormal_plane_axes((0.0, 0.0, 0.0))


class TestRectangleAxisConvention(unittest.TestCase):
    @staticmethod
    def _edge_inventory(use_session: bool):
        def build():
            return scad.make_rectangle_rwire(30.0, 10.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))

        if use_session:
            with scad.GraphSession(graph_id="rect_axes_session"):
                wire = build()
        else:
            wire = build()
        inventory = []
        for edge in ql.edges().resolve(wire):
            center = edge.get_center()
            inventory.append(
                (round(center.x, 3), round(center.y, 3), round(edge.get_length(), 3))
            )
        return sorted(inventory)

    def test_width_spans_x_on_session_path(self):
        self.assertEqual(
            self._edge_inventory(use_session=True),
            [
                (-15.0, -0.0, 10.0),
                (0.0, -5.0, 30.0),
                (0.0, 5.0, 30.0),
                (15.0, 0.0, 10.0),
            ],
        )

    def test_width_spans_x_on_legacy_path(self):
        self.assertEqual(
            self._edge_inventory(use_session=False),
            [
                (-15.0, -0.0, 10.0),
                (0.0, -5.0, 30.0),
                (0.0, 5.0, 30.0),
                (15.0, 0.0, 10.0),
            ],
        )


if __name__ == "__main__":
    unittest.main()
