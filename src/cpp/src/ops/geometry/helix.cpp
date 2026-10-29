#include "scad/ops/geometry/helix.hpp"

#include "internal.hpp"
#include "scad/ops/geometry/plane.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

constexpr const char* kEdgeOp = "make_helix_redge";

OpRecord helix_record(std::string_view op, std::string_view kind, const Scalar& pitch, const Scalar& height,
                      const Scalar& radius, const Scalar3& center, const Scalar3& dir, std::string_view handedness) {
  return OpParams(std::string(op), primitive_labels(kind))
      .scalar("pitch", pitch)
      .scalar("height", height)
      .scalar("radius", radius)
      .point("center", center)
      .point("dir", dir)
      .text("handedness", handedness)
      .take();
}

// The helix wire of the given sizes, placed through the current coordinate system.
TopoDS_Wire helix_wire(double pitch, double height, double radius, const Scalar3& center, const Scalar3& dir,
                       std::string_view handedness) {
  const CoordinateSystem& cs = current_cs();
  const Vec3 center_global = cs.transform_point(evaluate_point(center, "center"));
  const Vec3 dir_value = evaluate_point(dir, "dir");
  return kernel::make_helix_wire(pitch, height, radius, center_global, cs.transform_vector(dir_value),
                                 cs.transform_vector(default_plane_x_direction(dir_value)), handedness);
}

}  // namespace

Edge make_helix_redge(const Scalar& pitch, const Scalar& height, const Scalar& radius, const Scalar3& center,
                      const Scalar3& dir, std::string_view handedness) {
  static const ErrorSpec kSpec{
      kEdgeOp,
      "Failed to create a helix edge.",
      {"Pitch, height, or radius is not positive.", "The center or direction vector is invalid.",
       "The kernel rejected the helix definition."},
      {"Use positive pitch, height, and radius values.", "Pass a valid center and a non-zero direction vector.",
       "Inspect the evaluated helix parameters before retrying."}};
  return guarded(kSpec, [&] {
    if (handedness != "Right" && handedness != "Left")
      throw ValueError("handedness must be 'Right' or 'Left'");
    const double pitch_value = evaluate_scalar(pitch, "pitch");
    const double height_value = evaluate_scalar(height, "height");
    const double radius_value = evaluate_scalar(radius, "radius");
    if (pitch_value <= 0)
      throw ValueError("The pitch must be greater than zero");
    if (height_value <= 0)
      throw ValueError("The height must be greater than zero");
    if (radius_value <= 0)
      throw ValueError("The radius must be greater than zero");

    // The edge belongs to the wire it was found in, like the Python wrapper tree.
    const Wire wire(helix_wire(pitch_value, height_value, radius_value, center, dir, handedness));
    std::vector<Edge> edges = wire.edges();
    if (edges.empty())
      throw ValueError("Cannot extract edges from the helix");
    return finalize_primitive_with(std::move(edges.front()), kEdgeOp, [&] {
      return helix_record(kEdgeOp, "edge", pitch, height, radius, center, dir, handedness);
    });
  });
}

Wire make_helix_rwire(const Scalar& pitch, const Scalar& height, const Scalar& radius, const Scalar3& center,
                      const Scalar3& dir, std::string_view handedness) {
  static constexpr const char* kOp = "make_helix_rwire";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a helix wire.",
      {"The helix parameters are invalid.", "The direction vector is zero or malformed.",
       "The kernel rejected the wire geometry."},
      {"Use positive pitch, height, and radius values.", "Pass a valid center and a non-zero direction vector.",
       "Retry after logging the evaluated helix parameters."}};
  return guarded(kSpec, [&] {
    if (graph_recording())
      return make_wire_from_edges_rwire({make_helix_redge(pitch, height, radius, center, dir, handedness)});
    const TopoDS_Wire wire = helix_wire(evaluate_scalar(pitch, "pitch"), evaluate_scalar(height, "height"),
                                        evaluate_scalar(radius, "radius"), center, dir, handedness);
    return finalize_primitive_with(Wire(wire), "make_helix_wire", [&] {
      return helix_record("make_helix_wire", "wire", pitch, height, radius, center, dir, handedness);
    });
  });
}

}  // namespace scad
