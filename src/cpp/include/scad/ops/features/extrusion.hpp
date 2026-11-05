// Prisms: extrude, tapered extrude, extrude until a target.
#pragma once

#include <string_view>
#include <vector>

#include "scad/ops/features/support.hpp"
#include "scad/ops/features/tags.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A prism of `profile` (a closed Wire or a Face) along `direction` (current coordinates)
// by `distance`.  Roles: extrusion.start / .end (the caps), extrusion.side.
// Error "extrude_rsolid": non-positive distance, zero direction, an open wire (with the
// measured gap), neither wire nor face, a rejected kernel build.
Solid extrude_rsolid(const Shape& profile, const Scalar3& direction, const Scalar& distance,
                     const SweepTags& tags = {});

// Press or pull one planar face of `solid` along its outward normal by a signed `distance`: positive pulls it out
// (the prism of the face joined), negative presses it in (the prism cut), zero leaves the solid.  Recorded as its
// steps (make_extrude_rsolid, then make_union_rsolid or make_cut_rsolid).
Solid press_pull_rsolid(const Solid& solid, const FaceSelection& face, const Scalar& distance);

// A planar face extruded by `vector` with `taper` degrees of draft (positive shrinks the outer
// loop; inner loops go the other way when `flip_inner`).  Recorded as make_extrude_taper_rsolid.
Solid extrude_taper_rsolid(const Face& profile, const Scalar3& vector, const Scalar& taper, bool flip_inner = true);

// A planar face extruded along `direction` until it meets `targets`: until is "NEXT" (forward,
// nearest surface), "LAST" (forward, farthest), "PREVIOUS" (reverse, nearest) or "FIRST"
// (reverse, farthest).  Recorded as make_extrude_until_rsolid.
Solid extrude_until_rsolid(const Face& profile, const std::vector<Solid>& targets,
                           const Scalar3& direction = scalar3(0, 0, 1), std::string_view until = "NEXT");

}  // namespace scad
