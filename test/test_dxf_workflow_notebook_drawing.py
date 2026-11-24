import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import ezdxf


class NotebookDrawingTests(unittest.TestCase):
    def test_dimensionless_vars_and_explicit_units(self):
        import simplecadapi as scad
        from simplecadapi.dxf_engine.workflow.notebook import parameter_value

        count = scad.var("bolt_count", 8)
        self.assertEqual(parameter_value(count, None, "BOLT_COUNT"), (8.0, None, False))
        legacy_length = scad.var("slot_width", 34.0)
        self.assertEqual(
            parameter_value(legacy_length, "mm", "SLOT_W"), (34.0, "mm", True)
        )
        metric_value = scad.var("bearing_width", 2.0, unit="cm")
        self.assertEqual(
            parameter_value(metric_value, None, "bearing_width"), (20.0, "cm", True)
        )

    def test_compact_layout_section_keeps_the_replaced_view_for_design_intent(self):
        # With the compact layout a full section replaces one of the views; the notebook's design
        # intent names that view, so the section must keep its name for the dimensions to resolve.
        directory = Path(__file__).resolve().parent
        sample = directory.parent / "examples/dxf_exporter/stepped_mount.py"
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "compact.dxf"
            result = subprocess.run(
                [sys.executable, "-m", "simplecadapi.cli", "drawing", "--notebook", str(sample),
                 "--layout", "compact", "--out", str(out)],
                capture_output=True, text=True, encoding="utf-8", timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            spec = json.loads(out.with_suffix(".drawing.json").read_text(encoding="utf-8"))
            sections = [view for view in spec["views"] if "section" in view]
            self.assertEqual(len(sections), 1)
            self.assertIn(sections[0]["name"], {"top", "right"})
            self.assertTrue(out.exists())

    def test_notebook_overrides_rebuild_native_dimensions_and_audit_unbound_parameter(
        self,
    ):
        directory = Path(__file__).resolve().parent
        sample = directory.parent / "examples/dxf_exporter/stepped_mount.py"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = [
                sys.executable,
                "-m",
                "simplecadapi.cli",
                "drawing",
                "--primary-view",
                "top",
                "--no-section",
                "--sheet",
                "A3",
            ]
            for name, wanted, overrides in [
                ("base", {6, 31, 8}, []),
                (
                    "changed",
                    {8, 36},
                    ["--set", "HOLE_DIAMETER=8", "--set", "HOLE_PITCH=36"],
                ),
            ]:
                out = root / f"{name}.dxf"
                result = subprocess.run(
                    args + ["--notebook", str(sample), "--out", str(out)] + overrides,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
                coverage = data["design_intent"]["parameters"]
                self.assertEqual(
                    {
                        d["measured_mm"]
                        for p in coverage
                        if p["status"] == "verified"
                        for d in p["dimensions"]
                    },
                    wanted,
                )
                self.assertEqual(
                    [p["name"] for p in coverage if p["status"] == "unbound"],
                    ["TOOL_CLEARANCE"],
                )
                doc = ezdxf.readfile(out)
                dimensions = doc.modelspace().query("DIMENSION")
                self.assertEqual(len(dimensions), 6)
                actual = {
                    round(
                        abs(d.get_measurement())
                        * doc.dimstyles.get(d.dxf.dimstyle).dxf.dimlfac,
                        6,
                    )
                    for d in dimensions
                }
                self.assertEqual(actual, wanted | {50, 80, 12})

            # Keep the geometry unchanged and offset the expected dimension by
            # less than the SDK's generic mismatch threshold of 0.005 mm.
            bad_model = root / "bad_model.py"
            source = sample.read_text(encoding="utf-8")
            source = source.replace(
                '"parameter": "HOLE_PITCH",',
                '"parameter": "HOLE_PITCH", "factor": 1.0001,',
            )
            bad_model.write_text(source, encoding="utf-8")
            rejected = root / "rejected.dxf"
            failure = subprocess.run(
                args + ["--notebook", str(bad_model), "--out", str(rejected)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            self.assertEqual(failure.returncode, 1, failure.stderr + failure.stdout)
            self.assertFalse(rejected.exists())
            plan = json.loads(
                rejected.with_suffix(".plan.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "DESIGN_INTENT_MISMATCH", [issue["code"] for issue in plan["issues"]]
            )
