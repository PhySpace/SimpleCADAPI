"""A Part holds exactly one solid; several solids side by side are loose notebook values.

The decision (design-docs/part-holds-one-solid.md): a Part is the unit an Assembly places, mates and gives connectors
to, so it is one solid.  The solids the editor needs next to each other while a model is built (a tool and its target,
the tools of a pattern before the cut) are notebook values: they are previewed side by side, and a notebook that ends
with several of them and no Part has no product (``SeveralOpenBodiesError``) until the author chooses one.

This file replaces ``test_multi_body_part.py``.  Its split-cut tests (``Pieces``) stay: pieces are notebook values.
"""

from __future__ import annotations

import pickle
import unittest

import pytest

import simplecadapi as scad
from simplecadapi.runtime import run_notebook
from simplecadapi.runtime.projection import SeveralOpenBodiesError
from simplecadapi.scene.preview import compile_open_bodies, compile_preview, decode_preview_header, encode_preview, entity_info

from test_notebook_runtime import NotebookTestCase, cell, notebook_text


def _base() -> scad.Solid:
    return scad.make_box_rsolid(20.0, 20.0, 10.0, tag_prefix="base")


def _lid() -> scad.Solid:
    return scad.make_box_rsolid(20.0, 20.0, 2.0, (40.0, 0.0, 0.0), tag_prefix="lid")


class TestAPartIsOneSolid(unittest.TestCase):
    def test_a_part_has_one_body(self) -> None:
        part = scad.make_part_rpart(part_id="plate", body=_base())
        self.assertEqual(part.body_ids(), ("body",))
        self.assertEqual(len(part.bodies), 1)
        self.assertTrue(part.body.same_topology(part.bodies[0].solid))
        self.assertFalse(hasattr(part, "multi_body"))
        self.assertNotIn("bodies", part.to_dict())

    def test_several_solids_are_refused_with_what_to_do(self) -> None:
        for build in (
            lambda: scad.make_part_rpart(part_id="case", body=[_base(), _lid()]),  # the pieces of a split cut
            lambda: scad.Part(part_id="case", body=[_base(), _lid()]),
        ):
            with self.assertRaisesRegex(Exception, r"exactly one solid.*one Part per"):
                build()

    def test_the_bodies_argument_no_longer_exists(self) -> None:
        with self.assertRaises(TypeError):
            scad.make_part_rpart(part_id="case", bodies={"base": _base(), "lid": _lid()})
        with self.assertRaises(TypeError):
            scad.Part(part_id="case", bodies=[scad.Body("a", _base())])
        with self.assertRaises(Exception):
            scad.make_part_rpart(part_id="case")  # a body is required

    def test_one_solid_in_a_list_or_a_body_is_accepted(self) -> None:
        self.assertEqual(scad.make_part_rpart(part_id="one", body=[_base()]).body_ids(), ("body",))
        named = scad.Part(part_id="one", body=scad.Body("body", _base(), "Base", color=(0.1, 0.2, 0.3), opacity=0.5))
        self.assertEqual((named.bodies[0].name, named.bodies[0].color, named.bodies[0].opacity), ("Base", (0.1, 0.2, 0.3), 0.5))

    def test_pickle_and_deepcopy_keep_the_body_and_its_tags(self) -> None:
        part = scad.make_part_rpart(part_id="plate", body=_base())
        again = pickle.loads(pickle.dumps(part))
        self.assertEqual(again.body_ids(), ("body",))
        self.assertIn("base.face.top", {tag for face in again.body.faces() for tag in face._tags})

    def test_the_mass_report_has_one_row(self) -> None:
        material = scad.make_material_rmaterial(material_id="al", density=2.7, density_unit="g/cm^3")
        report = scad.measure_part_mass_rmassreport(scad.assign_material_rpart(scad.make_part_rpart(part_id="base", body=_base()), material))
        self.assertEqual([item.body_id for item in report.bodies], ["body"])
        self.assertAlmostEqual(report.mass_kg, 4000.0 * 2.7e-6, places=12)

    def test_the_removed_helpers_are_gone(self) -> None:
        for name in ("part_shape", "inspect_body_overlaps_rlist", "BodyOverlap", "BodyOverlapWarning"):
            self.assertFalse(hasattr(scad, name), name)


