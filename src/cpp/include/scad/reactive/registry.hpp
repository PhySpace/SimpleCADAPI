// The executor registry: how the reactive engine re-runs an operation without
// knowing any operator.
//
// Every operator area (ops_geometry, ops_features, surface, std, ...) that
// wants its operations to recompute after a parameter edit registers, once, a
// function per recorded operation name.  The function gets what the recorder
// stored -- the parameters (symbolic numbers already replaced by their current
// values), the inputs (the upstream outputs as they are *now*) and the current
// value of every symbolic scalar -- and returns the operation's outputs.
//
// HOW AN OPERATOR AUTHOR HOOKS IN
//
//   1. Record the operation with scad/reactive/record.hpp: every scalar argument goes
//      through the builder, which evaluates it (the active session's edits apply),
//      stores the number and keeps the symbolic Scalar:
//
//          OperationBuilder rec("make_box_rsolid");
//          const double w = rec.scalar("width", width);   // width: a Scalar argument
//          ...                                            // rec.input(shape, "body"), rec.param(...)
//          Solid result = build_box(w, ...);
//          rec.record({result});
//
//      (A scalar inside an array parameter is named by a path: scalar_at("size", 1, y)
//      records "size[1]".  Without the builder, fill an OpRecord yourself:
//      `params` = the numbers, `symbolic` = (path, Scalar) for each symbolic one.)
//
//   2. Register a function that rebuilds the result from the stored values.
//      Read numbers from `params` -- they are current -- and shapes from
//      `inputs`, which are in the order the operation recorded them:
//
//          void register_executors(scad::reactive::ExecutorRegistry& registry) {
//            registry.add("make_box_rsolid", [](const Value& params, const std::vector<OpInput>&,
//                                               const ScalarValues&) {
//              return std::vector<Shape>{make_box_rsolid(params.find("width")->as_double(), ...)};
//            });
//          }
//
//      The executor runs with recording suspended; it must not record.  It
//      should be a pure function of its arguments (the engine memoizes on
//      them) and must return exactly the number of outputs the operation
//      recorded.  Throw a scad::Error as the operator would; the engine
//      reports it against the node and blocks only the nodes downstream.
//
//   3. Call your `register_executors(ExecutorRegistry::global())` from your
//      Python binding's `bind_<area>(...)` (or from any code that runs before
//      the first recompute).  Do NOT rely on a static initializer in a static
//      library: the linker drops translation units nothing references.
//
// An operation with no registered executor still records, replays in the
// model graph and answers impact queries; it only cannot be *re*computed, and
// the engine says so by name.
#pragma once

#include <functional>
#include <map>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive {

// Current value of each symbolic scalar of the operation, by the parameter
// path it was recorded under ("width", "size[1]").  Values are in the
// canonical CAD units, exactly the numbers `params` holds at those paths.
using ScalarValues = std::map<std::string, double, std::less<>>;

// params, inputs, scalars -> outputs.
using Executor = std::function<std::vector<Shape>(const Value& params, const std::vector<OpInput>& inputs,
                                                  const ScalarValues& scalars)>;

// A table from operation name to executor.  Thread-safe: registration and
// lookup take an internal lock; a looked-up Executor is a copy.
class ExecutorRegistry {
 public:
  // `builtins`: also register the executors for the selection operations
  // ("make_select_r<kind>") the session records for picked faces and edges.
  explicit ExecutorRegistry(bool builtins = true);
  ExecutorRegistry(const ExecutorRegistry&) = delete;
  ExecutorRegistry& operator=(const ExecutorRegistry&) = delete;

  // The process-wide registry operator areas register into.
  static ExecutorRegistry& global();

  // ValueError when `op` already has an executor (two areas claiming one name).
  void add(std::string op, Executor executor);
  // Add or overwrite.
  void replace(std::string op, Executor executor);
  bool remove(std::string_view op);

  bool contains(std::string_view op) const;
  // The executor of `op`, or an empty function.
  Executor find(std::string_view op) const;
  std::vector<std::string> operations() const;  // sorted

 private:
  mutable std::mutex mutex_;
  std::map<std::string, Executor, std::less<>> table_;
};

// Shorthand for ExecutorRegistry::global().add(...).
void register_executor(std::string op, Executor executor);

}  // namespace scad::reactive
