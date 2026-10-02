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

---

## Role 1 — Drawing Requirement Confirmer ⛔

Convert the drawing into `drawing_work/report_A.md` and `REQUIREMENTS.md`.
No geometry, no probe builds, no source-file writes before this gate closes.

1. Copy the source PDF into `<part-dir>/drawing_work/source/` first
   (transfer directories expire). Run the parsing SOP steps 0–7 of
   `domains/drawing-inspection.md` exactly — checkup and route verdict, text
   coordinate preflight, inventory, overview pass, region reading, per-view
   calibration and measurement, separate association verification, semantic assembly.
2. If the route verdict is not `vector`, stop the route: name what is
   missing (raster-only sheet, mixed content) and ask the user for a vector
   PDF or the native DXF/DWG. Never improvise an OCR path.
3. Write `report_A.md` in the ten-section skeleton. Every dimension gets a
   stable `DIM-xxx` id and all ledger fields required by the inspection domain.
   Unresolved association prevents a verified verdict for that DIM; independent
   stages can continue. Every section view in the view list also
   records its resolved cut-plane spec (plane position, normal, viewing
   direction) per the Section-plane parsing rules (R1–R7) of
   `domains/drawing-inspection.md` — deterministic, never asked; a view
   whose plane cannot be resolved uniquely is marked `unreviewable` in the
   gap list. Unrecoverable content (external
   schedules, blank title fields, unlabeled constructions) goes to section 9
   verbatim — measured-and-marked where possible, listed as missing where
   not.
4. Refine the requirement into `REQUIREMENTS.md`
   (`domains/requirement-refinement.md`): units and coordinate convention
   fixed from the sheet's views (front view, up axis, datum story from the
   GD&T section), named parameters seeded from the dimension ledger,
   verification intent, export targets. Technical-requirement lines are
   classified: geometry-affecting (model) vs process/manufacturing notes
   (deliverable remarks, never modeled).
5. Batch every blocking item into ONE ask round: disputed shape-level
   interpretation, missing external schedules (e.g. curve coordinate
   tables), approximation approvals for sheet-unsupported geometry, and
   material assumptions where a check needs one. Record everything in the
   Ask-or-Record ledger with the user's wording preserved.

<!-- skill:if omp -->

### Host binding: designing the Role 1 `ask` payload (omp)

One batched `ask` call for all items that block `REQUIREMENTS.md`. One
decision per question; name the region, view, or DIM id and state the
evidence or gap; options mutually exclusive and operational (what gets
recorded, what modeling follows); conservative clearly-labeled assumption
first with `recommended: 0` — a recommendation, never consent; include a
concrete correction path. Stable machine-readable `id`s keyed to ledger rows
(e.g. `arc_schedule_missing`, `unlabeled_hatched_circles`). After the call,
copy answers into the ledger verbatim; timeout or dismissal keeps the gate
blocked and stops — never continue by silently selecting the recommended
option.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: designing the Role 1 `question` payload (opencode)

One batched `question` call. No `id` field: key each ledger row to the
`header` (≤30 chars) derived from the stable identifier (e.g. `arc
schedule`, `hatched circles`); no `recommended` index: put the conservative
option first with a `(Recommended)` label suffix. Free-text custom answers
arrive automatically — phrase the question so the needed correction is
obvious when no option fits. Copy selected labels and custom answers into
the ledger keyed by header; a dismissed question is an unanswered blocking
row: keep the gate blocked and stop.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: requirement questions using available host tools

Use the host's available question tool for the batched requirement questions;
if none is available, ask in a concise message. Key each answer to its DIM/view
or requirement entry and record the user's words. Do not invent tool names or
interpret a timeout as consent. Existing explicit authorization still applies;
ask only for requirements that remain unresolved.

<!-- skill:endif -->

Gate: the ask round returned answers, consent is recorded in the ledger,
`report_A.md` and `REQUIREMENTS.md` exist. Entering Role 2 without this
gate is the cardinal violation.

## Role 2 — Master Planner

From `report_A.md` and `REQUIREMENTS.md` only — no API detail, no
step-level modeling.

1. **Feature inference.** Build the feature hypothesis list: one entry per
   inferred feature (base body, segments, bores, groove lattices, bosses,
   lugs, modifiers), each citing its evidence (`DIM-xxx` ids, view-list
   entries, 〔归属〕 conclusions) and carrying a confidence mark. Check
   `scad.std.gear` / `scad.std.bearing` before hand-modeling anything
   standard-like. Function/purpose narrative stays here and in the user
   conversation — it never re-enters the parse report.
