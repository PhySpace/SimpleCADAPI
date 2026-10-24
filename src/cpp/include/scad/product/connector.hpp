// Connector datums: a frame anchored by selected geometry or by an explicit placement, and
// the references that name one through a component instance (product/connector.py).
//
// Resolving a connector *through an assembly* (public connectors, nesting) is in resolve.hpp.
#pragma once

#include <optional>
#include <string>

#include "scad/core/value.hpp"
#include "scad/product/placement.hpp"
#include "scad/product/semantic_value.hpp"
#include "scad/product/validation.hpp"
#include "scad/topo/shape.hpp"

namespace scad::product {

// A serialisable reference to a sub-shape: the exact-geometry selector and the graph node the
// shape was picked from.  When `flip` is set the derived frame's z axis is negated.
class GeometryRef : public SemanticValue {
 public:
  // `kind` is one of vertex, edge, wire, face, solid (ValueError otherwise); `geo_selector` is a JSON object.
  GeometryRef(std::string kind, OptionalString source_node_id, Value geo_selector, bool flip = false);

  const std::string& kind() const noexcept { return kind_; }
  const OptionalString& source_node_id() const noexcept { return source_node_id_; }
  const Value& geo_selector() const noexcept { return geo_selector_; }
  bool flip() const noexcept { return flip_; }

  Value to_dict() const;
  bool operator==(const GeometryRef& other) const;

 private:
  std::string kind_;
  OptionalString source_node_id_;
  Value geo_selector_;
  bool flip_;
};

// Where a connector's frame comes from: "geometry" (a GeometryRef) or "placement" (a Placement).
class ConnectorAnchor : public SemanticValue {
 public:
  // Geometry anchor.
  explicit ConnectorAnchor(GeometryRef geometry_ref);
  // Placement anchor.
  explicit ConnectorAnchor(Placement placement);
  // The Python constructor: ValueError for an unknown kind, TypeError / ValueError when the
  // payload does not match the kind.
  ConnectorAnchor(const std::string& anchor_kind, std::optional<GeometryRef> geometry_ref,
                  std::optional<Placement> placement);

  const std::string& anchor_kind() const noexcept { return kind_; }
  const std::optional<GeometryRef>& geometry_ref() const noexcept { return geometry_ref_; }
  const std::optional<Placement>& placement() const noexcept { return placement_; }

  Value to_dict() const;
  bool operator==(const ConnectorAnchor& other) const;

 private:
  std::string kind_;
  std::optional<GeometryRef> geometry_ref_;
  std::optional<Placement> placement_;
};

// A datum frame in the coordinate system of the Part that owns it.
class Connector : public SemanticValue {
 public:
  // Exactly one source is needed: `anchor`, or a `geometry_ref` (TypeError when neither).
  // ValueError for a geometry_ref next to a placement anchor.
  explicit Connector(std::string connector_id, std::optional<GeometryRef> geometry_ref = {}, OptionalString name = {},
                     std::optional<ConnectorAnchor> anchor = {});

  const std::string& connector_id() const noexcept { return connector_id_; }
  const std::optional<GeometryRef>& geometry_ref() const noexcept { return geometry_ref_; }
  const OptionalString& name() const noexcept { return name_; }
  const ConnectorAnchor& anchor() const noexcept { return anchor_; }
  const std::string& anchor_kind() const noexcept { return anchor_.anchor_kind(); }

  // The frame in the owning Part's coordinates (resolve_connector_placement).
  Placement placement() const;

  Value to_dict() const;
  bool operator==(const Connector& other) const;

 private:
  std::string connector_id_;
  std::optional<GeometryRef> geometry_ref_;
  OptionalString name_;
  ConnectorAnchor anchor_;
};

// A connector reached through a component instance of an assembly.
class ConnectorRef : public SemanticValue {
 public:
  ConnectorRef(std::string component_id, std::string connector_id);

  const std::string& component_id() const noexcept { return component_id_; }
  const std::string& connector_id() const noexcept { return connector_id_; }

  Value to_dict() const;
  bool operator==(const ConnectorRef& other) const noexcept {
    return component_id_ == other.component_id_ && connector_id_ == other.connector_id_;
  }

 private:
  std::string component_id_, connector_id_;
};

// The frame of a real connector in its owning Part's coordinate system: from the selector's
// face centre and normal, edge midpoint and direction, or vertex point; or the placement.
Placement resolve_connector_placement(const Connector& connector);

// The exact-geometry selector that identifies `shape` (simplecadapi's `_make_geo_selector`).
Value make_geo_selector(const Shape& shape);
// Kind token of a shape: "face", "edge", ...
std::string shape_kind_token(const Shape& shape);

}  // namespace scad::product
