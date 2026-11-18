import tempfile
import unittest
from pathlib import Path

import numpy as np
import ezdxf
import simplecadapi as scad
from simplecadapi.kernel.ocp_export import export_step_shapes
from simplecadapi.dxf_engine.workflow import inspection as tool


class ModelDrawingTests(unittest.TestCase):
    def test_collapsed_HLR_edges_are_retained_as_audited_points(self):
        from unittest.mock import patch
        from types import SimpleNamespace

        class Point:
            def X(self):
                return 1.0

            def Y(self):
                return 2.0

        ad = SimpleNamespace(
            FirstParameter=lambda: 0.0,
            LastParameter=lambda: 1.0,
            Value=lambda t: Point(),
        )
        with patch.object(tool, "discretize_edge", return_value=(ad, [(1.0, 2.0)])):
            edge = tool.edge_record(object(), 0.03)
        self.assertEqual(edge["kind"], "POINT")
        self.assertEqual(edge["projected_extent_mm"], 0.0)
        fake = {
            "views": {
                n: dict(bounds=[[0, 0], [20, 10]], edges=[dict(edge, visible=True)])
                for n in tool.frames()
            }
        }
        layout = tool.sheet_layout([fake])
        doc = tool.new_document(layout)
        tool.add_geometry(doc.modelspace(), fake, layout)
        self.assertEqual(len(list(doc.modelspace().query("POINT"))), 7)

    def test_frames_are_proper_and_projection_layout_is_explicit(self):
        for f in tool.frames().values():
            np.testing.assert_allclose(
                np.cross(f["right"], f["up"]), -np.asarray(f["direction"]), atol=1e-10
            )
        fake = {"views": {n: dict(bounds=[[0, 0], [20, 10]]) for n in tool.frames()}}
        first = tool.sheet_layout([fake], "first")
        third = tool.sheet_layout([fake], "third")
        self.assertLess(first["cells"]["top"][1], first["cells"]["front"][1])
        self.assertLess(first["cells"]["right"][0], first["cells"]["front"][0])
        self.assertGreater(third["cells"]["top"][1], third["cells"]["front"][1])
        self.assertGreater(third["cells"]["right"][0], third["cells"]["front"][0])

    def test_real_offset_blind_hole_visibility_curves_and_independent_export(self):
        box = scad.make_box_rsolid(width=20.0, height=14.0, depth=10.0)
        cutter = scad.make_cylinder_rsolid(
            radius=2.0, height=3.0, bottom_face_center=(3.0, 1.0, 7.0)
        )
        solid = scad.cut_rsolid(box, cutter, on_split="error")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "hole.step"
            export_step_shapes([solid.wrapped], str(source))
            p = tool.project_step(source)
            circles = lambda v: [
                e
                for e in p["views"][v]["edges"]
                if e["kind"] == "CIRCLE" and abs(e["radius"] - 2) < 1e-6
            ]
            self.assertTrue(any(e["visible"] for e in circles("top")))
            self.assertFalse(any(e["visible"] for e in circles("bottom")))
            self.assertTrue(any(not e["visible"] for e in circles("bottom")))
            np.testing.assert_allclose(
                circles("top")[0]["center"], [3.0, 1.0], atol=1e-6
            )
            np.testing.assert_allclose(
                circles("bottom")[0]["center"], [3.0, -1.0], atol=1e-6
            )
            q = tool.project_step(
                source,
                transform=dict(
                    rotation=np.eye(3).tolist(), translation_mm=[4.0, 5.0, 6.0]
                ),
            )
            qc = [
                e
                for e in q["views"]["top"]["edges"]
                if e["kind"] == "CIRCLE" and abs(e["radius"] - 2) < 1e-6
            ]
            np.testing.assert_allclose(qc[0]["center"], [7.0, 6.0], atol=1e-6)
            layout = tool.sheet_layout([p, q])
            meta = tool.export_sheet(p, folder / "sheet.dxf", layout=layout)
            self.assertEqual(meta["reopen_audit"]["audit_errors"], 0)
            doc = ezdxf.readfile(folder / "sheet.dxf")
            self.assertTrue(list(doc.modelspace().query("CIRCLE")))
            self.assertTrue(list(doc.modelspace().query("LINE")))
            for suffix in [".png", ".svg", ".json"]:
                self.assertTrue((folder / ("sheet" + suffix)).exists())
            previews = list(
                tool.export_view_previews(
                    folder / "sheet.dxf", layout, folder / "sheet_views"
                ).values()
            )
            self.assertEqual(len(previews), 7)
            import xml.etree.ElementTree as ET

            for preview in previews:
                root = ET.parse(preview).getroot()
                self.assertTrue(root.attrib.get("viewBox"))
            # Common layout must preserve the deliberate translation, not re-center q.
            np.testing.assert_allclose(
                np.asarray(qc[0]["center"]) - circles("top")[0]["center"], [4, 5]
            )
            for r in [np.diag([-1.0, 1.0, 1.0]), np.eye(3) * 2]:
                with self.assertRaises(ValueError):
                    tool.rigid_shape(
                        solid.wrapped,
                        dict(rotation=r.tolist(), translation_mm=[0, 0, 0]),
                    )
            self.assertTrue(
                all(
                    v["input_hlr_edges"]
                    == len(v["edges"]) + v["duplicate_edges_removed"]
                    for v in p["views"].values()
                )
            )
            plain = folder / "missing_hole.step"
            export_step_shapes([box.wrapped], str(plain))
            missing = tool.project_step(plain)
            self.assertFalse(
                any(e["kind"] == "CIRCLE" for e in missing["views"]["top"]["edges"])
            )
            tool.export_overlay(p, missing, folder / "overlay.dxf", layout=layout)
            overlay = ezdxf.readfile(folder / "overlay.dxf")
            self.assertTrue(
                list(overlay.modelspace().query('CIRCLE[layer=="REFERENCE"]'))
            )
            self.assertFalse(
                list(overlay.modelspace().query('CIRCLE[layer=="CANDIDATE"]'))
            )


if __name__ == "__main__":
    unittest.main()
