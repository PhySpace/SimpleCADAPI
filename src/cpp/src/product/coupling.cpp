// Gear, belt and rack-pinion couplings: a relation between the drive coordinates of the two
// joints (revolute / prismatic) that carry the coupled connectors.
#include <algorithm>
#include <cmath>

#include "scad/core/error.hpp"
#include "solver_detail.hpp"

namespace scad::product {

namespace detail {

namespace {

// One end of a coupling: the joint that carries the connector, or a grounded component (which
// does not move: its coordinate is 0).
struct Endpoint {
  std::optional<Constraint> support;  // empty: grounded
};

bool is_grounded(const Assembly& assembly, const std::string& component_id) {
  const auto& grounded = assembly.grounded_component_ids();
  return std::find(grounded.begin(), grounded.end(), component_id) != grounded.end();
}

std::optional<Constraint> support_constraint_for(const Assembly& assembly, const ConnectorRef& ref,
                                                 std::string_view support_kind) {
  for (const Constraint& constraint : assembly.constraints()) {
    if (constraint.constraint_kind() != support_kind)
      continue;
    if (constraint.connector_a() == ref || constraint.connector_b() == ref)
      return constraint;
  }
  return std::nullopt;
}

std::optional<Endpoint> endpoint_for(const Assembly& assembly, const ConnectorRef& ref, std::string_view support_kind) {
  if (auto support = support_constraint_for(assembly, ref, support_kind))
    return Endpoint{std::move(support)};
  if (is_grounded(assembly, ref.component_id()))
    return Endpoint{};
  return std::nullopt;
}

double support_scalar(const Assembly& assembly, const Constraint& support) {
  return project_scalar(constraint_current_scalar(assembly, support), constraint_scalar_bounds(support));
}

double endpoint_scalar(const Assembly& assembly, const Endpoint& endpoint) {
  return endpoint.support ? support_scalar(assembly, *endpoint.support) : 0.0;
}

bool can_accept_coupled_scalar(const Endpoint& endpoint) {
  if (!endpoint.support)
    return false;
  const Constraint& support = *endpoint.support;
  if (support.constraint_kind() == "revolute")
    return !support.drive_angle_degrees();
  if (support.constraint_kind() == "prismatic")
    return !support.drive_distance();
  return false;
}

Placement component_placement_for_support_scalar(const Assembly& assembly, const Constraint& support, double scalar) {
  const std::string& a_id = support.connector_a().component_id();
  const std::string& b_id = support.connector_b().component_id();
  const bool a_grounded = is_grounded(assembly, a_id);
  const bool b_grounded = is_grounded(assembly, b_id);
  if (b_grounded && !a_grounded) {
    return solve_other_component(assembly, support, Side::B, assembly.get_component(b_id).placement, scalar);
  }
  return solve_other_component(assembly, support, Side::A, assembly.get_component(a_id).placement, scalar);
}

Assembly set_endpoint_scalar(const Assembly& assembly, const Endpoint& endpoint, double scalar) {
  if (!endpoint.support)
    return assembly;
  const Constraint& support = *endpoint.support;
  scalar = project_scalar(scalar, constraint_scalar_bounds(support));
  const ConnectorRef& moving_ref =
      is_grounded(assembly, support.connector_b().component_id()) ? support.connector_a() : support.connector_b();
  const Placement placement = component_placement_for_support_scalar(assembly, support, scalar);
  return assembly.with_component_placement(moving_ref.component_id(), placement);
}

std::optional<std::pair<Endpoint, Endpoint>> coupling_supports(const Assembly& assembly, const Constraint& coupling) {
  const bool rack = coupling.constraint_kind() == "rack_pinion";
  auto first = endpoint_for(assembly, coupling.connector_a(), rack ? "prismatic" : "revolute");
  auto second = endpoint_for(assembly, coupling.connector_b(), "revolute");
  if (!first || !second)
    return std::nullopt;
  return std::pair{std::move(*first), std::move(*second)};
}

double phase_from_supports(const Assembly& assembly, const Constraint& coupling, const Endpoint& a, const Endpoint& b) {
  const double scalar_a = endpoint_scalar(assembly, a);
  const double scalar_b = endpoint_scalar(assembly, b);
  if (coupling.constraint_kind() == "gear") {
    return *coupling.pitch_radius_a() * radians(scalar_a) + *coupling.pitch_radius_b() * radians(scalar_b);
  }
  if (coupling.constraint_kind() == "belt") {
    return *coupling.pulley_radius_a() * radians(scalar_a) - *coupling.pulley_radius_b() * radians(scalar_b);
  }
  return scalar_a + *coupling.pitch_radius() * radians(scalar_b);
}

// The coordinates that satisfy the coupling when one side is free: {target_a, target_b}.
struct Targets {
  double a, b;
};

Targets coupled_targets(const Constraint& coupling, double phase, double scalar_a, double scalar_b) {
  if (coupling.constraint_kind() == "gear") {
    return {degrees((phase - *coupling.pitch_radius_b() * radians(scalar_b)) / *coupling.pitch_radius_a()),
            degrees((phase - *coupling.pitch_radius_a() * radians(scalar_a)) / *coupling.pitch_radius_b())};
  }
  if (coupling.constraint_kind() == "belt") {
    return {degrees((phase + *coupling.pulley_radius_b() * radians(scalar_b)) / *coupling.pulley_radius_a()),
            degrees((*coupling.pulley_radius_a() * radians(scalar_a) - phase) / *coupling.pulley_radius_b())};
  }
  // rack and pinion: the rack coordinate is a length, the pinion's an angle.
  return {phase - *coupling.pitch_radius() * radians(scalar_b), degrees((phase - scalar_a) / *coupling.pitch_radius())};
}

}  // namespace

Assembly solve_coupling_constraints(const Assembly& assembly) {
  Assembly result = assembly;
  for (const Constraint& coupling : assembly.constraints()) {
    if (!coupling.is_coupling())
      continue;
    const auto supports = coupling_supports(result, coupling);
    if (!supports)
      continue;
    const auto& [support_a, support_b] = *supports;
    const double phase = coupling.phase_offset().value_or(0.0);
    const double scalar_a = endpoint_scalar(result, support_a);
    const double scalar_b = endpoint_scalar(result, support_b);
    const bool can_set_a = can_accept_coupled_scalar(support_a);
    const bool can_set_b = can_accept_coupled_scalar(support_b);
    const Targets target = coupled_targets(coupling, phase, scalar_a, scalar_b);
    if (!can_set_a && can_set_b) {
      result = set_endpoint_scalar(result, support_b, target.b);
    } else if (can_set_a && !can_set_b) {
      result = set_endpoint_scalar(result, support_a, target.a);
    }
  }
  return result;
}

ConstraintResidual measure_coupling_residual(const Assembly& assembly, const Constraint& constraint) {
  const auto supports = coupling_supports(assembly, constraint);
  if (!supports)
    return {constraint.constraint_id(), 1.0e30, 0.0, false};
  const double residual = std::abs(phase_from_supports(assembly, constraint, supports->first, supports->second) -
                                   constraint.phase_offset().value_or(0.0));
  double angular_error = 0.0;
  if (constraint.constraint_kind() == "gear") {
    angular_error = degrees(residual / *constraint.pitch_radius_b());
  } else if (constraint.constraint_kind() == "belt") {
    angular_error = degrees(residual / *constraint.pulley_radius_b());
  } else if (constraint.constraint_kind() == "rack_pinion") {
    angular_error = degrees(residual / *constraint.pitch_radius());
  }
  return {constraint.constraint_id(), residual, std::abs(angular_error), residual <= kPlacementTolerance};
}

std::optional<double> current_coupling_phase(const Assembly& assembly, const Constraint& coupling) {
  const auto supports = coupling_supports(assembly, coupling);
  if (!supports)
    return std::nullopt;
  return phase_from_supports(assembly, coupling, supports->first, supports->second);
}

}  // namespace detail

double coupling_phase_offset(const Assembly& assembly, const Constraint& constraint) {
  if (!constraint.is_coupling())
    throw ValueError("constraint must be a gear, belt, or rack_pinion constraint");
  return detail::current_coupling_phase(assembly, constraint).value_or(0.0);
}

}  // namespace scad::product
