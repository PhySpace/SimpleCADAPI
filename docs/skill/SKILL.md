---
name: simplecadapi
description: Build, assemble, inspect, reconstruct, and export parametric CAD models with the SimpleCADAPI Python SDK. Use for SimpleCAD geometry modeling, constrained sketches, parts and assemblies, standard gears and bearings, STEP/BREP inspection and reconstruction, vector-PDF drawing reconstruction, durable product packages, model JSON replay, and CAD backend translation.
license: Apache-2.0
metadata:
  project: simplecadapi
  version: 2.1.3
  package-name: simplecadapi
  package-version: 2.1.3
---

# SimpleCAD SDK Skill

This file is the router: it owns load order, route selection, and
execution discipline only. Each selected workflow owns its procedure.
Classify the request, load exactly one workflow, follow its domain and
discipline references, and read exact API pages for the APIs its steps
use.

## Mandatory load order

Paths are relative to this file's directory.

1. Read this file.
2. Select exactly one workflow from Task routing. If two rows
   plausibly match, ask one discriminator question that names the
   candidate outcomes; never pick silently between routes with
   different deliverables.
3. Read the selected workflow in full. From selection on, it owns the
   procedure; do not load another workflow's procedure.
4. Load each required domain/discipline file the workflow names
   before the step that uses it; optional ones only when their
   trigger fires.
5. Before the first call of any API, read its exact page
   (`references/docs/api/<name>.md`, `references/docs/stdlib/<name>.md`,
   `references/docs/core/<type>.md`). A method absent from its page
   does not exist, however plausible it looks.

- You MUST NOT read the full API or stdlib index up front; the workflow
  names every page its steps need.
- Routing questions are decided here; after selection the workflow owns
  execution. You MUST always follow the global rules and execution
  discipline below.
- Questions about an existing STEP file that change nothing enter no
  workflow; you MUST use `references/domains/step-inspection.md` for them
  directly.
- Creating, installing, updating, or removing a SimpleCADAPI addon (a
  third-party skill+tooling package around `.scadpkg`) enters no
  workflow; you MUST use `references/domains/addon-development.md`
  directly.

## Task routing

Read exactly one workflow first, per the user's goal:

| User goal | Workflow |
| --- | --- |
| Model one physical part | `references/workflows/single-part-modeling.md` |
| Multi-part product or mechanism (custom parts, stdlib gears/bearings, connectors, constraints, package) | `references/workflows/assembly-product-build.md` |
| Rebuild an editable model from a STEP file | `references/workflows/step-reconstruction.md` |
| Export/translate a validated package | `references/workflows/export-and-translation.md` |
| Produce a GB engineering drawing (DXF) from validated geometry | `references/workflows/engineering-drawing.md` |
| Rebuild a 3D model from a vector-PDF engineering drawing | `references/workflows/drawing-reconstruction.md` |

Do not present route-choice menus when a row already matches: profile,
strategy, and tool choices inside a route belong to that workflow's
own gates, not to an up-front question. A missing prerequisite — state
it and stop that route; never invent an alternative route.

## Routing discipline

| Rule | Behavior |
| --- | --- |
| One lifecycle per request | Every task enters exactly one workflow; domains, disciplines, and guides refine it and are never competing routes |
| Deterministic selection | When the matrix matches, proceed without asking a route question |
| Ambiguous request | Ask one discriminator question naming the candidate deliverables (editable model vs inspection evidence vs export package), then route |
| Missing prerequisite | Name what is missing and stop that route |
| Explicit user override | Honor it only when the target route's scope actually covers the request |

## Global rules (every task)

1. Refine the requirement into a brief before modeling
   (`references/domains/requirement-refinement.md`).
2. Use keyword arguments for every documented public API and
   stdlib function, except the canonical durable export call
   `capture(result, path)`, whose two required arguments are
   positional.
3. Every model is a marimo notebook with a `[tool.simplecadapi]`
   header (`references/docs/guides/notebook-runtime.md`): one part
   per notebook; one assembly notebook per product, composing
   children with `scad.use(...)`; parameters live in the notebook
   that consumes them; exposed tunable parameters are `var()`/`Var`
   declarations (optionally with `unit`, `tolerance`). Part sources
   follow the Feature Tree Convention
   (`references/discipline/feature-tree-convention.md`): block
   structure `sketch → basic body op → bool → modifier`, one
   feature per block and one block per cell, with a mandatory
   boundary comment `# ---- feature: <slug> (<role>) ----`; 2D
   profiles and planar paths go through the sketch API, primitives
   only when the shape is completely contained in the basic form.
