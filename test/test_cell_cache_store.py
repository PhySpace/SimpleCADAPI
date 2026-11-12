"""What the cell cache puts on disk: compressed, and still reading what it
wrote before it compressed."""

from __future__ import annotations

import zlib

from simplecadapi.runtime import run_notebook
from simplecadapi.runtime.deps import state_dir
from test_notebook_runtime import NotebookTestCase, cell, notebook_text

DRILLED = notebook_text(
    cell(
        """
        plate = scad.make_box_rsolid(60.0, 40.0, 6.0)
        for _i in range(24):
            _hole = scad.make_cylinder_rsolid(
                radius=1.5, height=20.0, bottom_face_center=(5.0 + _i % 6 * 9, 5.0 + _i // 6 * 9, -5.0)
            )
            plate = scad.cut_rsolid(plate, _hole)
        """,
        returns="plate",
    ),
    cell("part = scad.Part(part_id='drilled', body=plate)", reads="plate", returns="part"),
    table='id = "drilled"',
)


class TestCellCacheStore(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.nb = self.write("drilled.py", DRILLED)

    def entries(self, run):
        return [item for item in (state_dir(run.config) / "cache").rglob("*") if item.is_file() and item.name != "_runs.json"]

    def test_entries_are_stored_compressed(self) -> None:
        run = run_notebook(self.nb)
        stored = sum(item.stat().st_size for item in self.entries(run))
        plain = 0
        for item in self.entries(run):
            data = item.read_bytes()
            plain += len(zlib.decompress(data[4:])) if data.startswith(b"SCZ2") else len(data)
        self.assertGreater(plain, 100_000)
        self.assertLess(stored, plain // 2)

    def test_entries_written_before_compression_are_still_hit(self) -> None:
        first = run_notebook(self.nb)
        for item in self.entries(first):
            data = item.read_bytes()
            if data.startswith(b"SCZ2"):
                item.write_bytes(zlib.decompress(data[4:]))
        second = run_notebook(self.nb)
        self.assertEqual(self.statuses(second), ["ran", "cached", "cached"])
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)


def _params_notebook(params: str) -> str:
    """A params cell, a cell that reads `a` only, and the part made from it."""

    return notebook_text(
        cell(params, returns="a, b, w" if "w =" in params else "a, b"),
        cell("block = scad.make_box_rsolid(float(w), 4.0, 4.0)", reads="w", returns="block")
        if "w =" in params
        else cell("block = scad.make_box_rsolid(float(a), 4.0, 4.0)", reads="a", returns="block"),
        cell("part = scad.Part(part_id='vars', body=block)", reads="block", returns="part"),
        table='id = "vars"',
    )


class TestParametersAreKeyedByValue(NotebookTestCase):
    """`scad.var` is a value, not a piece of its cell's code: a cell that reads
    one parameter is not redone because another one, defined next to it,
    changed (marimo keys what it cannot hash by the code that made it)."""

    def run_edit(self, before: str, after: str):
        path = self.write("vars.py", _params_notebook(before))
        run_notebook(path)
        self.write("vars.py", _params_notebook(after))
        edited = run_notebook(path)
        fresh = run_notebook(path, cache=False)
        self.assertEqual(edited.definition.content_hash, fresh.definition.content_hash)
        return self.statuses(edited)

    A, B = 'a = scad.var("a", 10.0, unit="mm")', 'b = scad.var("b", {}, unit="mm")'

    def test_editing_a_sibling_parameter_leaves_the_reader_cached(self) -> None:
        statuses = self.run_edit(f"{self.A}\n{self.B.format(1.0)}", f"{self.A}\n{self.B.format(2.0)}")
        self.assertEqual(statuses, ["ran", "ran", "cached", "cached"])

    def test_editing_the_parameter_it_reads_redoes_it(self) -> None:
        statuses = self.run_edit(
            f"{self.A}\n{self.B.format(1.0)}", f'a = scad.var("a", 11.0, unit="mm")\n{self.B.format(1.0)}'
        )
        self.assertEqual(statuses, ["ran", "ran", "ran", "ran"])

    def test_what_else_a_declaration_says_also_redoes_it(self) -> None:
        for after in (
            'a = scad.var("a", 10.0, unit="mm", comment="new comment")',
            'a = scad.var("a2", 10.0, unit="mm")',
            'a = scad.var("a", 10.0, unit="mm", tolerance=0.1)',
        ):
            with self.subTest(after=after):
                statuses = self.run_edit(f"{self.A}\n{self.B.format(1.0)}", f"{after}\n{self.B.format(1.0)}")
                self.assertEqual(statuses[2:], ["ran", "ran"])

    def test_a_derived_expression_is_keyed_by_its_content_too(self) -> None:
        derived = f"{self.A}\n{self.B.format(1.0)}\nw = a * 2.0 + 1.0"
        statuses = self.run_edit(derived, derived.replace('b", 1.0', 'b", 2.0'))
        self.assertEqual(statuses, ["ran", "ran", "cached", "cached"])
        changed = self.run_edit(derived, derived.replace("a * 2.0", "a * 3.0"))
        self.assertEqual(changed[2:], ["ran", "ran"])


SELECTOR = notebook_text(
    cell("plate = scad.make_box_rsolid(20.0, 10.0, 5.0)", returns="plate"),
    cell(
        """
        sel_top = scad.ql.faces().where(scad.ql.prop("geom.type", "==", "PLANE")).order_by(scad.ql.key("geom.center.z"), desc=True).take(1)
        """,
        returns="sel_top",
    ),
    cell("top = sel_top.resolve(plate)", reads="plate, sel_top", returns="top"),
    cell("part = scad.Part(part_id='sel', body=plate)", reads="plate", returns="part"),
    table='id = "sel"',
)


class TestSelectorIsCacheable(NotebookTestCase):
    """A cell may return a QL selector (not yet resolved): the cache pickles it, as it did when the selector was a
    Python dataclass."""

    def test_selector_pickles_and_roundtrips(self) -> None:
        import copy
        import pickle

        from simplecadapi import ql

        selector = ql.edges().where(ql.prop("geom.type", "==", "LINE")).order_by(ql.key("geom.center.z")).take(2)
        for protocol in range(2, pickle.HIGHEST_PROTOCOL + 1):  # pybind11 pickling needs protocol 2+
            self.assertEqual(pickle.loads(pickle.dumps(selector, protocol)), selector)
        self.assertEqual(copy.deepcopy(selector), selector)
        predicate, key = ql.prop("geom.type", "==", "LINE"), ql.key("geom.center.z")
        self.assertEqual(pickle.loads(pickle.dumps(predicate)), predicate)
        self.assertEqual(pickle.loads(pickle.dumps(key)), key)

    def test_a_cell_returning_a_selector_is_cached(self) -> None:
        path = self.write("sel.py", SELECTOR)
        first = run_notebook(path)
        second = run_notebook(path)
        self.assertNotIn("cached", self.statuses(first))
        # the first status is the setup cell, which always runs
        self.assertEqual(self.statuses(second), ["ran"] + ["cached"] * (len(self.statuses(first)) - 1))


SPLIT = notebook_text(
    cell(
        "pieces = scad.cut_rsolid(scad.make_box_rsolid(40.0, 10.0, 10.0), scad.make_box_rsolid(2.0, 20.0, 20.0))",
        returns="pieces",
    ),
    cell(
        "moved = scad.translate_shape(pieces, (0.0, 0.0, 5.0))\nkind = type(pieces).__name__",
        reads="pieces",
        returns="moved, kind",
    ),
    cell("part = scad.make_part_rpart(part_id='split', body=moved[0])", reads="moved", returns="part"),  # a Part holds one solid: one piece
    table='id = "split"',
)


class TestPiecesComeBackAsPieces(NotebookTestCase):
    """marimo stores a list as a plain list; the pieces of a split body restored from the cache are still pieces."""

    def test_a_restored_split_feeds_the_next_cell_as_pieces(self) -> None:
        nb = self.write("split.py", SPLIT)
        first = run_notebook(nb)
        source = nb.read_text(encoding="utf-8").replace("(0.0, 0.0, 5.0)", "(0.0, 0.0, 6.0)")
        nb.write_text(source, encoding="utf-8")
        second = run_notebook(nb)
        self.assertEqual(self.statuses(second), ["ran", "cached", "ran", "ran"])
        self.assertEqual(second.values["kind"], "Pieces")
        self.assertEqual(second.product.body_ids(), first.product.body_ids())  # one piece is the Part (a Part holds one solid)
        self.assertAlmostEqual(second.product.body.get_center().z, first.product.body.get_center().z + 1.0, places=6)