2. **Stage plan.** Design the construction as `S1..Sn`: base body first,
   then major segments, feature groups as their own late stages (pattern
   lattices after their prototype feature is proven), modifiers last. Pair
   every stage with the DIM-id subset it must satisfy.
3. Write `BUILD_PLAN.md`: stage output boundaries, datum story, DIM-id
   mapping, hypothesis list. Role 3 appends verification contracts; Role 4
   appends modeling hypotheses while the loop runs.
4. Initialize the TODO tool with phases `Requirements / Plan / Build &
   Verify / Roundtrip / Export`; per stage create `plan verifier`, `model`,
   `run verifier` items; create the roundtrip tasks
   (`roundtrip: generate sheet`, `roundtrip: parse report B`,
   `roundtrip: diff and triage`). Mark Requirements and Plan done; start
   the first stage's `plan verifier`.

Present the plan in ≤10 lines. No approval gate; enter the Role 3/4 loop.

<!-- skill:if omp -->

### Host binding: TODO tool (omp)

Tool `todo`: `init(list=[{phase, items[]}])`, `start(task)`, `done(task)`,
`append(phase, items[])`, `view`. Task strings are stable identifiers —
quote them exactly. Keep the stage's `model` item pending until its
`plan verifier` artifact exists; a failed `run verifier` opens a
`repair:` item for the owner; never advance while an owner is open. Batch
`todo` calls with real work in the same turn.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: TODO tool (opencode)

Tool `todowrite`: submit the whole list every call as
`todos=[{content, status, priority}]` with statuses
`pending / in_progress / completed / cancelled`. `content` strings are the
stable identifiers — quote them exactly (`S1 plan verifier`,
`repair: S1 verifier bore depth`, `roundtrip: diff and triage`). Exactly one
item `in_progress` at a time; mark `completed` only at the real gate; a
blocked item stays `in_progress` with a follow-up item recording the
blocker. Keep the stage's `model` pending until its `plan verifier`
artifact exists; a failed `run verifier` opens a `repair:` item for the
owner.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: plan and checklist state

Use the host's available plan/TODO tool. If none exists, maintain the same stage
checklist in `BUILD_PLAN.md`, updating the artifact after each real result.
Keep `plan verifier`, `model`, `run verifier` and any `repair:` items distinct;
complete them only when the corresponding evidence exists.

<!-- skill:endif -->

## Role 3 — Verifier Planner

Runs before every stage's modeling work and owns the roundtrip contract.
This is "tests before implementation" applied to sheet evidence.

For the current `S` stage, in order:

1. **Stage output**: name the substructure, its datum relationship, and the
   `DIM-xxx` subset it must satisfy; state what is deliberately out of
   scope.
2. **Acceptance criteria** from the ledger subset: dimensions with their
   tolerance bands, required topology (face/hole/axis counts), interfaces
   with already-built geometry, BREP validity and single-solid expectations,
   visual criteria where a view must confirm attachment.
   Apply the scope restriction above when planning the verifier: no center-of-mass,
   mass, inertia, or high-precision volume-equivalence checks without a separate
   user requirement. Record the requirement/validity condition and threshold
   basis for each blocking assertion; do not introduce gates during debugging.
   For every DIM write a measurement contract before modeling: feature/geometry
   selection, datum, direction, section origin/normal/basis, algorithm, sampling
   configuration, accuracy class, error-bound evidence and tolerance basis.
   Verify true circle geometry for diameters; use continuous extrema for envelopes.
   Define wall thickness as minimum boundary gap, radial thickness, or material
   length along a specified line before selecting the algorithm. A fitted circle
   is only a candidate; sampled nesting is only a pair-selection candidate.
   Neither fit residual, intersection `tolerance`, nor additional sampling alone
   establishes the total error bound. Record convergence checks as such.
   An approximate value with reliable bound e passes only when [value-e,value+e]
   is wholly inside the tolerance band. Boundary overlap or unknown error is
   `pending`; refine the algorithm or obtain a supported uncertainty assessment.
   Cite any default tolerance actually specified by the sheet; otherwise record
   missing tolerance basis and keep conformance pending, never invent a standard.
   Unreliable fits or measurements stay pending. They cannot justify changing
   CAD dimensions. For circle candidates record residuals, angular coverage,
   conditioning, closure and actual edge types; a local arc, gapped contour or
   nearly collinear sample set cannot establish a full circular feature.
