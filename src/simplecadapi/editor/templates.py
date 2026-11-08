"""New notebooks: a part or an assembly, as the editor's "new" action writes them.

A new part is empty: the header and nothing else (no cell builds its ``Part``: the runtime makes it from the one open
body), and the person or agent adds the first feature.  ``sample`` writes a small parametric part instead (a
``# ---- params ----`` cell with ``# ui:`` sliders and one feature, after the feature tree convention), for a first look
or a test; an assembly ends with its layout.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..runtime.workspace import scan_workspace

_HEADER = '''# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "{id}"
# revision = "1.0.0"
# ///
import marimo

app = marimo.App(width="medium")

with app.setup:
    import simplecadapi as scad
'''

_SAMPLE = '''

@app.cell
def _():
    # ---- params ----
    RADIUS = scad.var("radius", 25.0, comment="Radius", unit="mm")  # ui: slider(5, 60, step=1, label="Radius")
    HEIGHT = scad.var("height", 10.0, comment="Height", unit="mm")  # ui: slider(2, 40, step=1, label="Height")
    return HEIGHT, RADIUS


@app.cell
def _(HEIGHT, RADIUS):
    # ---- feature: base (build) ----
    base = scad.make_cylinder_rsolid(
        radius=RADIUS,
        height=HEIGHT,
        bottom_face_center=(0.0, 0.0, 0.0),
        axis=(0.0, 0.0, 1.0),
    )
    return (base,)
'''

_ASSEMBLY = '''

@app.cell
def _():
    # ---- feature: parts (add) ----
{uses}
    return {names},


@app.cell
def _({names}):
    # ---- feature: layout (add) ----
    _assembly = scad.make_assembly_rassembly(
        assembly_id=scad.notebook_id(), name="{title}"
    )
{components}
    {variable} = _assembly
    return ({variable},)
'''

_RUNNER = '''

if __name__ == "__main__":
    app.run()
'''

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def render_notebook(name: str, kind: str = "part", parts: list[tuple[str, str]] | None = None) -> str:
    """The source of a new notebook called *name*.

    An assembly lists the part notebooks it uses as ``(path, variable)``.
    """
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid notebook name: {name!r}")
    variable = name.replace("-", "_")
    # The kind is fixed when the notebook is made.
    header = _HEADER.format(id=name).replace('# id = "', f'# kind = "{"assembly" if kind == "assembly" else "part"}"\n# id = "', 1)
    if kind in ("part", "blank"):
        # No cells: the first feature is added by whoever models it.  A part notebook needs no product cell: its open
        # body is the Part.  ("blank" is the former name of this.)
        return header + _RUNNER
    if kind == "sample":
        return header + _SAMPLE + _RUNNER
    if kind != "assembly":
        raise ValueError(f"unknown notebook kind: {kind}")
    if not parts:
        raise ValueError("an assembly uses part notebooks; create a part first")
    names = ", ".join(variable_name for _, variable_name in parts)
    uses = "\n".join(f'    {variable_name} = scad.use("{path}")' for path, variable_name in parts)
    components = "\n".join(
        "    _assembly = scad.add_component_rassembly(\n"
        f'        assembly=_assembly, item={variable_name}, component_id="{variable_name}",\n'
        "        placement=scad.identity_placement_rplacement(),\n"
        "    )"
        for _, variable_name in parts
    )
    body = _ASSEMBLY.format(
        uses=uses, names=names, title=name, components=components, variable=variable
    )
    return header + body + _RUNNER


def create_notebook(workspace: Path, name: str, kind: str = "part") -> Path:
    """Write a new notebook into *workspace*; refuses to clobber a file."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid notebook name: {name!r}")
    root = workspace.resolve()
    path = root / f"{name}.py"
    if path.exists():
        raise FileExistsError(f"notebook already exists: {path}")
    parts: list[tuple[str, str]] = []
    if kind == "assembly":
        for entry in scan_workspace(root):
            if entry.kind == "part":
                # Relative to the new notebook, which sits at the workspace root.
                parts.append((entry.path, re.sub(r"\W", "_", Path(entry.path).stem)))
            if len(parts) == 2:
                break
    path.write_text(render_notebook(name, kind, parts), encoding="utf-8")
    return path
