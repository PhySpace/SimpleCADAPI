"""Multi-body parts: one Part, several named solids kept apart (not an assembly).

The spike of design-docs/multi-solid-design.md: a Part made from ``bodies={"base": ..., "lid": ...}`` keeps both
solids, previews them as two nodes, packages each with its own BRep and topology snapshot, exports one STEP product
holding both, reports the mass of each body, and survives the notebook cell cache.  One-body Parts are unchanged.
"""

from __future__ import annotations

import copy
import pickle
import re
import tempfile
import unittest
from pathlib import Path

import simplecadapi as scad
from simplecadapi.artifacts import materialize_definition
from simplecadapi.exporter.step import export_product_package_to_step
from simplecadapi.product.packages import build_product_package, encode_product_package, load_product_package
from simplecadapi.runtime import run_notebook
from simplecadapi.scene.preview import compile_preview, decode_preview_header, encode_preview, entity_info

from test_notebook_runtime import NotebookTestCase, cell, notebook_text


def _base() -> scad.Solid:
    return scad.make_box_rsolid(20.0, 20.0, 10.0, tag_prefix="base")


def _lid() -> scad.Solid:
    return scad.make_box_rsolid(20.0, 20.0, 2.0, (40.0, 0.0, 0.0), tag_prefix="lid")


def _case() -> scad.Part:
    return scad.make_part_rpart(part_id="case", bodies={"base": _base(), "lid": _lid()})


def _tags(solid: scad.Solid) -> set[str]:
    return {tag for face in solid.faces() for tag in face._tags}


class TestMultiBodyPartValue(unittest.TestCase):
    def test_bodies_are_kept_apart_in_order(self) -> None:
        case = _case()
        self.assertTrue(case.multi_body)
        self.assertEqual(case.body_ids(), ("base", "lid"))
        self.assertEqual([type(body).__name__ for body in case.bodies], ["Body", "Body"])
        self.assertAlmostEqual(case.get_body("lid").solid.get_volume(), 800.0, places=6)
        self.assertIn("lid.face.top", _tags(case.get_body("lid").solid))
        self.assertEqual(case.to_dict()["bodies"], [{"body_id": "base", "name": None}, {"body_id": "lid", "name": None}])

    def test_body_is_refused_on_a_multi_body_part(self) -> None:
        with self.assertRaisesRegex(TypeError, r"has 2 bodies \(base, lid\)"):
            _case().body
        with self.assertRaises(KeyError):
            _case().get_body("hinge")

    def test_bodies_may_be_body_values_with_names(self) -> None:
        case = scad.make_part_rpart(
            part_id="case", bodies=[scad.Body("base", _base(), "Base"), scad.Body("lid", _lid(), name="Lid")]
        )
        self.assertEqual([body.name for body in case.bodies], ["Base", "Lid"])

    def test_bad_bodies_are_refused(self) -> None:
        with self.assertRaises(Exception):
            scad.make_part_rpart(part_id="case", body=_base(), bodies={"lid": _lid()})
        with self.assertRaises(Exception):
            scad.make_part_rpart(part_id="case")
        with self.assertRaisesRegex(Exception, "duplicate body_id"):
            scad.Part(part_id="case", bodies=[scad.Body("a", _base()), scad.Body("a", _lid())])
        with self.assertRaises(Exception):
            scad.make_part_rpart(part_id="case", bodies={"not an id": _base(), "lid": _lid()})
        with self.assertRaises(Exception):
            scad.make_part_rpart(part_id="case", bodies={"base": _base(), "lid": "lid"})

    def test_a_one_body_part_is_what_it_always_was(self) -> None:
        part = scad.make_part_rpart(part_id="plate", body=_base())
        self.assertFalse(part.multi_body)
        self.assertEqual(part.body_ids(), ("body",))
        self.assertTrue(part.body.same_topology(part.bodies[0].solid))
        self.assertNotIn("bodies", part.to_dict())

    def test_pickle_and_deepcopy_keep_every_body_and_its_tags(self) -> None:
        case = _case().with_material(scad.make_material_rmaterial(material_id="pp", density=900.0, density_unit="kg/m^3"))
        for again in (pickle.loads(pickle.dumps(case)), copy.deepcopy(case)):
            self.assertEqual(again.body_ids(), ("base", "lid"))
            self.assertEqual(again.material.material_id, "pp")
            self.assertEqual(_tags(again.get_body("lid").solid), _tags(case.get_body("lid").solid))
        one = pickle.loads(pickle.dumps(scad.make_part_rpart(part_id="plate", body=_base())))
        self.assertFalse(one.multi_body)

    def test_material_and_connectors(self) -> None:
        material = scad.make_material_rmaterial(material_id="al", density=2.7, density_unit="g/cm^3")
        case = scad.assign_material_rpart(_case(), material)
        self.assertEqual(case.body_ids(), ("base", "lid"))
        connector = scad.make_placement_connector_rconnector(
            connector_id="mount", placement=scad.identity_placement_rplacement()
        )
        with self.assertRaisesRegex(Exception, "multi-body"):
            scad.add_connector_rpart(case, connector)

    def test_an_assembly_of_a_multi_body_part_flattens_every_body(self) -> None:
        rig = scad.make_assembly_rassembly(assembly_id="rig")
        rig = scad.add_component_rassembly(
            assembly=rig, item=_case(), component_id="case", placement=scad.make_placement_rplacement(origin=(0, 0, 5))
        )
        compound = scad.make_compound_from_assembly_rcompound(assembly=rig)
        self.assertEqual(len(compound.solids()), 2)


