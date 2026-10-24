#include "scad/ql/key.hpp"

#include <optional>

#include "scad/core/error.hpp"
#include "scad/ql/compare.hpp"
#include "text.hpp"

namespace scad::ql {

namespace {

enum class KeyType : unsigned char { Value, Property, CenterAxis, Unsupported };
enum class GeoField : unsigned char { None, Area, Length, Volume };

[[noreturn]] void missing_field(std::string_view name) {
  throw Exception(PyKind::KeyError, "'" + std::string(name) + "'");
}

std::string required_string(const Value& data, std::string_view name) {
  const Value* found = data.find(name);
  if (found == nullptr) missing_field(name);
  return found->is_string() ? found->as_string() : py_str(*found);
}

GeoField geo_field_of(std::string_view path) {
  if (!path.starts_with("geo.")) return GeoField::None;
  const std::string_view remainder = path.substr(4);
  if (remainder.find('.') != std::string_view::npos) return GeoField::None;
  if (remainder == "area") return GeoField::Area;
  if (remainder == "length") return GeoField::Length;
  if (remainder == "volume") return GeoField::Volume;
  return GeoField::None;
}

std::optional<Measure> measure_of(GeoField field) {
  switch (field) {
    case GeoField::Area: return Measure::Area;
    case GeoField::Length: return Measure::Length;
    case GeoField::Volume: return Measure::Volume;
    case GeoField::None: break;
  }
  return std::nullopt;
}

}  // namespace

struct Key::Impl {
  std::string kind;
  Value data;
  KeyType type = KeyType::Unsupported;
  MetadataPath metadata;                  // Value
  std::optional<PropertyPath> property;   // Property
  GeoField geo = GeoField::None;          // Value: the geo.* measurements
  std::string axis;                       // CenterAxis
  Value fallback;
};

Key::Key(std::string kind, Value data) {
  if (data.is_null()) data = Value::object();
  if (!data.is_object()) throw TypeError("key data must be an object");
  auto impl = std::make_shared<Impl>();
  if (kind == "value" || kind == "property") {
    const std::string path = required_string(data, "path");
    if (const Value* fallback = data.find("default")) impl->fallback = *fallback;
    if (kind == "value") {
      impl->type = KeyType::Value;
      impl->metadata = MetadataPath(path);
      impl->geo = geo_field_of(path);
    } else {
      impl->type = KeyType::Property;
      impl->property.emplace(path);
    }
  } else if (kind == "center_axis") {
    impl->type = KeyType::CenterAxis;
    impl->axis = text::lower(required_string(data, "axis"));
  }
  impl->kind = std::move(kind);
  impl->data = std::move(data);
  impl_ = std::move(impl);
}

const std::string& Key::kind() const noexcept { return impl_->kind; }
const Value& Key::data() const noexcept { return impl_->data; }

Value Key::evaluate(const Shape& shape) const {
  const EvalContext ctx;
  return evaluate(shape, ctx);
}

Value Key::evaluate(const Shape& shape, const EvalContext& ctx) const {
  const Impl& k = *impl_;
  switch (k.type) {
    case KeyType::Value: {
      if (const Value* found = k.metadata.find(shape.metadata())) return *found;
      if (const auto what = measure_of(k.geo))
        if (const std::optional<double> measured = ctx.measure(shape, *what)) return Value(*measured);
      return k.fallback;
    }
    case KeyType::Property: {
      std::optional<Value> found = k.property->lookup(shape, ctx);
      return found ? std::move(*found) : k.fallback;
    }
    case KeyType::CenterAxis: {
      const std::optional<Vec3> center = ctx.center(shape);
      if (!center) return Value();
      if (k.axis == "x") return Value(center->x);
      if (k.axis == "y") return Value(center->y);
      if (k.axis == "z") return Value(center->z);
      throw ValueError("unsupported axis: " + k.axis);
    }
    case KeyType::Unsupported: break;
  }
  throw ValueError("unsupported key kind: " + k.kind);
}

Value Key::to_value() const {
  Value out = Value::object();
  out.set("kind", impl_->kind);
  out.set("data", impl_->data);
  return out;
}

Key Key::from_value(const Value& payload) {
  if (!payload.is_object()) throw TypeError("key payload must be an object");
  const Value* kind = payload.find("kind");
  if (kind == nullptr) missing_field("kind");
  const Value* data = payload.find("data");
  return Key(kind->is_string() ? kind->as_string() : py_str(*kind), data != nullptr ? *data : Value::object());
}

bool Key::operator==(const Key& other) const {
  return impl_ == other.impl_ || (impl_->kind == other.impl_->kind && values_equal(impl_->data, other.impl_->data));
}

namespace {
Key path_key(const char* kind, std::string_view path, Value fallback) {
  Value data = Value::object();
  data.set("path", std::string(path));
  data.set("default", std::move(fallback));
  return Key(kind, std::move(data));
}
}  // namespace

Key value(std::string_view path, Value fallback) { return path_key("value", path, std::move(fallback)); }
Key key(std::string_view path, Value fallback) { return path_key("property", path, std::move(fallback)); }
Key geo(std::string_view field, Value fallback) { return value("geo." + std::string(field), std::move(fallback)); }

Key center_axis(std::string_view axis) {
  const std::string normalized = text::lower(text::strip(axis));
  if (normalized != "x" && normalized != "y" && normalized != "z")
    throw ValueError("axis must be one of 'x', 'y', 'z'");
  return key("geom.center." + normalized);
}

}  // namespace scad::ql
