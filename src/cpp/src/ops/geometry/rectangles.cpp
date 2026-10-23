#include "scad/ops/geometry/rectangles.hpp"

#include <array>
#include <cmath>

#include "internal.hpp"
#include "scad/ops/geometry/faces.hpp"
#include "scad/ops/geometry/lines.hpp"
#include "scad/ops/geometry/plane.hpp"
#include "scad/ops/geometry/scalar_math.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

constexpr const char* kWireOp = "make_rectangle_rwire";
constexpr const char* kFaceOp = "make_rectangle_rface";

OpRecord rectangle_record(std::string_view op, std::string_view kind, const Scalar& width, const Scalar& height,
                          const Scalar3& center, const Scalar3& normal) {
  return OpParams(std::string(op), primitive_labels(kind))
      .scalar("width", width)
      .scalar("height", height)
      .point("center", center)
      .point("normal", normal)
      .take();
}

// `_offset_point_expr`: center + dx * x_axis + dy * y_axis, symbolic where an operand is.
Scalar3 offset_point(const Scalar3& center, const Vec3& x_axis, const Vec3& y_axis, const Num& dx, const Num& dy) {
  const auto coordinate = [&](std::size_t i, double x, double y) {
    return (Num(center[i]) + dx * Num(x) + dy * Num(y)).scalar();
  };
  return {coordinate(0, x_axis.x, y_axis.x), coordinate(1, x_axis.y, y_axis.y), coordinate(2, x_axis.z, y_axis.z)};
}

// The session path: four recorded segments chained into a wire, so editing `width` reruns them.
Wire recorded_rectangle(const Scalar& width, const Scalar& height, const Scalar3& center, const Scalar3& normal) {
  const PlaneAxes axes = orthonormal_plane_axes(evaluate_point(normal, "normal"));
  const Num half_width = Num(width) / Num(2), half_height = Num(height) / Num(2);
  const std::array<Scalar3, 4> corners{offset_point(center, axes.x_axis, axes.y_axis, -half_width, -half_height),
                                       offset_point(center, axes.x_axis, axes.y_axis, half_width, -half_height),
                                       offset_point(center, axes.x_axis, axes.y_axis, half_width, half_height),
                                       offset_point(center, axes.x_axis, axes.y_axis, -half_width, half_height)};
  std::vector<Edge> edges;
  edges.reserve(corners.size());
  for (std::size_t i = 0; i < corners.size(); ++i) edges.push_back(make_line_redge(corners[i], corners[(i + 1) % corners.size()]));
  return make_wire_from_edges_rwire(edges);
}

std::vector<Vec3> placed_corners(double width, double height, const Scalar3& center, const Scalar3& normal) {
  const CoordinateSystem& cs = current_cs();
  const Vec3 center_global = cs.transform_point(evaluate_point(center, "center"));
  const Vec3 normal_value = evaluate_point(normal, "normal");
  const double normal_norm = cs.transform_vector(normal_value).norm();
  if (normal_norm <= 1e-15 || !std::isfinite(normal_norm)) throw ValueError("The normal vector cannot be a zero vector");

  const PlaneAxes axes = orthonormal_plane_axes(normal_value);
  const Vec3 plane_x = cs.transform_vector(axes.x_axis);
  const Vec3 plane_y = cs.transform_vector(axes.y_axis);
  const double half_width = width / 2, half_height = height / 2;
  const std::array<std::array<double, 2>, 4> local{{{-half_width, -half_height}, {half_width, -half_height},
                                                    {half_width, half_height}, {-half_width, half_height}}};
  std::vector<Vec3> corners;
  corners.reserve(local.size());
  for (const auto& [u, v] : local) corners.push_back(center_global + plane_x * u + plane_y * v);
  return corners;
}

Wire with_edge_prefix(Wire wire, const RectangleTags& tags) {
  return Wire(apply_profile_tag_prefix(std::move(wire), tags.tag_prefix, tags.edge_tags, prefix_source(kWireOp)));
}

}  // namespace

Wire make_rectangle_rwire(const Scalar& width, const Scalar& height, const Scalar3& center, const Scalar3& normal,
                          const RectangleTags& tags) {
  static const ErrorSpec kSpec{kWireOp,
                               "Failed to create a rectangular wire.",
                               {"Width or height is not a positive finite scalar.",
                                "The center or normal is not a valid finite 3D vector.",
                                "The local rectangle basis became degenerate."},
                               {"Use width and height values greater than zero.",
                                "Pass a valid center and a non-zero normal vector.",
                                "If the normal is near zero, normalize or replace it before retrying."}};
  return guarded(kSpec, [&] {
    const double w = evaluate_scalar(width, "width");
    const double h = evaluate_scalar(height, "height");
    if (w <= 0 || h <= 0) throw ValueError("The width and height must be greater than zero");

    if (graph_recording()) return with_edge_prefix(recorded_rectangle(width, height, center, normal), tags);

    const TopoDS_Wire wire = kernel::make_polyline_wire(placed_corners(w, h, center, normal), true);
    return with_edge_prefix(finalize_primitive_with(Wire(wire), "make_rectangle_wire",
                                                    [&] { return rectangle_record("make_rectangle_wire", "wire", width, height, center, normal); }),
                            tags);
  });
}

Face make_rectangle_rface(const Scalar& width, const Scalar& height, const Scalar3& center, const Scalar3& normal,
                          const RectangleTags& tags) {
  static const ErrorSpec kSpec{kFaceOp,
                               "Failed to create a rectangular face.",
                               {"The rectangular wire could not be created.",
                                "The face construction step rejected the generated wire."},
                               {"Verify width, height, center, and normal.",
                                "Retry with positive dimensions and a valid non-zero normal vector."}};
  return guarded(kSpec, [&] {
    const Wire wire = make_rectangle_rwire(width, height, center, normal, tags);
    if (graph_recording()) return make_face_from_wire_rface(wire, normal, tags.tag_prefix);
    return profile_face(wire, "make_rectangle_face", kFaceOp, tags.tag_prefix,
                        [&] { return rectangle_record("make_rectangle_face", "face", width, height, center, normal); });
  });
}

}  // namespace scad
