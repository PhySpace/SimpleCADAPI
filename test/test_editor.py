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

from simplecadapi.editor.server import WorkspaceState, _module_code, pick_notebook
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
