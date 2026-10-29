#include "scad/reactive/graph.hpp"
#include "scad/reactive/node_registry.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <deque>
#include <iomanip>
#include <random>
#include <sstream>

#include "scad/reactive/digest.hpp"
#include "scad/reactive/errors.hpp"

namespace scad::reactive {

namespace {

std::string& producer_version_slot() {
  static std::string version = "0+cpp";
  return version;
}

Value capabilities_payload() {
  Value out = Value::object();
  for (const char* flag : {"selection_ref_strategies", "geo_select_nodes", "selector_hint_fallback", "display_payload",
                           "sketch_constraints", "sketch_solve_snapshots", "product_semantics", "assembly_graph"}) {
    out.set(flag, true);
  }
  out.set("topology_delta_summary", false);
  out.set("topology_delta_entries", true);
  out.set("durable_topology_parent_refs", true);
  out.set("operation_output_roles", true);
  out.set("scalar_field_graph", false);
  out.set("expression_graph", true);
  out.set("semantic_tag_bindings", true);
  out.set("tag_binding_schema", "1.0");
  out.set("source_mapping", true);
  out.set("source_mapping_schema", "1.0");
  return out;
}

std::string random_graph_id() {
  std::random_device device;
  std::mt19937_64 engine((static_cast<std::uint64_t>(device()) << 32) ^ device());
  std::ostringstream out;
  out << "graph_" << std::hex << std::setw(8) << std::setfill('0') << (engine() & 0xffffffffULL);
  return out.str();
}

std::vector<std::string> input_ids(const OperationNode& node) {
  std::vector<std::string> ids;
  ids.reserve(node.inputs.size());
  for (const NodePtr& input : node.inputs)
    ids.push_back(input->node_id);
  return ids;
}

template <class T, class ToValue>
bool optional_values_equal(const std::optional<T>& a, const std::optional<T>& b, ToValue to_value) {
  if (a.has_value() != b.has_value())
    return false;
  return !a || to_value(*a) == to_value(*b);
}

}  // namespace

// ---------------------------------------------------------------------------
// Closure
// ---------------------------------------------------------------------------

OperationNode::~OperationNode() {
  std::vector<NodePtr> pending = std::move(inputs);
  while (!pending.empty()) {
    NodePtr node = std::move(pending.back());
    pending.pop_back();
    // Sole owner: nobody else can observe the node, so taking its inputs is safe.
    if (node && node.use_count() == 1) {
      auto& owned = const_cast<OperationNode&>(*node);
      for (NodePtr& input : owned.inputs)
        pending.push_back(std::move(input));
      owned.inputs.clear();
    }
  }
}

bool same_node_content(const OperationNode& a, const OperationNode& b) {
  if (&a == &b)
    return true;
  if (a.node_id != b.node_id || a.op != b.op || a.params != b.params || a.param_exprs != b.param_exprs ||
      a.context != b.context || a.output_count != b.output_count || a.tags != b.tags || a.graph_id != b.graph_id ||
      a.source != b.source) {
    return false;
  }
  if (!optional_values_equal(a.semantic_delta, b.semantic_delta, [](const SemanticDelta& d) { return to_value(d); }) ||
      !optional_values_equal(a.topo_delta, b.topo_delta, [](const TopoDelta& d) { return to_value(d); })) {
    return false;
  }
  return input_ids(a) == input_ids(b) && a.bindings == b.bindings;
}

std::vector<NodePtr> upstream_closure(const std::vector<NodePtr>& roots,
                                      const std::function<bool(const NodePtr&)>& stop_at) {
  std::vector<NodePtr> order;
  std::unordered_map<std::string, NodePtr> seen;
  // (node, inputs_done): a node is emitted once all its inputs have been.
  std::vector<std::pair<NodePtr, bool>> stack;
  for (auto it = roots.rbegin(); it != roots.rend(); ++it)
    stack.emplace_back(*it, false);
  while (!stack.empty()) {
    auto [node, inputs_done] = std::move(stack.back());
    stack.pop_back();
    if (inputs_done) {
      order.push_back(std::move(node));
      continue;
    }
    if (const auto known = seen.find(node->node_id); known != seen.end()) {
      if (!same_node_content(*known->second, *node))
        throw StaleLineageError(node->node_id);
      continue;
    }
    if (stop_at && stop_at(node))
      continue;
    seen.emplace(node->node_id, node);
    stack.emplace_back(node, true);
    for (auto it = node->inputs.rbegin(); it != node->inputs.rend(); ++it)
      stack.emplace_back(*it, false);
  }
  return order;
}

// ---------------------------------------------------------------------------
// Graph
// ---------------------------------------------------------------------------

OperationGraph::OperationGraph(std::string graph_id, std::optional<std::string> ns)
    : graph_id_(graph_id.empty() ? random_graph_id() : std::move(graph_id)), namespace_(std::move(ns)) {
  if (namespace_ && namespace_->empty())
    throw ValueError("graph namespace must be a non-empty string");
}

std::string OperationGraph::namespaced(std::string_view prefix) const {
  return namespace_ ? *namespace_ + "_" + std::string(prefix) : std::string(prefix);
}

std::string OperationGraph::allocate_node_id(std::string_view prefix) {
  const std::string qualified = namespaced(prefix);
  while (true) {
    char suffix[16];
    std::snprintf(suffix, sizeof suffix, "_%08zx", ++counter_);
    std::string node_id = qualified + suffix;
    if (nodes_.count(node_id) == 0)
      return node_id;
  }
}

NodePtr OperationGraph::add_node(NodeSpec spec) {
  std::string nid = spec.node_id.empty() ? allocate_node_id() : std::move(spec.node_id);
  if (nodes_.count(nid) != 0)
    throw ValueError("node id '" + nid + "' already exists in graph");
  for (const NodePtr& input : spec.inputs) {
    if (!input->graph_id.empty() && input->graph_id != graph_id_) {
      throw ValueError("input node '" + input->node_id + "' belongs to graph '" + input->graph_id +
                       "', active graph is '" + graph_id_ + "'");
    }
    const auto owned = nodes_.find(input->node_id);
    if (owned == nodes_.end())
      throw ValueError("input node '" + input->node_id + "' is not part of this graph");
    if (owned->second != input) {
      throw ValueError("input node '" + input->node_id + "' is not the node owned by this graph");
    }
  }

  auto node = std::make_shared<OperationNode>();
  node->node_id = nid;
  node->op = std::move(spec.op);
  node->params = std::move(spec.params);
  node->param_exprs = std::move(spec.param_exprs);
  node->inputs = std::move(spec.inputs);
  node->bindings = std::move(spec.bindings);
  node->context = std::move(spec.context);
  node->output_count = spec.output_count;
  if (spec.semantic_delta)
    node->semantic_delta = bind_semantic_delta(*spec.semantic_delta, graph_id_, nid);
  if (spec.topo_delta)
    node->topo_delta = bind_topo_delta(*spec.topo_delta, graph_id_, nid);
  node->tags = std::move(spec.tags);
  node->graph_id = graph_id_;
  node->source = std::move(spec.source);
  node->expressions = std::move(spec.expressions);
  node->symbolic = std::move(spec.symbolic);
  node->frame = std::move(spec.frame);
  node->source_index = spec.source_index;
  NodePtr result = std::move(node);
  insert(result);
  return result;
}

NodePtr OperationGraph::adopt(const NodePtr& node) {
  const auto known = [this](const NodePtr& item) {
    const auto owned = nodes_.find(item->node_id);
    if (owned == nodes_.end())
      return false;
    if (!same_node_content(*owned->second, *item))
      throw StaleLineageError(item->node_id);
    return true;
  };
  for (const NodePtr& item : upstream_closure({node}, known)) {
    if (item->graph_id != graph_id_) {
      throw ValueError("node '" + item->node_id + "' belongs to graph '" + item->graph_id + "', this graph is '" +
                       graph_id_ + "'");
    }
    insert(item);
  }
  return nodes_.at(node->node_id);
}

void OperationGraph::insert(NodePtr node) {
  // Callers guarantee a new id whose inputs are already in the graph.
  for (const NodePtr& input : node->inputs) {
    edges_.emplace_back(input->node_id, node->node_id);
    adj_[input->node_id].push_back(node->node_id);
    radj_[node->node_id].push_back(input->node_id);
  }
  nodes_.emplace(node->node_id, node);
  order_.push_back(std::move(node));
}

NodePtr OperationGraph::get_node(std::string_view node_id) const {
  const auto found = nodes_.find(std::string(node_id));
  return found == nodes_.end() ? nullptr : found->second;
}

std::vector<std::string> OperationGraph::upstream_nodes(std::string_view node_id) const {
  const auto found = radj_.find(std::string(node_id));
  return found == radj_.end() ? std::vector<std::string>{} : found->second;
}

std::vector<std::string> OperationGraph::downstream_nodes(std::string_view node_id) const {
  const auto found = adj_.find(std::string(node_id));
  return found == adj_.end() ? std::vector<std::string>{} : found->second;
}

std::vector<NodePtr> OperationGraph::root_nodes() const {
  std::vector<NodePtr> out;
  for (const NodePtr& node : order_) {
    const auto found = radj_.find(node->node_id);
    if (found == radj_.end() || found->second.empty())
      out.push_back(node);
  }
  return out;
}

std::vector<NodePtr> OperationGraph::leaf_nodes() const {
  std::vector<NodePtr> out;
  for (const NodePtr& node : order_) {
    const auto found = adj_.find(node->node_id);
    if (found == adj_.end() || found->second.empty())
      out.push_back(node);
  }
  return out;
}

std::vector<std::string> OperationGraph::kahn_order() const {
  // Iterative, so long chains do not recurse.  Nodes on a cycle never reach
  // in-degree zero and are left out.
  std::unordered_map<std::string, std::size_t> in_degree;
  for (const NodePtr& node : order_)
    in_degree.emplace(node->node_id, 0);
  for (const auto& edge : edges_)
    ++in_degree[edge.second];
  std::deque<std::string> queue;
  for (const NodePtr& node : order_) {
    if (in_degree[node->node_id] == 0)
      queue.push_back(node->node_id);
  }
  std::vector<std::string> order;
  while (!queue.empty()) {
    std::string id = std::move(queue.front());
    queue.pop_front();
    order.push_back(id);
    const auto found = adj_.find(id);
    if (found == adj_.end())
      continue;
    for (const std::string& child : found->second) {
      if (--in_degree[child] == 0)
        queue.push_back(child);
    }
  }
  return order;
}

bool OperationGraph::is_dag() const {
  return kahn_order().size() == order_.size();
}

std::vector<NodePtr> OperationGraph::topological_order() const {
  const std::vector<std::string> ids = kahn_order();
  if (ids.size() != order_.size())
    throw ValueError("graph contains a cycle");
  std::vector<NodePtr> out;
  out.reserve(ids.size());
  for (const std::string& id : ids)
    out.push_back(nodes_.at(id));
  return out;
}

// ---------------------------------------------------------------------------
// Display payload
// ---------------------------------------------------------------------------

namespace {

bool starts_with(std::string_view text, std::string_view prefix) {
  return text.substr(0, prefix.size()) == prefix;
}

bool contains(std::string_view text, std::string_view part) {
  return text.find(part) != std::string_view::npos;
}

bool one_of(std::string_view op, std::initializer_list<std::string_view> names) {
  return std::find(names.begin(), names.end(), op) != names.end();
}

std::string display_category(std::string_view op) {
  if (starts_with(op, "make_select_"))
    return "selection";
  if (one_of(op, {"cut", "union", "intersect", "make_cut_rsolid", "make_union_rsolid", "make_intersect_rsolid"}))
    return "boolean";
  if (one_of(op, {"translate", "rotate", "mirror", "make_translate_rshape", "make_rotate_rshape", "make_scale_rsolid",
                  "make_transform_rsolid", "make_mirror_rshape"})) {
    return "transform";
  }
  if (one_of(op, {"linear_pattern", "radial_pattern"}))
    return "pattern";
  if (one_of(op, {"extrude", "revolve", "loft", "sweep", "helical_sweep", "make_extrude_rsolid", "make_revolve_rsolid",
                  "make_loft_rsolid", "make_sweep_rsolid", "make_twisted_sweep_rsolid", "make_extrude_taper_rsolid",
                  "make_extrude_until_rsolid", "make_sweep_multisection_rsolid"})) {
    return "feature";
  }
  if (one_of(op, {"fillet", "chamfer", "shell", "make_fillet_rsolid", "make_chamfer_rsolid", "make_shell_rsolid",
                  "make_offset_rsolid", "make_draft_rsolid"})) {
    return "detail";
  }
  if (starts_with(op, "make_")) {
    for (const std::string_view token : {"_wire", "_edge", "_face", "point"}) {
      if (contains(op, token))
        return "profile";
    }
    return "primitive";
  }
  return "operation";
}

std::string display_label(std::string_view op) {
  std::string label(op);
  std::replace(label.begin(), label.end(), '_', ' ');
  if (starts_with(label, "make "))
    label.erase(0, 5);
  std::string out;
  bool word_start = true;
  for (const char c : label) {
    if (c == ' ') {
      if (!out.empty() && out.back() != ' ')
        out += ' ';
      word_start = true;
    } else {
      out += word_start ? static_cast<char>(std::toupper(static_cast<unsigned char>(c)))
                        : static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
      word_start = false;
    }
  }
  while (!out.empty() && out.back() == ' ')
    out.pop_back();
  return out;
}

// Python's str() of a parameter value.
std::string py_text(const Value& value, bool nested) {
  if (value.is_null())
    return "None";
  if (value.is_bool())
    return value.as_bool() ? "True" : "False";
  if (value.is_int())
    return std::to_string(value.as_int());
  if (value.is_double())
    return py_float_repr(value.as_double());
  if (value.is_string())
    return nested ? py_str_repr(value.as_string()) : value.as_string();
  std::string out;
  if (value.is_array()) {
    const bool tuple = value.is_tuple();
    out = tuple ? "(" : "[";
    bool first = true;
    for (const Value& item : value.as_array()) {
      out += (first ? "" : ", ") + py_text(item, true);
      first = false;
    }
    if (tuple && value.size() == 1)
      out += ",";
    return out + (tuple ? ")" : "]");
  }
  out = "{";
  bool first = true;
  for (const auto& [key, item] : value.as_object()) {
    out += (first ? "" : ", ") + py_str_repr(key) + ": " + py_text(item, true);
    first = false;
  }
  return out + "}";
}

std::string display_summary(std::string_view op, const Value& params) {
  static constexpr std::string_view kIgnored[] = {"selected_edges",
                                                  "selected_faces",
                                                  "selected_edge_node_ids",
                                                  "selected_face_node_ids",
                                                  "selected_edge_indices",
                                                  "selected_face_indices",
                                                  "geo_selector"};
  std::vector<std::string> parts;
  if (params.is_object()) {
    for (const auto& [key, value] : params.as_object()) {
      if (std::find(std::begin(kIgnored), std::end(kIgnored), key) != std::end(kIgnored))
        continue;
      if (value.is_double()) {
        char buf[48];
        std::snprintf(buf, sizeof buf, "%.4g", value.as_double());
        parts.push_back(key + "=" + buf);
      } else if (value.is_array() && value.size() > 4) {
        parts.push_back(key + "[" + std::to_string(value.size()) + "]");
      } else {
        parts.push_back(key + "=" + py_text(value, false));
      }
      if (parts.size() == 3)
        break;
    }
  }
  if (parts.empty())
    return display_label(op);
  std::string out;
  for (std::size_t i = 0; i < parts.size(); ++i)
    out += (i == 0 ? "" : ", ") + parts[i];
  return out;
}

}  // namespace

void set_producer_version(std::string version) {
  producer_version_slot() = std::move(version);
}

// canonical_source_payload: `local_path` is a runtime-only hint, and a source outside the detected
// project (an absolute path) is written as unresolved.
Value canonical_source_payload(const Value& source) {
  if (!source.is_object())
    return source;
  Value out = Value::object();
  const Value* kind = source.find("path_kind");
  const bool absolute = kind != nullptr && kind->is_string() && kind->as_string() == "absolute";
  for (const auto& [key, value] : source.as_object()) {
    if (key == "local_path")
      continue;
    if (absolute && key == "path")
      out.set(key, Value());
    else if (absolute && key == "path_kind")
      out.set(key, "unresolved");
    else
      out.set(key, value);
  }
  return out;
}

Value node_display_payload(std::string_view op, const Value& params) {
  std::size_t selection_count = 0;
  if (const Value* edges = params.find("selected_edges"); edges != nullptr && edges->is_array()) {
    selection_count = edges->size();
  } else if (const Value* faces = params.find("selected_faces"); faces != nullptr && faces->is_array()) {
    selection_count = faces->size();
  }
  Value out = Value::object();
  out.set("label", display_label(op));
  out.set("category", display_category(op));
  out.set("summary", display_summary(op, params));
  if (selection_count != 0)
    out.set("selection_count", static_cast<std::int64_t>(selection_count));
  return out;
}

// ---------------------------------------------------------------------------
// Serialization
// ---------------------------------------------------------------------------

Value OperationGraph::to_value() const {
  Value nodes = Value::array();
  for (const NodePtr& node : topological_order()) {
    Value item = Value::object();
    item.set("node_id", node->node_id);
    item.set("op", node->op);
    item.set("params", node->params);
    Value inputs = Value::array();
    for (const NodePtr& input : node->inputs)
      inputs.push_back(input->node_id);
    item.set("inputs", std::move(inputs));
    item.set("output_count", node->output_count);
    Value tags = Value::array();
    for (const std::string& tag : node->tags)
      tags.push_back(tag);  // std::set: sorted
    item.set("tags", std::move(tags));
    item.set("display", node_display_payload(node->op, node->params));
    if (node->source)
      item.set("source", canonical_source_payload(*node->source));
    if (node->param_exprs.size() != 0)
      item.set("param_exprs", node->param_exprs);
    if (node->context && node->context->size() != 0)
      item.set("context", *node->context);
    if (node->semantic_delta)
      item.set("semantic_delta", scad::to_value(*node->semantic_delta));
    if (node->topo_delta)
      item.set("topo_delta", scad::to_value(*node->topo_delta));
    nodes.push_back(std::move(item));
  }
  Value edges = Value::array();
  for (const auto& [from, to] : edges_) {
    Value pair = Value::array();
    pair.push_back(from);
    pair.push_back(to);
    edges.push_back(std::move(pair));
  }
  Value out = Value::object();
  out.set("schema_version", std::string(kGraphSchemaVersion));
  out.set("producer_version", producer_version_slot());
  out.set("capabilities", capabilities_payload());
  out.set("graph_id", graph_id_);
  out.set("nodes", std::move(nodes));
  out.set("edges", std::move(edges));
  return out;
}

namespace {

// json.dumps: ensure_ascii strings, Python float text, `indent` spaces per level.
void json_string(const std::string& text, std::string& out) {
  out += '"';
  for (std::size_t i = 0; i < text.size();) {
    const auto lead = static_cast<unsigned char>(text[i]);
    std::uint32_t code = lead;
    std::size_t length = 1;
    if (lead >= 0xf0) {
      code = lead & 0x07u;
      length = 4;
    } else if (lead >= 0xe0) {
      code = lead & 0x0fu;
      length = 3;
    } else if (lead >= 0xc0) {
      code = lead & 0x1fu;
      length = 2;
    }
    for (std::size_t k = 1; k < length && i + k < text.size(); ++k) {
      code = (code << 6) | (static_cast<unsigned char>(text[i + k]) & 0x3fu);
    }
    i += length;
    char buf[16];
    switch (code) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      case '\b':
        out += "\\b";
        break;
      case '\f':
        out += "\\f";
        break;
      default:
        if (code >= 0x20 && code < 0x7f) {
          out += static_cast<char>(code);
        } else if (code >= 0x10000) {
          const std::uint32_t v = code - 0x10000;
          std::snprintf(buf, sizeof buf, "\\u%04x\\u%04x", 0xd800 + (v >> 10), 0xdc00 + (v & 0x3ff));
          out += buf;
        } else {
          std::snprintf(buf, sizeof buf, "\\u%04x", code);
          out += buf;
        }
    }
  }
  out += '"';
}

void json_value(const Value& value, int indent, int depth, std::string& out) {
  const auto newline = [&](int level) {
    if (indent <= 0)
      return;
    out += '\n';
    out.append(static_cast<std::size_t>(level * indent), ' ');
  };
  if (value.is_null())
    out += "null";
  else if (value.is_bool())
    out += value.as_bool() ? "true" : "false";
  else if (value.is_int())
    out += std::to_string(value.as_int());
  else if (value.is_double()) {
    const double d = value.as_double();
    out += std::isnan(d) ? "NaN" : std::isinf(d) ? (d < 0 ? "-Infinity" : "Infinity") : py_float_repr(d);
  } else if (value.is_string())
    json_string(value.as_string(), out);
  else if (value.is_array()) {
    if (value.size() == 0) {
      out += "[]";
      return;
    }
    out += '[';
    bool first = true;
    for (const Value& item : value.as_array()) {
      if (!first)
        out += indent > 0 ? "," : ", ";
      first = false;
      newline(depth + 1);
      json_value(item, indent, depth + 1, out);
    }
    newline(depth);
    out += ']';
  } else {
    if (value.size() == 0) {
      out += "{}";
      return;
    }
    out += '{';
    bool first = true;
    for (const auto& [key, item] : value.as_object()) {
      if (!first)
        out += indent > 0 ? "," : ", ";
      first = false;
      newline(depth + 1);
      json_string(key, out);
      out += ": ";
      json_value(item, indent, depth + 1, out);
    }
    newline(depth);
    out += '}';
  }
}

}  // namespace

