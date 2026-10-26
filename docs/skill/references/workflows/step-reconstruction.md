# Workflow: STEP Reconstruction

For evidence and local visual artifacts without reconstruction, see
`step-computational-geometry-analysis.md`. For detailed local geometric feature analysis and section evidence, see
`step-reconstruction-geometry-guide.md` (Chinese:
`step-reconstruction-geometry-guide-cn.md`). Use the modeling operations and
validation rules in this upstream workflow.

Three whole-body loft/sweep examples with saved report gates, candidate
iterations, and visual previews are in
`references/docs/guides/step-reconstruction-loft-sweep-cases.md` (relative to
the skill root). Load that guide when the target has the corresponding
whole-body feature; keep this workflow's gates authoritative.

Rebuild an editable SimpleCAD model from an existing STEP file. The first
stage always runs the complete computational-geometry analysis as a prelude;
feature-tree inference, candidate construction, and tiered acceptance consume
that analysis package.

## Goal and scope

Use when the deliverable is an editable/replayable model reproducing a target
`.step`/`.stp`. Not for read-only questions about a STEP file — those stay in
`domains/step-inspection.md` without reconstruction. A request for the
analysis package alone routes to `step-computational-geometry-analysis.md`
with route `analysis_only`.

## Task decomposition

```yaml
goal: candidate model accepted against the target STEP
primary_domain: step-inspection
required_domains:
  - requirement-refinement
  - step-inspection
  - part-modeling
optional_domains:
  - sketch-and-features
  - assembly-and-product     # multi-component targets
  - export-and-translation   # re-export for comparison or delivery
artifacts:
  - analysis package from the prelude (analysis/)
  - feature-tree hypothesis with provenance rows
  - analysis-evidence.md mapping every recognized feature to a candidate operation
  - candidate source and replayed model
  - comparison evidence and acceptance verdict
validation_gates:
  - prelude package passes the R0 hard gates
  - analysis report is read and every recognized feature has an evidence row before candidate construction
  - replay succeeds in a fresh process
  - STEP roundtrip of the candidate validates
  - acceptance follows the hierarchy (topology identity > float drift > justified stop)
repair_routes:
  - R0 hard gate fails -> rerun the prelude
  - comparison fails -> step-inspection (localize) then part-modeling (fix feature)
  - global similarity but locally falsified feature -> change the feature hypothesis
```

## Output layout

```text
<absolute-output-directory>/analysis/        # prelude package; read-only after Phase 9
<absolute-output-directory>/reconstruction/  # brief, source, model JSON, candidate STEP, comparisons, iterations
```

Never write reconstruction artifacts into `analysis/`. Replacing the analysis
package invalidates every result in `reconstruction/` derived from it.

## Analysis prelude

1. **Refine the requirement**
   (`references/domains/requirement-refinement.md`): fidelity (exact
   transcription vs functional equivalence), components in scope, acceptance
   thresholds with units and sources. Write it to
   `reconstruction/requirement-brief.md`.
2. **Run `step-computational-geometry-analysis.md` Phases 1-9** with route
   `reconstruction_prelude`, output directory
   `<absolute-output-directory>/analysis/`, all eight feature kinds, and a
   recorded render budget. Read that workflow in full before Phase 1; it owns
   the prelude procedure, required reading, and gates. A failed phase stops
   reconstruction with the failed phase and reason.

## Reconstruction stages

### R0: Validate and load the analysis package

Read `references/docs/api/inspect_analysis_package_rdescriptor.md`, then call
`inspect_analysis_package_rdescriptor` with the `analysis/` directory, the
target STEP, and this request's recognition parameters as `expected_config`
(keys `feature_kinds`, `linear_tolerance`, `angular_tolerance_degrees`,
`max_features`, `section_rule`). Save its result as
`reconstruction/analysis-package-check.json`. Continue only when
`may_start_reconstruction` is true; never edit package files to make it pass.
The function implements the gates below.

Hard gate (any failure means rerun Phase 1-9; never patch a stale package):

- the target's current SHA-256 equals `target_sha256` in `feature-index.json`
  and `artifact-manifest.json`;
