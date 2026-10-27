# Changelog

All notable changes to SimpleCADAPI are documented here. Per-version
user-facing notes live in [`docs/updates/`](docs/updates/) (English and
中文).

## Unreleased

### Added
- `simplecadapi.verify` (`to_ocp`, `from_ocp`) and the `verify` extra (`pip install "simplecadapi[verify]"`, OCP 7.9
  without VTK) for verifier scripts: `shape.wrapped` is the SDK's own binding and OCP functions reject it. The SDK
  itself still never imports OCP. The skill gains `references/discipline/verifier-scripts.md` with the recipes
  (volume, bounds, validity, point in solid, distance, overlap) and a verifier skeleton.

### Removed
- The `fem` extra (`gmsh` and `ccx2paraview[VTK]`) and the README steps that used it; the `gmsh` extra stays. VTK is no
  longer in the lock file at all.

## 2.2.7b1 — 2026-10-24

### Added
- `cut_rsolid_list(base, *tools)`: the boolean cut that keeps every piece. A slot through a bar returns both halves, a
  tool that encloses the body returns an empty list. Recorded as `make_cut_rsolid_list` and replayable.
- Prebuilt wheels for Linux x86_64, Linux aarch64, macOS arm64 and Windows x86_64, each for Python 3.10-3.13,
  built by the release workflow against one static OpenCASCADE 7.9.3.

### Changed
- `simplecadapi.inspect.brep` is part of the default install and renders with the built-in software renderer: VTK is no
  longer needed, `matplotlib` is a core dependency, and the `inspect` extra is an empty alias.
- The geometry engine is C++ on OpenCASCADE, shipped in the wheel as `simplecadapi._cpp`; one distribution, one
  import package. The public API is unchanged, and the previous test suite passes (three tests that relied on a dropped
  sliver of a tangent cut now use a tool clear of the wall).
- Every message the library writes is English; the tag-validation and semantic-query errors render in full with
  possible causes and fixes.
- macOS wheels require macOS 14 or later.

### Fixed
- `cut_rsolid` no longer drops pieces silently. When a cut split the body it returned only the first piece (a slot
  through a 100x20x10 bar reported half the volume); it now raises and points to `cut_rsolid_list`. A tool that only
  touches a wall tangentially (a cylinder of radius 2 at (3, 3) in a 10x10 block) leaves a separate sliver and now
  raises too.

### Removed
- Dependencies `cadquery-ocp`, `ocp-gordon` and `py-slvs`; the `SCA_BACKEND` switch.

## 2.2.6.post2 — 2026-10-21

### Changed

- Operators: `scale_rsolid` and `transform_rsolid` are implemented in `operators/transform.py`,
  `boolean_rsolidlist` in `operators/boolean.py`, and `offset_rsolid`, `draft_rsolid`,
  `extrude_taper_rsolid`, `extrude_until_rsolid` and `sweep_multisection_rsolid` in
  `operators/features.py`, next to the operators of their family. `from simplecadapi import ...`
  is unchanged. The one-feature modules they were first written in (`operators.deformation`,
  `draft`, `section_features`, `limited_extrusion`) remain as aliases: importing a name from
  them still works and raises a `DeprecationWarning` that names the new place.

### Fixed

- Skill API docs: the documentation generator listed its source files and public functions by
  hand and had never been told about those four modules, so the docs of the eight operators
  above were kept by hand and deleted by the generator's clean-up. `operators/` is now
  discovered, a function the package exports is public, the content of the hand-written docs
  (examples, error conditions, replay notes) is in the docstrings, and tests check that every
  public operator has a doc and that the committed docs are exactly what the generator writes.
  `boolean_rsolidlist` had no doc at all.
- Skill API docs of `NotebookRun`, `run_notebook` and `add_bspline_rsketch` caught up with the
  code (`through`, `product` and `timeout`; a partial run's `product` is `None`; closed
  B-splines).

## 2.2.6.post1 — 2026-10-21

### Fixed

- Editor: the parameter panel reads `scad.var(name="j1", default=0.0, ...)` — the keyword
  form — as well as `scad.var("j1", 0.0, ...)`. Before, only the second positional argument
  was taken as the default, so keyword declarations never showed up as parameters.
- Add-ons: `[compat] sca` ranges and the add-on commands accept a post-release version such as
  `2.2.6.post1` (it sorts after `2.2.6` and before `2.2.7`); the parser rejected it.

