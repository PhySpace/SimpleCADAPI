# Workflow: Engineering Drawing Generation

Produce a GB-standard engineering drawing sheet set (DXF + PNG) from an
already-validated part or product. This is a preliminary workflow; drawing is
an output stage, so geometry must be final before entry. Layout follows the
engine's division of labor: the solver computes deterministic truth
(projection, measurements, collisions, rules R1–R7), and the agent refines
the layout through a validate-and-rollback action loop.

Read `domains/engineering-drawing.md` first — this workflow does not repeat
its solver rules or engine boundaries.

Standing discipline, binding for every role:

- **Geometry first, drawing second.** Enter only with validated geometry and
  a settled datum story. A drawing never repairs a model; it exposes one.
- **Engine truth, agent choice.** Every validity judgment (collision, R1–R7,
  coverage) is computed by the engine. The agent only arbitrates discrete
  choices (which side/row, which trade-off) through actions the engine
  validates or rejects with reasons. Never hand-edit a rendered DXF or PNG.
- **Declare, then arbitrate.** Start from semantic declarations
  (`SheetDecl` + friends); run the action loop only on what the solver could
  not place cleanly. Actions refine a solvable declaration; they are not a
  substitute for one.
- **The action log is the decision log.** Every layout change is an action
  in a replayable JSON file. Rebuilding from declarations plus replaying the
  action file must reproduce the sheet byte-for-byte.
- **Audit before render; two artifacts, one truth.** `report()` is reviewed
  before rendering, and visual acceptance means reading the PNG rendered
  from the DXF — "no rule conflicts" alone is not acceptance.

## Role map

| # | Role | Reads (load before acting) | Produces | Exit gate |
| --- | --- | --- | --- | --- |
| 1 | Drawing Requirement Confirmer | `domains/requirement-refinement.md`, `domains/engineering-drawing.md`, model requirements (`REQUIREMENTS.md`/`BUILD_PLAN.md` if present) | `<part-dir>/DRAWING.md` | ⛔ user consent received |
| 2 | Sheet Planner | `DRAWING.md`, `discipline/datums-and-coordinate-systems.md` | per-sheet view/datum/dimension roster + R5 coverage ledger | plan presented |
| 3 | Layout Arbiter | sheet plan, `domains/engineering-drawing.md`, declaration/action API pages | sheet declarations, action-log JSONs, solver-clean report | `report()` Issues: no errors, every warning fixed or accepted-with-reason |
| 4 | Visual Reviewer | rendered PNG only | structured verdict | verdict pass; failures become `repair:` items for Role 3 |
| 5 | Drawing Exporter | verdict-passed action logs, `domains/engineering-drawing.md` | final DXF + PNG + archived action logs | artifacts re-open cleanly |

## Role-switch protocol

Before starting a role's work, output exactly:

```markdown
## [Role Switch: <Role Name>]
Reading: <role-owned files>
Artifact out: <path>
```

Then act only inside that role's scope. Roles 3 and 4 alternate per sheet:

```text
Sheet_1: Role 3 declare + action loop -> Role 4 render verdict -> (repair:)*
Sheet_2: Role 3 declare + action loop -> Role 4 render verdict -> (repair:)*
...
```

A failed verdict does not advance the sheet; it appends a `repair:` item
owned by the declarations or the action log, whichever owns the failure, and
repeats the same Role 3/4 loop.

---

## Role 1 — Drawing Requirement Confirmer ⛔

Convert the request into `DRAWING.md`. No declarations, no renders before
this gate closes.

1. Carry over the model's settled facts (geometry validated, parameters
   named). Do not reopen modeling decisions here.
2. Decide-or-ask the drawing-level choices: sheet scale, view set (which
   views, which sheet each lives on), datum letters, which parameters are
   manufacturing-critical, and the notes/parameter-table split.
3. Batch every blocking ambiguity into ONE ask round with conservative
   defaults first (`domains/requirement-refinement.md`). Record the rest in
   the Ask-or-Record ledger with basis.

   **Unattended:** no ask round. Decide each drawing-level choice from the
   model's facts (the conservative default of `domains/requirement-refinement.md`
   when the evidence ties) and record it in the assumption ledger inside
   `DRAWING.md`: `value / evidence / how to change it / the check that would show it wrong`.

