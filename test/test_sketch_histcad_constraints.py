"""HistCAD-driven sketch constraint coverage tests.

Covers the constraint kinds added for HistCAD sequence translation: driving
angle, line-to-line minimum distance, point-pair horizontal/vertical
alignment, normal (line through curve center), entity mirror, and the
two-point midpoint form.
"""

from __future__ import annotations

import math
import unittest

import simplecadapi as scad


def _point(sketch, name, x, y):
    return scad.add_point_rsketch(sketch, name, x, y)


def _line(sketch, name, start, end):
    return scad.add_line_rsketch(sketch, name, start, end)


class TestDrivingAngleConstraint(unittest.TestCase):
    def _two_line_sketch(self, b_initial_deg: float):
        sketch = scad.make_sketch_rsketch("angle")
        sketch = _point(sketch, "p0", 0.0, 0.0)
        sketch = _point(sketch, "p1", 4.0, 0.0)
        sketch = _point(sketch, "p2", 1.0, 1.0)
        radians = math.radians(b_initial_deg)
        sketch = _point(
            sketch,
            "p3",
            1.0 + 3.0 * math.cos(radians),
            1.0 + 3.0 * math.sin(radians),
        )
        sketch = _line(sketch, "a", "p0", "p1")
        sketch = _line(sketch, "b", "p2", "p3")
        sketch = scad.constrain_fix_rsketch(sketch, "p0")
        sketch = scad.constrain_fix_rsketch(sketch, "p1")
        sketch = scad.constrain_fix_rsketch(sketch, "p2")
        sketch = scad.constrain_length_rsketch(sketch, "b", 3.0)
        return sketch

    def _directed_angle(self, result):
        p2 = result.solved_points["p2"]
        p3 = result.solved_points["p3"]
        return math.degrees(
            math.atan2(p3[1] - p2[1], p3[0] - p2[0])
        ) % 360.0

    def test_driving_angle_holds_each_directed_branch(self):
        for directed in (30.0, 150.0, 200.0, 330.0):
            with self.subTest(directed=directed):
                sketch = self._two_line_sketch(directed)
                sketch = scad.constrain_angle_rsketch(sketch, "a", "b", directed)

                result = scad.inspect_sketch_rsketchresult(
                    sketch, require_fully_constrained=True
                )
                self.assertEqual(result.status, "solved")
                measured = self._directed_angle(result)
                self.assertAlmostEqual(
                    measured, directed, places=5,
                    msg=f"directed {directed} deg branch not held",
                )

    def test_driving_angle_converges_from_perturbed_same_basin(self):
        sketch = self._two_line_sketch(207.0)
        sketch = scad.constrain_angle_rsketch(sketch, "a", "b", 200.0)

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(self._directed_angle(result), 200.0, places=5)

    def test_zero_angle_redirects_to_parallel_guidance(self):
        sketch = self._two_line_sketch(0.5)
        sketch = scad.constrain_angle_rsketch(sketch, "a", "b", 0.0)
        with self.assertRaises(Exception) as ctx:
            scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn("parallel", str(ctx.exception))

    def test_reference_angle_measures_directed_value_modulo_360(self):
        sketch = self._two_line_sketch(200.0)
        sketch = scad.constrain_fix_rsketch(sketch, "p3")
        sketch = scad.constrain_angle_rsketch(
            sketch, "a", "b", 99.0, constraint_id="measured", driving=False
        )
        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(
            result.solved_scalars["constraint:measured:value"], 200.0, places=5
        )


