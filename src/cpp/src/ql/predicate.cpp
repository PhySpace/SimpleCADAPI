#include "scad/ql/predicate.hpp"

#include <algorithm>
#include <cstdint>
#include <set>
#include <variant>

#include "scad/core/error.hpp"
#include "scad/ql/compare.hpp"
#include "text.hpp"

namespace scad::ql {

namespace pred {

// ---- the compiled form ------------------------------------------------------------------------
// A predicate tree flattened in pre-order.  Every node records the size of its
// subtree, so and/or/not walk their children without a parent pointer.
struct TagNode {
  std::string text;  // the exact tag, or the prefix of a wildcard
  bool wildcard = false;
  bool matchable = true;  // an exact pattern that is not a valid tag name matches nothing
  TagScope scope = TagScope::Effective;
};
struct OperationNode {
  std::vector<std::string> names;  // the accepted spellings of the operation
  std::string event;
  bool any_event = true;
};
struct RoleNode {
  std::string role;
  bool output = false;  // result_roles instead of origin_roles
};
struct SourceNode {
  std::string expected;
  bool by_binding = false;  // evidence field source_binding_id, else source_topo_id
};
struct MetaNode {
  MetadataPath path;
  CompareOp op = CompareOp::Eq;
  std::string op_text;
  Value expected;
};
struct PropertyNode {
  PropertyPath path;
  CompareOp op = CompareOp::Eq;
  std::string op_text;
  Value expected;
};
struct GeomTypeNode {  // curve_type / surface_type payloads: the kernel type, not a looked-up property
  std::string expected;
};
enum class Logic : unsigned char { And, Or, Not };
struct LogicNode {
  Logic logic = Logic::And;
};

struct Node {
  std::uint32_t span = 1;
  std::variant<TagNode, OperationNode, RoleNode, SourceNode, MetaNode, PropertyNode, GeomTypeNode, LogicNode> payload;
};
using Program = std::vector<Node>;

// ---- schema -----------------------------------------------------------------------------------------
struct KindSchema {
  std::string_view kind;
  std::set<std::string_view> required;
  std::set<std::string_view> optional;
};

const std::vector<KindSchema>& schemas() {
  static const std::vector<KindSchema> table = {
      {"tag", {"pattern"}, {"scope"}},
      {"operation_event", {"op"}, {"event"}},
      {"origin_role", {"role"}, {}},
      {"output_role", {"role"}, {}},
      {"source_binding", {"source_binding_id"}, {}},
      {"source_topology", {"source_topo_id"}, {}},
      {"meta", {"path", "op", "value"}, {}},
      {"property_compare", {"path", "op", "value"}, {}},
      {"curve_type", {"value"}, {}},
      {"surface_type", {"value"}, {}},
      {"and", {}, {}},
      {"or", {}, {}},
      {"not", {}, {}},
  };
  return table;
}

bool is_logic(std::string_view kind) noexcept {
  return kind == "and" || kind == "or" || kind == "not";
}

// The sorted names of `a` that are not in `b` (Python prints sorted sets).
std::string names_missing_from(const std::set<std::string_view>& a, const std::set<std::string_view>& b,
                               const std::set<std::string_view>* also = nullptr) {
  std::vector<std::string> out;
  for (const auto name : a)
    if (b.count(name) == 0 && (also == nullptr || also->count(name) == 0))
      out.emplace_back(name);
  return text::join(out, ", ");
}

void check_schema(const std::string& kind, const Value& data) {
  const auto found =
      std::find_if(schemas().begin(), schemas().end(), [&](const KindSchema& s) { return s.kind == kind; });
  if (found == schemas().end())
    throw ValueError("unsupported predicate kind: " + kind);
  std::set<std::string_view> present;
  for (const auto& [name, item] : data.as_object())
    present.insert(name);
  const std::string missing = names_missing_from(found->required, present);
  const std::string unknown = names_missing_from(present, found->required, &found->optional);
  if (!missing.empty())
    throw ValueError("predicate '" + kind + "' is missing required data: " + missing);
  if (!unknown.empty())
    throw ValueError("predicate '" + kind + "' contains unknown data: " + unknown);
}

void check_children(const std::string& kind, std::size_t count) {
  if (kind == "not" && count != 1)
    throw ValueError("predicate 'not' requires exactly one child");
  if (!is_logic(kind) && count != 0)
    throw ValueError("predicate '" + kind + "' cannot contain children");
}

// ---- compilation --------------------------------------------------------------------------------------
std::string str_of(const Value* v, std::string_view fallback = {}) {
  if (v == nullptr)
    return std::string(fallback);
  return v->is_string() ? v->as_string() : py_str(*v);
}

// Spellings an operation answers to: "make_cut_rsolid" -> {"make_cut_rsolid", "cut"}.
struct OperationSpellings {
  std::string_view token;
  std::string_view alias;
};

OperationSpellings spellings(std::string_view raw) noexcept {
  std::string_view token = text::strip(raw);
  if (token.starts_with("op."))
    token.remove_prefix(3);
  std::string_view alias = token;
  if (alias.starts_with("make_"))
    alias.remove_prefix(5);
  for (const std::string_view suffix : {"_rsolid", "_rshape", "_rface", "_rwire", "_redge"}) {
    if (alias.ends_with(suffix)) {
      alias.remove_suffix(suffix.size());
      break;
    }
  }
  return {token, alias};
}

bool shares_a_spelling(std::string_view actual, const std::vector<std::string>& accepted) {
  const OperationSpellings s = spellings(actual);
  return std::any_of(accepted.begin(), accepted.end(),
                     [&](const std::string& name) { return name == s.token || name == s.alias; });
}

Node compile_leaf(const std::string& kind, const Value& data) {
  const auto get = [&](std::string_view name) { return data.find(name); };
  Node node;
  if (kind == "tag") {
    TagNode tag_node;
    std::string pattern = str_of(get("pattern"));
    tag_node.scope = normalize_tag_scope(str_of(get("scope"), "effective"));
    if (pattern.ends_with('*')) {
      pattern.pop_back();
      tag_node.wildcard = true;
    } else {
      tag_node.matchable = is_normalized_tag(pattern);
    }
    tag_node.text = std::move(pattern);
    node.payload = std::move(tag_node);
  } else if (kind == "operation_event") {
    OperationNode op_node;
    const std::string operation = str_of(get("op"));  // the spellings are views into it
    const OperationSpellings s = spellings(operation);
    op_node.names.emplace_back(s.token);
    if (s.alias != s.token)
      op_node.names.emplace_back(s.alias);
    op_node.event = str_of(get("event"), "*");
    op_node.any_event = op_node.event == "*";
    node.payload = std::move(op_node);
  } else if (kind == "origin_role" || kind == "output_role") {
    node.payload = RoleNode{str_of(get("role")), kind == "output_role"};
  } else if (kind == "source_binding" || kind == "source_topology") {
    const bool by_binding = kind == "source_binding";
    node.payload = SourceNode{str_of(get(by_binding ? "source_binding_id" : "source_topo_id")), by_binding};
  } else if (kind == "meta") {
    std::string op_text = str_of(get("op"));
    node.payload = MetaNode{MetadataPath(str_of(get("path"))), parse_compare_op(op_text), op_text, *get("value")};
  } else if (kind == "property_compare") {
    std::string op_text = str_of(get("op"));
    node.payload = PropertyNode{PropertyPath(str_of(get("path"))), parse_compare_op(op_text), op_text, *get("value")};
  } else {  // curve_type / surface_type: a type name compared with geom.type
    node.payload = GeomTypeNode{text::upper(str_of(get("value")))};
  }
  return node;
}

// ---- evaluation ----------------------------------------------------------------------------------------
const Value& null_value() {
  static const Value none;
  return none;
}

// Does any value under track[plural] (or, failing a list, track[singular]) satisfy `accept`?
template <class Accept>
bool any_track_value(const Value& track, std::string_view plural, std::string_view singular, Accept&& accept) {
  const auto check = [&](const Value& v) {
    if (v.is_string())
      return accept(std::string_view(v.as_string()));
    const std::string rendered = py_str(v);
    return accept(std::string_view(rendered));
  };
  const Value* many = track.find(plural);
  if (many != nullptr && many->is_array()) {
    const auto& items = many->as_array();
    return std::any_of(items.begin(), items.end(), check);
  }
  const Value* one = track.find(singular);
  return one != nullptr && !one->is_null() && check(*one);
}

struct Evaluator {
  const Program& program;
  std::size_t at;
  const Shape& shape;
  const EvalContext& ctx;

