"""Body appearance: a display colour, opacity and name for the body of a Part (``set_body_appearance_rpart``).

The material colour is the default; a body colour overrides it for display.  The appearance reaches the live preview,
the legacy scene compiler, the product package (part definition and package scene), STEP, the cell cache (pickle)
and graph replay.  A Part whose body has no appearance is byte for byte what it was.

A Part holds exactly one solid, so its body id is always ``"body"``; the display of several solids is the business of
several Parts (an Assembly) or of loose notebook values (see ``test_one_solid_part.py``).
"""

from __future__ import annotations

import copy
import pickle
import re
import tempfile
import unittest
from pathlib import Path

import simplecadapi as scad
from simplecadapi import catalog
from simplecadapi.artifacts import materialize_definition
from simplecadapi.artifacts.validation import validate_manifest
from simplecadapi.exporter.step import export_product_package_to_step
from simplecadapi.product.packages import build_product_package, encode_product_package, load_product_package
from simplecadapi.runtime import run_notebook
from simplecadapi.scene.preview import compile_preview, decode_preview_header, encode_preview

from test_notebook_runtime import NotebookTestCase, cell, notebook_text

RED = (0.9, 0.2, 0.1)
BLUE = (0.1, 0.3, 0.8)


def _plate() -> scad.Part:
    return scad.make_part_rpart(part_id="plate", body=scad.make_box_rsolid(10.0, 10.0, 2.0))


class TestOperation(unittest.TestCase):
    def test_sets_colour_opacity_and_name_of_the_body(self) -> None:
        plate = _plate()
        painted = scad.set_body_appearance_rpart(plate, "body", color=RED, opacity=0.5, name="Plate")
        body = painted.get_body("body")
        self.assertEqual(body.color, RED)
        self.assertEqual(body.opacity, 0.5)
        self.assertEqual(body.name, "Plate")
        self.assertIsNone(plate.get_body("body").color)  # values are immutable
        self.assertEqual(painted.body_ids(), ("body",))
        self.assertEqual(
            painted.to_dict()["bodies"], [{"body_id": "body", "name": "Plate", "color": list(RED), "opacity": 0.5}]
        )

    def test_none_keeps_and_reset_clears(self) -> None:
        painted = scad.set_body_appearance_rpart(_plate(), "body", color=RED, name="Plate")
        again = scad.set_body_appearance_rpart(painted, "body", opacity=0.25)
        self.assertEqual((again.bodies[0].color, again.bodies[0].name), (RED, "Plate"))
        cleared = scad.set_body_appearance_rpart(again, "body", reset=True)
        body = cleared.bodies[0]
        self.assertEqual((body.color, body.opacity, body.name), (None, None, None))
        self.assertNotIn("bodies", cleared.to_dict())  # a plain body keeps the dict it always had

    def test_the_body_id_defaults_to_body(self) -> None:
        plate = scad.set_body_appearance_rpart(_plate(), color=BLUE)
        self.assertEqual(plate.bodies[0].color, BLUE)
        self.assertEqual(plate.to_dict()["bodies"], [{"body_id": "body", "name": None, "color": list(BLUE)}])
        self.assertNotIn("bodies", _plate().to_dict())  # a plain part keeps its dict

    def test_material_is_kept_and_overridden_for_display_only(self) -> None:
        steel = scad.make_material_rmaterial("steel", color=(0.5, 0.5, 0.5), density=7.85, density_unit="g/cm^3")
        plate = scad.set_body_appearance_rpart(scad.assign_material_rpart(_plate(), steel), color=RED)
        self.assertEqual(plate.material.material_id, "steel")
        mass = scad.measure_part_mass_rmassreport(plate)
        self.assertAlmostEqual(mass.mass_kg, 200.0 * 7.85e-6, places=12)  # the density is the material's, not the colour's
        colors = {node.node_id: node.color for node in compile_preview(plate).nodes}
        self.assertEqual(colors, {"node/plate": RED})
        plain = scad.assign_material_rpart(_plate(), steel)
        self.assertEqual({node.color for node in compile_preview(plain).nodes}, {(0.5, 0.5, 0.5)})

    def test_errors(self) -> None:
        for kwargs in ({"color": (1.5, 0, 0)}, {"color": (1, 0)}, {"opacity": 2.0}, {"name": "  "}):
            with self.subTest(kwargs=kwargs), self.assertRaises(scad.SimpleCADError):
                scad.set_body_appearance_rpart(_plate(), "body", **kwargs)
        with self.assertRaisesRegex(scad.SimpleCADError, "hinge"):
            scad.set_body_appearance_rpart(_plate(), "hinge", color=RED)
        with self.assertRaises(scad.SimpleCADError):
            scad.set_body_appearance_rpart("not a part", color=RED)
        with self.assertRaises(Exception):
            scad.Body("a", scad.make_box_rsolid(1, 1, 1), color=(2, 0, 0))

    def test_catalog_types_every_parameter(self) -> None:
        op = catalog.operation("set_body_appearance_rpart")
        kinds = {p.name: p.kind for p in op.params}
        self.assertEqual(
            kinds,
            {"part": "part", "body_id": "text", "color": "color", "opacity": "number", "name": "text", "reset": "bool"},
        )
        self.assertEqual(op.returns, "part")
        self.assertEqual(catalog.operation("make_material_rmaterial").params[-1].kind, "color")


