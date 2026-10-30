// Serializable predicates (SerializablePredicate).
//
// A predicate is data: a kind, a small data object and child predicates.  It
// round-trips through to_value()/from_value() exactly like the Python dict, and
// it is compiled once, at construction, into a flat vector of typed nodes (tag
// pattern split, operator parsed, metadata path split, property resolved to an
// enum).  Evaluating a candidate walks that vector: no string parsing and no
// allocation per candidate for the geometric and metadata predicates.
//
// Kinds: tag, operation_event, origin_role, output_role, source_binding,
// source_topology, meta, property_compare, and, or, not.
#pragma once

#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/ql/property.hpp"
#include "scad/topo/shape.hpp"
#include "scad/topo/tagging.hpp"

namespace scad::ql {

class Predicate {
 public:
  // Validates `data` against the kind's schema (ValueError otherwise) and compiles.
  Predicate(std::string kind, Value data = Value::object(), std::vector<Predicate> children = {});

  [[nodiscard]] const std::string& kind() const noexcept;
  [[nodiscard]] const Value& data() const noexcept;
  [[nodiscard]] const std::vector<Predicate>& children() const noexcept;

  [[nodiscard]] bool matches(const Shape& shape) const;
  [[nodiscard]] bool matches(const Shape& shape, const EvalContext& ctx) const;
  [[nodiscard]] bool operator()(const Shape& shape) const { return matches(shape); }

  // {"kind", "data", "children"}
  [[nodiscard]] Value to_value() const;
  // Strict: unknown fields / kinds, missing data and bad child counts are ValueErrors.
  [[nodiscard]] static Predicate from_value(const Value& payload);

  [[nodiscard]] bool operator==(const Predicate& other) const;

 private:
  struct Impl;
  std::shared_ptr<const Impl> impl_;
};

// ---- factories (the module-level functions of simplecadapi.ql) -------------------

// Exact tag, or a prefix when the pattern ends in '*'.
[[nodiscard]] Predicate tag(std::string_view pattern, TagScope scope = TagScope::Effective);
[[nodiscard]] Predicate tag(std::string_view pattern, std::string_view scope);
// Compare the metadata value at `path`: "==", "!=", ">", ">=", "<", "<=".
[[nodiscard]] Predicate meta(std::string_view path, std::string_view op, Value expected);
// Compare a property (see property.hpp); a missing property never matches.
[[nodiscard]] Predicate prop(std::string_view path, std::string_view op, Value expected);
[[nodiscard]] Predicate curve_type(std::string_view kind);    // geom.type == KIND
[[nodiscard]] Predicate surface_type(std::string_view kind);  // geom.type == KIND

[[nodiscard]] Predicate and_(std::vector<Predicate> predicates);
[[nodiscard]] Predicate or_(std::vector<Predicate> predicates);
[[nodiscard]] Predicate not_(Predicate predicate);

// Typed tracking evidence, under metadata "track".
[[nodiscard]] Predicate operation_event(std::string_view op_name, std::string_view event = "*");
[[nodiscard]] Predicate origin_role(std::string_view role_name);
[[nodiscard]] Predicate output_role(std::string_view role_name);
// A projected local binding, by exact source identity.
[[nodiscard]] Predicate source_binding(std::string_view binding_id);
[[nodiscard]] Predicate source_topology(std::string_view topo_id);
// Aliases.
[[nodiscard]] inline Predicate op(std::string_view op_name, std::string_view event = "*") {
  return operation_event(op_name, event);
}
[[nodiscard]] inline Predicate origin(std::string_view role_name) {
  return origin_role(role_name);
}
[[nodiscard]] Predicate role(std::string_view role_name);  // tag("role.<name>.*")

}  // namespace scad::ql
