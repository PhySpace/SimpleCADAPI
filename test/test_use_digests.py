"""`use` in the cache: a cell depends on the notebooks it uses, one by one.

The path of a ``use`` call is usually a literal, so which notebooks a cell
depends on is known before it runs: the cell is keyed by what each of them is
(its code, not its comments or layout; the modules it imports; the notebooks
it uses in turn).  What is computed at run time is recorded by a run, as
before.
"""

from __future__ import annotations

from simplecadapi.runtime import run_notebook
from simplecadapi.runtime._marimo import InternalApp, load_notebook
from simplecadapi.runtime.cache import CellDigests
from simplecadapi.runtime.config import read_notebook_config
from simplecadapi.runtime.runner import _cell_prefix
from test_notebook_runtime import NotebookTestCase, cell, notebook_text


def child(name: str, width: float, note: str = "") -> str:
    return notebook_text(
        cell(f"width = {width}{note}", returns="width"),
        cell("block = scad.make_box_rsolid(width, 4.0, 4.0)", reads="width", returns="block"),
        cell(f"part = scad.Part(part_id='{name}', body=block)", reads="block", returns="part"),
        table=f'id = "{name}"',
    )


ASSEMBLE = """
    _asm = scad.make_assembly_rassembly(assembly_id="top", name="top")
    for _key, _item in (("a", a), ("b", b)):
        _asm = scad.add_component_rassembly(
            assembly=_asm, item=_item, component_id=_key, placement=scad.identity_placement_rplacement()
        )
    top = _asm
"""


def parent(first: str = 'scad.use("child_a.py")', second: str = 'scad.use("child_b.py")', *, before: str = "") -> str:
    cells = [cell(f"{before}\na = {first}" if before else f"a = {first}", returns="a")]
    cells += [cell(f"b = {second}", returns="b"), cell(ASSEMBLE, reads="a, b", returns="top")]
    return notebook_text(*cells, table='id = "top"')


class TestStaticUse(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write("child_a.py", child("child_a", 10.0))
        self.write("child_b.py", child("child_b", 6.0))
        self.top = self.write("top.py", parent())

    def edited(self) -> list[str]:
        run = run_notebook(self.top)
        fresh = run_notebook(self.top, cache=False)
        self.assertEqual(run.definition.content_hash, fresh.definition.content_hash)
        return self.statuses(run)

    def test_editing_one_child_redoes_only_the_cell_that_uses_it(self) -> None:
        run_notebook(self.top)
        self.write("child_a.py", child("child_a", 12.0))
        # setup, use a, use b, the assembly
        self.assertEqual(self.edited(), ["ran", "ran", "cached", "ran"])

    def test_a_comment_in_a_child_is_a_change_like_any_other(self) -> None:
        # The definition records where in the file each step is: a parent that
        # embeds the child must equal a fresh run, comment or not.
        run_notebook(self.top)
        self.write("child_a.py", child("child_a", 10.0, note="  # the width, in mm"))
        self.assertEqual(self.edited(), ["ran", "ran", "cached", "ran"])

    def test_a_module_a_child_imports_is_followed(self) -> None:
        self.write("lib/size.py", "SIZE = 5.0\n")
        text = child("child_a", 10.0).replace(
            "with app.setup:\n    import simplecadapi as scad\n",
            "with app.setup:\n    import simplecadapi as scad\n    from lib.size import SIZE\n",
        ).replace("make_box_rsolid(width, 4.0, 4.0)", "make_box_rsolid(width, SIZE, 4.0)")
        self.write("child_a.py", text)
        run_notebook(self.top)
        self.write("lib/size.py", "SIZE = 6.0\n")
        self.assertEqual(self.edited(), ["ran", "ran", "cached", "ran"])

    def test_a_grandchild_is_followed_through_the_child(self) -> None:
        self.write("deep.py", child("deep", 3.0))
        text = child("child_a", 10.0).replace(
            "block = scad.make_box_rsolid(width, 4.0, 4.0)",
            'deep = scad.use("deep.py")\n    block = scad.make_box_rsolid(width, 4.0, 4.0)',
        )
        self.write("child_a.py", text)
        run_notebook(self.top)
        self.write("deep.py", child("deep", 4.0))
        self.assertEqual(self.edited(), ["ran", "ran", "cached", "ran"])

    def test_a_path_computed_at_run_time_is_still_followed(self) -> None:
        self.write("top.py", parent(first='scad.use(_name + ".py")', before='_name = "child_a"'))
        run_notebook(self.top)
        self.write("child_a.py", child("child_a", 12.0))
        statuses = self.edited()
        self.assertEqual(statuses[1], "ran")
        self.assertEqual(statuses[3], "ran")

    def test_the_kernel_keys_a_static_use_cell_and_runs_a_dynamic_one_live(self) -> None:
        for source, expected in ((parent(), True), (parent(first='scad.use(_name + ".py")', before='_name = "child_a"'), False)):
            path = self.write("probe.py", source)
            config = read_notebook_config(path)
            internal = InternalApp(load_notebook(path, cell_prefix=_cell_prefix(config)))
            ordered = [internal.graph.cells[i] for i in internal.cell_manager.cell_ids() if i in internal.graph.cells]
            setup = internal.graph.cells.get(internal.cell_manager.setup_cell_id)
            digests = CellDigests(config, ordered, setup, kernel=True)
            first_use = next(c for c in ordered if "use(" in c.code)
            self.assertEqual(digests.digest(first_use.cell_id) is not None, expected)
