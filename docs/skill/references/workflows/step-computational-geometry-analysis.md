# Workflow: STEP Computational-Geometry Analysis v4

Parse a STEP file into a complete, per-instance computational-geometry
artifact package without reconstructing an editable model.

## 1. Scope

Use this workflow for a complete STEP parse, supported feature inventory,
feature highlights, profile measurements, or section views. Use the inspection
domain for one read-only fact. Use `step-reconstruction.md` only for an
editable model or candidate STEP.

This workflow runs under exactly one route, recorded in Phase 1:

- `analysis_only`: the user asked for the analysis package; the run ends at
  Phase 9.
- `reconstruction_prelude`: `step-reconstruction.md` runs Phases 1-9 as its
  mandatory first stage. The package is produced exactly as for
  `analysis_only`, then `step-reconstruction.md` resumes at R0. The prelude is
  part of the reconstruction lifecycle, not a second route.

Every instance is a `geometric_candidate`: final-BREP evidence, not recovered
feature history, a unique command order, or manufacturing intent.

`extrusion` means extrusion-style geometry: whole-body prisms plus local
bosses, ribs/webs, blind pockets, open slots/notches, and through-cut regions.
It never means only a “whole-body straight-extrusion candidate”. Circular and
non-circular closed negative spaces are all holes. Special-shaped holes must
have `category="hole"`, never a peer category.

`revolution` is an independent category for a meridian profile rotated around
a stable axis. It includes whole-body and local regions, both full 360° and
partial-angle. A cylinder may support both extrusion and revolution; when the
complete revolution gate passes, revolution is primary and extrusion is an
`alternative_interpretations` entry in the same `conflict_group_id`.

`loft` is variable-section geometry supported by ordered profile sections,
including one- or two-point terminals and variable profiles constrained by a
recovered path. `sweep` transports a rigid
section along a path and includes path, twisted, and helical subtypes. These
are final-geometry claims only: straight rigid translation belongs to
`extrusion`, fixed-axis rotation belongs to `revolution`, and a rigid
transported section belongs to `sweep` before considering `loft`.

## 2. Non-negotiable boundaries

- Treat the target STEP and its directory as read-only.
- Require an isolated, user-specified absolute output directory.
- Run inspection outside `GraphSession` and keep one `BRepModel` index.
- Bind every record and artifact to one target STEP SHA-256.
- Run recognition once. Visualization consumes saved `feature-index.json` and
  must never rerun recognition.
- A truncated catalog is incomplete. Stop after the analysis package; under
  either route, no later stage may consume it.

**Explicit terminal boundary:** do not create model JSON, an operation
sequence, model audit, strict replay, roundtrip result, candidate STEP,
target/candidate comparison, or reconstruction iteration.

**Route-scoped termination:** the terminal boundary applies only to the
analysis package directory, under both routes. For `analysis_only`, the output
directory is the user's absolute directory and the task ends after Phase 9.
For `reconstruction_prelude`, the package lives in
`<absolute-output-directory>/analysis/`; after Phase 9 this workflow returns
control to R0 of `step-reconstruction.md`, which writes every reconstruction
artifact under `<absolute-output-directory>/reconstruction/`. This workflow
itself never writes into `reconstruction/`.

## 3. Inputs

- absolute `.step` or `.stp` target path;
- isolated absolute output directory;
- explicit feature kinds; v4 full analysis uses
  `("hole", "extrusion", "revolution", "loft", "sweep", "fillet", "chamfer", "sheet_metal")`;
- linear/angular tolerances and `max_features`;
- optional user section planes and recorded automatic section rules;
- deterministic rendering options;
- route: `analysis_only` or `reconstruction_prelude`;
- for `reconstruction_prelude` only, a render budget: the maximum number of
  per-feature visual sets and the per-render timeout.

Persist every default in `analysis-config.json` before analysis.

## 4. Required reading and API pages

Read `references/inspect/brep-reverse-engineering.md` and
`references/domains/step-inspection.md` completely. Then read the exact pages:

