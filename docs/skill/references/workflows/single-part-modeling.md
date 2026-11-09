# Workflow: Single-Part Modeling

Model one physical part from confirmed requirements to validated, optionally
packaged geometry. The workflow is role-structured. Roles 1 and 2 establish
the requirements and the stage plan; Roles 3 and 4 then run a strict,
stage-by-stage TDD loop; Role 5 exports only after every stage gate passes.


## Read now (one parallel batch)

| File | Why |
| --- | --- |
| `workflows/single-part-modeling/role-1-requirements.md` | Role 1 procedure and its gate: nothing is built before it closes |
| `workflows/single-part-modeling/requirements-template.md` | the `REQUIREMENTS.md` fields (with the `Mode:` line and the assumption ledger) |
| `domains/requirement-refinement.md` | brief format, Ask-or-Record blocking table, input precedence |
| `discipline/requirement-and-cad-brief.md` | evidence precedence, one-question rule, brief quality gate |

## Read when

| When | File |
| --- | --- |
| Role 1 is about to ask (interactive): designing the batched ask payload | `workflows/single-part-modeling/role-1-ask-bindings.md` |
| Role 1 is about to read a model or a drawing as input | `domains/step-inspection.md` / `domains/drawing-inspection.md` |
| Role 2 starts | `workflows/single-part-modeling/role-2-plan.md`, `discipline/mechanical-modeling.md`, `discipline/datums-and-coordinate-systems.md` |
| Role 3 starts a stage | `workflows/single-part-modeling/role-3-verifier.md`, `workflows/single-part-modeling/role-3-host-bindings.md`, `discipline/geometric-validation.md` |
| Role 3 selects the checks, or plans a visual review | `workflows/single-part-modeling/verifier-contract-patterns.md`, `discipline/verifier-scripts.md` |
| Role 4 starts a stage | `workflows/single-part-modeling/role-4-build.md`, `domains/part-modeling.md`, `discipline/feature-ordering.md` |
| Role 4 writes a notebook source | `discipline/feature-tree-convention.md`, `discipline/notebook-cell-design.md`, `docs/guides/notebook-runtime.md` |
| a stage's profiles are sketch tier | `domains/sketch-and-features.md` |
| the requirement is a standard part (gear, bearing, fastener) | `domains/standard-parts.md` |
| a mechanism mating several standard parts | `workflows/assembly-product-build.md` |
| Role 5 starts | `domains/export-and-translation.md`, `domains/assembly-and-product.md`, `docs/guides/product-export.md` |
| a check or a build keeps failing | `discipline/failure-and-repair.md` |

## Unattended mode

The mode is decided once, at the start (`discipline/operating-modes.md`), and written as the first line of
`REQUIREMENTS.md`. No gate is weakened: each one still binds an artifact. Only who decides changes.

| Interactive gate | Unattended replacement |
| --- | --- |
| "⛔ BLOCKING means stop": wait for the explicit user answer (standing discipline) | Never wait. The gate passes on an artifact: the filled brief plus a written decision paragraph. Never decide by feel |
| Role 1 ask round: shape interpretation confirmed, Ask-or-Record blocking items asked, recommended assumptions offered as ask options (Role 1 steps 1 and 2) | Record each item in the assumption ledger (`value / evidence / how to change it / the check that would show it wrong`). Shape-level facts are still described region by region and checked against the measured evidence first |
| Role 1 host ask bindings (`ask`, `question`, `AskUserQuestion`, plain-text message that stops and waits) | Skip `workflows/single-part-modeling/role-1-ask-bindings.md`. Nothing is asked and nothing is waited for |
| Role 1 exit gate "⛔ user consent received" | Self-review gate: re-read `REQUIREMENTS.md` against the request and the evidence, write one paragraph of decision with the open risks, go on only when every field is filled |
| Role 2 "plan presented" | The plan is `BUILD_PLAN.md` plus a short summary in the report. Two viable strategies: take the one that meets the requirements and is easier to change later, record the other in `BUILD_PLAN.md` |
| Role 3 / Role 4: image verdict from an isolated subagent reviewer (standing discipline, Role 3 visual contract, Role 4 step 5) | A fresh-context check of your own against the written visual contract, using a subagent if the host offers one, quoting the observation per region; if neither is possible the report says the review was not independent. A mismatch is never overridden by the context that made the render |
| Isolated-review host bindings whose fallback reviewer is the user (codex, dsh / kimicode) | The user is not asked to look at the render. Use the row above |
| Role 5 "Final delivery ⛔": evidence pack shown, the user's verdict recorded | The report (`discipline/operating-modes.md`) replaces the message: evidence pack, artifact list, assumptions, checks not run, reviews that were not independent. Your closing text approves nothing |
| A rejection at final delivery routes back through the role map | The service validates independently; a failure of your own checks still routes back to the owning artifact |
| A missing input (mesh, drawing, image) | Record the blocker in the report, do the strongest work the available evidence supports, never invent the input |
| Conflicting information between sources | Measured evidence over prose, prose over inference; record the conflict and the choice |

Standing discipline, binding for every role:

- **Serial stages, no bundling.** Do not prepare a later stage's model or
  verification artifact early. Finish the current stage gate before entering
  the next `S` stage.
- **Verifier before model.** For every stage, define and exercise the
  verification contract before editing the real part source. A model is not
  accepted because it builds; it is accepted only when the prepared checks
  pass.
- **⛔ BLOCKING means stop.** At a blocking gate, wait for the explicit user
  answer. Never decide on the user's behalf.
