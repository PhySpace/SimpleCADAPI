#include "scad/ops/geometry/circles.hpp"

#include "internal.hpp"
#include "scad/ops/geometry/faces.hpp"
#include "scad/ops/geometry/plane.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

constexpr const char* kEdgeOp = "make_circle_redge";
constexpr const char* kWireOp = "make_circle_rwire";
constexpr const char* kFaceOp = "make_circle_rface";

OpRecord circle_record(std::string_view op, std::string_view kind, const Scalar3& center, const Scalar& radius,
                       const Scalar3& normal) {
  return OpParams(std::string(op), primitive_labels(kind))
      .point("center", center)
      .scalar("radius", radius)
      .point("normal", normal)
      .take();
}

const ErrorSpec& edge_spec() {
  static const ErrorSpec spec{
      kEdgeOp,
      "Failed to create a circular edge.",
      {"The radius is not a positive finite scalar.", "The center or normal is not a valid finite 3D vector.",
       "The kernel rejected the circle definition."},
      {"Use a radius greater than zero.", "Pass finite center and normal vectors.",
       "If the normal is computed dynamically, verify it is not zero-length."}};
  return spec;
}

// The circle's geometry, placed through the current coordinate system.  Fails as the edge
// operator does, whoever asks.
TopoDS_Edge circle_geometry(const Scalar3& center, const Scalar& radius, const Scalar3& normal) {
  return guarded(edge_spec(), [&] {
    const double radius_value = evaluate_scalar(radius, "radius");
    if (radius_value <= 0)
      throw ValueError("The radius must be greater than zero");
    const CoordinateSystem& cs = current_cs();
    const Vec3 center_global = cs.transform_point(evaluate_point(center, "center"));
    const Vec3 normal_value = evaluate_point(normal, "normal");
    return kernel::make_circle_edge(center_global, radius_value, cs.transform_vector(normal_value),
                                    cs.transform_vector(default_plane_x_direction(normal_value)));
  });
}

}  // namespace

Edge make_circle_redge(const Scalar3& center, const Scalar& radius, const Scalar3& normal,
                       const OptionalString& tag_prefix) {
  return guarded(edge_spec(), [&] {
    Edge edge = finalize_primitive_with(Edge(circle_geometry(center, radius, normal)), kEdgeOp,
                                        [&] { return circle_record(kEdgeOp, "edge", center, radius, normal); });
    return with_shape_prefix(std::move(edge), tag_prefix, kEdgeOp);
  });
}

Wire make_circle_rwire(const Scalar3& center, const Scalar& radius, const Scalar3& normal, const ProfileTags& tags) {
  static const ErrorSpec kSpec{
      kWireOp,
      "Failed to create a circular wire.",
      {"The circle edge could not be created.", "The wire assembly step rejected the generated edge."},
      {"Check the center, radius, and normal inputs.", "Retry with a positive radius and a valid normal vector."}};
  return guarded(kSpec, [&] {
    if (graph_recording()) {
      Wire wire = make_wire_from_edges_rwire({make_circle_redge(center, radius, normal)});
      return with_profile_prefix(std::move(wire), tags.tag_prefix, tags.edge_tag, "circle", kWireOp);
    }
    Wire wire = finalize_primitive_with(
        Wire(kernel::make_wire_from_edges({circle_geometry(center, radius, normal)})), "make_circle_wire",
        [&] { return circle_record("make_circle_wire", "wire", center, radius, normal); });
    return with_profile_prefix(std::move(wire), tags.tag_prefix, tags.edge_tag, "circle", kWireOp);
  });
}

Face make_circle_rface(const Scalar3& center, const Scalar& radius, const Scalar3& normal, const ProfileTags& tags) {
  static const ErrorSpec kSpec{
      kFaceOp,
      "Failed to create a circular face.",
      {"The underlying circular wire could not be created.", "The kernel could not create a face from the wire."},
      {"Verify the center, radius, and normal values.", "Use a positive radius and a valid non-zero normal vector."}};
  return guarded(kSpec, [&] {
    const Wire wire = make_circle_rwire(center, radius, normal, tags);
    if (graph_recording())
      return make_face_from_wire_rface(wire, normal, tags.tag_prefix);
    return profile_face(wire, "make_circle_face", kFaceOp, tags.tag_prefix,
                        [&] { return circle_record("make_circle_face", "face", center, radius, normal); });
  });
}

}  // namespace scad
