// Solved sketch -> OCCT: the edges and wires of a profile, in world coordinates.
//
// Internal to the sketch library.  Everything goes through scad::kernel; a
// sketch never reads current_cs() here because its plane was placed through the
// active workplane when the sketch was made.
#pragma once

#include <string>
#include <utility>
#include <vector>

#include <TopoDS_Edge.hxx>

#include "scad/sketch/profile.hpp"
#include "scad/sketch/sketch.hpp"
#include "scad/topo/shape.hpp"

namespace scad::sketch_detail {

// A profile's wire plus the OCCT edge each sketch entity became (Python keeps
// this as the wire's "sketch.entity_edges" runtime value).
struct ProfileWire {
  Wire wire;
  std::vector<std::pair<std::string, TopoDS_Edge>> entity_edges;
};

// Sketch._wire_from_profile_payload.  ValueError for degenerate arcs and
// ellipses with the Python messages.
ProfileWire wire_from_profile(const Sketch& sketch, const SketchProfile& profile);

}  // namespace scad::sketch_detail
