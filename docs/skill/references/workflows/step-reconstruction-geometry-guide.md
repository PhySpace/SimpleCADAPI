# STEP Reconstruction: Local Geometry Analysis Guide

This guide preserves the local STEP analysis method. For modeling operations,
follow the upstream `step-reconstruction.md` workflow and the installed
SimpleCADAPI API. The recovered geometry remains evidence, not an executable
operation history.

Extract geometric evidence from an existing `.step`/`.stp` file, infer its
feature tree, and rebuild it as an editable, replayable, and verifiable
SimpleCADAPI model.

## 1. Scope

Use this workflow when the deliverable is a newly modeled reconstruction based
on a target STEP.

The following tasks do not enter this workflow:

- read-only questions about dimensions, topology, surfaces, or assemblies:
  use `references/domains/step-inspection.md`;
- requests for computational-geometry evidence and local visual artifacts
  without an editable candidate: use
  `references/workflows/step-computational-geometry-analysis.md`;
- format conversion or export only: use the export workflow;
- loading the target STEP directly or copying an entire Solid as the final
  model: neither constitutes reconstruction.

## 2. Non-negotiable rules

### 2.1 The final program must contain actual modeling operations

The final reconstruction program must call public modeling APIs inside an
explicit `GraphSession`, and the upstream operation chain of its final result
must contain at least one `constructive_modeling` operation.

Modeling operations include:

- creating and constraining sketches;
- extruding, revolving, sweeping, and lofting;
- creating primitives;
- fitting surfaces, creating surface patches, and other surface construction;
- union, cut, and intersection;
- patterns, fillets, chamfers, and other geometric modifiers.

The following are not modeling operations:

- STEP/BREP inspection and measurement;
- importing, replaying, or exporting model JSON;
- exporting STEP, rendering images, or printing reports;
- tags, metadata, and selection operations;
- `copy_step_region_rpath`;
- `load_brep_region_rshell` or `load_brep_region_rsolid`;
- geometry obtained by directly reading the target STEP.

A program containing only inspection, copying, loading, import, replay, or
export operations must fail. Even when controlled spline-face copying is
authorized, copied faces may only supplement local regions that public APIs
cannot construct to the required quality. They cannot replace actual modeling
operations in the final program.

The final audit must require:

```text
result_reachable_constructive_modeling_operation_count >= 1
```

`transcription_load` nodes alone cannot pass this gate.

### 2.2 Outputs must be traceable

The final program must:

1. use an explicit `GraphSession`;
2. capture the intended result with `capture_result`;
3. store the exact model JSON returned by `export_model_json`;
4. export the candidate STEP;
5. produce a topologically ordered operation sequence;
6. pass a model audit bound to the final source.

Do not hand-author model JSON. Source scanning and prose feature lists are not
substitutes for a model operation graph.

### 2.3 Isolate the target from the output directory

Treat the target STEP and its directory as read-only. Final replay must not read
the target STEP.

The reconstruction source, parameters, model JSON, candidate STEP, comparison
reports, logs, renders, sidecars, and manifest must all be under the absolute
output directory specified by the user. Do not start without an output
directory, and do not invent a default `out/`.

The output directory has two layers: the prelude analysis package goes to
`<absolute-output-directory>/analysis/` and is read-only after Phase 9; every
reconstruction artifact goes to `<absolute-output-directory>/reconstruction/`,
never into `analysis/`. Replacing the analysis package invalidates every result
in `reconstruction/` derived from it.

## 3. Workflow overview

```text
Target STEP
   |
   v
1. Define requirements and acceptance criteria
   |
   v
2. Computational-geometry prelude (Phases 1-9, route reconstruction_prelude)
   + validate and load the analysis package (R0)
   |
   v
3. Infer the feature tree
   |
   v
4. Build a candidate with public APIs  <-----------------+
   |                                                     |
   v                                                     |
5. Audit + fresh-process strict replay + STEP roundtrip  |
   |                                                     |
   v                                                     |
6. Tiered comparison --- fail: localize the cause and ---+
   |                          repair the owning feature
   |
   +---- acceptance criteria pass: deliver
   |
   +---- only spline faces keep failing: enter controlled fallback gates
```

Execute the phases serially. A later phase cannot be declared successful until
the preceding phase has produced its required artifacts and passed its gates.