class TestMultiBodyReplay(unittest.TestCase):
    def test_a_recorded_multi_body_part_replays_with_its_bodies(self) -> None:
        with scad.GraphSession() as session:
            _case()
        replayed = [item for item in scad.replay_model_json(scad.export_model_json(session)) if isinstance(item, scad.Part)]
        self.assertEqual([part.body_ids() for part in replayed], [("base", "lid")])
        self.assertAlmostEqual(replayed[0].get_body("lid").solid.get_volume(), 800.0, places=6)


class TestMultiBodyMass(unittest.TestCase):
    def test_mass_of_each_body_and_of_the_part(self) -> None:
        material = scad.make_material_rmaterial(material_id="al", density=2.7, density_unit="g/cm^3")
        report = scad.measure_part_mass_rmassreport(scad.assign_material_rpart(_case(), material))
        self.assertEqual([item.body_id for item in report.bodies], ["base", "lid"])
        self.assertAlmostEqual(report.body("base").volume_mm3, 4000.0, places=6)
        self.assertAlmostEqual(report.body("base").mass_kg, 4000.0 * 2.7e-6, places=12)
        self.assertAlmostEqual(report.body("lid").mass_kg, 800.0 * 2.7e-6, places=12)
        self.assertAlmostEqual(report.mass_kg, 4800.0 * 2.7e-6, places=12)
        self.assertAlmostEqual(report.body("lid").centroid_mm[0], 40.0, places=6)
        self.assertAlmostEqual(report.centroid_mm[0], 800.0 * 40.0 / 4800.0, places=6)

    def test_without_a_density_masses_are_none(self) -> None:
        report = scad.measure_part_mass_rmassreport(_case())
        self.assertIsNone(report.mass_kg)
        self.assertAlmostEqual(report.volume_mm3, 4800.0, places=6)
        override = scad.measure_part_mass_rmassreport(_case(), density=1000.0)
        self.assertAlmostEqual(override.body("lid").mass_kg, 800.0e-6, places=12)

    def test_a_one_body_part_has_one_row(self) -> None:
        report = scad.measure_part_mass_rmassreport(scad.make_part_rpart(part_id="plate", body=_base()))
        self.assertEqual([item.body_id for item in report.bodies], ["body"])


class TestMultiBodyPreview(unittest.TestCase):
    def test_each_body_is_a_node_with_its_own_entities(self) -> None:
        scene = compile_preview(_case())
        header = decode_preview_header(encode_preview(scene))
        self.assertEqual([node["node_id"] for node in header["nodes"]], ["node/case/body:base", "node/case/body:lid"])
        self.assertEqual({part["body_id"] for part in header["parts"]}, {"base", "lid"})
        lid = next(part for part in header["parts"] if part["body_id"] == "lid")
        self.assertTrue(lid["solid_entity_id"].startswith("entity/case/body:lid/solid/"))
        self.assertTrue(all(g["entity_id"].startswith("entity/case/body:lid/face/") for g in lid["face_groups"]))
        info = entity_info(scene, lid["solid_entity_id"])
        self.assertAlmostEqual(info["properties"]["volume"], 800.0, places=6)
        face = entity_info(scene, lid["face_groups"][0]["entity_id"])
        self.assertEqual(face["kind"], "face")
        self.assertTrue(any(tag.startswith("lid.face.") for tag in face["tags"]))

    def test_two_bodies_of_the_same_shape_stay_two(self) -> None:
        a = scad.make_box_rsolid(5.0, 5.0, 5.0)
        b = scad.make_box_rsolid(5.0, 5.0, 5.0)
        scene = compile_preview(scad.make_part_rpart(part_id="pair", bodies={"a": a, "b": b}))
        self.assertEqual(len(scene.nodes), 2)
        self.assertEqual(len(scene.parts), 2)

    def test_a_one_body_part_previews_as_before(self) -> None:
        header = decode_preview_header(encode_preview(compile_preview(scad.make_part_rpart(part_id="plate", body=_base()))))
        self.assertEqual([node["node_id"] for node in header["nodes"]], ["node/plate"])
        self.assertNotIn("body_id", header["parts"][0])
        self.assertTrue(header["parts"][0]["solid_entity_id"].startswith("entity/plate/solid/"))


