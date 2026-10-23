// Recording a product operation.  Private to src/product.
#pragma once

#include <string>
#include <utility>
#include <vector>

#include <memory>
#include <optional>
#include <variant>

#include "scad/core/value.hpp"
#include "scad/product/assembly.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/value_lineage.hpp"

namespace scad::product::detail {

// An operation record carrying `params`; inputs and the semantic delta are added by the caller.
inline OpRecord op_record(std::string op, Value params) {
  OpRecord record;
  record.op = std::move(op);
  record.params = std::move(params);
  return record;
}

namespace lineage {
// A product value by reference, however it is held.
template <class V>
const V& deref(const V& value) { return value; }
template <class V>
const V& deref(const std::shared_ptr<const V>& value) { return *value; }

template <class V>
void add(std::vector<ValueLineage>& out, const V& value) { scad::detail::collect_lineage(out, deref(value)); }
template <class V>
void add(std::vector<ValueLineage>& out, const std::optional<V>& value) {
  if (value) scad::detail::collect_lineage(out, *value);
}
inline void add(std::vector<ValueLineage>& out, const Item& item) {
  std::visit([&out](const auto& held) { scad::detail::collect_lineage(out, *held); }, item);
}
}  // namespace lineage

// `build()` makes the OpRecord; it only runs when something records (the cost of an
// operation nobody watches is one pointer test).  A product value is described by the parameters, so the
// record carries no shape output: the node is linked to the nodes of the value `inputs` (their lineage) and
// the `output` value takes the lineage of the node (value_lineage.hpp).
template <class Build, class Out, class... In>
void record_value(Build&& build, const Out& output, const In&... inputs) {
  Recorder* recorder = current_recorder();
  if (recorder == nullptr) return;
  std::vector<ValueLineage> lineages;
  (lineage::add(lineages, inputs), ...);
  const OpRecord record = std::forward<Build>(build)();
  if (const auto taken = recorder->record_value_op(record, lineages))
    attach_value_lineage(lineage::deref(output), *taken, record.op);
}

// As record_value, for an operation whose result is a shape.
template <class Build>
void record_shape(const Shape& output, Build&& build) {
  if (current_recorder() != nullptr) record_operation(std::forward<Build>(build)(), {output});
}

}  // namespace scad::product::detail
