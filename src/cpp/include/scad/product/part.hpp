// A Part: exactly one Solid, with an optional material and its connector datums
// (product/part.py).  Values are immutable: every `with_*` returns a new Part.
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

class Part : public SemanticValue {
 public:
  // ValueError for a malformed id, an empty name, or duplicate connector ids.
  Part(std::string part_id, Solid body, OptionalString name = {}, std::optional<Material> material = {},
       std::vector<Connector> connectors = {});

  const std::string& part_id() const noexcept { return part_id_; }
  const Solid& body() const noexcept { return body_; }
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
  Solid body_;
  OptionalString name_;
  std::optional<Material> material_;
  std::vector<Connector> connectors_;
};

using PartPtr = std::shared_ptr<const Part>;

}  // namespace scad::product
