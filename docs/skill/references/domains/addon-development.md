# Task Domain: Addon Development

Author, install, and manage SimpleCADAPI addons: third-party packages that
add non-modeling capabilities — simulation, analysis, downstream tooling —
by consuming `.scadpkg` product packages.

## Use when

- Creating or publishing an addon (a repository with `sca-addon.toml` and
  a skill directory).
- Installing, updating, or removing an addon with the `sca` CLI.
- Deciding whether a capability belongs in an addon or in the SDK.

## Boundary: addon vs SDK contribution

| Capability | Belongs in |
| --- | --- |
| Geometry modeling, domain modeling operations, anything that must build BRep inside a session | SimpleCADAPI core (optionally as an extra, e.g. `simplecadapi[fem]`) |
| Verification, analysis, simulation, rendering, export to foreign ecosystems, anything that *consumes* finished geometry | An addon |

An addon has two legal integration modes with the SDK.

**Recommended default — process boundary.** The addon consumes
`.scadpkg` files (members, tags channel, occurrence graph, scene
projection; units are millimeters) and whatever host tooling it needs,
in any language. Dependency conflicts are structurally impossible and
non-Python addons are first-class.

**Allowed — in-process SDK use.** A Python addon may install
`simplecadapi` inside its own environment and import it: the builtin
exporters (STEP/STL/OBJ/MJCF, gmsh meshing) and the package readers
(`read_product_package`, `load_product_package`) exist for exactly this
kind of downstream consumer. The descriptor's `[compat] sca` range
governs which SDK releases that dependency may resolve to — declare
the SDK as a dependency of the addon environment and keep the range
honest.

What holds in both modes: the addon runs in its own environment and is
not installed into the environment that models the geometry — mixing
plugin dependencies into the modeling SDK environment is what the
separation exists to prevent.

## Repository layout

```text
<repo root>/
  sca-addon.toml      descriptor: machine-checked facts only, no prose
  skill/
    SKILL.md          everything an agent reads; installed as sca-<name>
    <supporting assets: scripts, references, templates...>
  <runtime code, binaries, docs — addon-owned>
```

One document per audience: the descriptor is read by the `sca` CLI, the
SKILL.md is read by agents. Never duplicate prose into the descriptor.

## Payload vs runtime state

An installed addon lives in two places:

- **Payload** — `<addon home>/<name>`: the repository contents, replaced
  wholesale on every install/update. Treat it as a pure function of the
  source; nothing provisioned by the user should live here.
- **Runtime state** — `<addon home>/../runtimes/<name>` (`~/.sca/runtimes/<name>`
  by default; a redirected `SCA_ADDON_HOME=/x/addons` keeps all state under
  `/x/runtimes`): created at install, addressed as `{runtime_dir}` in the
  descriptor, never touched by updates, removed with the addon.
  Provision virtualenvs and caches here.

The split is what makes `sca addon update` safe to run blindly: the
payload is re-fetched and swapped while provisioned runtime state (a
multi-hundred-MB venv, downloaded models) survives. As a legacy
compatibility shim, an update also preserves a pre-`{runtime_dir}`
`.venv` provisioned inside the payload itself.

## Descriptor reference (`sca-addon.toml`)

Validation is strict: unknown tables and keys are rejected, every
failure names the field and file.

| Field | Rule |
| --- | --- |
| `[addon] name` | lowercase slug `[a-z0-9][a-z0-9-]{0,63}`; becomes the install directory and skill prefix |
| `[addon] version` | dotted numeric with optional pre-release suffix (e.g. `0.3.1`, `2.0.4b2`) |
| `[addon] license` | non-empty; must be accurate — addons are redistributed |
| `[addon] skill_path` | relative POSIX-style directory containing `SKILL.md` |
| `[compat] sca` | version range, comma-separated clauses with `== != >= <= > <`; a bare version means exact match. Ranges, never pins: SDK releases within a range must not break addons. Pre-release suffixes sort before their release (`2.0.4b2 < 2.0.4`); missing trailing components pad with zero (`2.1` == `2.1.0`) |
| `[runtime] kind` | `binary` \| `python-env` \| `docker` \| `none` |
| `[runtime] platforms` | non-empty list, required for `binary`/`python-env`, forbidden for `none`/`docker` |
| `[runtime] check_cmd` | required for `binary`/`python-env`, optional for `docker`, forbidden for `none` |
| `[runtime] command_prefix` | optional shell prelude joined in front of every command the addon runs (see below); `{addon_dir}` resolves to the installed payload, `{runtime_dir}` to the addon's runtime-state directory; no other `{placeholder}` is allowed |
| `[runtime.check_overrides]` | optional per-platform command overrides; keys must be declared platforms |