## 4. Required reading before work

Before inspecting a STEP, read both of these files completely:

- `references/inspect/brep-reverse-engineering.md`;
- `references/domains/step-inspection.md`.

Before authoring or editing any part source, read
`references/discipline/feature-tree-convention.md` completely and follow its
feature blocks, mandatory boundary comments, and rules for choosing Sketch,
direct geometry, or primitives.

## 5. Main workflow

### Phase 1: Define requirements and acceptance criteria

**Inputs**

- target STEP;
- the user's reconstruction goal.

**Actions**

Read `references/domains/requirement-refinement.md` and write a short brief
that establishes:

- the absolute target STEP path and SHA-256;
- the user-specified absolute output directory;
- the reconstruction scope: one part, multiple parts, or a full assembly;
- the fidelity goal: topology identity, structural equivalence, functional
  equivalence, or another explicit target;
- acceptance thresholds for dimensions, area, volume, centroid, material
  regions, topology, and freeform surfaces;
- the unit and source of each threshold;
- whether target-derived spline-face copying is permitted.

**Artifacts**

- requirement brief;
- bound output directory.

**Gate**

- scope, output directory, and acceptance criteria are defined;
- every unresolved item has been asked or recorded as an explicit assumption;
- metrics without a threshold may only be reported, not declared passing or
  unsupported.

### Phase 2: Run the analysis prelude and load its package

**Inputs**

- target STEP;
- requirement brief.

**Actions**

1. Run Phases 1-9 of
   `references/workflows/step-computational-geometry-analysis.md` with route
   `reconstruction_prelude`, output directory
   `<absolute-output-directory>/analysis/`, all eight feature kinds, and a
   recorded render budget. That workflow owns required reading, recognition,
   sections, visuals, and packaging; a failed phase stops reconstruction.
2. Validate the package per R0 of `step-reconstruction.md`. Hard gates: target
   hash, recognition parameters in `analysis-config.json`, catalog and
   `reconstruction` `schema_version`, SDK version, file hashes in
   `artifact-manifest.json`, `truncated=false`, and `complete=true`. Any
   mismatch reruns Phases 1-9; never patch the package. Soft gate: under
   `complete_with_gaps`, features with skipped visuals or `incomplete`
   specialist entries may enter Phase 3 with lowered confidence and are
   reported at delivery.
3. Load `feature-index.json`, `reconstruction-hypotheses.json`,
   `loft-sweep-specialist.json`, `section-index.json`, `parse-report.md`, and
   `unresolved-features.md`.
4. For a specific question the package does not answer, inspect the target
   directly through `references/domains/step-inspection.md`, least to most
   expensive: request complete curve or surface definitions only for selected
   entities, and save large control-point, knot-vector, and sample arrays under
   `reconstruction/`.

**Artifacts**

- the analysis package that passed R0 (its path recorded in
  `reconstruction/`);
- supplementary entity, neighborhood, boundary, and section evidence with a
  stated purpose;
- unresolved-region list, including `unresolved-features.md` and every
  soft-gate gap.

**Gate**

- the package passes every hard gate;
- every later feature hypothesis is grounded in target evidence;
- catalog entries are treated only as evidence; an absent, conflicting,
  or non-strong entry returns to entity, neighborhood, boundary, and section
  inspection rather than becoming an inferred operation;
- no geometry is inferred solely from a render or visual impression;
- matching face IDs in the target and candidate are not assumed to represent
  the same semantic face.

### Phase 3: Infer the feature tree

**Inputs**

- target evidence;
- unresolved-region list.

**Actions**

Use `references/docs/guides/reconstruction-agent-strategy.md` to infer feature
families:

```text
shared axis + rotational sections        -> revolve
stable profile translated in one direction -> extrude
profile transported along a path         -> sweep
ordered continuously changing sections   -> loft
verified equal angular or linear spacing  -> one seed feature + pattern
several local geometric signatures        -> ordered mixed feature tree
```

For every loft/sweep candidate, consume its versioned `reconstruction` handoff
from `reconstruction-hypotheses.json`, whose target hash and schema R0 already
validated.
The specialist result is evidence, not executable history. Choose the least
complex supported operation that explains the ROI:

