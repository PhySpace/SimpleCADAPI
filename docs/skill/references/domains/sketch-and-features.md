# Task Domain: Sketch and Features

Author declarative, constraint-driven 2D profiles and promote them into
topology, when the design intent is an editable sketch rather than direct
geometry transcription.

**Read when:** the part's controlling dimensions are geometric constraints, or an editable, constraint-driven profile is
requested (sketch tier profiles and paths).

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
- A sketch off the XY/XZ/YZ planes goes on a workplane value: `plane=wp` where `wp` is a recorded
  `make_workplane_*_rworkplane` (a face, three points, an axis, a midplane, a curve's normal plane; see
  `references/docs/core/simple_workplane.md`). It follows the geometry the workplane was made from; a frame mapping of
  copied numbers does not.

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
- Editing: `trim_rsketch`, `extend_rsketch` (see "Trim and extend" below),
  `fillet_corner_rsketch`, `chamfer_corner_rsketch` (see "Fillet and chamfer a
  corner"), `project_rsketch` (see "Relating sketches: project").
- Promotion: `make_wire_from_sketch_rwire`, `make_face_from_sketch_rface`.
- Diagnostics: `inspect_sketch_rsketchresult` (non-recording),
  `diff_sketch_rsketchdiff` (non-recording report of what an edit changed).

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

## Trim and extend

Use `trim_rsketch` when overlapping or overshooting lines, circles and arcs must
be cut back to where other entities cross them (a rectangle drawn as four
over-long lines, a circle cut by a slot); use `extend_rsketch` to lengthen a line
until it meets another entity. Both solve the sketch first and cut or extend on
the solved geometry, return a new `Sketch`, are recorded in the graph and replay
from model JSON. They keep the sketch connected: a new cut point is tied to the
entity that cut it with `point_on`, a line piece keeps the `horizontal` /
`vertical` constraint of its line, constraints on `<entity>.start|end|center`
stay on the point, and constraints that name the removed entity (and a dimension
that no longer holds) are removed. The edit picks the new ids: points are
`p<n>`, lines `l<n>`, arcs `a<n>` (the lowest number never used by the sketch)
and constraints `c_<kind>_<n>`.

```python
before = sketch
# remove the part of line "h" that contains the point (8, 0), between the crossings
sketch = scad.trim_rsketch(sketch, "h", (8.0, 0.0))          # at: (x, y) or a point id
sketch = scad.trim_rsketch(sketch, "c", "click", against=["l1", "l2"])  # only these entities cut
sketch = scad.extend_rsketch(sketch, "spur", "end")            # to the nearest entity ahead
sketch = scad.extend_rsketch(sketch, "spur", "end", to="wall") # or to a named one
print(scad.diff_sketch_rsketchdiff(before, sketch))
# {'created': [...], 'removed': [...], 'changed': [...],
#  'created_constraints': [...], 'removed_constraints': [...], 'changed_constraints': [...]}
```

- A circle needs two cuts to leave an arc (one cut is an error, no cut removes
  it whole); an entity nothing crosses is removed whole.
- `extend_rsketch` refuses an end point shared with another entity and names the
  ids; ellipses and B-splines neither cut nor can be trimmed.
- Read `diff_sketch_rsketchdiff(before, after)` instead of diffing
  `Sketch.to_dict()` yourself; the last edit's notes are in
  `sketch.get_metadata("last_edit")`.

## Fillet and chamfer a corner

`fillet_corner_rsketch(sketch, a, b, radius)` rounds the corner where two lines
meet; `chamfer_corner_rsketch(sketch, a, b, distance)` cuts it with a line. The
lines must share an end point (build them from the same point id). Like trim,
both solve the sketch first, return a new `Sketch`, are recorded and replay.

```python
sketch = scad.fillet_corner_rsketch(sketch, "bottom", "right", 2.0)    # arc a1, points p1..p3
sketch = scad.chamfer_corner_rsketch(sketch, "top", "left", 1.0)       # line l<n>
```

- Both lines are shortened to the tangent points; the arc runs counter-clockwise
  from its start to its end around its centre and gets a `tangent` constraint
  with each line plus a driving `radius`, so a re-solve keeps it. A chamfer gets
  a driving `length` (its chord) and a driving `angle` to line `a`.
- The corner point goes away unless something else uses it; if a constraint
  does, it stays as the sharp corner and the cut-off parts of the lines stay as
  construction lines (collinear with their lines), so the lines keep their place.
- `horizontal`, `vertical` and the other constraints that hold for a shorter
  line stay; lengths and other dimensions of the two lines are dropped and
  listed by `diff_sketch_rsketchdiff` and `get_metadata("last_edit")["notes"]`.
  Re-dimension what you need afterwards (the remaining DOF show what to add).
- Refused with the ids named: parallel lines, lines without a shared point, a
  radius or distance that does not leave part of the shorter line (the message
  gives the largest radius).

## Relating sketches: project

`project_rsketch(sketch, source, *, entities=None, construction=True)` brings
geometry from another sketch (any plane) or from shape edges into `sketch` as
reference geometry, so a sketch in one plane can be constrained to another.

```python
plan = scad.project_rsketch(plan, front, entities=["wall", "hole"])   # another Sketch
plan = scad.project_rsketch(plan, scad.ql.edges().resolve(solid))   # edges of a shape, in world coordinates
plan = scad.constrain_point_on_rsketch(plan, "tail", "proj_front_3")  # constrain to the projection
print(plan.get_metadata("projections"))   # [{'source': 'front', 'entity': 'wall', 'projected': 'proj_front_3'}, ...]
```

- Coordinates go through both plane frames: `u = (P - origin) . x_axis`,
  `v = (P - origin) . y_axis`. Points, lines, circles and arcs in a parallel
  plane are copied (an arc keeps its sense); a circle or arc seen edge on becomes
  a line, a line along the sketch normal a point, an oblique full circle an
  ellipse. An oblique arc, a spline edge, or an unknown id is refused by name.
- Copies are `construction` (default) and fixed at their projected coordinates;
  ids are `proj_<source sketch id>_<n>` (`proj_shape_<n>`), never colliding with
  existing ids. Projecting the same source again reuses what is there.
- Without `entities`, ellipses and B-splines of a source sketch are skipped and
  named in `get_metadata("last_edit")["notes"]`; `entities` is for source
  sketches only.

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
