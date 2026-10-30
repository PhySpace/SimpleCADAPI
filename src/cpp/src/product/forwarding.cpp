// Closing a residual through a nested assembly's public connector.
//
// A public connector on a nested assembly (a bearing's inner_axis, say) resolves through that
// assembly's own component placement.  When an outside constraint pins such a forwarded frame
// while a sibling constraint already holds the other public frame, the nested instance cannot
// move rigidly: the nested source component itself has to move.
#include <algorithm>

#include "scad/product/resolve.hpp"
#include "solver_detail.hpp"

namespace scad::product::detail {

namespace {

struct ForwardedTarget {
  std::vector<std::string> component_path;
  Placement parent_world;
  Placement connector_tail;
};

const PublicConnectorRef* public_connector_or_null(const Assembly& assembly, const std::string& connector_id) {
  try {
    return &assembly.get_public_connector(connector_id);
  } catch (const reactive::KeyError&) {
    return nullptr;
  }
}

std::optional<ForwardedTarget> descend(const Assembly& owner, const PublicConnectorRef& pub,
                                       const Placement& owner_world, const std::vector<std::string>& component_path) {
  const Component& source = owner.get_component(pub.component_id);
  std::vector<std::string> source_path = component_path;
  source_path.push_back(pub.component_id);
  if (const auto* nested_assembly = std::get_if<AssemblyPtr>(&source.item)) {
    if (const PublicConnectorRef* nested_public = public_connector_or_null(**nested_assembly, pub.connector_id)) {
      return descend(**nested_assembly, *nested_public, owner_world.compose(source.placement), source_path);
    }
  }
  return ForwardedTarget{source_path, owner_world, resolve_item_connector_placement(source.item, pub.connector_id)};
}

std::optional<ForwardedTarget> forwarded_target(const Assembly& assembly, const ConnectorRef& ref) {
  const Component& component = assembly.get_component(ref.component_id());
  const auto* nested = std::get_if<AssemblyPtr>(&component.item);
  if (nested == nullptr)
    return std::nullopt;
  const PublicConnectorRef* pub = public_connector_or_null(**nested, ref.connector_id());
  if (pub == nullptr)
    return std::nullopt;
  return descend(**nested, *pub, component.placement, {component.component_id});
}

// The assemblies a component path passes through, outermost child first; empty when the path
// does not run through assemblies all the way.
std::vector<AssemblyPtr> assemblies_along(const Assembly& assembly, const std::vector<std::string>& path) {
  const auto* first = std::get_if<AssemblyPtr>(&assembly.get_component(path.front()).item);
  if (first == nullptr)
    return {};
  std::vector<AssemblyPtr> owners{*first};
  for (std::size_t i = 1; i + 1 < path.size(); ++i) {
    const auto* next = std::get_if<AssemblyPtr>(&owners.back()->get_component(path[i]).item);
    if (next == nullptr)
      return {};
    owners.push_back(*next);
  }
  return owners;
}

bool preserves_satisfied_constraints(const Assembly& before, const Assembly& after) {
  for (const Constraint& constraint : before.constraints()) {
    if (measure_constraint_residual(before, constraint.constraint_id()).within_tolerance &&
        !measure_constraint_residual(after, constraint.constraint_id()).within_tolerance) {
      return false;
    }
  }
  return true;
}

}  // namespace

std::optional<Assembly> try_close_forwarded_constraint(const Assembly& assembly, const Constraint& constraint) {
  const Placement motion = constraint_motion_from_current(assembly, constraint);
  for (const Side moving_side : {Side::A, Side::B}) {
    const ConnectorRef& moving_ref = moving_side == Side::A ? constraint.connector_a() : constraint.connector_b();
    const auto target = forwarded_target(assembly, moving_ref);
    if (!target)
      continue;
    const std::vector<AssemblyPtr> owners = assemblies_along(assembly, target->component_path);
    if (owners.empty())
      continue;
    const auto& grounded = owners.back()->grounded_component_ids();
    if (std::find(grounded.begin(), grounded.end(), target->component_path.back()) != grounded.end())
      continue;

    const Placement target_frame =
        moving_side == Side::B
            ? connector_world_frame(assembly, constraint.connector_a()).compose(motion)
            : connector_world_frame(assembly, constraint.connector_b()).compose(inverse_placement(motion));
    const Placement placement = inverse_placement(target->parent_world)
                                    .compose(target_frame)
                                    .compose(inverse_placement(target->connector_tail));
    Assembly candidate = assembly.with_component_path_placement(target->component_path, placement);
    if (!measure_constraint_residual(candidate, constraint.constraint_id()).within_tolerance)
      continue;
    if (!preserves_satisfied_constraints(assembly, candidate))
      continue;
    const std::vector<AssemblyPtr> updated = assemblies_along(candidate, target->component_path);
    if (!std::all_of(updated.begin(), updated.end(),
                     [](const AssemblyPtr& owner) { return inspect_assembly_constraints(*owner).solved; })) {
      continue;
    }
    return candidate;
  }
  return std::nullopt;
}

}  // namespace scad::product::detail