- `analysis-config.json` matches this request for feature kinds, linear and
  angular tolerances, `max_features`, and section rules (render options alone
  do not count);
- `feature-index.json` `schema_version` and every `reconstruction`
  `schema_version` are in the analysis workflow's accepted list;
- the SDK version recorded in `run-status.json` equals the installed version;
- `run-status.json` is `complete` or `complete_with_gaps`;
- `truncated=false`, `complete=true`, and every entity ID resolves on the
  target;
- every file in `artifact-manifest.json` exists with matching bytes and
  SHA-256;
- the catalog carries `coverage`, and every face it reports as owned by no
  feature is listed in `unresolved-features.md`.
- `parse-report.md` contains exactly one feature heading for each catalog
  `feature_id`.

Soft gate: under `complete_with_gaps`, skipped per-feature visuals or
sections and `incomplete` loft/sweep entries do not block R1 when each is
listed in
`run-status.json` `gaps` (result `status="pass_with_gaps"`); carry each gap
into R1 as lowered confidence and report it in R7.

A package from an earlier `analysis_only` run may be reused when every hard
gate passes; record its original path in `reconstruction/` as reused.

Before R1 or any candidate construction, read `parse-report.md` in full, then
load `feature-index.json`, `reconstruction-hypotheses.json`,
`loft-sweep-specialist.json`, `section-index.json`, and
`unresolved-features.md`. Write `reconstruction/analysis-evidence.md` with one
row for every catalog `feature_id`: report claim, category/subtype, location and
dimensions, confidence, supporting section or entity IDs, proposed operation,
and a check that could falsify it. List unresolved faces and soft gaps there as
well. If the report and catalog conflict, inspect the target and resolve the
conflict before R1. A passing package hash alone does not satisfy this read
gate. Do not start R3 until the evidence rows cover the entire catalog.

### R1: Turn geometric evidence into a feature tree

Infer feature families from the catalog, sections, and carrier behavior
(`references/docs/guides/reconstruction-agent-strategy.md`):

```text
shared axis + rotational sections       -> revolve
stable translated profile               -> extrude
unchanged profile transported on a path -> sweep
ordered changing section family         -> loft (with or without a path)
verified equal angular/linear units     -> one unit + pattern
several local signatures                -> ordered mixed feature tree
```

Use the analysis-evidence rows to choose the first candidate's operations and
parameters. Record a provenance row per region: observed boundary, adjacent-carrier
evidence, catalog `feature_id`, proposed operation, direction/axis/path,
confidence, and the check that could falsify it. A loop on a final planar face
may be a later hole or pocket, not part of the base profile. Every entry in
`unresolved-features.md` and every soft-gate gap stays an explicit unexplained
or low-confidence region. When the catalog does not answer a question, inspect
the target directly through `domains/step-inspection.md`.
If the catalog has zero candidates, treat the whole body as unresolved:
inspect its face carriers, cap/section sequence, and material role before
choosing a first operation. Record that operation as a manual hypothesis with
the measured evidence and a falsification check. Zero candidates do not mean
that the body has no reconstructable features, and a manual hypothesis does
not become an automatic recognition result.

### R2: Check capability and parameters

For each candidate operation, read its exact API page and check signature,
section closure and order, boolean role, point terminals, and path/guide
constraints. Classify it as `native`, `emulated`, `planned`, or
`unsupported` (the loft/sweep handoff already carries a capability state).
Never execute `planned` or `unsupported`; an `emulated` choice records the
lost constraint and the check that will measure its effect.

### R3: Build the minimal candidate

Build the initial candidate from `analysis-evidence.md` via
`single-part-modeling.md` (block structure per
`discipline/feature-tree-convention.md`; sketch tier when constraints
represent the evidence (`domains/sketch-and-features.md`), direct geometry
tier for non-planar or exact transcription, annotated `profile=geometry`
honestly). Start with the base and one representative local feature, then
extend. Overshoot through-cut tools; validate one representative feature
before patterning. Loading the target STEP is never a reconstruction.

### R4: Replay and export