class TestCacheAndReplay(unittest.TestCase):
    def test_pickle_and_deepcopy_keep_the_appearance(self) -> None:
        plate = scad.set_body_appearance_rpart(_plate(), color=BLUE, opacity=0.5, name="Plate")
        for again in (pickle.loads(pickle.dumps(plate)), copy.deepcopy(plate)):
            body = again.bodies[0]
            self.assertEqual((body.color, body.opacity, body.name), (BLUE, 0.5, "Plate"))
        plain = pickle.loads(pickle.dumps(_plate()))
        self.assertIsNone(plain.bodies[0].color)
        self.assertEqual(plain.body_ids(), ("body",))

    def test_recorded_and_replayed(self) -> None:
        with scad.GraphSession() as session:
            plate = scad.set_body_appearance_rpart(_plate(), color=RED, opacity=0.5, name="Plate")
            scad.set_body_appearance_rpart(plate, color=BLUE)
        model = scad.export_model_json(session)
        self.assertIn("make_set_body_appearance_rpart", model)
        parts = [item for item in scad.replay_model_json(model) if isinstance(item, scad.Part)]
        body = parts[-1].bodies[0]
        self.assertEqual((body.color, body.opacity, body.name), (BLUE, 0.5, "Plate"))


class TestPreviewAndScene(unittest.TestCase):
    def test_preview_header_carries_colour_and_opacity(self) -> None:
        plate = scad.set_body_appearance_rpart(_plate(), color=RED, opacity=0.5, name="Plate")
        (node,) = decode_preview_header(encode_preview(compile_preview(plate)))["nodes"]
        self.assertEqual(node["color"], list(RED))
        self.assertEqual(node["opacity"], 0.5)

    def test_a_plain_preview_header_is_unchanged(self) -> None:
        header = decode_preview_header(encode_preview(compile_preview(_plate())))
        self.assertNotIn("color", header["nodes"][0])
        self.assertNotIn("opacity", header["nodes"][0])

    def test_legacy_scene_compiler_uses_the_body_colour(self) -> None:
        from simplecadapi.scene import compiler

        plate = scad.set_body_appearance_rpart(_plate(), color=BLUE)
        package = compiler.compile_scene(scene_id="plate", roots=[compiler.SceneRoot(root_id="plate", value=plate)])
        colors = [list(a["base_color"]) for a in package.manifest["appearances"]]
        self.assertIn([*BLUE, 1], colors)


PLATE = notebook_text(
    cell(
        """
        plate = scad.make_part_rpart(part_id=scad.notebook_id(), body=scad.make_box_rsolid(5.0, 5.0, 1.0))
        plate = scad.set_body_appearance_rpart(plate, color=(0.1, 0.3, 0.8), name="Plate")
        """,
        returns="plate",
    ),
    table='id = "plate"',
)

PLAIN = notebook_text(
    cell("plate = scad.make_part_rpart(part_id=scad.notebook_id(), body=scad.make_box_rsolid(5.0, 5.0, 1.0))", returns="plate"),
    table='id = "plain"',
)


class TestPackage(NotebookTestCase):
    def test_definition_keeps_profile_2_and_round_trips(self) -> None:
        path = self.write("plate.py", PLATE)
        first = run_notebook(path)
        second = run_notebook(path)
        self.assertEqual(self.statuses(second)[-1], "cached")
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)
        manifest = second.definition.to_dict()
        self.assertEqual(manifest["profile"], "simplecad-part-definition-2")
        self.assertEqual(manifest["appearance"], {"bodies": [{"body_id": "body", "color": list(BLUE), "opacity": None, "name": "Plate"}]})
        self.assertNotIn("bodies", manifest["solid_cache"])
        validate_manifest(manifest, "part_definition")
        part = materialize_definition(load_product_package(encode_product_package(build_product_package(second.definition))))
        self.assertEqual((part.bodies[0].color, part.bodies[0].name), (BLUE, "Plate"))

    def test_a_plain_definition_has_no_appearance_key(self) -> None:
        definition = run_notebook(self.write("plain.py", PLAIN)).definition
        self.assertNotIn("appearance", definition.to_dict())
        self.assertEqual(definition.appearance, ())

    def test_package_scene_nodes_carry_the_colour(self) -> None:
        from simplecadapi.scene.product_scene import compile_product_scene

        plate = compile_product_scene(run_notebook(self.write("plate.py", PLATE)).definition).manifest["nodes"]
        self.assertEqual(plate[0]["properties"]["color"], list(BLUE))
        self.assertEqual(len(plate), 1)  # one node: a Part has no child solid nodes

    def test_step_writes_the_body_colour(self) -> None:
        data = encode_product_package(build_product_package(run_notebook(self.write("plate.py", PLATE)).definition))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.step"
            export_product_package_to_step(data, path)
            step = path.read_text(encoding="utf-8", errors="replace")
        rgb = [tuple(round(float(v), 3) for v in m) for m in re.findall(r"COLOUR_RGB\('[^']*',([\d.Ee+-]+),([\d.Ee+-]+),([\d.Ee+-]+)\)", step)]
        # OCCT takes the colour as linear RGB (Quantity_TOC_RGB, as for a material colour) and STEP stores sRGB
        srgb = tuple(round(c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055, 3) for c in BLUE)
        self.assertTrue(any(all(abs(a - b) < 2e-3 for a, b in zip(srgb, row)) for row in rgb), rgb)


if __name__ == "__main__":
    unittest.main()