4. Booleans (`union_rsolid`, `cut_rsolid`, `intersect_rsolid`)
   accept mixed inputs and return exactly one `Solid`; union
   defaults to `glue=False` with a conservative scale-relative
   tolerance and fails explicitly when it cannot produce one
   merged solid.
5. Build and validate incrementally: each major step prints small
   QL-derived facts; grounding uses QL wherever possible; never
   print whole solids or full model objects.
6. Topology enumeration is QL-only and strictly enforced: plural
   getters (`get_edges`, `get_faces`, `get_wires`, `get_vertices`,
   `get_solids`, `get_inner_wires`) accept ONLY an index — the
   no-argument list form raises. Enumerate, count, and measure via
   `ql.<kind>().resolve(shape)`; filter with QL predicates plus
   `take`/`exactly` cardinality; never build selections by looping
   over an enumerated list and indexing it. Indexed picks
   (`get_edges(index)`) are reserved for intentional, named choices
   and are recorded as graph selection nodes.
7. Tags: attach with `apply_tag(shape=..., tag=...)` (LOCAL scope —
   it never propagates downward); inspect with
   `list_tags(shape=...)`; keep numeric facts in metadata, never in
   tags.
8. The notebook file is the only source of truth; `.scadpkg` is
   generated from it for exchange and publishing (`sca run
   product.py --out out/product.scadpkg`, or
   `capture(result, "out/product.scadpkg")` in one call) and is
   never read back as a source. `@scad.part` / `@scad.assemble`
   are for reusable library parts in plain modules; they may be
   called inside a notebook cell.
9. `simplecadapi.inspect.brep` and `simplecadapi.inspect.drawing` are
   diagnostic-only and rejected inside `GraphSession`; obtain/export
   geometry first, inspect outside.
10. Standard parts first: before hand-modeling a gear, ring gear,
    rack, cycloidal disc, or bearing, check `scad.std.gear` /
    `scad.std.bearing`.
11. Read `references/docs/guides/notebook-runtime.md` in full
    before writing a notebook, composing notebooks, or reasoning
    about the cell cache. Run models with `sca run`; never enable
    marimo's `[tool.marimo.runtime] cache_cells` in the editor, and
    never commit the generated `__marimo__/` directory.

## Boundaries

- `.scadpkg` is the canonical durable product; STL/OBJ/MJCF are
  point-in-time exports, never editable sources.
- Model JSON is the replay/interchange contract for explicit
  `GraphSession` flows; never hand-author payloads.
- No claims of strength, fatigue, thermal, vibration, tolerance
  compliance, or regulatory fitness without the corresponding
  analysis actually run.

## Execution discipline (every task)

1. Gates bind artifacts: a validation gate passes only when its named
   artifact exists — printed QL facts, targeted measurements, named
   rendered views, completed brief fields. A stated feeling of success
   is not a gate result.
2. Blocking waits: an Ask-or-Record blocking item resolves before any
   geometry — asked once (batched into one question set) or recorded
   as an explicit assumption. Proceeding with neither is the failure,
   not the asking.
3. Serial phases: do not preload later-phase pages or build
   later-phase artifacts early. After an interruption, re-ground from
   the owning artifact (source file, brief), not from conversation
   memory.
4. Repair the owning source: the named parameter, the brief field, or
   the upstream selection — never the downstream symptom.
   Candidate x parameter enumeration loops are diagnosis debt, not
   repair (`references/discipline/failure-and-repair.md`).
5. A failed check closes by changing the design or by redefining the
   check with the user — never by weakening or deleting the check.

## Example SDK usage

```python
import simplecadapi as scad
from simplecadapi import GraphSession, export_model_json, replay_model_json

with GraphSession(graph_id="box") as session:
    shape = scad.make_box_rsolid(width=10.0, height=20.0, depth=30.0)
    session.capture_result(value=shape)
    payload = export_model_json(session=session)

rebuilt = replay_model_json(json_str=payload)
print(len(rebuilt))
```

## References

- `references/README.md` — skill layer structure
- `references/workflows/` — goal-oriented workflows, including drawing reconstruction
- `references/domains/` — capability domains, including drawing inspection
- `references/discipline/` — modeling knowledge and invariants
- `references/SDK_OVERVIEW.md` — package-level map
- `references/inspect/brep-reverse-engineering.md`
- `references/domains/addon-development.md` — `sca` addon CLI and authoring guide
- `references/docs/guides/reconstruction-agent-test-prompt.md`
- `references/docs/guides/reconstruction-agent-strategy.md`
- `references/docs/guides/notebook-runtime.md`
- `references/ql-playbook.md`
- `references/scadpkg-format.md` — `.scadpkg` consumer spec: member
  layout, tag channel, minimal readers (addon exporters read this)
- `references/docs/api/`, `references/docs/stdlib/`, `references/docs/core/`
