// OCCT curve and wire builders (ocp_curves.py).
//
// Failures follow the Python SDK: argument checks are ValueError; anything the
// kernel itself refuses (coincident end points, collinear arc points, an
// invalid B-spline definition) leaves as a KernelError carrying the OCCT class.
#pragma once

#include <optional>
#include <string_view>
#include <vector>

#include <TopoDS_Edge.hxx>
#include <TopoDS_Wire.hxx>

#include "scad/core/vec.hpp"

namespace scad::kernel {

TopoDS_Edge make_line_edge(const Vec3& start, const Vec3& end);

// A full circle.  `x_direction` fixes where the parametrisation starts; without
// it the plane basis derived from `normal` is used.
TopoDS_Edge make_circle_edge(const Vec3& center, double radius, const Vec3& normal,
                             const std::optional<Vec3>& x_direction = std::nullopt);

// A full ellipse.  ValueError unless 0 < minor_radius <= major_radius.
TopoDS_Edge make_ellipse_edge(const Vec3& center, double major_radius, double minor_radius, const Vec3& normal,
                              const std::optional<Vec3>& major_direction = std::nullopt);

TopoDS_Edge make_arc_three_point_edge(const Vec3& start, const Vec3& middle, const Vec3& end);

// An arc from `start_angle` to `end_angle` (radians) about `normal`, counter-clockwise.
TopoDS_Edge make_arc_angle_edge(const Vec3& center, double radius, double start_angle, double end_angle,
                                const Vec3& normal, const std::optional<Vec3>& x_direction = std::nullopt);

struct BSplineSpec {
  std::vector<Vec3> control_points;
  int degree = 3;
  std::vector<double> knots;
  std::vector<int> multiplicities;
  std::vector<double> weights;  // empty = non-rational
  bool periodic = false;
};
TopoDS_Edge make_bspline_edge(const BSplineSpec& spec);

// Interpolates `points` (GeomAPI_Interpolate); ValueError when the fit fails.
TopoDS_Edge make_interpolated_bspline_edge(const std::vector<Vec3>& points, bool periodic = false,
                                           double tolerance = 1.0e-6);

// The edges must chain end to start; a gap is a KernelError (StdFail_NotDone).
TopoDS_Wire make_wire_from_edges(const std::vector<TopoDS_Edge>& edges);

// Segments between consecutive points; `closed` adds the last -> first segment
// (only when there are more than two points, like the Python SDK).
TopoDS_Wire make_polyline_wire(const std::vector<Vec3>& points, bool closed = false);

// A helix of `pitch` rising to `height` on a cylinder of `radius` around the
// axis (`center`, `direction`).  `handedness` is "Right" or "Left".
TopoDS_Wire make_helix_wire(double pitch, double height, double radius, const Vec3& center, const Vec3& direction,
                            const std::optional<Vec3>& x_direction = std::nullopt,
                            std::string_view handedness = "Right");

}  // namespace scad::kernel
