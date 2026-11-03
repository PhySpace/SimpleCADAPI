# Workflow: Drawing Reconstruction (Vector PDF)

Rebuild an editable SimpleCAD model from a vector-PDF engineering drawing.
The workflow is role-structured. Roles 1 and 2 turn the sheet into a tiered
parse report and a stage plan; Roles 3 and 4 run a strict, stage-by-stage
TDD loop; then the model is drawn back into a sheet, that sheet is re-parsed
blind, and the two parse reports are diffed parameter by parameter —
acceptance requires independently supported interpretation, model measurement
and output expression for every DIM. Agreement of two reports alone cannot pass.
Role 5 exports only after the roundtrip passes.

Scope: vector-PDF drawings only. Image, DXF, and DWG inputs have no
supported route yet — name the missing capability and stop that route.

Reconstruction targets only the drawing's explicit geometric dimensions,
tolerances, shape/position relationships, and user-confirmed completions.
Unless the user separately requests them, do not calculate or compare center
of mass, mass or inertia, and do not add high-precision volume-equivalence
acceptance gates. Retain basic checks for valid geometry, necessary closure,
expected solid count, and exports that can be reopened. Every blocking check
must trace to an explicit requirement or necessary geometric validity condition,
with the basis for its threshold recorded. A diagnostic observation alone does
not create an additional acceptance requirement.

Read `domains/drawing-inspection.md` first; Role 1 runs its parsing SOP and
report skeleton verbatim. Read `domains/engineering-drawing.md` before the
roundtrip section is executed.

Standing discipline, binding for every role:

- **Serial stages, no bundling.** Finish the current stage gate before
  entering the next `S` stage.
- **Verifier before model.** The verification contract and executable check
  exist before the stage's part source is edited. A model is not accepted
  because it builds.
- **⛔ BLOCKING means stop.** Never decide on the user's behalf at a
  blocking gate.
  **Unattended:** the ⛔ gates become self-review gates (`discipline/operating-modes.md`). Every blocking item is
  decided from evidence and recorded in the assumption ledger; the gate still binds its artifact (`report_A.md`,
  `REQUIREMENTS.md`, a ledger row per blocking item); `report.md` lists every decision.
- **The parse report is the drawing's truth.** Every modeling decision
  traces to a report entry with its tier mark (〔图面〕/〔归属〕/〔推算〕).
  The report contains no function/purpose inference; interpretation of what
  a feature is for lives in Role 2's hypothesis list, citing report entries.
- **Annotate, don't guess.** A feature the sheet cannot support (unlabeled
  hatched circles, external schedule curves) is measured, described, marked
  〔推算〕 or listed as missing — never invented and never silently dropped.
- **Roundtrip reports are blind.** Report B is parsed from the generated
  sheet without reading report A's values. The diff joins on `DIM-xxx` ids
  afterwards; pre-seeding B with A's numbers voids the gate.
- **Image judgments are independent.** Visual verdicts (original views, region
  crops, generated sheets) come from an isolated reviewer that sees the
  artifacts and written criteria. When no isolated reviewer tool is available,
  request the user's independent review and retain the actual verdict. An
  unavailable reviewer leaves the visual gate pending.
  **Unattended:** a fresh-context check of your own against the written criteria replaces the isolated reviewer or the
  user's review (a subagent if the host offers one). Quote what you observed per view and DIM, record the reviewer as
  `self (fresh context)` with the hashes of the reviewed files, and list the review as not independent in the report.
  The visual gate closes only on that written verdict.
- **Standard parts first; sketch tier is the default part form; every part
  source follows the Feature Tree Convention**
  (`discipline/feature-tree-convention.md`).
- **Repair the owning artifact.** A failure reopens exactly one owner: the
  parse report, the model source, or the drawing declaration. Never patch a
  downstream symptom; never weaken a check.

## Role map

| # | Role | Reads (load before acting) | Produces | Exit gate |
| --- | --- | --- | --- | --- |
| 1 | Drawing Requirement Confirmer | `domains/drawing-inspection.md`, `domains/requirement-refinement.md`, `discipline/requirement-and-cad-brief.md` | `<part-dir>/drawing_work/report_A.md`, evidence files, `<part-dir>/REQUIREMENTS.md` | ⛔ user consent received |
| 2 | Master Planner | `report_A.md`, `REQUIREMENTS.md`, `discipline/mechanical-modeling.md`, `discipline/datums-and-coordinate-systems.md` | feature hypothesis list + `<part-dir>/BUILD_PLAN.md` + base TODOs | plan presented |
| 3 | Verifier Planner | `report_A.md`, `BUILD_PLAN.md`, `discipline/geometric-validation.md`, check-specific API pages | per-stage verification contracts, the roundtrip contract, executable checks | verification artifact ready before modeling |
| 4 | Detail Modeling Planner & Builder | stage contract, `domains/part-modeling.md`, `discipline/feature-ordering.md`, `discipline/feature-tree-convention.md`, modeling API pages | stage models, operation hypotheses, rendered inputs | model runs and the prepared verifier passes |
| 5 | Exporter | `REQUIREMENTS.md` export rows, `domains/export-and-translation.md`, `domains/assembly-and-product.md` | `.scadpkg` + exports + evidence pack | artifacts re-open cleanly |

