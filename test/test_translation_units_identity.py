"""H1 contract test: same-content definitions with distinct ids stay separate units."""
import json
import tempfile
import unittest
from pathlib import Path

import simplecadapi as scad


def _build_two_id_package() -> scad.ProductPackage:
    material = scad.make_material_rmaterial(
        material_id="dual_steel", density=7.85e-6, density_unit="kg/mm^3"
    )

    def make_bar(part_id: str) -> scad.Part:
        body = scad.make_box_rsolid(width=10.0, height=2.0, depth=2.0)
        part = scad.make_part_rpart(part_id=part_id, body=body)
        part = scad.assign_material_rpart(part=part, material=material)
        return scad.add_connector_rpart(
            part=part,
            connector=scad.make_placement_connector_rconnector(
                "axis", scad.identity_placement_rplacement()
            ),
        )

    @scad.part(id="bar_left", project_root=Path(__file__).parent)
    def build_left() -> scad.Part:
        return make_bar("bar_left")

    @scad.part(id="bar_right", project_root=Path(__file__).parent)
    def build_right() -> scad.Part:
        # Same geometry and material as bar_left; only the id differs.
        return make_bar("bar_right")

    left = build_left()
    right = build_right()

    @scad.assemble(
        id="dual_bars",
        definitions=(left, right),
        project_root=Path(__file__).parent,
    )
    def build_fixture() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly("dual_bars")
        assembly = scad.add_component_rassembly(
            assembly,
            left.part,
            component_id="left",
            placement=scad.identity_placement_rplacement(),
        )
        assembly = scad.add_component_rassembly(
            assembly,
            right.part,
            component_id="right",
            placement=scad.make_placement_rplacement(origin=(20.0, 0.0, 0.0)),
        )
        assembly = scad.ground_component_rassembly(assembly, "left")
        return scad.add_revolute_constraint_rassembly(
            assembly,
            "hinge",
            scad.make_connector_ref_rconnectorref("left", "axis"),
            scad.make_connector_ref_rconnectorref("right", "axis"),
        )

    return scad.build_product_package(build_fixture())


class TestSameContentDistinctIdUnits(unittest.TestCase):
    def test_units_and_step_export_keep_both_definitions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            package = _build_two_id_package()

            from simplecadapi.translator.package_units import (
                read_product_package_translation_units,
            )

            _, units = read_product_package_translation_units(package)
            ids = [unit.definition_id for unit in units]
            self.assertIn("bar_left", ids)
            self.assertIn("bar_right", ids)
            self.assertEqual(len(ids), len(set(ids)))

            report = scad.exporter.export_product_package_to_step(
                package, root / "dual_bars.step"
            )
            self.assertEqual(
                sorted(report.definition_ids),
                ["bar_left", "bar_right", "dual_bars"],
            )
            self.assertEqual(report.occurrence_count, 2)


if __name__ == "__main__":
    unittest.main()