- `references/docs/api/inspect_step_rsummary.md`;
- `references/docs/api/inspect_geometric_features_rdescriptor.md`;
- `references/docs/api/render_geometric_features_rpath.md`;
- `references/docs/api/render_region_rpath.md`;
- `references/docs/api/inspect_section_rdescriptor.md`;
- `references/docs/api/render_sections_rpath.md`.

Legacy `inspect_manufacturing_hints_rdescriptor` and
`render_manufacturing_hints_rpath` remain available, but raw hints are not the
v4 user report. The legacy default remains fillet, chamfer, and sheet metal;
`hole`, `extrusion`, `revolution`, `loft`, and `sweep` are opt-in there.

## 5. Workflow

Execute all nine phases serially. On failure, write `run-status.json` with
`status="failed"`, the failed phase, and a bounded error summary, then stop.

### Phase 1: Freeze input and run parameters

Validate target existence, suffix, readability, and output isolation. Compute
the target hash. Write `requirement-brief.md`, `analysis-config.json`, and an
initial `run-status.json` with units, SDK version/platform/time, route,
feature kinds, tolerances, `max_features`, section stations, render options,
and the render budget when the route is `reconstruction_prelude`.

**Gate:** no hidden defaults; absolute paths, route, and target hash are on
disk.

### Phase 2: Build one BREP index and global summary

Load once, retain the same indexed `BRepModel`, and call
`inspect_step_rsummary`. Write `target-summary.json` with bounds, volume,
surface area, centroid, body/face/edge/vertex counts, surface statistics, and
units.

**Gate:** parsing and indexing succeed; never fall back to screenshots.

### Phase 3: Build shared geometric facts

Collect face carriers, parameters, area, centroid, normals, adjacency, ordered
outer/inner loops, curve types, material side, local frames, and profile
samples. Also build canonical collinear axis clusters from cylinder, cone,
torus, REVOLUTION carriers, and supporting circular edges. Measure
width/height, area, perimeter, directions, calipers, curve segments,
translated-loop correspondence, rotated-loop correspondence, and meridian
profiles. For loft/sweep analysis, also compute equal-arc-length profile
samples, cyclic/reversed Kabsch rigid fits, similarity fits, shared cap-to-cap
wall coverage, ordered actual BREP sections, contour tracks, and longitudinal
edge samples. Reuse one section-family result for loft and sweep. After a
bounded candidate passes the coarse gate, run the specialist pass only on its
ROI to recover global direction/seam alignment, path hypotheses, frame law,
explicit guides, guide attachments, endpoint conditions, profile laws, and
bounded station-refinement requests. This layer measures only; it does not
create reconstruction geometry.

**Gate:** all values are finite and use recorded units.

### Phase 4: Recognize categories and subtypes

Call `inspect_geometric_features_rdescriptor` once with every enabled kind.

- Extrusion-style: `whole_body_prism`, `local_boss`, `rib_or_web`,
  `blind_pocket`, `open_slot_or_notch`, `through_cut_region`.
- Revolution-style: `whole_body_full_revolution`,
  `whole_body_partial_revolution`, `local_full_revolved_boss`,
  `local_partial_revolved_boss`, `local_full_revolved_groove`,
  `local_partial_revolved_cut`.
- Loft-style: `whole_body_profile_loft`, `whole_body_point_loft`,
  `local_lofted_boss`, `local_lofted_cut`. Orthogonal fields record
  `coverage`, `region_role`, `terminal_kind`, `terminal_mode`,
  `interpolation`, `interpolation_by_span`, `loft_control_mode`, and
  `variation_law`.
- Sweep-style: `whole_body_path_sweep`, `local_swept_boss`,
  `local_swept_cut`, `twisted_sweep`, `helical_sweep`. Orthogonal fields
  record `coverage` and `region_role`; twist and helix measurements appear
  only when applicable.
