# Changelog

All notable changes to SimpleCADAPI are documented here. Per-version
user-facing notes live in [`docs/updates/`](docs/updates/) (English and
中文).

## Unreleased

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