  bool operator()(const TagNode& n) const {
    if (n.wildcard) {
      const std::vector<std::string> tags = shape.list_tags(n.scope);
      return std::any_of(tags.begin(), tags.end(), [&](const std::string& t) { return t.starts_with(n.text); });
    }
    return n.matchable && shape.has_tag(n.text, n.scope);
  }

  bool operator()(const OperationNode& n) const {
    const Value* track = shape.metadata().find("track");
    if (track == nullptr || !track->is_object())
      return false;
    bool named = false;
    for (const std::string_view field : {"op", "operation"}) {
      const Value* actual = track->find(field);
      if (actual == nullptr || actual->is_null())
        continue;
      named = named || shares_a_spelling(actual->is_string() ? actual->as_string() : py_str(*actual), n.names);
    }
    if (!named)
      return false;
    if (n.any_event) {
      return any_track_value(*track, "events", "event", [](std::string_view) { return true; });
    }
    return any_track_value(*track, "events", "event", [&](std::string_view e) { return e == n.event; });
  }

  bool operator()(const RoleNode& n) const {
    const Value* track = shape.metadata().find("track");
    if (track == nullptr || !track->is_object())
      return false;
    const std::string_view plural = n.output ? "result_roles" : "origin_roles";
    const std::string_view singular = n.output ? "result_role" : "origin_role";
    return any_track_value(*track, plural, singular, [&](std::string_view r) { return r == n.role; });
  }