3. **Deterministic checks**: iterate hypothesis snippets in the execution
   environment; good and bad probes must show each check separates pass
   from fail. QL-only topology enumeration (plural getters take an index or
   are driven through `ql.<kind>().resolve`). Reject checks that merely
   print a plausible number.
4. **Executable verification script** with explicit assertions and named
   measurements; append `Verifier contract: <output> / Criteria: <...> /
   Script: <path>` to `BUILD_PLAN.md` with hypothesis evidence and known-bad
   proof. Complete the stage's `plan verifier` TODO; only then may `model`
   start. After Role 4 finishes, run the exact prepared script; only its
   passing output closes the stage.
5. **Roundtrip contract** (written once, before S1): the coverage table
   mapping every ledger `DIM-xxx` to its verification channel — a generated
   sheet dimension where the drawing engine can express it, a
   **section-evidence render** where the drawing's section views express it
   (cut plane from the view list, measured dimensions from
   `measure_model_section_rdimensions`, annotated render via
   `render_model_section_rpath`, compared against the drawing's viewport by
   you), or direct QL model measurement otherwise;
   for each section view, a section-evidence task (plane spec, expected
   DIM-id set, provenance viewport); the sheet declaration plan derived
   from report A's view list; the pass criterion (every parameter within its
   original tolerance band with sufficient accuracy; defaults only when the sheet
   explicitly supplies a standard/class).

Role 3 may prepare visual verification (named views, regions, verdict
fields for the isolated reviewer) but never certifies its own renders.

<!-- skill:if omp -->

### Host binding: persistent REPL and TODO state machine (omp)

Use the persistent `eval` tool (language `py`) for hypothesis snippets,
known-bad probes, and the verification scripts; keep cells incremental.
Never treat a modeling success message as verification: invoke the prepared
verifier and record its output. Drive the stage gates through `todo`
exactly as declared in Role 2; close `plan verifier` only when contract,
executable check, hypothesis evidence, and known-bad proof exist; after
Role 4's run, start and complete `run verifier` on the script's real output.
On failure do not rewrite the criterion to clear the list — open
`repair: <stage> <owner>` for the verifier or the model and repeat the loop.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: file-based hypothesis loop (opencode)

No persistent REPL: every Python run is a fresh process. Keep hypothesis
snippets, known-bad probes, and final checks as numbered files under
`<part-dir>/verify/` (`s1_hypothesis.py`, `s1_known_bad.py`, `s1_verify.py`),
run them via `bash`, and persist intermediate state to files (JSON,
pickle, or captured packages) between runs. The script file is the
evidence. Gate the stages through `todowrite` with the exact task strings;
`todowrite`'s echoed list is the re-grounding source after any interruption.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: file-based verification

No persistent REPL is assumed. Write hypotheses, known-bad probes and final
checks under `<part-dir>/verify/`, and execute them through the available shell
or execution tool. Retain scripts and JSON results so the stage can resume from
files. Update the plan/checklist from actual outputs; a failed check reopens its
owning artifact and cannot be cleared by weakening the criterion.

<!-- skill:endif -->

## Role 4 — Detail Modeling Planner & Builder

Starts only after the stage's verifier contract and executable check exist.

1. Read the contract, then choose construction from the geometry: profile
   and sketch first when they control the shape (constrained sketches,
   promotion, `extrude/revolve/loft/sweep_rsolid`); documented primitives
   when they map directly; named feature solids combined deliberately with
   `union/cut/intersect_rsolid` (positive overlap, tool overshoot); patterns
   only after one representative feature is proven; topology-sensitive
   features (fillet/chamfer/shell) last. The ladder expresses intent — it
   is not an API whitelist; read the exact API page before every first
   call.
2. Name every construction step for its part role or feature
   (`mounting_base`, `port_bore_tool`, `front_flange`), never its creation
   order. Attach `role.*` / `feature.*` / `tool.*` tags; numeric facts in
   metadata, not tags.
3. Probe the construction on minimal solids before editing the part source;
   print types, counts, volumes, bounds as the contract requires; append
   `Hypothesis / Result / Adopted` rows to `BUILD_PLAN.md`.