Run a marimo candidate in a fresh process with `run_notebook` or `sca run`,
capture its definition as `.scadpkg`, then export STEP from that package in a
separate process. For a `GraphSession` candidate, use its matching
`export_model_json` → `replay_model_json` route instead. The two JSON schemas
are different; do not pass notebook or package feature-graph JSON to
`replay_model_json`. Run `validate_step_roundtrip_rdescriptor` on the exported
STEP. Record the failing operation on any failure and repair before comparing.

### R5: Compare

Use `domains/step-inspection.md`:
`compare_global_properties_rdescriptor` → scoped
`compare_boundary_distance_rdescriptor` (≤200 samples, face-id scoped) →
`compare_material_rdescriptor(include_components=True)` for strict proof →
`compare_steps_rbrepcomparison` for the exact gate. Use
`track_section_contours_rdescriptor` when section topology
(birth/death/split/merge) is the open question,
`fit_face_analytic_rdescriptor` to test carrier families,
`render_step_comparison_rpath` for shared-view visual evidence.
If a Boolean result is invalid or a comparison times out, mark material
equality `unproven`, retain the failure record, and use bounded sections and
face-scoped boundary samples to localize the difference. Do not accept a
candidate on global volume, area, or screenshots alone.
For each `feature_id` in `feature-index.json`, compare the target region with
the corresponding candidate region using the feature's dimensions, section
shape, location, adjacency, and material role. Record `built_and_matched`,
`built_but_mismatched`, or `not_built` with the evidence. A global comparison
cannot stand in for this feature-by-feature check.

### R6: Iterate from the error

After a failed feature check or strict comparison, group causes with
`BRepComparison.to_error_summary()` where available. Correct an evidenced
parameter error first; if the chosen operation still fails to reproduce the
reported feature, return to R1/R2 and try another supported operation. Record
why the prior operation failed and how the replacement uses the analysis
evidence, then rerun a fresh R3-R5 cycle.

### R7: Accept and deliver

Accept per the hierarchy (`domains/step-inspection.md`): topology identity is
the endpoint; float-level serialization drift is acceptable; a structurally
different but visually close stop requires recorded evidence that no better
feature order exists or the SDK lacks the operation.
The feature checklist must have an outcome for every recognized `feature_id`.
Acceptance requires every in-scope recognized feature to be
`built_and_matched`; any `built_but_mismatched` or `not_built` entry blocks
acceptance unless its unsupported or unresolved limitation is explicitly
justified under the hierarchy and reported as incomplete reconstruction.

## Validation gates

- One compact iteration row per attempt: hypothesis, changed parameters,
  replay/roundtrip status, diagnostic deltas, strongest proof attempted.
- Preserve the best valid candidate; repeated non-improvement changes the
  feature hypothesis instead of blind parameter tuning.
- Global similarity never overrides a locally falsified feature.
- The feature checklist covers every catalog feature exactly once and cites
  target and candidate evidence for each verdict.

## Failure routes

- Prelude phase fails or an R0 hard gate fails → rerun Phase 1-9 or report
  the failed phase; do not start R1.
- No affordable evidence for a region → record the gap; do not invent
  geometry and call it recovered.
- Candidate structurally different → re-open the feature-tree hypothesis
  before accepting a visual-close stop.
- Reconstruction tooling absent (`inspect` extra not installed) → report the
  missing capability rather than degrading silently.

## Deliverables

The analysis package path, `analysis-evidence.md`, candidate source path,
replay evidence, per-feature checklist, comparison evidence with verdict and
its acceptance tier, provenance rows, and explicitly unrecovered regions with
their reasons, including every soft-gate gap.

**Required reading before authoring or editing any part source in this
workflow:** `discipline/feature-tree-convention.md` — the block-structured
sketch → basic body op → bool → modifier convention, its mandatory boundary
comments, and the sketch/geometry/primitive tier rules. Every part source
is a marimo notebook, one block per cell
(`references/docs/guides/notebook-runtime.md`): run it with `sca run`, and
load its product from verification scripts with
`simplecadapi.runtime.run_notebook(...)`.
