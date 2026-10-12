"""The editor's server-side logic and templates (no kernel is started).

An end-to-end run against a real marimo kernel is opt-in:
``SCA_EDITOR_E2E=1 pytest test/test_editor.py``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("starlette")

from simplecadapi.editor.server import WorkspaceState, _is_function_cell, _module_code, pick_notebook
from simplecadapi.editor.templates import create_notebook, render_notebook
from simplecadapi.runtime import run_notebook
from simplecadapi.runtime.params import ParamSpec, parameters_in_cell


def specs_of(code: str) -> dict[str, ParamSpec]:
    return {spec.name: spec for spec in parameters_in_cell(code)}


class TemplatesTest(unittest.TestCase):
    def test_new_part_runs_and_offers_sliders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = create_notebook(Path(tmp), "bracket", "part")
            run = run_notebook(path)
            self.assertEqual(run.definition.definition_kind, "single_solid")
            self.assertEqual(run.definition.definition_id, "bracket")
            from simplecadapi.runtime.params import list_parameters

            controls = {spec.name: spec.control for spec in list_parameters(path)}
            self.assertEqual(controls, {"RADIUS": "slider", "HEIGHT": "slider"})

    def test_new_assembly_uses_the_workspace_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "create a part first"):
                create_notebook(root, "unit", "assembly")
            create_notebook(root, "bracket", "part")
            create_notebook(root, "pin-a", "part")
            path = create_notebook(root, "unit", "assembly")
            run = run_notebook(path)
            self.assertEqual(run.definition.definition_kind, "assembly")
            self.assertEqual(run.definition.definition_id, "unit")

    def test_names_and_kinds_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("", "1abc", "a b", "../x"):
                with self.assertRaises(ValueError):
                    create_notebook(Path(tmp), bad)
            with self.assertRaises(ValueError):
                render_notebook("x", "gadget")
            create_notebook(Path(tmp), "once")
            with self.assertRaises(FileExistsError):
                create_notebook(Path(tmp), "once")


class PickNotebookTest(unittest.TestCase):
    def test_prefers_the_asked_one_then_the_top_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(pick_notebook(root))
            create_notebook(root, "a-part", "part")
            create_notebook(root, "b-part", "part")
            self.assertEqual(pick_notebook(root), (root / "a-part.py").resolve())
            create_notebook(root, "top", "assembly")
            self.assertEqual(pick_notebook(root), (root / "top.py").resolve())
            self.assertEqual(pick_notebook(root, root / "b-part.py"), (root / "b-part.py").resolve())


class ParamCleaningTest(unittest.TestCase):
    def state(self) -> WorkspaceState:
        state = WorkspaceState(Path(tempfile.gettempdir()))
        state.specs = specs_of(
            "# ---- params ----\n"
            "W = 20.0  # ui: slider(10, 40)\n"
            "N = 4  # ui: slider(2, 8)\n"
            "F = False\n"
        )
        return state

    def test_values_are_clamped_and_typed(self) -> None:
        clean = self.state()._clean_params({"W": 99, "N": 3.6, "F": 1, "NOPE": 1})
        self.assertEqual(clean, {"W": 40.0, "N": 4, "F": True})
        self.assertIsInstance(clean["N"], int)

    def test_wrong_kinds_are_dropped(self) -> None:
        self.assertEqual(self.state()._clean_params({"W": "7", "F": "yes"}), {})
        self.assertEqual(self.state()._clean_params({"N": True}), {})


class ModuleCodeTest(unittest.TestCase):
    def test_top_level_return_is_stripped_for_code_mode(self) -> None:
        code = "x = 1\nif x:\n    return\nreturn (x,)"
        self.assertEqual(_module_code(code), "x = 1\nif x:\n    pass\n(x,)")

    def test_returns_inside_functions_and_classes_are_code(self) -> None:
        code = (
            "def f(x):\n    if x:\n        return 1\n    return\n"
            "class C:\n    def g(self):\n        return self\n"
            "g = lambda: 1\n"
        )
        self.assertEqual(_module_code(code), code.rstrip("\n"))

    def test_only_the_cells_own_return_goes_and_comments_stay(self) -> None:
        code = "def f():\n    return 2  # keep\ny = f()  # call\nreturn (y,)  # export"
        self.assertEqual(
            _module_code(code),
            "def f():\n    return 2  # keep\ny = f()  # call\n(y,)  # export",
        )


class FunctionCellTest(unittest.TestCase):
    def test_a_function_cell_is_one_def_or_class(self) -> None:
        self.assertTrue(_is_function_cell("def f(x):\n    return x"))
        self.assertTrue(_is_function_cell("class C:\n    pass"))
        self.assertFalse(_is_function_cell("def f():\n    pass\nf()"))
        self.assertFalse(_is_function_cell("x = 1"))
        self.assertFalse(_is_function_cell("def broken("))

    def test_editing_one_is_refused_and_unchanged_code_is_not(self) -> None:
        state = WorkspaceState(Path(tempfile.gettempdir()))
        state.kernel = type("K", (), {"run_cells": lambda self, ids: {}, "wait_idle": lambda self: True})()  # type: ignore[assignment]
        state.cells = [{"id": "f1", "code": "def f():\n    return 1"}]
        state.schedule_settle = lambda: None  # type: ignore[method-assign]
        refused = state.dispatch_command({"type": "code.edit", "cell": "f1", "code": "def f():\n    return 2"})
        self.assertEqual(refused["type"], "error")
        self.assertIn("@app.function", refused["message"])
        accepted = state.dispatch_command({"type": "code.edit", "cell": "f1", "code": "def f():\n    return 1"})
        self.assertEqual(accepted["type"], "ack")


@unittest.skipUnless(os.environ.get("SCA_EDITOR_E2E"), "set SCA_EDITOR_E2E=1 to boot a marimo kernel")
class EditorEndToEndTest(unittest.TestCase):
    def test_slider_rebuilds_the_part_and_commit_writes_the_source(self) -> None:
        import threading

        import uvicorn

        from simplecadapi.editor.server import create_app
        from simplecadapi.runtime.params import read_saved_params

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = create_notebook(root, "bracket", "part")
            state = WorkspaceState(root)
            state.port = 17731
            app = create_app(state)
            server = uvicorn.Server(uvicorn.Config(app, port=state.port, log_level="error"))
            threading.Thread(target=server.run, daemon=True).start()
            state.hub.attach_loop(__import__("asyncio").new_event_loop())
            try:
                state.start_kernel(path)
                self.assertIn("RADIUS", state.specs)
                first = state.latest_preview_bytes
                self.assertTrue(first)
                state.dispatch_command({"type": "param.set", "values": {"RADIUS": 40}})
                deadline = time.monotonic() + 90
                while state.latest_preview_bytes == first and time.monotonic() < deadline:
                    time.sleep(0.5)
                self.assertNotEqual(state.latest_preview_bytes, first)
                self.assertEqual(read_saved_params(state.config), {"RADIUS": 40.0})
                state.dispatch_command({"type": "param.commit", "names": ["RADIUS"]})
                deadline = time.monotonic() + 60
                while "40.0" not in path.read_text() and time.monotonic() < deadline:
                    time.sleep(0.5)
                self.assertIn('scad.var("radius", 40.0', path.read_text())
                self.assertEqual(read_saved_params(state.config), {})
                with urllib.request.urlopen(f"http://127.0.0.1:{state.port}/api/health") as response:
                    self.assertTrue(json.load(response)["kernel"])
            finally:
                if state.kernel is not None:
                    state.kernel.stop()
                server.should_exit = True


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Selection as notebook code, the step titles, the agent snapshot
# ---------------------------------------------------------------------------

from simplecadapi.editor.selection import (
    MARKER,
    selection_cell_code,
    selector_expression,
    variable_names,
)
from simplecadapi.editor.server import cell_title

FACE = {"centroid": [1.0, 2.0, 3.0], "area": 100.0}
EDGE = {"centroid": [0.0, 0.0, 5.0], "length": 12.5}


class SelectionCodeTest(unittest.TestCase):
    def test_a_face_is_selected_by_type_place_and_size(self) -> None:
        expression = selector_expression("face", FACE, {"type": "plane"})
        assert expression is not None
        self.assertTrue(expression.startswith("scad.ql.faces().where(scad.ql.and_("))
        self.assertTrue(expression.endswith(".exactly(1)"))
        for part in ('"geom.type", "==", "PLANE"', '"geom.center.x", ">=", 0.9', '"geom.area", "<=", 101'):
            self.assertIn(part, expression)

    def test_a_solid_is_selected_by_volume_only(self) -> None:
        expression = selector_expression("solid", {"centroid": [1, 2, 3], "volume": 50.0}, {"type": "brep_solid"})
        assert expression is not None
        self.assertIn("geom.volume", expression)
        self.assertNotIn("geom.center", expression)

    def test_nothing_to_select_by_gives_none(self) -> None:
        self.assertIsNone(selector_expression("face", {}, {}))
        self.assertIsNone(selector_expression("gadget", FACE, {}))

    def test_one_item_per_kind_is_named_by_its_kind(self) -> None:
        code = selection_cell_code([{"kind": "face", "properties": FACE, "geometry": {"type": "plane"}}])
        self.assertTrue(code.startswith(MARKER))
        self.assertIn("selected_face = scad.ql.faces()", code)
        self.assertTrue(code.endswith("selected_item = [selected_face]"))
        compile(code, "<selection>", "exec")

    def test_several_items_are_numbered_per_kind_and_listed(self) -> None:
        items = [
            {"kind": "edge", "properties": EDGE, "geometry": {"type": "line"}},
            {"kind": "face", "properties": FACE, "geometry": {"type": "plane"}},
            {"kind": "edge", "properties": EDGE, "geometry": {"type": "circle"}},
        ]
        self.assertEqual(variable_names(items), ["selected_edge_1", "selected_face", "selected_edge_2"])
        code = selection_cell_code(items)
        self.assertTrue(code.endswith("selected_item = [selected_edge_1, selected_face, selected_edge_2]"))
        compile(code, "<selection>", "exec")

    def test_an_empty_selection_is_an_empty_list(self) -> None:
        self.assertEqual(selection_cell_code([]), f"{MARKER}\nselected_item = []")

    def test_a_component_is_its_node_id(self) -> None:
        code = selection_cell_code([{"kind": "component", "node_id": "node/asm/shell"}])
        self.assertIn("selected_component = 'node/asm/shell'", code)

    def test_the_generated_selectors_find_the_picked_entities(self) -> None:
        import simplecadapi as scad

        body = scad.make_box_rsolid(10.0, 20.0, 30.0)
        for kind, entity in (
            ("solid", {"properties": {"volume": body.get_volume()}, "geometry": {"type": "brep_solid"}}),
            ("face", {"properties": {"centroid": [0.0, 0.0, 0.0], "area": 200.0}, "geometry": {"type": "plane"}}),
            ("vertex", {"properties": {"position": [-5.0, -10.0, 0.0]}, "geometry": {"type": "point"}}),
        ):
            expression = selector_expression(kind, entity["properties"], entity["geometry"])
            assert expression is not None
            found = eval(expression, {"scad": scad}).resolve(body)  # noqa: S307
            self.assertEqual(len(found), 1, kind)


class CellTitleTest(unittest.TestCase):
    def test_the_name_comes_from_the_most_specific_source(self) -> None:
        self.assertEqual(cell_title("x = 1", "base-plate"), "base-plate")
        self.assertEqual(cell_title(f"{MARKER}\nselected_item = []", None), "selection")
        self.assertEqual(cell_title("# ---- params ----\nA = 1", None), "params")
        self.assertEqual(cell_title("# ---- params: disc ----\nA = 1", None), "params: disc")
        self.assertEqual(cell_title("_t = 1\nbody = _t", None), "body")
        self.assertEqual(cell_title("def mount(x):\n    return x", None), "mount")
        self.assertEqual(cell_title("# only a comment", None), "only a comment")
        self.assertEqual(cell_title("print(1)", None), "cell")


class SnapshotTest(unittest.TestCase):
    def test_the_snapshot_is_written_and_read_back_by_the_cli(self) -> None:
        from simplecadapi import cli as sca_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = WorkspaceState(root)
            state.cells = [{"id": "a", "code": "x = 1", "title": "x", "status": "idle", "errors": []}]
            state.selection_items = [{"kind": "face", "entity_id": "e/1", "node_id": "n/1", "definition_id": "d"}]
            state.write_snapshot()
            data = json.loads((root / ".sca-editor" / "snapshot.json").read_text())
            self.assertEqual(data["selection"]["items"][0]["variable"], "selected_face")
            self.assertEqual(data["cells"][0]["title"], "x")
            report, code, _printer = sca_cli.run(["snapshot", str(root)])
            self.assertEqual((code, report["selection"]["items"][0]["entity_id"]), (0, "e/1"))
            png = b"\x89PNG\r\n\x1a\nrest"
            state.save_viewport(png)
            self.assertEqual((root / ".sca-editor" / "viewport.png").read_bytes(), png)
            self.assertTrue(state.snapshot()["viewport_png"].endswith("viewport.png"))
            with self.assertRaises(ValueError):
                sca_cli.run(["snapshot", str(root / "nowhere")])


class RunAboveTest(unittest.TestCase):
    def test_run_above_runs_the_cells_before_this_one_in_order(self) -> None:
        ran: list[list[str]] = []
        state = WorkspaceState(Path(tempfile.gettempdir()))
        state.kernel = type(  # type: ignore[assignment]
            "K", (), {"run_cells": lambda self, ids: ran.append(list(ids)) or {}, "wait_idle": lambda self: True}
        )()
        state.cells = [{"id": name, "code": ""} for name in ("a", "b", "c")]
        state.schedule_settle = lambda: None  # type: ignore[method-assign]
        for _ in range(2):
            state.dispatch_command({"type": "rerun.request", "cell": "c", "above": True})
        state.dispatch_command({"type": "rerun.request", "cell": "a", "above": True})
        deadline = time.monotonic() + 3
        while len(ran) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(ran[:2], [["a", "b"], ["a", "b"]])
        self.assertEqual(len(ran), 2)  # nothing is above the first cell


class CellLinesTest(unittest.TestCase):
    NOTEBOOK = (
        "import marimo\n\napp = marimo.App()\n\nwith app.setup:\n    import simplecadapi as scad\n\n\n"
        "@app.cell\ndef _():\n    a = 1\n    b = 2\n    return a, b\n\n\n"
        "@app.cell\ndef _(a):\n    c = a\n    return (c,)\n"
    )

    def test_cells_are_located_in_the_file_by_order(self) -> None:
        from simplecadapi.editor.server import file_line_ranges

        lines = self.NOTEBOOK.splitlines()
        ranges = file_line_ranges(self.NOTEBOOK, ["a = 1\nb = 2", "c = a"])
        self.assertEqual(lines[ranges[0][0] - 1].strip(), "a = 1")
        self.assertEqual(lines[ranges[0][1] - 1].strip(), "b = 2")
        self.assertEqual(lines[ranges[1][0] - 1].strip(), "c = a")

    def test_an_unsaved_cell_has_no_location(self) -> None:
        from simplecadapi.editor.server import file_line_ranges

        self.assertEqual(file_line_ranges(self.NOTEBOOK, ["a = 1\nb = 2", "c = 99"])[1], None)
        self.assertEqual(file_line_ranges("def broken(", ["x"]), [None])


class ModulesTest(unittest.TestCase):
    def _workspace(self, root: Path) -> None:
        (root / "dims.py").write_text(
            "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass D:\n    L: float = 80.0\n\nDIMS = D()\n"
        )
        (root / "helper.py").write_text("def helper():\n    return 1\n")
        notebook = create_notebook(root, "part", "part")
        notebook.write_text(
            notebook.read_text().replace(
                "with app.setup:\n    import simplecadapi as scad\n",
                "with app.setup:\n    import simplecadapi as scad\n    from dims import DIMS\n    from helper import helper\n",
            )
        )

    def test_the_workspace_lists_the_modules_notebooks_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._workspace(root)
            state = WorkspaceState(root)
            modules = {m["path"]: m for m in state.modules()}
            self.assertEqual(sorted(modules), ["dims.py", "helper.py"])
            self.assertEqual(modules["dims.py"]["used_by"], ["part.py"])

    def test_a_module_opens_with_its_dataclass_fields_as_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._workspace(root)
            state = WorkspaceState(root)
            seen: list[dict] = []
            state.emit = seen.append  # type: ignore[method-assign]
            state.open_module("dims.py")
            envelope = seen[-1]
            self.assertEqual((envelope["type"], envelope["origin"], envelope["used_by"]), ("module", "open", ["part.py"]))
            self.assertEqual([p["id"] for p in envelope["params"]], ["D.L"])
            with self.assertRaises(ValueError):
                state.open_module("../outside.py")

    def test_a_parameter_edit_is_written_to_the_module_and_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._workspace(root)
            state = WorkspaceState(root)
            state.emit = lambda envelope: None  # type: ignore[method-assign]
            changed: list[set[Path]] = []
            state._files_changed = lambda paths, announce=True: changed.append(paths)  # type: ignore[method-assign]
            state.open_module("dims.py")
            state.set_module_params("dims.py", {"D.L": 120})
            self.assertIn("L: float = 120.0", (root / "dims.py").read_text())
            self.assertEqual(changed, [{(root / "dims.py").resolve()}])
            state.save_module("dims.py", "X = 1\n")
            self.assertEqual((root / "dims.py").read_text(), "X = 1\n")
            self.assertEqual(len(changed), 2)


class SelectionLatencyTest(unittest.TestCase):
    """A pick shows up at once and the kernel only ever writes the newest selection."""

    def test_the_cell_is_pushed_before_the_kernel_writes_and_writes_coalesce(self) -> None:
        import threading

        from simplecadapi.editor.server import PENDING_SELECTION_ID

        gate = threading.Event()
        written: list[str] = []

        class Kernel:
            def put_cell(self, code: str, *, cell_id: str | None, run: bool = True) -> str:
                gate.wait(5)  # the kernel is busy with something long
                written.append(code)
                return cell_id or "real"

            def wait_idle(self, timeout: float = 0) -> bool:
                return True

        state = WorkspaceState(Path(tempfile.gettempdir()))
        kernel = Kernel()
        state.kernel = kernel  # type: ignore[assignment]
        sent: list[dict] = []
        state.emit = sent.append  # type: ignore[method-assign]
        state.push_cells = lambda: None  # type: ignore[method-assign]
        state.write_snapshot = lambda: None  # type: ignore[method-assign]
        face = {"kind": "face", "properties": FACE, "geometry": {"type": "plane"}}
        worker = threading.Thread(target=state._set_selection, args=(kernel, [face]))
        worker.start()
        deadline = time.monotonic() + 3
        while not any(m["type"] == "notebook.cells" for m in sent) and time.monotonic() < deadline:
            time.sleep(0.01)
        cells = next(m for m in sent if m["type"] == "notebook.cells")["cells"]
        self.assertEqual(cells[-1]["id"], PENDING_SELECTION_ID)  # shown while the kernel is still busy
        self.assertEqual(written, [])
        # two more picks while the first write is stuck: only the newest is written afterwards
        edge = {"kind": "edge", "properties": EDGE, "geometry": {"type": "line"}}
        state._set_selection(kernel, [face, edge])
        state._set_selection(kernel, [edge])
        gate.set()
        worker.join(5)
        self.assertEqual(len(written), 2)  # the first, then the newest
        self.assertIn("selected_edge = ", written[-1])
        self.assertNotIn("selected_face", written[-1])


@unittest.skipUnless(os.environ.get("SCA_EDITOR_E2E"), "set SCA_EDITOR_E2E=1 to boot a marimo kernel")
class KernelCacheTest(unittest.TestCase):
    """The editor kernel shares the cell cache: a changed module recomputes only what reads it."""

    NOTEBOOK = (
        "# /// script\n# [tool.simplecadapi]\n# id = \"two\"\n# ///\n"
        "import marimo\n\napp = marimo.App()\n\nwith app.setup:\n    import simplecadapi as scad\n\n\n"
        "@app.cell\ndef _():\n    from lib.alpha import A\n"
        "    open('/tmp/_sca_cache_log.txt', 'a').write('A')\n    return (A,)\n\n\n"
        "@app.cell\ndef _():\n    from lib.beta import B\n"
        "    open('/tmp/_sca_cache_log.txt', 'a').write('B')\n    return (B,)\n\n\n"
        "@app.cell\ndef _(A, B):\n    part = scad.Part(part_id='two', body=scad.make_box_rsolid(A, B, 1.0))\n"
        "    open('/tmp/_sca_cache_log.txt', 'a').write('P')\n    return (part,)\n"
    )

    def test_only_the_cells_that_read_a_changed_module_run_again(self) -> None:
        import threading

        import uvicorn

        from simplecadapi.editor.server import create_app

        log = Path("/tmp/_sca_cache_log.txt")
        log.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "lib").mkdir()
            (root / "lib" / "alpha.py").write_text("A = 10.0\n")
            (root / "lib" / "beta.py").write_text("B = 6.0\n")
            path = root / "two.py"
            path.write_text(self.NOTEBOOK)
            state = WorkspaceState(root)
            state.port = 17733
            app = create_app(state)
            server = uvicorn.Server(uvicorn.Config(app, port=state.port, log_level="error"))
            threading.Thread(target=server.run, daemon=True).start()
            state.hub.attach_loop(__import__("asyncio").new_event_loop())
            try:
                state.start_kernel(path)
                first = log.read_text()
                self.assertEqual(sorted(first), ["A", "B", "P"])  # everything ran once
                (root / "lib" / "alpha.py").write_text("A = 12.0\n")
                kernel = state.kernel
                assert kernel is not None
                kernel.reload_modules(["lib", "lib.alpha", "lib.beta"])
                kernel.wait_idle(120)
                again = log.read_text()[len(first):]
                # alpha changed: the cell that reads it and the part rerun; beta's cell is restored.
                self.assertEqual(sorted(again), ["A", "P"])
                # going back is restored for both
                (root / "lib" / "alpha.py").write_text("A = 10.0\n")
                before = log.read_text()
                kernel.reload_modules(["lib", "lib.alpha", "lib.beta"])
                kernel.wait_idle(120)
                self.assertEqual(log.read_text()[len(before):], "")
            finally:
                if state.kernel is not None:
                    state.kernel.stop()
                server.should_exit = True
                log.unlink(missing_ok=True)


class WatchedFilesTest(unittest.TestCase):
    """What the editor watches: modules, child notebooks, and the data files a header lists."""

    def test_input_files_of_the_notebook_and_its_children_are_watched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "data").mkdir()
            (root / "data" / "profile.dxf").write_text("0\nEOF\n")
            (root / "data" / "child.csv").write_text("1,2\n")
            header = '# /// script\n# [tool.simplecadapi]\n# id = "{id}"\n# inputs = ["{inputs}"]\n# ///\n'
            body = "import marimo\n\napp = marimo.App()\n\nwith app.setup:\n    import simplecadapi as scad\n"
            (root / "child.py").write_text(header.format(id="child", inputs="data/child.csv") + body)
            (root / "top.py").write_text(
                header.format(id="top", inputs="data/profile.dxf")
                + body
                + '\n\n@app.cell\ndef _():\n    c = scad.use("child.py")\n    return (c,)\n'
            )
            state = WorkspaceState(root, root / "top.py")
            mtimes, _own, inputs = state._watched_files()
            self.assertEqual(inputs, {root / "data" / "profile.dxf"})
            self.assertIn(root / "data" / "profile.dxf", mtimes)
            self.assertIn(root / "data" / "child.csv", mtimes)  # a child's data: its cells rerun
            self.assertIn(root / "child.py", mtimes)


@unittest.skipUnless(os.environ.get("SCA_EDITOR_E2E"), "set SCA_EDITOR_E2E=1 to boot a marimo kernel")
class LongCellTest(unittest.TestCase):
    """A cell that runs longer than the bridge's probes must not be interrupted by them."""

    def test_a_long_cell_survives_the_bridge_polling_the_kernel(self) -> None:
        import threading

        import uvicorn

        from simplecadapi.editor.server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "slow.py"
            path.write_text(
                "# /// script\n# [tool.simplecadapi]\n# id = \"slow\"\n# ///\n"
                "import marimo\n\napp = marimo.App()\n\nwith app.setup:\n    import simplecadapi as scad\n\n\n"
                "@app.cell\ndef _():\n    import time\n    time.sleep(22)\n    done = 1\n    return (done,)\n"
            )
            state = WorkspaceState(root)
            state.port = 17735
            app = create_app(state)
            server = uvicorn.Server(uvicorn.Config(app, port=state.port, log_level="error"))
            threading.Thread(target=server.run, daemon=True).start()
            state.hub.attach_loop(__import__("asyncio").new_event_loop())
            try:
                # start_kernel waits for the notebook to go idle with scratch probes while the
                # cell sleeps: they used to time out after 15 s and interrupt the cell.
                state.start_kernel(path)
                kernel = state.kernel
                assert kernel is not None
                self.assertTrue(kernel.session_exists())
                cell = next(c for c in kernel.list_cells() if "time.sleep" in c["code"])
                self.assertEqual(cell["status"], "idle")
                self.assertEqual(cell["errors"], [])
                self.assertIn("DONE 1", kernel.execute("print('DONE', done)").get("log", "").upper())
            finally:
                if state.kernel is not None:
                    state.kernel.stop()
                server.should_exit = True


