// Faces from wires.
#pragma once

#include <vector>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// The planar face bounded by a closed wire.  `normal` (local coordinates) only checks the
// orientation: a face the kernel builds against it is reported on stderr, as the Python SDK
// prints a warning.  The face carries the wire's metadata and the identity tags of its edges.
// Error "make_face_from_wire_rface": not a wire; an open wire (with the measured gap).
Face make_face_from_wire_rface(const Shape& wire, const Scalar3& normal = scalar3(0, 0, 1),
                               const OptionalString& tag_prefix = std::nullopt);

// A face with holes: `outer_wire` and any number of `inner_wires`, all closed.
// Error "make_face_from_wires_rface".
Face make_face_from_wires_rface(const Shape& outer_wire, const std::vector<Shape>& inner_wires,
                                const Scalar3& normal = scalar3(0, 0, 1));

}  // namespace scad
