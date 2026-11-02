# Task Domain: STEP/BREP Inspection

**Read when:** the input is an existing `.step`/`.stp` file and you need facts out of it, or a reconstruction candidate must be compared against a target STEP (details under "Use when").

Extract bounded geometric facts from existing STEP files, compare targets and
candidates, and gather reconstruction evidence with the
`simplecadapi.inspect.brep` namespace.

## Use when

- The input is an existing `.step`/`.stp` file and the question is about its
  geometry: counts, dimensions, carriers, sections, neighborhoods, components.
- A reconstruction candidate must be compared against a target STEP.
- Visual evidence (entity maps, region highlights, comparison renders) is
  needed for review.

## Do not use

- Building or editing geometry: these functions are diagnostic, not modeling
  operations.
- Any call inside `GraphSession`: inspection functions are rejected there.
  Export or obtain the geometry first, then inspect outside the modeling
  script.

## Normative references

- `references/inspect/brep-reverse-engineering.md` — read completely before any
  inspection or target/candidate comparison work.
- `references/docs/guides/reconstruction-agent-strategy.md` — advisory tactics
  only.
- `references/docs/guides/reconstruction-agent-test-prompt.md` — the controlled
  run contract for reconstruction trials.

## API groups

Read the exact page under `references/docs/api/` for every API used:

- Inventory: `inspect_step_rsummary` (entity counts, bounds, volume, area,
  centroid, carrier statistics; `include_parameter_groups=True` for analytic
  radius/degree groups), `inspect_step_rbrepinspection` (full knot/multiplicity
  data).
- Local evidence: `inspect_step_entity_rdescriptor` (stable zero-based ids like
  `face:0`), `inspect_topology_neighborhood_rdescriptor`,
  `inspect_face_boundaries_rdescriptor` (prefer `compact=True`),
  `inspect_section_rdescriptor`, `inspect_point_rdescriptor`,
  `inspect_nearby_entities_rdescriptor`, `inspect_topology_rdescriptor`,
  `measure_entity_relation_rdescriptor`, `measure_shape_mass_rtuple`.
- Reuse across queries: `load_step_rbrepmodel`, `load_step_rshape`,
  `index_shape_rbrepmodel`, `clear_step_model_cache_rnone`.
- Comparison: `compare_global_properties_rdescriptor`,
  `compare_material_rdescriptor`, `compare_boundary_distance_rdescriptor`,
  `compare_entities_rdescriptor`, `compare_sections_rdescriptor`,
  `inspect_difference_regions_rdescriptor`, `compare_shapes_rbrepcomparison`,
  `compare_steps_rbrepcomparison`, `evaluate_reconstruction_rdescriptor`.
- Rendering: `render_entity_map_rpath`, `render_entity_kind_maps_rpath`,
  `render_region_rpath`, `render_shape_views_rpath`,
  `render_step_views_rpath`, `render_step_components_rpath`,
  `render_step_components_colored_rpath`, `render_screenshot_rpath`,
  `select_region_entities_rdescriptor`.
- Reconstruction evaluation: `fit_face_analytic_rdescriptor` (test whether a
  sampled face is planar/spherical/cylindrical/conic; residuals are evidence,
  not recovered feature history), `track_section_contours_rdescriptor`
  (contour continuation/birth/death/split/merge across ordered sections),
  `validate_step_roundtrip_rdescriptor`, `render_step_comparison_rpath`
  (Original-vs-Reconstructed shared views/camera/scale).
- Benchmark/evaluation harness — a separate import surface at
  `simplecadapi.inverse_engineer.brep` (not `inspect.brep`):
  `EvaluationConfig`, `SectionEvaluationConfig`, `classify_benchmark_result`,
  `inspect_benchmark_step`, `run_comparison_bundle`. Section results are
  diagnostics, not acceptance gates.

There is no fixed pipeline. Start with the cheapest evidence that can falsify
the current hypothesis; escalate only when the question requires it:

| Question | Preferred primitives |
| --- | --- |
| Global size, mass, topology scale | `inspect_step_rsummary`, `compare_global_properties_rdescriptor` |
| Single face/edge parameters and adjacency | `inspect_step_entity_rdescriptor`, `inspect_topology_neighborhood_rdescriptor` |
| Map stable ids to visual entities | `render_entity_map_rpath` |
| Section profile, wall thickness | `inspect_section_rdescriptor`, `compare_sections_rdescriptor` |
| Assembly tree visualization | `inspect_step_components_rdescriptorlist`, `render_step_components_rpath` |
| Where the difference is | `compare_material_rdescriptor`, `inspect_difference_regions_rdescriptor` |
| Local geometric error | `compare_boundary_distance_rdescriptor`, `compare_entities_rdescriptor` |
| Final exact-BREP gate | `compare_shapes_rbrepcomparison`, `compare_steps_rbrepcomparison` |

## Acceptance hierarchy

1. BREP topology identity is the best endpoint (complete reconstruction).
2. Identical structure with minor float-level parameter drift from export is
   acceptable and not a failure.
3. Structurally different but visually close is a valid stop only when no
   better feature operation order/combination exists or the SDK lacks the
   required operation type, with evidence recorded.

## Validation gates

- Strict material proof and reusable difference regions require
  `compare_material_rdescriptor(include_components=True)`; the estimate mode is
  diagnostic only.
- Start `compare_boundary_distance_rdescriptor` at ≤200 samples and scope by
  face ids; pass results forward as `boundary_result` to avoid recomputation.
- After strict comparison, use `BRepComparison.to_error_summary()` to group
  failed checks by plausible common root cause; fix related groups together,
  then rerun a fresh replay/export/compare cycle.
- Visual similarity from `render_step_comparison_rpath` never replaces strict
  BREP comparison.

## Failure modes

- Assuming entity ids imply semantic correspondence between two different
  models: ids are stable per unmodified BREP only.
- Fuzzy boolean tolerance in comparison: diagnostic only, never an acceptance
  gate.
- Untrimmed carrier definitions without UV range/trim-loop/seam evidence are
  incomplete evidence.
