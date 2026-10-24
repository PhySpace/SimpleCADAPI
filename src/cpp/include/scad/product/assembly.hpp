// Assembly structure: placed components (Parts or sub-assemblies), public connectors,
// constraints and grounding (product/assembly.py).  Values are immutable: every `with_*`
// returns a new Assembly and leaves the original alone.
#pragma once

#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/product/constraint.hpp"
#include "scad/product/part.hpp"
#include "scad/product/placement.hpp"
#include "scad/product/semantic_value.hpp"
#include "scad/product/validation.hpp"

namespace scad::product {

class Assembly;
using AssemblyPtr = std::shared_ptr<const Assembly>;

// What a component instantiates.  Both alternatives are non-null.
using Item = std::variant<PartPtr, AssemblyPtr>;

// "part" / "assembly".
std::string_view item_kind(const Item& item);
// part_id / assembly_id.
const std::string& item_id(const Item& item);

// A public alias for an existing connector on a direct child component.
struct PublicConnectorRef {
  PublicConnectorRef(std::string public_connector_id, std::string component_id, std::string connector_id,
                     const OptionalString& name = {});

  std::string public_connector_id, component_id, connector_id;
  OptionalString name;

  Value to_dict() const;
  bool operator==(const PublicConnectorRef&) const = default;
};

// An assembly-local instance of a Part or sub-assembly.
struct Component {
  Component(std::string component_id, Item item, Placement placement, const OptionalString& name = {});

  std::string component_id;
  Item item;
  Placement placement;
  OptionalString name;

  Value to_dict() const;
};

// The runtime key under which a solved assembly remembers the placements it was authored with.
inline constexpr std::string_view kAuthoredPlacementsKey = "assembly.authored_component_placements";
// ... and the prefix of the keys that carry a durable definition through a solve.
inline constexpr std::string_view kDefinitionRuntimePrefix = "definition.";

class Assembly : public SemanticValue {
 public:
  // ValueError for duplicate component / public connector / constraint ids, a public connector
  // or constraint that names a missing component or connector (KeyError), or a grounded
  // component that is not in the assembly.
  explicit Assembly(std::string assembly_id, OptionalString name = {}, std::vector<Component> components = {},
                    std::vector<PublicConnectorRef> public_connectors = {}, std::vector<Constraint> constraints = {},
                    std::vector<std::string> grounded_component_ids = {});

  const std::string& assembly_id() const noexcept { return id_; }
  const OptionalString& name() const noexcept { return name_; }
  const std::vector<Component>& components() const noexcept { return components_; }
  const std::vector<PublicConnectorRef>& public_connectors() const noexcept { return public_connectors_; }
  const std::vector<Constraint>& constraints() const noexcept { return constraints_; }
  const std::vector<std::string>& grounded_component_ids() const noexcept { return grounded_; }

  std::vector<std::string> component_ids() const;
  // KeyError ("assembly has no component_id 'x'") for an unknown id.
  const Component& get_component(std::string_view component_id) const;
  // ValueError for a duplicate id, or when a sub-assembly would contain this one.
  Assembly with_component(const Component& component) const;
  // KeyError for an unknown id.
  Assembly with_component_placement(std::string_view component_id, const Placement& placement) const;

  std::vector<std::string> public_connector_ids() const;
  const PublicConnectorRef& get_public_connector(std::string_view public_connector_id) const;
  Assembly with_public_connector(const PublicConnectorRef& public_connector) const;

  std::vector<std::string> constraint_ids() const;
  const Constraint& get_constraint(std::string_view constraint_id) const;
  Assembly with_constraint(const Constraint& constraint) const;

  // Grounding an already grounded component returns an equal assembly.
  Assembly with_grounded_component(std::string_view component_id) const;
  Assembly without_grounded_component(std::string_view component_id) const;

  Value to_dict() const;

  // This assembly with one component's placement replaced, `component_path` steps down
  // through nested assemblies (the sub-assemblies on the way are rebuilt).
  Assembly with_component_path_placement(const std::vector<std::string>& component_path,
                                         const Placement& placement) const;

 private:
  // The same assembly with other parts; metadata is inherited, the runtime is as given.
  Assembly derive(std::vector<Component> components, std::vector<PublicConnectorRef> public_connectors,
                  std::vector<Constraint> constraints, std::vector<std::string> grounded, Value runtime) const;
  Value authored_runtime() const;

  std::string id_;
  OptionalString name_;
  std::vector<Component> components_;
  std::vector<PublicConnectorRef> public_connectors_;
  std::vector<Constraint> constraints_;
  std::vector<std::string> grounded_;
};

}  // namespace scad::product