class RestoreTest(unittest.TestCase):
    """Switching back to a notebook shows its last model at once, if nothing it depends on changed."""

    def _workspace(self, root: Path) -> Path:
        (root / "dims.py").write_text("L = 10.0\n")
        path = create_notebook(root, "part", "part")
        path.write_text(path.read_text().replace("import simplecadapi as scad\n", "import simplecadapi as scad\n    import dims\n", 1))
        return path

    def test_the_signature_follows_what_the_model_depends_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = self._workspace(root)
            state = WorkspaceState(root, path)
            first = state._signature(path)
            self.assertEqual(first, state._signature(path))
            time.sleep(2.1)  # file digests are remembered per (mtime, size) once settled
            (root / "dims.py").write_text("L = 11.0\n")
            changed = state._signature(path)
            self.assertNotEqual(first, changed)  # a module it imports
            path.write_text(path.read_text() + "\n# edited\n")
            self.assertNotEqual(changed, state._signature(path))  # the notebook itself

    def test_a_package_is_recalled_from_memory_and_from_disk_for_its_signature_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = self._workspace(root)
            state = WorkspaceState(root, path)
            state.remember_model(path, "sig-1", b"PKG")
            self.assertEqual(state._recall_model(path, "sig-1"), b"PKG")
            self.assertIsNone(state._recall_model(path, "sig-2"))
            fresh = WorkspaceState(root, path)  # a new server: only the disk remembers
            self.assertEqual(fresh._recall_model(path, "sig-1"), b"PKG")
            self.assertIsNone(fresh._recall_model(path, "sig-2"))

    def test_restoring_shows_the_cells_and_the_model_before_any_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = self._workspace(root)
            state = WorkspaceState(root, path)
            sent: list[dict] = []
            state.emit = sent.append  # type: ignore[method-assign]
            state.hub.broadcast = lambda message: None  # type: ignore[method-assign]
            self.assertFalse(state._restore(path))  # nothing published yet
            state.remember_model(path, state._signature(path), b"PKG")
            self.assertTrue(state._restore(path))
            package = next(m for m in sent if m["type"] == "preview")
            self.assertEqual((package["cached"], package["size"]), (True, 3))
            self.assertEqual(state.latest_preview_bytes, b"PKG")
            cells = next(m for m in sent if m["type"] == "notebook.cells")["cells"]
            self.assertEqual([c["title"] for c in cells], ["params", "base", "part"])
            self.assertTrue(all(c["readonly"] for c in cells))  # not editable until a kernel has them
            self.assertIn("RADIUS", state.specs)

    def test_static_cells_leave_out_the_setup_cell(self) -> None:
        from simplecadapi.editor.server import _static_cells

        with tempfile.TemporaryDirectory() as tmp:
            path = create_notebook(Path(tmp), "part", "part")
            names = [cell["name"] for cell in _static_cells(path)]
            self.assertNotIn("setup", names)
            self.assertEqual(len(names), 3)


