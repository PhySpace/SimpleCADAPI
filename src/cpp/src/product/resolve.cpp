#include "scad/product/resolve.hpp"

#include <set>
#include <utility>

#include "scad/core/error.hpp"

namespace scad::product {

namespace {

using Visited = std::set<std::pair<const Assembly*, std::string>>;

// Marks (assembly, connector) as visited; ValueError when it already was.
Visited entered(const Visited& seen, const Assembly& assembly, const std::string& connector_id) {
  Visited next = seen;
  if (!next.emplace(&assembly, connector_id).second) {
    throw ValueError("public connector cycle detected at " + python_repr(connector_id));
  }
  return next;
}

Connector resolve_through(const Item& item, std::string_view connector_id, const Visited& seen) {
  if (const auto* part = std::get_if<PartPtr>(&item))
    return (*part)->get_connector(connector_id);
  const Assembly& assembly = *std::get<AssemblyPtr>(item);
  const Visited next = entered(seen, assembly, std::string(connector_id));
  const PublicConnectorRef& pub = assembly.get_public_connector(connector_id);
  return resolve_through(assembly.get_component(pub.component_id).item, pub.connector_id, next);
}

Placement placement_through(const Item& item, std::string_view connector_id, const Visited& seen) {
  if (const auto* part = std::get_if<PartPtr>(&item))
    return resolve_connector_placement((*part)->get_connector(connector_id));
  const Assembly& assembly = *std::get<AssemblyPtr>(item);
  const Visited next = entered(seen, assembly, std::string(connector_id));
  const PublicConnectorRef& pub = assembly.get_public_connector(connector_id);
  const Component& component = assembly.get_component(pub.component_id);
  return component.placement.compose(placement_through(component.item, pub.connector_id, next));
}

}  // namespace

Connector resolve_connector(const Assembly& assembly, const ConnectorRef& ref) {
  return resolve_item_connector(assembly.get_component(ref.component_id()).item, ref.connector_id());
}

Connector resolve_item_connector(const Item& item, std::string_view connector_id) {
  return resolve_through(item, connector_id, {});
}

Placement resolve_item_connector_placement(const Item& item, std::string_view connector_id) {
  return placement_through(item, connector_id, {});
}

Placement resolve_connector_ref_placement(const Assembly& assembly, const ConnectorRef& ref) {
  const Component& component = assembly.get_component(ref.component_id());
  return component.placement.compose(resolve_item_connector_placement(component.item, ref.connector_id()));
}

}  // namespace scad::product