- Holes: `circular_through`, `circular_blind`, `counterbore`, `countersink`,
  `circular_stepped`, `tapered_hole`, `obround_through`, `obround_blind`,
  `rectangular`, `polygonal`, `d_or_keyhole`, `freeform_profile`,
  `profile_stepped`.
- Fillets: `cylindrical_constant`, `toroidal_constant`, `spherical_corner`.
- Chamfers: `planar_bevel`, `conical_bevel`.
- Sheet metal: `flat_sheet_body`, `formed_sheet_body`, `cylindrical_bend`.

Write returned `raw_feature_hints` unchanged to `raw-feature-hints.json`;
write unsupported or insufficient evidence to `unresolved-features.md`.

**Gate:** a hole has a closed entry, material-side evidence, continuous walls,
and exit or bottom. An extrusion region has parallel carrier planes, at least
one translated loop pair with bidirectional correspondence, a translation
normal to those planes, complete direction-consistent side walls, and actual
BREP sections at 25%/50%/75%; complete face area similarity is recorded only
as diagnostic evidence and is not a required gate. Loop roles may legitimately
pair inner-to-outer; loops are paired by deterministic minimum cost rather than
list position. A revolution region has a supported collinear axis cluster,
axis-compatible carriers, a stable meridian profile, coherent angular coverage
and angular caps, closed local boundaries, and a clear material side.

A profile loft requires complete cap-to-side coverage, non-rigid endpoint
profiles, actual intermediate BREP sections, and contour tracking without an
unreported birth/death/split/merge. A point loft may have one or two shared
terminal vertices. A two-point terminal requires non-degenerate intermediate
sections; an interior point is not accepted as one loft operation. A sweep
requires complete coverage plus a
rigid endpoint-profile fit; straight translation is rejected in favor of
extrusion. Twisted sweeps require rotating rigid sections. Helical sweeps also
require a longitudinal edge with near-constant fitted radius and a high-quality
linear unwrapped-angle-to-axial fit that yields radius, pitch, turns, axis, and
handedness.

#### Phase 4b: Review loft/sweep candidates on their ROI

This is the second checkpoint of Phase 4, not a separate recognition run. For
every loft or sweep candidate that passed the coarse gate, read the specialist
result the same call returned under `geometry.specialist_analysis`: adaptive
sections, contour tracks, global seam alignment, path and frame hypotheses,
guides, and endpoint conditions. Write
`loft-sweep-specialist.json` with `target_sha256` and one entry per candidate
holding its hint ID, ROI entity IDs, `specialist_trigger.decision`, and the
unchanged `specialist_analysis`. A candidate whose analysis hit its budget or
could not be resolved keeps its coarse classification and is recorded as
`incomplete` with the reason; never force a subtype past the budget, and never
describe a fitted path as the original design curve.

**Gate:** every loft/sweep candidate has an entry; each entry is either
complete or `incomplete` with a reason.

### Phase 5: Resolve ownership, overlap, and alternatives

Closed negative space belongs to `hole`, including every shaped hole. Open
subtractive regions belong to `extrusion`. Countersink cone faces are not
ordinary chamfers; sheet-metal bends are not ordinary fillets. Shared support
faces are allowed, but mutually exclusive primaries cannot own the same
explanatory face. Put uncertainty in `conflict_group_id` and
`alternative_interpretations`; count only the primary.

Recognize ownership in this dependency order: holes, sheet-metal skins and
bends, extrusion/revolution/sweep/loft regions, then fillets and chamfers. For
the same whole-body entity set use revolution > extrusion > sweep > loft. Do not promote
hole walls, countersink cones, confirmed sheet bends, fillets, or chamfers into
standalone revolution features. Whole-body candidates may contain local
features only through explicit `contains_feature_ids` / `parent_feature_id`.

**Gate:** no mutually exclusive primary duplicate remains.

### Phase 6: Normalize the per-instance catalog