class TestLineDistanceConstraint(unittest.TestCase):
    def _offset_sketch(self, initial_offset: float):
        sketch = scad.make_sketch_rsketch("offset")
        sketch = _point(sketch, "b0", 0.0, 0.0)
        sketch = _point(sketch, "b1", 5.0, 0.0)
        sketch = _point(sketch, "a0", 1.0, initial_offset)
        sketch = _point(sketch, "a1", 5.0, initial_offset)
        sketch = _line(sketch, "base", "b0", "b1")
        sketch = _line(sketch, "offset", "a0", "a1")
        sketch = scad.constrain_fix_rsketch(sketch, "b0")
        sketch = scad.constrain_fix_rsketch(sketch, "b1")
        sketch = scad.constrain_length_rsketch(sketch, "offset", 4.0)
        sketch = scad.constrain_parallel_rsketch(sketch, "offset", "base")
        sketch = scad.constrain_distance_x_rsketch(
            sketch, "b0", "a0", 1.0 + initial_offset * 0.0
        )
        return sketch

    def test_line_distance_drives_minimum_offset(self):
        sketch = self._offset_sketch(2.1)
        sketch = scad.constrain_line_distance_rsketch(sketch, "offset", "base", 2.5)

        result = scad.inspect_sketch_rsketchresult(
            sketch, require_fully_constrained=True
        )
        self.assertEqual(result.status, "solved")
        a0 = result.solved_points["a0"]
        a1 = result.solved_points["a1"]
        self.assertAlmostEqual(a0[1], 2.5, places=6)
        self.assertAlmostEqual(a1[1], 2.5, places=6)

    def test_line_distance_keeps_initial_side_below(self):
        sketch = self._offset_sketch(-1.8)
        sketch = scad.constrain_line_distance_rsketch(sketch, "offset", "base", 2.5)

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        a0 = result.solved_points["a0"]
        self.assertAlmostEqual(a0[1], -2.5, places=6)

    def test_line_distance_reference_measures_perpendicular_gap(self):
        sketch = self._offset_sketch(3.0)
        sketch = scad.constrain_line_distance_rsketch(
            sketch, "offset", "base", 99.0,
            constraint_id="measured", driving=False,
        )
        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(
            result.solved_scalars["constraint:measured:value"], 3.0, places=6
        )

    def test_line_distance_rejects_non_positive_value(self):
        sketch = self._offset_sketch(2.0)
        sketch = scad.constrain_line_distance_rsketch(sketch, "offset", "base", -1.0)
        with self.assertRaises(Exception):
            scad.inspect_sketch_rsketchresult(sketch)


class TestPointsAlignmentConstraints(unittest.TestCase):
    def test_points_horizontal_aligns_y(self):
        sketch = scad.make_sketch_rsketch("align")
        sketch = _point(sketch, "a", 0.0, 1.2)
        sketch = _point(sketch, "b", 4.0, 3.9)
        sketch = scad.constrain_fix_rsketch(sketch, "a")
        sketch = scad.constrain_points_horizontal_rsketch(sketch, "a", "b")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(result.solved_points["b"][1], 1.2, places=6)

    def test_points_vertical_aligns_x(self):
        sketch = scad.make_sketch_rsketch("align")
        sketch = _point(sketch, "a", 1.5, 0.0)
        sketch = _point(sketch, "b", 4.7, 3.0)
        sketch = scad.constrain_fix_rsketch(sketch, "a")
        sketch = scad.constrain_points_vertical_rsketch(sketch, "a", "b")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(result.solved_points["b"][0], 1.5, places=6)


class TestNormalConstraint(unittest.TestCase):
    def test_normal_moves_line_through_curve_center(self):
        sketch = scad.make_sketch_rsketch("normal")
        sketch = _point(sketch, "c", 0.0, 0.0)
        sketch = scad.add_circle_rsketch(sketch, "circle", "c", 1.0)
        sketch = _point(sketch, "p0", 0.5, 0.5)
        sketch = _point(sketch, "p1", 2.0, 2.4)
        sketch = _line(sketch, "probe", "p0", "p1")
        sketch = scad.constrain_fix_rsketch(sketch, "c")
        sketch = scad.constrain_radius_rsketch(sketch, "circle", 1.0)
        sketch = scad.constrain_fix_rsketch(sketch, "p0")
        sketch = scad.constrain_length_rsketch(sketch, "probe", 3.0)
        sketch = scad.constrain_normal_rsketch(sketch, "probe", "circle")

        result = scad.inspect_sketch_rsketchresult(
            sketch, require_fully_constrained=True
        )
        self.assertEqual(result.status, "solved")
        p0 = result.solved_points["p0"]
        p1 = result.solved_points["p1"]
        cross = p0[0] * p1[1] - p0[1] * p1[0]
        self.assertAlmostEqual(cross, 0.0, places=7)

    def test_normal_accepts_reversed_argument_order(self):
        sketch = scad.make_sketch_rsketch("normal")
        sketch = _point(sketch, "c", 0.0, 0.0)
        sketch = scad.add_circle_rsketch(sketch, "arc_circle", "c", 1.0)
        sketch = _point(sketch, "p0", 0.5, 0.5)
        sketch = _point(sketch, "p1", 2.0, 2.4)
        sketch = _line(sketch, "probe", "p0", "p1")
        sketch = scad.constrain_fix_rsketch(sketch, "c")
        sketch = scad.constrain_fix_rsketch(sketch, "p0")
        sketch = scad.constrain_length_rsketch(sketch, "probe", 3.0)
        sketch = scad.constrain_normal_rsketch(sketch, "arc_circle", "probe")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})


