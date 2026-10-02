# Skill Documentation Structure

This directory is the task-routed skill layer. It sits between the SDK's
generated

```text
docs/skill/
  domains/       stable, reusable capability modules
  workflows/     goal-oriented compositions of domains
  discipline/    mechanical modeling knowledge and invariants
```

## Layering

```text
SKILL.md (router: load order, routing, execution discipline)
→ workflows/<scenario>.md        what to run, in what order
→ domains/<capability>.md        capability boundaries and API groups
→ discipline/<topic>.md          why: modeling reasoning and invariants
→ docs/api|stdlib|core/          exact signatures (auto-generated)
```

Load top-down and only what the current task triggers. No task reads the
whole API index up front.

## Domains

| Domain | Owns |
| --- | --- |
| `requirement-refinement` | request → brief (dimensions, units, datums, validation targets) |
| `part-modeling` | single-solid parts: primitives, profiles, features, booleans, transforms |
| `sketch-and-features` | declarative constrained sketches and promotion |
| `assembly-and-product` | parts, placements, connectors, constraints, notebooks and `scad.use`, @part/@assemble, `.scadpkg` |
| `standard-parts` | stdlib gears, ring gears, racks, cycloidal discs, bearings |
| `step-inspection` | STEP/BREP evidence, comparison, reconstruction evaluation |
| `drawing-inspection` | vector-PDF coordinates and dimensions, model-section measurements, independent evidence validation |
| `export-and-translation` | STEP/STL/OBJ/MJCF export, FreeCAD/Fusion/SolidWorks translation |
| `addon-development` | third-party addon authoring and management: `sca` CLI, `sca-addon.toml` descriptor, runtime probes, addon SKILL.md requirements |

Cross-cutting capabilities — QL grounding, semantic tags, GraphSession replay,
units/tolerances, incremental validation — are not routing targets; each
workflow pulls them in as conditions require. Verified QL selection patterns
for operation outputs (extrude-family slots, boolean seam curves, seam
fillets) live in `ql-playbook.md`. The `.scadpkg` consumer-facing format
spec (member layout, `interface.*` tag channel, minimal readers for addon
exporters) lives in `scadpkg-format.md`.

## Workflows

| Workflow | Scenario |
| --- | --- |
| `single-part-modeling` | one physical part from brief to validated solid — sketch tier by default, std parts first |
| `assembly-product-build` | multi-part product or mechanism with connectors/constraints and package capture; stdlib gears/bearings live here |
| `step-reconstruction` | editable rebuild from a target STEP with tiered acceptance |
| `drawing-reconstruction` | editable rebuild from vector-PDF dimensions with stage checks and independent drawing/model/output acceptance |
| `export-and-translation` | downstream formats from a validated package |

Each workflow states: goal/scope, task decomposition (required/optional
domains, artifacts, validation gates, repair routes), ordered steps with the
domain/discipline/API references to load, failure routes, and deliverables.
`single-part-modeling` is additionally **role-structured**: five roles
(requirement confirmer → master planner → verifier planner ⇄ detail modeling
planner & builder → exporter), with Roles 3 and 4 looping per stage before
the next stage is allowed. Each role owns a disk artifact and an exit gate;
per-harness host bindings (interactive ask, TODO/plan tool, REPL-or-script
hypothesis loop, mandatory isolated image review) are declared inside the
workflow file as conditional blocks compiled per target by
`tools/skillbuild.py` (targets declared in `skillproj.toml`).

## Discipline

Modeling reasoning and invariants, independent of any single API:
`mechanical-modeling` (construction strategy), `requirement-and-cad-brief`
(input precedence, drawings), `datums-and-coordinate-systems`,
`feature-ordering` (operation order and boolean tool geometry),
`assembly-positioning` (mating/motion intent), `geometric-validation`
(validity vs volume, incremental grounding, spec-driven measurement),
`failure-and-repair` (failure classes and the repair loop),
`manufacturing-boundaries` (defaults and what geometry never proves).

## Authoring rules

- Domain files say what a capability owns, when to use it, when to route
  elsewhere, and which API pages to read — they do not restate signatures.
- Workflow files compose domains; they never duplicate discipline content.
- Discipline files state reasoning and invariants; they avoid CLI- or
  tool-specific detail that belongs in domains/workflows.
- Every `references/...` path written here must exist in the packaged skill.
- Reading an API page is an action with an output: before the first
  call of any API, note its signature, return type, and documented
  failure modes — one line each in the working notes. A method name
  absent from the page does not exist, however plausible it looks.
  Non-SDK dependencies (Gmsh, CalculiX, VTK, FreeCAD scripting) are not
  covered by SDK pages: check their own documentation before the first
  call.
