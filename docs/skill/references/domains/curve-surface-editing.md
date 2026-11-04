# Task Domain: Editing Curves and Surfaces (control points, weights, knots, degree)

Change an existing curve or surface the way a NURBS editor does (drag a pole, weight it, add a knot for local control,
raise the degree), as ordinary recorded operations. Each one returns a NEW Edge or Face; the input is never changed.

**Read when:** an existing Edge or Face must be reshaped by its control points, weights, knots or degree, refitted
(`rebuild_*`), or sampled for a curvature comb / isocurves; or a freeform face built with `make_bezier_surface_rface`,
`fit_point_grid_rface`, `trim_surface_rface`, Gordon or a patch must be adjusted after it was built.

## Use when

- A freeform face or spline edge is close but must be adjusted locally ("lift this corner", "flatten this edge").
- A surface needs more control in one region: insert a knot there, then move the new poles.
- An analytic face or edge (plane, cylinder, line, arc) must become freeform so it can be bent.

## Do not use

- The shape is better rebuilt from its inputs: change the profile / point grid / curve network of the constructor
  instead (parametric intent stays in the constructor's arguments).
- A face that is part of a solid must stay part of a closed body: an edit returns a free face (no shell or solid is
  rebuilt around it). Sew the edited faces again (`sew_faces_rshell`, `make_solid_from_shell_rsolid`) when needed.

## The loop: read, edit, check

1. `inspect_curve_rcurvedata(edge)` / `inspect_surface_rsurfacedata(face)`: degree(s), `poles`, `weights`, knots,
   multiplicities, domain, `editable`, `trimmed`. Pole indices are 0-based; a surface's `poles` are rows along U, each
   row along V (the shape `make_bezier_surface_rface` takes). Coordinates are in the current coordinate system.
2. If `editable` is false (`type` is `line`, `circle`, `plane`, `cylinder`, ...), convert explicitly:
   `convert_to_bspline_redge` / `convert_to_bspline_rface` (recorded; the shape does not change). The edits refuse
   analytic geometry with a message naming the conversion; nothing converts silently.
3. Edit (each recorded, each returns a new shape):

| Goal | Curve (Edge) | Surface (Face) |
| --- | --- | --- |
| Move some poles | `move_curve_poles_redge(e, {1: (x, y, z)})` | `move_surface_poles_rface(f, {(1, 2): (x, y, z)})` |
| Set all poles | `set_curve_poles_redge(e, poles)` | `set_surface_poles_rface(f, grid)` |
| Weights (rational) | `set_curve_weights_redge(e, ws)` | `set_surface_weights_rface(f, ws_grid)` |
| Local control | `insert_curve_knot_redge(e, t, multiplicity=1)` | `insert_surface_knot_rface(f, "U", u)` |
| Smoother / more poles | `elevate_curve_degree_redge(e, 4)` | `elevate_surface_degree_rface(f, u_degree=3)` |
| Refit (degree, pole count or tolerance) | `rebuild_curve_redge(e, 3, 8)` | `rebuild_surface_rface(f, 3, 3, 6, 6)` |

4. Check: `inspect_*` again; `sample_curve_rcurvature(edge, 64)` for a curvature comb (points, normals,
   curvatures, `max_curvature`); `sample_surface_risocurves(face, 5, 5)` for isocurves clipped to the trimming.

Knot insertion and degree elevation never change the shape (only the control net). A knot parameter must lie strictly
inside the edge's `parameter_range` / the surface's `domain`; the knot's total multiplicity is at most the degree.

## Trimmed faces

A trimmed face (holes, an outer loop that is not the surface's own boundary) keeps its trimming exactly: the loops stay
where they are in (u, v), and the 3D boundary edges are recomputed on the edited surface. So a hole moves with the
surface as it bends. `rebuild_surface_rface` keeps the parametrisation for the same reason. An edit that makes the
boundary invalid (folds the surface over itself) fails with the operation's error; nothing is returned half-built.

## Tags and references

Every edit records its history: the face and its boundary edges are `modified` (continuation). A tag assigned with
`apply_tag_rselection` on the face or on one of its edges, and a stable reference (`scad.ref`), follow the
entity through any chain of edits (with or without a `GraphSession`), and `ql.tag(...)` finds it on the result.
`tag_prefix=` only names the result of the operation it is passed to (`<prefix>.face` / `<prefix>.edge`), as for every
other operation: name the entities that must keep their name with `apply_tag_rselection`.

```python
face = scad.make_bezier_surface_rface(grid)
face = scad.apply_tag_rselection(face, [face], "skin")    # a name that follows the face
data = scad.inspect_surface_rsurfacedata(face)            # degrees, poles, knots ...
face = scad.insert_surface_knot_rface(face, "U", 0.5)      # one more row of poles
face = scad.move_surface_poles_rface(face, {(2, 1): (1.0, 1.0, 2.5)})
assert ql.faces().where(ql.tag("skin")).exactly(1).resolve(face)
```

Read the API page of each operation under `references/docs/api/` before the first call.
