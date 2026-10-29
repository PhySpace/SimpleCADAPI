// solve_assembly_constraints: placement propagation from the grounded components.
#include <algorithm>
#include <cmath>
#include <map>
#include <set>

#include "scad/core/error.hpp"
#include "solver_detail.hpp"

namespace scad::product {

namespace detail {

namespace {

constexpr double kGoldenTolerance = 1e-10;
constexpr int kGoldenMaxIterations = 200;

// Minimises `func` on [a, b] (golden-section search).
double golden_section_search(const std::function<double(double)>& func, double a, double b) {
  const double phi = (std::sqrt(5.0) - 1.0) / 2.0;
  double c = b - phi * (b - a);
  double d = a + phi * (b - a);
  double fc = func(c);
  double fd = func(d);
  for (int i = 0; i < kGoldenMaxIterations; ++i) {
    if (b - a <= kGoldenTolerance)
      break;
    if (fc < fd) {
      b = d;
      d = c;
      fd = fc;
      c = b - phi * (b - a);
      fc = func(c);
    } else {
      a = c;
      c = d;
      fc = fd;
      d = a + phi * (b - a);
      fd = func(d);
    }
  }
  return (a + b) / 2.0;
}

// Residual of the constraint when the unknown side's component is placed for `candidate_scalar`.
double loop_residual_at_scalar(const Assembly& assembly, const Constraint& constraint, Side known_side,
                               const Placement& known_placement, double candidate_scalar) {
  const ConnectorRef& unknown_ref = known_side == Side::A ? constraint.connector_b() : constraint.connector_a();
  const ConnectorRef& known_ref = known_side == Side::A ? constraint.connector_a() : constraint.connector_b();
  Placement motion = motion_from_scalar(constraint, candidate_scalar);
  if (known_side == Side::B)
    motion = inverse_placement(motion);
  const Placement known_frame = known_placement.compose(connector_local_frame(assembly, known_ref));
  const Placement target_placement =
      known_frame.compose(motion).compose(inverse_placement(connector_local_frame(assembly, unknown_ref)));
  const Assembly test = assembly.with_component_placement(unknown_ref.component_id(), target_placement);
  const ConstraintResidual residual = measure_constraint_residual(test, constraint.constraint_id());
  return residual.translation_error + radians(residual.angular_error_degrees);
}

// The drive scalar of the constraint when its known side is placed: the drive clamped into the
// limits, else the current relative scalar projected into them, else none (the current one is used).
std::optional<double> propagation_scalar(const Assembly& assembly, const Constraint& constraint) {
  const Bounds bounds = constraint_scalar_bounds(constraint);
  if (constraint.constraint_kind() == "revolute" && constraint.drive_angle_degrees()) {
    return project_scalar(*constraint.drive_angle_degrees(), bounds);
  }
  if (constraint.constraint_kind() == "prismatic" && constraint.drive_distance()) {
    return project_scalar(*constraint.drive_distance(), bounds);
  }
  if (bounds)
    return project_scalar(constraint_current_scalar(assembly, constraint), bounds);
  return std::nullopt;
}

Value authored_placements_of(const Assembly& assembly) {
  const Value existing = assembly.get_runtime(kAuthoredPlacementsKey);
  if (!existing.is_null())
    return existing;
  Value authored = Value::object();
  for (const Component& component : assembly.components())
    authored.set(component.component_id, component.placement.to_dict());
  return authored;
}

Value definition_runtime_of(const Assembly& assembly) {
  Value out = Value::object();
  if (!assembly.runtime().is_object())
    return out;
  for (const auto& [key, value] : assembly.runtime().as_object()) {
    if (key.rfind(kDefinitionRuntimePrefix, 0) == 0)
      out.set(key, value);
  }
  return out;
}

}  // namespace

}  // namespace detail

AssemblyPtr solve_assembly_constraints(const AssemblyPtr& input, bool strict) {
  using namespace detail;
  if (!input)
    throw TypeError("assembly must be an Assembly");
  const Value definition_runtime = definition_runtime_of(*input);
  const Value authored = authored_placements_of(*input);
  if (input->constraints().empty())
    return input;
  if (input->grounded_component_ids().empty()) {
    throw ValueError("assembly constraints require at least one grounded component");
  }

  Assembly assembly = *input;
  std::map<std::string, Placement> solved;
  for (const std::string& id : assembly.grounded_component_ids())
    solved.emplace(id, assembly.get_component(id).placement);

  std::vector<Constraint> pending;
  for (const Constraint& constraint : assembly.constraints()) {
    if (!constraint.is_coupling())
      pending.push_back(constraint);
  }

  const auto place_other = [&](const Constraint& constraint, Side known_side, const std::string& known_id,
                               const std::string& unknown_id) {
    const std::optional<double> scalar = propagation_scalar(assembly, constraint);
    solved.insert_or_assign(unknown_id,
                            solve_other_component(assembly, constraint, known_side, solved.at(known_id), scalar));
  };

  for (bool progressed = true; !pending.empty() && progressed;) {
    progressed = false;
    std::vector<Constraint> remaining;
    for (const Constraint& constraint : pending) {
      const std::string a_id = constraint.connector_a().component_id();
      const std::string b_id = constraint.connector_b().component_id();
      const bool a_solved = solved.count(a_id) != 0;
      const bool b_solved = solved.count(b_id) != 0;
      if (a_solved && !b_solved) {
        place_other(constraint, Side::A, a_id, b_id);
        progressed = true;
      } else if (b_solved && !a_solved) {
        place_other(constraint, Side::B, b_id, a_id);
        progressed = true;
      } else if (a_solved && b_solved) {
        const Assembly candidate =
            assembly.with_component_placement(a_id, solved.at(a_id)).with_component_placement(b_id, solved.at(b_id));
        const ConstraintResidual residual = measure_constraint_residual(candidate, constraint.constraint_id());
        if (!residual.within_tolerance) {
          if (std::optional<Assembly> adjusted = try_close_forwarded_constraint(candidate, constraint)) {
            assembly = std::move(*adjusted);
          } else if (strict) {
            raise_residual_failure(assembly, {residual}, "forwarded");
          }
        }
      } else {
        remaining.push_back(constraint);
      }
    }
    pending = std::move(remaining);
  }

  for (const Constraint& constraint : pending) {
    const std::string a_id = constraint.connector_a().component_id();
    const std::string b_id = constraint.connector_b().component_id();
    const Bounds bounds = constraint_scalar_bounds(constraint);
    if (!bounds) {
      if (strict)
        raise_structural_failure(assembly, StructuralFailure::UnresolvableLoop, &constraint);
      continue;
    }
    Side known_side = Side::A;
    if (solved.count(a_id) != 0 && solved.count(b_id) != 0) {
      known_side = Side::A;
    } else if (solved.count(b_id) != 0) {
      known_side = Side::B;
    } else {
      if (strict)
        raise_structural_failure(assembly, StructuralFailure::NoGroundedPath, &constraint);
      continue;
    }
    const std::string& known_id = known_side == Side::A ? a_id : b_id;
    const std::string& unknown_id = known_side == Side::A ? b_id : a_id;
    const Placement known_placement = solved.at(known_id);
    const double best = golden_section_search(
        [&](double scalar) {
          return loop_residual_at_scalar(assembly, constraint, known_side, known_placement, scalar);
        },
        bounds->first, bounds->second);
    solved.insert_or_assign(unknown_id, solve_other_component(assembly, constraint, known_side, known_placement, best));
  }

  std::vector<std::string> unsolved;
  for (const Component& component : assembly.components()) {
    if (solved.count(component.component_id) == 0)
      unsolved.push_back(component.component_id);
  }
  if (strict && !unsolved.empty())
    raise_structural_failure(assembly, StructuralFailure::UnsolvedComponents, nullptr, unsolved);

  Assembly result = assembly;
  for (const auto& [id, placement] : solved)
    result = result.with_component_placement(id, placement);
  result = solve_coupling_constraints(result);
  const ConstraintReport report = inspect_assembly_constraints(result);
  if (strict && std::any_of(report.residuals.begin(), report.residuals.end(),
                            [](const ConstraintResidual& r) { return !r.within_tolerance; })) {
    raise_residual_failure(result, report.residuals, "final");
  }
  result.set_runtime("constraint_report", report.to_dict());
  result.set_runtime(std::string(kAuthoredPlacementsKey), authored);
  if (definition_runtime.is_object()) {
    for (const auto& [key, value] : definition_runtime.as_object())
      result.set_runtime(key, value);
  }
  return std::make_shared<const Assembly>(std::move(result));
}

}  // namespace scad::product