```text
rigid profile + recovered path                 -> sweep_rsolid
variable profiles, no required path            -> loft_rsolid / loft_rshell
variable profiles + recovered path             -> loft_rsolid / loft_rshell as an approximation; path remains evidence
one auxiliary orientation spine                -> unsupported as a frame constraint in the upstream API
multiple boundary guides                       -> validated surface network, otherwise unsupported
```

Use `terminal_mode` to distinguish no point, start/end point, and both-point
lofts. An interior point splits the reconstruction into two operations. Do not
promote a fitted path or guide to original authoring intent, and do not select
a `planned` or `unsupported` operation as if it were native.

For every base, hole, slot, notch, boss, or freeform region, record:

- observed boundary or section;
- adjacent-carrier and continuation evidence;
- proposed modeling operation;
- direction, axis, datum plane, or path;
- confidence;
- the check that can falsify the hypothesis.

A closed loop on a final planar face may belong to a later hole, slot, or
pocket; do not automatically fold it into the base profile. Repetition and
symmetry must also be verified against the position, direction, spacing, and
adjacency of at least two instances.

Write each accepted catalog feature into the per-region provenance table
and the ordered feature-tree hypothesis. Keep a falsification task for every
conflict or non-strong candidate. The detailed hole and extrusion-style
subtypes, ownership rules, alternatives, and confidence interpretation
are defined in `references/inspect/brep-reverse-engineering.md`; hint ordering
does not choose the final feature order. Evidence and later target/candidate
comparison still determine that order.

**Artifacts**

- ordered feature-tree hypothesis;
- per-region provenance table;
- first candidate construction plan.

**Gate**

- every proposed feature traces to evidence;
- every low-confidence hypothesis has an explicit falsification check;
- the order of the base, additive features, subtractive features, and modifiers
  is defined.

### Phase 4: Build the candidate with public APIs

**Inputs**

- feature-tree hypothesis;
- per-region provenance table.

**Actions**

Build one-part candidates through
`references/workflows/single-part-modeling.md`. Enter assembly modeling only
when evidence establishes multiple physical components.

Source must follow `references/discipline/feature-tree-convention.md`:

```text
sketch -> basic body operation -> boolean -> modifier
```

Place each feature in its own block with the required feature-boundary comment.
Prefer Sketch for planar design profiles. Direct geometry is appropriate for
non-planar paths, freeform surfaces, or relationships that Sketch cannot
represent, but label it honestly; do not describe coordinate locking or fitting
as recovered design intent.

During construction:

- complete the base first, then add or subtract local features in evidence-backed
  order;
- overshoot through-cut tools to avoid coincident terminal faces;
- validate one representative feature before creating a pattern;
- print small QL-derived facts after each major step;
- when a boolean fails, repair its operands, intersection, or feature order;
  never call a skipped boolean successful.

Before every loft call, inspect section order, closure, orientation, and
compatible topology. Treat non-monotonic stations or opposed section normals
as repair tasks, not kernel trial-and-error. The upstream API accepts ordered
sections and `ruled` for `loft_rsolid` or `loft_rshell`; it does not accept a
path or auxiliary spine constraint. If the recovered path matters, mark a
section-only loft as an approximation and verify it against the target.

Endpoint tangent, draft-angle, curvature, and magnitude constraints are not
portable in the upstream section-loft backend. Keep such conditions as evidence
and choose a documented approximation or unsupported result; never silently
drop them.
Always keep solid/shell and ruled/smooth decisions evidence-backed. Do not call
`MakeSolid` when endpoint closure is absent, and do not force a multi-rail
surface network through the auxiliary-spine API.

**Artifacts**

- SimpleCADAPI reconstruction source;
- API-produced model JSON;
- candidate STEP for this iteration.

**Gate**

- the final result is produced by an explicit `GraphSession` and
  `capture_result`;
- the final result has at least one actual modeling operation upstream;
- the candidate was not obtained by directly loading the target STEP or by a
  whole-Solid copy;
- model JSON is the exact output of `export_model_json`.

### Phase 5: Audit, strict replay, and roundtrip

**Inputs**

- final source;
- model JSON produced by that source;
- candidate STEP.

**Actions**

Produce a topologically ordered operation sequence, then run API import,
fresh-process strict replay, and STEP roundtrip against the final-source-bound
model JSON.

Classify audited operations as:

