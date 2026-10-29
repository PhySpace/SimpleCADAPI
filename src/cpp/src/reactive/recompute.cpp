// Session: the reactive engine -- dirty marking, memoization, recompute().
#include <algorithm>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/reactive/param_path.hpp"
#include "scad/reactive/session.hpp"

namespace scad::reactive {

namespace {

[[noreturn]] void raise_recompute_error(const OperationNode& node, const std::exception& cause) {
  const ErrorSpec spec(node.op,
                       "Failed to recompute '" + node.op + "' (node " + node.node_id + ") after a parameter change.",
                       {"The new parameter values are outside what the operation can build (a zero or negative size, a "
                        "fillet larger than its edge, ...).",
                        "An upstream result changed so that this step no longer applies."},
                       {"Set the parameter back to a value this operation accepts.",
                        "Read the technical details below, which carry the operation's own message."});
  raise_harness_error(spec, cause);
}

[[noreturn]] void raise_missing_executor(const OperationNode& node) {
  const ErrorSpec spec(
      node.op,
      "The engine cannot recompute '" + node.op + "' (node " + node.node_id + "): no executor is registered for it.",
      {"The operator area that records this operation has not registered an executor."},
      {"Register one with scad::reactive::ExecutorRegistry::add(\"" + node.op +
       "\", ...), as described in scad/reactive/registry.hpp."});
  raise_harness_error(spec, "No executor registered for operation '" + node.op + "'");
}

// The recorded numbers of a node, with each symbolic scalar re-evaluated under the edited bindings;
// `scalars` receives the evaluated values by parameter path.
Value evaluate_node_params(const OperationNode& node, const Bindings& bindings, ScalarValues& scalars) {
  Value params = node.params;
  if (node.source_index) {
    Value at = Value::array();
    at.push_back(node.source_index->first);
    at.push_back(node.source_index->second);
    params.set("__source_index", std::move(at));
  }
  for (const auto& [path, scalar] : node.symbolic) {
    const double value = evaluate_scalar(scalar, path, &bindings);
    scalars[path] = value;
    set_param(params, ParamPath::parse(path), Value(value));
  }
  return params;
}

// Runs the executor under the conditions the operation was recorded in, and checks its output count.
std::vector<Shape> run_executor(const OperationNode& node, const Executor& executor, const Value& params,
                                const std::vector<OpInput>& inputs, const ScalarValues& scalars, bool value_output) {
  std::vector<Shape> outputs;
  try {
    // Executors re-run operators under the conditions the operation was recorded in:
    // its workplane, the edited variable values, and no recording.
    const RecorderSuspend suspended;
    const CoordinateSystemScope placement(
        node.frame ? CoordinateSystem(node.frame->origin, node.frame->x_axis, node.frame->y_axis) : CoordinateSystem());
    outputs = occt_guard([&] { return executor(params, inputs, scalars); });
    if (static_cast<int>(outputs.size()) != node.output_count && !(value_output && outputs.empty())) {
      throw RuntimeError("executor returned " + std::to_string(outputs.size()) + " output(s); the operation recorded " +
                         std::to_string(node.output_count));
    }
  } catch (const std::exception& e) {
    raise_recompute_error(node, e);
  }
  return outputs;
}

}  // namespace

void Session::mark_dirty(const std::vector<std::string>& node_ids) {
  for (const std::string& id : node_ids) {
    NodeState& state = state_of(id);
    if (state.status == NodeStatus::Clean)
      state.status = NodeStatus::Dirty;
  }
}

NodeStatus Session::status(std::string_view node_id) const {
  return state_of(node_id).status;
}

std::exception_ptr Session::failure(std::string_view node_id) const {
  return state_of(node_id).error;
}

std::vector<std::string> Session::dirty_nodes() const {
  std::vector<std::string> out;
  for (const NodePtr& node : graph_.nodes()) {
    if (state_of(node->node_id).status != NodeStatus::Clean)
      out.push_back(node->node_id);
  }
  return out;
}

const std::vector<Shape>* Session::memo_find(const std::string& key) {
  const auto found = memo_index_.find(key);
  if (found == memo_index_.end())
    return nullptr;
  memo_.splice(memo_.begin(), memo_, found->second);  // most recently used first
  return &memo_.front().second;
}

void Session::memo_insert(const std::string& key, const std::vector<Shape>& outputs) {
  if (options_.memo_capacity == 0)
    return;
  if (const auto found = memo_index_.find(key); found != memo_index_.end()) {
    found->second->second = outputs;
    memo_.splice(memo_.begin(), memo_, found->second);
    return;
  }
  memo_.emplace_front(key, outputs);
  memo_index_[key] = memo_.begin();
  while (memo_.size() > options_.memo_capacity) {
    memo_index_.erase(memo_.back().first);
    memo_.pop_back();
  }
}

RecomputeReport Session::recompute(const RecomputeOptions& options) {
  RecomputeReport report;
  std::exception_ptr first_error;
  const AmbientBindingsScope ambient(&bindings_);

  // Insertion order is a topological order: a node is always added after the nodes it consumes.
  for (const NodePtr& node : graph_.nodes()) {
    NodeState& state = state_of(node->node_id);
    if (state.status == NodeStatus::Clean)
      continue;

    const bool blocked = std::any_of(node->bindings.begin(), node->bindings.end(), [this](const InputBinding& b) {
      if (b.external())
        return false;
      const NodeStatus s = state_of(b.node_id).status;
      return s == NodeStatus::Failed || s == NodeStatus::Blocked;
    });
    if (blocked) {
      state.status = NodeStatus::Blocked;
      report.blocked.push_back(node->node_id);
      continue;
    }

    try {
      ScalarValues scalars;
      const Value params = evaluate_node_params(*node, bindings_, scalars);
      const std::string key = node_key(*node, params);

      if (key == state.key) {
        state.status = NodeStatus::Clean;
        state.error = nullptr;
        report.unchanged.push_back(node->node_id);
        continue;
      }
      if (const std::vector<Shape>* known = memo_find(key)) {
        state.outputs = *known;
        state.key = key;
        state.status = NodeStatus::Clean;
        state.error = nullptr;
        attach_outputs(node, state.outputs, node->op.rfind("make_select_", 0) == 0);
        report.memoized.push_back(node->node_id);
        report.changed.push_back(node->node_id);
        continue;
      }

      const Executor executor = registry_->find(node->op);
      if (!executor)
        raise_missing_executor(*node);

      std::vector<OpInput> inputs;
      inputs.reserve(node->bindings.size());
      std::size_t external = 0;
      for (const InputBinding& binding : node->bindings) {
        if (binding.external()) {
          inputs.push_back(OpInput{state.externals.at(external++).shape, binding.role});
        } else {
          const std::vector<Shape>& produced = state_of(binding.node_id).outputs;
          inputs.push_back(OpInput{produced.at(static_cast<std::size_t>(binding.output_slot)), binding.role});
        }
      }

      std::vector<Shape> outputs = run_executor(*node, executor, params, inputs, scalars, state.value_output);
      state.outputs = std::move(outputs);
      state.key = key;
      state.status = NodeStatus::Clean;
      state.error = nullptr;
      attach_outputs(node, state.outputs, node->op.rfind("make_select_", 0) == 0);
      memo_insert(key, state.outputs);
      report.executed.push_back(node->node_id);
      report.changed.push_back(node->node_id);
    } catch (const std::exception& e) {
      state.status = NodeStatus::Failed;
      state.error = std::current_exception();
      if (!first_error)
        first_error = state.error;
      report.failed.push_back(NodeFailure{node->node_id, node->op, e.what(), state.error});
    }
  }
  if (options.throw_on_error && first_error)
    std::rethrow_exception(first_error);
  return report;
}

}  // namespace scad::reactive
