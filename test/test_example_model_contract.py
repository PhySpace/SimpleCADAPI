"""Structural checks for the example notebook contract."""

import importlib.util
import re
import sys
from pathlib import Path
import unittest


import simplecadapi as scad
from simplecadapi.runtime.config import read_notebook_config

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

# Directories that do not follow the notebook layout: translator output kept
# in library form, demo tooling, and work in progress.
_NON_NOTEBOOK_EXAMPLES = frozenset(
    {
        "histcad_demo",
        "demo_kit",
        "pcg_facade_tower",
    }
)

_ASSEMBLY_CONSTRUCTOR = re.compile(r"\bscad\.(make_assembly_rassembly|assembly_builder)\(")


def _source_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in EXAMPLES.rglob("*.py")
        if not {"out", "__marimo__"} & set(path.relative_to(EXAMPLES).parts)
    )


def _notebook_layout_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in _source_files()
        if path.relative_to(EXAMPLES).parts[0] not in _NON_NOTEBOOK_EXAMPLES
    )


class TestExampleModelContract(unittest.TestCase):
    def test_hydraulic_rod_assembly_output_dir_is_anchored_to_the_example_file(self):
        path = EXAMPLES / "hydraulic_rod_assembly" / "export.py"
        spec = importlib.util.spec_from_file_location(
            "hydraulic_rod_assembly_path_contract", path
        )
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(module.OUT_DIR.is_absolute())
        self.assertEqual(
            module.OUT_DIR,
            EXAMPLES / "hydraulic_rod_assembly" / "out",
        )

    def test_assemblies_are_composed_only_in_notebooks(self):
        # Plain modules hold parameters and helpers; a product is a notebook.
        for path in _notebook_layout_files():
            if read_notebook_config(path) is not None:
                continue
            source = path.read_text(encoding="utf-8")
            self.assertIsNone(_ASSEMBLY_CONSTRUCTOR.search(source), path)
            self.assertNotEqual(path.name, "main.py", path)

    def test_notebook_ids_are_unique_within_each_example(self):
        seen: dict[tuple[str, str], Path] = {}
        notebooks = 0
        for path in _notebook_layout_files():
            config = read_notebook_config(path)
            if config is None:
                continue
            notebooks += 1
            key = (path.relative_to(EXAMPLES).parts[0], config.id)
            self.assertNotIn(key, seen, f"{path} reuses the id of {seen.get(key)}")
            seen[key] = path
        self.assertGreater(notebooks, 0)


    def test_examples_do_not_use_removed_decorator_api(self):
        for path in _source_files():
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("@scad.model", source, path)
            self.assertNotIn("scad.requires_session", source, path)
            self.assertNotIn("scad.capture_result", source, path)

    def test_bldc_bearing_decorative_balls_are_part_of_outer_ring(self):
        example_dir = EXAMPLES / "integrated_bldc_joint_actuator"
        sys.path.insert(0, str(example_dir))
        try:
            path = example_dir / "bearings.py"
            spec = importlib.util.spec_from_file_location(
                "bldc_bearings_contract", path
            )
            self.assertIsNotNone(spec)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            from dimensions import BearingSpec

            bearing_spec = BearingSpec(3.0, 6.0, 3.0, 0.7, 8)
            material = scad.make_material_rmaterial(
                "bearing_contract_steel",
                density=7.85e-6,
                density_unit="kg/mm^3",
            )
            bearing = module.build_actuator_bearing_rassembly(
                assembly_id="bearing_contract",
                spec=bearing_spec,
                material=material,
            )
            solved = scad.solve_assembly_constraints_rassembly(bearing)
            report = scad.inspect_assembly_constraints_rconstraintreport(solved)
        finally:
            sys.path.remove(str(example_dir))

        self.assertEqual(bearing.component_ids(), ("outer_ring", "inner_ring"))
        self.assertEqual(bearing.constraint_ids(), ("inner_outer_revolute",))
        self.assertEqual(bearing.grounded_component_ids, ("outer_ring",))
        self.assertEqual(report.unsolved_component_ids, ())
        outer = bearing.get_component("outer_ring").item.body
        self.assertEqual(len(scad.ql.solids().resolve(outer)), 1)
        self.assertGreater(outer.get_volume(), 0.0)
        self.assertIn(
            "role.rolling_elements_fused_into_outer_ring", scad.list_tags(outer)
        )


if __name__ == "__main__":
    unittest.main()
