// make_wire_from_edges_rwire.
#pragma once

#include <vector>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A wire through `edges`, given in any order: they must connect into one chain (the kernel orders them; an edge that
// touches none of the others is an error, never left out).  Identity tags of the edges
// ("circle", "line1", ...) carry over to the identical edges of the wire.
// Error "make_wire_from_edges_rwire": empty list, edges that do not connect.
Wire make_wire_from_edges_rwire(const std::vector<Edge>& edges, const OptionalString& tag_prefix = std::nullopt);

// What an operation that takes a wire is given: the Wire itself, or for an Edge the wire of that one edge (nothing is
// lost: the same edge, its tags and lineage), made by make_wire_from_edges_rwire so a recording sees where it came
// from.  ValueError `message` for any other shape.
Wire as_wire(const Shape& shape, const char* message);

// `shapes` with every Edge made the wire of that one edge (as_wire); the other shapes as they are.
std::vector<Shape> edges_as_wires(const std::vector<Shape>& shapes);

}  // namespace scad
