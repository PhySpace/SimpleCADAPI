#include "scad/product/part.hpp"

#include <algorithm>
#include <map>

#include "scad/core/error.hpp"

namespace scad::product {

namespace {

std::vector<Connector> unique_connectors(std::vector<Connector> connectors) {
  std::map<std::string, int> counts;
  for (const Connector& connector : connectors) ++counts[connector.connector_id()];
  std::string duplicates;
  for (const auto& [id, count] : counts) {
    if (count > 1) duplicates += (duplicates.empty() ? "" : ", ") + id;
  }
  if (!duplicates.empty()) throw ValueError("duplicate connector_id: " + duplicates);
  return connectors;
}

}  // namespace

Part::Part(std::string part_id, Solid body, OptionalString name, std::optional<Material> material,
           std::vector<Connector> connectors)
    : part_id_(validate_identifier(part_id, "part_id")),
      body_(std::move(body)),
      name_(clean_name(name)),
      material_(std::move(material)),
      connectors_(unique_connectors(std::move(connectors))) {}

Part Part::with_material(const Material& material) const {
  Part result(part_id_, body_, name_, material, connectors_);
  result.inherit_metadata(*this);
  return result;
}

Part Part::with_connector(const Connector& connector) const {
  const std::vector<std::string> ids = connector_ids();
  if (std::find(ids.begin(), ids.end(), connector.connector_id()) != ids.end()) {
    throw ValueError("duplicate connector_id in part: " + connector.connector_id());
  }
  std::vector<Connector> connectors = connectors_;
  connectors.push_back(connector);
  Part result(part_id_, body_, name_, material_, std::move(connectors));
  result.inherit_metadata(*this);
  return result;
}

std::vector<std::string> Part::connector_ids() const {
  std::vector<std::string> ids;
  ids.reserve(connectors_.size());
  for (const Connector& connector : connectors_) ids.push_back(connector.connector_id());
  return ids;
}

const Connector& Part::get_connector(std::string_view connector_id) const {
  const std::string target = validate_identifier(connector_id, "connector_id");
  for (const Connector& connector : connectors_) {
    if (connector.connector_id() == target) return connector;
  }
  throw LookupError("part has no connector_id '" + target + "'");
}

Value Part::to_dict() const {
  Value out = Value::object();
  out.set("part_id", part_id_);
  out.set("name", name_ ? Value(*name_) : Value());
  out.set("material", material_ ? material_->to_dict() : Value());
  Value rows = Value::array();
  for (const Connector& connector : connectors_) rows.push_back(connector.to_dict());
  out.set("connectors", std::move(rows));
  return out;
}

}  // namespace scad::product