std::string OperationGraph::to_json(int indent) const {
  std::string out;
  json_value(to_value(), indent, 0, out);
  return out;
}

OperationGraph OperationGraph::from_value(const Value& payload, bool strict, const ExpressionGraph* expressions,
                                          const FrameGraph* frames) {
  if (!payload.is_object())
    throw ValueError("graph payload must be an object");
  if (strict) {
    const Value* version = payload.find("schema_version");
    if (version == nullptr || !version->is_string() || version->as_string() != kGraphSchemaVersion) {
      throw ValueError("unsupported graph schema_version " + (version ? version->dump() : std::string("None")));
    }
  }
  const Value* raw_nodes = payload.find("nodes");
  const Value* raw_edges = payload.find("edges");
  Value empty = Value::array();
  if (raw_nodes == nullptr)
    raw_nodes = &empty;
  if (raw_edges == nullptr)
    raw_edges = &empty;
  if (!raw_nodes->is_array() || !raw_edges->is_array())
    throw ValueError("graph nodes and edges must be arrays");
  const Value* id = payload.find("graph_id");
  OperationGraph graph(id != nullptr && id->is_string() ? id->as_string() : std::string{});

  struct Pending {
    const Value* data;
    std::string node_id;
    std::vector<std::string> inputs;
  };
  std::vector<Pending> pending;
  std::set<std::pair<std::string, std::string>> declared_edges;
  std::set<std::string> known;
  for (const Value& nd : raw_nodes->as_array()) {
    if (!nd.is_object())
      throw ValueError("graph node entries must be objects");
    const Value* node_id = nd.find("node_id");
    const Value* op = nd.find("op");
    if (node_id == nullptr || !node_id->is_string() || node_id->as_string().empty()) {
      throw ValueError("graph node_id must be a non-empty string");
    }
    const std::string& nid = node_id->as_string();
    if (op == nullptr || !op->is_string() || op->as_string().empty()) {
      throw ValueError("graph node '" + nid + "' op must be a non-empty string");
    }
    if (const Value* count = nd.find("output_count"); count != nullptr && (!count->is_int() || count->as_int() < 0)) {
      throw ValueError("graph node '" + nid + "' output_count must be a non-negative integer");
    }
    Pending item{&nd, nid, {}};
    if (const Value* inputs = nd.find("inputs")) {
      bool ok = inputs->is_array();
      if (ok) {
        for (const Value& input : inputs->as_array())
          ok = ok && input.is_string();
      }
      if (!ok)
        throw ValueError("graph node '" + nid + "' inputs must be string ids");
      for (const Value& input : inputs->as_array())
        item.inputs.push_back(input.as_string());
      if (std::set<std::string>(item.inputs.begin(), item.inputs.end()).size() != item.inputs.size()) {
        throw ValueError("graph node '" + nid + "' contains duplicate inputs");
      }
    }
    for (const std::string& input : item.inputs)
      declared_edges.emplace(input, nid);
    if (!known.insert(nid).second)
      throw ValueError("node id '" + nid + "' already exists in graph");
    pending.push_back(std::move(item));
  }

  std::set<std::pair<std::string, std::string>> serialized_edges;
  for (const Value& edge : raw_edges->as_array()) {
    const bool well_formed =
        edge.is_array() && edge.size() == 2 && edge.as_array()[0].is_string() && edge.as_array()[1].is_string();
    if (!well_formed) {
      if (strict)
        throw ValueError("malformed graph edge entry: " + edge.dump());
      continue;
    }
    const std::string& src = edge.as_array()[0].as_string();
    const std::string& dst = edge.as_array()[1].as_string();
    if (known.count(src) == 0 || known.count(dst) == 0) {
      if (strict)
        throw ValueError("graph edge references missing node(s): '" + src + "' -> '" + dst + "'");
      continue;
    }
    if (!serialized_edges.emplace(src, dst).second && strict) {
      throw ValueError("duplicate graph edge: '" + src + "' -> '" + dst + "'");
    }
  }
  if (strict && serialized_edges != declared_edges)
    throw ValueError("graph edges do not match node input declarations");

  // Add each node once everything it consumes is in.
  std::vector<bool> placed(pending.size(), false);
  std::size_t remaining = pending.size();
  while (remaining > 0) {
    bool progressed = false;
    for (std::size_t i = 0; i < pending.size(); ++i) {
      if (placed[i])
        continue;
      const Pending& item = pending[i];
      std::vector<NodePtr> inputs;
      bool ready = true;
      for (const std::string& input : item.inputs) {
        if (NodePtr node = graph.get_node(input)) {
          inputs.push_back(std::move(node));
        } else if (known.count(input) != 0) {
          ready = false;
        } else if (const NodePtr foreign = find_registered_node(graph.graph_id(), input)) {
          // A node of another cell's session: a restored cell builds on what was restored before it.
          inputs.push_back(graph.adopt(foreign));
        } else if (strict) {
          throw ValueError("graph node '" + item.node_id + "' references missing input node(s): " + input);
        }
      }
      if (!ready)
        continue;
      const Value& nd = *item.data;
      NodeSpec spec;
      spec.op = nd.find("op")->as_string();
      if (const Value* params = nd.find("params"); params != nullptr && params->is_object())
        spec.params = *params;
      if (const Value* exprs = nd.find("param_exprs"); exprs != nullptr && exprs->is_object())
        spec.param_exprs = *exprs;
      spec.node_id = item.node_id;
      if (const Value* count = nd.find("output_count"))
        spec.output_count = static_cast<int>(count->as_int());
      if (const Value* ctx = nd.find("context"); ctx != nullptr && !ctx->is_null())
        spec.context = *ctx;
      if (const Value* tags = nd.find("tags"); tags != nullptr && tags->is_array()) {
        for (const Value& tag : tags->as_array()) {
          if (tag.is_string())
            spec.tags.insert(tag.as_string());
        }
      }
      if (const Value* source = nd.find("source"); source != nullptr && !source->is_null())
        spec.source = *source;
      if (const Value* delta = nd.find("semantic_delta"); delta != nullptr && delta->is_object()) {
        spec.semantic_delta = semantic_delta_from_value(*delta);
      }
      if (const Value* delta = nd.find("topo_delta"); delta != nullptr && delta->is_object()) {
        spec.topo_delta = topo_delta_from_value(*delta);
      }
      if (expressions != nullptr && !spec.param_exprs.is_null())
        spec.expressions = referenced_expressions(spec.param_exprs, *expressions);
      if (frames != nullptr) {
        if (const FrameNode* frame = frames->get("frame:" + item.node_id))
          spec.frame = *frame;
      }
      for (const NodePtr& input : inputs)
        spec.bindings.push_back(InputBinding{input->node_id, 0, {}});
      spec.inputs = std::move(inputs);
      graph.add_node(std::move(spec));
      placed[i] = true;
      --remaining;
      progressed = true;
    }
    if (!progressed) {
      if (strict)
        throw ValueError("graph contains a cycle");
      break;
    }
  }
  return graph;
}

}  // namespace scad::reactive
