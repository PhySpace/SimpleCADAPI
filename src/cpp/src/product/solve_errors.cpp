// The solver's strict-mode failures: errors that carry the measurements, the inventory and the
// parameterised repair the solver already had in hand (the error-guidance contract), under the
// operation name "solve_assembly_constraints".
#include <algorithm>
#include <cstdio>

#include "scad/core/error.hpp"
#include "solver_detail.hpp"

namespace scad::product::detail {

namespace {

constexpr std::size_t kInventoryCap = 16;
constexpr const char* kOperation = "solve_assembly_constraints";

std::string constraint_description(const Constraint& constraint) {
  return constraint.constraint_kind() + " " + constraint.connector_a().component_id() + "↔" +
         constraint.connector_b().component_id();
}

std::string join(const std::vector<std::string>& items, std::string_view separator) {
  std::string out;
  for (const std::string& item : items)
    out += (out.empty() ? "" : std::string(separator)) + item;
  return out;
}

// Python's repr(list_of_str).
std::string list_repr(const std::vector<std::string>& items) {
  std::string out = "[";
  for (std::size_t i = 0; i < items.size(); ++i)
    out += (i == 0 ? "" : ", ") + python_repr(items[i]);
  return out + "]";
}

}  // namespace

std::string format_g3(double value) {
  char buffer[64];
  std::snprintf(buffer, sizeof buffer, "%.3g", value);
  return buffer;
}

void raise_residual_failure(const Assembly& assembly, const std::vector<ConstraintResidual>& residuals,
                            std::string_view stage) {
  std::vector<ErrorMeasurement> measurements = {{"placement tolerance", kPlacementTolerance, "mm"},
                                                {"angular tolerance", kAngleToleranceDegrees, "deg"}};
  std::vector<std::string> failed_ids;
  for (const ConstraintResidual& residual : residuals) {
    if (residual.within_tolerance)
      continue;
    failed_ids.push_back(residual.constraint_id);
    measurements.push_back({residual.constraint_id + " translation error", residual.translation_error, "mm"});
    measurements.push_back({residual.constraint_id + " angular error", residual.angular_error_degrees, "deg"});
  }

  std::vector<InventoryEntry> inventory;
  for (std::size_t i = 0; i < residuals.size() && i < kInventoryCap; ++i) {
    const ConstraintResidual& residual = residuals[i];
    const Constraint& constraint = assembly.get_constraint(residual.constraint_id);
    inventory.push_back({residual.constraint_id, residual.within_tolerance ? "ok" : "exceeded",
                         constraint_description(constraint) + ": Δt=" + format_g3(residual.translation_error) +
                             " mm, Δθ=" + format_g3(residual.angular_error_degrees) + " deg"});
  }

  const ConstraintResidual* worst = nullptr;
  double worst_score = 0.0;
  for (const ConstraintResidual& residual : residuals) {
    if (residual.within_tolerance)
      continue;
    const double score = std::max(residual.translation_error / std::max(kPlacementTolerance, 1e-30),
                                  residual.angular_error_degrees / std::max(kAngleToleranceDegrees, 1e-30));
    if (worst == nullptr || score > worst_score) {
      worst = &residual;
      worst_score = score;
    }
  }
  std::vector<std::string> repair;
  if (worst != nullptr) {
    repair.push_back("The worst-residual constraint is " + worst->constraint_id + " (dt=" +
                     format_g3(worst->translation_error) + " mm, dtheta=" + format_g3(worst->angular_error_degrees) +
                     " deg): check the local frame definitions (datum and interface orientation) of the connectors on "
                     "both ends of that constraint first — not the component placements");
  }
  repair.push_back(
      "Closed-loop constraints that each fit but do not fit together are overconstrained: break the loop (delete one "
      "redundant constraint), or let a nested subassembly solve internally and have the parent consume only its "
      "public interface");
  repair.push_back(
      "Rerun inspect_assembly_constraints_rassembly(assembly) to review all residuals before touching the constraint "
      "set");

  const ErrorSpec spec(
      kOperation,
      std::to_string(failed_ids.size()) + " of " + std::to_string(residuals.size()) +
          " constraint(s) exceed tolerance at the " + std::string(stage) + " pass: " + join(failed_ids, ", "),
      {"A connector's local frame (datum or axis orientation) does not match the intended mating geometry.",
       "A closed kinematic loop is overconstrained: each constraint alone fits, the combination cannot.",
       "A nested subassembly still owns internal degrees of freedom that the parent cannot close."},
      {"Fix the connector frame definitions named in the repair lines, not the placements.",
       "For closed loops, remove one redundant constraint or solve the loop internally in a subassembly."});
  raise_harness_error(
      spec, "assembly_id=" + assembly.assembly_id() + ", grounded=" + list_repr(assembly.grounded_component_ids()),
      std::move(measurements), std::move(repair), std::move(inventory));
}

void raise_structural_failure(const Assembly& assembly, StructuralFailure kind, const Constraint* constraint,
                              const std::vector<std::string>& unsolved_ids) {
  const std::vector<ErrorMeasurement> measurements = {
      {"component count", static_cast<double>(assembly.components().size()), ""},
      {"constraint count", static_cast<double>(assembly.constraints().size()), ""},
      {"grounded components", static_cast<double>(assembly.grounded_component_ids().size()), ""}};

  std::vector<InventoryEntry> inventory;
  const auto& grounded = assembly.grounded_component_ids();
  for (std::size_t i = 0; i < assembly.components().size() && i < kInventoryCap; ++i) {
    const std::string& id = assembly.components()[i].component_id;
    const char* status = "reachable";
    if (std::find(grounded.begin(), grounded.end(), id) != grounded.end()) {
      status = "grounded";
    } else if (std::find(unsolved_ids.begin(), unsolved_ids.end(), id) != unsolved_ids.end()) {
      status = "unsolved";
    }
    const auto references =
        std::count_if(assembly.constraints().begin(), assembly.constraints().end(), [&id](const Constraint& existing) {
          return existing.connector_a().component_id() == id || existing.connector_b().component_id() == id;
        });
    inventory.push_back({id, status, std::to_string(references) + " connecting constraint(s)"});
  }

  const char* kind_name =
      kind == StructuralFailure::UnresolvableLoop
          ? "unresolvable_loop"
          : (kind == StructuralFailure::NoGroundedPath ? "no_grounded_path" : "unsolved_components");
  std::string what;
  std::vector<std::string> repair;
  if (constraint != nullptr && kind == StructuralFailure::UnresolvableLoop) {
    what = "constraint '" + constraint->constraint_id() + "' (" + constraint_description(*constraint) +
           ") forms a closed loop with no feasible scalar inside its limits";
    repair = {
        "Add or widen a ScalarLimit on that constraint (angle_limit / distance_limit), or delete one constraint "
        "on the loop to break it open",
        "Let a nested subassembly solve the loop internally and have the parent consume its public interface"};
  } else if (constraint != nullptr && kind == StructuralFailure::NoGroundedPath) {
    what = "constraint '" + constraint->constraint_id() + "' (" + constraint_description(*constraint) +
           ") connects two components that are both unreachable from any grounded component";
    repair = {
        "Ground one end of the chain with ground_component_rassembly, or add a connecting constraint so the "
        "component is reachable from a grounded one"};
  } else {
    what =
        "components unreachable from any grounded component through the constraint graph: " + join(unsolved_ids, ", ");
    repair = {
        "Add a ground or a connecting constraint for the [unsolved] components so they are reachable from a "
        "grounded one"};
  }

  const ErrorSpec spec(
      kOperation, what,
      {"No grounding path reaches a constrained component.", "The constraint graph splits into disconnected islands.",
       "A closed loop cannot be satisfied within its scalar limits."},
      {repair.front(),
       "Inspect the component inventory: [grounded]/[reachable]/[unsolved] is the connectivity verdict."});
  raise_harness_error(spec, "assembly_id=" + assembly.assembly_id() + ", kind=" + kind_name, measurements, repair,
                      std::move(inventory));
}

}  // namespace scad::product::detail
