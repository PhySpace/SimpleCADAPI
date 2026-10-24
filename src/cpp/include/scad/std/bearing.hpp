// Radial ball bearings (std/bearing.py).
//
// `build_ball_bearing`, the durable-definition wrapper of the Python module, is not ported: it
// is a `build.part` / `build.assemble` decorator application and the build layer stays Python.
#pragma once

#include <optional>
#include <string>

#include "scad/product/assembly.hpp"
#include "scad/product/material.hpp"

namespace scad {

struct BallBearingOptions {
  // Default: as many balls as fit with half a diameter of gap, at least 3.
  std::optional<int> ball_count;
  double raceway_clearance = 0.02;  // groove radius = ball radius + clearance
  double edge_chamfer = 0.0;        // on the long (circular) edges of both rings
  std::string assembly_id = "ball_bearing";
  std::optional<double> drive_angle_degrees;  // drives the inner/outer revolute constraint
  // Embed the balls into the outer race and union them into one body (a simplified solver or export body).
  bool fuse_rolling_elements = false;
  double rolling_element_fuse_overlap = 0.01;
  std::optional<product::Material> material;  // assigned to the rings and the ball part
};

// A radial ball bearing along Z, centred on the origin: components `outer_ring`, `inner_ring`
// and `ball_NN` (one per rolling element, all sharing the part "<assembly_id>_ball"), a revolute
// constraint `inner_outer_revolute`, and public connectors `outer_axis` / `inner_axis`.
// Metadata "std.bearing.ball_bearing" holds the resolved geometry.  Rings carry the tags
// role.outer_ring / role.inner_ring and group.ball_bearing, balls role.rolling_element.
// ValueError: a diameter or width that is not positive and finite, an outer diameter not above the
// bore, no radial wall or axial clearance left, a chamfer thicker than the thinnest feature, fewer
// than 3 balls or balls that do not fit the pitch circle.
product::AssemblyPtr make_ball_bearing_rassembly(double bore_diameter, double outer_diameter, double bearing_width,
                                                 double ball_diameter, const BallBearingOptions& options = {});

}  // namespace scad