### Changed

Cache and runtime speed, measured on the desktop six-axis arm (cold 80.5 s to 34.6 s, no
change 23.6 s to 4.0 s, one joint edited 18.2 s to 3.0 s, cache 1.7 GB to 96 MB):

- Restoring a cached shape is cheaper: adding a child to a shape no longer refreshes its
  whole subtree's tag cache unless a tag can pass down, and a restore finds entities by
  position and refreshes each tag cache once. A restored shape is then built when something
  first uses it, so a cached value that no running cell reads is never built; pickling it
  again hands back what it was restored from.
- The cell cache stores less and compresses it: no values for a cell's private (`_name`)
  variables, geometry bytes and cache entries zlib-compressed (level 1). Entries written
  before are still read.
- `scad.var(...)` values and the expressions made from them are keyed by content, so a cell
  that reads one parameter is no longer redone because another one, defined in the same cell,
  changed (marimo keyed any object it cannot hash by the code of the cell that made it).
- A cell that does `from lib.dims import A` depends on the definition of `A` (and what it
  reads, across local modules), not on the whole file. A module the analysis cannot prove
  (calls or loops at top level, star imports, a name defined twice, a plain
  `import lib.dims`) still depends on the whole file.
- A cell that runs a notebook with `use("child.py")` (a literal path) is keyed by what that
  child is (its text, the modules it imports, the notebooks it uses in turn) instead of by
  everything a run recorded: editing one child redoes the cell that uses it and not those
  that use its siblings, and the editor kernel caches such cells too (it ran them live
  before). A path computed at run time still depends on what a run recorded.
- The `use` calls a cell is about to make (literal path; arguments made of values it reads,
  `float(...)`, `notebook_id()`) are started together in worker processes, which fill the
  notebooks' caches; the cell then finds them built. OpenCASCADE keeps the interpreter lock,
  so these are processes, not threads. `SCA_JOBS` sets how many (default: the smaller of 4
  and the cores; 1 turns it off). Workers are only started when the builds they take off the
  cell's hands are worth the seconds a worker takes to start (a notebook remembers how long
  it last took to build), and a notebook that has not changed since it last ran is not
  started at all. A notebook's state directory is locked between processes while it runs.
- Editor: a slider drag is sent when it pauses (250 ms) or ends, not step by step; clicks and
  number-box commits still go at once.

## 2.2.6 — 2026-10-19

### Added

- Editor: `sca cell open NOTEBOOK` switches the running editor to another notebook of the
  workspace and waits for its kernel, so the following `sca cell` writes go through instead
  of refusing. The write commands take `--open` to switch and write in one step
  (`--wait`, or `SCA_EDITOR_OPEN_WAIT`, raises the boot wait; default 120s). `/api/cells`
  reports `kernel` so a caller can tell a booted notebook from one still opening.
- Editor: `sca viewport [WORKSPACE] [--out PATH]` reports where the viewport image lives
  (path, age, size) and copies it out, instead of reading `.sca-editor/viewport.png` by hand.

### Changed

- Cache: `cryptography` ships as a dependency, so the notebook cache keeps marimo's
  manifest signing and verification on instead of silently degrading to unsigned,
  unverified entries (the "LazyLoader verification='on' degraded to 'off'" warning).
- Editor: a refused write now names `sca cell open NOTEBOOK` (or `--open`) as the way out,
  and the bundled skill's editor-collaboration reference says so.

## 2.2.5 — 2026-10-15

### Fixed

- Editor: `sca cell` finds the editor through a container's proxy environment: the recorded
  url is always the loopback (`--host 0.0.0.0` included), the health check and the editor
  calls bypass `http_proxy`, and a record whose server does not answer is an error naming
  the record and the url instead of a silent "no editor is running". A record whose pid is
  gone reports the stale record and the remedy. A fallback to reading the file says so on
  stderr.

### Added

- Run: `sca run --through N` runs the first N cells only (a stage, numbered the way the
  editor numbers cells), `--no-product` runs a work-in-progress notebook that has no product
  yet, and `--timeout SECONDS` fails a run that takes longer (off by default).
- Editor: a failing or blocked cell's report names its upstream cells (failing ones first),
  with marimo's own dependency semantics.

### Changed

- Editor: `sca cell put/insert/run` report the console output and every cell left unhealthy
  by the change, and the dependents a write made stale are run, not left stale. A write whose
  rerun outlives the call says the edit was applied and names `sca cell ls`
  (`SCA_EDITOR_CALL_TIMEOUT` raises the wait, default 300s).
