// What every feature operator shares: recording, selections, argument checks.
//
// The operators of this area (extrude, fillet, cut, translate, ...) all follow
// operators/_support.py: evaluate the arguments, build with the tracked_* kernel
// builders, finish through semantic/finalize.hpp.  The pieces that are not
// specific to one operator live here.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/ops/geometry/types.hpp"  // Scalar3, OptionalString
#include "scad/ql/selector.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// The OpRecord of an operator, built the way reactive::OperationBuilder builds it
// (scalars are evaluated once and stored with the expression they came from), but
// ready to hand to a finalize_* call: inputs are kept even when nothing records,
// because the tag projection reads them, and `op` is always set.  With no recorder
// installed the numbers are evaluated and dropped: nothing is allocated for them.
class FeatureRecord {
 public:
  explicit FeatureRecord(std::string_view op);

  bool recording() const noexcept { return recording_; }

  // A scalar argument; returns its current value.
  double scalar(std::string_view name, const Scalar& value);
  // A point or vector argument: [x, y, z], each symbolic coordinate named "name[i]".
  Vec3 point(std::string_view name, const Scalar3& value);
  // A row-major matrix argument, symbolic cells named "name[i][j]".
  std::vector<std::vector<double>> matrix(std::string_view name, const std::vector<std::vector<Scalar>>& value);

  // A plain (non-symbolic) parameter.
  FeatureRecord& param(std::string_view name, Value value);
  // An input shape and the role it plays.
  FeatureRecord& input(const Shape& shape, std::string role);
  template <class T>
  FeatureRecord& inputs(const std::vector<T>& shapes, const std::string& role) {
    for (const T& shape : shapes) input(shape, role);
    return *this;
  }

  OpRecord take() &&;

 private:
  bool recording_;
  OpRecord record_;
};

// What a detail feature (fillet, chamfer, shell, offset, draft) records about its picks:
// their references with selector hints, and the graph nodes the picks became (or, with no
// recording session, their positions among the source's own sub-shapes).
struct PickParams {
  Value refs = Value::array();
  std::vector<std::string> node_ids;
  Value indices = Value::array();

  void apply_refs(FeatureRecord& rec, std::string_view refs_key) const;
  // `ids_key` when there are node ids, else `indices_key` (empty: nothing).
  void apply_ids(FeatureRecord& rec, std::string_view ids_key, std::string_view indices_key) const;
};

// `_serialize_shape_refs` + `_ensure_geo_selection_node_ids` (+ `_serialize_selection_indices` of `candidates`).
// References come before the node ids are ensured when `refs_first` (the blends) and after
// them otherwise (offset, draft): a pick's reference names the select node once it has one.
// Empty without a recording session.
PickParams capture_picks(const Shape& source, const std::vector<Shape>& picked, const std::vector<Shape>& candidates,
                         bool refs_first);

template <class T, class C>
PickParams capture_picks(const Shape& source, const std::vector<T>& picked, const std::vector<C>& candidates, bool refs_first) {
  return capture_picks(source, std::vector<Shape>(picked.begin(), picked.end()),
                       std::vector<Shape>(candidates.begin(), candidates.end()), refs_first);
}

// "Edges the caller listed, or a ql selector that finds them in the operand"
// (_resolve_selector_or_shapes).  A selector is resolved against the operator's
// solid and reported to the recorder as a selection, so the picks follow their
// source when it is rebuilt.
template <class T>
class Selection {
 public:
  Selection() = default;
  Selection(std::vector<T> items) : items_(std::move(items)) {}          // NOLINT(google-explicit-constructor)
  Selection(ql::ShapeSelector selector) : selector_(std::move(selector)) {}  // NOLINT(google-explicit-constructor)

  // A selector may call back into Python (ql property resolvers): a binding keeps
  // the GIL while it resolves one.
  bool is_selector() const noexcept { return selector_.has_value(); }

  std::vector<T> resolve(const Shape& scope) const {
    if (!selector_) return items_;
    std::vector<T> picked;
    for (const Shape& shape : selector_->resolve(scope)) picked.emplace_back(shape);
    return picked;
  }

 private:
  std::vector<T> items_;
  std::optional<ql::ShapeSelector> selector_;
};

using EdgeSelection = Selection<Edge>;
using FaceSelection = Selection<Face>;

// Python's `get_active_session() is not None`: a recording session exists, even
// while its recording is suspended (an executor rebuilding a node).  Operators that
// record their parts as separate nodes in a session, and as one node otherwise,
// ask this.
bool recording_session_active();

// TrackingPolicy for an operator that takes `tracking_policy=` ("full" or "graph",
// any case): the graph policy of the surrounding scope wins.  ValueError otherwise.
TrackingPolicy resolve_tracking_policy(std::string_view requested);
std::string_view to_string(TrackingPolicy policy) noexcept;

// evaluate_scalar as the Python SDK words it: a NaN or infinity is ValueError("value must be finite").
double evaluate_finite(const Scalar& scalar);

// `_finite_vector` of an evaluated 3-vector: ValueError("value must be finite") for a NaN or infinity.
Vec3 finite_vector(const Scalar3& value, std::string_view name);

// `target._metadata = source._metadata.copy()` for a result that carries none of its own;
// later sources win over earlier ones (dict.update).
void inherit_metadata(Shape& target, std::initializer_list<const Shape*> sources);
template <class T>
void inherit_metadata(Shape& target, const std::vector<T>& sources) {
  for (const T& source : sources) inherit_metadata(target, {&source});
}

// repr() of a Python float: the shortest text that reads back as the same number.
std::string python_float_repr(double value);

// "%.<digits>g", as Python's format spec .4g / .6g.
std::string general_format(double value, int digits);

// `_finish`: what the builders that have no face-history channel end with.  `built` must
// hold exactly one solid; it is made outward-pointing, checked for validity, given the
// metadata of `source`, and recorded with `record` (op, params, inputs) as partial lineage
// of `source`.
Solid finish_solid(const Shape& source, const TopoDS_Shape& built, OpRecord record);

}  // namespace scad
