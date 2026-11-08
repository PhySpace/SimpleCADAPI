#include "scad/product/part.hpp"

#include <algorithm>
#include <map>

#include "scad/core/error.hpp"

namespace scad::product {

namespace {

std::vector<Connector> unique_connectors(std::vector<Connector> connectors) {
  std::map<std::string, int> counts;
  for (const Connector& connector : connectors)
    ++counts[connector.connector_id()];
  std::string duplicates;
  for (const auto& [id, count] : counts) {
    if (count > 1)
      duplicates += (duplicates.empty() ? "" : ", ") + id;
  }
  if (!duplicates.empty())
    throw ValueError("duplicate connector_id: " + duplicates);
  return connectors;
}

std::vector<Body> checked_bodies(std::vector<Body> bodies) {
  if (bodies.empty())
    throw ValueError("a Part needs at least one body");
  std::map<std::string, int> counts;
  for (const Body& body : bodies)
    ++counts[body.body_id()];
  std::string duplicates;
  for (const auto& [id, count] : counts) {
    if (count > 1)
      duplicates += (duplicates.empty() ? "" : ", ") + id;
  }
  if (!duplicates.empty())
    throw ValueError("duplicate body_id: " + duplicates);
  return bodies;
}

std::string joined_ids(const std::vector<Body>& bodies) {
  std::string out;
  for (const Body& body : bodies)
    out += (out.empty() ? "" : ", ") + body.body_id();
  return out;
}

std::optional<Vec3> checked_color(const std::optional<Vec3>& color) {
  if (!color)
    return color;
  const Vec3 rgb = finite_vec3(*color, "color");
  for (double c : {rgb.x, rgb.y, rgb.z}) {
    if (c < 0.0 || c > 1.0)
      throw ValueError("color components must be in [0.0, 1.0]");
  }
  return rgb;
}

OptionalDouble checked_opacity(OptionalDouble opacity) {
  opacity = optional_float(opacity, "opacity");
  if (opacity && (*opacity < 0.0 || *opacity > 1.0))
    throw ValueError("opacity must be in [0.0, 1.0]");
  return opacity;
}

}  // namespace

Body::Body(std::string body_id, Solid solid, OptionalString name, std::optional<Vec3> color, OptionalDouble opacity)
    : body_id_(validate_identifier(body_id, "body_id")),
      solid_(std::move(solid)),
      name_(clean_name(name)),
      color_(checked_color(color)),
      opacity_(checked_opacity(opacity)) {}

Body Body::with_appearance(OptionalString name, std::optional<Vec3> color, OptionalDouble opacity) const {
  return Body(body_id_, solid_, std::move(name), color, opacity);
}

Value Body::to_dict() const {
  Value out = Value::object();
  out.set("body_id", body_id_);
  out.set("name", name_ ? Value(*name_) : Value());
  if (color_)  // a body without an appearance keeps the dict it always had
    out.set("color", to_array(*color_));
  if (opacity_)
    out.set("opacity", *opacity_);
  return out;
}

namespace {

// A one-body Part writes its body in to_dict only when the body says more than its solid.
bool plain_default_body(const Body& body) {
  return body.body_id() == kDefaultBodyId && !body.name() && !body.has_appearance();
}

}  // namespace

Part::Part(std::string part_id, Solid body, OptionalString name, std::optional<Material> material,
           std::vector<Connector> connectors)
    : Part(std::move(part_id), std::vector<Body>{Body(kDefaultBodyId, std::move(body))}, std::move(name),
           std::move(material), std::move(connectors)) {}

Part::Part(std::string part_id, std::vector<Body> bodies, OptionalString name, std::optional<Material> material,
           std::vector<Connector> connectors)
    : part_id_(validate_identifier(part_id, "part_id")),
      bodies_(checked_bodies(std::move(bodies))),
      name_(clean_name(name)),
      material_(std::move(material)),
      connectors_(unique_connectors(std::move(connectors))) {
  if (bodies_.size() > 1 && !connectors_.empty())
    throw ValueError("connectors on a multi-body part are not supported yet (part '" + part_id_ + "')");
}

const Solid& Part::body() const {
  if (bodies_.size() != 1) {
    throw TypeError("part '" + part_id_ + "' has " + std::to_string(bodies_.size()) + " bodies (" +
                    joined_ids(bodies_) + "); read Part.bodies or Part.get_body(body_id)");
  }
  return bodies_.front().solid();
}

std::vector<std::string> Part::body_ids() const {
  std::vector<std::string> ids;
  ids.reserve(bodies_.size());
  for (const Body& body : bodies_)
    ids.push_back(body.body_id());
  return ids;
}

const Body& Part::get_body(std::string_view body_id) const {
  const std::string target = validate_identifier(body_id, "body_id");
  for (const Body& body : bodies_) {
    if (body.body_id() == target)
      return body;
  }
  throw LookupError("part has no body_id '" + target + "'");
}

Part Part::with_material(const Material& material) const {
  Part result(part_id_, bodies_, name_, material, connectors_);
  result.inherit_metadata(*this);
  return result;
}

Part Part::with_body(const Body& body) const {
  std::vector<Body> bodies = bodies_;
  bool found = false;
  for (Body& item : bodies) {
    if (item.body_id() == body.body_id()) {
      item = body;
      found = true;
    }
  }
  if (!found)
    throw LookupError("part has no body_id '" + body.body_id() + "'");
  Part result(part_id_, std::move(bodies), name_, material_, connectors_);
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
  Part result(part_id_, bodies_, name_, material_, std::move(connectors));
  result.inherit_metadata(*this);
  return result;
}

std::vector<std::string> Part::connector_ids() const {
  std::vector<std::string> ids;
  ids.reserve(connectors_.size());
  for (const Connector& connector : connectors_)
    ids.push_back(connector.connector_id());
  return ids;
}

const Connector& Part::get_connector(std::string_view connector_id) const {
  const std::string target = validate_identifier(connector_id, "connector_id");
  for (const Connector& connector : connectors_) {
    if (connector.connector_id() == target)
      return connector;
  }
  throw LookupError("part has no connector_id '" + target + "'");
}

Value Part::to_dict() const {
  Value out = Value::object();
  out.set("part_id", part_id_);
  out.set("name", name_ ? Value(*name_) : Value());
  out.set("material", material_ ? material_->to_dict() : Value());
  Value rows = Value::array();
  for (const Connector& connector : connectors_)
    rows.push_back(connector.to_dict());
  out.set("connectors", std::move(rows));
  // a one-body Part keeps the dict it always had, unless its body has a name or an appearance
  if (bodies_.size() > 1 || !plain_default_body(bodies_.front())) {
    Value bodies = Value::array();
    for (const Body& body : bodies_)
      bodies.push_back(body.to_dict());
    out.set("bodies", std::move(bodies));
  }
  return out;
}

}  // namespace scad::product
