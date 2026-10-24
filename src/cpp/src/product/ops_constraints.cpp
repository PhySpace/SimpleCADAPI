// Grounding, constraints, solving and inspecting.
#include "scad/core/error.hpp"
#include "scad/product/guard.hpp"
#include "scad/product/operators.hpp"
#include "scad/product/solver.hpp"
#include "record.hpp"

namespace scad::product {

using namespace detail;

namespace {

OptionalDouble to_double(const OptionalScalar& value) {
  if (!value) return std::nullopt;
  return scalar_float(*value);
}

double to_double(const Scalar& value) { return scalar_float(value); }

AssemblyPtr ground_operation(const Assembly& assembly, const std::string& component_id, bool ground) {
  const char* const name = ground ? "ground_component_rassembly" : "unground_component_rassembly";
  return guard_operation(name, [&] {
    auto result = std::make_shared<const Assembly>(ground ? assembly.with_grounded_component(component_id)
                                                          : assembly.without_grounded_component(component_id));
    record_value([&] {
      Value params = Value::object();
      params.set("assembly_id", assembly.assembly_id());
      params.set("component_id", component_id);
      OpRecord record = op_record(ground ? "make_ground_component_rassembly" : "make_unground_component_rassembly",
                                  std::move(params));
      Value metadata = Value::object();
      metadata.set(ground ? "grounded_component_id" : "ungrounded_component_id", component_id);
      record.semantic_delta = semantic_modified("Assembly", assembly.assembly_id(), std::move(metadata));
      return record;
    }, result, assembly);
    return result;
  });
}

// _add_constraint_rassembly.  The Constraint is built by the caller, outside any guard, as in
// Python: its validation errors are the plain ValueError / TypeError.
AssemblyPtr add_constraint(const Assembly& assembly, const Constraint& constraint, std::string_view recorded_op,
                           std::string_view public_name) {
  return guard_operation(public_name, [&] {
    auto result = std::make_shared<const Assembly>(assembly.with_constraint(constraint));
    record_value([&] {
      OpRecord record = op_record(std::string(recorded_op), constraint.to_dict());
      Value metadata = Value::object();
      metadata.set("constraint", constraint.to_dict());
      record.semantic_delta = semantic_modified("Assembly", assembly.assembly_id(), std::move(metadata));
      return record;
    }, result, assembly, constraint.connector_a(), constraint.connector_b(), constraint.angle_limit(),
       constraint.distance_limit());
    return result;
  });
}

// A coupling whose phase offset is left out takes the one the current placements realise.
Constraint coupling_constraint(const Assembly& assembly, const std::string& id, const char* kind,
                               const ConnectorRef& a, const ConnectorRef& b, ConstraintSettings settings) {
  const bool derive_phase = !settings.phase_offset;
  Constraint constraint(id, kind, a, b, settings);
  if (!derive_phase) return constraint;
  settings.phase_offset = coupling_phase_offset(assembly, constraint);
  return Constraint(id, kind, a, b, std::move(settings));
}

}  // namespace

AssemblyPtr ground_component_rassembly(const Assembly& assembly, const std::string& component_id) {
  return ground_operation(assembly, component_id, true);
}

AssemblyPtr unground_component_rassembly(const Assembly& assembly, const std::string& component_id) {
  return ground_operation(assembly, component_id, false);
}

AssemblyPtr add_fixed_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                           const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                           const OptionalString& name) {
  const Constraint constraint(constraint_id, "fixed", connector_a, connector_b, {.name = name});
  return add_constraint(assembly, constraint, "make_fixed_constraint_rassembly", "add_fixed_constraint_rassembly");
}

AssemblyPtr add_revolute_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                              const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                              const OptionalScalar& drive_angle_degrees, const OptionalLimit& angle_limit,
                                              const OptionalString& name) {
  const Constraint constraint(
      constraint_id, "revolute", connector_a, connector_b,
      {.drive_angle_degrees = to_double(drive_angle_degrees), .angle_limit = angle_limit, .name = name});
  return add_constraint(assembly, constraint, "make_revolute_constraint_rassembly", "add_revolute_constraint_rassembly");
}