class TestEveryPartCanJoinAnAssembly(unittest.TestCase):
    """What the multi-body Part could not do (it refused connectors and made explode_rassembly raise)."""

    def _rig(self) -> scad.Assembly:
        mount = scad.make_placement_connector_rconnector(connector_id="mount", placement=scad.identity_placement_rplacement())
        base = scad.add_connector_rpart(scad.make_part_rpart(part_id="base", body=_base()), mount)
        lid = scad.add_connector_rpart(scad.make_part_rpart(part_id="lid", body=_lid()), mount)
        rig = scad.make_assembly_rassembly(assembly_id="rig")
        rig = scad.add_component_rassembly(assembly=rig, item=base, component_id="base", placement=scad.identity_placement_rplacement())
        return scad.add_component_rassembly(
            assembly=rig, item=lid, component_id="lid", placement=scad.make_placement_rplacement(origin=(0, 0, 10))
        )

    def test_a_part_takes_connectors(self) -> None:
        part = scad.add_connector_rpart(
            scad.make_part_rpart(part_id="base", body=_base()),
            scad.make_placement_connector_rconnector(connector_id="mount", placement=scad.identity_placement_rplacement()),
        )
        self.assertEqual(part.connector_ids(), ("mount",))

    def test_the_assembly_flattens_explodes_and_previews(self) -> None:
        rig = self._rig()
        self.assertEqual(len(scad.make_compound_from_assembly_rcompound(assembly=rig).solids()), 2)
        exploded = scad.explode_rassembly(rig, 1.0)
        self.assertEqual(set(exploded.component_ids()), {"base", "lid"})
        header = decode_preview_header(encode_preview(compile_preview(rig)))
        self.assertEqual([node["node_id"] for node in header["nodes"]], ["node/rig/base", "node/rig/lid"])

    def test_several_solids_are_delivered_as_an_assembly_of_parts(self) -> None:
        rig = scad.make_assembly_rassembly(assembly_id="case")
        for name, solid in (("base", _base()), ("lid", _lid())):
            rig = scad.add_component_rassembly(
                assembly=rig,
                item=scad.make_part_rpart(part_id=name, body=solid),
                component_id=name,
                placement=scad.identity_placement_rplacement(),
            )
        self.assertEqual(len(scad.make_compound_from_assembly_rcompound(assembly=rig).solids()), 2)


class TestReplay(unittest.TestCase):
    def test_a_recorded_part_replays(self) -> None:
        with scad.GraphSession() as session:
            scad.make_part_rpart(part_id="plate", body=_base())
        replayed = [item for item in scad.replay_model_json(scad.export_model_json(session)) if isinstance(item, scad.Part)]
        self.assertEqual([part.body_ids() for part in replayed], [("body",)])
        self.assertAlmostEqual(replayed[0].body.get_volume(), 4000.0, places=6)

    def test_a_model_recorded_with_several_solids_in_one_part_is_refused(self) -> None:
        import json

        with scad.GraphSession() as session:
            scad.make_part_rpart(part_id="plate", body=_base())
        model = json.loads(scad.export_model_json(session))
        node = next(n for n in model["graph"]["nodes"] if n.get("op") == "make_part_rpart") if "graph" in model else None
        if node is None:
            self.skipTest("the model JSON layout has no graph/nodes with ops to edit")
        params = node.setdefault("params", {})
        params["bodies"] = [{"body_id": "a", "name": None}, {"body_id": "b", "name": None}]
        with self.assertRaisesRegex(Exception, "exactly one solid"):
            scad.replay_model_json(json.dumps(model))