class TestMirrorConstraint(unittest.TestCase):
    def _mirror_sketch(self):
        sketch = scad.make_sketch_rsketch("mirror")
        sketch = _point(sketch, "a0", 0.0, 0.0)
        sketch = _point(sketch, "a1", 0.0, 4.0)
        sketch = _line(sketch, "axis", "a0", "a1")
        sketch = _point(sketch, "m0", 1.0, 1.0)
        sketch = _point(sketch, "m1", 1.0, 3.0)
        sketch = _line(sketch, "source", "m0", "m1")
        sketch = _point(sketch, "n0", -1.25, 1.1)
        sketch = _point(sketch, "n1", -1.1, 2.85)
        sketch = _line(sketch, "image", "n0", "n1")
        sketch = scad.constrain_fix_rsketch(sketch, "a0")
        sketch = scad.constrain_fix_rsketch(sketch, "a1")
        sketch = scad.constrain_fix_rsketch(sketch, "m0")
        sketch = scad.constrain_fix_rsketch(sketch, "m1")
        return sketch

    def test_mirror_snaps_image_line_about_axis(self):
        sketch = self._mirror_sketch()
        sketch = scad.constrain_mirror_rsketch(
            sketch, "image", "axis", "source"
        )

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(result.solved_points["n0"][0], -1.0, places=6)
        self.assertAlmostEqual(result.solved_points["n0"][1], 1.0, places=6)
        self.assertAlmostEqual(result.solved_points["n1"][0], -1.0, places=6)
        self.assertAlmostEqual(result.solved_points["n1"][1], 3.0, places=6)

    def test_mirror_matches_flipped_endpoint_pairing(self):
        sketch = scad.make_sketch_rsketch("mirror")
        sketch = _point(sketch, "a0", 0.0, 0.0)
        sketch = _point(sketch, "a1", 0.0, 4.0)
        sketch = _line(sketch, "axis", "a0", "a1")
        # image stored reversed: n0 mirrors m1, n1 mirrors m0
        sketch = _point(sketch, "m0", 1.0, 1.0)
        sketch = _point(sketch, "m1", 1.0, 3.0)
        sketch = _line(sketch, "source", "m0", "m1")
        sketch = _point(sketch, "n0", -1.1, 2.9)
        sketch = _point(sketch, "n1", -1.2, 1.15)
        sketch = _line(sketch, "image", "n0", "n1")
        sketch = scad.constrain_fix_rsketch(sketch, "a0")
        sketch = scad.constrain_fix_rsketch(sketch, "a1")
        sketch = scad.constrain_fix_rsketch(sketch, "m0")
        sketch = scad.constrain_fix_rsketch(sketch, "m1")
        sketch = scad.constrain_mirror_rsketch(sketch, "image", "axis", "source")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(result.solved_points["n0"][1], 3.0, places=6)
        self.assertAlmostEqual(result.solved_points["n1"][1], 1.0, places=6)

    def test_mirror_circle_centers(self):
        sketch = scad.make_sketch_rsketch("mirror")
        sketch = _point(sketch, "a0", 0.0, 0.0)
        sketch = _point(sketch, "a1", 0.0, 4.0)
        sketch = _line(sketch, "axis", "a0", "a1")
        sketch = _point(sketch, "mc", 2.0, 2.0)
        sketch = scad.add_circle_rsketch(sketch, "source", "mc", 0.5)
        sketch = _point(sketch, "nc", -1.7, 2.2)
        sketch = scad.add_circle_rsketch(sketch, "image", "nc", 0.5)
        sketch = scad.constrain_fix_rsketch(sketch, "a0")
        sketch = scad.constrain_fix_rsketch(sketch, "a1")
        sketch = scad.constrain_fix_rsketch(sketch, "mc")
        sketch = scad.constrain_mirror_rsketch(sketch, "image", "axis", "source")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(result.solved_points["nc"][0], -2.0, places=6)
        self.assertAlmostEqual(result.solved_points["nc"][1], 2.0, places=6)