- `constructive_modeling`: actual modeling operations;
- `transcription_load`: loading copied target-derived regions;
- `selection_or_annotation`: selection, tag, or annotation operations;
- `non_geometry`: import, export, reporting, and other non-geometric
  operations.

**Artifacts**

- operation sequence;
- model audit bound to the final source;
- fresh-process strict replay evidence;
- STEP roundtrip report.

**Gate**

- public API import accepts the model JSON;
- `strict=True` replay succeeds and returns geometry;
- explicit result IDs are non-empty and resolvable;
- the operation sequence is non-empty;
- `result_reachable_constructive_modeling_operation_count >= 1`;
- no whole-Solid copy exists;
- roundtrip validation passes;
- SHA-256 binds the source, model JSON, operation sequence, and audit report.

Any final source edit invalidates all of these artifacts; rerun this phase.
When the required audit capability is unavailable, stop acceptance and report
the missing capability. Do not degrade to source inspection, ordinary replay,
or visual judgment.

### Phase 6: Compare and iterate

**Inputs**

- a candidate that passed Phase 5;
- target STEP;
- acceptance criteria.

**Actions**

Compare in this order:

1. `compare_global_properties_rdescriptor`: dimensions, area, volume, and
   centroid;
2. `compare_boundary_distance_rdescriptor`: localize error with no more than
   200 samples and explicit face scope;
3. `compare_material_rdescriptor(include_components=True)`: strict material
   difference;
4. `compare_steps_rbrepcomparison`: the final exact gate when exact BREP is
   required.

Use these diagnostics when needed:

- `track_section_contours_rdescriptor` for section births, deaths, splits,
  and merges;
- `fit_face_analytic_rdescriptor` to test analytic-carrier hypotheses;
- `render_step_comparison_rpath` for human review under a shared view.

Renders are review evidence, not a substitute for strict comparison. After a
strict comparison fails, use `BRepComparison.to_error_summary()` to group
likely common causes, repair the owning upstream features, and return to Phase
4 for a fresh build, audit, replay, roundtrip, and comparison.

Record every attempt with:

- a unique positive integer iteration number;
- status `complete` or `failed_attempt`;
- hypothesis, operation order, and exact parameter changes;
- replay, BREP validity, and roundtrip status;
- candidate STEP path and SHA-256;
- global, local, material, and exact comparison summaries;
- whether it became the best candidate and the supporting evidence;
- the question to falsify next.

A `complete` iteration requires successful fresh-process replay, a newly
generated candidate STEP, a valid target-kind BREP, a valid roundtrip, and a
recorded candidate SHA-256. Every other attempt is `failed_attempt`.

**Artifacts**

- iteration log;
- tiered comparison reports;
- best valid candidate bound by hash.

**Gate**

- the candidate meets the Phase 1 acceptance criteria; or
- sufficient evidence supports a stop under the acceptance hierarchy; or
- only target spline faces remain failing and the prerequisites for controlled
  fallback evaluation are met.

Always preserve the best valid candidate. One parameter correction may retain
the current construction strategy. Repeated non-improvement must change the
feature hypothesis instead of blindly enumerating parameters. Global similarity
cannot override a feature falsified by local evidence.

## 6. Controlled spline-surface fallback

Target-derived face copying is forbidden by default. It is available only for
local spline faces and cannot replace actual modeling in Phase 4.

### 6.1 Gate for considering a copy

All of these conditions must hold:

1. at least three `complete` iterations or at least five well-formed total
   iterations exist;
2. the evaluated candidate is the best valid complete candidate so far, and
   its SHA-256 matches the iteration log;
3. the requirement brief defines an explicit spline-face distance or area
   threshold;
4. at least one target spline face in the best candidate still exceeds that
   threshold;
5. every B-spline/Bezier face in the target STEP has been enumerated;
6. every target spline face has searched every face in the candidate STEP,
   without filtering by candidate carrier type;
7. every target spline-face mapping is evidence-backed `resolved`, with no
   `ambiguous` or `unmatched` result;
8. every applicable public-API modeling sequence supported by the evidence has
   been executed and recorded as failing the quality requirement;
9. an ordinary task has explicit user authorization, or a controlled trial is
   in `exact_brep_transcription` mode;
10. the proposed copy contains only failing target spline faces and forms a
    connected valid Shell.

