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

- **The product** is the top-level variable whose id (`Part.part_id` or
  `Assembly.assembly_id`) equals the notebook id. An assembly built up over
  several cells (components, then constraints, then the solve) carries the
  id in each of them; the product is the one no other cell reads. Exactly
  one must remain; the error lists the candidates otherwise. A run may be
  given another id
  (`run_notebook(..., id=...)`, `scad.use(..., id=...)`, `sca run --id`);
  cells read the id of their run with `scad.notebook_id()` — see
  [Part families](#part-families).
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

## Composing notebooks

`scad.use(path, **overrides)` runs another notebook and returns its product,
ready to be a component of an assembly. A relative path is relative to the
calling notebook; keyword arguments override the child's top-level variables.

```python
@app.cell
def _():
    bracket = scad.use("bracket.py", width=24.0)
    return (bracket,)


@app.cell
def _(bracket):
    rig = scad.make_assembly_rassembly(assembly_id="rig", name="Rig")
    rig = scad.add_component_rassembly(
        assembly=rig, item=bracket, component_id="bracket",
        placement=scad.identity_placement_rplacement(),
    )
    return (rig,)
```

The child runs with its own cell cache, and the calling notebook's cache
depends on the child from then on.

### Part families

One notebook may describe several parts that differ only in their
parameters — the links of a linkage, the planet gears of two stages. Name the
product with `scad.notebook_id()` instead of a literal:

```python
# link_bar.py — [tool.simplecadapi] id = "link_bar"
@app.cell
def _(web):
    link_bar = scad.Part(part_id=scad.notebook_id(), body=web)
    return (link_bar,)
```

and give each member an id of its own where it is used:

```python
@app.cell
def _():
    crank = scad.use("link_bar.py", id="crank", center_distance=40.0)
    rocker = scad.use("link_bar.py", id="rocker", center_distance=90.0)
    return crank, rocker
```

Each id is one definition, with its own content hash and its own cell cache.
Used twice under one id with different parameters, the two products would be
two definitions with the same id, which an assembly rejects
(`reference_identity_conflict`). Run alone, the notebook builds the member
named in its header.

## The cell cache

Every cell except the setup cell is cached, in headless runs and in the
editor's kernel alike (what one computed the other restores). marimo keys a
cell's entry by its code and what it reads; SimpleCAD adds a digest of what
the cells cannot show, **per cell**, over the files *that cell* depends on:

- **local modules** — Python files under the notebook's directory, found from
  the `import` statements (setup cell included), and the local modules those
  import in turn. A cell depends on a module when it reads a name an `import`
  bound to it, or calls a function the notebook defines (an `@app.function`
  cell, a `def` in the setup cell) that does;
- **everything the cells it reads from depend on**: marimo keys a cell that
  reads an object (a solid, a part) by the code of the cells that made it, so
  it cannot see a module that changed upstream;
- **child notebooks** run with `scad.use` (and what they depend on), for the
  cells that call `use` and those that read what they make;
- the files listed in `inputs`, for every cell;
- the SimpleCAD, OpenCASCADE, and marimo versions.

So editing `dimensions.py` recomputes the cells that read the dimensions (and
what is made from them) and restores the rest, and going back to an earlier
value restores everything. A run keeps the entries of its own digests and of
the previous run's. Local modules are imported afresh when their files changed
since the last run in the same process.

- Imports through `importlib` or `__import__` are not seen; import local
  modules with `import` statements, or list the files in `inputs`.
- Values that cannot be pickled cannot be restored: the run then executes the
  whole notebook without the cache. Keep such values (locks, open files,
  handles) out of top-level variables.
- The editor kernel does not cache the cells that run child notebooks (only a
  headless run records what they depend on; the children themselves are
  cached), and keys the cells downstream of a value an editor saved by that
  value. `SCA_NO_KERNEL_CACHE=1` turns the kernel's cache off.
- The state lives in `__marimo__/simplecad/<notebook file name>/<id>/`
  (`deps.json` and `cache/<digest>/`), one directory per part-family member. It
  is generated state: do not commit `__marimo__/`. Entries are unsigned unless
  the `cryptography` package is installed; treat the directory as trusted local
  files.

**In the marimo editor, leave `[tool.marimo.runtime] cache_cells` off.** That
is marimo's own cache: it does not know these digests, so after a local module
or child notebook changes it would restore stale values. Under `sca edit` the
SimpleCAD cache above is already in use.

## Library parts: `@scad.part` and `@scad.assemble`

Reusable parts belong in plain `.py` modules next to the notebooks, built by
decorated builders. A call builds the part in a session of its own and returns
a `PartBuildResult(value, definition, feature_graph)`; `@scad.assemble`
returns an `AssemblyBuildResult` with the same fields. Calls may happen inside
a notebook cell or another builder: the built part enters the calling
recording as an external definition.

```python
# lib/plates.py
import simplecadapi as scad


@scad.part(id="mounting_plate", revision="1.0.0")
def build_plate(width: float = 30.0) -> scad.Part:
    body = scad.make_box_rsolid(width=width, height=20.0, depth=3.0)
    return scad.make_part_rpart(part_id="mounting_plate", body=body)
```

```python
@app.cell
def _():
    from lib.plates import build_plate

    plate = build_plate(width=40.0).value
    return (plate,)
```

The builders do not cache; inside a notebook the calling cell is cached, and
editing `lib/plates.py` invalidates it through *D*. Declare every non-Python
file a builder reads with `scad.file_input(...)`; its content snapshot is
recorded in the definition. `@scad.assemble(definitions=...)` names the
external part and assembly definitions an assembly references; its assembly
is solved strictly.

## Product package export

A notebook's product, or a builder's result, is written as one canonical
product package:

```python
scad.capture(run.definition, "out/bracket.scadpkg")
scad.capture(build_plate(), "out/plate.scadpkg")

root = scad.load_product_package("out/bracket.scadpkg")
rebuilt = scad.materialize_definition(root)
```

Use `build_product_package(...)`, `encode_product_package(...)`,
`read_product_package(...)`, and `load_product_package(...)` only for explicit
in-memory package handling. `validate_product_package(...)` verifies every object
hash and size, the complete recursive definition graph, cycle/depth limits, and
rejects missing or unreferenced objects. Use `export_part_definition(...)` or
`export_assembly_definition(...)` only for low-level definition exchange or
inspection; neither is the product delivery format.

## Downstream CAD and mesh targets

Keep `.scadpkg` as the canonical SimpleCAD delivery artifact. Choose a
downstream target from the consumer contract:

| Target | Use when | Preserved contract | Boundary |
| --- | --- | --- | --- |
| `.scadpkg` | Rebuild, replay, or further SimpleCAD tooling is required | Complete durable definition closure, feature graphs, source snapshots, topology, connectors, constraints, and materials | SimpleCAD-specific archive |
| `.FCStd` | A FreeCAD user needs an editable native document | Definition-owned, dependency-first native feature graphs; final body links; repeated instances; nested assemblies; names; solved placements; materials; connectors; constraints; grounding; revision; and content hashes | Requires FreeCADCmd/FreeCAD |
| AP242 `.step` | Neutral CAD exchange or downstream OpenCASCADE tooling is required | Evaluated BREP, product hierarchy, shared definitions, occurrence names/placements, materials, colors, density, and named SimpleCAD property payloads | Canonical feature history is not reconstructed as AP242 features |
| Triangle `.obj` | Surface inspection or DCC exchange needs an indexed mesh | Direct OpenCASCADE tessellation of evaluated BREP with shared vertices and oriented triangles | Evaluated surface mesh only; no CAD hierarchy, feature semantics, quads, or materials |
| Binary `.stl` | Additive manufacturing or triangle-only consumers | The same direct OpenCASCADE BREP triangles | Facet soup only; no shared vertices, CAD hierarchy, feature semantics, or materials |

```python
package_path = "out/product.scadpkg"
scad.capture(run.definition, package_path)

fcstd_path = scad.translator.freecad_translator.translate_product_package_to_fcstd(
    package_path,
    "out/product.FCStd",
)
step_report = scad.exporter.export_product_package_to_step(
    package_path,
    "out/product.step",
)
stl_report = scad.exporter.export_product_package_to_stl(
    package_path,
    "out/product.stl",
)
obj_report = scad.exporter.export_product_package_to_obj(
    package_path,
    "out/product.obj",
)
print(step_report.definition_ids, step_report.occurrence_count)
print(stl_report.solid_count, stl_report.triangle_count)
print(obj_report.vertex_count, obj_report.triangle_count)
```

STL and OBJ use the same direct OpenCASCADE tessellation and parameters. Set
`linear_deflection` to the maximum chordal deviation in product units and
`angular_deflection_degrees` to the curved-surface angular limit. Both formats
contain oriented triangles; OBJ preserves shared vertex indices while binary STL
stores each facet independently. No remeshing or optional dependency is involved.

AP242 definition and occurrence metadata is stored in one standard
`PROPERTY_DEFINITION_REPRESENTATION`. Its named
`DESCRIPTIVE_REPRESENTATION_ITEM` records use
`SimpleCAD:definition:<kind>:<definition_id>` and
`SimpleCAD:occurrence:<parent_definition_id>:<component_id>`. Each description
is canonical sorted JSON containing durable IDs, revision, content hash,
connectors, constraints, grounding, name, and solved placement.
`ProductSTEPExportReport` reports the schema, definition IDs, occurrence
count, material IDs, metadata item count, and explicit limitations.

For tetrahedral meshing, run the split example directly in dependency order:
the model is the `bracket.py` notebook, `export_step.py` captures its product
to `.scadpkg` (through `bracket_package.py`) and exports AP242 STEP, and
`export_fem_mesh.py` imports that STEP with Gmsh's OpenCASCADE kernel. The FEM
stage rejects imports with no 3D volumes, generates a dimension-3 mesh, writes
`.msh`, and always finalizes Gmsh. Install and invoke the optional dependency
with `uv run --extra gmsh python
examples/ap242_gmsh_volume_mesh/export_fem_mesh.py`; Gmsh is never imported
by the core SDK or product exporters.