class TestOpenBodiesPreview(unittest.TestCase):
    """The editor's several solids side by side: drawn as nodes of the notebook, not as the bodies of a Part."""

    def test_each_open_solid_is_a_node_with_its_own_entities(self) -> None:
        scene = compile_open_bodies("nb", {"base": _base(), "lid": _lid()})
        header = decode_preview_header(encode_preview(scene))
        self.assertEqual([node["node_id"] for node in header["nodes"]], ["node/nb/body:base", "node/nb/body:lid"])
        self.assertEqual({part["body_id"] for part in header["parts"]}, {"base", "lid"})
        lid = next(part for part in header["parts"] if part["body_id"] == "lid")
        self.assertTrue(lid["solid_entity_id"].startswith("entity/nb/body:lid/solid/"))
        info = entity_info(scene, lid["solid_entity_id"])
        self.assertAlmostEqual(info["properties"]["volume"], 800.0, places=6)
        face = entity_info(scene, lid["face_groups"][0]["entity_id"])
        self.assertEqual(face["kind"], "face")
        self.assertTrue(any(tag.startswith("lid.face.") for tag in face["tags"]))

    def test_two_solids_of_the_same_shape_stay_two(self) -> None:
        scene = compile_open_bodies("pair", {"a": scad.make_box_rsolid(5.0, 5.0, 5.0), "b": scad.make_box_rsolid(5.0, 5.0, 5.0)})
        self.assertEqual((len(scene.nodes), len(scene.parts)), (2, 2))

    def test_a_part_previews_as_one_node(self) -> None:
        header = decode_preview_header(encode_preview(compile_preview(scad.make_part_rpart(part_id="plate", body=_base()))))
        self.assertEqual([node["node_id"] for node in header["nodes"]], ["node/plate"])
        self.assertNotIn("body_id", header["parts"][0])
        self.assertTrue(header["parts"][0]["solid_entity_id"].startswith("entity/plate/solid/"))

    def test_nothing_to_draw_is_an_error(self) -> None:
        with self.assertRaises(Exception):
            compile_open_bodies("nb", {})


def _part_notebook(*cells: str, notebook_id: str = "demo") -> str:
    return notebook_text(*cells, table=f'id = "{notebook_id}"\nkind = "part"')


TWO_OPEN = _part_notebook(
    cell(
        """
        base = scad.make_box_rsolid(20.0, 20.0, 10.0, tag_prefix="base")
        tool = scad.make_cylinder_rsolid(3.0, 30.0, (10.0, 10.0, -5.0))
        """,
        returns="base, tool",
    ),
)

ONE_OPEN = _part_notebook(cell("base = scad.make_box_rsolid(20.0, 20.0, 10.0)", returns="base"))

CHOSEN = _part_notebook(
    cell(
        """
        base = scad.make_box_rsolid(20.0, 20.0, 10.0, tag_prefix="base")
        tool = scad.make_cylinder_rsolid(3.0, 30.0, (10.0, 10.0, -5.0))
        """,
        returns="base, tool",
    ),
    cell("demo = scad.make_part_rpart(part_id=scad.notebook_id(), body=base)", reads="base", returns="demo"),
)

CUT = _part_notebook(
    cell(
        """
        base = scad.make_box_rsolid(20.0, 20.0, 10.0)
        tool = scad.make_cylinder_rsolid(3.0, 30.0, (10.0, 10.0, -5.0))
        """,
        returns="base, tool",
    ),
    cell("bored = scad.cut_rsolid(base, tool)", reads="base, tool", returns="bored"),
)


