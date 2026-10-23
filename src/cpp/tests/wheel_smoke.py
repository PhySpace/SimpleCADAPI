"""Smoke test of an installed wheel: the compiled module loads, models, exchanges files, renders and reports errors.

cibuildwheel runs this in a clean environment with only the built wheel installed (no checkout on the path), on every
platform and Python version of a release.  The full test suite runs separately against the Linux wheels.

    python src/cpp/tests/wheel_smoke.py
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    import simplecadapi as scad
    import simplecadapi._cpp as cpp

    # The extension is the one shipped in the wheel, and it carries its own OpenCASCADE (no OCP, no system OCCT).
    here = Path(cpp.__file__).resolve().parent
    assert any(here.glob("_native*")), f"no compiled extension next to {cpp.__file__}"
    from simplecadapi._cpp import occt

    print("python", sys.version.split()[0], "| OpenCASCADE", occt.__version__, "|", here)
    try:
        import OCP  # noqa: F401
    except ImportError:
        pass
    else:
        raise AssertionError("OCP is installed in this environment; the wheel must not need it")

    # Modeling.
    box = scad.make_box_rsolid(10, 20, 30)
    hole = scad.make_cylinder_rsolid(3, 40, bottom_face_center=(0, 0, -5))
    body = scad.cut_rsolid(box, hole)
    expected = 10 * 20 * 30 - math.pi * 3**2 * 30
    assert abs(body.get_volume() - expected) < 1e-6, (body.get_volume(), expected)

    # The OCCT view of a shape.
    from simplecadapi._cpp.occt.BRepGProp import BRepGProp
    from simplecadapi._cpp.occt.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(body.wrapped, props)
    assert abs(props.Mass() - expected) < 1e-6

    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)

        # File exchange: BREP bytes, STEP and STL round trips.
        restored = cpp.from_brep(body.to_brep())
        assert abs(restored.get_volume() - expected) < 1e-6
        step = folder / "body.step"
        cpp.export_step(body, str(step))
        assert step.stat().st_size > 0
        assert abs(cpp.import_step(str(step)).get_volume() - expected) < 1e-3
        stl = folder / "body.stl"
        cpp.export_stl(body, str(stl))
        assert stl.stat().st_size > 0

        # Headless rendering (the software renderer: no GPU, no display, no VTK).
        png = folder / "body.png"
        scad.render_screenshot_rpath(shapes=[body], output_path=str(png))
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

        # Sketch solver and the product layer.
        part = scad.make_part_rpart("plate", body)
        assembly = scad.make_assembly_rassembly("a")
        assembly = scad.add_component_rassembly(assembly, part, "c", scad.identity_placement_rplacement())
        assert len(assembly.components) == 1

    # Errors are rendered in full, for the agent that reads them.
    try:
        scad.make_box_rsolid(-1, 1, 1)
    except scad.SimpleCADError as error:
        text = str(error)
        for section in ("Operation:", "What happened:", "Possible causes:", "How to fix:"):
            assert section in text, (section, text)
    else:
        raise AssertionError("a negative box did not raise")

    # The command line is installed and runs.
    from simplecadapi.cli import main as sca_main

    assert callable(sca_main)
    print("wheel smoke test passed on", sys.platform, os.uname().machine if hasattr(os, "uname") else "")


if __name__ == "__main__":
    main()
