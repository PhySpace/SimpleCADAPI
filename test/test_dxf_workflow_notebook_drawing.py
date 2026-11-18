import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import ezdxf


class NotebookDrawingTests(unittest.TestCase):
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
