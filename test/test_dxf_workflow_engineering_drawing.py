import copy
import math
import tempfile
import unittest
from pathlib import Path

import ezdxf
import simplecadapi as scad
from ezdxf.math import BoundingBox2d
from ezdxf.xclip import XClip
from PIL import Image
from simplecadapi.kernel.ocp_export import export_step_shapes

from simplecadapi.dxf_engine.workflow.declaration import (
    build_plan,
    export_engineering_sheet,
    load_engineering_shape,
)
from simplecadapi.dxf_engine.workflow.inspection import rigid_shape


class EngineeringDrawingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.spec = {
            "sheet": {"scale": 0.5, "auto_centers": False},
            "views": [
                {"name": "top", "frame": "top"},
                {
                    "name": "cut",
                    "frame": "front",
                    "align": {"to": "top", "gap": 28},
                    "section": {"point": [0, 1, 5], "label": "A", "mark_in": "top"},
                },
            ],
            "dimensions": [
                {
                    "caption": "width",
                    "kind": "overall",
                    "view": "top",
                    "semantic": "linear",
                    "extent": "x",
                },
                {
                    "caption": "bore",
                    "kind": "size",
                    "view": "top",
                    "semantic": "diameter",
                    "of": {"cylinder": {"axis_point": [3, 1, 5], "axis": [0, 0, 1]}},
                },
            ],
        }

    def step_with_hole(self, radius):
        block = scad.make_box_rsolid(width=30, height=20, depth=10)
        cylinder = scad.make_cylinder_rsolid(
            radius=radius, height=12, bottom_face_center=(3, 1, -1)
        )
        part = scad.cut_rsolid(block, cylinder, on_split="error")
        source = self.root / f"plate-{radius}.step"
        export_step_shapes([part.wrapped], str(source))
        return source

    def test_section_and_bound_diameter_follow_edited_step(self):
        for radius in (2, 3):
            output = self.root / f"drawing-{radius}.dxf"
            meta = export_engineering_sheet(
                self.step_with_hole(radius), output, self.spec
            )
            self.assertEqual(meta["reopen_audit"]["audit_errors"], 0)
            self.assertEqual(
                {d["caption"]: d["value_mm"] for d in meta["dimensions"]},
                {"width": 30, "bore": 2 * radius},
            )
            doc = ezdxf.readfile(output)
            self.assertGreater(len(doc.modelspace().query("HATCH")), 0)
            dimensions = doc.modelspace().query("DIMENSION")
            self.assertEqual(len(dimensions), 2)
            diameter = next(d for d in dimensions if d.dimtype == 3)
            scale_factor = doc.dimstyles.get(diameter.dxf.dimstyle).dxf.dimlfac
            self.assertAlmostEqual(
                diameter.get_measurement() * scale_factor, 2 * radius
            )
            self.assertEqual(diameter.override()["dimtxsty"], "DXF_EXPORTER_DIM_SYMBOL")
            self.assertTrue(output.with_suffix(".png").is_file())
            self.assertFalse(output.with_suffix(".pdf").exists())

    def test_dimension_conflict_stops_before_publication(self):
        spec = copy.deepcopy(self.spec)
        spec["dimensions"][1]["value"] = 30
        output = self.root / "rejected.dxf"
        with self.assertRaisesRegex(ValueError, "DIM_VALUE_MISMATCH"):
            export_engineering_sheet(self.step_with_hole(2), output, spec)
        self.assertFalse(any(self.root.glob("rejected.*")))

    def test_detail_clipping_and_printed_scale(self):
        import pymupdf

        spec = copy.deepcopy(self.spec)
        spec["details"] = [
            {
                "label": "B",
                "parent": "top",
                "center": [6, 5, 10],
                "size_mm": [16, 14],
                "position_mm": [305, 210],
                "scale": 2,
            }
        ]
        output = self.root / "detail.dxf"
        meta = export_engineering_sheet(self.step_with_hole(2), output, spec, pdf=True)
        expected = (289, 196), (321, 224)
        self.assertEqual(meta["details"][0]["clip_sheet_mm"], list(expected))
        doc = ezdxf.readfile(output)
        insert = doc.modelspace().query("INSERT").first
        crop = XClip(insert)
        self.assertTrue(crop.is_clipping_enabled)
        bounds = BoundingBox2d(crop.get_wcs_clipping_path().vertices)
        self.assertEqual((tuple(bounds.extmin), tuple(bounds.extmax)), expected)
        self.assertEqual(insert.dxf.xscale, 4)
        self.assertGreater(len(doc.blocks[insert.dxf.name].query("CIRCLE")), 0)

        mm_per_point = 25.4 / 72
        with pymupdf.open(output.with_suffix(".pdf")) as pdf:
            self.assertEqual(len(pdf), 1)
            page = pdf[0]
            self.assertAlmostEqual(page.rect.width * mm_per_point, 420, places=3)
            self.assertAlmostEqual(page.rect.height * mm_per_point, 297, places=3)
            self.assertFalse(page.get_images())
            expected_border = (289, 297 - 224, 321, 297 - 196)
            self.assertTrue(
                any(
                    all(
                        abs(value * mm_per_point - coordinate) < 0.01
                        for value, coordinate in zip(drawing["rect"], expected_border)
                    )
                    for drawing in page.get_drawings()
                )
            )

        spec["details"][0]["position_mm"] = [210, 210]
        with self.assertRaisesRegex(ValueError, "clear of views"):
            export_engineering_sheet(
                self.root / "plate-2.step", self.root / "overlap.dxf", spec
            )
        self.assertFalse(any(self.root.glob("overlap.*")))

    def test_removed_section_omits_rear_edges_and_keeps_analytic_profile(self):
        block = scad.make_box_rsolid(width=30, height=20, depth=10)
        boss = scad.make_cylinder_rsolid(
            radius=5, height=9, bottom_face_center=(0, 0, 9)
        )
        raised = scad.union_rsolid(block, boss)
        bore = scad.make_cylinder_rsolid(
            radius=2, height=20, bottom_face_center=(0, 0, -1)
        )
        part = scad.cut_rsolid(raised, bore, on_split="error")
        step = self.root / "raised.step"
        export_step_shapes([part.wrapped], str(step))
        cut = {
            "name": "profile",
            "frame": "top",
            "align": {"to": "front", "side": "below", "gap": 33},
            "section": {"point": [0, 0, 13], "label": "A", "mark_in": "front"},
        }
        spec = {"views": [{"name": "front", "frame": "front"}, cut]}
        shape = load_engineering_shape(step)
        full = build_plan(shape, spec, "Raised boss")
        cut["section"]["kind"] = "removed"
        profile = build_plan(shape, spec, "Raised boss")
        self.assertEqual(len(profile.views["profile"]["hatch"]), 2)
        self.assertAlmostEqual(
            full.views["profile"]["lbox"][2] - full.views["profile"]["lbox"][0], 30
        )
        self.assertAlmostEqual(
            profile.views["profile"]["lbox"][2] - profile.views["profile"]["lbox"][0],
            10,
        )
        out = self.root / "removed.dxf"
        export_engineering_sheet(step, out, spec)
        entities = ezdxf.readfile(out).modelspace()
        self.assertEqual(len(entities.query("HATCH").first.paths.paths), 2)
        self.assertEqual(
            sorted(
                round(circle.dxf.radius / profile.s, 5)
                for circle in entities.query("CIRCLE")
            ),
            [2, 5],
        )

    def test_a0_preview_is_capped_and_vector_pdf_stays_full_size(self):
        import pymupdf
        from simplecadapi.dxf_engine.workflow.details import PREVIEW_LONG_SIDE_PX
        from unittest.mock import patch

        solid = scad.make_box_rsolid(width=30, height=20, depth=10)
        step = self.root / "large-sheet.step"
        export_step_shapes([solid.wrapped], str(step))
        out = self.root / "a0.dxf"
        spec = dict(
            sheet={"sheet": "A0", "scale": 1},
            views=[{"name": "front", "frame": "front"}],
        )
        with patch(
            "simplecadapi.dxf_engine.planner.SheetPlan.render",
            side_effect=AssertionError("intermediate PNG"),
        ):
            result = export_engineering_sheet(step, out, spec, pdf=True)
        self.assertEqual(result["reopen_audit"]["audit_errors"], 0)
        with Image.open(out.with_suffix(".png")) as preview:
            self.assertEqual(list(preview.size), result["preview"]["pixels"])
            self.assertLessEqual(max(preview.size), PREVIEW_LONG_SIDE_PX)
        with pymupdf.open(out.with_suffix(".pdf")) as pdf:
            self.assertAlmostEqual(pdf[0].rect.width * 25.4 / 72, 1189, places=3)
            self.assertAlmostEqual(pdf[0].rect.height * 25.4 / 72, 841, places=3)

    def test_extent_ignores_presentation_wire_and_uses_solid(self):
        from simplecadapi._cpp.occt.BRep import BRep_Builder
        from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
        from simplecadapi._cpp.occt.gp import gp_Pnt

        solid = scad.make_box_rsolid(width=30, height=20, depth=10)
        model = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(model)
        builder.Add(model, solid._native_wrapped)
        builder.Add(
            model, BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 30), gp_Pnt(0, 5, 30)).Edge()
        )
        spec = {
            "views": [{"name": "front", "frame": "front"}],
            "dimensions": [
                {
                    "caption": "z height",
                    "view": "front",
                    "kind": "overall",
                    "semantic": "linear",
                    "extent": "y",
                }
            ],
        }
        plan = build_plan(model, spec, "Solid with presentation edge")
        self.assertAlmostEqual(plan.dims[0]._measured, 10)
        self.assertAlmostEqual(
            plan.projection_bounds()["front"]["max_outline_gap_mm"], 0
        )

    def test_face_auxiliary_and_explicit_annotations_export_in_third_angle(self):
        from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface
        from simplecadapi.inspect import brep

        block = scad.make_box_rsolid(width=30, height=20, depth=10)
        c, s = math.cos(math.pi / 6), math.sin(math.pi / 6)
        shape = rigid_shape(
            block.wrapped,
            dict(rotation=[[c, 0, s], [0, 1, 0], [-s, 0, c]], translation_mm=[0, 0, 0]),
        )
        step = self.root / "sloping.step"
        export_step_shapes([shape], str(step))
        shape = load_engineering_shape(step)
        model = brep.index_shape_rbrepmodel(shape=shape)
        face = next(
            f
            for f in model.faces
            if abs(abs(BRepAdaptor_Surface(f).Plane().Axis().Direction().Z()) - c)
            < 1e-6
        )
        spec = {
            "sheet": {
                "projection": "third",
                "scale": 1,
                "auto_centers": False,
                "notes": ["Review geometry."],
            },
            "views": [
                {"name": "front", "frame": "front"},
                {
                    "name": "face_view",
                    "align": {"to": "front", "side": "left", "gap": 42},
                    "auxiliary": {
                        "mark_in": "front",
                        "label": "B",
                        "face": {"entity": model.id_for_shape("face", face)},
                    },
                },
            ],
            "roughness": [
                {"view": "front", "on": [10 * s, 0, 10 * c], "text": "Ra 3.2"}
            ],
            "leaders": [
                {
                    "view": "front",
                    "anchor": [15 * c, 0, -15 * s],
                    "off": [36, -24],
                    "lines": ["INSPECT EDGE"],
                }
            ],
            "centerlines": [{"view": "front", "p1": [-5, 0, 4], "p2": [5, 0, 4]}],
            "control_frames": [
                {
                    "view": "front",
                    "name": "face-flatness",
                    "anchor": [-15 * c + 10 * s, 0, 15 * s + 10 * c],
                    "characteristic": "flatness",
                    "value": 0.05,
                    "offset": [38, 26],
                }
            ],
        }
        plan = build_plan(shape, spec, "Sloping plate")
        axis = BRepAdaptor_Surface(face).Plane().Axis().Direction().Coord()
        self.assertAlmostEqual(
            abs(sum(a * b for a, b in zip(axis, plan.by_name["face_view"].n))), 1.0
        )
        out = self.root / "aux.dxf"
        meta = export_engineering_sheet(step, out, spec)
        self.assertEqual(meta["projection"], "third")
        doc = ezdxf.readfile(out)
        symbols = {label.dxf.text for label in doc.modelspace().query("TEXT")}
        self.assertTrue(
            {"AUX B", "Ra 3.2", "INSPECT EDGE", "mm · third-angle", "0.05"} <= symbols
        )
        self.assertTrue(doc.modelspace().query('LWPOLYLINE[layer=="FEATURE_CONTROL"]'))
        self.assertTrue(doc.modelspace().query('LINE[layer=="05_CENTER"]'))
        self.assertEqual(meta["control_frames"][0]["value"], 0.05)
        spec["control_frames"][0]["datums"] = ["Q"]
        with self.assertRaisesRegex(ValueError, "declared on this sheet"):
            build_plan(shape, spec, "Sloping plate")
