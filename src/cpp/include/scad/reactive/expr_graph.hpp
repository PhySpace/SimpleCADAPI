// The registry of expression nodes a recording keeps, and the helpers that
// split a parameter set into numbers and expression references: the rest of
// simplecadapi/params/expr.py.
#pragma once

#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/reactive/expr.hpp"

namespace scad::reactive {

// A registry of expression DAG nodes by id.  Not thread-safe: one recording
// session owns one graph.
class ExpressionGraph {
 public:
  std::size_t node_count() const noexcept { return nodes_.size(); }
  const std::vector<ScalarPtr>& nodes() const noexcept { return nodes_; }

  // The node registered under `expr_id`, or nullptr.
  ScalarPtr get(std::string_view expr_id) const;

  // Register an expression and its operands.  ValueError when an id is
  // already taken by a different node; UnitValidationError when the
  // expression is physically inconsistent.  Nothing is registered on failure.
  ScalarPtr register_expr(const ScalarPtr& expr);
  ScalarPtr register_expr(const Scalar& value);

  // {"nodes": [...]} with operands before the nodes that use them.
  Value to_value() const;
  // TypeError / ValueError for a malformed payload.
  static ExpressionGraph from_value(const Value& payload);

 private:
  std::vector<ScalarPtr> nodes_;  // registration order
  std::unordered_map<std::string, std::size_t> index_;
};

// The names whose values are discrete (indices, counts, flags): they are kept
// as they are and never carry an expression.
bool is_discrete_param_name(std::string_view key);

using SymbolicParams = std::vector<std::pair<std::string, Scalar>>;

struct CanonicalParams {
  Value numeric;  // the parameters with every number a float
  Value exprs;    // the same nesting, with {"expr_id": ...} at each symbolic position
};

// Register the expressions of `symbolic` (paths into `params`, see ParamPath)
// and build the two views of the parameters.  A symbolic scalar whose position
// is missing from `params` is written there with its current value.
CanonicalParams canonicalize_params(const Value& params, const SymbolicParams& symbolic, ExpressionGraph& graph);

// The expressions `param_exprs` refers to, in first-use order.  KeyError for an
// id the graph does not know.
std::vector<ScalarPtr> referenced_expressions(const Value& param_exprs, const ExpressionGraph& graph);

}  // namespace scad::reactive