- **Image judgments are delegated.** Visual checks are planned by Role 3
  before the stage model is built; the render may be produced by Role 4
  afterward, but its acceptance verdict is supplied by an isolated subagent.
- **Standard parts first.** If the requirement can be satisfied by a
  standard part, or by a part based on one (gear, ring gear, rack,
  cycloidal disc, bearing, fastener), `scad.std.*` MUST be the basis —
  hand-modeling a standard shape is a defect, not a fallback. A single
  std part with no assembly context stays in this workflow via
  `domains/standard-parts.md`; a mechanism mating several std parts
  routes to `assembly-product-build.md`.
- **Sketch tier is the default part form.** Per the Feature Tree
  Convention, planar profiles and planar paths are sketch tier. When a
  stage's profiles are sketch tier, its verification contract includes
  the sketch gates: solve status and remaining DOF recorded before
  promotion, and promotion preserving measured geometry (closure, area,
  bounds compare). Plan entities and constraints with stable ids and
  evidence-backed constraints; intentional free DOF are recorded in the
  brief, never left silent. Capability detail:
  `domains/sketch-and-features.md`.
- **Feature Tree Convention.** Every part source is a marimo notebook
  (`docs/guides/notebook-runtime.md`) authored as
  block-structured features per `discipline/feature-tree-convention.md`
  (sketch → basic body op → bool → modifier, one feature per block and one
  block per cell, each with its boundary comment); read both before Role 4
  writes any model source, together with `discipline/notebook-cell-design.md`
  (where the cell boundaries go, when a number is a `Var`, and why).
- **Repair the owning artifact.** A failed verification reopens the current
  stage's verifier contract or model, whichever owns the failure. Never patch
  downstream symptoms or weaken a check to pass it.

## Role map

| # | Role | Reads (load before acting) | Produces | Exit gate |
| --- | --- | --- | --- | --- |
| 1 | Requirement Confirmer | `domains/requirement-refinement.md`, `discipline/requirement-and-cad-brief.md` | `<part-dir>/REQUIREMENTS.md` | ⛔ user consent received |
| 2 | Master Planner | `REQUIREMENTS.md`, `discipline/mechanical-modeling.md`, `discipline/datums-and-coordinate-systems.md` | `<part-dir>/BUILD_PLAN.md` + base TODOs | plan presented |
| 3 | Verifier Planner | `REQUIREMENTS.md`, `BUILD_PLAN.md`, `discipline/geometric-validation.md`, exact API/diagnostic pages used by the check | current-stage verification contract, hypothesis snippets, executable verification script, `plan verifier` and `run verifier` TODO items | verification artifact is ready before modeling |
| 4 | Detail Modeling Planner & Builder | current stage's verifier contract, `domains/part-modeling.md`, `discipline/feature-ordering.md`, `discipline/feature-tree-convention.md`, `discipline/notebook-cell-design.md`, exact modeling API pages | current-stage model, operation hypotheses, rendered evidence inputs | model runs and the prepared verifier passes |
| 5 | Exporter | `REQUIREMENTS.md` export rows, `domains/export-and-translation.md`, `domains/assembly-and-product.md` | `.scadpkg` + requested exports, readability check | artifacts re-open cleanly |

## Role-switch protocol

Before starting a role's work, output exactly:

```markdown
## [Role Switch: <Role Name>]
Reading: <role-owned files>
Artifact out: <path>
```

Then act only inside that role's scope. Roles 3 and 4 switch for each
Master-Planner stage as follows:

```text
S1: Role 3 plan verifier -> Role 4 build -> Role 3 run/review verifier
S2: Role 3 plan verifier -> Role 4 build -> Role 3 run/review verifier
...
Sn: Role 3 plan verifier -> Role 4 build -> Role 3 run/review verifier
```

Role 3 may use hypotheses to design a check, but may not certify a model it
has not tested. Role 4 may use modeling hypotheses, but may not start a stage
until that stage's verification contract and script exist. A failed stage does
not advance the TODO; it appends or starts a `repair:` item for the owning
artifact and repeats the same Role 3/4 loop.

---

## Role 5 — Exporter

Read the export rows from `REQUIREMENTS.md`. Durable canonical delivery is
`sca run <part>.py --out out/<part>.scadpkg` (or
`capture(run.definition, ...)` after `run_notebook`); external formats go through
`domains/export-and-translation.md` capabilities. Post-export gate:
re-open the package in a fresh process (`validate_product_package` /
definition materialization) and confirm definition/solid counts; list every
produced file with size.

Final delivery ⛔: evidence pack + artifact list + assumptions made +
checks not run, and record the user's verdict. A rejection here routes back
through the role map to the owning artifact.

**Unattended:** the final delivery is the report, not a question; see the Unattended mode table above.

---

## Failure routes

- Boolean fails, or a cut splits the body into pieces → `domains/part-modeling.md`
  boolean discipline (overlap, overshoot tools, isolate the pair).
- Fillet/chamfer fails → smaller radius, narrower selection, later order;
  selection problems follow the edge-selection defaults.
- Dimension mismatch → re-measure against `REQUIREMENTS.md`; fix the named
  parameter, not the symptom.
- Repeated dead ends → `discipline/failure-and-repair.md`; reconsider the
  BUILD_PLAN stage, not the same retry.

Part notebook, `REQUIREMENTS.md`, `BUILD_PLAN.md` with stage output
boundaries, verifier contracts, executable verification scripts, modeling
hypotheses, and method proofs; evidence pack paths; image verdicts quoted
from isolated subagent reviews; package/exports with sizes; assumptions made;
and checks not run.
