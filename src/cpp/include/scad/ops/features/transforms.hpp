// Rigid and affine transforms, and the patterns built from them.
#pragma once

#include <vector>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// The shape moved by `vector` (current coordinates).  A Solid result carries the tags of its
// faces and edges; any other shape keeps its own.  Error "translate_shape".
Shape translate_shape(const Shape& shape, const Scalar3& vector);

// `angle` degrees about the line through `origin` along `axis`; angle 0 returns `shape` itself.
// Error "rotate_shape".
Shape rotate_shape(const Shape& shape, const Scalar& angle, const Scalar3& axis = scalar3(0, 0, 1),
                   const Scalar3& origin = scalar3(0, 0, 0));

// The reflection through the plane (origin, normal), in current coordinates.  Error "mirror_shape".
Shape mirror_shape(const Shape& shape, const Scalar3& plane_origin, const Scalar3& plane_normal);

// Scale along the current axes about `center`; factors finite and nonzero.  Uniform scales keep
// analytic surfaces.  Recorded as make_scale_rsolid.
Solid scale_rsolid(const Solid& solid, const Scalar3& factors, const Scalar3& center = scalar3(0, 0, 0));

// A finite nonsingular 4x4 affine matrix (row-major, last row 0 0 0 1) in the current
// coordinate system.  Recorded as make_transform_rsolid.
Solid transform_rsolid(const Solid& solid, const std::vector<std::vector<Scalar>>& matrix);

// `count` copies of `shape`, `spacing` apart along `direction`.  Error "linear_pattern_rsolidlist".
std::vector<Shape> linear_pattern_rsolidlist(const Shape& shape, const Scalar3& direction, int count,
                                             const Scalar& spacing);

// `count` copies spread over `total_rotation_angle` degrees about the axis.
// Error "radial_pattern_rsolidlist".
std::vector<Shape> radial_pattern_rsolidlist(const Shape& shape, const Scalar3& center, const Scalar3& axis, int count,
                                             const Scalar& total_rotation_angle);

}  // namespace scad
