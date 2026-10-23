// OperationBuilder: the one place an operator turns its arguments into a
// recorded operation.
//
//     Solid make_box_rsolid(const Scalar& width, const Scalar& height, const Scalar& depth) {
//       OperationBuilder rec("make_box_rsolid");
//       const double w = rec.scalar("width", width);     // evaluated once, recorded as given
//       const double h = rec.scalar("height", height);
//       const double d = rec.scalar("depth", depth);
//       Solid result = build_box(w, h, d);
//       rec.record({result});
//       return result;
//     }
//
// `scalar` evaluates through scad::evaluate_scalar (so the active session's
// parameter edits apply and NaN/inf are rejected as "<name> must be a finite
// number"), stores the number under `name` and, when the argument was symbolic,
// keeps the Scalar so the reactive engine can re-evaluate it.  With no recorder
// installed the builder only evaluates: it allocates nothing.
//
// Not thread-safe; use it on the thread that runs the operator.
#pragma once

#include <string>
#include <string_view>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive {

class OperationBuilder {
 public:
  explicit OperationBuilder(std::string op);

  // True when a recorder is installed and the operation will be recorded.
  bool recording() const noexcept { return recorder_ != nullptr; }

  // A scalar argument.  Returns its current value.
  double scalar(std::string_view name, const Scalar& value);
  // One element of an array argument, recorded as "name[index]"; the number is
  // also appended to the array parameter `name`.
  double scalar_at(std::string_view name, std::size_t index, const Scalar& value);

  // A plain (non-symbolic) parameter.
  OperationBuilder& param(std::string_view name, Value value);
  // An input shape and the role it plays.
  OperationBuilder& input(const Shape& shape, std::string role);
  OperationBuilder& delta(TopoDelta delta);
  OperationBuilder& semantic_delta(SemanticDelta delta);

  // Hand the operation to the recorder (a no-op without one).
  void record(const std::vector<Shape>& outputs) const;

 private:
  Recorder* recorder_;
  OpRecord record_;
};

}  // namespace scad::reactive
