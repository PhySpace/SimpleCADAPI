"""The notebook runtime: SimpleCAD models as marimo notebooks.

Every notebook is written to a temporary directory and run headlessly with
:func:`simplecadapi.runtime.run_notebook`, the path ``sca run`` and agents
take.  The editor kernel shares the executor but is not driven from here.
"""

from __future__ import annotations

import contextlib
import copy
import importlib
import importlib.metadata
import io
import json
import pickle
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

from simplecadapi import cli
from simplecadapi.artifacts.assembly_definition import AssemblyDefinition
from simplecadapi.artifacts.feature_graph import load_feature_graph_artifact
from simplecadapi.product.assembly import Assembly
from simplecadapi.product.packages import load_product_package
from simplecadapi.runtime import (
    NotebookConfigError,
    NotebookRun,
    ProductNotFoundError,
    UnboundRequirementError,
    notebook_id,
    run_notebook,
)
from simplecadapi.runtime._marimo import load_notebook
from simplecadapi.runtime.cells import cell_keys
from simplecadapi.runtime.cli import parse_overrides
from simplecadapi.runtime.config import read_notebook_config
from simplecadapi.runtime.deps import local_modules, refresh_local_modules, state_dir
from simplecadapi.runtime.executor import SimpleCadExecutor


# ---------------------------------------------------------------------------
# Writing notebooks
# ---------------------------------------------------------------------------


def cell(body: str, *, reads: str = "", returns: str = "") -> str:
    """One ``@app.cell``; *reads* and *returns* are comma-separated names."""

    code = textwrap.indent(textwrap.dedent(body).strip(), "    ")
    names = [name.strip() for name in returns.split(",") if name.strip()]
    result = f"return ({', '.join(names)},)" if names else "return"
    return f"@app.cell\ndef _({reads}):\n{code}\n    {result}\n"


def notebook_text(*cells: str, table: str | None = "", setup: str = "import simplecadapi as scad") -> str:
    """A marimo notebook; *table* is the ``[tool.simplecadapi]`` body, or
    ``None`` for a notebook without one."""

    header = ""
    if table is not None:
        lines = ["[tool.simplecadapi]", *textwrap.dedent(table).strip().splitlines()]
        header = "# /// script\n" + "".join(f"# {line}".rstrip() + "\n" for line in lines) + "# ///\n"
    body = "\n\n".join(cells)
    return (
        f"{header}import marimo\n\napp = marimo.App()\n\n"
        f"with app.setup:\n    {setup}\n\n\n{body}\n\n"
        'if __name__ == "__main__":\n    app.run()\n'
    )


BRACKET = notebook_text(
    cell("width = 20.0", returns="width"),
    cell(
        """
        block = scad.make_box_rsolid(width, 10.0, 5.0)
        from lib.dims import HOLE_RADIUS
        hole = scad.make_cylinder_rsolid(HOLE_RADIUS, 5.0)
        body = scad.cut_rsolid(block, hole)
        """,
        reads="width",
        returns="body",
    ),
    cell('bracket = scad.Part(part_id="bracket", body=body)', reads="body", returns="bracket"),
    table='id = "bracket"',
)

RIG = notebook_text(
    cell('bracket = scad.use("bracket.py", width=24.0)', returns="bracket"),
    cell(
        """
        @scad.part(id="pin")
        def build_pin() -> scad.Part:
            return scad.Part(part_id="pin", body=scad.make_cylinder_rsolid(1.5, 12.0))

        pin = build_pin().part
        """,
        returns="build_pin, pin",
    ),
    cell(
        """
        rig = scad.make_assembly_rassembly(assembly_id="rig", name="Rig")
        rig = scad.add_component_rassembly(
            assembly=rig, item=bracket, component_id="bracket",
            placement=scad.identity_placement_rplacement(),
        )
        rig = scad.add_component_rassembly(
            assembly=rig, item=pin, component_id="pin",
            placement=scad.make_placement_rplacement(origin=(0.0, 0.0, 5.0)),
        )
        """,
        reads="bracket, pin",
        returns="rig",
    ),
    table='id = "rig"',
)


