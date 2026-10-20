"""Variable-level dependencies on local modules.

A cell that does ``from lib.dims import A`` depends on the definition of
``A`` (and what that definition reads), not on the whole file: editing
another name of ``lib/dims.py`` must leave the cell cached.  Anything the
analysis cannot prove falls back to the whole file.
"""

from __future__ import annotations

from simplecadapi.runtime import run_notebook
from simplecadapi.runtime.deps import state_dir
from simplecadapi.runtime.names import definition_digest
from test_notebook_runtime import NotebookTestCase, cell, notebook_text


class TestDefinitionDigest(NotebookTestCase):
    def digest(self, name: str, module: str = "lib.dims") -> str | None:
        return definition_digest(self.root, module, name)

    def test_an_unrelated_name_does_not_move_the_digest(self) -> None:
        self.write("lib/dims.py", "A = 1.0\nB = 2.0\n")
        before = self.digest("A")
        self.write("lib/dims.py", "A = 1.0\nB = 9.0\n")
        self.assertEqual(self.digest("A"), before)
        self.assertNotEqual(self.digest("B"), definition_digest(self.root, "lib.dims", "A"))

    def test_the_definition_itself_moves_it(self) -> None:
        self.write("lib/dims.py", "A = 1.0\n")
        before = self.digest("A")
        self.write("lib/dims.py", "A = 1.5\n")
        self.assertNotEqual(self.digest("A"), before)

    def test_formatting_and_comments_do_not_move_it(self) -> None:
        self.write("lib/dims.py", "A = 1.0\n")
        before = self.digest("A")
        self.write("lib/dims.py", "# note\nA   =   1.0  # same\n")
        self.assertEqual(self.digest("A"), before)

    def test_names_it_reads_in_the_module_are_followed(self) -> None:
        self.write("lib/dims.py", "BASE = 2.0\nA = BASE * 3\nOTHER = 1\n")
        before = self.digest("A")
        self.write("lib/dims.py", "BASE = 2.0\nA = BASE * 3\nOTHER = 5\n")
        self.assertEqual(self.digest("A"), before)
        self.write("lib/dims.py", "BASE = 4.0\nA = BASE * 3\nOTHER = 5\n")
        self.assertNotEqual(self.digest("A"), before)

    def test_functions_and_classes_are_definitions_too(self) -> None:
        self.write("lib/dims.py", "K = 2\n\ndef half(x):\n    return x / K\n\nZ = 0\n")
        before = self.digest("half")
        self.write("lib/dims.py", "K = 2\n\ndef half(x):\n    return x / K\n\nZ = 1\n")
        self.assertEqual(self.digest("half"), before)
        self.write("lib/dims.py", "K = 4\n\ndef half(x):\n    return x / K\n\nZ = 1\n")
        self.assertNotEqual(self.digest("half"), before)

    def test_a_name_imported_from_another_local_module_is_followed(self) -> None:
        self.write("lib/base.py", "W = 1.0\nV = 2.0\n")
        self.write("lib/dims.py", "from lib.base import W\nA = W * 2\n")
        before = self.digest("A")
        self.write("lib/base.py", "W = 1.0\nV = 3.0\n")
        self.assertEqual(self.digest("A"), before)
        self.write("lib/base.py", "W = 2.0\nV = 3.0\n")
        self.assertNotEqual(self.digest("A"), before)

    def test_what_it_cannot_prove_falls_back_to_the_whole_file(self) -> None:
        for text in (
            "from lib.base import *\nA = 1\n",  # unknown bindings
            "A = 1\nprint('side effect')\n",  # a statement with effects
            "import os\nA = 1\nA += os.getpid() * 0\n",  # name rebound
            "A = 1\n",  # (control: provable)
        ):
            self.write("lib/base.py", "W = 1\n")
            self.write("lib/dims.py", text)
            expected_none = text != "A = 1\n"
            self.assertEqual(self.digest("A") is None, expected_none, text)
        self.assertIsNone(self.digest("MISSING"))
        self.assertIsNone(definition_digest(self.root, "lib.nope", "A"))


TWO_NAMES = notebook_text(
    cell("from lib.dims import A", returns="A"),
    cell("from lib.dims import B", returns="B"),
    cell("box = scad.make_box_rsolid(A, 4.0, 4.0)", reads="A", returns="box"),
    cell("plate = scad.make_box_rsolid(B, B, 1.0)", reads="B", returns="plate"),
    cell(
        "part = scad.Part(part_id='names', body=scad.union_rsolid(box, plate))",
        reads="box, plate",
        returns="part",
    ),
    table='id = "names"',
)


class TestVariableLevelCache(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write("lib/dims.py", "A = 10.0\nB = 6.0\n")
        self.nb = self.write("names.py", TWO_NAMES)

    def test_editing_one_name_reruns_only_what_reads_it(self) -> None:
        run_notebook(self.nb)
        self.write("lib/dims.py", "A = 12.0\nB = 6.0\n")
        changed = run_notebook(self.nb)
        # setup, A, B (its name is unchanged), box, plate (cached), part
        self.assertEqual(self.statuses(changed), ["ran", "ran", "cached", "ran", "cached", "ran"])

    def test_an_edit_to_a_name_nobody_reads_reruns_nothing(self) -> None:
        run_notebook(self.nb)
        self.write("lib/dims.py", "A = 10.0\nB = 6.0\nUNUSED = 1\n")
        self.assertEqual(self.statuses(run_notebook(self.nb)), ["ran"] + ["cached"] * 5)

    def test_the_result_is_what_a_fresh_run_gives(self) -> None:
        run_notebook(self.nb)
        for text in ("A = 12.0\nB = 6.0\n", "A = 12.0\nB = 8.0\nC = 1\n", "A = 10.0\nB = 6.0\n"):
            self.write("lib/dims.py", text)
            self.assertEqual(
                run_notebook(self.nb).definition.content_hash,
                run_notebook(self.nb, cache=False).definition.content_hash,
                text,
            )


class TestWhatTheCacheStores(NotebookTestCase):
    """A cell's private (underscore) names are invisible to every other cell:
    storing them only costs disk and restore time."""

    def test_private_names_are_not_stored_and_the_cell_is_still_restored(self) -> None:
        text = notebook_text(
            cell(
                """
                _scratch = scad.make_box_rsolid(30.0, 30.0, 30.0)
                width = 20.0
                """,
                returns="width",
            ),
            cell("block = scad.make_box_rsolid(width, 4.0, 4.0)", reads="width", returns="block"),
            cell("part = scad.Part(part_id='priv', body=block)", reads="block", returns="part"),
            table='id = "priv"',
        )
        path = self.write("priv.py", text)
        first = run_notebook(path)
        stored = {item.stem for item in (state_dir(first.config) / "cache").rglob("*.pickle")}
        self.assertIn("block", stored)
        self.assertNotIn("_scratch", stored)
        second = run_notebook(path)
        self.assertEqual(self.statuses(second), ["ran", "cached", "cached", "cached"])
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)