Closed platform enum (additive across spec versions):

```text
macos-arm64 | macos-x86_64 | linux-x86_64 | linux-aarch64
| windows-x86_64 | windows-arm64
```

## Naming standard: one name everywhere

The addon name is a single identity enforced at install time:

- `[addon].name` == the repo name (the `repo` segment of an
  `owner/repo` GitHub source; for a local path, the basename of the git
  `origin` URL, falling back to the directory name);
- `[addon].name` == the SKILL.md frontmatter `name:`.

A mismatch is a hard install failure that names both sides. Skill
directories install as `sca-<name>` (no doubling when the name already
starts with `sca-`).

## Command prefix and `sca addon use`

An addon owns its runtime environment. `[runtime].command_prefix` is a
shell prelude — env assignments, `PATH` edits, a `cd` — prepended to
every command the addon runs:

```toml
[runtime]
kind = "python-env"
command_prefix = "PATH=\"{runtime_dir}/.venv/bin:$PATH\""
check_cmd = "{runtime_dir}/.venv/bin/python -c 'import mytool'"
```

- Two placeholders resolve in the prefix and in `check_cmd`:
  `{addon_dir}` (the installed payload) and `{runtime_dir}` (the addon's
  runtime-state directory — provision venvs there, never inside the
  payload; see "Payload vs runtime state").
- `sca addon use <name> <cmd...>` resolves the installed addon by name,
  joins prefix + command, and executes it via the shell with
  `SCA_ADDON_DIR` and `SCA_RUNTIME_DIR` exported (provisioning scripts
  can self-locate); the exit code propagates. `--capture` returns output
  in the report instead of streaming it. Without a command, `sca addon
  use <name>` reports the prefix and both directories.
- `check_cmd` runs through the same prefix, so a probe like
  `python -c 'import mytool'` automatically tests the addon's own
  interpreter. The probe executes after the payload is committed, in
  the final installed layout; a failing probe stays a loud warning,
  never an install blocker.

## `check_cmd` contract

A runtime probe must be fast but meaningful:

1. Exit code `0` means usable; any other exit or a missing command means
   not usable.
2. Execution shell is pinned by the spec: `sh -c` on Unix, `cmd /c` on
   Windows — write the command accordingly.
3. Completes in about two seconds; no network access, no license
   checkout, no GUI launch.
4. A failing probe warns loudly at install time but never blocks the
   install — the runtime can be installed afterwards. Re-run it before
   first use.

The install/update-time probe is a **cache, not truth**: it records the
state of the machine at that moment, which is usually *before* the
runtime was provisioned. `sca addon list` shows the cached state with
its timestamp (`ok (cached ...)`); `sca addon check <name>` (or
`sca addon check` for every installed addon) re-probes the installed
layout NOW, refreshes the registry record, and is the answer to "is the
runtime usable right now?".

## Addon SKILL.md requirements

The skill is the addon's single agent-facing document:

- **Frontmatter `description` is the routing card.** Hosts surface it to
  agents verbatim; state the trigger condition, what the addon consumes
  from `.scadpkg` (which members, which tag patterns such as
  `interface.*`), and what it produces.
- **Pre-check the runtime.** Run the probe (the descriptor's
  `check_cmd`) before first use; on failure, name the missing runtime
  and stop — never silently skip the analysis.
- **Declare the consumption contract.** Units are millimeters; state
  coordinate-system assumptions and required tags explicitly.
