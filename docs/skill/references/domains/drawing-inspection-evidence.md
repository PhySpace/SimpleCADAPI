# Task Domain: Drawing Inspection Evidence (model sections and executable checks)

**Read when:** a section view of the drawing must be verified against the rebuilt model, a DIM ledger row needs its
`measurement_contract`, or the roundtrip evidence (annotations, reviews, coverage) is built or checked.

Companion of `domains/drawing-inspection.md` (the parsing SOP, tiers and report skeleton). Everything below feeds the
roundtrip in `workflows/drawing-reconstruction/roundtrip-acceptance.md`.

## Model-section evidence group

Cut the rebuilt model where the drawing cuts it; these functions take a live
shape (pass ``solid.wrapped``) or a STEP path and an explicit plane, and stay
factual — plane semantics belong to the caller:

- `measure_model_section_rdimensions` — distinguish analytic circle geometry,
  fitted-circle candidates, continuous geometry extrema/distances and sampled
  approximations by each record's method and accuracy fields. A fitted circle's
  residual is not a dimensional error bound. Section intersection tolerance is
  not total measurement uncertainty. Unknown error bounds stay unknown.
  Circle diagnostics include conditioning, angular coverage/max gap and both
  RMS/max residual. Local arcs, open/gapped contours and nearly collinear
  samples stay unverified; do not modify CAD dimensions from unreliable fits.
- `render_model_section_rpath` — annotated section render (45° hatch on
  material only, dimension leaders with `dim_id` + measured value + sheet
  value, mm scale bar). Fixed output: the section PNG and sidecar. The
  renderer displays caller data, including wrong numbers; rendering success
  does not prove measurement correctness. Formal evidence must use the bound
  annotation builder and independent validator. The caller owns the comparison: put the render next to the drawing's own
  viewport crop (same evidence directory) and judge — no composite is
  generated for you.

### Explicit section strategy and integrity evidence

Result version **2.2** adds `section_strategy="auto"|"material"|"edges"`.
Auto uses material-face intersection for solids even if edge contours would
already be closed, and edge intersection for non-solid diagnostic inputs.
Material mode retains the actual edges and topological outer/inner wire roles
from the same intersection. Edges mode remains available; with formal checks
it also obtains an independent material-face reference. Environment variable
`SIMPLECADAPI_MATERIAL_SECTION` no longer selects the workflow strategy.
Archive both the requested strategy and the actual `contour_method`.

Each formal DIM ledger row must reference the same independently reviewed
`section_checks` contract as its measurement. For a tube cut at z=10, an example
contract is:

```json
{
  "expected_origin": [0, 0, 10],
  "expected_normal": [0, 0, 1],
  "expected_x_direction": [0, -1, 0],
  "expected_y_direction": [1, 0, 0],
  "expected_solid_count": 1,
  "expected_face_count": 1,
  "expected_hole_count": 1,
  "material_points": [{"id": "wall", "point": [9, 0]}],
  "void_points": [{"id": "bore", "point": [0, 0]}],
  "point_tolerance_mm": 0.0000001,
  "tolerance_basis": "Point-classification precision for this fixture",
  "evidence": "Drawing view and independent feature-association review"
}
```

The example's points assume an outer radius of 10 and inner radius of 8;
choose actual points from the intended drawing geometry. Expected counts and
directions come from the drawing/confirmed requirements, never from copying the
current result. Points are section-local mm. Every material face needs an
interior material point; every hole needs an interior void point. Boundary or
indeterminate classifications stay pending. Empty void lists are allowed only
when no topological hole needs coverage; include points in any additional
drawing-defined open cavity or gap. The coordinate-frame direction comparison
uses the recorded numerical threshold 1e-10; point tolerance is not a dimensional
error bound.

`section_validation` separately reports source validity/closure/solid count,
section closure, valid material faces and inner/outer rings, and each point's
classification against the original solid, material faces, and displayed
polygons. Formal rendering checks its own actual sampling density. Open or
incomplete sections may render as `diagnostic_only`, but cannot become formal
evidence. Missing section checks are not auto-filled from measured geometry.

On failure, inspect the section definition, intersection and display first.
`section_definition`, `section_intersection` and `section_display` failures
do not justify changing the model. Only independent solid evidence, confirmed
against the drawing, can establish a model-geometry error. Mass, center of mass,
inertia and high-precision volume matching remain outside drawing-reconstruction
acceptance unless the user separately requests them.

### Executable evidence checks

Read the exact API pages for `inspect_drawing_coordinates_rreport`,
`assess_dimension_rverdict`, `build_section_annotation_rrecord`,
`validate_section_annotations_rreport`, and
`summarize_dimension_coverage_rreport`. The latter requires the complete expected
DIM list; omitted rows count as missing in every coverage column.

Result version **2.1** requires an independent `measurement_contract` in each
ledger row. For example, a section's width is
`{"kind":"extent_width","definition":"axis_aligned_extent","direction":[1,0],
"point":null,"units":"mm","coordinate_space":"section_local"}`.
Height uses `extent_height` and `[0,1]`. Diameter uses `circle_diameter`,
minimum gap uses `minimum_boundary_gap`, both with null direction/point.
Directional material thickness uses `material_length_on_line`, a normalized
local direction and the specified local point. Geometry IDs bind the selected
contour; this separate contract binds what is measured on it. Missing contracts
cannot be inferred from whichever measurement happens to fall inside tolerance.

The repository script `tools/verify_drawing_evidence.py --model part.step
--evidence evidence.json --out verification.json` independently remeasures and
reports all three gates. Its input contains `plane`, the complete `ledger`,
bound `annotations`, and `output_reviews` keyed by DIM ID. An output review
contains `layout_status: reviewed`, `association_status: verified` and independent
`evidence` references, plus the `dim_id`, `measurement_id`, `model_hash` and
`section_id` captured **when the image was reviewed**. Its `render_artifact`
contains absolute `image_path`, `sidecar_path`, and the reviewed
`image_sha256`, `sidecar_sha256`. The renderer records the image hash and each
annotation's content-derived ID in the sidecar. Validate both file hashes,
annotation content (including anchors and precision) and measurement identity.
Never replace old review IDs or hashes with current values during verification.
Old or missing identities require a new review of the actual current artifact.
Missing visual review remains pending even when numeric checks pass.

Formal annotations also check the actual formatted value: the display step
must be no wider than the tolerance band, rounding error no larger than half
its width, and the displayed number itself inside the band. Zero-width bands
require exact representation. For 10.4 mm in [10.39,10.41], zero decimals are
rejected; one decimal also lacks the required resolution. Geometric conformance
continues to use the unrounded value and its uncertainty interval.

An external total-error assessment must be tied to the exact `measurement_id`
and include `bound_mm`, `basis`, and `evidence`. These fields record a separate
metrology assessment; the SDK cannot establish its truth just by reading them.
Do not turn a fitted-circle residual or kernel edge tolerance into this bound.
