// Building the OpRecord of an operator.
//
// An operation is recorded as JSON-like `params` holding the *evaluated* numbers, plus
// the scalars that were symbolic, each named by its path in `params` ("width",
// "center[1]", "control_points[2][0]").  OpParams keeps those two in step: every
// scalar argument goes in through one call, which evaluates it, stores the number and
// remembers the expression.
//
//   OpRecord record = OpParams("make_line_redge", {"edge", "primitive"})
//                         .point("start", start)
//                         .point("end", end)
//                         .take();
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/topo/recorder.hpp"

namespace scad {

class OpParams {
 public:
  // `labels` are the node labels of record_operation_if_active(tags=...).
  explicit OpParams(std::string op, std::vector<std::string> labels = {});

  OpParams& scalar(std::string_view name, const Scalar& value);
  OpParams& point(std::string_view name, const Scalar3& value);
  OpParams& optional_point(std::string_view name, const std::optional<Scalar3>& value);  // null when absent
  OpParams& points(std::string_view name, const std::vector<Scalar3>& value);
  OpParams& coordinates(std::string_view name, const std::vector<ScalarPoint>& value);  // 2D/3D poles
  OpParams& scalars(std::string_view name, const ScalarList& value);
  OpParams& optional_scalars(std::string_view name, const std::optional<ScalarList>& value);

  OpParams& vec(std::string_view name, const Vec3& value);
  OpParams& numbers(std::string_view name, const std::vector<double>& value);
  OpParams& integers(std::string_view name, const std::vector<int>& value);
  OpParams& integer(std::string_view name, std::int64_t value);
  OpParams& boolean(std::string_view name, bool value);
  OpParams& text(std::string_view name, std::string_view value);
  OpParams& optional_text(std::string_view name, const OptionalString& value);
  OpParams& null(std::string_view name);

  OpParams& input(Shape shape, std::string role);

  // Moves the record out; use the builder once.
  OpRecord take();

 private:
  OpRecord record_;
};

// Node labels of a primitive / derived output: {"primitive", "edge"} sorted like a set.
std::vector<std::string> primitive_labels(std::string_view kind);
std::vector<std::string> derived_labels(std::string_view kind);

}  // namespace scad
