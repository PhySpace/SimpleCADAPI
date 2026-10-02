"""Capture the bracket notebook's product as the exchange package.

Every export and translation script starts here. ``run_notebook`` builds
``bracket.py`` (cell-cached, so a rerun only reads the cache) and the
product is written to ``out/ap242_gmsh_bracket.scadpkg``, the file the
exporters, the translators and the FEM chain read.
"""

from __future__ import annotations

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
NOTEBOOK_PATH = HERE / "bracket.py"
PACKAGE_PATH = OUT_DIR / "ap242_gmsh_bracket.scadpkg"


def capture_bracket() -> Path:
    """Build the bracket notebook, write its package and return the path."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(NOTEBOOK_PATH)
    scad.capture(run.definition, PACKAGE_PATH)
    return PACKAGE_PATH
