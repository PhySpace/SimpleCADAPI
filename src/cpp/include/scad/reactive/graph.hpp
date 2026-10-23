// The operation DAG: port of OperationNode / OperationGraph / upstream_closure
// from simplecadapi/topology/model.py.
//
// A node is an immutable record of one operation: its name, parameters (numbers
// as evaluated when it was recorded, plus the symbolic scalars they came from),
// the nodes it consumed and the topology delta it produced.  Nodes are shared
// (`std::shared_ptr<const OperationNode>`), so a graph, a session and a closure
// walk can all hold the same node.  The graph itself is a plain value-like
// container and is not thread-safe.
#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/reactive/expr.hpp"
#include "scad/reactive/expr_graph.hpp"
#include "scad/reactive/frame.hpp"
#include "scad/topo/delta.hpp"

namespace scad::reactive {

inline constexpr std::string_view kGraphSchemaVersion = "2.0";

// What a node was given as its i-th input: an output slot of an upstream node,
// or (empty node_id) a value the recording did not produce -- an imported
// shape, say -- which the session keeps as a constant.
struct InputBinding {
  std::string node_id;
  int output_slot = 0;
  std::string role;  // "body", "tool", ...

  bool external() const noexcept { return node_id.empty(); }
  bool operator==(const InputBinding&) const = default;
};

struct OperationNode;
using NodePtr = std::shared_ptr<const OperationNode>;

struct OperationNode {
  std::string node_id;
  std::string op;
  Value params = Value::object();       // numbers as recorded (canonical units)
  Value param_exprs = Value::object();  // the same nesting with {"expr_id": ...} leaves
  std::vector<NodePtr> inputs;          // the distinct nodes this one consumes, first use first
  std::vector<InputBinding> bindings;   // every input in call order (a node may feed several)
  std::optional<Value> context;         // workplane snapshot
  int output_count = 1;
  std::optional<SemanticDelta> semantic_delta;
  std::optional<TopoDelta> topo_delta;
  std::set<std::string> tags;
  std::string graph_id;
  std::optional<Value> source;

  // Carried along but not part of the node's identity (compare=False in Python).
  std::vector<ScalarPtr> expressions;  // the expressions param_exprs refers to
  SymbolicParams symbolic;             // path -> scalar: what makes the node reactive
  std::optional<FrameNode> frame;
  // Where a selection was found in its source (index and count among the source's sub-shapes of
  // its kind): lets a recompute re-find a pick by identity when the geometry moved.  Not part of
  // the recording the SDK defines, so never serialized.
  std::optional<std::pair<std::int64_t, std::int64_t>> source_index;

  OperationNode() = default;
  OperationNode(const OperationNode&) = default;
  OperationNode(OperationNode&&) noexcept = default;
  OperationNode& operator=(const OperationNode&) = default;
  OperationNode& operator=(OperationNode&&) noexcept = default;
  // Releases a chain of single-owner inputs iteratively.  The implicit destructor
  // recurses once per node, which overflows the stack on a long modelling history.
  ~OperationNode();
};

// Whether two node objects record the same operation: every identity field
// equal and the inputs the same ids in the same order.  Shallow on purpose.
bool same_node_content(const OperationNode& first, const OperationNode& second);

// `roots` and every node upstream of them, inputs first.  Iterative
// depth-first post-order, deterministic; a second object under a seen id is
// skipped when same_node_content holds and throws StaleLineageError otherwise.
// Nodes for which `stop_at` is true are neither returned nor walked through.
std::vector<NodePtr> upstream_closure(const std::vector<NodePtr>& roots,
                                      const std::function<bool(const NodePtr&)>& stop_at = {});

// Everything add_node takes.
struct NodeSpec {
  std::string op;
  Value params = Value::object();
  Value param_exprs = Value::object();
  std::vector<NodePtr> inputs;
  std::vector<InputBinding> bindings;
  std::string node_id;  // empty: allocated
  int output_count = 1;
  std::optional<SemanticDelta> semantic_delta;
  std::optional<TopoDelta> topo_delta;
  std::optional<Value> context;
  std::set<std::string> tags;
  std::optional<Value> source;
  std::vector<ScalarPtr> expressions;
  SymbolicParams symbolic;
  std::optional<FrameNode> frame;
  std::optional<std::pair<std::int64_t, std::int64_t>> source_index;
};

class OperationGraph {
 public:
  // A random id when `graph_id` is empty.  `ns` prefixes every id the graph
  // allocates ("<ns>_node_00000001"); ValueError when it is given but empty.
  explicit OperationGraph(std::string graph_id = {}, std::optional<std::string> ns = std::nullopt);

  const std::string& graph_id() const noexcept { return graph_id_; }
  const std::optional<std::string>& ns() const noexcept { return namespace_; }

  std::string namespaced(std::string_view prefix) const;
  // The next deterministic node id ("node_00000001"); skips ids already taken.
  std::string allocate_node_id(std::string_view prefix = "node");

  // ---- construction ------------------------------------------------------
  // Add a node and wire its input edges.  ValueError for a taken id or an
  // input that is not this graph's node.
  NodePtr add_node(NodeSpec spec);

  // Make `node` and everything upstream of it part of this graph.  Ids
  // already present must hold the same content (StaleLineageError otherwise);
  // nodes must carry this graph's id.  Returns this graph's node for that id.
  NodePtr adopt(const NodePtr& node);

  // ---- queries -----------------------------------------------------------
  NodePtr get_node(std::string_view node_id) const;
  const std::vector<NodePtr>& nodes() const noexcept { return order_; }  // insertion order
  std::size_t node_count() const noexcept { return order_.size(); }
  const std::vector<std::pair<std::string, std::string>>& edges() const noexcept { return edges_; }
  std::size_t edge_count() const noexcept { return edges_.size(); }

  std::vector<std::string> upstream_nodes(std::string_view node_id) const;
  std::vector<std::string> downstream_nodes(std::string_view node_id) const;
  std::vector<NodePtr> root_nodes() const;
  std::vector<NodePtr> leaf_nodes() const;

  bool is_dag() const;
  // Execution order; ValueError when the graph has a cycle.
  std::vector<NodePtr> topological_order() const;

  // ---- serialization (OperationGraph.to_dict / from_dict) --------------------
  Value to_value() const;
  std::string to_json(int indent = 2) const;
  // Restores nodes and edges; topology/semantic deltas are not restored.
  // `expressions` / `frames`, when given, are what the nodes' expression and frame records are
  // looked up in (a restored node carries the expressions its parameters refer to, and its frame).
  static OperationGraph from_value(const Value& payload, bool strict = true, const class ExpressionGraph* expressions = nullptr,
                                   const class FrameGraph* frames = nullptr);

 private:
  void insert(NodePtr node);
  std::vector<std::string> kahn_order() const;

  std::string graph_id_;
  std::optional<std::string> namespace_;
  std::vector<NodePtr> order_;
  std::unordered_map<std::string, NodePtr> nodes_;
  std::vector<std::pair<std::string, std::string>> edges_;
  std::unordered_map<std::string, std::vector<std::string>> adj_, radj_;
  std::size_t counter_ = 0;
};

// The producer_version the serialized graph carries (the SDK package version); set once by the host.
void set_producer_version(std::string version);

// The portable form of a node's `source` stored in graph JSON (canonical_source_payload).
Value canonical_source_payload(const Value& source);

// The "display" payload of a node in the serialized graph.
Value node_display_payload(std::string_view op, const Value& params);

}  // namespace scad::reactive