Write `feature-index.json` and `feature-summary.json`. Every feature has a
stable ID and exactly: `feature_id`, `category`, `subtype`, `display_name`,
`claim`, `body_id`, `entity_ids`, `highlight_entity_ids`,
`support_entity_ids`, `location`, `dimensions`, `profile`, `relationships`,
`evidence`, `confidence`, `visuals`, `limitations`, `reconstruction`, and
`target_sha256`.

For loft and sweep, `reconstruction` is a versioned JSON-safe handoff, not a
claim about original authoring history. It includes ROI IDs, ordered sections,
global alignment, profile/frame laws, path candidates, explicit guides and
`guide_attachment_map`, endpoint-condition evidence, adaptive station
requests, operation candidates, capability state, preflight checks, fallback
order, and limitations. Preserve `specialist_trigger.decision`; an incomplete
specialist result must not erase the coarse candidate.

Operation candidates describe what the upstream modeling API can currently
build. `loft_rsolid` and `loft_rshell` accept ordered sections and `ruled`, but
cannot enforce a recovered path or endpoint continuity. Mark such a proposal
`emulated` and retain the path and conditions as evidence; do not suggest a
multi-section sweep operation that is absent from the upstream API.

Each subtype lists its dimensions directly with units. A non-applicable value
says `not_applicable`; an unmeasurable value is `null` with
`unavailable_reason`. Holes list terminal, entry/exit or bottom,
direction/axis or local frame, depth, segment dimensions, and profile details.
Revolutions store `location.axis.point`, `location.axis.direction`,
`dimensions.sweep_angle`, `minimum_radius`, `maximum_radius`, `axial_span`, and
`profile.kind="meridian"`, without changing the fixed top-level field set.
Lofts store endpoint fit error/scale, start/end area where measurable,
variation law, and section tracking. Sweeps store path chord, endpoint rigid
fit, applicable twist angle, and applicable helix radius, pitch, turns, axis,
handedness, and fit quality.

Write `reconstruction-hypotheses.json` with `target_sha256` and one entry per
feature whose `reconstruction` is not null (loft and sweep), copied unchanged
and keyed by `feature_id`. It is a handoff for R1/R2 of
`step-reconstruction.md`, not an operation sequence; other categories get
their hypotheses from evidence in R1.

Accepted schema versions, which R0 of `step-reconstruction.md` checks:

- `feature-index.json` `schema_version`: `"4.1"`;
- `reconstruction` handoff `schema_version`: `"1.0"`.

Change this list in the same commit as any schema change.

**Gate:** `truncated=false`, `complete=true`; all IDs resolve and every feature
has its subtype-specific dimensions, evidence, and planned links.

### Phase 7: Plan and compute deterministic sections

Plan longitudinal/transverse sections for holes, profile and 25/50/75%
transverse checks plus a length section for extrusions, and XY/XZ/YZ center
sections for every run. For revolutions, plan a through-axis meridian section;
full revolutions add 0°/90°/180°/270° comparisons, while partial revolutions add
start/25%/50%/75%/end angular sections. For lofts and sweeps, preserve the cap
sections and every successful 25%/50%/75% actual BREP section plane used by
recognition. Also materialize bounded `adaptive_station_plan.requests` as
additional measured sections when the station budget permits; record skipped
requests and their budget reason. Never replace an actual BREP section with
an interpolated drawing. Helical candidates
may use the longitudinal helix fit as primary evidence when one plane intersects
multiple turns. Deduplicate by recorded tolerances. Call
`inspect_section_rdescriptor(..., compact=False)` and save descriptors under
`sections/data/`.

**Gate:** normals are finite/unit length; contours retain `samples_2d`; an
empty section remains an explicit empty panel.

### Phase 8: Render only from the authoritative catalog

Load saved `feature-index.json`. Call `render_geometric_features_rpath` for
`highlights/all-features.png`; it checks target hash and IDs without
recognizing. Produce per-feature `isometric.png`, `context.png`, profiles for
holes/extrusions, longitudinal/transverse sections, and `section-atlas.png`.

