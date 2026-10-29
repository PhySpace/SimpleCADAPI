#include "scad/ops/geometry/faces.hpp"

#include <cmath>
#include <cstdio>

#include "internal.hpp"
#include "scad/ops/geometry/diagnostics.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

// The face the kernel builds may face away from the requested normal; Python only prints.
void warn_if_reversed(const Vec3& requested, const Face& face) {
  const double dot = requested.dot(face.normal_at());
  if (dot < 0)
    std::fprintf(stderr,
                 "Warning: the normal of the created face is opposite to the expected direction (dot product: %.3f)\n",
                 dot);
}

Wire require_wire(const Shape& shape, const char* message) {
  if (shape.kind() != Kind::Wire)
    throw ValueError(message);
  return Wire(shape);
}

}  // namespace

Face make_face_from_wire_rface(const Shape& wire, const Scalar3& normal, const OptionalString& tag_prefix) {
  static constexpr const char* kOp = "make_face_from_wire_rface";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a face from the input wire.",
      {"The input is not a Wire instance.", "The wire is open or geometrically invalid.",
       "The kernel rejected the closed wire when building a face."},
      {"Pass a Wire object, not an Edge or a list of points.", "Ensure the wire is closed before calling this API.",
       "If the wire was assembled from edges, verify the edges connect end-to-end."}};
  return guarded(kSpec, [&] {
    const Wire profile = require_wire(wire, "The input must be a Wire");
    if (!profile.is_closed())
      raise_open_wire_failure(kOp, profile, "create a face");

    // The wire is already global geometry; only the requested normal goes through the workplane.
    const Vec3 global_normal = place_vector(normal, "normal");
    Face face(kernel::make_face_from_wire(TopoDS::Wire(profile.wrapped())));
    warn_if_reversed(global_normal / global_normal.norm(), face);
    copy_metadata(profile, face);

    FinalizeSpec spec = derived_spec(record_for(kOp, [&] {
      return OpParams(kOp, derived_labels("face")).point("normal", normal).input(profile, "wire").take();
    }));
    Face result = finalize_derived(std::move(face), std::move(spec));
    result = Face(copy_exact_topology_identity_tags(std::move(result), {profile}, kOp));
    return with_shape_prefix(std::move(result), tag_prefix, kOp);
  });
}

Face make_face_from_wires_rface(const Shape& outer_wire, const std::vector<Shape>& inner_wires, const Scalar3& normal) {
  static constexpr const char* kOp = "make_face_from_wires_rface";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a face from the input outer and inner wires.",
      {"The outer wire is not a Wire instance or is not closed.",
       "One or more inner wires are not Wire instances or are not closed.",
       "The inner wires are not contained by the outer wire or are geometrically invalid.",
       "The kernel rejected the multi-loop face definition."},
      {"Pass one closed outer Wire and zero or more closed inner Wire objects.",
       "Ensure every inner wire lies inside the outer wire and does not intersect other loops.",
       "Use a valid non-zero normal vector."}};
  return guarded(kSpec, [&] {
    const Wire outer = require_wire(outer_wire, "outer_wire must be a Wire");
    if (!outer.is_closed())
      throw ValueError("outer_wire must be closed");
    std::vector<Wire> inner;
    inner.reserve(inner_wires.size());
    for (const Shape& shape : inner_wires) {
      inner.push_back(require_wire(shape, "inner_wires must contain only Wire objects"));
      if (!inner.back().is_closed())
        throw ValueError("inner wires must be closed");
    }

    const Vec3 global_normal = place_vector(normal, "normal");
    const double norm = global_normal.norm();
    if (norm <= 1e-15 || !std::isfinite(norm))
      throw ValueError("normal must be a non-zero finite vector");

    std::vector<TopoDS_Wire> raw_inner;
    raw_inner.reserve(inner.size());
    for (const Wire& wire : inner)
      raw_inner.push_back(TopoDS::Wire(wire.wrapped()));
    Face face(kernel::make_face_from_wires(TopoDS::Wire(outer.wrapped()), raw_inner));
    warn_if_reversed(global_normal / norm, face);
    copy_metadata(outer, face);

    FinalizeSpec spec = derived_spec(record_for(kOp, [&] {
      OpParams params(kOp, derived_labels("face"));
      params.point("normal", normal).integer("inner_wire_count", static_cast<std::int64_t>(inner.size()));
      params.input(outer, "outer_wire");
      for (const Wire& wire : inner)
        params.input(wire, "inner_wire");
      return params.take();
    }));
    return finalize_derived(std::move(face), std::move(spec));
  });
}

}  // namespace scad
