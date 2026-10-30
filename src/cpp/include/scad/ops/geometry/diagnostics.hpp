// Why a wire is not closed (operators/_diagnostics.py: diagnose_open_wire,
// raise_open_wire_failure).
//
// The structured failure every operator that needs a closed profile raises
// (make_face_from_wire_rface, extrude_rsolid, ...): the measured gap between the closest
// dangling ends, with a repair hint.  Unlike the Python SDK it attaches no rendered
// evidence image: the measurements carry the same facts as text.
#pragma once

#include <optional>
#include <string_view>

#include "scad/core/vec.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

struct WireGapDiagnosis {
  double gap_distance = 0.0;  // the smallest dangling end-to-end gap
  Vec3 point_a, point_b;      // its two ends
  int edge_count = 0;
  int chain_count = 0;  // > 1: the wire is not even connected
  int dangling_count = 0;
};

// Chains the edges by end-point proximity and reports the closest dangling pair.  nullopt
// when the ends cannot be probed or every end is matched.
std::optional<WireGapDiagnosis> diagnose_open_wire(const Wire& wire);

// Throws the "the given wire is not closed" Error for `operation`.  `purpose` finishes the
// sentence "... so it cannot be used to <purpose>" ("create a face", "extrude it into a solid").
[[noreturn]] void raise_open_wire_failure(std::string_view operation, const Wire& wire, std::string_view purpose);

}  // namespace scad
