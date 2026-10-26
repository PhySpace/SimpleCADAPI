"""Recognition settings shared by target analysis and report validation."""

from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
CASES = ("l1", "s1", "p1")
FEATURE_KINDS = (
    "hole", "extrusion", "revolution", "loft", "sweep",
    "fillet", "chamfer", "sheet_metal",
)
CONFIG = {
    "feature_kinds": FEATURE_KINDS,
    "linear_tolerance": 1.0e-6,
    "angular_tolerance_degrees": 0.5,
    "max_features": 200,
    "section_rule": "feature-stations-and-global-center-v1",
}
