"""Ellipse support tests: geometry tier, three-point sketch tier, radius
constraints, promotion, and FreeCAD translation mapping."""

from __future__ import annotations

import json
import math
import unittest

import simplecadapi as scad
from simplecadapi import ql


class TestGeometryTierEllipse(unittest.TestCase):
    def test_ellipse_face_area_is_exact(self):
        face = scad.make_ellipse_rface((0.0, 0.0, 0.0), 4.0, 2.0)
        self.assertAlmostEqual(face.get_area(), math.pi * 4.0 * 2.0, places=9)

    def test_ellipse_major_direction_orients_bbox(self):
        face = scad.make_ellipse_rface(
            (0.0, 0.0, 0.0), 4.0, 2.0, major_direction=(0.0, 1.0, 0.0)
        )
        from simplecadapi._cpp.occt.Bnd import Bnd_Box
        from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib

        box = Bnd_Box()
        BRepBndLib.Add_s(face.wrapped, box)
        xmin, ymin, _zmin, xmax, ymax, _zmax = box.Get()
        self.assertAlmostEqual(xmin, -2.0, places=6)
        self.assertAlmostEqual(xmax, 2.0, places=6)
        self.assertAlmostEqual(ymin, -4.0, places=6)
        self.assertAlmostEqual(ymax, 4.0, places=6)

    def test_ellipse_extrudes_to_exact_volume(self):
        face = scad.make_ellipse_rface((0.0, 0.0, 0.0), 4.0, 2.0)
        body = scad.extrude_rsolid(profile=face, direction=(0, 0, 1), distance=3.0)
        self.assertAlmostEqual(
            body.get_volume(), 3.0 * math.pi * 4.0 * 2.0, places=6
        )

    def test_ellipse_rejects_minor_above_major(self):
        with self.assertRaises(Exception):
            scad.make_ellipse_redge((0.0, 0.0, 0.0), 2.0, 4.0)

    def test_ql_recognizes_ellipse_edges(self):
        face = scad.make_ellipse_rface((0.0, 0.0, 0.0), 4.0, 2.0)
        edges = ql.edges().where(ql.curve_type("ELLIPSE")).resolve(face)
        self.assertEqual(len(edges), 1)


