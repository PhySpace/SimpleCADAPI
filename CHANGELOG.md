# Changelog

All notable changes to SimpleCADAPI are documented here. Per-version
user-facing notes live in [`docs/updates/`](docs/updates/) (English and
中文).

## Unreleased

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

- Editor: a **new** action in the workspace tab starts a notebook from the SDK's template (a part,
  or an assembly that uses the first two parts of the workspace), with the name checked as you
  type. An empty workspace opens on that form, so `sca edit` on an empty directory is usable.
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