- **Never modify geometry.** An addon analyzes, verifies, or transforms
  finished packages; when a task needs geometry changes, return to the
  SimpleCADAPI modeling workflows and re-capture.
- **Reference the main skill.** Describe the pipeline end to end:
  model with SimpleCADAPI → `capture` a `.scadpkg` → this addon
  consumes it.

## Reading a `.scadpkg`

The complete consumer-facing format spec — member layout, manifest
fields, the `interface.*` tag channel, and two verified minimal
readers (in-process SDK and pure ZIP+JSON for any language) — lives in
`references/scadpkg-format.md`. Point your addon's agent at that page:
it is written so that an agent given the document alone can produce a
correct parser or exporter for the inputs your addon declares. Mirror
this pointer in your addon's SKILL.md (the page ships inside the
SimpleCADAPI skill; the normative JSON Schemas also ship inside the
`simplecadapi` wheel at `simplecadapi/contracts/` for environments
without the skill).

Consumer rules that hold regardless of path:

- resolve members through the manifest by `sha256`, never by guessing
  names or extensions;
- treat missing `interface.*` names as loud failures naming the exact
  name — never approximate by geometry;
- verify `schema_version` major before parsing anything else.

## Installing and managing addons

```bash
sca init                           # once per machine: home + registry + config
sca addon add owner/repo           # install from GitHub (default branch)
sca addon add owner/repo@v1.2.0    # pin a tag or commit for reproducibility
sca addon add ./my-addon           # install a local checkout (test before publishing)
sca addon update [name]            # re-fetch one addon or all (payload swapped; runtime state survives)
sca addon check [name]             # re-probe the runtime NOW and refresh the cached state
sca addon remove name
sca addon list                     # registry contents + on-disk drift + cached runtime state
```

- Locations resolve as flag > environment variable (`SCA_ADDON_HOME`,
  `SCA_SKILLS_DIR`) > `~/.sca/config.toml` > defaults
  (`~/.sca/addons`, `~/.agents/skills`).
- Skills install as `sca-<name>` inside the skills directory — copied,
  never symlinked. A non-registry directory of that name is never
  overwritten.
- GitHub sources fetch as tarballs (no git binary needed, byte-exact
  files); `--method clone` is the escape hatch for private
  repositories.

### Shell integration (`sca init`)

`sca` is the single CLI for the whole SDK (`sca addon …`, `sca run …`,
`sca export …`), and `sca init` makes it resolve in any new shell —
interactive or scripted, on any of the supported platforms:

- a shim `~/.sca/bin/sca` (Windows: `sca.cmd`) execs the real console
  script of the install that ran `sca init`; the venv's own `bin` is
  never put on PATH;
- that directory lands on PATH via a marked, removable
  `# >>> sca shell integration >>>` block: `~/.zshenv` for zsh (read by
  non-interactive shells too, so agents see the command), `~/.bashrc`
  for bash, `~/.config/fish/conf.d/sca-path.fish` for fish; on Windows
  the user-scope `PATH` registry value is updated and refreshed.
- rc files are only created for the login shell or when they already
  exist — no dotfiles are planted for shells that are not in use;
  `--no-shell` skips the step; re-running `sca init` refreshes the shim
  after the install moves. Removing the block(s) and `~/.sca/bin`
  uninstalls the wiring.

### Hard failures vs warnings

| Outcome | Behavior |
| --- | --- |
| Descriptor invalid, `[compat] sca` mismatch, platform unsupported, name collision, foreign skill directory | install aborts, naming the exact cause |
| `check_cmd` fails, update downgrades | loud warning; install/update proceeds |
| Registry vs disk drift (missing directories) | surfaced by `sca addon list` as `DRIFT` lines |

## Publishing checklist

1. `sca addon add ./repo` from a local checkout; confirm the summary
   and that the skill lands under `sca-<name>`.
2. `sca addon list` shows no drift; the runtime probe passes on every
   declared platform you can test.
3. Tag the release; users pin with `owner/repo@<tag>`.
4. Bump `[addon] version` for every published change; widen
   `[compat] sca` only after testing against the new SDK release.
