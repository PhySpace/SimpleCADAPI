// A Part: one or more named bodies (Solids), with an optional material and its connector datums
// (product/part.py).  Values are immutable: every `with_*` returns a new Part.
//
// A one-body Part is what every Part was before multi-body parts: `body()` is its Solid.  A multi-body
// Part keeps several solids apart inside one product item (bodies of one part are not components: they
// have no placements, joints or constraints between them).  See design-docs/multi-solid-design.md.
#pragma once

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/product/connector.hpp"
#include "scad/product/material.hpp"
#include "scad/product/semantic_value.hpp"
#include "scad/product/validation.hpp"
#include "scad/topo/shape.hpp"

namespace scad::product {

// One named solid of a Part.  The body id is a stable identifier within its Part ("base", "lid").
class Body {
 public:
  // ValueError for a malformed id or an empty name.
  Body(std::string body_id, Solid solid, OptionalString name = {});

  const std::string& body_id() const noexcept { return body_id_; }
  const Solid& solid() const noexcept { return solid_; }
  const OptionalString& name() const noexcept { return name_; }

  Value to_dict() const;  // {"body_id", "name"} (the solid is geometry, not a dict field)

 private:
  std::string body_id_;
  Solid solid_;
  OptionalString name_;
};

// The body id of a Part made from one Solid.
inline constexpr const char* kDefaultBodyId = "body";

class Part : public SemanticValue {
 public:
  // ValueError for a malformed id, an empty name, or duplicate connector ids.
  Part(std::string part_id, Solid body, OptionalString name = {}, std::optional<Material> material = {},
       std::vector<Connector> connectors = {});
  // A Part of several bodies, in this order.  ValueError for no bodies, duplicate body ids, or connectors on
  // more than one body (connectors of a multi-body part are not supported yet).
  Part(std::string part_id, std::vector<Body> bodies, OptionalString name = {}, std::optional<Material> material = {},
       std::vector<Connector> connectors = {});

  const std::string& part_id() const noexcept { return part_id_; }
  // The Solid of a one-body Part.  TypeError for a multi-body Part: read bodies() instead.
  const Solid& body() const;
  const std::vector<Body>& bodies() const noexcept { return bodies_; }
  bool multi_body() const noexcept { return bodies_.size() > 1; }
  std::vector<std::string> body_ids() const;
  // KeyError ("part has no body_id 'x'") for an unknown id.
  const Body& get_body(std::string_view body_id) const;
  const OptionalString& name() const noexcept { return name_; }
  const std::optional<Material>& material() const noexcept { return material_; }
  const std::vector<Connector>& connectors() const noexcept { return connectors_; }

  Part with_material(const Material& material) const;
  // ValueError when the Part already has a connector with that id.
  Part with_connector(const Connector& connector) const;

  std::vector<std::string> connector_ids() const;
  // KeyError ("part has no connector_id 'x'") for an unknown id.
  const Connector& get_connector(std::string_view connector_id) const;

  Value to_dict() const;

 private:
  std::string part_id_;
  std::vector<Body> bodies_;
  OptionalString name_;
  std::optional<Material> material_;
  std::vector<Connector> connectors_;
};

using PartPtr = std::shared_ptr<const Part>;

}  // namespace scad::product
