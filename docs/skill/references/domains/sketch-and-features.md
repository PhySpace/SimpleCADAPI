# Task Domain: Sketch and Features

Author declarative, constraint-driven 2D profiles and promote them into
topology, when the design intent is an editable sketch rather than direct
geometry transcription.

## Use when

- The part's controlling dimensions are naturally expressed as geometric
  constraints (coincidence, tangency, symmetry, equal radii, distances).
- The user asks for a parametric, editable profile whose constraints carry the
  design intent.
- Reconstruction evidence supports a planar generating profile
  (`domains/step-inspection.md` feeds this).

## Do not use

- Non-planar paths, guides, or exact freeform carrier transcription: build
  `Wire`/`Edge` geometry directly in `domains/part-modeling.md`.
- Report-derived geometry whose projection would change measured control data.
- A sketch whose available constraints do not represent the evidence: direct
  Wire construction is appropriate then.

## Inputs

- Plane mapping (which model plane the sketch lives on), closure requirements,
  arc direction conventions, spline definitions, and known degrees of freedom.

## Outputs

- A solved `Sketch` promoted with `make_wire_from_sketch_rwire` or
  `make_face_from_sketch_rface` into the topology layer.
- Promotion records `solve_snapshot` and `promotion_map` evidence; promoted
  geometry receives `source_sketch`, `sketch_solve` metadata and entity tags.

## API groups

Read the exact page under `references/docs/api/` for every API used:

- Document: `make_sketch_rsketch`, `add_point_rsketch`, `add_line_rsketch`,
  `add_arc_rsketch`, `add_circle_rsketch`, `add_bspline_rsketch`,
  `add_ellipse_rsketch`.
- Entities: `get_sketch_entity_rsketchref`, `get_sketch_point_rsketchref`.
- Constraints: `constrain_coincident_rsketch`, `constrain_collinear_rsketch`,
  `constrain_concentric_rsketch`, `constrain_connect_rsketch`,
  `constrain_distance_rsketch`, `constrain_distance_x_rsketch`,
  `constrain_distance_y_rsketch`, `constrain_line_distance_rsketch`,
  `constrain_diameter_rsketch`,
  `constrain_radius_rsketch`, `constrain_length_rsketch`,
  `constrain_equal_length_rsketch`, `constrain_equal_radius_rsketch`,
  `constrain_angle_rsketch`, `constrain_parallel_rsketch`,
  `constrain_perpendicular_rsketch`, `constrain_horizontal_rsketch`,
  `constrain_vertical_rsketch`, `constrain_points_horizontal_rsketch`,
  `constrain_points_vertical_rsketch`, `constrain_tangent_rsketch`,
  `constrain_midpoint_rsketch`, `constrain_midpoint_points_rsketch`,
  `constrain_symmetric_rsketch`, `constrain_mirror_rsketch`,
  `constrain_normal_rsketch`, `constrain_point_on_rsketch`,
  `constrain_major_radius_rsketch`, `constrain_minor_radius_rsketch`,
  `constrain_fix_rsketch`. Driving `constrain_angle_rsketch` holds the
  directed angle from the first line to the second (0-360 degrees; the
  solve keeps the branch nearest the initial geometry).
- Promotion: `make_wire_from_sketch_rwire`, `make_face_from_sketch_rface`.
- Diagnostics: `inspect_sketch_rsketchresult` (non-recording).

## Construction rules

- Sketch construction is functional: `add_*_rsketch` and
  `constrain_*_rsketch` return an updated `Sketch` (cloned), leaving the input
  untouched. (A private linear-edit runtime mode mutates internally; never
  rely on it from your own code — always rebind the returned value.)
- Every sketch entity has a stable explicit id; constraints reference those ids.
- `add_arc_rsketch` follows the positive local angular sweep, so endpoint order
  is meaningful.
- Solve is not a graph leaf: promotion runs the solver internally, so keep the
  sketch fully constrained (or record remaining DOF) before promotion.
- The default solver backend is `py-slvs`; solve snapshots record
  `backend`, `backend_version`, and `backend_status_code` for replay evidence.
- `inner_profiles` is valid only when adjacent-carrier evidence shows the loops
  belong to the same generating profile.

## Validation gates

- Record plane mapping, closure, solve status, and remaining DOF in the brief.
- `dof=0` says the constraint system closed, not that the shape is the intended
  one: angle and symmetry constraints can solve to the mirror solution. Verify
  the promoted geometry by measurement (bounding box, area, edge counts), never
  by the solver status alone.
- When sketch promotion may change measured geometry, build Wire and Sketch
  from one parameter source and compare closure/area/bounds/segmentation before
  promoting.
- A Sketch wrapping a prebuilt Wire does not recover sketch intent: do not
  claim parametric intent for coordinate-locked transcription; label it as such.

## Failure modes

- Underconstrained sketch drifting on promotion: add evidence-backed
  constraints, or record the free DOF explicitly.
- Unsupported or redundant constraints in downstream translation are recorded
  as skipped, not silently dropped; check the solve snapshot when fidelity
  matters.