Use fixed colors: extrusion `#29ad57`, revolution `#06b6d4`, loft `#ec4899`,
sweep `#4f46e5`, hole `#943dc7`, fillet `#ef4444`,
chamfer `#f2b134`, sheet metal `#3b82f6`, bend `#f97316`. Circular and shaped
holes share purple. Write `visual-index.json` and `section-index.json` with
feature ID, entity IDs, relative path, image SHA-256, and target SHA-256.

**Gate:** every feature has a highlight; holes/extrusions/lofts/sweeps have a profile and
length/depth sections; revolutions have a meridian profile and required
angular sections. For zero features, the overview is `not_applicable`,
but three global sections still exist.

Under `reconstruction_prelude`, the overview and the three global sections are
always required, but per-feature visuals stop at the recorded render budget.
A feature that exceeds the budget or whose render fails is listed in
`visual-index.json` with `status="skipped"` and the reason; it is a visual gap,
not a missing feature.

### Phase 9: Write the per-instance report, manifest, and stop

Write `parse-report.md` with category/subtype counts and exactly one section
per feature. Each section directly lists type, body, location/direction,
dimensions with units, topology, evidence, confidence, clickable relative
visuals, and limitations. Write `artifact-manifest.json` with relative path,
role, bytes, SHA-256, and target hash. Set `run-status.json` to `complete`,
or to `complete_with_gaps` when the only shortfalls are budget-skipped or
failed per-feature visuals and Phase 4b `incomplete` entries; list every gap
in `run-status.json` and in the affected report sections. `analysis_only` runs
never use `complete_with_gaps`: any missing visual leaves them incomplete.

**Gate:** every link exists, hashes agree, no feature is omitted or double
counted, and no candidate geometry/model/replay artifact exists. A
`reconstruction` handoff descriptor is analysis data and is allowed. End here
for `analysis_only`; for `reconstruction_prelude`, return to R0 of
`step-reconstruction.md`.

## 6. Failure routes

| Failure | Required response |
| --- | --- |
| Missing target, bad suffix, unreadable BREP | Write failed Phase 1/2 status and stop |
| Output overlaps target directory | Request an isolated absolute directory |
| `truncated=true` | Increase `max_features`, replace the catalog, regenerate dependents |
| Entity/hash mismatch | Reject stale report; do not render |
| No supported feature | Preserve empty indexes; render global sections |
| Ownership is ambiguous | Record unresolved/alternative; do not guess |
| Missing visual or detailed section | `analysis_only`: mark the run incomplete. `reconstruction_prelude`: a missing overview or global section marks it incomplete; a skipped or failed per-feature visual is recorded as a gap under `complete_with_gaps` |
| Manifest or link mismatch | Write failed status and stop |

## 7. Deliverables

```text
<absolute-output-directory>/
  requirement-brief.md
  analysis-config.json
  target-summary.json
  raw-feature-hints.json
  feature-index.json
  feature-summary.json
  reconstruction-hypotheses.json
  loft-sweep-specialist.json
  visual-index.json
  section-index.json
  parse-report.md
  unresolved-features.md
  run-status.json
  artifact-manifest.json
  highlights/all-features.png
  highlights/<category>/<feature-id>/{isometric,context}.png
  profiles/<feature-id>.png
  sections/<feature-id>-longitudinal.png
  sections/<feature-id>-transverse.png
  sections/<feature-id>-angular.png
  sections/section-atlas.png
  sections/data/<section-id>.json
```

Forbidden deliverables include a candidate STEP, model JSON, operation
sequence, model audit, strict replay, roundtrip report, target/candidate
comparison, and reconstruction iteration output.

## 8. Completion gate

A run is complete only when all nine gates pass, every non-zero feature has one
Markdown section and required visuals, all hashes agree, `run-status.json` is
`complete`, and forbidden reconstruction outputs are absent. Under
`reconstruction_prelude`, `complete_with_gaps` also passes when every gap is
listed. This is only an analysis-package verdict; whether reconstruction may
start is decided by R0 of `step-reconstruction.md`.
