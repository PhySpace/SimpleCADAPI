---
name: simplecadapi
description: Build, assemble, inspect, reconstruct, and export parametric CAD models with the SimpleCADAPI Python SDK. Use for SimpleCAD geometry modeling, constrained sketches, parts and assemblies, standard gears and bearings, STEP/BREP inspection and reconstruction, mesh or image based reconstruction, vector-PDF drawing reconstruction, durable product packages, model JSON replay, and CAD backend translation.
license: Apache-2.0
metadata:
  project: simplecadapi
  version: 2.2.9
  package-name: simplecadapi
  package-version: 2.2.9
---

# SimpleCAD SDK Skill

This file is the router. Pick the route, read its batch, work. Paths are relative to this file's directory.

## Start here

1. **Decide the mode** (`references/discipline/operating-modes.md`): interactive (a person can answer) or unattended (nobody
   will). Write `Mode: ...` as the first line of the brief. The mode changes who decides, never what is checked.
2. **Pick one route** from the table. Do not ask a route question when a row matches; if two rows plausibly match, ask one
   question naming the candidate deliverables (unattended: take the row whose deliverable the request names, record the choice).
3. **Read the whole batch of that row at once**, plus the two always-read pages `references/discipline/core-rules.md` and
   `references/discipline/operating-modes.md`. Then work; the workflow's `Read when` table says when to read anything else.
4. Before the first call of an API, read its page (`references/docs/api|stdlib|core/<name>.md`) in the same batch as the
   other pages of that step. A method absent from its page does not exist. Never read the whole index.

## Reading in parallel

Reading is cheap when it is one request and expensive when it is ten. Ask for a whole batch together.

<!-- skill:if claudecode,zcode -->
Issue every `Read` call of the batch in one message, so the harness runs them together. Do not read a file, think, then
read the next.
<!-- skill:endif -->
<!-- skill:if opencode -->
Issue every `read` call of the batch in one response, so the harness runs them together. Do not read a file, think, then
read the next.
<!-- skill:endif -->
<!-- skill:if codex -->
Print the whole batch with one shell command from this skill's directory, for example
`tail -n +1 references/discipline/core-rules.md references/discipline/operating-modes.md references/workflows/single-part-modeling.md`
(each file is preceded by a `==> name <==` line). One command, not one per file.
<!-- skill:endif -->
<!-- skill:if omp,dsh,kimicode -->
Request the whole batch together if your tools allow several reads in one step.
<!-- skill:endif -->

## Routes

Each row's batch is the workflow page plus its `Read now` set (the workflow page repeats it).

| You are asked to | Workflow | Read now |
| --- | --- | --- |
| Model one physical part | `references/workflows/single-part-modeling.md` | `references/workflows/single-part-modeling.md` `references/workflows/single-part-modeling/role-1-requirements.md` `references/workflows/single-part-modeling/requirements-template.md` `references/domains/requirement-refinement.md` `references/discipline/requirement-and-cad-brief.md` |
| Build a multi-part product or mechanism | `references/workflows/assembly-product-build.md` | `references/workflows/assembly-product-build.md` `references/domains/requirement-refinement.md` `references/domains/assembly-and-product.md` `references/discipline/assembly-positioning.md` |
| Rebuild an editable model from a STEP file | `references/workflows/step-reconstruction.md` | `references/workflows/step-reconstruction.md` `references/domains/step-inspection.md` `references/inspect/brep-reverse-engineering.md` |
| Rebuild a model from a mesh, point cloud or photos | `references/workflows/scan-reconstruction.md` | `references/workflows/scan-reconstruction.md` `references/domains/step-inspection.md` `references/domains/part-modeling.md` |
| Rebuild a model from a vector-PDF drawing | `references/workflows/drawing-reconstruction.md` | `references/workflows/drawing-reconstruction.md` `references/workflows/drawing-reconstruction/role-1-drawing-confirmer.md` `references/domains/drawing-inspection.md` `references/domains/requirement-refinement.md` |
| Produce a GB engineering drawing (DXF) from validated geometry | `references/workflows/engineering-drawing.md` | `references/workflows/engineering-drawing.md` `references/domains/engineering-drawing.md` `references/domains/requirement-refinement.md` |
| Export or translate a validated package | `references/workflows/export-and-translation.md` | `references/workflows/export-and-translation.md` `references/domains/export-and-translation.md` |

Routes without a workflow (no lifecycle, read the page and answer):

- A question about an existing STEP file that changes nothing: `references/domains/step-inspection.md`.
- A person has the editor open (`sca edit`) and talks about what they selected or tuned: keep the workflow you are in and
  read `references/domains/editor-collaboration.md` first. While the editor runs, `sca cell` is the only way to change a
  regular cell.
- Creating, installing, updating or removing an addon (`.scadpkg` skill + tooling): `references/domains/addon-development.md`.

An explicit request for a route is honoured only when that workflow's scope covers it.
A missing prerequisite (a file, a tool, an input): name it and stop that route; never invent another route. Unattended: record
it as a blocker in the report and do the strongest supported work.

## Always-on rules

`references/discipline/core-rules.md` has the full text with reasons; the IDs below are what reviews cite.

- **R2** keyword arguments for every documented API (except `capture(result, path)`).
- **R3** a model is a marimo notebook; cell boundaries and `var()` follow `references/discipline/notebook-cell-design.md`,
  blocks follow `references/discipline/feature-tree-convention.md`. Read both before writing a cell.
- **R6** topology is enumerated through QL only; plural getters take only an index (`references/ql-playbook.md`).
- **R13** an API not on its page does not exist.
- **P1** gates bind artifacts, not feelings. **P2** resolve blocking items before geometry (ask once, or record).
  **P5** repair the owner, not the symptom. **P6** a failed check closes by changing the design or redefining the check in
  the open, never by weakening it.
- No claim of strength, fatigue, thermal, vibration, tolerance or regulatory fitness without the analysis run.

## Where things are

- `references/README.md`: every page by layer (workflows, domains, discipline, guides, generated API docs).
- `references/SDK_OVERVIEW.md`: package map. `references/ql-playbook.md` and `references/ql-recipes.md`: selection.
- `references/scadpkg-format.md`: the `.scadpkg` consumer spec.
- `references/docs/api/`, `references/docs/stdlib/`, `references/docs/core/`: exact signatures. `sca ops [NAME] [--json]`
  lists every operation with what each parameter means (`length`, `angle`, `point3`, `direction3`, `color`, ... read
  from the signature types in `simplecadapi.types`; `simplecadapi.catalog` in code).
- Sketches and features off the base planes: a recorded workplane (`make_workplane_from_face_rworkplane`, `..._from_points_`,
  `..._from_axis_`, `..._midplane_`, `..._normal_to_curve_`), then `make_sketch_rsketch(plane=wp)` or `with wp:`. See
  `references/discipline/datums-and-coordinate-systems.md`.
- Colours and names for people: a body's colour, opacity and name are `set_body_appearance_rpart`; a face or edge name is
  a tag (`apply_tag_rselection`, `ql.tag`). See "Colours and names for people" in `references/domains/part-modeling.md`.
- Maintainers: the contract these pages follow is `skill-design.md` in the repository's `docs/` folder.