- Inspect: printing a `BRepInspection` shows a one-line summary; the full record is
  `to_dict()` / `.faces` / `.edges`.
- Runs are quieter: the cache loaders' degraded-state warnings no longer print at WARNING,
  and the render paths switch VTK's warning display off process-wide (this also hides VTK
  chatter from code run in the same process); a real failure is still raised and named.
- Skill: while an editor runs, `sca cell` is the only way to change a regular cell; `dof=0`
  says the constraint system closed, not that the shape is right (mirror solutions); modeling
  projects are version-controlled with git.

## 2.2.4 — 2026-10-15

### Fixed

- Editor: a failed publish is reported again on every run someone asked for — a page rerun, an
  agent `sca cell` command, a change to the notebook file, a module reload, a parameter commit —
  so the page's "building the model" veil lifts with the reason instead of waiting out its
  fallback. The once-per-identical-message dedup stays for the parameter burst. A page that
  connects after the failure is told the last error at the end of the connection handshake.

### Changed

- Editor: the header's button that opened the raw marimo editor is gone.
- Skill: the editor docs state which notebooks the workspace scan lists — subfolders of any
  depth are scanned; names starting with `.` or `_` and `node_modules`, `venv`, `site-packages`,
  `build`, `dist` are skipped.

## 2.2.3 — 2026-10-14

### Added

- Editor: `sca cell ls|get|put|insert|rm|run` edits the open notebook's cells through the
  running editor (found by `<workspace>/.sca-editor/server.json`): the page shows the change live,
  with no reload, the cell runs, and the command prints its status, errors and output. `sca new
  NAME [--kind part|assembly]` writes a notebook the editor then lists, leaving the person's view
  alone. The routes behind them are `GET /api/cells` and `POST /api/cells/{edit,insert,delete,run}`.
- Editor: a change to the open notebook's file made by someone else (an agent) is noticed
  within a second and applied cell by cell (edited cells are updated and run again, added or
  removed cells appear or go), without a reload; a changed setup or `@app.function` cell restarts
  the kernel. Notebooks added to or removed from the workspace appear in the list by themselves.

### Fixed

- Editor: an edit made in the editor no longer writes over what an agent saved to the same
  notebook file. If a cell was edited in both places, the file's version is kept and the
  editor's unsaved text goes to the log.

## 2.2.2 — 2026-10-14

### Added

- Editor: code completion from the SDK itself. `scad.` (and `scad.ql.`, `scad.std.gear.`, `ql.`)
  lists the real functions with their signatures and docstrings; accepting one, or typing `(`
  after a known name, writes the call with every required parameter as `name=` and Tab moves
  between them; inside a call the parameters not given yet complete as `name=` (required first).
  The names come from the running package (`GET /api/sdk`), so they cannot drift from the code.
- Editor: a **new** action in the workspace tab starts a notebook from the SDK's template (a part,
  or an assembly that uses the first two parts of the workspace), with the name checked as you
  type. An empty workspace opens on that form, so `sca edit` on an empty directory is usable.

### Fixed

- Editor: the cell editors rebuilt their configuration on every render (a new `onChange` and
  `basicSetup` each time), which dropped any snippet in progress and could disturb typing; both
  are stable now.

## 2.2.1 — 2026-10-13

The first stable release of the 2.2 line (2.2.0b1 was a pre-release): everything
below was added since 2.1.4, the notebook runtime of 2.2.0b1 included.

### Removed

- Re-Studio, the reverse-engineering studio (the `Re-mode` workspace of the
  standalone sca-web-editor), and its skill workflow
  `reverse-engineering-studio.md`. `sca edit` replaces the standalone editor;
  STEP reconstruction continues through the inspection API and the
  `step-reconstruction` workflow.

### Added

- Modeling: `scale`, affine `transform`, signed `offset`, `draft`, tapered and
  until-limited extrusions and multisection sweeps are recorded features, and
  boolean results can keep every output of a set operation; graph nodes keep
  ordered input references so a replay selects the same entities.
- `tools/research/build123dftc`: an execution-based build123d to FTC converter
  (isolated tracing, exact profile reconstruction, generated notebooks and
  assemblies) with independent geometry and STEP acceptance. It is research
  tooling, not part of the installed package.