Write `DRAWING.md` with: scale; per-sheet view roster; datum scheme;
dimension roster seeds (parameter → kind/semantic guess); R5 ledger skeleton
(every parameter → dimension carrier or notes/table); open assumptions.

Gate: the ask round returned and consent is recorded. Entering Role 2
without this gate is the cardinal violation.

**Unattended:** the gate is a self-review. Re-read `DRAWING.md` against the
request and the model's facts, write one paragraph of decision with the open
risks, and go on only when every required field is filled (a recorded
assumption fills a field; an empty one does not).

## Role 2 — Sheet Planner

From `DRAWING.md` only — no API detail, no coordinates.

1. Per sheet, fix the view set and alignment structure (front view anchored;
   every other view `align`ed to it — 长对正 / 高平齐 by construction, never
   by offsets).
2. Fix the datum scheme consistent with the model's functional interfaces
   (`discipline/datums-and-coordinate-systems.md`).
3. Produce the dimension roster: for each parameter, its carrier dimension
   (kind, semantic, view, reference datum) or its notes/parameter-table
   destination. This roster IS the R5 coverage ledger.
4. Flag parameters the engine cannot express yet (engine boundaries in the
   domain page) and route them to notes explicitly — never silently.

Present the plan in ≤10 lines. No approval gate; enter the Role 3/4 loop.

## Role 3 — Layout Arbiter

Owns declarations and the agent-in-the-loop refinement cycle.

**Phase A — declare.** Author the `SheetDecl` per sheet from the roster:
`ViewDecl`s with `align`, `DatumDecl`s first, `DimDecl`s with `covers`,
`CenterDecl`/`LeaderDecl` as planned. Solve, print `report()`, and read it
line by line: fix declaration-level problems (wrong view, missing datum
reference, duplicate measurement) by re-declaring, not by actions.

**Phase B — the action loop.** For everything the solver placed with
warnings or left unsolved, iterate:

1. **See.** Render the annotated review image (`viz`): gray = placed ok,
   blue = unsolved, red = warning, orange = accepted-with-reason; green
   arrows show each element's free movement corridors (how far it can
   translate, per direction). Read the red and blue elements first.
2. **Measure.** Call `plan.evaluate()` and read the exact, digested numbers
   for the failing elements: per-element `violations` (what it hits, where,
   by how much) and `corridors` (free translation distances). Work from
   these quantities — never from re-derived raw geometry.
3. **Propose.** Compose the next action-log JSON: one action per decision
   (`rad`/`dia`/`lin`/`lead` position adjustments, `accept` to bless a
   warning with a recorded reason). Actions are discrete choices — which
   side, which row, which trade-off (R1 squeeze vs arrow-off-arc vs new
   azimuth) — arbitrated by you, the agent.
4. **Submit.** Replay via `plan.apply(actions)`: the engine validates each
   action and rejects bad ones with `violations`/`corridors` residuals,
   rolling the sheet back to the last consistent state. A rejection is data,
   not failure: read the residuals, revise the action, resubmit.
5. **Verify blast radius.** Diff the previous and new action logs (pixel
   diff of the two replays): red = newly covered, blue = vacated, gray =
   untouched. Confirm the action moved only what you intended.
6. Loop 1–5 until every element is gray or orange (warn = 0), then run the
   full `report()` audit once more.

Exit gate: `report()` shows R1–R7 ok or accepted-with-reason, the R5
coverage table has no `MISS`, and no red/blue elements remain. Drive the
loop directly against `SheetPlan` (solve / evaluate / apply / render);
declaring `SheetDecl.diag_png` makes every solve/apply auto-refresh the
annotated conflict image and return a must-read instruction with it.

## Role 4 — Visual Reviewer

Rendered-PNG-only judgment, delegated in the same spirit as image verdicts
in `workflows/single-part-modeling.md`: the reviewer sees the artifacts, not
the reasoning.

