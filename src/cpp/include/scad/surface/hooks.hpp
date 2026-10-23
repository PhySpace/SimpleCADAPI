// Extension points of the surface operators.
//
// Both are process-wide and meant to be installed once, at import time, by
// whoever owns the missing half: the surface area sits below the reactive and
// diagnostics areas and cannot include them.  Without a hook the operators
// behave as if no scalar carried units and no loft failure could be explained.
#pragma once

#include <string_view>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/surface/types.hpp"

namespace scad {

// ---- units -----------------------------------------------------------------
// make_cylindrical_surface_rface rejects unit-aware scalars of the wrong
// dimension (an angle where a length is expected, ...), like
// expression_uses_units / infer_dimension in the Python SDK.
enum class UnitDimension { Dimensionless, Length, Other };

struct ScalarUnits {
  bool uses_units = false;  // the expression declares at least one unit
  UnitDimension dimension = UnitDimension::Dimensionless;
};

using ScalarUnitsProbe = ScalarUnits (*)(const Scalar&);

// nullptr removes the probe.
void set_scalar_units_probe(ScalarUnitsProbe probe) noexcept;
// What the installed probe says; {false, Dimensionless} without one or for a plain number.
ScalarUnits scalar_units(const Scalar& value);

// ---- loft diagnosis ----------------------------------------------------------
// loft_rshell re-reads its sections when the kernel fails and, if a verdict can be
// computed (coincident stations, edge-count mismatch, open wires, ...), raises it as a
// scad::Error instead of the generic wrap.  The diagnoser throws when it explains the
// failure and returns quietly otherwise.
using LoftFailureDiagnoser = void (*)(const std::vector<LoftSection>& sections, std::string_view operation);

void set_loft_failure_diagnoser(LoftFailureDiagnoser diagnoser) noexcept;
// Runs the installed diagnoser (if any); exceptions other than scad::Error from it are swallowed.
void diagnose_loft_failure(const std::vector<LoftSection>& sections, std::string_view operation);

}  // namespace scad
