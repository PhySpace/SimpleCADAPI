// Tag assignment and the public tag operators (operators/selection.py).
//
//   apply_tag(shape, "role.mount")                      tag one shape, in place
//   apply_tag_rselection(scope, selector_or_shapes, ..) tag what a query / list picks, on a detached view
//   list_tags / explain_tag / select_faces_by_tag / select_edges_by_tag
//
// `ShapeSelector` is the seam to the QL language: apply_tag_rselection takes
// anything that can resolve itself against a scope and serialise itself into the
// binding's target.  The QL area implements it; `NativeSelector` below covers the
// two queries the SDK issues on its own behalf ("the one solid", "the faces with
// output role R").
#pragma once

#include <concepts>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/topo/shape.hpp"
#include "scad/topo/tagging.hpp"

namespace scad {

// The graph node a selector (or a tag assignment) is anchored to.
struct SelectorSource {
  std::string node_id;
  int output_slot = 0;
};

class ShapeSelector {
 public:
  virtual ~ShapeSelector() = default;

  // The shapes the query picks inside `scope`, cardinality checks included.
  virtual std::vector<Shape> resolve(const Shape& scope) const = 0;
  // ShapeSelector.to_dict(): stored verbatim as the tag target's `selector`.
  virtual Value to_value() const = 0;
  // Where the selector says it reads from; nullopt when unanchored.
  virtual std::optional<SelectorSource> source() const { return std::nullopt; }
  // A copy anchored at `source` (ShapeSelector.from_source), or nullptr when the
  // selector cannot be anchored (it is then used as it is).
  virtual std::shared_ptr<const ShapeSelector> from_source(const SelectorSource& source) const {
    (void)source;
    return nullptr;
  }
};

using SelectorPtr = std::shared_ptr<const ShapeSelector>;

// What a tag is assigned to: a query, or explicit shapes (which must belong to the scope).
class TagTargets {
 public:
  TagTargets(SelectorPtr selector) : selector_(std::move(selector)) {}  // NOLINT(google-explicit-constructor)
  template <class T>
    requires std::derived_from<T, Shape>
  TagTargets(const std::vector<T>& shapes) : shapes_(shapes.begin(), shapes.end()) {}  // NOLINT

  const SelectorPtr& selector() const noexcept { return selector_; }
  const std::vector<Shape>& shapes() const noexcept { return shapes_; }

 private:
  SelectorPtr selector_;
  std::vector<Shape> shapes_;
};

// The two queries the SDK issues itself.  Serialises exactly as QL's
// ShapeSelector.to_dict() does for `ShapeSelector(kind).exactly(1)` and
// `ShapeSelector(kind).where(output_role(role)).exactly(1) / .at_least(1)`.
class NativeSelector final : public ShapeSelector {
 public:
  enum class Count { Exactly, AtLeast };

  NativeSelector(Kind target, std::optional<std::string> output_role, Count mode, int count,
                 std::optional<SelectorSource> source = std::nullopt);

  static SelectorPtr exactly_one(Kind target);
  static SelectorPtr with_output_role(Kind target, std::string_view role, bool exactly_one);

  std::vector<Shape> resolve(const Shape& scope) const override;
  Value to_value() const override;
  std::optional<SelectorSource> source() const override { return source_; }
  std::shared_ptr<const ShapeSelector> from_source(const SelectorSource& source) const override;

 private:
  Kind target_;
  std::optional<std::string> output_role_;
  Count mode_;
  int count_;
  std::optional<SelectorSource> source_;
};

// ---- assignment ----------------------------------------------------------------

struct TagAssignOptions {
  std::string authoring_source = "simplecadapi.apply_tag_rselection";
  Value extra_evidence = Value::object();  // merged into the binding's evidence after the standard keys
  bool clone_scope = true;                 // false: tag `scope` itself (apply_tag)
};

// _apply_tag_rselection: attach one canonical user binding to every target.
// The targets are resolved on a detached view of `scope` (a clone carrying its
// semantic state) unless options.clone_scope is false, and the view is returned.
// With a recorder installed the assignment is recorded as an
// `apply_tag_rselection` operation whose input is `scope`.
Shape assign_tag(const Shape& scope, const TagTargets& targets, std::string_view tag, TopologyPropagation topology,
                 LineagePolicy lineage, const TagAssignOptions& options = {});

// A detached view of `shape` over the same geometry with all semantic state of
// its topology copied (clone_semantic_shape_view); topo ids are preserved.
Shape clone_semantic_view(const Shape& shape);

// ---- the public operators (selection.py); errors are scad::Error with the Python operation names ----

Shape apply_tag_rselection(const Shape& scope, const TagTargets& targets, std::string_view tag,
                           TopologyPropagation topology = TopologyPropagation::Local,
                           LineagePolicy lineage = LineagePolicy::ContinuationFragment);

// Attach a local user tag with continuation/fragment lineage policy; returns `shape`.
Shape apply_tag(const Shape& shape, std::string_view tag);

std::vector<std::string> list_tags(const Shape& shape, TagScope scope = TagScope::Effective);
std::vector<Value> explain_tag(const Shape& shape, std::string_view tag, TagScope scope = TagScope::Effective);
std::vector<Face> select_faces_by_tag(const Solid& solid, std::string_view tag, TagScope scope = TagScope::Effective);
// `shape` must be a Face or a Solid.
std::vector<Edge> select_edges_by_tag(const Shape& shape, std::string_view tag, TagScope scope = TagScope::Effective);

}  // namespace scad