4. Edit the part source with keyword arguments, named parameters, FTC block
   structure, and boundary comments; selection cards before every
   fillet/chamfer.
5. Run the source and hand the stage geometry to Role 3. The stage passes
   only when all assertions, measurements, and required visual verdicts
   pass. On failure: no weakened checks — determine the owner (contract or
   model), open a `repair:` item, repeat the loop.

<!-- skill:if omp -->

### Host binding: persistent REPL (omp)

Hypothesis construction lives in `eval` (names survive across calls); the
real source run lives in bash. Close `S<n> model` only after the source run
completes, then start `S<n> run verifier` for Role 3.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: file-based hypothesis loop (opencode)

Run incremental construction hypotheses as numbered scripts under
`<part-dir>/hypotheses/` via `bash`; carry geometry between probes by
writing files (pickle/JSON/`capture`) and reloading, or by re-materializing
from the part source. The source run itself also runs in `bash`. A modeling
success message is never the verification result.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: modeling execution and independent image review

Run the part source with the available execution tool and preserve the stage's
verification outputs. For image judgments, use an available isolated reviewer
with the render paths and written criteria, or the user's explicit review when
no such tool exists. The context that generated the image cannot provide its
own acceptance verdict. Store reviewer identity, result and reviewed artifact
hashes; lack of a reviewer leaves the visual gate pending.

<!-- skill:endif -->

## Drawing-roundtrip acceptance

Owned by Role 3, executed after the last stage closes. This loop replaces
impression with evidence: the model must regenerate the sheet's content.

1. **Generate sheet B.** From the validated model, drive the engineering-
   drawing engine (`domains/engineering-drawing.md`) in batch: declare the
   view set from report A's view list (subset the engine supports), with
   dimensions covering the sheet-expressible ledger parameters. Read
   `report()`; declaration-level problems are re-declared, never
   action-patched. Export the DXF/PDF plus rendered PNGs.
   Build annotations from verified measurement records. Section evidence uses
   `build_section_annotation_rrecord`; native sheet dimensions require equivalent
   bindings to their model-measurement records. Copying A's nominal values is not
   a model measurement.
   Bind `DIM ID → feature/contours → section definition → measurement ID → model hash`.
   Independently bind `measurement_contract` from the ledger: dimension kind,
   direction, definition, line point, units and coordinate space. A contour ID
   shared by width and height cannot substitute for this contract.
   Before rendering, `validate_section_annotations_rreport` independently reruns
   geometry measurement and checks values, target IDs, section/configuration and
   current model hash. A model or section change invalidates the old evidence
   (conservative invalidation of all model evidence is acceptable). Preserve
   unrounded measured values for acceptance; configure displayed decimals from
   the tolerance band. Reject a display step wider than the band, rounding error
   greater than half its width, or a displayed number outside it. Keep
   `measured=999`, wrong-axis, wrong-definition, coarse-display and stale-model cases as
   required negative tests. Raw rendering remains permitted but cannot pass this gate.
2. **Generate section evidence.** For every section view in report A's view
   list, cut the model at the recorded plane (`measure_model_section_rdimensions`),
   verify the ledger-matching dimension candidates and their accuracy, and render the annotated
   section (`render_model_section_rpath`). The annotated values are model
   measurements only when their source binding passes independent validation.
   Declare section_strategy explicitly (auto/material/edges) and archive the
   method actually used. Formal section evidence requires the section_checks
   contract: independently resolved origin, normal and local axes, expected solid,
   material-face and hole counts, representative material/void points, point
   tolerance and its basis. Check model validity/closure, section closure, valid
   material faces and topological outer/inner wires. Classify each point against
   the original solid, material-face intersection and displayed polygons. Cover
   every material face and every hole; boundary/uncertain points remain pending.
   An image containing open or incomplete contours is diagnostic output only.
   First verify the section definition, intersection and display. Modify the
   model only when independent solid checks establish a geometry error supported
   by the drawing; a rendering failure never establishes that by itself.
   Record **layout readability** (legibility, clipping, overlap) separately from
   **feature association** (anchor, target geometry, leader path, text box).
   Automatic placeholder anchors are not association evidence. Tables require
   feature numbers plus view/detail references that permit checking the mapping.
   Archive local axes, final rotation/scale, canvas and pixel transforms, text
   boxes and leader paths; test interior-point forward/inverse transforms.
   Visual review records must retain the DIM/measurement/model/section IDs and
   SHA-256 of the actual reviewed PNG and sidecar. The acceptance script compares
   these with current files and annotation content; it must never overwrite a
   review's old IDs. Changes to anchors, displayed precision, render layout or
   either artifact require review of the new artifact even if model IDs agree.
   Compare each render against the drawing's own
   viewport crop (both are yours) and emit per-DIM verdicts
   (`consistent` / `different` / `unreviewable` + reasons); hand both images
   to the isolated reviewer when visual arbitration is required.
