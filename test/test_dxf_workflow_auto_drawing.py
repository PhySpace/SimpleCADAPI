import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import ezdxf
import simplecadapi as scad
from ezdxf.lldxf.tagwriter import TagCollector
from simplecadapi.kernel.ocp_export import export_step_shapes


class AutomaticDrawingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.step = self.root / "plate.step"

    def make_plate(self, *, hole=False):
        solid = scad.make_box_rsolid(width=30, height=20, depth=10)
        if hole:
            cylinder = scad.make_cylinder_rsolid(
                radius=2, height=12, bottom_face_center=(3, 1, -1)
            )
            solid = scad.cut_rsolid(solid, cylinder, on_split="error")
        export_step_shapes([solid.wrapped], str(self.step))

    def cli(self, out, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "simplecadapi.cli",
                "drawing",
                "--step",
                str(self.step),
                "--out",
                str(out),
                *args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=True,
        )

    def test_plan_only_emits_machine_readable_decisions_and_skips_unhelpful_cut(self):
        self.make_plate()
        output = self.root / "planned.dxf"
        result = json.loads(
            self.cli(
                output,
                "--mode",
                "auto",
                "--plan-only",
                "--primary-view",
                "front",
                "--sheet",
                "A4",
                "--dimensions",
                "overall",
            ).stdout
        )
        report = json.loads(Path(result["plan"]).read_text(encoding="utf-8"))
        self.assertEqual(report["section"]["status"], "not_proposed")
        self.assertEqual(report["view_selection"]["primary_source_frame"], "front")
        self.assertTrue(report["view_selection"]["forced"])
        self.assertEqual(len(report["view_selection"]["candidates"]), 6)
        self.assertEqual(
            report["source"]["sha256"],
            hashlib.sha256(self.step.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            sorted(d["value_mm"] for d in report["dimensions"]["measured"]),
            [10, 20, 30],
        )
        self.assertFalse(output.exists())
        self.assertFalse(output.with_suffix(".png").exists())

    def test_visible_bore_drives_view_cut_and_dimension_and_declaration_replays(self):
        self.make_plate(hole=True)
        output = self.root / "auto.dxf"
        result = json.loads(self.cli(output, "--mode", "auto").stdout)
        report = json.loads(Path(result["plan"]).read_text(encoding="utf-8"))
        self.assertIn(
            report["view_selection"]["primary_source_frame"], ("top", "bottom")
        )
        self.assertEqual(report["section"]["status"], "proposed")
        self.assertEqual(len(report["section"]["selected"]["bore_axis_refs"]), 1)
        self.assertEqual(result["dimension_count"], 4)
        self.assertEqual(report["dimensions"]["bore_groups"][0]["status"], "proposed")
        self.assertEqual(report["render"]["audit"]["audit_errors"], 0)

        replay = self.root / "replay.dxf"
        self.cli(
            replay, "--mode", "engineering", "--drawing-json", result["declaration"]
        )
        geometry = []
        for path in (output, replay):
            doc = ezdxf.readfile(path)
            entities = doc.modelspace()
            self.assertGreater(len(entities.query("HATCH")), 0)
            measurements = [
                abs(dim.get_measurement())
                * doc.dimstyles.get(dim.dxf.dimstyle).dxf.dimlfac
                for dim in entities.query("DIMENSION")
            ]
            self.assertEqual(
                sorted(round(value, 5) for value in measurements), [4, 10, 20, 30]
            )
            # The PNG backend jitters hatch rasterization slightly. Compare the exported DXF geometry.
            geometry.append(
                Counter(
                    tuple(
                        (
                            tag.code,
                            round(tag.value, 8)
                            if isinstance(tag.value, float)
                            else tag.value,
                        )
                        for tag in TagCollector.dxftags(entity)
                        if tag.code not in (5, 330)
                    )
                    for entity in entities
                )
            )
            self.assertTrue(path.with_suffix(".png").is_file())
        self.assertEqual(*geometry)

    def test_template_records_basis_and_compact_third_angle_layout(self):
        self.make_plate(hole=True)
        out = self.root / "compact.dxf"
        result = json.loads(
            self.cli(
                out,
                "--mode",
                "auto",
                "--template",
                "asme-machining",
                "--layout",
                "compact",
                "--section-view",
                "full",
            ).stdout
        )
        report = json.loads(Path(result["plan"]).read_text(encoding="utf-8"))
        decl = json.loads(Path(result["declaration"]).read_text(encoding="utf-8"))
        self.assertEqual(report["template"]["id"], "asme-machining")
        self.assertEqual(decl["sheet"]["projection"], "third")
        self.assertIn(report["section"]["replaces_view"], ("top", "right"))
        self.assertEqual(len(decl["views"]), 3)
        self.assertEqual(
            {row["align"]["side"] for row in decl["views"] if "align" in row},
            {"above", "right"},
        )
        doc = ezdxf.readfile(out)
        self.assertIn(
            "mm · third-angle",
            [label.dxf.text for label in doc.modelspace().query("TEXT")],
        )