class SwitchOrderTest(unittest.TestCase):
    """Opening one notebook after another: the last one asked for is the one that ends up open."""

    def test_the_last_open_wins_however_the_threads_are_scheduled(self) -> None:
        import simplecadapi.editor.server as server

        booted: list[str] = []

        class FakeKernel:
            marimo_url = "http://127.0.0.1:1"
            alive = True

            def __init__(self, notebook, **_kw) -> None:
                self.notebook = notebook
                self._stop = __import__("threading").Event()

            def start(self) -> None:
                time.sleep(0.2)
                if self._stop.is_set():
                    raise RuntimeError("stopped while booting")
                booted.append(self.notebook.stem)

            def stop(self) -> None:
                self._stop.set()

            def wait_instantiated(self, *_a, **_k) -> bool:
                return True

            def wait_idle(self, *_a, **_k) -> bool:
                return True

        original = server.MarimoKernel
        server.MarimoKernel = FakeKernel  # type: ignore[misc]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                a = create_notebook(root, "alpha", "part")
                b = create_notebook(root, "beta", "part")
                state = WorkspaceState(root, a)
                sent: list[dict] = []
                state.hub.broadcast = sent.append  # type: ignore[method-assign]
                state.settle = lambda: None  # type: ignore[method-assign]
                state._watch_files = lambda kernel: None  # type: ignore[method-assign]
                first = state.reserve_switch()
                second = state.reserve_switch()
                # the later request's thread runs first, the earlier one after it
                state.open_notebook("beta.py", second)
                state.open_notebook("alpha.py", first)
                self.assertEqual(state.notebook, b)
                self.assertEqual(booted, ["beta"])
                self.assertEqual([m for m in sent if m.get("error")], [])
        finally:
            server.MarimoKernel = original  # type: ignore[misc]

    def test_an_open_superseded_while_booting_ends_quietly(self) -> None:
        import threading

        import simplecadapi.editor.server as server

        class SlowKernel:
            marimo_url = "http://127.0.0.1:1"
            alive = True

            def __init__(self, notebook, **_kw) -> None:
                self._stop = threading.Event()

            def start(self) -> None:
                self._stop.wait(5)
                raise RuntimeError("marimo exited with code -15")

            def stop(self) -> None:
                self._stop.set()

            def wait_instantiated(self, *_a, **_k) -> bool:
                return True

            def wait_idle(self, *_a, **_k) -> bool:
                return True

        original = server.MarimoKernel
        server.MarimoKernel = SlowKernel  # type: ignore[misc]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                create_notebook(root, "alpha", "part")
                b = create_notebook(root, "beta", "part")
                state = WorkspaceState(root, None)
                state.hub.broadcast = lambda message: None  # type: ignore[method-assign]
                errors: list[BaseException] = []

                def first() -> None:
                    try:
                        state.open_notebook("alpha.py")
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(exc)

                thread = threading.Thread(target=first)
                thread.start()
                time.sleep(0.3)  # alpha is booting
                state.reserve_switch()
                state._begin_switch(b, state._generation)  # beta is asked for: alpha's kernel is stopped
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(state.notebook, b)
        finally:
            server.MarimoKernel = original  # type: ignore[misc]


