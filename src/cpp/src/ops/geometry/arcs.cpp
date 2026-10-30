#include "scad/ops/geometry/arcs.hpp"

#include "internal.hpp"
#include "scad/ops/geometry/plane.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

constexpr const char* kThreePointEdgeOp = "make_three_point_arc_redge";
constexpr const char* kAngleEdgeOp = "make_angle_arc_redge";

OpRecord three_point_record(std::string_view op, std::string_view kind, const Scalar3& start, const Scalar3& middle,
                            const Scalar3& end) {
  return OpParams(std::string(op), primitive_labels(kind))
      .point("start", start)
      .point("middle", middle)
      .point("end", end)
      .take();
}

const ErrorSpec& three_point_spec() {
  static const ErrorSpec spec{
      kThreePointEdgeOp,
      "Failed to create a three-point arc edge.",
      {"One or more points are invalid.", "The three points are collinear or nearly collinear.",
       "The kernel rejected the derived arc geometry."},
      {"Pass three finite 3D points.", "Make sure the three points do not lie on the same straight line.",
       "If points are computed dynamically, log them before retrying."}};
  return spec;
}

TopoDS_Edge three_point_geometry(const Scalar3& start, const Scalar3& middle, const Scalar3& end) {
  return guarded(three_point_spec(), [&] {
    const Vec3 a = place_point(start, "start");
    const Vec3 b = place_point(middle, "middle");
    const Vec3 c = place_point(end, "end");
    return kernel::make_arc_three_point_edge(a, b, c);
  });
}

OpRecord angle_record(std::string_view op, std::string_view kind, const Scalar3& center, const Scalar& radius,
                      const Scalar& start_angle, const Scalar& end_angle, const Scalar3& normal) {
  return OpParams(std::string(op), primitive_labels(kind))
      .point("center", center)
      .scalar("radius", radius)
      .scalar("start_angle", start_angle)
      .scalar("end_angle", end_angle)
      .point("normal", normal)
      .take();
}

const ErrorSpec& angle_spec() {
  static const ErrorSpec spec{kAngleEdgeOp,
                              "Failed to create an angle-defined arc edge.",
                              {"The radius is not positive.", "The start and end angles collapse to the same value.",
                               "The center or normal is invalid, or the kernel rejected the arc."},
                              {"Use a positive radius.", "Make sure start_angle and end_angle are different.",
                               "Pass a valid finite center and a non-zero normal vector."}};
  return spec;
}

TopoDS_Edge angle_geometry(const Scalar3& center, const Scalar& radius, const Scalar& start_angle,
                           const Scalar& end_angle, const Scalar3& normal) {
  return guarded(angle_spec(), [&] {
    const double radius_value = evaluate_scalar(radius, "radius");
    const double start = evaluate_scalar(start_angle, "start_angle");
    const double end = evaluate_scalar(end_angle, "end_angle");
    if (radius_value <= 0)
      throw ValueError("The radius must be greater than zero");
    if (start == end)
      throw ValueError("The start angle and the end angle cannot be equal");

    const CoordinateSystem& cs = current_cs();
    const Vec3 center_global = cs.transform_point(evaluate_point(center, "center"));
    const Vec3 normal_value = evaluate_point(normal, "normal");
    return kernel::make_arc_angle_edge(center_global, radius_value, start, end, cs.transform_vector(normal_value),
                                       cs.transform_vector(default_plane_x_direction(normal_value)));
  });
}

}  // namespace

Edge make_three_point_arc_redge(const Scalar3& start, const Scalar3& middle, const Scalar3& end) {
  return guarded(three_point_spec(), [&] {
    return finalize_primitive_with(Edge(three_point_geometry(start, middle, end)), kThreePointEdgeOp,
                                   [&] { return three_point_record(kThreePointEdgeOp, "edge", start, middle, end); });
  });
}

Wire make_three_point_arc_rwire(const Scalar3& start, const Scalar3& middle, const Scalar3& end) {
  static constexpr const char* kOp = "make_three_point_arc_rwire";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a wire from the three-point arc.",
      {"The arc edge could not be created.", "The wire assembly step rejected the generated edge."},
      {"Verify the three arc points first.",
       "If the edge is valid but the wire still fails, inspect the generated arc geometry."}};
  return guarded(kSpec, [&] {
    if (graph_recording())
      return make_wire_from_edges_rwire({make_three_point_arc_redge(start, middle, end)});
    return finalize_primitive_with(
        Wire(kernel::make_wire_from_edges({three_point_geometry(start, middle, end)})), "make_three_point_arc_wire",
        [&] { return three_point_record("make_three_point_arc_wire", "wire", start, middle, end); });
  });
}

Edge make_angle_arc_redge(const Scalar3& center, const Scalar& radius, const Scalar& start_angle,
                          const Scalar& end_angle, const Scalar3& normal) {
  return guarded(angle_spec(), [&] {
    return finalize_primitive_with(
        Edge(angle_geometry(center, radius, start_angle, end_angle, normal)), kAngleEdgeOp,
        [&] { return angle_record(kAngleEdgeOp, "edge", center, radius, start_angle, end_angle, normal); });
  });
}

Wire make_angle_arc_rwire(const Scalar3& center, const Scalar& radius, const Scalar& start_angle,
                          const Scalar& end_angle, const Scalar3& normal) {
  static constexpr const char* kOp = "make_angle_arc_rwire";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a wire from the angle-defined arc.",
      {"The underlying arc edge could not be created.", "The wire assembly step rejected the generated edge."},
      {"Check the center, radius, angle range, and normal.", "Retry after validating the arc edge input values."}};
  return guarded(kSpec, [&] {
    if (graph_recording())
      return make_wire_from_edges_rwire({make_angle_arc_redge(center, radius, start_angle, end_angle, normal)});
    return finalize_primitive_with(
        Wire(kernel::make_wire_from_edges({angle_geometry(center, radius, start_angle, end_angle, normal)})),
        "make_angle_arc_wire",
        [&] { return angle_record("make_angle_arc_wire", "wire", center, radius, start_angle, end_angle, normal); });
  });
}

}  // namespace scad
