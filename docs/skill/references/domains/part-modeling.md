# Task Domain: Part Modeling

Model one physical, single-solid mechanical part with the core geometry API:
primitives, profiles, 3D features, booleans, detail features, and transforms.

## Use when

- The deliverable is one physical part that will be manufactured or exported as
  a single solid body.
- The request names brackets, plates, enclosures bodies, shafts, spacers,
    bosses, flanges, blades, or any monolithic part geometry.
- An existing part source needs a geometry edit: new features, dimension
  changes, repaired booleans, or re-selected detail edges.

## Do not use

- Constrained editable profiles as the design intent: use
  `domains/sketch-and-features.md`.
- Multi-part products, connectors, or motion: use
  `domains/assembly-and-product.md`.
- Standard gears, ring gears, racks, cycloidal discs, or bearings: use
  `domains/standard-parts.md` first.
- Reading facts out of an existing STEP file: use
  `domains/step-inspection.md`.

## Inputs

- A refined brief with units (SDK evaluates lengths in millimeters), overall
  dimensions, named parameters, feature list, and validation targets
  (`domains/requirement-refinement.md`).
- A chosen part-local coordinate convention
  (`discipline/datums-and-coordinate-systems.md`).

## Outputs

- A positive-volume, closed `Solid`, or a `Part` via `make_part_rpart` when the
  product boundary is needed.
- Semantic tags on mating/role surfaces and numeric facts in metadata.
- A replayable `GraphSession` model JSON when the flow must be replayable or
  interchange-exported.

## Required discipline

- `discipline/mechanical-modeling.md` before designing construction strategy.
- `discipline/feature-ordering.md` before composing operation order.
- `discipline/geometric-validation.md` for the validation gates.

## API groups

Read the exact page under `references/docs/api/` for every API used.
Before the first call, extract each page's signature, return type, and
documented failure modes into working notes — a method absent from the
page does not exist, however plausible it looks. Non-SDK dependencies
(Gmsh, CalculiX, VTK, FreeCAD scripting) are outside these pages:
consult their own documentation before the first call.

- Primitives: `make_box_rsolid`, `make_cylinder_rsolid`, `make_sphere_rsolid`,
  `make_cone_rsolid`.
- Profiles: `make_circle_rface`, `make_rectangle_rface`, `make_face_from_wire_rface`,
  `make_face_from_wires_rface`, `make_surface_patch_rface`,
  `make_ruled_surface_rface`, `make_gordon_surface_rface`,
  `make_cylindrical_surface_rface`.
- Features: `extrude_rsolid`, `revolve_rsolid`, `sweep_rsolid`,
  `twisted_sweep_rsolid` (supports inner-wire profiles), `helical_sweep_rsolid`,
  `loft_rsolid`, `loft_rshell`, `loft_multisection_rsolid` (varying sections
  along a path), `shell_rsolid`.
- Detail: `fillet_rsolid`, `chamfer_rsolid`.

## Boolean discipline

- `union_rsolid`, `cut_rsolid`, and `intersect_rsolid` accept mixed inputs
  (standalone `Solid`, lists, nested sequences) and return exactly one `Solid`.
- `union_rsolid` defaults to `glue=False` with a conservative scale-relative
  internal tolerance. If a union cannot produce exactly one merged solid it
  fails explicitly; do not silently pick one piece.
- If a single merged solid is required and union fails, adjust placement so the
  bodies really overlap (not merely touch), then recompute.
- Overshoot through-cut tools past the faces they enter and exit; coincident
  tool/target faces are a classic kernel failure.
- `cut_rsolid` skips non-intersecting tools by default
  (`skip_non_intersecting=True`); pass `skip_non_intersecting=False` for strict
  diagnostics — a skipped cut is never a completed feature.

## Validation gates

- After each major step print small QL-derived facts: selected face count, top
  face center, edge count, volume, bounding box.
- Validity is not positive volume, and `Solid` exposes no public
  `is_valid`/closure predicate: run BREP validity/closure diagnostics with
  `inspect_shape_rbrepinspection` / `inspect_step_rbrepinspection` from
  `simplecadapi.inspect.brep` (outside `GraphSession`), and check
  `Solid.get_volume() > 0` yourself. `Shell.is_closed` exists for shells.
- Verify every user-specified dimension with a targeted measurement, not only
  aggregate properties.

