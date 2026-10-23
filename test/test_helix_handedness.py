"""Helix handedness tests."""

from __future__ import annotations

import math
import unittest

import simplecadapi as scad
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve


def _helix_turns_and_rise(edge):
    adaptor = BRepAdaptor_Curve(edge.wrapped)
    t0, t1 = adaptor.FirstParameter(), adaptor.LastParameter()
    samples = 400
    prev_theta = None
    total = 0.0
    for index in range(samples + 1):
        point = adaptor.Value(t0 + (t1 - t0) * index / samples)
        theta = math.atan2(point.Y(), point.X())
        if prev_theta is not None:
            delta = theta - prev_theta
            while delta > math.pi:
                delta -= 2 * math.pi
            while delta < -math.pi:
                delta += 2 * math.pi
            total += delta
        prev_theta = theta
    z0 = adaptor.Value(t0).Z()
    z1 = adaptor.Value(t1).Z()
    return total / (2 * math.pi), z1 - z0


class TestHelixHandedness(unittest.TestCase):
    def test_right_handed_winds_counterclockwise_ascending(self):
        edge = scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0)
        turns, rise = _helix_turns_and_rise(edge)
        self.assertAlmostEqual(turns, 5.0, places=3)
        self.assertAlmostEqual(rise, 10.0, places=6)

    def test_left_handed_winds_clockwise_ascending(self):
        edge = scad.make_helix_redge(
            pitch=2.0, height=10.0, radius=3.0, handedness="Left"
        )
        turns, rise = _helix_turns_and_rise(edge)
        self.assertAlmostEqual(turns, -5.0, places=3)
        self.assertAlmostEqual(rise, 10.0, places=6)

    def test_handedness_keeps_radius_and_length(self):
        right = scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0)
        left = scad.make_helix_redge(
            pitch=2.0, height=10.0, radius=3.0, handedness="Left"
        )
        self.assertAlmostEqual(
            right.get_length(), left.get_length(), places=6
        )

    def test_invalid_handedness_is_rejected(self):
        with self.assertRaises(Exception):
            scad.make_helix_redge(
                pitch=2.0, height=10.0, radius=3.0, handedness="wrong"
            )

    def test_left_handed_sweep_builds_a_solid(self):
        profile = scad.make_wire_from_edges_rwire(
            [scad.make_circle_redge((3.4, 0.0, 0.0), 0.3)]
        )
        solid = scad.helical_sweep_rsolid(
            profile, pitch=2.0, height=6.0, radius=3.0, handedness="Left"
        )
        self.assertGreater(solid.get_volume(), 0.0)
        spring = scad.helical_sweep_rsolid(
            profile, pitch=2.0, height=6.0, radius=3.0, handedness="Right"
        )
        self.assertAlmostEqual(
            solid.get_volume(), spring.get_volume(), places=6
        )

    def test_left_handed_freecad_script_uses_makehelix(self):
        from simplecadapi.recording.graph import GraphSession
        from simplecadapi.recording.serializer import import_model_json
        from simplecadapi.translator.freecad_translator.translator import (
            _FreeCADCompiler,
        )

        with GraphSession() as session:
            scad.make_helix_redge(
                pitch=2.0, height=10.0, radius=3.0, handedness="Left"
            )
            payload = scad.export_model_json(session)

        script = _FreeCADCompiler().translate_model_payload_to_script(
            import_model_json(payload)
        )
        self.assertIn("Part.makeHelix", script)
        self.assertIn("True", script)

        with GraphSession() as session:
            scad.make_helix_redge(pitch=2.0, height=10.0, radius=3.0)
            payload = scad.export_model_json(session)
        script = _FreeCADCompiler().translate_model_payload_to_script(
            import_model_json(payload)
        )
        self.assertIn("Part::Helix", script)


if __name__ == "__main__":
    unittest.main()
