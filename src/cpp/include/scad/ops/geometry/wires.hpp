// make_wire_from_edges_rwire.
#pragma once

#include <vector>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A wire through `edges`, which must chain end to start.  Identity tags of the edges
// ("circle", "line1", ...) carry over to the identical edges of the wire.
// Error "make_wire_from_edges_rwire": empty list, edges that do not connect.
Wire make_wire_from_edges_rwire(const std::vector<Edge>& edges, const OptionalString& tag_prefix = std::nullopt);

}  // namespace scad