AssemblyPtr add_prismatic_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                               const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                               const OptionalScalar& drive_distance, const OptionalLimit& distance_limit,
                                               const OptionalString& name) {
  const Constraint constraint(
      constraint_id, "prismatic", connector_a, connector_b,
      {.drive_distance = to_double(drive_distance), .distance_limit = distance_limit, .name = name});
  return add_constraint(assembly, constraint, "make_prismatic_constraint_rassembly", "add_prismatic_constraint_rassembly");
}

AssemblyPtr add_gear_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                          const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                          const Scalar& pitch_radius_a, const Scalar& pitch_radius_b,
                                          const OptionalScalar& phase_offset, const OptionalString& name) {
  const Constraint constraint = coupling_constraint(
      assembly, constraint_id, "gear", connector_a, connector_b,
      {.pitch_radius_a = to_double(pitch_radius_a),
       .pitch_radius_b = to_double(pitch_radius_b),
       .phase_offset = to_double(phase_offset),
       .name = name});
  return add_constraint(assembly, constraint, "make_gear_constraint_rassembly", "add_gear_constraint_rassembly");
}

AssemblyPtr add_belt_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                          const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                          const Scalar& pulley_radius_a, const Scalar& pulley_radius_b,
                                          const OptionalScalar& phase_offset, const OptionalString& name) {
  const Constraint constraint = coupling_constraint(
      assembly, constraint_id, "belt", connector_a, connector_b,
      {.pulley_radius_a = to_double(pulley_radius_a),
       .pulley_radius_b = to_double(pulley_radius_b),
       .phase_offset = to_double(phase_offset),
       .name = name});
  return add_constraint(assembly, constraint, "make_belt_constraint_rassembly", "add_belt_constraint_rassembly");
}

AssemblyPtr add_rack_pinion_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                                 const ConnectorRef& rack_connector, const ConnectorRef& pinion_connector,
                                                 const Scalar& pitch_radius, const OptionalScalar& phase_offset,
                                                 const OptionalString& name) {
  const Constraint constraint = coupling_constraint(
      assembly, constraint_id, "rack_pinion", rack_connector, pinion_connector,
      {.pitch_radius = to_double(pitch_radius),
       .phase_offset = to_double(phase_offset),
       .name = name});
  return add_constraint(assembly, constraint, "make_rack_pinion_constraint_rassembly",
                        "add_rack_pinion_constraint_rassembly");
}

AssemblyPtr solve_assembly_constraints_rassembly(const AssemblyPtr& assembly, bool strict) {
  return guard_operation("solve_assembly_constraints_rassembly", [&] {
    AssemblyPtr result = solve_assembly_constraints(assembly, strict);
    record_value([&] {
      Value placements = Value::object();
      for (const Component& component : result->components()) placements.set(component.component_id, component.placement.to_dict());
      Value params = Value::object();
      params.set("assembly_id", assembly->assembly_id());
      params.set("strict", strict);
      params.set("component_placements", std::move(placements));
      OpRecord record = op_record("make_solve_assembly_constraints_rassembly", std::move(params));
      Value metadata = Value::object();
      metadata.set("constraints_solved", true);
      record.semantic_delta = semantic_modified("Assembly", assembly->assembly_id(), std::move(metadata));
      return record;
    }, result, assembly);
    return result;
  });
}

ConstraintResidual measure_constraint_residual_rconstraintresidual(const Assembly& assembly,
                                                                   const std::string& constraint_id) {
  return measure_constraint_residual(assembly, constraint_id);
}

ConstraintReport inspect_assembly_constraints_rconstraintreport(const Assembly& assembly) {
  return inspect_assembly_constraints(assembly);
}

}  // namespace scad::product