These conditions may only set `copy_consideration_ready=true`. That value
means the quantitative evidence is complete; it neither grants authorization
nor triggers copying automatically.

A corresponding candidate may be one face or several faces, with any carrier
type. Use single-entity comparison only for a proven one-to-one mapping.
One-to-many or many-to-one mappings require bidirectional boundary-distance and
area-error comparison over the face set.

### 6.2 Restrictions when copying

- `copy_step_region_rpath` must receive an explicit, non-empty `face_ids`;
- face IDs may contain only target B-spline/Bezier faces that exceed the
  threshold;
- never copy a non-spline face, omit `face_ids`, or copy a whole Solid;
- the sidecar must be a connected valid Shell under the output directory;
- final source may load the sidecar only through a relative path and bound
  SHA-256;
- final replay must not read the target STEP;
- record copied regions as
  `copied / transcribed / retained / embedded_target_derived`;
- never describe copied carriers, trims, pcurves, or topology as recovered
  feature history.

When copying is used, write a `simplecadapi.spline-copy-decision/1` record
binding the target, best candidate, iteration log, quantitative report,
authorization evidence, target face IDs, sidecar relative path, and SHA-256.

The final audit must inspect copy calls in source, the actual faces in every
`.scadbrep`, and the decision evidence. It must pass:

- `source_copy_calls_allowed`;
- `copied_faces_are_spline_surfaces_only`;
- `copy_gate_evidence_valid`;
- whole-Solid copy absent;
- `result_reachable_constructive_modeling_operation_count >= 1`.

The last gate ensures that the final program still contains actual modeling
operations even when spline sidecars are used.

## 7. Acceptance hierarchy

Evaluate results in this order. Lower-tier evidence cannot override a
higher-tier gate failure:

1. **Topology identity**: reconstruction is complete;
2. **Structural identity with serialization-only float drift**: acceptable
   when supported by recorded evidence;
3. **Structurally different, justified stop**: deliver only when evidence shows
   that no better feature order exists or the SDK lacks the required operation,
   and all differences and unrecovered regions are explicit;
4. **Visual similarity only**: not acceptable.

The final reconstruction program must pass the actual-modeling-operation gate
at every acceptance tier.

## 8. Failure routes

| Failure | Required response |
| --- | --- |
| The prelude fails or an R0 hard gate fails | Rerun Phases 1-9 or report the failed phase; do not enter Phase 3 |
| Evidence for a region is insufficient | Record the evidence gap; do not invent geometry |
| Local evidence falsifies a feature family | Return to Phase 3 and revise the feature hypothesis and order |
| A boolean or construction fails | Return to Phase 4 and repair operands, intersection, or upstream parameters |
| No result-reachable actual modeling operation exists | Rewrite the final program; copying or loading cannot substitute |
| Model audit, strict replay, or roundtrip fails | Repair final source or the `GraphSession`, then rerun Phase 5 |
| Comparison fails | Localize the common cause and return to Phase 3 or Phase 4 |
| Spline iteration count is insufficient | Continue public-API modeling; copying is unavailable |
| A spline mapping is `ambiguous` or `unmatched` | Improve correspondence search; copying is unavailable |
| No explicit threshold or authorization exists | Deliver the best modeled candidate and difference report without copying |
| Reconstruction or audit tooling is unavailable | Report the missing capability; do not degrade silently |

## 9. Deliverables

### 9.1 Required

- the prelude analysis package path (`analysis/`) and its `run-status.json`
  status;
- final SimpleCADAPI reconstruction source;
- API-produced model JSON;
- topologically ordered operation sequence containing at least one
  result-reachable `constructive_modeling` operation;
- model audit bound to the final source;
- best candidate STEP;
- fresh-process strict replay and STEP roundtrip evidence;
- target evidence notes, feature-tree hypothesis, and per-region provenance;
- iteration log;
- tiered comparison reports, acceptance verdict, and acceptance tier;
- explicit unrecovered-region list;
- artifact manifest containing each artifact's role, byte size, and SHA-256.

### 9.2 Conditional

Add these only when the spline fallback gate triggers:

- exhaustive target-spline correspondence and quantitative comparison report;
- case-specific comparison code and numeric results;
- hash-bound `.scadbrep` sidecars;
- `simplecadapi.spline-copy-decision/1` record.