- Editor: light mode. The editor follows the system theme and a button in the
  header cycles system, light and dark (remembered); the 3D viewport, edges,
  grid, axes and the code editor switch with it, in place, without reloading
  the model or losing the camera and selection.
- `sca edit [WORKSPACE]`: the web editor, now part of the SDK
  (`simplecadapi.editor`, UI sources in `editor-web/`; needs the `editor`
  extra). It runs a workspace's notebooks in a marimo kernel with the SDK's
  own cell executor, so the editor, `sca run` and `run_notebook` share one
  runtime, and marimo's dataflow decides what a parameter change reruns.
- Editor: picking in the viewport writes a selection cell of `scad.ql`
  selectors (`selected_<kind>[_<i>]`, `selected_item`); edits autosave to the
  notebook file; `sca snapshot` and `.sca-editor/snapshot.json` + `viewport.png`
  tell a coding agent what is selected and shown. Ground grid and axis gizmo in
  a Z-up CAD frame; cells fold to their step name and can run all cells above.
- Editor: a log dock along the bottom replaces the error line in the header.
  It lists what happened and what failed (with the time), and while cells are
  re-evaluated shows how many of them are done, which one is running and for
  how long; each cell shows running/queued/blocked. A module that does not
  compile is reported as the cause ("setup failed — SyntaxError ...").
- Editor: models reach the viewport as a live preview straight from the
  solids (`simplecadapi.scene.preview`, wire format `SCAPREV1`), without
  building a package; a picked entity's details are fetched on demand.
  Solids no longer carry an eagerly built mesh (modeling is about 20% faster).
- Editor: the local modules a notebook imports (shared dimensions, helpers)
  are listed in the workspace, with the notebooks that use them, and open in a
  module view: source (autosaved) plus the dataclass fields (and top-level
  constants with a `# ui:` comment) as parameter controls. Editing a module,
  there or on disk, reloads it in the kernel and reruns the open notebook; the
  notebooks it `use`s are rerun from their files. `sca ls` reports each
  notebook's modules.
- Notebook parameters: the numbers, bools and `scad.var`s of a
  `# ---- params ----` cell are discoverable (`sca params`,
  `simplecadapi.runtime.params.list_parameters`) with an optional trailing
  `# ui: slider(min, max, step=, unit=, label=)` comment to pick the control.
  Existing notebooks need no change.
- `sca ls [DIR]` lists the SimpleCAD notebooks under a directory (id, part or
  assembly, the notebooks each uses); `simplecadapi.runtime.workspace` also
  parses `# ---- feature: ... ----` headers.
- `simplecadapi.runtime.live`: project the running kernel's product to a
  `.scadpkg` (`live_package`, `publish_live`).

- Editor: a cell's run button is a stop button while the kernel runs the cell (the header's run-all too);
  stopping interrupts the kernel. Switching back to a notebook shows its last model and cells at once
  when nothing it depends on changed (the editor remembers each notebook's last published package,
  keyed by a digest of its files), while the kernel boots.

### Changed

- Volumes and centres of mass integrate NURBS by knot spans (Gauss-Kronrod)
  instead of the fixed-order routine: exact for rational patches (a sewn
  80 mm cube measures 512000 mm3, the old routine overshot by ~19 mm3) and
  safe on affine-transformed trims. A degenerate blend result now measures 0
  and is still reported as `BlendVolumeViolation`.
- The cell cache is per cell: an entry is stored under a digest of the local
  modules, child notebooks and input files *that cell* depends on (and what the
  cells it reads from depend on), no longer one digest for the whole notebook. A
  changed module recomputes the cells that read it and restores the rest; going
  back to an earlier value restores everything. The editor kernel uses the same
  cache. `sca run` reports the same cell statuses; caches written by earlier
  versions are ignored and removed.
- Building a package is about twice as fast: the render mesh of a face is
  computed with numpy in the profile's fixed operation order (the bytes, and so
  every content hash, are unchanged).
- Editor: parameters of local modules and `inputs` data files are watched.

### Fixed

- Editor: switching notebooks quickly no longer ends on the wrong one or
  reports `open failed: Connection refused`: opens are ordered, a superseded
  open stops its kernel quietly, and the list highlights the notebook being
  opened at once. A kernel for a notebook with inline dependencies no longer
  waits for marimo's sandbox prompt ("marimo not ready after 60s"); opening a
  notebook no longer publishes its model before its cells ran; a page
  refreshed after an unchanged publish shows the model; the viewport redraws
  after a panel resize; edges stay visible where a coarse mesh would hide them.
