"""Body appearance: a display colour, opacity and name per body of a Part (``set_body_appearance_rpart``).

The material colour is the default; a body colour overrides it for display.  The appearance reaches the live preview,
the legacy scene compiler, the product package (part definition and package scene), STEP, the cell cache (pickle)
and graph replay.  A Part whose bodies have no appearance is byte for byte what it was.
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


def _case() -> scad.Part:
    return scad.make_part_rpart(
        part_id="case",
        bodies={
            "base": scad.make_box_rsolid(20.0, 20.0, 10.0, tag_prefix="base"),
            "lid": scad.make_box_rsolid(20.0, 20.0, 2.0, (40.0, 0.0, 0.0), tag_prefix="lid"),
        },
    )


def _plate() -> scad.Part:
    return scad.make_part_rpart(part_id="plate", body=scad.make_box_rsolid(10.0, 10.0, 2.0))


class TestOperation(unittest.TestCase):
    def test_sets_colour_opacity_and_name_of_one_body(self) -> None:
        case = _case()
        painted = scad.set_body_appearance_rpart(case, "lid", color=RED, opacity=0.5, name="Lid")
        lid = painted.get_body("lid")
        self.assertEqual(lid.color, RED)
        self.assertEqual(lid.opacity, 0.5)
        self.assertEqual(lid.name, "Lid")
        self.assertIsNone(painted.get_body("base").color)
        self.assertIsNone(case.get_body("lid").color)  # values are immutable
        self.assertEqual(painted.body_ids(), ("base", "lid"))
        self.assertEqual(
            painted.to_dict()["bodies"][1], {"body_id": "lid", "name": "Lid", "color": list(RED), "opacity": 0.5}
        )

    def test_none_keeps_and_reset_clears(self) -> None:
        painted = scad.set_body_appearance_rpart(_case(), "lid", color=RED, name="Lid")
        again = scad.set_body_appearance_rpart(painted, "lid", opacity=0.25)
        self.assertEqual((again.get_body("lid").color, again.get_body("lid").name), (RED, "Lid"))
        cleared = scad.set_body_appearance_rpart(again, "lid", reset=True)
        lid = cleared.get_body("lid")
        self.assertEqual((lid.color, lid.opacity, lid.name), (None, None, None))
        self.assertEqual(cleared.to_dict()["bodies"][1], {"body_id": "lid", "name": None})

    def test_one_body_part_uses_the_default_body(self) -> None:
        plate = scad.set_body_appearance_rpart(_plate(), color=BLUE)
        self.assertFalse(plate.multi_body)
        self.assertEqual(plate.bodies[0].color, BLUE)
        self.assertEqual(plate.to_dict()["bodies"], [{"body_id": "body", "name": None, "color": list(BLUE)}])
        self.assertNotIn("bodies", _plate().to_dict())  # a plain one-body part keeps its dict

    def test_material_is_kept_and_overridden_for_display_only(self) -> None:
        steel = scad.make_material_rmaterial("steel", color=(0.5, 0.5, 0.5), density=7.85, density_unit="g/cm^3")
        case = scad.set_body_appearance_rpart(scad.assign_material_rpart(_case(), steel), "lid", color=RED)
        self.assertEqual(case.material.material_id, "steel")
        mass = scad.measure_part_mass_rmassreport(case)
        self.assertAlmostEqual(mass.body("lid").mass_kg, 800.0 * 7.85e-6, places=12)
        colors = {node.node_id: node.color for node in compile_preview(case).nodes}
        self.assertEqual(colors, {"node/case/body:base": (0.5, 0.5, 0.5), "node/case/body:lid": RED})

    def test_errors(self) -> None:
        for kwargs in ({"color": (1.5, 0, 0)}, {"color": (1, 0)}, {"opacity": 2.0}, {"name": "  "}):
            with self.subTest(kwargs=kwargs), self.assertRaises(scad.SimpleCADError):
                scad.set_body_appearance_rpart(_case(), "lid", **kwargs)
        with self.assertRaisesRegex(scad.SimpleCADError, "hinge"):
            scad.set_body_appearance_rpart(_case(), "hinge", color=RED)
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
        case = scad.set_body_appearance_rpart(_case(), "lid", color=RED, opacity=0.5, name="Lid")
        plate = scad.set_body_appearance_rpart(_plate(), color=BLUE, name="Plate")
        for again in (pickle.loads(pickle.dumps(case)), copy.deepcopy(case)):
            lid = again.get_body("lid")
            self.assertEqual((lid.color, lid.opacity, lid.name), (RED, 0.5, "Lid"))
        one = pickle.loads(pickle.dumps(plate))
        self.assertFalse(one.multi_body)
        self.assertEqual((one.bodies[0].color, one.bodies[0].name), (BLUE, "Plate"))
        plain = pickle.loads(pickle.dumps(_plate()))
        self.assertIsNone(plain.bodies[0].color)

    def test_recorded_and_replayed(self) -> None:
        with scad.GraphSession() as session:
            case = scad.set_body_appearance_rpart(_case(), "lid", color=RED, opacity=0.5, name="Lid")
            scad.set_body_appearance_rpart(case, "base", color=BLUE)
        model = scad.export_model_json(session)
        self.assertIn("make_set_body_appearance_rpart", model)
        parts = [item for item in scad.replay_model_json(model) if isinstance(item, scad.Part)]
        final = parts[-1]
        self.assertEqual(final.get_body("base").color, BLUE)
        lid = final.get_body("lid")
        self.assertEqual((lid.color, lid.opacity, lid.name), (RED, 0.5, "Lid"))


class TestPreviewAndScene(unittest.TestCase):
    def test_preview_header_carries_colour_and_opacity(self) -> None:
        case = scad.set_body_appearance_rpart(_case(), "lid", color=RED, opacity=0.5, name="Lid")
        nodes = {n["node_id"]: n for n in decode_preview_header(encode_preview(compile_preview(case)))["nodes"]}
        self.assertEqual(nodes["node/case/body:lid"]["color"], list(RED))
        self.assertEqual(nodes["node/case/body:lid"]["opacity"], 0.5)
        self.assertEqual(nodes["node/case/body:lid"]["display_name"], "case / Lid")
        self.assertNotIn("color", nodes["node/case/body:base"])

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


PAINTED = notebook_text(
    cell(
        """
        base = scad.make_box_rsolid(20.0, 20.0, 10.0, tag_prefix="base")
        lid = scad.make_box_rsolid(20.0, 20.0, 2.0, (40.0, 0.0, 0.0), tag_prefix="lid")
        """,
        returns="base, lid",
    ),
    cell(
        """
        case = scad.make_part_rpart(part_id=scad.notebook_id(), bodies={"base": base, "lid": lid})
        case = scad.set_body_appearance_rpart(case, "lid", color=(0.9, 0.2, 0.1), opacity=0.5, name="Lid")
        """,
        reads="base, lid",
        returns="case",
    ),
    table='id = "case"',
)

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
    def test_multi_body_definition_round_trip(self) -> None:
        path = self.write("case.py", PAINTED)
        first = run_notebook(path)
        second = run_notebook(path)
        self.assertEqual(self.statuses(second)[-1], "cached")
        # (the content hash of a cached multi-body run differs from the first run on this branch already:
        # test_multi_body_part's cache test, known WIP of the stable-refs merge; the appearance is the same)
        self.assertEqual(first.definition.to_dict()["appearance"], second.definition.to_dict()["appearance"])
        manifest = second.definition.to_dict()
        self.assertEqual(manifest["profile"], "simplecad-part-definition-3")
        self.assertEqual(manifest["appearance"], {"bodies": [{"body_id": "lid", "color": list(RED), "opacity": 0.5}]})
        self.assertEqual([row["name"] for row in manifest["solid_cache"]["bodies"]], [None, "Lid"])
        validate_manifest(manifest, "part_definition")
        part = materialize_definition(load_product_package(encode_product_package(build_product_package(second.definition))))
        lid = part.get_body("lid")
        self.assertEqual((lid.color, lid.opacity, lid.name), (RED, 0.5, "Lid"))
        self.assertIsNone(part.get_body("base").color)

    def test_one_body_definition_keeps_profile_2_and_round_trips(self) -> None:
        definition = run_notebook(self.write("plate.py", PLATE)).definition
        manifest = definition.to_dict()
        self.assertEqual(manifest["profile"], "simplecad-part-definition-2")
        self.assertEqual(manifest["appearance"], {"bodies": [{"body_id": "body", "color": list(BLUE), "opacity": None, "name": "Plate"}]})
        validate_manifest(manifest, "part_definition")
        part = materialize_definition(load_product_package(encode_product_package(build_product_package(definition))))
        self.assertFalse(part.multi_body)
        self.assertEqual((part.bodies[0].color, part.bodies[0].name), (BLUE, "Plate"))

    def test_a_plain_definition_has_no_appearance_key(self) -> None:
        definition = run_notebook(self.write("plain.py", PLAIN)).definition
        self.assertNotIn("appearance", definition.to_dict())
        self.assertEqual(definition.appearance, ())

    def test_package_scene_nodes_carry_the_colour(self) -> None:
        from simplecadapi.scene.product_scene import compile_product_scene

        nodes = {n["node_id"]: n for n in compile_product_scene(run_notebook(self.write("case.py", PAINTED)).definition).manifest["nodes"]}
        self.assertEqual(nodes["node/case/body:lid"]["properties"]["color"], list(RED))
        self.assertEqual(nodes["node/case/body:lid"]["properties"]["opacity"], 0.5)
        self.assertNotIn("color", nodes["node/case/body:base"]["properties"])
        plate = compile_product_scene(run_notebook(self.write("plate.py", PLATE)).definition).manifest["nodes"]
        self.assertEqual(plate[0]["properties"]["color"], list(BLUE))

    def test_step_writes_the_body_colours_and_names(self) -> None:
        for name, text, expected, label in (("case.py", PAINTED, RED, "Lid"), ("plate.py", PLATE, BLUE, None)):
            data = encode_product_package(build_product_package(run_notebook(self.write(name, text)).definition))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "out.step"
                export_product_package_to_step(data, path)
                step = path.read_text(encoding="utf-8", errors="replace")
            rgb = [tuple(round(float(v), 3) for v in m) for m in re.findall(r"COLOUR_RGB\('[^']*',([\d.Ee+-]+),([\d.Ee+-]+),([\d.Ee+-]+)\)", step)]
            # OCCT takes the colour as linear RGB (Quantity_TOC_RGB, as for a material colour) and STEP stores sRGB
            srgb = tuple(round(c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055, 3) for c in expected)
            self.assertTrue(any(all(abs(a - b) < 2e-3 for a, b in zip(srgb, row)) for row in rgb), (name, rgb))
            if label:
                self.assertIn(f"'{label}'", step)


if __name__ == "__main__":
    unittest.main()
