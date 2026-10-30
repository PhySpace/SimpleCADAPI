// ShapeSelector: the fluent, serializable shape query.
//
//   ql::faces().where(ql::prop("geom.normal.z", ">", 0.9))
//       .order_by(ql::key("geom.center.z"), true).take(1).exactly(1)
//       .boundary("edge").resolve(solid)
//
// A selector is an immutable value; every fluent call returns a new one that
// shares the unchanged parts (predicates and keys are compiled at construction,
// so resolving never parses anything).  to_value()/from_value() are the Python
// to_dict()/from_dict() payloads, key for key and in the same order.
//
// resolve() pipeline (identical to the Python SDK): candidates -> predicate ->
// incident-face constraints -> order keys -> limit -> cardinality assertions.
// A violated assertion throws a scad::Error that lists what matched and what
// exists instead (see diagnostics.hpp).
//
// This class is the QL implementation of the seam semantic/selection.hpp declares
// (scad::ShapeSelector), so apply_tag_rselection accepts it directly.
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/ql/key.hpp"
#include "scad/ql/predicate.hpp"
#include "scad/ql/scope.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/topo/shape.hpp"

namespace scad::ql {

struct TraversalSpec {
  std::string relation;  // "boundary"
  [[nodiscard]] Value to_value() const;
  [[nodiscard]] static TraversalSpec from_value(const Value& payload);
  [[nodiscard]] bool operator==(const TraversalSpec&) const = default;
};

class ShapeSelector final : public scad::ShapeSelector {
 public:
  // Any string is accepted, like the Python dataclass; the topology kinds are
  // "vertex" "edge" "wire" "face" "shell" "solid" "compound".
  explicit ShapeSelector(std::string target_kind);
  explicit ShapeSelector(Kind target_kind);

  // ---- the dataclass fields --------------------------------------------------
  [[nodiscard]] const std::string& target_kind() const noexcept;
  [[nodiscard]] const ShapeSelector* source_selector() const noexcept;  // nullptr when none
  [[nodiscard]] const std::optional<TraversalSpec>& traversal() const noexcept;
  [[nodiscard]] const std::optional<Predicate>& predicate() const noexcept;
  [[nodiscard]] const std::optional<Key>& order_key() const noexcept;
  [[nodiscard]] const std::vector<std::pair<Key, bool>>& order_keys() const noexcept;
  [[nodiscard]] bool order_desc() const noexcept;
  [[nodiscard]] std::optional<std::int64_t> limit_count() const noexcept;
  // "exactly" / "at_least" / "at_most" in the order they were asserted.
  [[nodiscard]] const std::vector<std::pair<std::string, std::int64_t>>& cardinality() const noexcept;
  [[nodiscard]] const std::optional<std::string>& source_node_id() const noexcept;
  [[nodiscard]] std::optional<int> source_output_slot() const noexcept;
  [[nodiscard]] const std::optional<std::string>& set_operation() const noexcept;
  [[nodiscard]] const std::vector<ShapeSelector>& operands() const noexcept;
  [[nodiscard]] const std::vector<ShapeSelector>& incident_face_selectors() const noexcept;
  [[nodiscard]] bool incident_faces_distinct() const noexcept;
  [[nodiscard]] std::optional<std::int64_t> incident_face_cardinality() const noexcept;

  // ---- fluent builders ---------------------------------------------------------
  // Successive where() calls are and-ed.
  [[nodiscard]] ShapeSelector where(const Predicate& predicate) const;
  [[nodiscard]] ShapeSelector order_by(const Key& sort_key, bool desc = false) const;
  // Anchor at a recorded graph node (node_id must be non-empty, output_slot >= 0).
  [[nodiscard]] ShapeSelector from_source(std::string node_id, int output_slot = 0) const;
  [[nodiscard]] ShapeSelector take(std::int64_t count) const;
  [[nodiscard]] ShapeSelector exactly(std::int64_t count) const;
  [[nodiscard]] ShapeSelector at_least(std::int64_t count) const;
  [[nodiscard]] ShapeSelector at_most(std::int64_t count) const;
  // Only the "boundary" relation exists: the sub-shapes of `to_kind` bounding each selected shape.
  [[nodiscard]] ShapeSelector traverse(std::string_view relation, std::string_view to_kind) const;
  [[nodiscard]] ShapeSelector boundary(std::string_view to_kind) const;
  // Entities present in both result sets (same topology, not merely equal geometry).
  [[nodiscard]] ShapeSelector intersection(const ShapeSelector& other) const;
  [[nodiscard]] ShapeSelector shared_boundary(const ShapeSelector& other, std::string_view to_kind = "edge") const;
  // Edge selectors only: keep edges that touch every given Face selector's result;
  // `distinct` demands a different incident face for each selector.
  [[nodiscard]] ShapeSelector incident_to(std::vector<ShapeSelector> face_selectors, bool distinct = false) const;
  [[nodiscard]] ShapeSelector incident_face_count(std::int64_t exactly) const;

  // ---- evaluation --------------------------------------------------------------
  [[nodiscard]] std::vector<Shape> resolve(const Shape& scope) const override;
  [[nodiscard]] std::vector<Shape> resolve(const Scope& scope) const;
  // resolve(), then report the pick to the active recorder as a graph selection
  // node (Recorder::record_selection).  Operators that consume a selection use this.
  [[nodiscard]] std::vector<Shape> resolve_recorded(const Shape& scope) const;

  // ---- serialization (to_dict / from_dict) -------------------------------------------
  [[nodiscard]] Value to_value() const override;
  [[nodiscard]] static ShapeSelector from_value(const Value& payload);
  [[nodiscard]] bool operator==(const ShapeSelector& other) const;

  // ---- the semantic-layer seam ---------------------------------------------------------
  [[nodiscard]] std::optional<SelectorSource> source() const override;
  [[nodiscard]] std::shared_ptr<const scad::ShapeSelector> from_source(const SelectorSource& source) const override;
  [[nodiscard]] SelectorPtr shared() const;  // a heap copy, for APIs that take SelectorPtr

 private:
  struct Impl;
  explicit ShapeSelector(std::shared_ptr<const Impl> impl) noexcept;
  template <class F>
  ShapeSelector amended(F&& edit) const;
  [[nodiscard]] std::vector<Shape> resolve_with(const Scope& scope, const EvalContext& ctx) const;

  std::shared_ptr<const Impl> impl_;
};

// ---- the module-level constructors ---------------------------------------------------
[[nodiscard]] ShapeSelector edges();
[[nodiscard]] ShapeSelector faces();
[[nodiscard]] ShapeSelector wires();
[[nodiscard]] ShapeSelector vertices();
[[nodiscard]] ShapeSelector solids();
[[nodiscard]] ShapeSelector shells();
[[nodiscard]] inline ShapeSelector selector_from_value(const Value& payload) {
  return ShapeSelector::from_value(payload);
}

}  // namespace scad::ql