## Role-switch protocol

Before starting a role's work, output exactly:

```markdown
## [Role Switch: <Role Name>]
Reading: <role-owned files>
Artifact out: <path>
```

Then act only inside that role's scope. Roles 3 and 4 switch per stage:

```text
S1: Role 3 plan verifier -> Role 4 build -> Role 3 run/review verifier
S2: Role 3 plan verifier -> Role 4 build -> Role 3 run/review verifier
...
Sn: (last stage) -> roundtrip: generate sheet -> roundtrip: parse report B
  -> roundtrip: diff + triage -> (repair loop | pass)
```

A failed stage does not advance the TODO; it opens a `repair:` item for the
owning artifact and repeats the same Role 3/4 loop.

## Role and stage pages

| Page | Holds |
| --- | --- |
| `workflows/drawing-reconstruction/role-1-drawing-confirmer.md` | Role 1: parse report A, `REQUIREMENTS.md`, the ask round and its host bindings |
| `workflows/drawing-reconstruction/role-2-master-planner.md` | Role 2: hypothesis list, stage plan, `BUILD_PLAN.md`, TODO bindings |
| `workflows/drawing-reconstruction/role-3-verifier-planner.md` | Role 3: per-stage verification contracts, roundtrip contract, hypothesis-loop bindings |
| `workflows/drawing-reconstruction/role-4-detail-builder.md` | Role 4: construction ladder, probes, source edits, modeling bindings |
| `workflows/drawing-reconstruction/roundtrip-acceptance.md` | sheet B, section evidence, blind report B, diff, triage, pass criteria |
| `workflows/drawing-reconstruction/role-5-exporter.md` | Role 5: package, exports, final delivery |

## Read now (one parallel batch)

| File | Why |
| --- | --- |
| `workflows/drawing-reconstruction.md` | scope, standing discipline, role map (this page) |
| `workflows/drawing-reconstruction/role-1-drawing-confirmer.md` | the first stage: Role 1 |
| `domains/drawing-inspection.md` | the parsing SOP, tiers and report skeleton Role 1 runs verbatim |
| `domains/requirement-refinement.md` | Role 1 turns the parse into `REQUIREMENTS.md` |

## Read when

| When | File |
| --- | --- |
| Role 1 writes the ledger rows, or any section view needs evidence | `domains/drawing-inspection-evidence.md` |
| Role 1 writes `REQUIREMENTS.md` | `discipline/requirement-and-cad-brief.md` |
| Role 2 starts | `workflows/drawing-reconstruction/role-2-master-planner.md` |
| Role 2 picks the datum story and stage order | `discipline/mechanical-modeling.md` |
| Role 2 sets the datum story | `discipline/datums-and-coordinate-systems.md` |
| Role 3 starts (before every stage) | `workflows/drawing-reconstruction/role-3-verifier-planner.md` |
| Role 3 writes a stage's checks | `discipline/geometric-validation.md` |
| Role 4 starts | `workflows/drawing-reconstruction/role-4-detail-builder.md` |
| Role 4 builds a stage | `domains/part-modeling.md` |
| Role 4 orders features | `discipline/feature-ordering.md` |
| any part source is authored or edited | `discipline/feature-tree-convention.md` |
| any part source is run or loaded by a verifier | `docs/guides/notebook-runtime.md` |
| the last stage closes | `workflows/drawing-reconstruction/roundtrip-acceptance.md` |
| sheet B is generated | `domains/engineering-drawing.md` |
| the roundtrip has passed | `workflows/drawing-reconstruction/role-5-exporter.md` |
| Role 5 exports | `domains/export-and-translation.md` |
| Role 5 exports an assembly-rooted package | `domains/assembly-and-product.md` |
| a check fails twice for the same cause, or repeated dead ends | `discipline/failure-and-repair.md` |

## Unattended mode

A service that hands over a drawing wants a model and a report. Decide the mode first (`discipline/operating-modes.md`);
in unattended mode never ask, write the assumption ledger into `REQUIREMENTS.md` and `report.md` (the report of
`discipline/operating-modes.md`, with the diff table and the evidence pack), and never weaken a check.