- `ql.vertices()` resolves through solids, faces and wires (it found nothing
  unless the scope was an edge).
- The editor no longer rewrites a notebook when a cell is run unchanged, and
  keeps `return` statements inside the functions a cell defines.
- The notebook executor no longer fails on cells that are not part of the
  notebook (the editor's scratch cell raised `KeyError`).

### Changed

- pymupdf is no longer a default-install dependency: it is optional under
  the new `drawing` extra. The engineering-drawing family is the only user:
  vector-PDF drawing inspection, and DXF -> PNG rendering (via ezdxf's
  drawing backend). `import simplecadapi`, modeling, STEP export, and VTK
  rendering all work without it. Drawing functions without pymupdf raise an
  ImportError naming the extra: `pip install 'simplecadapi[drawing]'`.

## 2.1.3 — 2026-09-18

The addon ecosystem leaves the beta line: one stable `sca` CLI, addon
runtime state that survives updates, structured error guidance, and a
wheel that ships the Agent Skill source for installation on any machine.

### Added

- `sca skill targets|install` (#4): compile the bundled Agent Skill for a
  harness target and install it into the skills directory. The wheel
  ships the uncompiled skill source tree (`docs/skill` +
  `skillproj.toml`) and compilation happens at install time, so pip
  users no longer need a repository checkout. `install` resolves the
  destination through the addon config/env chain (default
  `~/.agents/skills`, no `sca init` required), refuses to overwrite an
  existing directory, and `--force` only permits replacing a directory
  whose `SKILL.md` declares the same skill name.
- Addon runtime state outside the payload (#3): provisioned environments
  and caches live under `~/.sca/runtimes/<name>`, survive addon updates,
  and are removed with the addon; the `{runtime_dir}` placeholder now
  resolves in both `command_prefix` and `check_cmd`. New
  `sca addon check [name]` re-probes a runtime immediately and refreshes
  the cached registry state.
- Addon v2 standard (#2): the repository name, the descriptor, and the
  skill frontmatter must share one name; `[runtime].command_prefix`
  (with `{addon_dir}` / `{runtime_dir}` placeholders) is prepended to
  commands; new `sca addon use <name> <cmd>` runs a command inside the
  addon's declared environment.
- `sca init` (#2): creates the addon home and wires a `sca` shim plus a
  PATH block into new shells (`--no-shell` skips the wiring).
- Error guidance overhaul (#1): all SDK exceptions share one
  `SimpleCADError` root, and failures across sketch solve, assembly
  solve, boolean, blend, sweep/loft, and QL selection report structured,
  measured, repairable diagnostics with evidence rendering (edge
  highlights, four-iso views); zero-hit highlight guards name the tags
  that are actually available.

### Changed

- One command line: the historical `simplecad-cache` /
  `simplecad-export` entry points are gone; the same commands live under
  `sca cache` and `sca export` (#2).

### Fixed

- Diagnostic evidence rendering no longer crashes the process or vanishes
  silently: GL work is kept out of the failure path's render thread (the
  crash-isolated worker subprocess is used on every platform there), a
  render that cannot finish within its budget is reported as a named
  `render-unavailable` evidence entry instead of silently missing, and the
  budget is tunable via `SCA_DIAGNOSTIC_RENDER_BUDGET` (tests use 60 s; the
  agent-facing default stays 15 s).
- Windows build blockers: binary file opens, guarded directory fsync,
  and evidence-based stale-lock handling.
- Translator: unified geometry signatures and SolidWorks 2023 support.

## 2.1.2 — 2026-09-10

Script-anchored part cache: the `@scad.part` / `@scad.assemble` anchor is
the builder's source directory (`.simplecad/` beside the script); no
`pyproject.toml` required for standalone scripts. histjson emitter
keyword-only arguments. See [2.1.2 update notes](docs/updates/2.1.2.md).

## 2.1.1 — 2026-09-09

Tooling patch; the SDK public API is unchanged. See
[2.1.1 update notes](docs/updates/2.1.1.md).

## 2.1.0 — 2026-09-07

The SDK becomes an agent-first CAD toolkit: the QL selection language,
persistent tagging, durable `.scadpkg` product packages, standard parts,
multi-backend translation (FreeCAD, SolidWorks, Fusion), and the Agent
Skill. See [2.1.0 update notes](docs/updates/2.1.0.md).