class InterruptTest(unittest.TestCase):
    def test_the_stop_command_interrupts_the_kernel(self) -> None:
        state = WorkspaceState(Path(tempfile.gettempdir()))
        stopped: list[bool] = []
        state.kernel = type("K", (), {"interrupt": lambda self: stopped.append(True)})()  # type: ignore[assignment]
        self.assertEqual(state.dispatch_command({"type": "interrupt.request"})["type"], "ack")
        deadline = time.monotonic() + 2
        while not stopped and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(stopped, [True])

    def test_cell_states_from_marimo_reach_the_webuis(self) -> None:
        from simplecadapi.editor.kernel import MarimoKernel

        seen: list[tuple[str, str]] = []
        kernel = MarimoKernel(Path(tempfile.gettempdir()) / "x.py", server_port=40000, on_cell_status=lambda i, s: seen.append((i, s)))
        kernel._on_message(json.dumps({"op": "cell-op", "data": {"cell_id": "Hbol", "status": "running"}}))
        kernel._on_message(json.dumps({"op": "cell-op", "data": {"cell_id": "Hbol", "status": None}}))
        kernel._on_message("not json")
        # the setup cell and the bridge's own scratch snippets are not cells of the notebook
        kernel._on_message(json.dumps({"op": "cell-op", "data": {"cell_id": "setup", "status": "running"}}))
        kernel._on_message(json.dumps({"op": "cell-op", "data": {"cell_id": "__scratch__", "status": "running"}}))
        self.assertEqual(seen, [("Hbol", "running")])
        state = WorkspaceState(Path(tempfile.gettempdir()))
        sent: list[dict] = []
        state.hub.broadcast = sent.append  # type: ignore[method-assign]
        state.cells = [{"id": "Hbol", "code": "", "status": "idle", "title": "base"}]
        state.cell_status("Hbol", "queued")
        self.assertEqual(state.cells[0]["status"], "queued")
        self.assertEqual(sent, [{"type": "cell.status", "id": "Hbol", "status": "queued", "title": "base"}])