class TestNotebookProduct(NotebookTestCase):
    def test_one_open_solid_is_the_implicit_part(self) -> None:
        product = run_notebook(self.write("one.py", ONE_OPEN.replace('"demo"', '"one"'))).product
        self.assertEqual((product.part_id, product.body_ids()), ("one", ("body",)))

    def test_several_open_solids_have_no_product(self) -> None:
        with self.assertRaises(SeveralOpenBodiesError) as caught:
            run_notebook(self.write("two.py", TWO_OPEN))
        self.assertEqual(sorted(caught.exception.names), ["base", "tool"])  # the order of names defined in one cell is not fixed
        message = str(caught.exception)
        self.assertIn("exactly one solid", message)
        self.assertIn("make_part_rpart", message)

    def test_the_tool_cut_into_the_body_leaves_one_open_solid(self) -> None:
        # the example of the design: a tool and its target exist together, then the cut leaves one solid
        product = run_notebook(self.write("cut.py", CUT)).product
        self.assertEqual(product.body_ids(), ("body",))
        self.assertLess(product.body.get_volume(), 20 * 20 * 10)

    def test_a_part_made_of_the_chosen_solid_is_the_product(self) -> None:
        product = run_notebook(self.write("chosen.py", CHOSEN)).product
        self.assertAlmostEqual(product.body.get_volume(), 4000.0, places=6)
        self.assertIn("base.face.top", {tag for face in product.body.faces() for tag in face._tags})

    def test_the_package_holds_one_solid_and_exports_to_step(self) -> None:
        import re
        import tempfile
        from pathlib import Path

        from simplecadapi.exporter.step import export_product_package_to_step
        from simplecadapi.product.packages import build_product_package, encode_product_package

        definition = run_notebook(self.write("chosen.py", CHOSEN)).definition
        manifest = definition.to_dict()
        self.assertEqual(manifest["profile"], "simplecad-part-definition-2")
        self.assertNotIn("bodies", manifest["solid_cache"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.step"
            export_product_package_to_step(encode_product_package(build_product_package(definition)), path)
            text = path.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(len(re.findall(r"MANIFOLD_SOLID_BREP", text)), 1)

    def test_the_cell_cache_restores_the_product(self) -> None:
        path = self.write("chosen.py", CHOSEN)
        first = run_notebook(path)
        second = run_notebook(path)
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)
        self.assertIn("cached", self.statuses(second))

    def test_the_live_preview_shows_the_open_solids(self) -> None:
        from simplecadapi.runtime.live import preview_product
        from simplecadapi.runtime.projection import OpenBodies

        from simplecadapi.runtime import config as runtime_config

        path = self.write("two.py", TWO_OPEN)
        config = runtime_config.read_notebook_config(path)
        base, tool = _base(), scad.make_cylinder_rsolid(3.0, 30.0, (10.0, 10.0, -5.0))
        product, partial = preview_product(config, [], {"base": base, "tool": tool})
        self.assertIsInstance(product, OpenBodies)
        self.assertIsNone(partial)
        self.assertEqual(list(product.bodies), ["base", "tool"])


class TestSplitCutsStillGivePieces(unittest.TestCase):
    """Pieces are notebook values (where several solids belong); a Part takes one of them."""

    @staticmethod
    def _bar_and_slot() -> tuple[scad.Solid, scad.Solid]:
        return scad.make_box_rsolid(40.0, 10.0, 10.0, tag_prefix="bar"), scad.make_box_rsolid(4.0, 20.0, 20.0, (0.0, -5.0, -5.0))

    def test_a_splitting_cut_returns_its_pieces_in_centroid_order(self) -> None:
        bar, slot = self._bar_and_slot()
        pieces = scad.cut_rsolid(bar, slot)
        self.assertIsInstance(pieces, list)
        self.assertEqual([round(p.get_center().x, 6) for p in pieces], [-11.0, 11.0])
        with self.assertRaisesRegex(Exception, "split the body"):
            scad.cut_rsolid(*self._bar_and_slot(), on_split="error")

    def test_a_piece_is_a_part_and_pieces_are_not(self) -> None:
        bar, slot = self._bar_and_slot()
        pieces = scad.cut_rsolid(bar, slot)
        with self.assertRaisesRegex(Exception, "exactly one solid"):
            scad.make_part_rpart(part_id="bar", body=pieces)
        left = scad.make_part_rpart(part_id="bar_left", body=pieces[0])
        self.assertAlmostEqual(left.body.get_volume(), 1800.0, places=6)

    def test_a_split_replays_with_the_same_piece_order(self) -> None:
        with scad.GraphSession() as session:
            bar, slot = self._bar_and_slot()
            pieces = scad.cut_rsolid(bar, slot)
            scad.make_part_rpart(part_id="bar", body=pieces[0])
        (part,) = [x for x in scad.replay_model_json(scad.export_model_json(session)) if isinstance(x, scad.Part)]
        self.assertLess(part.body.get_center().x, 0.0)


if __name__ == "__main__":
    unittest.main()


def test_a_fillet_or_chamfer_on_the_pieces_of_a_split_body_blends_each_piece():
    """A cut that splits a body gives its pieces; the blends take them, each piece gets the edges on it."""
    with scad.GraphSession(graph_id="blend-pieces"):
        pieces = scad.cut_rsolid(scad.make_box_rsolid(40.0, 10.0, 10.0), scad.make_box_rsolid(2.0, 20.0, 20.0))
        assert isinstance(pieces, list) and len(pieces) == 2
        top = scad.ql.edges().where(scad.ql.prop("geom.center.z", ">=", 9.9))
        rounded = scad.fillet_rsolid(pieces, top.exactly(8), 1.0)
        assert len(rounded) == 2 and all(r.get_volume() < p.get_volume() for r, p in zip(rounded, pieces))
        bevelled = scad.chamfer_rsolid(pieces, top, 0.5)
        assert len(bevelled) == 2 and all(b.get_volume() < p.get_volume() for b, p in zip(bevelled, pieces))
        # edges of one piece only: the other piece is kept as it is
        left = [e for e in top.resolve(pieces[0])]
        one = scad.fillet_rsolid(pieces, left, 1.0)
        assert one[1].get_volume() == pytest.approx(pieces[1].get_volume()) and one[0].get_volume() < pieces[0].get_volume()
        with pytest.raises(ValueError, match="expected .*exactly.*5.*found 8"):
            scad.fillet_rsolid(pieces, top.exactly(5), 1.0)
        assert isinstance(scad.fillet_rsolid(scad.make_box_rsolid(10.0, 10.0, 10.0), top, 1.0), scad.Solid)  # a Solid stays a Solid


def test_an_operation_on_the_pieces_of_a_split_body_applies_to_every_piece():
    """Pieces flow on: a one-shape operation runs per piece, a selection is checked over all of them."""
    with scad.GraphSession(graph_id="op-pieces"):
        pieces = scad.cut_rsolid(scad.make_box_rsolid(40.0, 10.0, 10.0), scad.make_box_rsolid(2.0, 20.0, 20.0))
        assert isinstance(pieces, scad.Pieces)
        moved = scad.translate_shape(shape=pieces, vector=(0.0, 0.0, 5.0))
        assert isinstance(moved, scad.Pieces) and [round(m.get_center().z, 6) for m in moved] == [10.0, 10.0]
        drilled = scad.cut_rsolid(pieces, scad.make_cylinder_rsolid(1.0, 30.0, (10.0, 0.0, -5.0)))
        assert len(drilled) == 2 and drilled[1].get_volume() < pieces[1].get_volume()
        assert drilled[0].get_volume() == pytest.approx(pieces[0].get_volume())
        tops = scad.ql.faces().where(scad.ql.prop("geom.center.z", ">=", 9.9))
        assert len(scad.shell_rsolid(pieces, tops.exactly(2), 1.0)) == 2
        with pytest.raises(ValueError, match="found 2"):
            scad.shell_rsolid(pieces, tops.exactly(1), 1.0)
        # several pieces are not one Part: a Part holds exactly one solid
        with pytest.raises(Exception, match="exactly one solid"):
            scad.make_part_rpart(part_id="x", body=moved)
        assert isinstance(pickle.loads(pickle.dumps(pieces)), scad.Pieces)
        # a plain list is still a list of tools: a - b - c
        box = scad.make_box_rsolid(10.0, 10.0, 10.0)
        assert isinstance(scad.cut_rsolid([box, scad.make_box_rsolid(2.0, 2.0, 20.0)]), scad.Solid)
