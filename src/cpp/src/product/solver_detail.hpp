// What the solver's translation units share.  Private to src/product.
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/product/assembly.hpp"
#include "scad/product/constraint.hpp"
#include "scad/product/placement.hpp"
#include "scad/product/solver.hpp"

namespace scad::product::detail {

// math.radians / math.degrees, with CPython's constants.
double radians(double degrees);
double degrees(double radians);

using Bounds = std::optional<std::pair<double, double>>;

enum class Side { A, B };

// ---- frames and scalars (frames.cpp) ----------------------------------------------------------
Placement connector_local_frame(const Assembly& assembly, const ConnectorRef& ref);
Placement connector_world_frame(const Assembly& assembly, const ConnectorRef& ref);

// The relative drive coordinate of the two connectors (z offset for a prismatic, z rotation otherwise).
double constraint_current_scalar(const Assembly& assembly, const Constraint& constraint);
Bounds constraint_scalar_bounds(const Constraint& constraint);
double project_scalar(double scalar, const Bounds& bounds);
Placement motion_from_scalar(const Constraint& constraint, double scalar);
Placement constraint_motion_from_current(const Assembly& assembly, const Constraint& constraint);
double angular_error_degrees(const Placement& relative);

// The placement of the unknown side's component once the known side sits at `known_placement`.
Placement solve_other_component(const Assembly& assembly, const Constraint& constraint, Side known_side,
                                const Placement& known_placement, std::optional<double> scalar_override = {});

// ---- couplings (coupling.cpp) ------------------------------------------------------------------
Assembly solve_coupling_constraints(const Assembly& assembly);
ConstraintResidual measure_coupling_residual(const Assembly& assembly, const Constraint& constraint);
// The phase the supporting joints currently realise; empty when a supporting joint is missing.
std::optional<double> current_coupling_phase(const Assembly& assembly, const Constraint& coupling);

// ---- nested assemblies (forwarding.cpp) --------------------------------------------------------
// Close a residual by moving the component behind a forwarded public connector.
std::optional<Assembly> try_close_forwarded_constraint(const Assembly& assembly, const Constraint& constraint);

// ---- structured failures (solve_errors.cpp) ----------------------------------------------------
[[noreturn]] void raise_residual_failure(const Assembly& assembly, const std::vector<ConstraintResidual>& residuals,
                                         std::string_view stage);

enum class StructuralFailure { UnresolvableLoop, NoGroundedPath, UnsolvedComponents };
[[noreturn]] void raise_structural_failure(const Assembly& assembly, StructuralFailure kind,
                                           const Constraint* constraint = nullptr,
                                           const std::vector<std::string>& unsolved_ids = {});

// Python's `format(value, ".3g")`.
std::string format_g3(double value);

}  // namespace scad::product::detail
