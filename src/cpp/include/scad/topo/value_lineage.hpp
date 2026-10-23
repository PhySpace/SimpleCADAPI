// Recording an operation on values that are not shapes (Sketch, Part, Connector, ...).
//
// The value carries the node that made it in its runtime dictionary ("graph.node_id", ...), the way a shape
// does.  An operator that takes values reads their lineage into the record and gives its result the lineage of
// the node it recorded, so the graph links them without the caller saying how.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/topo/recorder.hpp"

namespace scad {

// The lineage a value holds, if a recorder gave it one.
template <class V>
std::optional<ValueLineage> value_lineage_of(const V& value) {
  const Value node = value.get_runtime("graph.node_id");
  if (!node.is_string() || node.as_string().empty()) return std::nullopt;
  ValueLineage out;
  out.node_id = node.as_string();
  if (const Value graph = value.get_runtime("graph.id"); graph.is_string()) out.graph_id = graph.as_string();
  if (const Value slot = value.get_runtime("graph.output_slot"); slot.is_int()) out.output_slot = static_cast<int>(slot.as_int());
  return out;
}

template <class V>
void attach_value_lineage(const V& value, const ValueLineage& lineage, std::string_view op) {
  value.set_runtime("graph.id", Value(lineage.graph_id));
  value.set_runtime("graph.node_id", Value(lineage.node_id));
  value.set_runtime("graph.output_slot", Value(static_cast<std::int64_t>(lineage.output_slot)));
  Value graph = Value::object();
  graph.set("graph_id", lineage.graph_id.empty() ? Value() : Value(lineage.graph_id));
  graph.set("node_id", lineage.node_id);
  graph.set("op", std::string(op));
  graph.set("output_slot", static_cast<std::int64_t>(lineage.output_slot));
  value.set_metadata("graph", std::move(graph));
}

namespace detail {
template <class V>
void collect_lineage(std::vector<ValueLineage>& out, const V& value) {
  if (auto lineage = value_lineage_of(value)) out.push_back(std::move(*lineage));
}
}  // namespace detail

// Record `record` as an operation on `inputs` that produced `output`.  Nothing happens without a recorder.
template <class Out, class... In>
void record_value_operation(const OpRecord& record, const Out& output, const In&... inputs) {
  Recorder* recorder = current_recorder();
  if (recorder == nullptr) return;
  std::vector<ValueLineage> lineages;
  (detail::collect_lineage(lineages, inputs), ...);
  if (const auto lineage = recorder->record_value_op(record, lineages)) attach_value_lineage(output, *lineage, record.op);
}

}  // namespace scad
