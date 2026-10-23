#include "scad/reactive/expr_graph.hpp"

#include <algorithm>
#include <unordered_set>

#include "scad/reactive/param_path.hpp"

namespace scad::reactive {

ScalarPtr ExpressionGraph::get(std::string_view expr_id) const {
  const auto found = index_.find(std::string(expr_id));
  return found == index_.end() ? nullptr : nodes_[found->second];
}

ScalarPtr ExpressionGraph::register_expr(const Scalar& value) { return register_expr(lift_scalar(value)); }

ScalarPtr ExpressionGraph::register_expr(const ScalarPtr& expr) {
  std::vector<ScalarPtr> staged;
  std::unordered_map<std::string, std::size_t> staged_index;
  std::unordered_set<const ScalarNode*> validated;

  std::vector<const ScalarPtr*> stack{&expr};
  while (!stack.empty()) {
    const ScalarPtr& node = *stack.back();
    stack.pop_back();
    const ScalarPtr* existing = nullptr;
    if (const auto s = staged_index.find(node->expr_id()); s != staged_index.end()) {
      existing = &staged[s->second];
    } else if (const auto g = index_.find(node->expr_id()); g != index_.end()) {
      existing = &nodes_[g->second];
    }
    if (existing != nullptr) {
      if (expr_signature(**existing) != expr_signature(*node)) {
        throw ValueError("Expression id '" + node->expr_id() + "' is already registered by a different node");
      }
    } else {
      staged_index.emplace(node->expr_id(), staged.size());
      staged.push_back(node);
    }
    if (!validated.insert(node.get()).second) continue;
    if (node->type() == NodeType::Expr) {
      const auto& args = static_cast<const Expr&>(*node).args();
      for (auto it = args.rbegin(); it != args.rend(); ++it) stack.push_back(&*it);
    }
  }
  expr->inference();  // throws before anything is committed
  for (ScalarPtr& node : staged) {
    index_.emplace(node->expr_id(), nodes_.size());
    nodes_.push_back(std::move(node));
  }
  return expr;
}

namespace {

Value node_payload(const ScalarNode& node) {
  Value out = Value::object();
  out.set("expr_id", node.expr_id());
  switch (node.type()) {
    case NodeType::Const:
      out.set("kind", "const");
      out.set("value", static_cast<const Const&>(node).value());
      break;
    case NodeType::Var: {
      const auto& v = static_cast<const Var&>(node);
      out.set("kind", "var");
      out.set("name", v.name());
      out.set("default", v.default_value());
      if (v.comment() && !v.comment()->empty()) out.set("comment", *v.comment());
      if (v.tolerance()) out.set("tolerance", v.tolerance()->to_value());
      if (v.unit()) out.set("unit", unit_to_payload(*v.unit()));
      if (v.tolerance_unit()) out.set("tolerance_unit", unit_to_payload(*v.tolerance_unit()));
      break;
    }
    case NodeType::Expr: {
      const auto& e = static_cast<const Expr&>(node);
      out.set("kind", "expr");
      out.set("op", e.op());
      Value args = Value::array();
      for (const ScalarPtr& arg : e.args()) args.push_back(arg->expr_id());
      out.set("args", args);
      break;
    }
  }
  return out;
}

}  // namespace

Value ExpressionGraph::to_value() const {
  std::vector<const ScalarNode*> ordered;
  std::unordered_set<std::string> seen;
  struct Frame {
    const ScalarNode* node;
    std::size_t next;
  };
  for (const ScalarPtr& root : nodes_) {
    if (seen.count(root->expr_id()) != 0) continue;
    seen.insert(root->expr_id());
    std::vector<Frame> stack{{root.get(), 0}};
    while (!stack.empty()) {
      Frame& frame = stack.back();
      const ScalarNode* node = frame.node;
      const std::size_t arity = node->type() == NodeType::Expr ? static_cast<const Expr&>(*node).args().size() : 0;
      if (frame.next < arity) {
        const ScalarNode* child = static_cast<const Expr&>(*node).args()[frame.next++].get();
        if (seen.insert(child->expr_id()).second) stack.push_back({child, 0});
        continue;
      }
      ordered.push_back(node);
      stack.pop_back();
    }
  }
  Value nodes = Value::array();
  for (const ScalarNode* node : ordered) nodes.push_back(node_payload(*node));
  Value out = Value::object();
  out.set("nodes", std::move(nodes));
  return out;
}

namespace {

double payload_number(const Value& value, std::string_view label) {
  if (!value.is_number()) throw TypeError(std::string(label) + " must be a real number");
  return value.as_double();
}

}  // namespace

ExpressionGraph ExpressionGraph::from_value(const Value& payload) {
  if (!payload.is_object()) throw TypeError("Expression graph payload must be an object");
  const Value* raw = payload.find("nodes");
  Value empty = Value::array();
  if (raw == nullptr) raw = &empty;
  if (!raw->is_array()) throw TypeError("Expression graph 'nodes' must be an array");

  std::vector<std::pair<std::string, const Value*>> payloads;
  std::unordered_map<std::string, const Value*> by_id;
  for (const Value& node : raw->as_array()) {
    if (!node.is_object()) throw TypeError("Expression graph nodes must be objects");
    const Value* id = node.find("expr_id");
    if (id == nullptr) throw ValueError("Expression graph node is missing 'expr_id'");
    if (!id->is_string() || id->as_string().empty()) throw ValueError("Expression graph node id must be non-empty");
    if (!by_id.emplace(id->as_string(), &node).second) {
      throw ValueError("Duplicate expression node id '" + id->as_string() + "'");
    }
    payloads.emplace_back(id->as_string(), &node);
  }

  ExpressionGraph graph;
  std::unordered_map<std::string, ScalarPtr> built;
  std::unordered_set<std::string> visiting;

  // Recursive on purpose: payload depth is the depth of the expression.
  struct Builder {
    const std::unordered_map<std::string, const Value*>& by_id;
    std::unordered_map<std::string, ScalarPtr>& built;
    std::unordered_set<std::string>& visiting;
    ExpressionGraph& graph;

    ScalarPtr build(const std::string& id) {
      if (const auto it = built.find(id); it != built.end()) return it->second;
      if (visiting.count(id) != 0) throw ValueError("Expression graph contains a cycle at '" + id + "'");
      const auto found = by_id.find(id);
      if (found == by_id.end()) throw ValueError("Unknown expression dependency '" + id + "'");
      const Value& node = *found->second;
      visiting.insert(id);
      const Value* kind = node.find("kind");
      ScalarPtr expr;
      if (kind != nullptr && kind->is_string() && kind->as_string() == "const") {
        const Value* value = node.find("value");
        if (value == nullptr) throw ValueError("Constant expression node '" + id + "' is missing 'value'");
        expr = Const::make(payload_number(*value, "value"), id);
      } else if (kind != nullptr && kind->is_string() && kind->as_string() == "var") {
        const Value* name = node.find("name");
        const Value* def = node.find("default");
        if (name == nullptr || def == nullptr) {
          throw ValueError("Variable expression node '" + id + "' requires 'name' and 'default'");
        }
        if (!name->is_string()) throw ValueError("Variable name must be a non-empty string");
        VarSpec spec;
        spec.name = name->as_string();
        spec.default_value = payload_number(*def, "Variable default");
        spec.expr_id = id;
        if (const Value* comment = node.find("comment"); comment != nullptr && !comment->is_null()) {
          if (!comment->is_string()) throw ValueError("Variable comment must be a string when provided");
          spec.comment = comment->as_string();
        }
        if (const Value* tol = node.find("tolerance"); tol != nullptr && !tol->is_null()) {
          spec.tolerance = DimensionTolerance::from_value(*tol);
        }
        if (const Value* unit = node.find("unit")) spec.unit = unit_from_payload(*unit);
        if (const Value* unit = node.find("tolerance_unit")) spec.tolerance_unit = unit_from_payload(*unit);
        expr = Var::make(std::move(spec));
      } else if (kind != nullptr && kind->is_string() && kind->as_string() == "expr") {
        const Value* op = node.find("op");
        if (op == nullptr) throw ValueError("Derived expression node '" + id + "' is missing 'op'");
        const Value* raw_args = node.find("args");
        Value none = Value::array();
        if (raw_args == nullptr) raw_args = &none;
        if (!raw_args->is_array()) throw TypeError("Expression node '" + id + "' field 'args' must be an array");
        for (const Value& arg : raw_args->as_array()) {
          if (!arg.is_string()) throw TypeError("Expression node '" + id + "' dependencies must be string ids");
        }
        if (!op->is_string()) throw TypeError("Expression op must be a string");
        std::vector<ScalarPtr> args;
        for (const Value& arg : raw_args->as_array()) args.push_back(build(arg.as_string()));
        expr = Expr::make(op->as_string(), std::move(args), id);
      } else {
        throw ValueError("Unknown expression node kind: " + (kind ? kind->dump() : std::string("None")));
      }
      visiting.erase(id);
      graph.index_.emplace(id, graph.nodes_.size());
      graph.nodes_.push_back(expr);
      built.emplace(id, expr);
      return expr;
    }
  };
  Builder builder{by_id, built, visiting, graph};
  for (const auto& [id, node] : payloads) builder.build(id);
  for (const ScalarPtr& node : graph.nodes_) node->inference();
  return graph;
}

bool is_discrete_param_name(std::string_view key) {
  std::string lower(key);
  std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  const auto ends_with = [&lower](std::string_view suffix) {
    return lower.size() >= suffix.size() && lower.compare(lower.size() - suffix.size(), suffix.size(), suffix) == 0;
  };
  if (ends_with("_indices")) return true;
  static constexpr std::string_view kNames[] = {"edge_count",   "face_count",   "geo_selector", "removed_face_count",
                                                "profile_count", "profile",      "count",        "degree",
                                                "multiplicities", "output_count", "periodic",     "tag_binding"};
  return std::find(std::begin(kNames), std::end(kNames), lower) != std::end(kNames);
}

namespace {

Value numbers_as_floats(const Value& value) {
  if (value.is_int()) return Value(static_cast<double>(value.as_int()));
  if (value.is_array()) {
    Value out = value.is_tuple() ? Value::tuple() : Value::array();
    for (const Value& item : value.as_array()) out.push_back(numbers_as_floats(item));
    return out;
  }
  if (value.is_object()) {
    Value out = Value::object();
    for (const auto& [key, item] : value.as_object()) out.set(key, numbers_as_floats(item));
    return out;
  }
  return value;
}

// A list of expression references is as long as the list of numbers it describes.
void pad_like(Value& exprs, const Value& numeric) {
  if (exprs.is_array() && numeric.is_array()) {
    Value::Array& items = exprs.as_array();
    items.resize(numeric.size());
    for (std::size_t i = 0; i < items.size(); ++i) pad_like(items[i], numeric.as_array()[i]);
  } else if (exprs.is_object() && numeric.is_object()) {
    for (auto& [key, item] : exprs.as_object()) {
      if (const Value* match = numeric.find(key)) pad_like(item, *match);
    }
  }
}

}  // namespace

CanonicalParams canonicalize_params(const Value& params, const SymbolicParams& symbolic, ExpressionGraph& graph) {
  CanonicalParams out{Value::object(), Value::object()};
  if (params.is_object()) {
    for (const auto& [key, value] : params.as_object()) {
      out.numeric.set(key, is_discrete_param_name(key) ? value : numbers_as_floats(value));
    }
  }
  for (const auto& [name, scalar] : symbolic) {
    const ParamPath path = ParamPath::parse(name);
    if (is_discrete_param_name(path.key)) continue;
    const ScalarPtr expr = graph.register_expr(scalar);
    const Value* present = find_param(out.numeric, path);
    if (present == nullptr || !present->is_number()) set_param(out.numeric, path, Value(scalar.value()));
    Value ref = Value::object();
    ref.set("expr_id", expr->expr_id());
    set_param(out.exprs, path, std::move(ref));
  }
  pad_like(out.exprs, out.numeric);
  return out;
}

std::vector<ScalarPtr> referenced_expressions(const Value& param_exprs, const ExpressionGraph& graph) {
  std::vector<ScalarPtr> found;
  std::unordered_set<std::string> seen;
  struct Visitor {
    const ExpressionGraph& graph;
    std::vector<ScalarPtr>& found;
    std::unordered_set<std::string>& seen;
    void visit(const Value& value) {
      if (value.is_object()) {
        const Value* id = value.find("expr_id");
        if (value.size() == 1 && id != nullptr && id->is_string()) {
          ScalarPtr expr = graph.get(id->as_string());
          if (!expr) throw KeyError("unknown expression id '" + id->as_string() + "'");
          if (seen.insert(id->as_string()).second) found.push_back(std::move(expr));
          return;
        }
        for (const auto& member : value.as_object()) visit(member.second);
      } else if (value.is_array()) {
        for (const Value& item : value.as_array()) visit(item);
      }
    }
  };
  Visitor visitor{graph, found, seen};
  if (param_exprs.is_object()) {
    for (const auto& member : param_exprs.as_object()) visitor.visit(member.second);
  }
  return found;
}

}  // namespace scad::reactive
