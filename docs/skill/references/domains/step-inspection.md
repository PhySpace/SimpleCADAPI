# Task Domain: STEP/BREP Inspection

Extract bounded geometric facts from existing STEP files, compare targets and
candidates, and gather reconstruction evidence with the
`simplecadapi.inspect.brep` namespace.

## Use when

- The input is an existing `.step`/`.stp` file and the question is about its
  geometry: counts, dimensions, carriers, sections, neighborhoods, components.
- A complete local analysis package needs global evidence, all supported
  geometric candidates, feature highlights, and 2D section panels; compose
  those APIs through
  `references/workflows/step-computational-geometry-analysis.md`.
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
  `render_sections_rpath` (draw non-compact section descriptors in local 2D
  coordinates), `select_region_entities_rdescriptor`.
- Reconstruction evaluation: `fit_face_analytic_rdescriptor` (test whether a
  sampled face is planar/spherical/cylindrical/conic; residuals are evidence,
  not recovered feature history), `track_section_contours_rdescriptor`
  (contour continuation/birth/death/split/merge across ordered sections),
  `validate_step_roundtrip_rdescriptor`, `render_step_comparison_rpath`
  (Original-vs-Reconstructed shared views/camera/scale).
- Legacy manufacturing candidates: `inspect_manufacturing_hints_rdescriptor`,
  `render_manufacturing_hints_rpath`.
- Workflow-ready per-instance catalog: `inspect_geometric_features_rdescriptor`;
  saved-catalog overview rendering: `render_geometric_features_rpath`.
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
| Complete per-instance feature list and dimensions | `inspect_geometric_features_rdescriptor` with all requested categories |
| Render the exact saved catalog without recognition drift | `render_geometric_features_rpath` |
| Where the difference is | `compare_material_rdescriptor`, `inspect_difference_regions_rdescriptor` |
| Local geometric error | `compare_boundary_distance_rdescriptor`, `compare_entities_rdescriptor` |
| Final exact-BREP gate | `compare_shapes_rbrepcomparison`, `compare_steps_rbrepcomparison` |

Manufacturing-hint defaults remain the legacy fillet, chamfer, and sheet-metal
set. The v4 catalog explicitly defaults to hole, extrusion, revolution, loft,
sweep, fillet, chamfer, and sheet metal. Here `extrusion` means extrusion-style geometry, including
local bosses, ribs, pockets, slots, and through cuts; `whole_body_prism` is
only one subtype. Circular and shaped closed negative spaces all belong to
`hole`. `revolution` covers full/partial and whole/local regions around a
supported axis. A cylinder is reported once with revolution primary and
extrusion recorded as an alternative interpretation when both gates pass.
`loft` covers whole/local variable-section and point-terminal regions;
`sweep` covers whole/local path transport, twist, and helix geometry.
IDs are valid only for the same unmodified BREP, and every candidate
describes final geometry rather than feature history or manufacturing intent.

For a full parse artifact package, call
`inspect_geometric_features_rdescriptor` once and save its unchanged result as
`feature-index.json`. Reuse that catalog for per-instance reports, sections,
and `render_geometric_features_rpath`; the renderer validates the saved hash
and entity IDs and never reruns recognition. Compute detailed sections with
`inspect_section_rdescriptor(compact=False)` and render those saved descriptors
with `render_sections_rpath`. The route ends without candidate modeling, model
JSON, replay, roundtrip, or comparison.

Extrusion recognition compares selected loops after translation; complete
support-face area equality is diagnostic only. It requires parallel planes,
complete direction-consistent side walls, and measured 25%/50%/75% sections.
Revolution recognition clusters collinear axes, validates angular coverage and
meridian consistency, and refuses to invent an axis for an isolated sphere.

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
