// The bearing races: revolved profiles with a circular raceway groove.
#pragma once

#include <string_view>

#include "scad/topo/shape.hpp"

namespace scad::stdlib {

enum class RingRole { Inner, Outer };

// A ring of `inner_radius`..`outer_radius` and `bearing_width`, its groove an arc of
// `groove_radius` centred on `ball_pitch_radius`.  Tagged role.<role> and group.ball_bearing, chamfered
// on its circular edges, metadata "std.bearing.ring".
// ValueError when the shoulder radius does not expose the groove.
Solid make_race_ring_solid(double bore_or_inner_radius, double outer_or_shoulder_radius, double ball_pitch_radius,
                           double groove_radius, double bearing_width, double edge_chamfer, RingRole role);

}  // namespace scad::stdlib
