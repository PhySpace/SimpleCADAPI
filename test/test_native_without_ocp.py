"""The native backend runs the core path without the OCP package.

With ``SCA_BACKEND=native`` the C++ module replaces the OCP layer: ``import simplecadapi``, the notebook
runtime, ``@part`` / ``@assemble`` builds, the product API, ``ql``, the standard parts and the editor
kernel must work while ``import OCP`` raises.  A stub package named ``OCP`` that raises on import is put
first on ``PYTHONPATH`` of every process (the editor kernel and the prefetch workers are subprocesses).
The OCCT view of a shape (``.wrapped``) is the C++ module's own binding, so the layers that read OCCT
shapes (inspection, export, translation, screenshots) run without OCP as well.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import pytest

CORE = textwrap.dedent(
    """
    import sys
    import simplecadapi as scad

    box = scad.make_box_rsolid(10, 20, 30)
    hole = scad.make_cylinder_rsolid(3, 40, bottom_face_center=(0, 0, -5))
    body = scad.cut_rsolid(box, hole)
    assert abs(body.get_volume() - (6000 - 3.14159265358979 * 9 * 30)) < 1e-6
    assert scad.ql.faces().resolve(body)
    part = scad.make_part_rpart("p", body)
    assembly = scad.make_assembly_rassembly("a")
    assembly = scad.add_component_rassembly(assembly, part, "c", scad.identity_placement_rplacement())
    assert len(assembly.components) == 1
    gear = scad.std.gear.make_spur_gear_rsolid(12, 2.0, gear_height=5.0)
    assert gear.get_volume() > 0
    from simplecadapi.artifacts.brep import brep_hash
    assert brep_hash(body).startswith("sha256:")
    from simplecadapi.artifacts import geometry_interface_fingerprint
    assert geometry_interface_fingerprint(body).startswith("sha256:")
    from simplecadapi.runtime import run_notebook  # noqa: F401
    import simplecadapi.build, simplecadapi.editor  # noqa: F401
    print("ok", "OCP" in sys.modules and sys.modules["OCP"] is not None)
    """
)

NOTEBOOK = textwrap.dedent(
    '''
    # /// script
    # [tool.simplecadapi]
    # id = "plate"
    # ///
    import marimo

    app = marimo.App()

    with app.setup:
        import simplecadapi as scad


    @app.cell
    def _():
        WIDTH = scad.var("width", 20.0, unit="mm")
        return (WIDTH,)


    @app.cell
    def _(WIDTH):
        body = scad.make_box_rsolid(float(WIDTH), 10.0, 5.0)
        plate = scad.make_part_rpart("plate", body)
        return (plate,)


    if __name__ == "__main__":
        app.run()
    '''
)

RUNTIME = textwrap.dedent(
    """
    import sys
    from simplecadapi.runtime import run_notebook

    run = run_notebook(sys.argv[1])
    assert run.definition.content_hash.startswith("sha256:")
    assert abs(run.product.body.get_volume() - 1000.0) < 1e-6
    print("ok")
    """
)

EDITOR = textwrap.dedent(
    """
    import asyncio, sys, threading, time
    import uvicorn
    from pathlib import Path
    from simplecadapi.editor.server import WorkspaceState, create_app

    root = Path(sys.argv[1])
    state = WorkspaceState(root)
    state.port = 17795
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=state.port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    state.hub.attach_loop(asyncio.new_event_loop())
    try:
        state.start_kernel(root / "bracket.py")
        first = state.latest_preview_bytes
        assert first
        state.dispatch_command({"type": "param.set", "values": {"RADIUS": 40}})
        deadline = time.monotonic() + 90
        while state.latest_preview_bytes == first and time.monotonic() < deadline:
            time.sleep(0.25)
        assert state.latest_preview_bytes != first
        print("ok")
    finally:
        if state.kernel is not None:
            state.kernel.stop()
        server.should_exit = True
    """
)


class NativeWithoutOcpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve()
        stub = cls.root / "blocked" / "OCP"
        stub.mkdir(parents=True)
        (stub / "__init__.py").write_text(
            'raise ImportError("OCP is blocked: the native backend must not need it")\n', encoding="utf-8"
        )
        cls.env = dict(os.environ)
        cls.env["PYTHONPATH"] = os.pathsep.join(
            [str(cls.root / "blocked"), *filter(None, [os.environ.get("PYTHONPATH")])]
        )
        cls.env["SCA_BACKEND"] = "native"
        cls.work = cls.root / "work"
        cls.work.mkdir()
        (cls.work / "plate.py").write_text(NOTEBOOK, encoding="utf-8")
        from simplecadapi.editor.templates import create_notebook

        create_notebook(cls.work, "bracket", "part")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def run_script(self, code: str, *args: str, timeout: int = 300) -> str:
        done = subprocess.run(
            [sys.executable, "-c", code, *args],
            env=self.env,
            cwd=str(self.root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        return done.stdout

    def test_the_import_and_the_modelling_api_need_no_ocp(self) -> None:
        self.assertIn("ok", self.run_script(CORE))

    def test_the_notebook_runtime_needs_no_ocp(self) -> None:
        self.assertIn("ok", self.run_script(RUNTIME, str(self.work / "plate.py")))

    def test_the_editor_kernel_needs_no_ocp(self) -> None:
        pytest.importorskip("uvicorn")
        self.assertIn("ok", self.run_script(EDITOR, str(self.work), timeout=400))

    def test_the_occt_view_of_a_shape_needs_no_ocp(self) -> None:
        code = (
            "import simplecadapi as scad\n"
            "from simplecadapi._cpp.occt.BRepGProp import BRepGProp\n"
            "from simplecadapi._cpp.occt.GProp import GProp_GProps\n"
            "b = scad.make_box_rsolid(1, 2, 3)\n"
            "props = GProp_GProps()\n"
            "BRepGProp.VolumeProperties_s(b.wrapped, props)\n"
            "print('volume', round(props.Mass(), 6))\n"
        )
        self.assertIn("volume 6.0", self.run_script(code))


if __name__ == "__main__":
    unittest.main()
