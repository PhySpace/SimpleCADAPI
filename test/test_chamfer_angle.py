"""Angled (asymmetric) chamfer tests."""

from __future__ import annotations

import math
import unittest

import simplecadapi as scad
from simplecadapi import ql


def _top_edge_selector():
    return ql.edges().where(
        ql.and_(
            ql.curve_type("LINE"),
            ql.prop("geom.center.z", ">", 9.999),
            ql.prop("geom.center.y", "<", -4.999),
        )
    ).exactly(1)


class TestAngledChamfer(unittest.TestCase):
    def setUp(self):
        self.box = scad.make_box_rsolid(width=10.0, height=10.0, depth=10.0)
        self.edge_length = 10.0

    def _removed(self, solid):
        return 1000.0 - solid.get_volume()

    def test_symmetric_chamfer_is_unchanged_default(self):
        solid = scad.chamfer_rsolid(self.box, _top_edge_selector(), 1.0)
        self.assertAlmostEqual(self._removed(solid), 0.5 * 1.0 * 1.0 * 10.0, places=6)

    def test_angled_chamfer_removes_tangent_wedge(self):
        for angle in (15.0, 30.0, 60.0, 75.0):
            with self.subTest(angle=angle):
                solid = scad.chamfer_rsolid(
                    self.box,
                    _top_edge_selector(),
                    1.0,
                    angle=angle,
                    reference_direction=(0.0, 0.0, 1.0),
                )
                expected = 0.5 * 1.0 * math.tan(math.radians(angle)) * self.edge_length
                self.assertAlmostEqual(self._removed(solid), expected, places=6)

    def test_distance_lands_on_reference_face(self):
        from simplecadapi._cpp.occt.Bnd import Bnd_Box
        from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib

        solid = scad.chamfer_rsolid(
            self.box,
            _top_edge_selector(),
            1.0,
            angle=30.0,
            reference_direction=(0.0, 0.0, 1.0),
        )
        chamfer_faces = [
            face
            for face in ql.faces().where(ql.surface_type("PLANE")).resolve(solid)
            if abs(face.get_center().z - 10.0) < 2.0
            and abs(face.get_center().y + 5.0) < 2.0
            and abs(face.get_center().x) < 0.1
        ]
        self.assertEqual(len(chamfer_faces), 1)
        box = Bnd_Box()
        BRepBndLib.Add_s(chamfer_faces[0].wrapped, box)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        self.assertAlmostEqual(ymax + 5.0, 1.0, places=6)  # leg on reference face
        self.assertAlmostEqual(10.0 - zmin, math.tan(math.radians(30.0)), places=6)

    def test_angle_requires_reference_direction(self):
        with self.assertRaises(Exception):
            scad.chamfer_rsolid(self.box, _top_edge_selector(), 1.0, angle=30.0)

    def test_angle_must_be_inside_exclusive_range(self):
        for bad in (-5.0, 0.0, 90.0, 120.0):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                scad.chamfer_rsolid(
                    self.box,
                    _top_edge_selector(),
                    1.0,
                    angle=bad,
                    reference_direction=(0.0, 0.0, 1.0),
                )

    def test_angle_params_recorded_in_graph(self):
        from simplecadapi.recording.graph import GraphSession
        from simplecadapi.recording.serializer import import_model_json
        from simplecadapi.translator.freecad_translator.translator import (
            _FreeCADCompiler,
        )

        with GraphSession() as session:
            box = scad.make_box_rsolid(width=10.0, height=10.0, depth=10.0)
            scad.chamfer_rsolid(
                box,
                _top_edge_selector(),
                1.0,
                angle=30.0,
                reference_direction=(0.0, 0.0, 1.0),
            )
            payload = scad.export_model_json(session)

        script = _FreeCADCompiler().translate_model_payload_to_script(
            import_model_json(payload)
        )
        self.assertIn("'distance2'", script)
        self.assertIn("'angle'", script)


if __name__ == "__main__":
    unittest.main()