CASE = notebook_text(
    cell(
        """
        base = scad.make_box_rsolid(20.0, 20.0, 10.0, tag_prefix="base")
        lid = scad.make_box_rsolid(20.0, 20.0, 2.0, (40.0, 0.0, 0.0), tag_prefix="lid")
        """,
        returns="base, lid",
    ),
    cell(
        'case = scad.make_part_rpart(part_id=scad.notebook_id(), bodies={"base": base, "lid": lid})',
        reads="base, lid",
        returns="case",
    ),
    table='id = "case"',
)


class TestMultiBodyNotebook(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.case = self.write("case.py", CASE)

    def test_the_cell_cache_restores_a_multi_body_product(self) -> None:
        first = run_notebook(self.case)
        second = run_notebook(self.case)
        self.assertEqual(self.statuses(second), ["ran", "cached", "cached"])
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)
        self.assertEqual([item.body_id for item in second.definition.bodies], ["base", "lid"])

    def test_the_package_holds_both_bodies_with_their_tags(self) -> None:
        definition = run_notebook(self.case).definition
        manifest = definition.to_dict()
        self.assertEqual([row["body_id"] for row in manifest["solid_cache"]["bodies"]], ["base", "lid"])
        loaded = load_product_package(encode_product_package(build_product_package(definition)))
        part = materialize_definition(loaded)  # the package's root definition, read back from its bytes
        self.assertEqual(part.body_ids(), ("base", "lid"))
        self.assertIn("lid.face.top", _tags(part.get_body("lid").solid))
        self.assertIn("base.face.top", _tags(part.get_body("base").solid))
        self.assertAlmostEqual(scad.measure_part_mass_rmassreport(part).body("lid").volume_mm3, 800.0, places=6)

    def test_the_scene_draws_each_body_as_a_solid_node(self) -> None:
        from simplecadapi.scene.product_scene import compile_product_scene

        manifest = compile_product_scene(run_notebook(self.case).definition).manifest
        nodes = {node["node_id"]: node for node in manifest["nodes"]}
        self.assertIsNone(nodes["node/case"]["geometry_asset_id"])
        self.assertEqual(nodes["node/case/body:lid"]["node_kind"], "solid")
        self.assertEqual(nodes["node/case/body:lid"]["parent_node_id"], "node/case")
        self.assertIsNotNone(nodes["node/case/body:base"]["geometry_asset_id"])
        self.assertNotEqual(nodes["node/case/body:base"]["entity_asset_id"], nodes["node/case/body:lid"]["entity_asset_id"])

    def test_step_export_writes_one_product_with_both_solids(self) -> None:
        data = encode_product_package(build_product_package(run_notebook(self.case).definition))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.step"
            export_product_package_to_step(data, path)
            text = path.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(len(re.findall(r"MANIFOLD_SOLID_BREP", text)), 2)
        self.assertEqual(len(re.findall(r"= PRODUCT\(", text)), 1)

    def test_a_one_body_definition_has_no_bodies_list(self) -> None:
        self.write(
            "plate.py",
            notebook_text(
                cell("plate = scad.make_part_rpart(part_id=scad.notebook_id(), body=scad.make_box_rsolid(5.0, 5.0, 1.0))", returns="plate"),
                table='id = "plate"',
            ),
        )
        definition = run_notebook(self.root / "plate.py").definition
        self.assertNotIn("bodies", definition.to_dict()["solid_cache"])
        self.assertEqual(definition.bodies, ())


if __name__ == "__main__":
    unittest.main()
