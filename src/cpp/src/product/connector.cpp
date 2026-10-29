#include "scad/core/tolerance.hpp"
#include "scad/product/connector.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>

#include "scad/core/error.hpp"

namespace scad::product {

// ---------------------------------------------------------------------------
// GeometryRef
// ---------------------------------------------------------------------------

GeometryRef::GeometryRef(std::string kind, OptionalString source_node_id, Value geo_selector, bool flip)
    : kind_(strip(kind)),
      source_node_id_(std::move(source_node_id)),
      geo_selector_(std::move(geo_selector)),
      flip_(flip) {
  std::transform(kind_.begin(), kind_.end(), kind_.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (kind_ != "vertex" && kind_ != "edge" && kind_ != "wire" && kind_ != "face" && kind_ != "solid") {
    throw ValueError("kind must be one of: vertex, edge, wire, face, solid");
  }
  if (!geo_selector_.is_object())
    throw TypeError("geo_selector must be a dict");
}

Value GeometryRef::to_dict() const {
  Value out = Value::object();
  out.set("kind", kind_);
  out.set("source_node_id", source_node_id_ ? Value(*source_node_id_) : Value());
  out.set("geo_selector", geo_selector_);
  out.set("flip", flip_);
  return out;
}

bool GeometryRef::operator==(const GeometryRef& other) const {
  return kind_ == other.kind_ && source_node_id_ == other.source_node_id_ && geo_selector_ == other.geo_selector_ &&
         flip_ == other.flip_;
}

// ---------------------------------------------------------------------------
// ConnectorAnchor
// ---------------------------------------------------------------------------

ConnectorAnchor::ConnectorAnchor(GeometryRef geometry_ref)
    : kind_("geometry"), geometry_ref_(std::move(geometry_ref)) {}

ConnectorAnchor::ConnectorAnchor(Placement placement) : kind_("placement"), placement_(std::move(placement)) {}

ConnectorAnchor::ConnectorAnchor(const std::string& anchor_kind, std::optional<GeometryRef> geometry_ref,
                                 std::optional<Placement> placement) {
  kind_ = strip(anchor_kind);
  std::transform(kind_.begin(), kind_.end(), kind_.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (kind_ != "geometry" && kind_ != "placement")
    throw ValueError("anchor_kind must be geometry or placement");
  if (kind_ == "geometry") {
    if (!geometry_ref)
      throw TypeError("geometry anchors require geometry_ref");
    if (placement)
      throw ValueError("geometry anchors do not accept placement");
  } else {
    if (!placement)
      throw TypeError("placement anchors require placement");
    if (geometry_ref)
      throw ValueError("placement anchors do not accept geometry_ref");
  }
  geometry_ref_ = std::move(geometry_ref);
  placement_ = std::move(placement);
}

Value ConnectorAnchor::to_dict() const {
  Value out = Value::object();
  out.set("anchor_kind", kind_);
  if (kind_ == "geometry") {
    out.set("geometry_ref", geometry_ref_->to_dict());
  } else {
    out.set("placement", placement_->to_dict());
  }
  return out;
}

bool ConnectorAnchor::operator==(const ConnectorAnchor& other) const {
  return kind_ == other.kind_ && geometry_ref_ == other.geometry_ref_ && placement_ == other.placement_;
}

// ---------------------------------------------------------------------------
// Connector
// ---------------------------------------------------------------------------

namespace {

ConnectorAnchor anchor_of(std::optional<GeometryRef>& geometry_ref, std::optional<ConnectorAnchor>& anchor) {
  if (!anchor) {
    if (!geometry_ref)
      throw TypeError("geometry_ref must be a GeometryRef when anchor is omitted");
    return ConnectorAnchor(*geometry_ref);
  }
  if (anchor->anchor_kind() == "geometry") {
    geometry_ref = anchor->geometry_ref();
  } else if (geometry_ref) {
    throw ValueError("geometry_ref is only valid for geometry connectors");
  }
  return *anchor;
}

}  // namespace

Connector::Connector(std::string connector_id, std::optional<GeometryRef> geometry_ref, OptionalString name,
                     std::optional<ConnectorAnchor> anchor)
    : connector_id_(validate_identifier(connector_id, "connector_id")),
      geometry_ref_(std::move(geometry_ref)),
      name_(),
      anchor_(anchor_of(geometry_ref_, anchor)) {
  name_ = clean_name(name);
}

Placement Connector::placement() const {
  return resolve_connector_placement(*this);
}

Value Connector::to_dict() const {
  Value out = Value::object();
  out.set("connector_id", connector_id_);
  out.set("name", name_ ? Value(*name_) : Value());
  out.set("anchor", anchor_.to_dict());
  if (geometry_ref_)
    out.set("geometry_ref", geometry_ref_->to_dict());
  return out;
}

bool Connector::operator==(const Connector& other) const {
  return connector_id_ == other.connector_id_ && geometry_ref_ == other.geometry_ref_ && name_ == other.name_ &&
         anchor_ == other.anchor_;
}

// ---------------------------------------------------------------------------
// ConnectorRef
// ---------------------------------------------------------------------------

ConnectorRef::ConnectorRef(std::string component_id, std::string connector_id)
    : component_id_(validate_identifier(component_id, "component_id")),
      connector_id_(validate_identifier(connector_id, "connector_id")) {}

Value ConnectorRef::to_dict() const {
  Value out = Value::object();
  out.set("component_id", component_id_);
  out.set("connector_id", connector_id_);
  return out;
}

// ---------------------------------------------------------------------------
// The frame a geometry reference stands for
// ---------------------------------------------------------------------------

namespace {

Vec3 selector_vec(const Value& selector, std::string_view key, const Vec3& fallback) {
  const Value* found = selector.find(key);
  if (found == nullptr)
    return fallback;
  const Value::Array& items = found->as_array();
  if (items.size() < 3)
    throw IndexError("list index out of range");
  return {finite_float(items[0].as_double(), "x"), finite_float(items[1].as_double(), "y"),
          finite_float(items[2].as_double(), "z")};
}

Vec3 normalized_or_throw(const Vec3& value, const char* field) {
  const Vec3 vec = finite_vec3(value, field);
  const double length = vec.norm();
  if (length <= tol::kNegligibleLength)
    throw ValueError(std::string(field) + " must be a non-zero vector");
  return {vec.x / length, vec.y / length, vec.z / length};
}

// An axis orthogonal to `z_axis`: the coordinate axis least aligned with it, projected.
Vec3 orthogonal_axis(const Vec3& z_axis) {
  const std::array<Vec3, 3> candidates = {Vec3{1, 0, 0}, Vec3{0, 1, 0}, Vec3{0, 0, 1}};
  Vec3 best = candidates[0];
  double best_dot = std::abs(z_axis.dot(best));
  for (std::size_t i = 1; i < candidates.size(); ++i) {
    const double d = std::abs(z_axis.dot(candidates[i]));
    if (d < best_dot) {
      best_dot = d;
      best = candidates[i];
    }
  }
  if (best_dot > 0.999)
    return std::abs(z_axis.y) < 0.999 ? Vec3{0, 1, 0} : Vec3{1, 0, 0};
  const double along = z_axis.dot(best);
  const Vec3 projected{best.x - z_axis.x * along, best.y - z_axis.y * along, best.z - z_axis.z * along};
  return normalized_or_throw(projected, "x_axis");
}

Placement frame_along(const Vec3& center, const Vec3& direction, const char* field, bool flip) {
  Vec3 z_axis = normalized_or_throw(direction, field);
  if (flip)
    z_axis = -z_axis;
  const Vec3 x_axis = orthogonal_axis(z_axis);
  const Vec3 y_axis = normalized_or_throw(z_axis.cross(x_axis), "y_axis");
  return Placement(center, x_axis, y_axis);
}

Placement placement_from_geometry_ref(const GeometryRef& ref) {
  const Value& selector = ref.geo_selector();
  const std::string& kind = ref.kind();
  if (kind == "face") {
    return frame_along(selector_vec(selector, "center", {0, 0, 0}), selector_vec(selector, "normal", {0, 0, 1}),
                       "normal", ref.flip());
  }
  if (kind == "edge") {
    const Vec3 center = selector_vec(selector, "center", {0, 0, 0});
    Vec3 direction{1, 0, 0};
    if (selector.find("start") != nullptr && selector.find("end") != nullptr && !selector.find("start")->is_null() &&
        !selector.find("end")->is_null()) {
      const Vec3 s = selector_vec(selector, "start", {});
      const Vec3 e = selector_vec(selector, "end", {});
      direction = {e.x - s.x, e.y - s.y, e.z - s.z};
    }
    return frame_along(center, direction, "direction", ref.flip());
  }
  if (kind == "vertex")
    return Placement(selector_vec(selector, "coordinates", {0, 0, 0}));
  return Placement(selector_vec(selector, "center", {0, 0, 0}));
}

}  // namespace

Placement resolve_connector_placement(const Connector& connector) {
  const ConnectorAnchor& anchor = connector.anchor();
  if (anchor.anchor_kind() == "geometry")
    return placement_from_geometry_ref(*anchor.geometry_ref());
  return *anchor.placement();
}

}  // namespace scad::product