  bool operator()(const SourceNode& n) const {
    const std::string_view field = n.by_binding ? "source_binding_id" : "source_topo_id";
    for (const TagBinding& binding : shape.local_bindings()) {
      const Value* found = binding.evidence->data.find(field);
      if (found == nullptr) {
        if (n.expected.empty())
          return true;
        continue;
      }
      if (found->is_string() ? found->as_string() == n.expected : py_str(*found) == n.expected)
        return true;
    }
    return false;
  }

  bool operator()(const MetaNode& n) const {
    const Value* found = n.path.find(shape.metadata());
    return compare(found != nullptr ? *found : null_value(), n.op, n.op_text, n.expected);
  }

  bool operator()(const PropertyNode& n) const {
    const std::optional<Value> actual = n.path.lookup(shape, ctx);
    return actual.has_value() && compare(*actual, n.op, n.op_text, n.expected);
  }

  bool operator()(const GeomTypeNode& n) const {
    const auto type = geom_type(shape);
    return type.has_value() && *type == n.expected;
  }

  bool operator()(const LogicNode& n) const {
    const std::size_t end = at + program[at].span;
    std::size_t child = at + 1;
    switch (n.logic) {
      case Logic::And:
        for (; child < end; child += program[child].span)
          if (!run(program, child, shape, ctx))
            return false;
        return true;
      case Logic::Or:
        for (; child < end; child += program[child].span)
          if (run(program, child, shape, ctx))
            return true;
        return false;
      case Logic::Not:
        return !run(program, child, shape, ctx);
    }
    return false;
  }

