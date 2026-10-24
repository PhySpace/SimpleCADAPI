// Solid primitives: box, cylinder, cone, sphere.
//
// The box, cylinder and cone are built by the tracking layer, so their faces and edges
// carry kernel-proven output roles ("box.top", "cylinder.seam", ...).  The role tags
// ask for those to be named; `tag_prefix` names the solid and its parts at once
// ("<prefix>.solid", "<prefix>.face.top", "<prefix>.edge.seam").
#pragma once

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// The keyword-only tag options of make_box_rsolid.
struct BoxTags {
  OptionalString tag_prefix;
  OptionalString result_tag;  // on the solid itself
  OptionalString bottom_face_tag, top_face_tag, front_face_tag, back_face_tag, left_face_tag, right_face_tag;
};

// The keyword-only tag options of make_cylinder_rsolid and make_cone_rsolid.
struct AxialSolidTags {
  OptionalString tag_prefix;
  OptionalString result_tag;
  OptionalString start_face_tag, end_face_tag, side_face_tag;
  OptionalString start_edge_tag, end_edge_tag, seam_edge_tag;
};

// A box of `width` along the current x axis, `height` along y and `depth` along z, centered
// on `bottom_face_center` in x and y and rising from it.
// Error "make_box_rsolid": a size that is not positive, an unnamed or duplicate role tag.
Solid make_box_rsolid(const Scalar& width, const Scalar& height, const Scalar& depth,
                      const Scalar3& bottom_face_center = scalar3(0, 0, 0), const BoxTags& tags = {});

// A cylinder rising `height` along `axis` from the center of its bottom (start) face.
Solid make_cylinder_rsolid(const Scalar& radius, const Scalar& height,
                           const Scalar3& bottom_face_center = scalar3(0, 0, 0), const Scalar3& axis = scalar3(0, 0, 1),
                           const AxialSolidTags& tags = {});

// A frustum rising `height` along `axis`, tapering from `bottom_radius` to `top_radius`
// (a cone when it is 0, which has no end face: `end_face_tag` is then an error).
Solid make_cone_rsolid(const Scalar& bottom_radius, const Scalar& height, const Scalar& top_radius = Scalar(0.0),
                       const Scalar3& bottom_face_center = scalar3(0, 0, 0), const Scalar3& axis = scalar3(0, 0, 1),
                       const AxialSolidTags& tags = {});

Solid make_sphere_rsolid(const Scalar& radius, const Scalar3& center = scalar3(0, 0, 0));

}  // namespace scad