3. **Parse report B blind.** Re-run Role 1's SOP (steps 0–7) on sheet B and
   write `drawing_work/report_B.md` in the same skeleton — without reading
   report A's values. B carries its own `DIM-xxx` ids for its own sheet.
   Blind reading tests communication. It never substitutes for model geometry
   measurement; A/B numerical agreement must still have a model-derived source.
4. **Diff.** Join verdicts to A's ledger parameters (geometry identity,
   not id text): sheet-expressible parameters join against report B's
   entries, section-expressible parameters against the section-evidence
   verdicts. Verdict per parameter: `consistent` (within the original
   tolerance band; unspecified tolerances per the sheet's default
   standard), `different`, or `not-expressible`. The diff table (parameter,
   A value, B value, verdict, channel) is a deliverable.
5. **Not-expressible fallback.** Parameters neither channel can carry
   (hatch-level geometry, features invisible in every resolved view)
   are verified by direct QL measurement of the model against the ledger —
   same tolerance criterion, different evidence channel, recorded in the
   coverage table.
6. **Triage every `different`.** Re-open the original drawing evidence
   (re-render the provenance viewport) before deciding:
   - **Sheet-generation artifact** — `report()` warnings, engine
     limitations, projection placement faults: fix the declaration,
     regenerate B, re-diff. The model is never touched for this.
   - **Section-plane artifact** — the cut plane was resolved wrong (R1–R4
     misapplied): correct the plane spec in report A's view list, re-render
     the section evidence, re-diff. The model is never touched for this.
   - **Parse error in report A** — the original evidence contradicts the
     ledger entry: correct `report_A.md` (tier marks intact), re-derive the
     affected hypotheses and stages, and re-model through the owning stages.
   - **Model error** — the evidence supports the ledger and the model
     measures otherwise: repair the owning source parameter (FTC block),
     re-run the stage verifier, then regenerate B.
7. **Convergence.** Two full rounds without convergence → ⛔ stop and ask
   the user with the diff table and the triage evidence. Blind parsing,
   section evidence, and delegated visual review apply to every round — no
   shortcuts on retries.

Pass: each DIM separately passes (1) original interpretation — value, tolerance,
association and coordinate evidence; (2) model measurement — actual geometry and
adequate accuracy; (3) output expression — the matching measurement supplied the
number and the feature association is correct. The isolated reviewer also passes
layout readability and feature association separately for sheet B and section
pairs. `assess_dimension_rverdict` records the three gates. Coverage must enumerate
value verification, association verification and layout review independently;
missing evidence cannot be hidden in a combined pass count. A fallback measurement
can satisfy geometry, but cannot certify an absent or incorrect output expression.

## Role 5 — Exporter

Read the export rows from `REQUIREMENTS.md`. Durable canonical delivery is
`sca run <part>.py --out out/<part>.scadpkg` (or
`capture(run.definition, ...)` after `run_notebook`); external formats through
`domains/export-and-translation.md`. Post-export gate: re-open the package
in a fresh process and confirm definition/solid counts; list every produced
file with size.

Final delivery ⛔: evidence pack — `report_A.md`, `report_B.md`, the diff
table, calibration records, provenance viewports, sheet B renders — plus
assumptions made, checks not run, and the process-note remarks from the
technical-requirements classification. Record the user's verdict; a
rejection routes back through the role map to the owning artifact.

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
- Boolean fails or yields multiple bodies → `domains/part-modeling.md`
  boolean discipline (overlap, overshoot, isolate the pair).
- Fillet/chamfer fails → smaller radius, narrower selection, later order.
- Dimension mismatch at a stage → re-measure against the ledger; fix the
  named parameter, not the symptom.
- Groove-lattice or pattern construction diverges → re-probe the single
  representative feature; reconsider the stage split, not blind retries.
- Roundtrip differences that survive triage → ⛔ user, with the diff table.
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