@unittest.skipUnless(os.environ.get("SCA_EDITOR_E2E"), "set SCA_EDITOR_E2E=1 to boot a marimo kernel")
class InterruptEndToEndTest(unittest.TestCase):
    def test_a_running_cell_is_stopped_and_the_kernel_stays_usable(self) -> None:
        import threading

        import uvicorn

        from simplecadapi.editor.server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "slow.py"
            path.write_text(
                '# /// script\n# [tool.simplecadapi]\n# id = "slow"\n# ///\n'
                "import marimo\n\napp = marimo.App()\n\nwith app.setup:\n    import simplecadapi as scad\n\n\n"
                "@app.cell\ndef _():\n    value = 1\n    return (value,)\n\n\n"
                "@app.cell\ndef _(value):\n    import time\n    time.sleep(60)\n    slow = value\n    return (slow,)\n"
            )
            state = WorkspaceState(root)
            state.port = 17737
            app = create_app(state)
            server = uvicorn.Server(uvicorn.Config(app, port=state.port, log_level="error"))
            threading.Thread(target=server.run, daemon=True).start()
            state.hub.attach_loop(__import__("asyncio").new_event_loop())
            statuses: list[tuple[str, str]] = []
            try:
                # boot without running the 60 s cell: start the kernel directly and interrupt the run
                from simplecadapi.editor.kernel import MarimoKernel

                kernel = MarimoKernel(path, server_port=state.port, on_cell_status=lambda i, s: statuses.append((i, s)))
                state.kernel = kernel
                state.notebook = path
                threading.Thread(target=kernel.start, daemon=True).start()
                deadline = time.monotonic() + 60
                while not any(s == "running" for _, s in statuses) and time.monotonic() < deadline:
                    time.sleep(0.2)
                self.assertTrue(any(s == "running" for _, s in statuses), "the slow cell never started")
                started = time.monotonic()
                kernel.interrupt()
                deadline = time.monotonic() + 20
                while not any(s == "idle" for _, s in statuses[-3:]) and time.monotonic() < deadline:
                    time.sleep(0.2)
                self.assertLess(time.monotonic() - started, 15)  # stopped, not 60 s later
                self.assertIn("OK", kernel.execute("print('ok')").get("log", "").upper())  # still usable
            finally:
                kernel = state.kernel
                if kernel is not None:
                    kernel.stop()
                server.should_exit = True
