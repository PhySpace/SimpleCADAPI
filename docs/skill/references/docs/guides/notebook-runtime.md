# Notebook Runtime and Product Build Workflow

A SimpleCAD model is a [marimo](https://marimo.io) notebook: a plain `.py`
file in the repository. The file is the only source of truth; `.scadpkg`
packages are generated from it for exchange and publishing, never read back
as input. The same runtime runs the notebook everywhere — the marimo editor,
`sca run`, and `simplecadapi.runtime.run_notebook()` — and only needs
`simplecadapi` installed.

## Project layout

```text
my_product/
├── base_plate.py      # part notebook: one physical part
├── motor_mount.py     # part notebook
├── product.py         # assembly notebook: scad.use("base_plate.py"), ...
├── lib/               # plain modules: shared dimensions, @scad.part builders
├── data/profile.dxf   # non-Python input, listed in the notebook's `inputs`
├── verify/            # verification scripts; load products with run_notebook
└── __marimo__/        # generated runtime state: add to .gitignore
```

One part per notebook and one assembly notebook per product. The notebooks
and modules are the project; packages under `out/` are generated from them.

## The notebook

A notebook becomes a SimpleCAD notebook by carrying a `[tool.simplecadapi]`
table in its PEP 723 script header. Notebooks without the table run exactly as
marimo runs them.

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "bracket"                  # default: the file name without .py
# revision = "1.0.0"
# tolerance_profile = "simplecad-default"
# inputs = ["data/profile.dxf"]   # optional: project files the cells read
# ///
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    width = 20.0
    return (width,)


@app.cell
def _(width):
    # ---- feature: base-block (build) ----
    body = scad.make_box_rsolid(width, 10.0, 5.0)
    return (body,)


@app.cell
def _(body):
    # ---- feature: bore (subtract) ----
    body_bored = scad.cut_rsolid(body, scad.make_cylinder_rsolid(3.0, 5.0))
    return (body_bored,)


@app.cell
def _(body_bored):
    bracket = scad.Part(part_id="bracket", body=body_bored)
    return (bracket,)


if __name__ == "__main__":
    app.run()
```

- **The kind** is fixed when the notebook is made: the header says
  `kind = "part"` or `kind = "assembly"` (`sca new` and the editor write it).
  A `kind = "part"` notebook needs **no product cell**: when no top-level
  `Part` has the notebook id, the runtime makes one from the notebook's
  *open bodies* (public top-level `Solid`s, or the piece lists of split cuts,
  that no other cell reads and that no other such value was built from), with
  the notebook id. One open body is a one-body Part (body id `"body"`); several
  are the bodies of one Part, named by their variables (pieces `<name>_1..n`).
  Write a `make_part_rpart` cell only to add connectors or a material, or to
  choose and name the bodies yourself; it then wins. The headless run and the
  editor use the same rule (`runtime/projection.py`, `find_product`).
- **The product** is the top-level variable whose id (`Part.part_id` or
  `Assembly.assembly_id`) equals the notebook id. An assembly built up over
  several cells (components, then constraints, then the solve) carries the
  id in each of them; the product is the one no other cell reads. Exactly
  one must remain; the error lists the candidates otherwise. A run may be
  given another id
  (`run_notebook(..., id=...)`, `scad.use(..., id=...)`, `sca run --id`);
  cells read the id of their run with `scad.notebook_id()` — see
  [Part families](notebook-composition-and-cache.md#part-families).
- **A part with several bodies** is one product:
  `scad.make_part_rpart(part_id=scad.notebook_id(), bodies={"base": base, "lid": lid})`.
  Each body keeps its own BRep, topology snapshot and tags in the package, whose
  part definition then has profile `simplecad-part-definition-3` (an older SDK
  refuses it instead of reading one body). One-body parts are unchanged.
  The cell cache restores a multi-body part like any other value.
- **Parameters** are ordinary top-level variables. Overriding one replaces it,
  and the cell that defines it does not run, so all variables of that cell
  must be overridden together. Group parameters into cells by what changes
  together (`# ---- params: bolt pattern ----`).
- **Helpers** shared by several cells are `@app.function`s: plain
  functions that read only the setup cell's names. Editing one re-runs the
  cells that call it.
- **One feature per cell.** Put one FTC block
  (`discipline/feature-tree-convention.md`) in each cell: the cell is the unit
  of caching and of incremental re-execution. marimo forbids redefining a
  variable in another cell, so each block binds a new name.
- **No boilerplate.** Each cell records into a graph session of its own,
  opened by the runtime; do not open `GraphSession` or `@scad.part` just to
  record a notebook's geometry.
- **Only what reaches the product is recorded.** The product's definition
  holds the operations upstream of the product; previews and experiments in
  other cells are left out.
- **Bind tolerance requirements to variables.** A requirement
  (`req = scad.get_active_session().require_tolerance(...)`) must be held by
  a top-level variable of the cell that creates it — the variable itself, or
  a list, tuple, set, or dict directly containing it. An unbound requirement
  fails the cell, because the cell cache stores variables only and would drop
  it on the next hit.
- Source positions in the definition point at the saved notebook file, and a
  cached run produces the same `content_hash` as a fresh one.

## Running headlessly

```bash
sca run bracket.py                        # run, print a JSON report
sca run bracket.py --set width=24         # override a top-level variable
sca run link_bar.py --id crank            # run one member of a part family
sca run bracket.py --out bracket.scadpkg  # also write the product package
sca run bracket.py --no-cache             # run every cell
```

`--set` values are Python literals, else strings; the option may repeat. The
report lists the definition id, kind, revision, `content_hash`, and every
cell's status: `ran`, `cached` (restored from the cell cache), or `skipped`
(replaced by an override).

From Python:

```python
from simplecadapi.runtime import run_notebook

run = run_notebook("bracket.py", overrides={"width": 24.0})
run.product            # the Part or Assembly, carrying its definition
run.definition         # its PartDefinition / AssemblyDefinition
run.values["width"]    # any top-level variable
[cell.status for cell in run.cells]
```

Errors raised by a cell propagate unchanged.

## Parameters and the editor

A **parameter** is a top-level variable a cell assigns a number, a bool, or a
`scad.var`, in a cell headed `# ---- params ----` (or `# ---- params: <group> ----`).
No change to a notebook is needed for an editor to list them. A trailing
`# ui:` comment on the line says which control to offer:

```python
# ---- params ----
OUTER_D = scad.var("outer_d", 100.0, unit="mm")  # ui: slider(50, 200, step=1, label="Outer diameter")
BOLTS = 6                                        # ui: number(3, 12, step=1)
CHAMFER = True                                   # no comment: a toggle, inferred
```

`slider(min, max, step=)`, `number(min=, max=, step=)` and `toggle()` take
`unit=` and `label=`. Without the comment a number gets a number box and a
bool a toggle. A bad comment is reported (`sca params`) and the inferred
control is used. A `scad.var`'s `unit` and `comment` show up in the editor.

**A `scad.var` is used like a number.** (When to make one, and where the cells go: `discipline/notebook-cell-design.md`.) Arithmetic on it (`2 * math.pi * R`, `R / 2`) builds a
formula that keeps the link to the parameter, so operators take it as it is and the model rebuilds when the slider
moves. Everything else Python asks of a number reads the value it has now: `R > 3`, `max(R, 3)`, `int(N)`,
`round(R, 1)`, `range(N)`, `[0] * N`, `f"{R:.1f}"`, `R == 5.0` all work, and the same code runs on a plain
float. `bool(R)` / `if R:` stays an error (as in 2.2.6; write the comparison, `if R > 0:`). Pass `float(R)` where a
plain number is needed: numpy (`np.sqrt(R)` raises and `np.array([R])` is an object array, because a Var has no array
protocol), `json.dumps`, and any notebook that also has to run on SimpleCADAPI 2.2.6, where the comparisons and
conversions above raise or answer wrongly. A count must be a whole number (`range(N)` with `N = 2.5` says so).

```bash
sca params bracket.py        # features (# ---- feature: ... ---- headers) and parameters, from the file
sca ls [DIR]                 # the notebooks under DIR: id, part or assembly, the notebooks each uses
```

A **workspace** is any directory tree: its models are the notebooks whose
header has `[tool.simplecadapi]`, at any depth. There is no manifest. Skipped
everywhere: names starting with `.` or `_`, and `node_modules`, `venv`,
`site-packages`, `build`, `dist` — a notebook in such a place is not listed
by `sca ls` or the editor's workspace tab, so keep notebooks in normally
named paths.

`sca edit [WORKSPACE]` (needs `pip install "simplecadapi[editor]"`) opens a
code-first editor on a workspace. The notebooks run in a marimo kernel with
this runtime's executor, so a model gives the same product in the editor as
under `sca run`; marimo's dataflow decides what reruns. A slider does not
edit the file: the editor saves the value (`params.json` in the notebook's
state directory), the kernel executor applies it as the declaring cell
finishes, and marimo reruns the cells that read it. **Write to source**
commits the saved values into the notebook; **revert** drops them. A headless
run takes only the overrides it is given, never the saved values, and the
notebook an assembly `use`s is run from its file: tune a part by opening it
and writing the value to source.

The editor and a coding agent share the notebook file:

- Every edit in a cell is **autosaved** to the file (it is not run; the cell
  shows `stale` until it is).
- **Picking in the viewport writes a selection cell**: each picked solid, face,
  edge or vertex becomes a `scad.ql` selector built from its geometry and
  is assigned to `selected_<kind>` (`selected_<kind>_<i>` when several of a
  kind are picked); `selected_item` lists them all. Ctrl/Cmd+click adds to the
  selection. The agent reads the cell from the file and builds on it, e.g.
  `scad.chamfer_rsolid(solid=body, edges=selected_edge_1, ...)`.
- `sca snapshot [WORKSPACE]` prints what the person is looking at as JSON: the
  selection, each cell's state and errors, the parameter values, and the path
  of the viewport image (`.sca-editor/viewport.png`) the agent can look at. The
  editor keeps `.sca-editor/snapshot.json` current while it runs.
- The local modules a notebook imports (`from dimensions import DIMS`) are
  listed under *modules* in the workspace tab, with the notebooks that use
  them. A module opens in a module view: its source, autosaved, and the fields
  of its dataclasses (and top-level constants with a `# ui:` comment) as
  controls whose values are written into the file. A change to a module, from
  the editor or from an agent on disk, reloads it and reruns the open notebook;
  the notebooks it `use`s are rerun from their files.
- A cell folds to its name (its feature slug, params header or first variable)
  and can run everything above it; `@app.function` cells are shown read-only
  (edit them in the file).

## Composing notebooks, the cell cache, library parts, export

- Composing notebooks (`scad.use`), part families (`scad.notebook_id()`), the cell cache, and library parts (`@scad.part`, `@scad.assemble`): `notebook-composition-and-cache.md`.
- Product package export (`scad.capture`), downstream targets (`.FCStd`, STEP, STL, OBJ) and the Gmsh meshing example: `product-export.md`.