| Interactive gate | Unattended replacement |
| --- | --- |
| Standing discipline: ⛔ BLOCKING means stop | Self-review gate; the gate still binds its artifact; every decision is in the ledger and the report |
| Standing discipline: image judgments from an isolated reviewer, or the user's review | Fresh-context check against the written criteria, quoted observations, hashes of the reviewed files; the report says it was not independent |
| Role 1 step 2: route verdict not `vector`, ask for a vector PDF or DXF/DWG | Record the blocker in the report, stop the route, build nothing, never improvise OCR |
| Role 1 step 5: the one batched ask round (shape interpretation, missing schedules, approximation approvals, material) | Record each as a ledger row chosen from the evidence; skip the host ask/question bindings |
| Role 1: ambiguous view or ambiguous association | Take the reading with the verified association, mark it 〔归属〕, list the alternative in section 8; an unresolved association keeps that DIM unverified while independent stages continue |
| Role 1: unreadable dimension or text | The DIM stays `unresolved` with the crop quoted; modelled only from an accepted-calibration measurement marked 〔推算〕, else listed in section 9 and reported |
| Role 1: missing sections, external schedules, blank fields, partial sheet set | A section whose plane cannot be resolved is `unreviewable` in the gap list; its DIMs take the not-expressible fallback (direct QL measurement) and their output expression stays pending; missing schedules or sheets go to section 9 and the report; never invented |
| Role 1 consent gate (⛔ user consent received) | Self-review gate: re-read `report_A.md` and `REQUIREMENTS.md` against the sheet, one paragraph of decision with open risks, every required field filled |
| Role 2 plan presented (no approval gate) | No change: record the plan in `BUILD_PLAN.md` |
| Role 3 may prepare visual verification for the isolated reviewer | Fresh-context check by a context that did not render the images; listed as not independent |
| Role 4 host binding: the user's review of an image | The same fresh-context check; the visual gate stays pending until its written verdict exists |
| Roundtrip step 2 and the Pass paragraph: isolated reviewer arbitrates layout readability and feature association | The fresh-context check, per-DIM verdicts with quoted observations, readability and association kept separate |
| Roundtrip step 7: two rounds without convergence, ⛔ ask the user | Stop the loop, keep the diff table and triage evidence, mark the DIMs `different` or `pending`, no pass claim; the part source and reports are the deliverable |
| Failure route: roundtrip differences that survive triage, ⛔ user | The same as step 7 |
| Role 5 final delivery ⛔: record the user's verdict | The evidence pack, assumptions, checks not run and process notes go into `report.md`; no verdict is recorded as approval |

---

## Failure routes

- Coordinate/source mismatch → reopen preflight, verify a single working source,
  invalidate dependent calibrations, interpretations and measurements.
- Ambiguous association → keep that DIM pending, repair the association evidence;
  continue unaffected work.
- Unknown/insufficient measurement accuracy → refine measurement or document a
  reliable bound; boundary overlap remains pending.
- Stale, fabricated or wrong-target annotation → reject output evidence, rebuild
  from current verified measurements and rerun independent validation.
- Readability passes but association fails → repair anchors/leaders/feature mapping;
  keep the two verdicts separate.

- Route verdict not `vector` → stop the route; request a vector PDF or the
  native format. No OCR improvisation.
- Calibration not accepted → re-anchor with independent dimensions; never
  produce derived numbers from a failed calibration.
- Boolean fails, or a cut splits the body into pieces → `domains/part-modeling.md`
  boolean discipline (overlap, overshoot, isolate the pair).
- Fillet/chamfer fails → smaller radius, narrower selection, later order.
- Dimension mismatch at a stage → re-measure against the ledger; fix the
  named parameter, not the symptom.
- Groove-lattice or pattern construction diverges → re-probe the single
  representative feature; reconsider the stage split, not blind retries.
- Roundtrip differences that survive triage → ⛔ user, with the diff table.
  **Unattended:** the same as roundtrip step 7 (stop the loop, mark the DIMs, report; no ask).
- Repeated dead ends → `discipline/failure-and-repair.md`; reconsider the
  stage plan.

Part notebooks; `REQUIREMENTS.md`; `drawing_work/report_A.md`,
`report_B.md`, and the diff table; `BUILD_PLAN.md` with stage boundaries,
hypotheses, and verifier contracts; executable verification scripts;
calibration records and provenance viewports; section renders and pair
composites with per-DIM verdicts; sheet B renders and the
isolated reviewer verdicts; package/exports with sizes; assumptions made;
checks not run.

**Required reading before authoring or editing any part source in this
workflow:** `domains/drawing-inspection.md` (Role 1), and
`discipline/feature-tree-convention.md` — the block-structured
sketch → basic body op → bool → modifier convention, its mandatory boundary
comments, and the sketch/geometry/primitive tier rules. Every part source
is a marimo notebook, one block per cell
(`references/docs/guides/notebook-runtime.md`): run it with `sca run`, and
load its product from verification scripts with
`simplecadapi.runtime.run_notebook(...)`.
