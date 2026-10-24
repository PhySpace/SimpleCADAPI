// Small helpers shared by the semantic translation units.  Private: not installed.
#pragma once

#include <initializer_list>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad::detail {

// {"a": 1, "b": "x"} in insertion order.
inline Value object(std::initializer_list<std::pair<std::string, Value>> members) {
  Value out = Value::object();
  for (const auto& [key, value] : members) out.set(key, value);
  return out;
}

inline Value string_array(const std::vector<std::string>& items) {
  Value out = Value::array();
  for (const auto& item : items) out.push_back(item);
  return out;
}

inline Value vec3_array(const Vec3& v) {
  Value out = Value::array();
  out.push_back(v.x);
  out.push_back(v.y);
  out.push_back(v.z);
  return out;
}

inline bool starts_with(std::string_view s, std::string_view prefix) noexcept {
  return s.substr(0, prefix.size()) == prefix;
}

inline bool ends_with(std::string_view s, std::string_view suffix) noexcept {
  return s.size() >= suffix.size() && s.substr(s.size() - suffix.size()) == suffix;
}

inline std::string strip(std::string_view s) {
  const auto b = s.find_first_not_of(" \t\r\n\f\v");
  if (b == std::string_view::npos) return {};
  const auto e = s.find_last_not_of(" \t\r\n\f\v");
  return std::string(s.substr(b, e - b + 1));
}

inline std::string lower(std::string_view s) {
  std::string out(s);
  for (char& c : out)
    if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
  return out;
}

inline std::string upper(std::string_view s) {
  std::string out(s);
  for (char& c : out)
    if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
  return out;
}

// str(value) for the scalar kinds evidence carries; JSON text for the rest.
inline std::string text_of(const Value& v) {
  if (v.is_string()) return v.as_string();
  return v.dump();
}

// The string a Value holds, else `fallback`.
inline std::string string_or(const Value* v, std::string fallback) {
  return v != nullptr && v->is_string() ? v->as_string() : std::move(fallback);
}

// The graph node `shape` came from, when a recorder is installed and has attached one
// (the recorder sets runtime "graph.node_id" / "graph.output_slot" on what it records).
inline int output_slot_of(const Shape& shape) {
  const Value slot = shape.get_runtime("graph.output_slot", 0);
  return slot.is_int() ? static_cast<int>(slot.as_int()) : 0;
}

inline std::optional<SelectorSource> graph_source_of(const Shape& shape) {
  if (current_recorder() == nullptr) return std::nullopt;
  const Value node = shape.get_runtime("graph.node_id");
  if (!node.is_string() || node.as_string().empty()) return std::nullopt;
  return SelectorSource{node.as_string(), output_slot_of(shape)};
}

// A typed handle's base, for APIs that take Shape.
template <class T>
std::vector<Shape> as_shapes(const std::vector<T>& items) {
  return std::vector<Shape>(items.begin(), items.end());
}

}  // namespace scad::detail