  static bool run(const Program& program, std::size_t at, const Shape& shape, const EvalContext& ctx) {
    return std::visit(Evaluator{program, at, shape, ctx}, program[at].payload);
  }
};

}  // namespace pred

struct Predicate::Impl {
  std::string kind;
  Value data;
  std::vector<Predicate> children;
  pred::Program program;
};

Predicate::Predicate(std::string kind, Value data, std::vector<Predicate> children) {
  if (data.is_null())
    data = Value::object();
  if (!data.is_object())
    throw ValueError("predicate data must be an object");
  pred::check_schema(kind, data);
  pred::check_children(kind, children.size());

  auto impl = std::make_shared<Impl>();
  if (pred::is_logic(kind)) {
    pred::LogicNode logic{kind == "and" ? pred::Logic::And : (kind == "or" ? pred::Logic::Or : pred::Logic::Not)};
    pred::Node head;
    head.payload = logic;
    impl->program.push_back(std::move(head));
    for (const Predicate& child : children)
      impl->program.insert(impl->program.end(), child.impl_->program.begin(), child.impl_->program.end());
    impl->program.front().span = static_cast<std::uint32_t>(impl->program.size());
  } else {
    impl->program.push_back(pred::compile_leaf(kind, data));
  }
  impl->kind = std::move(kind);
  impl->data = std::move(data);
  impl->children = std::move(children);
  impl_ = std::move(impl);
}

const std::string& Predicate::kind() const noexcept {
  return impl_->kind;
}
const Value& Predicate::data() const noexcept {
  return impl_->data;
}
const std::vector<Predicate>& Predicate::children() const noexcept {
  return impl_->children;
}

bool Predicate::matches(const Shape& shape, const EvalContext& ctx) const {
  return pred::Evaluator::run(impl_->program, 0, shape, ctx);
}

bool Predicate::matches(const Shape& shape) const {
  const EvalContext ctx;
  return matches(shape, ctx);
}

Value Predicate::to_value() const {
  Value out = Value::object();
  out.set("kind", impl_->kind);
  out.set("data", impl_->data);
  Value children = Value::array();
  for (const Predicate& child : impl_->children)
    children.push_back(child.to_value());
  out.set("children", std::move(children));
  return out;
}

Predicate Predicate::from_value(const Value& payload) {
  if (!payload.is_object())
    throw ValueError("predicate payload must be an object");
  for (const auto& [name, item] : payload.as_object())
    if (name != "kind" && name != "data" && name != "children")
      throw ValueError("predicate payload contains unknown fields");

  const Value* kind = payload.find("kind");
  const Value* data = payload.find("data");
  const Value* children = payload.find("children");
  if (kind == nullptr || !kind->is_string() || kind->as_string().empty())
    throw ValueError("predicate kind must be a non-empty string");
  if (data != nullptr && !data->is_object())
    throw ValueError("predicate data must be an object");
  if (children != nullptr && !children->is_array())
    throw ValueError("predicate children must be an array");

  const std::string& name = kind->as_string();
  const Value empty_data = Value::object();
  pred::check_schema(name, data != nullptr ? *data : empty_data);
  const std::size_t count = children != nullptr ? children->size() : 0;
  if ((name == "and" || name == "or") && count == 0)
    throw ValueError("predicate '" + name + "' requires at least one child");
  pred::check_children(name, count);

  std::vector<Predicate> parsed;
  if (children != nullptr)
    for (const Value& child : children->as_array())
      parsed.push_back(from_value(child));
  return Predicate(name, data != nullptr ? *data : empty_data, std::move(parsed));
}

bool Predicate::operator==(const Predicate& other) const {
  if (impl_ == other.impl_)
    return true;
  return impl_->kind == other.impl_->kind && values_equal(impl_->data, other.impl_->data) &&
         impl_->children == other.impl_->children;
}

// ---- factories ----------------------------------------------------------------------------------------------
namespace {

Value object_of(std::initializer_list<Value::Member> members) {
  Value out = Value::object();
  for (const auto& [name, item] : members)
    out.set(name, item);
  return out;
}

std::string non_empty(std::string_view raw, const char* name) {
  const std::string stripped(text::strip(raw));
  if (stripped.empty())
    throw ValueError(std::string(name) + " must be a non-empty string");
  return stripped;
}

Predicate compare_predicate(const char* kind, std::string_view path, std::string_view op, Value expected) {
  return Predicate(
      kind,
      object_of({{"path", std::string(path)}, {"op", std::string(text::strip(op))}, {"value", std::move(expected)}}));
}

}  // namespace

Predicate tag(std::string_view pattern, TagScope scope) {
  const std::string stripped(text::strip(pattern));
  if (stripped.empty())
    throw ValueError("pattern must be non-empty");
  if (stripped.find('*') != std::string::npos && !stripped.ends_with('*'))
    throw ValueError("only trailing '*' wildcard is supported");
  return Predicate("tag", object_of({{"pattern", stripped}, {"scope", std::string(to_string(scope))}}));
}

Predicate tag(std::string_view pattern, std::string_view scope) {
  return tag(pattern, normalize_tag_scope(scope));
}

Predicate meta(std::string_view path, std::string_view op_text, Value expected) {
  return compare_predicate("meta", path, op_text, std::move(expected));
}

Predicate prop(std::string_view path, std::string_view op_text, Value expected) {
  return compare_predicate("property_compare", path, op_text, std::move(expected));
}

Predicate curve_type(std::string_view kind) {
  return prop("geom.type", "==", Value(text::upper(kind)));
}
Predicate surface_type(std::string_view kind) {
  return prop("geom.type", "==", Value(text::upper(kind)));
}

Predicate and_(std::vector<Predicate> predicates) {
  return Predicate("and", Value::object(), std::move(predicates));
}
Predicate or_(std::vector<Predicate> predicates) {
  return Predicate("or", Value::object(), std::move(predicates));
}

Predicate not_(Predicate predicate) {
  std::vector<Predicate> children;
  children.push_back(std::move(predicate));
  return Predicate("not", Value::object(), std::move(children));
}

Predicate operation_event(std::string_view op_name, std::string_view event) {
  return Predicate("operation_event",
                   object_of({{"op", non_empty(op_name, "op_name")}, {"event", non_empty(event, "event")}}));
}

Predicate origin_role(std::string_view role_name) {
  return Predicate("origin_role", object_of({{"role", non_empty(role_name, "role_name")}}));
}

Predicate output_role(std::string_view role_name) {
  return Predicate("output_role", object_of({{"role", text::lower(non_empty(role_name, "role_name"))}}));
}

Predicate source_binding(std::string_view binding_id) {
  return Predicate("source_binding", object_of({{"source_binding_id", non_empty(binding_id, "binding_id")}}));
}

Predicate source_topology(std::string_view topo_id) {
  return Predicate("source_topology", object_of({{"source_topo_id", non_empty(topo_id, "topo_id")}}));
}

Predicate role(std::string_view role_name) {
  return tag("role." + std::string(role_name) + ".*");
}

}  // namespace scad::ql