class TestSketchTierEllipse(unittest.TestCase):
    def _ellipse_sketch(self, major=4.0, minor=2.0, angle_deg=30.0):
        sketch = scad.make_sketch_rsketch("oval")
        theta = math.radians(angle_deg)
        sketch = scad.add_point_rsketch(sketch, "c", 0.0, 0.0)
        sketch = scad.add_point_rsketch(
            sketch, "M", major * math.cos(theta), major * math.sin(theta)
        )
        sketch = scad.add_point_rsketch(
            sketch, "m", -minor * math.sin(theta), minor * math.cos(theta)
        )
        sketch = scad.add_ellipse_rsketch(sketch, "oval", "c", "M", "m")
        return sketch

    def test_driving_radius_constraints_solve_and_promote(self):
        sketch = self._ellipse_sketch()
        sketch = scad.constrain_fix_rsketch(sketch, "c")
        sketch = scad.constrain_major_radius_rsketch(sketch, "oval", 4.0)
        sketch = scad.constrain_minor_radius_rsketch(sketch, "oval", 2.0)

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertEqual(result.status, "underconstrained")  # orientation free
        entity = result.solved_entities["oval"]
        self.assertAlmostEqual(entity["major_radius"], 4.0, places=6)
        self.assertAlmostEqual(entity["minor_radius"], 2.0, places=6)

        face = scad.make_face_from_sketch_rface(sketch)
        self.assertAlmostEqual(face.get_area(), math.pi * 8.0, places=6)

    def test_solved_entity_reports_major_axis_angle(self):
        sketch = self._ellipse_sketch(angle_deg=30.0)
        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertAlmostEqual(
            result.solved_entities["oval"]["angle"], 30.0, places=6
        )

    def test_ellipse_center_participates_in_coincident_and_concentric(self):
        sketch = self._ellipse_sketch()
        sketch = scad.add_point_rsketch(sketch, "cc", 0.5, 0.3)
        sketch = scad.add_circle_rsketch(sketch, "hole", "cc", 0.5)
        sketch = scad.constrain_coincident_rsketch(sketch, "oval.center", "cc")
        sketch = scad.constrain_fix_rsketch(sketch, "c")

        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn(result.status, {"solved", "underconstrained"})
        self.assertAlmostEqual(result.solved_points["cc"][0], 0.0, places=6)
        self.assertAlmostEqual(result.solved_points["cc"][1], 0.0, places=6)

    def test_ellipse_fix_pins_all_axis_points(self):
        sketch = self._ellipse_sketch()
        sketch = scad.constrain_fix_rsketch(sketch, "oval")
        sketch = scad.constrain_major_radius_rsketch(
            sketch, "oval", 9.0, constraint_id="measured", driving=False
        )
        result = scad.inspect_sketch_rsketchresult(sketch)
        self.assertEqual(result.status, "solved")
        self.assertAlmostEqual(
            result.solved_scalars["constraint:measured:value"], 4.0, places=6
        )

    def test_ellipse_rejects_degenerate_axes(self):
        sketch = scad.make_sketch_rsketch("bad")
        sketch = scad.add_point_rsketch(sketch, "c", 0.0, 0.0)
        sketch = scad.add_point_rsketch(sketch, "M", 0.0, 0.0)
        sketch = scad.add_point_rsketch(sketch, "m", 0.0, 1.0)
        with self.assertRaises(Exception):
            scad.add_ellipse_rsketch(sketch, "oval", "c", "M", "m")

    def test_ellipse_serialization_round_trip(self):
        sketch = self._ellipse_sketch()
        restored = scad.Sketch.from_dict(json.loads(json.dumps(sketch.to_dict())))
        entity = restored.entities["oval"]
        self.assertEqual(entity.kind, "ellipse")
        self.assertEqual(entity.data["center"], "c")
        self.assertEqual(entity.data["major"], "M")
        self.assertEqual(entity.data["minor"], "m")
        ref = restored.point_ref("oval.major")
        self.assertEqual(ref.entity_id, "oval")
        self.assertEqual(ref.subentity, "major")

    def test_tangent_with_ellipse_reports_unsupported_kind(self):
        sketch = self._ellipse_sketch()
        sketch = scad.add_point_rsketch(sketch, "p0", 5.0, 0.0)
        sketch = scad.add_point_rsketch(sketch, "p1", 8.0, 0.0)
        sketch = scad.add_line_rsketch(sketch, "tan_line", "p0", "p1")
        sketch = scad.constrain_tangent_rsketch(sketch, "tan_line", "oval")
        with self.assertRaises(Exception) as ctx:
            scad.inspect_sketch_rsketchresult(sketch)
        self.assertIn("ellipse", str(ctx.exception))


class TestEllipseFreecadTranslation(unittest.TestCase):
    def test_ellipse_sketch_maps_to_freecad_geometry_and_radius(self):
        from simplecadapi.recording.graph import GraphSession
        from simplecadapi.recording.serializer import import_model_json
        from simplecadapi.translator.freecad_translator.translator import (
            _FreeCADCompiler,
        )

        with GraphSession() as session:
            sketch = scad.make_sketch_rsketch(name="oval")
            sketch = scad.add_point_rsketch(sketch, "c", 0.0, 0.0)
            sketch = scad.add_point_rsketch(sketch, "M", 4.0, 0.0)
            sketch = scad.add_point_rsketch(sketch, "m", 0.0, 2.0)
            sketch = scad.add_ellipse_rsketch(sketch, "oval", "c", "M", "m")
            sketch = scad.constrain_fix_rsketch(sketch, "c")
            sketch = scad.constrain_major_radius_rsketch(sketch, "oval", 4.0)
            sketch = scad.constrain_minor_radius_rsketch(sketch, "oval", 2.0)
            scad.make_face_from_sketch_rface(sketch)
            payload = scad.export_model_json(session)

        script = _FreeCADCompiler().translate_model_payload_to_script(
            import_model_json(payload)
        )
        self.assertIn("Part.Ellipse", script)
        self.assertIn("add_ellipse_rsketch", script)
        self.assertIn("major_radius", script)

    def test_ellipse_geometry_tier_compiles(self):
        from simplecadapi.recording.graph import GraphSession
        from simplecadapi.recording.serializer import import_model_json
        from simplecadapi.translator.freecad_translator.translator import (
            _FreeCADCompiler,
        )

        with GraphSession() as session:
            scad.make_ellipse_rface((0.0, 0.0, 0.0), 4.0, 2.0)
            payload = scad.export_model_json(session)

        script = _FreeCADCompiler().translate_model_payload_to_script(
            import_model_json(payload)
        )
        self.assertIn("_kernel_ellipse_from_params", script)


if __name__ == "__main__":
    unittest.main()
