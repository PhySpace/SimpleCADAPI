# Workflow: STEP Reconstruction

Rebuild an editable SimpleCAD model from an existing STEP file, with evidence
gathering, feature-tree inference, candidate construction, and tiered
acceptance.

## Goal and scope

Use when the deliverable is an editable/replayable model reproducing a target
`.step`/`.stp`. Not for read-only questions about a STEP file — those stay in
`domains/step-inspection.md` without reconstruction. When a human operator is
available to annotate feature intent on the target, run the variant workflow
`references/workflows/reverse-engineering-studio.md` instead of this
autonomous path.

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
  - target evidence notes (summaries, entity descriptors, sections)
  - feature-tree hypothesis with provenance rows
  - candidate source and replayed model
  - comparison evidence and acceptance verdict
validation_gates:
  - replay succeeds in a fresh process
  - STEP roundtrip of the candidate validates
  - acceptance follows the hierarchy (topology identity > float drift > justified stop)
repair_routes:
  - comparison fails -> step-inspection (localize) then part-modeling (fix feature)
  - global similarity but locally falsified feature -> change the feature hypothesis
```

## Steps

1. **Refine the requirement**: what fidelity is required (exact transcription
   vs functional equivalence), which components are in scope, what acceptance
   means here.
2. **Inventory the target economically**
   (`domains/step-inspection.md`): `inspect_step_rsummary` (with
   `include_parameter_groups=True` once), entity descriptors for specific
   hypotheses, compact boundaries/sections. Persist large arrays to files, not
   conversation context. Read
   `references/inspect/brep-reverse-engineering.md` completely first.
3. **Infer feature families** from carrier and section behavior
   (`references/docs/guides/reconstruction-agent-strategy.md`):

   ```text
   shared axis + rotational sections       -> revolve
   stable translated profile               -> extrude
   profile transported along a path        -> sweep
   ordered changing section family         -> loft
   verified equal angular/linear units     -> one unit + pattern
   several local signatures                -> ordered mixed feature tree
   ```

   Record a provenance row per region: observed boundary, adjacent-carrier
   evidence, proposed operation, direction/axis, confidence, and the check
   that could falsify it. A loop on a final planar face may be a later hole or
   pocket, not part of the base profile.
4. **Build the candidate** via `single-part-modeling.md` (block structure per
   `discipline/feature-tree-convention.md`; sketch tier when constraints
   represent the evidence (`domains/sketch-and-features.md`), direct
   geometry tier for non-planar or exact transcription, annotated
   `profile=geometry` honestly). Overshoot
   through-cut tools; validate one representative feature before patterning.
5. **Replay in a fresh process**: `export_model_json` →
   `replay_model_json`; then `validate_step_roundtrip_rdescriptor` on the
   candidate's STEP export.
6. **Compare and iterate** (`domains/step-inspection.md`):
   `compare_global_properties_rdescriptor` → scoped
   `compare_boundary_distance_rdescriptor` (≤200 samples, face-id scoped) →
   `compare_material_rdescriptor(include_components=True)` for strict proof →
   `compare_steps_rbrepcomparison` for the exact gate. Use
   `track_section_contours_rdescriptor` when section topology
   (birth/death/split/merge) is the open question,
   `fit_face_analytic_rdescriptor` to test carrier families,
   `render_step_comparison_rpath` for shared-view visual evidence. After a
   failed strict comparison, group causes with
   `BRepComparison.to_error_summary()`, fix related groups together, rerun a
   fresh cycle.
7. **Accept per the hierarchy** (`domains/step-inspection.md`): topology
   identity is the endpoint; float-level serialization drift is acceptable;
   a structurally different but visually close stop requires recorded evidence
   that no better feature order exists or the SDK lacks the operation.

## Validation gates

- One compact iteration row per attempt: hypothesis, changed parameters,
  replay/roundtrip status, diagnostic deltas, strongest proof attempted.
- Preserve the best valid candidate; repeated non-improvement changes the
  feature hypothesis instead of blind parameter tuning.
- Global similarity never overrides a locally falsified feature.

## Failure routes

- No affordable evidence for a region → record the gap; do not invent
  geometry and call it recovered.
- Candidate structurally different → re-open the feature-tree hypothesis
  before accepting a visual-close stop.
- Reconstruction tooling absent (`inspect` extra not installed) → report the
  missing capability rather than degrading silently.

## Deliverables

Candidate source path, replay evidence, comparison evidence with verdict and
its acceptance tier, provenance rows, and explicitly unrecovered regions.

**Required reading before authoring or editing any part source in this
workflow:** `discipline/feature-tree-convention.md` — the block-structured
sketch → basic body op → bool → modifier convention, its mandatory boundary
comments, and the sketch/geometry/primitive tier rules. Every part source
is a marimo notebook, one block per cell
(`references/docs/guides/notebook-runtime.md`): run it with `sca run`, and
load its product from verification scripts with
`simplecadapi.runtime.run_notebook(...)`.
