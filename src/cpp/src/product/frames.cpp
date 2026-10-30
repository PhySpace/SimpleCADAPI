// Connector frames, drive coordinates and residuals.
#include <algorithm>
#include <cmath>
#include <set>

#include "scad/core/error.hpp"
#include "scad/product/resolve.hpp"
#include "solver_detail.hpp"

namespace scad::product {

namespace detail {

double radians(double degrees_) {
  return degrees_ * (kPi / 180.0);
}
double degrees(double radians_) {
  return radians_ * (180.0 / kPi);
}

Placement connector_local_frame(const Assembly& assembly, const ConnectorRef& ref) {
  return resolve_item_connector_placement(assembly.get_component(ref.component_id()).item, ref.connector_id());
}

Placement connector_world_frame(const Assembly& assembly, const ConnectorRef& ref) {
  return assembly.get_component(ref.component_id()).placement.compose(connector_local_frame(assembly, ref));
}

double constraint_current_scalar(const Assembly& assembly, const Constraint& constraint) {
  const Placement relative = relative_placement(connector_world_frame(assembly, constraint.connector_a()),
                                                connector_world_frame(assembly, constraint.connector_b()));
  if (constraint.constraint_kind() == "prismatic")
    return relative.origin().z;
  return degrees(std::atan2(relative.x_axis().y, relative.x_axis().x));
}

Bounds constraint_scalar_bounds(const Constraint& constraint) {
  if (const auto& limit = constraint.angle_limit(); constraint.constraint_kind() == "revolute" && limit) {
    return std::pair{limit->lower_value(), limit->upper_value()};
  }
  if (const auto& limit = constraint.distance_limit(); constraint.constraint_kind() == "prismatic" && limit) {
    return std::pair{limit->lower_value(), limit->upper_value()};
  }
  return std::nullopt;
}

double project_scalar(double scalar, const Bounds& bounds) {
  if (!bounds)
    return scalar;
  return std::max(bounds->first, std::min(bounds->second, scalar));
}

Placement motion_from_scalar(const Constraint& constraint, double scalar) {
  if (constraint.constraint_kind() == "fixed")
    return identity_placement();
  if (constraint.constraint_kind() == "revolute")
    return rotate_z_placement(scalar);
  return translate_z_placement(scalar);
}

Placement constraint_motion_from_current(const Assembly& assembly, const Constraint& constraint) {
  if (constraint.constraint_kind() == "fixed")
    return identity_placement();
  if (constraint.constraint_kind() == "revolute") {
    const auto& drive_angle = constraint.drive_angle_degrees();
    return rotate_z_placement(drive_angle ? *drive_angle : constraint_current_scalar(assembly, constraint));
  }
  const auto& drive_distance = constraint.drive_distance();
  return translate_z_placement(drive_distance ? *drive_distance : constraint_current_scalar(assembly, constraint));
}

double angular_error_degrees(const Placement& relative) {
  const double trace = relative.x_axis().x + relative.y_axis().y + relative.z_axis().z;
  const double cos_angle = std::max(-1.0, std::min(1.0, (trace - 1.0) / 2.0));
  return std::abs(degrees(std::acos(cos_angle)));
}

Placement solve_other_component(const Assembly& assembly, const Constraint& constraint, Side known_side,
                                const Placement& known_placement, std::optional<double> scalar_override) {
  Placement motion = identity_placement();
  if (constraint.constraint_kind() != "fixed") {
    double scalar = 0.0;
    if (scalar_override) {
      scalar = *scalar_override;
    } else {
      const OptionalDouble& drive =
          constraint.constraint_kind() == "revolute" ? constraint.drive_angle_degrees() : constraint.drive_distance();
      scalar = drive ? *drive : constraint_current_scalar(assembly, constraint);
    }
    motion = motion_from_scalar(constraint, scalar);
    if (known_side == Side::B)
      motion = inverse_placement(motion);
  }
  const ConnectorRef& known_ref = known_side == Side::A ? constraint.connector_a() : constraint.connector_b();
  const ConnectorRef& unknown_ref = known_side == Side::A ? constraint.connector_b() : constraint.connector_a();
  const Placement known_frame = known_placement.compose(connector_local_frame(assembly, known_ref));
  const Placement target_unknown_frame = known_frame.compose(motion);
  return target_unknown_frame.compose(inverse_placement(connector_local_frame(assembly, unknown_ref)));
}

}  // namespace detail

ConstraintResidual measure_constraint_residual(const Assembly& assembly, std::string_view constraint_id) {
  const Constraint& constraint = assembly.get_constraint(constraint_id);
  if (constraint.is_coupling())
    return detail::measure_coupling_residual(assembly, constraint);
  const Placement frame_a = detail::connector_world_frame(assembly, constraint.connector_a());
  const Placement frame_b = detail::connector_world_frame(assembly, constraint.connector_b());
  const Placement motion =
      detail::motion_from_scalar(constraint, detail::constraint_current_scalar(assembly, constraint));
  const Placement relative = relative_placement(frame_a.compose(motion), frame_b);
  const double translation_error = relative.origin().norm();
  const double angular_error = detail::angular_error_degrees(relative);
  return {constraint.constraint_id(), translation_error, angular_error,
          translation_error <= kPlacementTolerance && angular_error <= kAngleToleranceDegrees};
}

ConstraintReport inspect_assembly_constraints(const Assembly& assembly) {
  ConstraintReport report;
  for (const Constraint& constraint : assembly.constraints()) {
    report.residuals.push_back(measure_constraint_residual(assembly, constraint.constraint_id()));
  }
  const std::vector<std::string> all_ids = assembly.component_ids();
  if (assembly.constraints().empty()) {
    report.solved_component_ids = all_ids;
  } else {
    std::set<std::string> reachable(assembly.grounded_component_ids().begin(), assembly.grounded_component_ids().end());
    for (bool progressed = true; progressed;) {
      progressed = false;
      for (const Constraint& constraint : assembly.constraints()) {
        if (constraint.is_coupling())
          continue;
        const std::string& a = constraint.connector_a().component_id();
        const std::string& b = constraint.connector_b().component_id();
        if (reachable.count(a) != 0 && reachable.count(b) == 0) {
          reachable.insert(b);
          progressed = true;
        }
        if (reachable.count(b) != 0 && reachable.count(a) == 0) {
          reachable.insert(a);
          progressed = true;
        }
      }
    }
    for (const std::string& id : all_ids) {
      (reachable.count(id) != 0 ? report.solved_component_ids : report.unsolved_component_ids).push_back(id);
    }
  }
  report.grounded_component_ids = assembly.grounded_component_ids();
  report.solved = report.unsolved_component_ids.empty() &&
                  std::all_of(report.residuals.begin(), report.residuals.end(),
                              [](const ConstraintResidual& r) { return r.within_tolerance; });
  return report;
}

}  // namespace scad::product