class TestMidpointPointsConstraint(unittest.TestCase):
    def test_midpoint_snaps_to_segment_center(self):
        sketch = scad.make_sketch_rsketch("midpoint")
        sketch = _point(sketch, "a", 0.0, 0.0)
        sketch = _point(sketch, "b", 4.0, 2.0)
        sketch = _point(sketch, "m", 1.8, 0.9)
        sketch = scad.constrain_fix_rsketch(sketch, "a")
        sketch = scad.constrain_fix_rsketch(sketch, "b")
        sketch = scad.constrain_midpoint_points_rsketch(sketch, "m", "a", "b")

        result = scad.inspect_sketch_rsketchresult(
            sketch, require_fully_constrained=True
        )
        self.assertEqual(result.status, "solved")
        self.assertAlmostEqual(result.solved_points["m"][0], 2.0, places=6)
        self.assertAlmostEqual(result.solved_points["m"][1], 1.0, places=6)

    def test_midpoint_rejects_duplicate_points(self):
        sketch = scad.make_sketch_rsketch("midpoint")
        sketch = _point(sketch, "a", 0.0, 0.0)
        sketch = _point(sketch, "b", 4.0, 2.0)
        sketch = scad.constrain_midpoint_points_rsketch(sketch, "a", "a", "b")
        with self.assertRaises(Exception):
            scad.inspect_sketch_rsketchresult(sketch)


class TestNewConstraintSerialization(unittest.TestCase):
    def test_new_kinds_round_trip_through_dict(self):
        import json

        sketch = scad.make_sketch_rsketch("serial")
        sketch = _point(sketch, "p0", 0.0, 0.0)
        sketch = _point(sketch, "p1", 4.0, 0.0)
        sketch = _point(sketch, "p2", 1.0, 2.0)
        sketch = _line(sketch, "a", "p0", "p1")
        sketch = _line(sketch, "b", "p1", "p2")
        sketch = scad.constrain_points_horizontal_rsketch(sketch, "p0", "p1")
        sketch = scad.constrain_line_distance_rsketch(sketch, "b", "a", 2.0)
        sketch = scad.constrain_angle_rsketch(sketch, "a", "b", 116.565)
        sketch = scad.constrain_mirror_rsketch(sketch, "a", "b", "a")
        sketch = scad.constrain_normal_rsketch(sketch, "a", "b")
        sketch = scad.constrain_midpoint_points_rsketch(sketch, "p0", "p1", "p2")

        restored = scad.Sketch.from_dict(json.loads(json.dumps(sketch.to_dict())))
        kinds = sorted(
            f"{constraint.kind}:{len(constraint.targets)}"
            for constraint in restored.constraints
        )
        self.assertEqual(
            kinds,
            [
                "angle:2",
                "line_distance:2",
                "midpoint_points:3",
                "mirror:3",
                "normal:2",
                "points_horizontal:2",
            ],
        )


class TestSymmetricRegression(unittest.TestCase):
    """Regression: the symmetric lowering used addSymmetricLine, which
    mirrors about the workplane u-axis regardless of the axis entity."""

    def test_symmetric_about_vertical_axis(self):
        sketch = scad.make_sketch_rsketch("sym")
        sketch = _point(sketch, "a0", 0.0, 0.0)
        sketch = _point(sketch, "a1", 0.0, 4.0)
        sketch = _line(sketch, "axis", "a0", "a1")
        sketch = _point(sketch, "p", 2.0, 2.0)
        sketch = _point(sketch, "q", -1.7, 2.2)
        sketch = scad.constrain_fix_rsketch(sketch, "a0")
        sketch = scad.constrain_fix_rsketch(sketch, "a1")
        sketch = scad.constrain_fix_rsketch(sketch, "p")
        sketch = scad.constrain_symmetric_rsketch(sketch, "q", "p", "axis")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        q = result.solved_points["q"]
        self.assertAlmostEqual(q[0], -2.0, places=6)
        self.assertAlmostEqual(q[1], 2.0, places=6)

    def test_symmetric_about_diagonal_axis(self):
        sketch = scad.make_sketch_rsketch("sym")
        sketch = _point(sketch, "a0", 0.0, 0.0)
        sketch = _point(sketch, "a1", 3.0, 3.0)
        sketch = _line(sketch, "axis", "a0", "a1")
        sketch = _point(sketch, "p", 1.0, 3.0)
        sketch = _point(sketch, "q", 2.6, 1.2)
        sketch = scad.constrain_fix_rsketch(sketch, "a0")
        sketch = scad.constrain_fix_rsketch(sketch, "a1")
        sketch = scad.constrain_fix_rsketch(sketch, "p")
        sketch = scad.constrain_symmetric_rsketch(sketch, "q", "p", "axis")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        q = result.solved_points["q"]
        self.assertAlmostEqual(q[0], 3.0, places=5)
        self.assertAlmostEqual(q[1], 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
