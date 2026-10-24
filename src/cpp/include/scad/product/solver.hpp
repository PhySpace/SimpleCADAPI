// The assembly constraint solver (product/solver.py).
//
// Solving propagates placements from the grounded components outward through the connecting
// constraints (fixed, revolute, prismatic): the constraint says where the far connector frame
// sits relative to the near one, and the far component's placement follows.  A drive scalar
// (angle / distance) is clamped into its ScalarLimit; without one the current relative scalar
// is kept (and projected into a limit).  Gear, belt and rack-pinion couplings then set the free
// coordinate of one supporting joint from the other.  A report of every residual is stored on
// the result under the "constraint_report" runtime key.
#pragma once

#include <string_view>

#include "scad/core/value.hpp"
#include "scad/product/assembly.hpp"
#include "scad/product/constraint.hpp"

namespace scad::product {

inline constexpr double kPlacementTolerance = 1e-7;   // mm
inline constexpr double kAngleToleranceDegrees = 1e-6;

// Place every component reachable from a grounded one.
//   strict: a residual above tolerance, an unreachable component, or a loop with nothing to
//   drive is a structured Error("solve_assembly_constraints", ...); not strict, the best effort is returned.
// An assembly without constraints is returned as it is (the same pointer).  ValueError when
// there are constraints but no grounded component.
AssemblyPtr solve_assembly_constraints(const AssemblyPtr& assembly, bool strict = true);

// The residual of one constraint in the assembly's current placements.  KeyError for an unknown id.
ConstraintResidual measure_constraint_residual(const Assembly& assembly, std::string_view constraint_id);

// Every residual, and which components the grounded ones reach through connecting constraints.
ConstraintReport inspect_assembly_constraints(const Assembly& assembly);

// The phase offset that makes a coupling constraint hold in the assembly's current placements
// (0 when a supporting joint is missing).  ValueError for a constraint that is not a coupling.
double coupling_phase_offset(const Assembly& assembly, const Constraint& constraint);

// Two reports (ConstraintReport::to_dict) agree: same verdict, same component sets, and residuals
// within the solver's tolerances.
bool constraint_reports_match(const Value& actual, const Value& expected);

}  // namespace scad::product
