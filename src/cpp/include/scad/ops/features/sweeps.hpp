// Solids swept or skinned through sections: loft, sweep, twisted sweep, helical sweep,
// multi-section sweep.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

#include "scad/ops/features/tags.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

struct LoftOptions {
  std::string tracking_policy = "full";  // "graph": no face roles, so no role tags or prefix
  SweepTags tags;                        // roles: loft.start / .end (Wire ends only), loft.side
};

// A solid through `profiles` (Wires, or Vertex caps at the ends; at least two, one a Wire).
// A failure is first explained by comparing the sections (coincident stations, edge counts,
// open wires, order).  Error "loft_rsolid".
Solid loft_rsolid(const std::vector<Shape>& profiles, bool ruled = false, const LoftOptions& options = {});

// A face swept along a wire.  Roles: sweep.start / .end / .side.  Error "sweep_rsolid".
Solid sweep_rsolid(const Face& profile, const Wire& path, bool is_frenet = false, const SweepTags& tags = {});

struct TwistedSweepOptions {
  Scalar guide_radius = Scalar(1.0);
  SweepTags tags;  // roles: twisted_sweep.start / .end / .side
};

// A planar face swept along a straight axis with a linear rotation of `twist_angle` degrees:
// one continuous side face per profile edge.  Error "twisted_sweep_rsolid".
Solid twisted_sweep_rsolid(const Shape& profile, const Scalar& distance, const Scalar& twist_angle,
                           const Scalar3& axis = scalar3(0, 0, 1), const Scalar3& origin = scalar3(0, 0, 0),
                           const TwistedSweepOptions& options = {});

// A profile wire swept along a helix.  In a recording session it is built from recorded steps
// (helix, face, sweep); otherwise in one kernel call, which ignores `handedness` like the Python
// SDK.  Error "helical_sweep_rsolid".
Solid helical_sweep_rsolid(const Wire& profile, const Scalar& pitch, const Scalar& height, const Scalar& radius,
                           const Scalar3& center = scalar3(0, 0, 0), const Scalar3& dir = scalar3(0, 0, 1),
                           std::string_view handedness = "Right");

// An auxiliary direction (current coordinates) or spine wire fixing the section orientation.
using Binormal = std::variant<Scalar3, Wire>;

// Ordered sections (Faces contribute their outer wire) swept along `path`.  Recorded as
// make_sweep_multisection_rsolid.
Solid sweep_multisection_rsolid(const std::vector<Shape>& profiles, const Wire& path, bool is_frenet = false,
                                const std::optional<Binormal>& binormal = std::nullopt);

}  // namespace scad
