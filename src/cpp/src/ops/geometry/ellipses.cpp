#include "scad/ops/geometry/circles.hpp"

#include "internal.hpp"
#include "scad/ops/geometry/faces.hpp"
#include "scad/ops/geometry/plane.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

constexpr const char* kEdgeOp = "make_ellipse_redge";
constexpr const char* kWireOp = "make_ellipse_rwire";
constexpr const char* kFaceOp = "make_ellipse_rface";

struct EllipseArgs {
  const Scalar3& center;
  const Scalar& major_radius;
  const Scalar& minor_radius;
  const Scalar3& normal;
  const std::optional<Scalar3>& major_direction;

  OpRecord record(std::string_view op, std::string_view kind) const {
    return OpParams(std::string(op), primitive_labels(kind))
        .point("center", center)
        .scalar("major_radius", major_radius)
        .scalar("minor_radius", minor_radius)
        .point("normal", normal)
        .optional_point("major_direction", major_direction)
        .take();
  }
};

const ErrorSpec& edge_spec() {
  static const ErrorSpec spec{
      kEdgeOp,
      "Failed to create an ellipse edge.",
      {"The major or minor radius is not positive.", "The minor radius exceeds the major radius.",
       "The normal or major direction vector is invalid."},
      {"Use positive radii with minor not exceeding major.",
       "Pass a valid non-zero normal and an in-plane major direction."}};
  return spec;
}

TopoDS_Edge ellipse_geometry(const EllipseArgs& args) {
  return guarded(edge_spec(), [&] {
    const double major = evaluate_scalar(args.major_radius, "major_radius");
    const double minor = evaluate_scalar(args.minor_radius, "minor_radius");
    if (major <= 0 || minor <= 0)
      throw ValueError("The ellipse radii must be greater than zero");
    if (minor > major)
      throw ValueError("The ellipse minor radius cannot exceed the major radius");

    const CoordinateSystem& cs = current_cs();
    const Vec3 center_global = cs.transform_point(evaluate_point(args.center, "center"));
    const Vec3 normal_value = evaluate_point(args.normal, "normal");
    const Vec3 direction = args.major_direction ? evaluate_point(*args.major_direction, "major_direction")
                                                : default_plane_x_direction(normal_value);
    return kernel::make_ellipse_edge(center_global, major, minor, cs.transform_vector(normal_value),
                                     cs.transform_vector(direction));
  });
}

}  // namespace

Edge make_ellipse_redge(const Scalar3& center, const Scalar& major_radius, const Scalar& minor_radius,
                        const Scalar3& normal, const std::optional<Scalar3>& major_direction,
                        const OptionalString& tag_prefix) {
  return guarded(edge_spec(), [&] {
    const EllipseArgs args{center, major_radius, minor_radius, normal, major_direction};
    Edge edge =
        finalize_primitive_with(Edge(ellipse_geometry(args)), kEdgeOp, [&] { return args.record(kEdgeOp, "edge"); });
    return with_shape_prefix(std::move(edge), tag_prefix, kEdgeOp);
  });
}

Wire make_ellipse_rwire(const Scalar3& center, const Scalar& major_radius, const Scalar& minor_radius,
                        const Scalar3& normal, const EllipseOptions& options) {
  static const ErrorSpec kSpec{
      kWireOp,
      "Failed to create an elliptical wire.",
      {"The underlying ellipse edge could not be created.", "The radii or direction vectors are invalid."},
      {"Verify the center, radii, normal, and major direction values.",
       "Use positive radii with minor not exceeding major."}};
  return guarded(kSpec, [&] {
    const EllipseArgs args{center, major_radius, minor_radius, normal, options.major_direction};
    if (graph_recording()) {
      Wire wire = make_wire_from_edges_rwire(
          {make_ellipse_redge(center, major_radius, minor_radius, normal, options.major_direction)});
      return with_profile_prefix(std::move(wire), options.tag_prefix, options.edge_tag, "ellipse", kWireOp);
    }
    Wire wire = finalize_primitive_with(Wire(kernel::make_wire_from_edges({ellipse_geometry(args)})),
                                        "make_ellipse_wire", [&] { return args.record("make_ellipse_wire", "wire"); });
    return with_profile_prefix(std::move(wire), options.tag_prefix, options.edge_tag, "ellipse", kWireOp);
  });
}

Face make_ellipse_rface(const Scalar3& center, const Scalar& major_radius, const Scalar& minor_radius,
                        const Scalar3& normal, const EllipseOptions& options) {
  static const ErrorSpec kSpec{
      kFaceOp,
      "Failed to create an elliptical face.",
      {"The underlying elliptical wire could not be created.", "The kernel could not create a face from the wire."},
      {"Verify the center, radii, normal, and major direction values.",
       "Use positive radii with minor not exceeding major."}};
  return guarded(kSpec, [&] {
    const Wire wire = make_ellipse_rwire(center, major_radius, minor_radius, normal, options);
    if (graph_recording())
      return make_face_from_wire_rface(wire, normal, options.tag_prefix);
    const EllipseArgs args{center, major_radius, minor_radius, normal, options.major_direction};
    return profile_face(wire, "make_ellipse_face", kFaceOp, options.tag_prefix,
                        [&] { return args.record("make_ellipse_face", "face"); });
  });
}

}  // namespace scad
