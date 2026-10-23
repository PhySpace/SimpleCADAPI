// Roller-chain sprockets (std/chain.py).
#pragma once

#include "scad/topo/shape.hpp"

namespace scad {

// A sprocket along +Z from the origin: a blank at the outside-diameter envelope p * (0.6 + cot(180 / z))
// opened with a roller-seat cylinder at every pitch point (and an optional bore), in one strict cut.
// Metadata "std.chain.roller_sprocket" keeps the tooth count, pitch, roller and root/outside radii.
// ValueError: fewer than 6 teeth, a dimension that is not positive and finite, a roller as large as
// the pitch, a bore as large as the root, dimensions that leave no open roller seats.
Solid make_roller_chain_sprocket_rsolid(int n_teeth, double chain_pitch, double roller_diameter,
                                        double sprocket_thickness, double bore_radius = 0.0,
                                        double roller_clearance = 0.15);

}  // namespace scad
