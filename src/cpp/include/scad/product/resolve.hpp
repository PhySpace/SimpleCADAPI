// Finding a connector through an assembly: direct components, and the public connectors
// that nested assemblies forward (product/connector.py resolve_*).
#pragma once

#include <string_view>

#include "scad/product/assembly.hpp"
#include "scad/product/connector.hpp"

namespace scad::product {

// The connector `ref` names in `assembly`.
Connector resolve_connector(const Assembly& assembly, const ConnectorRef& ref);

// The Part connector behind `connector_id` of `item`, following public connectors down through
// sub-assemblies.  ValueError on a public connector cycle.
Connector resolve_item_connector(const Item& item, std::string_view connector_id);

// The frame of that connector in the coordinate system of `item`.
Placement resolve_item_connector_placement(const Item& item, std::string_view connector_id);

// The frame of a direct component's connector in the assembly's coordinate system.
Placement resolve_connector_ref_placement(const Assembly& assembly, const ConnectorRef& ref);

}  // namespace scad::product
