"""H2 contract test: FreeCAD package translation reads the package once."""
import unittest
from pathlib import Path
from unittest import mock

import simplecadapi as scad


def _build_package() -> scad.ProductPackage:
    @scad.part(id="single_box", project_root=Path(__file__).parent)
    def build_box() -> scad.Part:
        return scad.make_part_rpart(
            "single_box", scad.make_box_rsolid(width=4.0, height=3.0, depth=2.0)
        )

    return scad.build_product_package(build_box())


class TestFreecadSingleRead(unittest.TestCase):
    def test_translate_reads_package_units_once(self):
        from simplecadapi.translator import package_units as pu
        from simplecadapi.translator.freecad_translator import (
            translate_product_package_to_freecad_script,
        )

        payload = scad.encode_product_package(_build_package())
        reference = translate_product_package_to_freecad_script(payload)

        with mock.patch.object(
            pu,
            "read_product_package_translation_units",
            wraps=pu.read_product_package_translation_units,
        ) as spy:
            script = translate_product_package_to_freecad_script(payload)

        self.assertEqual(spy.call_count, 1)
        self.assertEqual(script, reference)


if __name__ == "__main__":
    unittest.main()
