// Circles and ellipses, as edges, wires and faces.
#pragma once

#include <optional>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// The keyword-only options of the circle / ellipse wires and faces.
struct ProfileTags {
  OptionalString tag_prefix;  // "<prefix>.wire" / "<prefix>.face", and "<prefix>.edge.<edge_tag>"
  OptionalString edge_tag;    // local name of the one edge (default "circle" / "ellipse")
};

struct EllipseOptions {
  std::optional<Scalar3> major_direction;  // in-plane; default: the plane basis of `normal`
  OptionalString tag_prefix;
  OptionalString edge_tag;
};

// Errors "make_circle_redge" / "_rwire" / "_rface": radius not positive, invalid vectors.
Edge make_circle_redge(const Scalar3& center, const Scalar& radius, const Scalar3& normal = scalar3(0, 0, 1),
                       const OptionalString& tag_prefix = std::nullopt);
Wire make_circle_rwire(const Scalar3& center, const Scalar& radius, const Scalar3& normal = scalar3(0, 0, 1),
                       const ProfileTags& tags = {});
Face make_circle_rface(const Scalar3& center, const Scalar& radius, const Scalar3& normal = scalar3(0, 0, 1),
                       const ProfileTags& tags = {});

// Errors "make_ellipse_redge" / ...: radii not positive, minor radius larger than major.
Edge make_ellipse_redge(const Scalar3& center, const Scalar& major_radius, const Scalar& minor_radius,
                        const Scalar3& normal = scalar3(0, 0, 1),
                        const std::optional<Scalar3>& major_direction = std::nullopt,
                        const OptionalString& tag_prefix = std::nullopt);
Wire make_ellipse_rwire(const Scalar3& center, const Scalar& major_radius, const Scalar& minor_radius,
                        const Scalar3& normal = scalar3(0, 0, 1), const EllipseOptions& options = {});
Face make_ellipse_rface(const Scalar3& center, const Scalar& major_radius, const Scalar& minor_radius,
                        const Scalar3& normal = scalar3(0, 0, 1), const EllipseOptions& options = {});

}  // namespace scad
