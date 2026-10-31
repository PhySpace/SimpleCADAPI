# Notebook Composition and the Cell Cache

**Read when:** a notebook uses another notebook (`scad.use`), one notebook describes a part family, a run is unexpectedly cached or stale, or a reusable part is built with `@scad.part` / `@scad.assemble`. Running a notebook and parameters are in `notebook-runtime.md`.

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