class NotebookTestCase(unittest.TestCase):
    """A temporary project directory with ``lib/dims.py``."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.write("lib/__init__.py", "")
        self.write("lib/dims.py", "HOLE_RADIUS = 3.0\n")

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def statuses(run: NotebookRun) -> list[str]:
        return [report.status for report in run.cells]

    @staticmethod
    def graph_nodes(run: NotebookRun) -> list[dict[str, Any]]:
        definition = run.definition
        artifact = load_feature_graph_artifact(definition.blobs[definition.feature_graph_ref.path])
        return [dict(node) for node in artifact.graph["nodes"]]


# ---------------------------------------------------------------------------
# Configuration and cells
# ---------------------------------------------------------------------------


class TestNotebookConfig(NotebookTestCase):
    def test_defaults_come_from_the_file_name(self) -> None:
        config = read_notebook_config(self.write("flange.py", notebook_text(cell("x = 1"))))
        assert config is not None
        self.assertEqual(config.id, "flange")
        self.assertEqual(config.revision, "1.0.0")
        self.assertEqual(config.tolerance_profile, "simplecad-default")
        self.assertEqual(config.inputs, ())

    def test_a_notebook_without_the_table_is_not_ours(self) -> None:
        path = self.write("plain.py", notebook_text(cell("x = 1"), table=None))
        self.assertIsNone(read_notebook_config(path))
        with self.assertRaises(NotebookConfigError):
            run_notebook(path)

    def test_unknown_keys_are_rejected(self) -> None:
        path = self.write("bad.py", notebook_text(cell("x = 1"), table='colour = "red"'))
        with self.assertRaisesRegex(NotebookConfigError, "colour"):
            read_notebook_config(path)


class TestCellKeys(unittest.TestCase):
    def test_keys_follow_the_code_and_number_repeats(self) -> None:
        first, again, other, stripped = cell_keys(["x = 1", "x = 1", "y = 2", "\nx = 1\n"])
        self.assertRegex(first, r"^c[0-9a-f]{8}$")
        self.assertEqual(again, f"{first}_2")
        self.assertNotEqual(other, first)
        self.assertEqual(stripped, f"{first}_3")


class TestLoadNotebook(NotebookTestCase):
    def test_cell_ids_are_prefixed_per_notebook(self) -> None:
        text = notebook_text(cell("x = 1", returns="x"))
        one = load_notebook(self.write("one.py", text), cell_prefix="a-")
        two = load_notebook(self.write("two.py", text), cell_prefix="b-")
        assert one is not None and two is not None
        ids_one = set(one._cell_manager.cell_ids())
        ids_two = set(two._cell_manager.cell_ids())
        self.assertTrue(all(cell_id.startswith("a-") for cell_id in ids_one))
        self.assertFalse(ids_one & ids_two)

    def test_an_empty_file_has_no_notebook(self) -> None:
        self.assertIsNone(load_notebook(self.write("empty.py", ""), cell_prefix="a-"))


# ---------------------------------------------------------------------------
# Local modules
# ---------------------------------------------------------------------------


class TestLocalModules(NotebookTestCase):
    def modules(self, *codes: str) -> dict[str, str]:
        config = read_notebook_config(self.write("nb.py", notebook_text(cell("x = 1"))))
        assert config is not None
        return {
            name: path.relative_to(self.root).as_posix()
            for name, path in local_modules(config, codes).items()
        }

    def test_imports_resolve_to_files_under_the_notebook_directory(self) -> None:
        self.assertEqual(
            self.modules("import os, json", "from lib.dims import HOLE_RADIUS"),
            {"lib": "lib/__init__.py", "lib.dims": "lib/dims.py"},
        )

    def test_from_import_may_name_a_submodule(self) -> None:
        self.assertEqual(
            self.modules("from lib import dims"),
            {"lib": "lib/__init__.py", "lib.dims": "lib/dims.py"},
        )

    def test_local_modules_are_followed_through_relative_imports(self) -> None:
        self.write("lib/shapes/__init__.py", "from .rounds import disc\n")
        self.write("lib/shapes/rounds.py", "from ..dims import HOLE_RADIUS\nfrom . import missing\n")
        self.assertEqual(
            self.modules("import lib.shapes"),
            {
                "lib": "lib/__init__.py",
                "lib.shapes": "lib/shapes/__init__.py",
                "lib.shapes.rounds": "lib/shapes/rounds.py",
                "lib.dims": "lib/dims.py",
            },
        )

    def test_broken_modules_count_without_their_imports(self) -> None:
        self.write("lib/broken.py", "def (:\nimport lib.dims\n")
        self.assertEqual(
            self.modules("import lib.broken"),
            {"lib": "lib/__init__.py", "lib.broken": "lib/broken.py"},
        )

    def test_the_notebook_and_marimos_output_do_not_count(self) -> None:
        self.write("__marimo__/stale.py", "")
        self.assertEqual(self.modules("import nb", "import __marimo__.stale"), {})


class TestRefreshLocalModules(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(self.forget, "lib")
        self.forget("lib")

    @staticmethod
    def forget(package: str) -> None:
        for name in [item for item in sys.modules if item == package or item.startswith(package + ".")]:
            del sys.modules[name]

    def refresh_and_import(self) -> ModuleType:
        refresh_local_modules(
            {"lib": self.root / "lib" / "__init__.py", "lib.dims": self.root / "lib" / "dims.py"}
        )
        sys.path.insert(0, str(self.root))
        try:
            return importlib.import_module("lib.dims")
        finally:
            sys.path.remove(str(self.root))

    def test_an_unchanged_module_is_kept_and_a_changed_one_reloaded(self) -> None:
        first = self.refresh_and_import()
        self.assertIs(self.refresh_and_import(), first)
        self.write("lib/dims.py", "HOLE_RADIUS = 4.0\n")
        changed = self.refresh_and_import()
        self.assertIsNot(changed, first)
        self.assertEqual(getattr(changed, "HOLE_RADIUS"), 4.0)

    def test_a_same_named_module_of_another_project_is_replaced(self) -> None:
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        (Path(other.name) / "lib").mkdir()
        (Path(other.name) / "lib" / "__init__.py").write_text("")
        (Path(other.name) / "lib" / "dims.py").write_text("HOLE_RADIUS = 9.0\n")
        sys.path.insert(0, other.name)
        try:
            importlib.import_module("lib.dims")
        finally:
            sys.path.remove(other.name)
        self.assertEqual(getattr(self.refresh_and_import(), "HOLE_RADIUS"), 3.0)

    def test_standard_library_modules_are_never_dropped(self) -> None:
        import json as loaded

        refresh_local_modules({"json": self.write("json.py", "")})
        self.assertIs(sys.modules["json"], loaded)


# ---------------------------------------------------------------------------
# Running notebooks
# ---------------------------------------------------------------------------


class TestRunNotebook(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.bracket = self.write("bracket.py", BRACKET)

    def test_second_run_restores_every_cell_but_setup(self) -> None:
        first = run_notebook(self.bracket)
        second = run_notebook(self.bracket)
        self.assertEqual(self.statuses(first), ["ran", "ran", "ran", "ran"])
        self.assertEqual(self.statuses(second), ["ran", "cached", "cached", "cached"])
        self.assertEqual(first.cells[0].name, "setup")
        self.assertEqual(first.definition.definition_id, "bracket")
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)
        self.assertEqual(
            {path.name for path in first.dependencies}, {"__init__.py", "dims.py"}
        )

    def test_without_the_cache_nothing_is_stored(self) -> None:
        run = run_notebook(self.bracket, cache=False)
        self.assertEqual(self.statuses(run), ["ran", "ran", "ran", "ran"])
        self.assertFalse((state_dir(run.config) / "cache").exists())
        self.assertEqual(self.statuses(run_notebook(self.bracket)), ["ran"] * 4)

    def test_overrides_skip_the_defining_cell(self) -> None:
        plain = run_notebook(self.bracket)
        wide = run_notebook(self.bracket, overrides={"width": 30.0})
        self.assertEqual(self.statuses(wide), ["ran", "skipped", "ran", "ran"])
        self.assertEqual(wide.values["width"], 30.0)
        self.assertNotEqual(plain.definition.content_hash, wide.definition.content_hash)
        again = run_notebook(self.bracket, overrides={"width": 30.0})
        self.assertEqual(self.statuses(again), ["ran", "skipped", "cached", "cached"])

    def test_overrides_must_name_a_cell_variable(self) -> None:
        with self.assertRaisesRegex(ValueError, "no cell defines depth"):
            run_notebook(self.bracket, overrides={"depth": 1.0})
        with self.assertRaisesRegex(ValueError, "setup cell's variables"):
            run_notebook(self.bracket, overrides={"scad": None})
        # An overridden cell does not run: it cannot supply its other variables.
        with self.assertRaisesRegex(ValueError, "defining body also defines HOLE_RADIUS, block, hole"):
            run_notebook(self.bracket, overrides={"body": None})

    def test_a_changed_local_module_invalidates_the_cache(self) -> None:
        first = run_notebook(self.bracket)
        self.write("lib/dims.py", "HOLE_RADIUS = 2.0\n")
        changed = run_notebook(self.bracket)
        self.assertEqual(self.statuses(changed), ["ran"] * 4)
        self.assertNotEqual(first.definition.content_hash, changed.definition.content_hash)
        self.assertEqual(self.statuses(run_notebook(self.bracket))[1:], ["cached"] * 3)
        # Only the cache for the current dependencies is kept.
        self.assertEqual(len(list((state_dir(first.config) / "cache").iterdir())), 1)

    def test_sources_are_positions_in_the_notebook_file(self) -> None:
        lines = BRACKET.splitlines()
        expected = next(
            number for number, line in enumerate(lines, start=1) if "scad.cut_rsolid" in line
        )
        for run in (run_notebook(self.bracket), run_notebook(self.bracket)):
            cuts = [
                node["source"]
                for node in self.graph_nodes(run)
                if "cut_rsolid" in str(node.get("source", {}).get("call_text", ""))
            ]
            self.assertEqual(len(cuts), 1)
            self.assertEqual(cuts[0]["line"], expected)
            self.assertEqual(cuts[0]["column"], lines[expected - 1].index("scad.cut_rsolid"))
            self.assertNotIn("cell", cuts[0])

    def test_dead_nodes_stay_out_of_the_definition(self) -> None:
        path = self.write(
            "preview.py",
            notebook_text(
                cell(
                    """
                    body = scad.make_box_rsolid(4.0, 4.0, 4.0)
                    preview = scad.make_sphere_rsolid(9.0)
                    """,
                    returns="body, preview",
                ),
                cell('preview_part = scad.Part(part_id="preview", body=body)', reads="body", returns="preview_part"),
            ),
        )
        operations = {node["op"] for node in self.graph_nodes(run_notebook(path))}
        self.assertFalse(any("sphere" in str(operation) for operation in operations))

    def test_a_later_cell_tags_a_shape_from_an_earlier_one(self) -> None:
        path = self.write(
            "tagged.py",
            notebook_text(
                cell("body = scad.make_box_rsolid(4.0, 4.0, 4.0)", returns="body"),
                cell(
                    """
                    _tagged = scad.apply_tag(shape=body, tag="role.block")
                    block = scad.Part(part_id="tagged", body=_tagged)
                    """,
                    reads="body",
                    returns="block",
                ),
            ),
        )
        for run in (run_notebook(path), run_notebook(path)):
            self.assertIn("apply_tag_rselection", {node["op"] for node in self.graph_nodes(run)})


class TestProduct(NotebookTestCase):
    def test_no_product_lists_what_was_found(self) -> None:
        path = self.write(
            "orphan.py",
            notebook_text(cell('other = scad.Part(part_id="other", body=scad.make_box_rsolid(1.0, 1.0, 1.0))', returns="other")),
        )
        with self.assertRaisesRegex(ProductNotFoundError, r"other \(id 'other'\)"):
            run_notebook(path)

    def test_two_products_are_ambiguous(self) -> None:
        make = 'scad.Part(part_id="twin", body=scad.make_box_rsolid(1.0, 1.0, 1.0))'
        path = self.write(
            "twin.py",
            notebook_text(cell(f"a = {make}", returns="a"), cell(f"b = {make}", returns="b")),
        )
        with self.assertRaisesRegex(ProductNotFoundError, "a, b"):
            run_notebook(path)

    def test_an_assembly_built_over_several_cells_is_the_last_one(self) -> None:
        self.write(
            "block.py",
            notebook_text(cell('block = scad.make_part_rpart(part_id="block", body=scad.make_box_rsolid(1.0, 1.0, 1.0))', returns="block")),
        )
        path = self.write(
            "rig.py",
            notebook_text(
                cell(
                    """
                    block = scad.use("block.py")
                    started = scad.make_assembly_rassembly(assembly_id="rig")
                    """,
                    returns="block, started",
                ),
                cell(
                    """
                    rig = scad.add_component_rassembly(
                        assembly=started, item=block, component_id="block",
                        placement=scad.identity_placement_rplacement(),
                    )
                    """,
                    reads="block, started",
                    returns="rig",
                ),
            ),
        )
        rig = run_notebook(path).product
        assert isinstance(rig, Assembly)
        self.assertEqual([c.component_id for c in rig.components], ["block"])

    def test_one_value_under_two_names_is_one_product(self) -> None:
        path = self.write(
            "alias.py",
            notebook_text(
                cell('alias = scad.Part(part_id="alias", body=scad.make_box_rsolid(1.0, 1.0, 1.0))', returns="alias"),
                cell("same = alias", reads="alias", returns="same"),
            ),
        )
        self.assertEqual(run_notebook(path).definition.definition_id, "alias")


class TestTolerance(NotebookTestCase):
    def test_a_bound_requirement_survives_a_cache_hit(self) -> None:
        path = self.write(
            "toleranced.py",
            notebook_text(
                cell(
                    """
                    width = scad.var("width", 10.0, tolerance=0.05)
                    req = scad.get_active_session().require_tolerance(width, 0.1, name="width_fit")
                    body = scad.make_box_rsolid(width, 5.0, 5.0)
                    """,
                    returns="body, req, width",
                ),
                cell('toleranced = scad.Part(part_id="toleranced", body=body)', reads="body", returns="toleranced"),
            ),
        )

        def requirement_names(run: NotebookRun) -> list[str]:
            definition = run.definition
            artifact = load_feature_graph_artifact(definition.blobs[definition.feature_graph_ref.path])
            return [item["name"] for item in artifact.tolerance_graph["requirements"]]

        cold = run_notebook(path)
        warm = run_notebook(path)
        self.assertEqual(self.statuses(warm)[1:], ["cached", "cached"])
        self.assertEqual(requirement_names(cold), ["width_fit"])
        self.assertEqual(requirement_names(warm), ["width_fit"])
        self.assertEqual(cold.definition.content_hash, warm.definition.content_hash)

    def test_an_unbound_requirement_fails_the_cell(self) -> None:
        path = self.write(
            "loose.py",
            notebook_text(
                cell(
                    """
                    width = scad.var("width", 10.0, tolerance=0.05)
                    scad.get_active_session().require_tolerance(width, 0.1, name="lost")
                    """,
                    returns="width",
                ),
            ),
        )
        with self.assertRaisesRegex(UnboundRequirementError, "lost"):
            run_notebook(path)


class TestUnpicklableValues(NotebookTestCase):
    def test_a_value_the_cache_cannot_hold_reruns_the_notebook(self) -> None:
        path = self.write(
            "locked.py",
            notebook_text(
                cell("import threading\nlock = threading.Lock()", returns="lock, threading"),
                cell(
                    'locked = scad.Part(part_id="locked", body=scad.make_box_rsolid(2.0, 2.0, 2.0))',
                    reads="lock",
                    returns="locked",
                ),
            ),
        )
        first = run_notebook(path)
        second = run_notebook(path)
        self.assertEqual(self.statuses(second), ["ran", "ran", "ran"])
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)


class TestUse(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.bracket = self.write("bracket.py", BRACKET)
        self.rig = self.write("rig.py", RIG)

    def test_a_child_product_is_an_assembly_component(self) -> None:
        first = run_notebook(self.rig)
        second = run_notebook(self.rig)
        self.assertEqual(first.definition.definition_kind, "assembly")
        self.assertEqual(self.statuses(second)[1:], ["cached"] * 3)
        self.assertEqual(first.definition.content_hash, second.definition.content_hash)
        self.assertEqual(
            {path.name for path in first.dependencies},
            {"bracket.py", "__init__.py", "dims.py"},
        )
        references = [node["node_id"] for node in self.graph_nodes(first) if str(node["node_id"]).startswith("ref_")]
        self.assertTrue(references)
        self.assertTrue(all(re.fullmatch(r"ref_[0-9a-f]{16}", item) for item in references))

    def test_nested_and_standalone_runs_share_the_childs_cache(self) -> None:
        run_notebook(self.rig)
        standalone = run_notebook(self.bracket, overrides={"width": 24.0})
        self.assertEqual(self.statuses(standalone), ["ran", "skipped", "cached", "cached"])

    def test_a_changed_child_invalidates_the_parent(self) -> None:
        first = run_notebook(self.rig)
        self.write("bracket.py", BRACKET.replace("10.0, 5.0)", "12.0, 5.0)"))
        changed = run_notebook(self.rig)
        self.assertEqual(self.statuses(changed), ["ran"] * 4)
        self.assertNotEqual(first.definition.content_hash, changed.definition.content_hash)


LINK = notebook_text(
    cell("length = 40.0", returns="length"),
    cell("bar = scad.make_box_rsolid(length, 6.0, 3.0)", reads="length", returns="bar"),
    cell("link = scad.Part(part_id=scad.notebook_id(), body=bar)", reads="bar", returns="link"),
    table='id = "link"',
)

LINKAGE = notebook_text(
    cell('crank = scad.use("link.py", id="crank", length=20.0)', returns="crank"),
    cell('rocker = scad.use("link.py", id="rocker", length=50.0)', returns="rocker"),
    cell(
        """
        linkage = scad.make_assembly_rassembly(assembly_id="linkage", name="Linkage")
        linkage = scad.add_component_rassembly(
            assembly=linkage, item=crank, component_id="crank",
            placement=scad.identity_placement_rplacement(),
        )
        linkage = scad.add_component_rassembly(
            assembly=linkage, item=rocker, component_id="rocker",
            placement=scad.make_placement_rplacement(origin=(0.0, 20.0, 0.0)),
        )
        """,
        reads="crank, rocker",
        returns="linkage",
    ),
    table='id = "linkage"',
)


class TestPartFamily(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.link = self.write("link.py", LINK)

    def test_the_header_id_is_the_default(self) -> None:
        run = run_notebook(self.link)
        self.assertEqual(run.definition.definition_id, "link")

    def test_each_id_is_a_member_with_its_own_definition(self) -> None:
        definition = run_notebook(self.write("linkage.py", LINKAGE)).definition
        assert isinstance(definition, AssemblyDefinition)
        references = {ref.definition_id: ref for ref in definition.definition_refs}
        self.assertEqual(set(references), {"crank", "rocker"})
        self.assertNotEqual(references["crank"].content_hash, references["rocker"].content_hash)

    def test_each_id_keeps_a_cache_of_its_own(self) -> None:
        run_notebook(self.link, id="crank")
        rocker = run_notebook(self.link, id="rocker")
        self.assertEqual(self.statuses(rocker), ["ran"] * 4)
        self.assertEqual(rocker.definition.definition_id, "rocker")
        again = run_notebook(self.link, id="crank")
        self.assertEqual(self.statuses(again)[1:], ["cached"] * 3)
        self.assertEqual(again.definition.definition_id, "crank")

    def test_an_invalid_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_notebook(self.link, id="not an id")

    def test_notebook_id_needs_a_running_cell(self) -> None:
        with self.assertRaises(RuntimeError):
            notebook_id()

    def test_sca_run_takes_the_id(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(["run", str(self.link), "--id", "coupler"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["definition_id"], "coupler")


# ---------------------------------------------------------------------------
# Supporting pieces
# ---------------------------------------------------------------------------


class TestMappingProxyPickle(unittest.TestCase):
    def test_mapping_proxies_pickle_and_copy(self) -> None:
        import simplecadapi  # noqa: F401  (installs the reducer)

        proxy = MappingProxyType({"a": 1, "b": [2]})
        for restored in (pickle.loads(pickle.dumps(proxy)), copy.deepcopy(proxy)):
            self.assertIsInstance(restored, MappingProxyType)
            self.assertEqual(dict(restored), {"a": 1, "b": [2]})


class TestExecutorEntryPoint(unittest.TestCase):
    def test_marimo_finds_the_executor(self) -> None:
        points = importlib.metadata.entry_points(group="marimo.cell.executor")
        (point,) = [item for item in points if item.name == "simplecadapi"]
        self.assertIsInstance(point.load()(), SimpleCadExecutor)


class TestScaRun(NotebookTestCase):
    def test_overrides_parse_as_literals_or_strings(self) -> None:
        self.assertEqual(
            parse_overrides(["width=22", "name=plate", "size=(1, 2)", "label='x=y'"]),
            {"width": 22, "name": "plate", "size": (1, 2), "label": "x=y"},
        )
        for bad in (["width"], ["2x=1"], ["a=1", "a=2"]):
            with self.assertRaises(ValueError):
                parse_overrides(bad)

    def test_run_reports_and_writes_the_package(self) -> None:
        path = self.write("bracket.py", BRACKET)
        package = self.root / "out" / "bracket.scadpkg"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(["run", str(path), "--set", "width=22", "--out", str(package)])
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["definition_id"], "bracket")
        self.assertEqual([item["status"] for item in report["cells"]], ["ran", "skipped", "ran", "ran"])
        self.assertEqual(load_product_package(package).content_hash, report["content_hash"])

    def test_errors_are_reported_not_raised(self) -> None:
        path = self.write("bracket.py", BRACKET)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = cli.main(["run", str(path), "--set", "depth=1"])
        self.assertEqual(code, 2)
        self.assertIn("no cell defines depth", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
