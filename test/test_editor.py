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
                first = state.latest_package_bytes
                self.assertTrue(first)
                state.dispatch_command({"type": "param.set", "values": {"RADIUS": 40}})
                deadline = time.monotonic() + 90
                while state.latest_package_bytes == first and time.monotonic() < deadline:
                    time.sleep(0.5)
                self.assertNotEqual(state.latest_package_bytes, first)
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