**Unattended:** a fresh-context check of your own replaces the delegated
reviewer (a subagent if the host offers one): it reads only the PNG and the
check list below, and its structured verdict quotes what it observed per item.
The report says the review was not independent.

1. Read the PNG rendered from the final DXF (both sheets if multiple).
2. Check, in order: views aligned as planned; hidden lines (虚线) and center
   lines present; arrows touch their geometry; texts sit clear of lines;
   datum boxes legible; the dimension arrangement communicates design intent
   (a formally clean sheet can still mislead — e.g. dimensioning a derived
   length instead of the functional one).
3. Emit a structured verdict: pass, or an itemized list where each item
   names the owning artifact (declaration or action log).

A failed item becomes a `repair:` item for Role 3. Never patch the DXF.

## Role 5 — Drawing Exporter

1. Final render: `plan.render(dxf, png)` per sheet from the verdict-passed
   state (declarations + replayed action logs).
2. Re-open the DXF (e.g. via `ezdxf`) and check the entity count matches the
   render report; confirm both artifacts regenerate deterministically from
   the same inputs.
3. Deliver: DXF + PNG paths plus the archived action-log JSONs (they are
   part of the deliverable — the reproducible decision history).

## Acceptance

- `report()`: R1–R7 all ok, or accepted with recorded reasons.
- R5: every model parameter has a carrier; no `MISS`.
- Visual verdict passed; DXF re-opens with expected entity count; the sheet
  regenerates byte-for-byte from declarations + action log.
- Engine boundaries routed explicitly (notes/table), never silently dropped.

## Failure modes

- Entering with unvalidated geometry: every downstream conflict then looks
  like a drawing bug but is a model bug.
- Using actions to fight a wrong declaration: if `report()` shows structural
  problems (missing datum, duplicate measurement), re-declare — the action
  loop is for placement refinement, not for repairing semantics.
- Trusting "no conflicts" over the PNG, or skipping the diff step so one
  action silently relocates a neighbor.
- Losing the action log: without it the sheet is not reproducible; treat it
  as a deliverable, not scratch.
- Hitting engine boundaries (no sections/hatching; horizontal/vertical
  linear dims only; radius labels same-side outward): restructure the view
  set or record the limitation; do not simulate missing features with
  leader-note spam.

## Read now (one parallel batch)

| File | Why |
| --- | --- |
| `workflows/engineering-drawing.md` | standing discipline, role map, Role 1 (this page) |
| `domains/engineering-drawing.md` | solver rules and engine boundaries; this workflow does not repeat them |
| `domains/requirement-refinement.md` | Role 1 decides or asks the drawing-level choices |

## Read when

| When | File |
| --- | --- |
| Role 2 fixes the datum scheme | `discipline/datums-and-coordinate-systems.md` |
| the model's requirements or build plan exist | `domains/part-modeling.md` |
| Role 4 compares with the image-verdict practice | `workflows/single-part-modeling.md` |
| any part source is authored or edited to make geometry final | `discipline/feature-tree-convention.md` |
| a sheet fails twice for the same cause | `discipline/failure-and-repair.md` |

## Unattended mode

Decide the mode first (`discipline/operating-modes.md`). In unattended mode never ask; a gate still binds its artifact
(`DRAWING.md`, a solver-clean `report()`, a written verdict) and the result goes into `report.md`.

| Interactive gate | Unattended replacement |
| --- | --- |
| Role map and Role 1 consent gate (⛔ user consent received) | Self-review gate on `DRAWING.md`: one paragraph of decision with open risks, every required field filled |
| Role 1 step 2 decide-or-ask (scale, views, datums, critical parameters, notes/table split) | Decide from the model's facts and record each in the assumption ledger |
| Role 1 step 3 one batched ask round | No ask round; ledger rows with evidence, how to change, and the check that would show it wrong |
| Missing or unvalidated model geometry on entry | Record the blocker in the report, do the work the available evidence supports, never invent geometry or parameters |
| Role 4 delegated visual review of the PNG | Fresh-context check against the written list, quoted observations, listed as not independent in the report |
| Role 2 plan presented (no approval gate) | No change |
