// Editing existing curves and surfaces: read the NURBS data of an Edge / Face, change it, get a new shape.
//
// Every edit returns a NEW Edge or Face built on an edited copy of the input's geometry; the input is never mutated.
// The edits that change the B-spline without changing its parametrisation (poles, weights, knot insertion, degree
// elevation, refit over the same parameter domain) keep a Face's trimming exactly: its boundary loops stay where they
// are in the surface's (u, v) space, and the 3D boundary edges are recomputed on the edited surface.  Each edit is
// recorded with a TopoDelta (the face and its edges are `modified`, derivation `continuation`), so tags and stable
// references follow the edited entities.
//
// Only B-spline and Bezier geometry is edited (a Bezier is read as the B-spline it is, with the same parameters).
// Analytic geometry (line, circle, plane, cylinder, ...) is never converted silently: the edits refuse it and name
// convert_to_bspline_redge / convert_to_bspline_rface, the explicit, recorded conversion step.
//
// Coordinates (poles, sample points) are in the current coordinate system, as for every other operator; indices are
// 0-based; a surface's poles are rows along U, each row running along V (as make_bezier_surface_rface takes them).
#pragma once

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/surface/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// ---- read (diagnostic: not recorded) ---------------------------------------------------------------------------

// The NURBS data of an edge's curve: {type, analytic, editable, conversion, degree, poles, weights, knots,
// multiplicities, periodic, rational, closed, reversed, parameter_range, domain}.  For analytic geometry the data is
// what convert_to_bspline_redge would make of it, `editable` is false and `conversion` names that operation.
Value inspect_curve_rcurvedata(const Edge& edge);

// The NURBS data of a face's surface: {type, analytic, editable, conversion, u_degree, v_degree, poles (rows along U),
// weights, u_knots, v_knots, u_multiplicities, v_multiplicities, u_periodic, v_periodic, rational, reversed,
// trimmed, uv_bounds, domain}.  Analytic surfaces as for curves (convert_to_bspline_rface).
Value inspect_surface_rsurfacedata(const Face& face);

// ---- explicit conversion (recorded) ------------------------------------------------------------------------------

// The edge with its curve converted to a B-spline (BRepBuilderAPI_NurbsConvert).  A circle becomes a rational
// quadratic, a line a degree-1 B-spline; the parameter range may change with the conversion.
Edge convert_to_bspline_redge(const Edge& edge, const TagPrefix& tag_prefix = std::nullopt);

// The face with its surface (and its boundary curves) converted to B-splines, the trimming mapped by the converter.
Face convert_to_bspline_rface(const Face& face, const TagPrefix& tag_prefix = std::nullopt);

// ---- curve edits (recorded; B-spline / Bezier edges only) ---------------------------------------------------------

// All poles at once (as many as the curve has, in the curve's parameter order).
Edge set_curve_poles_redge(const Edge& edge, const std::vector<Vec3>& poles,
                           const TagPrefix& tag_prefix = std::nullopt);
// Some poles: index -> new position.
Edge move_curve_poles_redge(const Edge& edge, const std::map<int, Vec3>& moves,
                            const TagPrefix& tag_prefix = std::nullopt);
// All weights at once (positive; any weight other than 1 makes the curve rational).
Edge set_curve_weights_redge(const Edge& edge, const std::vector<double>& weights,
                             const TagPrefix& tag_prefix = std::nullopt);
// Insert a knot strictly inside the edge's parameter range (the shape does not change; one more pole per multiplicity).
Edge insert_curve_knot_redge(const Edge& edge, double parameter, int multiplicity = 1,
                             const TagPrefix& tag_prefix = std::nullopt);
// Raise the degree to `degree` (the shape does not change; poles are added).
Edge elevate_curve_degree_redge(const Edge& edge, int degree, const TagPrefix& tag_prefix = std::nullopt);

// ---- surface edits (recorded; B-spline / Bezier faces only; the trimming is kept in (u, v)) ------------------------

Face set_surface_poles_rface(const Face& face, const PointGrid& poles, const TagPrefix& tag_prefix = std::nullopt);
Face move_surface_poles_rface(const Face& face, const std::map<std::pair<int, int>, Vec3>& moves,
                              const TagPrefix& tag_prefix = std::nullopt);
Face set_surface_weights_rface(const Face& face, const WeightGrid& weights, const TagPrefix& tag_prefix = std::nullopt);
// `direction` is "U" or "V"; the parameter lies strictly inside the surface's domain in that direction.
Face insert_surface_knot_rface(const Face& face, const std::string& direction, double parameter, int multiplicity = 1,
                               const TagPrefix& tag_prefix = std::nullopt);
// At least one of the two degrees; each one given is at least the current degree, and one of them is higher.
Face elevate_surface_degree_rface(const Face& face, std::optional<int> u_degree, std::optional<int> v_degree,
                                  const TagPrefix& tag_prefix = std::nullopt);

// ---- rebuild (recorded; any curve / surface) ---------------------------------------------------------------------

struct RebuildCurveOptions {
  int degree = 3;
  std::optional<int> pole_count;  // none: the fewest poles that meet `tolerance`
  double tolerance = 1e-3;        // model length; only used when pole_count is none
  TagPrefix tag_prefix;
};
// A least-squares B-spline (uniform clamped knots, end points kept) over the edge's own parameter range, so the edge
// keeps its parameters; works on analytic edges too.
Edge rebuild_curve_redge(const Edge& edge, const RebuildCurveOptions& options = {});

struct RebuildSurfaceOptions {
  int u_degree = 3;
  int v_degree = 3;
  std::optional<int> u_pole_count;  // none (both): the fewest poles that meet `tolerance`
  std::optional<int> v_pole_count;
  double tolerance = 1e-3;
  TagPrefix tag_prefix;
};
// A least-squares B-spline surface over the face's (u, v) bounds in the same parametrisation, so the trimming is kept.
Face rebuild_surface_rface(const Face& face, const RebuildSurfaceOptions& options = {});

// ---- evaluation for an editor (diagnostic: not recorded) ----------------------------------------------------------

// `count` samples evenly in the edge's parameter range: {parameters, points, tangents, normals, curvatures,
// max_curvature}; a normal points to the centre of curvature (zero where the curve is straight).
Value sample_curve_rcurvature(const Edge& edge, int count = 64);

// Isocurves of the face clipped to its trimming: {u: [{parameter, segments: [[point, ...], ...]}], v: [...]}.
// `u_count` lines of constant u and `v_count` of constant v, evenly inside the face's (u, v) bounds.
Value sample_surface_risocurves(const Face& face, int u_count = 5, int v_count = 5, int samples = 48);

}  // namespace scad
