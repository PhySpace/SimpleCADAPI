#include "scad/product/assembly.hpp"

#include <algorithm>
#include <map>
#include <set>

#include "scad/core/error.hpp"
#include "scad/product/resolve.hpp"

namespace scad::product {

std::string_view item_kind(const Item& item) {
  return std::holds_alternative<AssemblyPtr>(item) ? "assembly" : "part";
}

const std::string& item_id(const Item& item) {
  if (const auto* assembly = std::get_if<AssemblyPtr>(&item))
    return (*assembly)->assembly_id();
  return std::get<PartPtr>(item)->part_id();
}

// ---------------------------------------------------------------------------
// PublicConnectorRef, Component
// ---------------------------------------------------------------------------

PublicConnectorRef::PublicConnectorRef(std::string public_id, std::string source_component,
                                       std::string source_connector, const OptionalString& label)
    : public_connector_id(validate_identifier(public_id, "public_connector_id")),
      component_id(validate_identifier(source_component, "component_id")),
      connector_id(validate_identifier(source_connector, "connector_id")),
      name(clean_name(label)) {}

Value PublicConnectorRef::to_dict() const {
  Value out = Value::object();
  out.set("public_connector_id", public_connector_id);
  out.set("component_id", component_id);
  out.set("connector_id", connector_id);
  out.set("name", name ? Value(*name) : Value());
  return out;
}

Component::Component(std::string id, Item instantiated, Placement frame, const OptionalString& label)
    : component_id(validate_identifier(id, "component_id")),
      item(std::move(instantiated)),
      placement(std::move(frame)),
      name(clean_name(label)) {}

Value Component::to_dict() const {
  Value out = Value::object();
  out.set("component_id", component_id);
  out.set("name", name ? Value(*name) : Value());
  out.set("item_kind", std::string(item_kind(item)));
  out.set("item_id", item_id(item));
  out.set("placement", placement.to_dict());
  return out;
}

// ---------------------------------------------------------------------------
// Assembly
// ---------------------------------------------------------------------------

namespace {

template <class Rows, class Key>
std::string duplicates_of(const Rows& rows, Key key) {
  std::map<std::string, int> counts;
  for (const auto& row : rows)
    ++counts[key(row)];
  std::string out;
  for (const auto& [id, count] : counts) {
    if (count > 1)
      out += (out.empty() ? "" : ", ") + id;
  }
  return out;
}

void assert_no_assembly_cycle(const Assembly& parent, const Assembly& child) {
  if (child.assembly_id() == parent.assembly_id()) {
    throw ValueError("assembly cycle detected for '" + parent.assembly_id() + "'");
  }
  for (const Component& component : child.components()) {
    if (const auto* nested = std::get_if<AssemblyPtr>(&component.item))
      assert_no_assembly_cycle(parent, **nested);
  }
}

}  // namespace

Assembly::Assembly(std::string assembly_id, OptionalString name, std::vector<Component> components,
                   std::vector<PublicConnectorRef> public_connectors, std::vector<Constraint> constraints,
                   std::vector<std::string> grounded_component_ids)
    : id_(validate_identifier(assembly_id, "assembly_id")),
      name_(clean_name(name)),
      components_(std::move(components)),
      public_connectors_(std::move(public_connectors)),
      constraints_(std::move(constraints)) {
  if (const std::string duplicate = duplicates_of(components_, [](const Component& c) { return c.component_id; });
      !duplicate.empty()) {
    throw ValueError("duplicate component_id in assembly: " + duplicate);
  }
  if (const std::string duplicate =
          duplicates_of(public_connectors_, [](const PublicConnectorRef& p) { return p.public_connector_id; });
      !duplicate.empty()) {
    throw ValueError("duplicate public_connector_id in assembly: " + duplicate);
  }
  for (const PublicConnectorRef& pub : public_connectors_) {
    resolve_item_connector(get_component(pub.component_id).item, pub.connector_id);
  }
  if (const std::string duplicate = duplicates_of(constraints_, [](const Constraint& c) { return c.constraint_id(); });
      !duplicate.empty()) {
    throw ValueError("duplicate constraint_id: " + duplicate);
  }
  for (const Constraint& constraint : constraints_) {
    resolve_connector(*this, constraint.connector_a());
    resolve_connector(*this, constraint.connector_b());
  }

  std::vector<std::string> grounded;
  for (const std::string& raw : grounded_component_ids) {
    const std::string id = validate_identifier(raw, "component_id");
    if (std::find(grounded.begin(), grounded.end(), id) == grounded.end())
      grounded.push_back(id);
  }
  const std::vector<std::string> known = component_ids();
  std::set<std::string> unknown;
  for (const std::string& id : grounded) {
    if (std::find(known.begin(), known.end(), id) == known.end())
      unknown.insert(id);
  }
  if (!unknown.empty()) {
    std::string joined;
    for (const std::string& id : unknown)
      joined += (joined.empty() ? "" : ", ") + id;
    throw ValueError("grounded component_id not found in assembly: " + joined);
  }
  grounded_ = std::move(grounded);
}

std::vector<std::string> Assembly::component_ids() const {
  std::vector<std::string> ids;
  ids.reserve(components_.size());
  for (const Component& component : components_)
    ids.push_back(component.component_id);
  return ids;
}

const Component& Assembly::get_component(std::string_view component_id) const {
  const std::string target = validate_identifier(component_id, "component_id");
  for (const Component& component : components_) {
    if (component.component_id == target)
      return component;
  }
  throw LookupError("assembly has no component_id '" + target + "'");
}

Value Assembly::authored_runtime() const {
  Value out = Value::object();
  const Value authored = get_runtime(kAuthoredPlacementsKey);
  if (!authored.is_null())
    out.set(std::string(kAuthoredPlacementsKey), authored);
  return out;
}

Assembly Assembly::derive(std::vector<Component> components, std::vector<PublicConnectorRef> public_connectors,
                          std::vector<Constraint> constraints, std::vector<std::string> grounded, Value runtime) const {
  Assembly result(id_, name_, std::move(components), std::move(public_connectors), std::move(constraints),
                  std::move(grounded));
  result.inherit_metadata(*this);
  result.replace_runtime(std::move(runtime));
  return result;
}

Assembly Assembly::with_component(const Component& component) const {
  const std::vector<std::string> ids = component_ids();
  if (std::find(ids.begin(), ids.end(), component.component_id) != ids.end()) {
    throw ValueError("duplicate component_id in assembly: " + component.component_id);
  }
  if (const auto* nested = std::get_if<AssemblyPtr>(&component.item))
    assert_no_assembly_cycle(*this, **nested);
  std::vector<Component> components = components_;
  components.push_back(component);
  return derive(std::move(components), public_connectors_, constraints_, grounded_, Value::object());
}

Assembly Assembly::with_component_placement(std::string_view component_id, const Placement& placement) const {
  const std::string target = validate_identifier(component_id, "component_id");
  std::vector<Component> components;
  components.reserve(components_.size());
  bool found = false;
  for (const Component& component : components_) {
    if (component.component_id == target) {
      found = true;
      components.emplace_back(component.component_id, component.item, placement, component.name);
    } else {
      components.push_back(component);
    }
  }
  if (!found)
    throw LookupError("assembly has no component_id '" + target + "'");
  return derive(std::move(components), public_connectors_, constraints_, grounded_, Value::object());
}

std::vector<std::string> Assembly::public_connector_ids() const {
  std::vector<std::string> ids;
  for (const PublicConnectorRef& pub : public_connectors_)
    ids.push_back(pub.public_connector_id);
  return ids;
}

const PublicConnectorRef& Assembly::get_public_connector(std::string_view public_connector_id) const {
  const std::string target = validate_identifier(public_connector_id, "public_connector_id");
  for (const PublicConnectorRef& pub : public_connectors_) {
    if (pub.public_connector_id == target)
      return pub;
  }
  throw LookupError("assembly has no public_connector_id '" + target + "'");
}

Assembly Assembly::with_public_connector(const PublicConnectorRef& public_connector) const {
  const std::vector<std::string> ids = public_connector_ids();
  if (std::find(ids.begin(), ids.end(), public_connector.public_connector_id) != ids.end()) {
    throw ValueError("duplicate public_connector_id in assembly: " + public_connector.public_connector_id);
  }
  resolve_item_connector(get_component(public_connector.component_id).item, public_connector.connector_id);
  std::vector<PublicConnectorRef> publics = public_connectors_;
  publics.push_back(public_connector);
  return derive(components_, std::move(publics), constraints_, grounded_, authored_runtime());
}

std::vector<std::string> Assembly::constraint_ids() const {
  std::vector<std::string> ids;
  for (const Constraint& constraint : constraints_)
    ids.push_back(constraint.constraint_id());
  return ids;
}

const Constraint& Assembly::get_constraint(std::string_view constraint_id) const {
  const std::string target = validate_identifier(constraint_id, "constraint_id");
  for (const Constraint& constraint : constraints_) {
    if (constraint.constraint_id() == target)
      return constraint;
  }
  throw LookupError("assembly has no constraint_id '" + target + "'");
}

Assembly Assembly::with_constraint(const Constraint& constraint) const {
  const std::vector<std::string> ids = constraint_ids();
  if (std::find(ids.begin(), ids.end(), constraint.constraint_id()) != ids.end()) {
    throw ValueError("duplicate constraint_id in assembly: " + constraint.constraint_id());
  }
  resolve_connector(*this, constraint.connector_a());
  resolve_connector(*this, constraint.connector_b());
  std::vector<Constraint> constraints = constraints_;
  constraints.push_back(constraint);
  return derive(components_, public_connectors_, std::move(constraints), grounded_, authored_runtime());
}

Assembly Assembly::with_grounded_component(std::string_view component_id) const {
  const std::string target = validate_identifier(component_id, "component_id");
  get_component(target);
  if (std::find(grounded_.begin(), grounded_.end(), target) != grounded_.end())
    return *this;
  std::vector<std::string> grounded = grounded_;
  grounded.push_back(target);
  return derive(components_, public_connectors_, constraints_, std::move(grounded), authored_runtime());
}

Assembly Assembly::without_grounded_component(std::string_view component_id) const {
  const std::string target = validate_identifier(component_id, "component_id");
  get_component(target);
  std::vector<std::string> grounded;
  for (const std::string& existing : grounded_) {
    if (existing != target)
      grounded.push_back(existing);
  }
  return derive(components_, public_connectors_, constraints_, std::move(grounded), authored_runtime());
}

Value Assembly::to_dict() const {
  Value out = Value::object();
  out.set("assembly_id", id_);
  out.set("name", name_ ? Value(*name_) : Value());
  Value components = Value::array();
  for (const Component& component : components_)
    components.push_back(component.to_dict());
  out.set("components", std::move(components));
  Value publics = Value::array();
  for (const PublicConnectorRef& pub : public_connectors_)
    publics.push_back(pub.to_dict());
  out.set("public_connectors", std::move(publics));
  Value constraints = Value::array();
  for (const Constraint& constraint : constraints_)
    constraints.push_back(constraint.to_dict());
  out.set("constraints", std::move(constraints));
  Value grounded = Value::array();
  for (const std::string& id : grounded_)
    grounded.push_back(id);
  out.set("grounded_component_ids", std::move(grounded));
  return out;
}

Assembly Assembly::with_component_path_placement(const std::vector<std::string>& component_path,
                                                 const Placement& placement) const {
  if (component_path.empty())
    throw ValueError("component path must not be empty");
  const Component& component = get_component(component_path.front());
  const Component replacement = [&]() -> Component {
    if (component_path.size() == 1)
      return Component(component.component_id, component.item, placement, component.name);
    const auto* nested = std::get_if<AssemblyPtr>(&component.item);
    if (nested == nullptr)
      throw ValueError("component path crosses a non-assembly component");
    const std::vector<std::string> rest(component_path.begin() + 1, component_path.end());
    return Component(component.component_id,
                     std::make_shared<const Assembly>((*nested)->with_component_path_placement(rest, placement)),
                     component.placement, component.name);
  }();
  std::vector<Component> components;
  components.reserve(components_.size());
  for (const Component& existing : components_) {
    components.push_back(existing.component_id == replacement.component_id ? replacement : existing);
  }
  Assembly result(id_, name_, std::move(components), public_connectors_, constraints_, grounded_);
  result.inherit_metadata(*this);
  result.replace_runtime(runtime());
  return result;
}

}  // namespace scad::product
