// Serializable sort keys (SerializableKey): what order_by sorts on.
//
// Kinds: "value" (metadata first, then geo.area/length/volume), "property" (the
// property language), "center_axis".  A key yields a Value; null means "no
// value", which sorts after everything.
#pragma once

#include <memory>
#include <string>
#include <string_view>

#include "scad/core/value.hpp"
#include "scad/ql/property.hpp"
#include "scad/topo/shape.hpp"

namespace scad::ql {

class Key {
 public:
  // path-based kinds must carry data["path"] (KeyError otherwise).  An unknown
  // kind is accepted, like the Python dataclass, and fails when evaluated.
  Key(std::string kind, Value data = Value::object());

  [[nodiscard]] const std::string& kind() const noexcept;
  [[nodiscard]] const Value& data() const noexcept;

  [[nodiscard]] Value evaluate(const Shape& shape) const;
  [[nodiscard]] Value evaluate(const Shape& shape, const EvalContext& ctx) const;
  [[nodiscard]] Value operator()(const Shape& shape) const { return evaluate(shape); }

  [[nodiscard]] Value to_value() const;  // {"kind", "data"}
  [[nodiscard]] static Key from_value(const Value& payload);
  [[nodiscard]] bool operator==(const Key& other) const;

 private:
  struct Impl;
  std::shared_ptr<const Impl> impl_;
};

// ---- factories ---------------------------------------------------------------------
[[nodiscard]] Key value(std::string_view path, Value fallback = {});  // kind "value"
[[nodiscard]] Key key(std::string_view path, Value fallback = {});    // kind "property"
[[nodiscard]] Key geo(std::string_view field, Value fallback = {});   // value("geo.<field>")
[[nodiscard]] Key center_axis(std::string_view axis);                 // key("geom.center.<axis>")

}  // namespace scad::ql
