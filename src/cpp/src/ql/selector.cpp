// ShapeSelector: the immutable query value, its fluent builders and its serialized form.
#include <algorithm>

#include "scad/core/error.hpp"
#include "scad/ql/compare.hpp"
#include "internal.hpp"
#include "selector_impl.hpp"
#include "text.hpp"

namespace scad::ql {

namespace {

Value count_value(std::int64_t n) {
  return Value(n);
}

void require_count(std::int64_t count, const char* message = "count must be >= 0") {
  if (count < 0)
    throw ValueError(message);
}

[[noreturn]] void missing_key(std::string_view name) {
  throw Exception(PyKind::KeyError, "'" + std::string(name) + "'");
}

std::string string_of(const Value& v) {
  return v.is_string() ? v.as_string() : py_str(v);
}

bool truthy(const Value& v) {
  if (v.is_null())
    return false;
  if (v.is_bool())
    return v.as_bool();
  if (v.is_int())
    return v.as_int() != 0;
  if (v.is_double())
    return v.as_double() != 0.0;
  if (v.is_string())
    return !v.as_string().empty();
  return v.size() != 0;
}

std::int64_t integer_of(const Value& v) {
  if (v.is_bool())
    return v.as_bool() ? 1 : 0;
  if (v.is_int())
    return v.as_int();
  if (v.is_double())
    return static_cast<std::int64_t>(v.as_double());
  if (v.is_string()) {
    try {
      return std::stoll(v.as_string());
    } catch (const std::exception&) {
      throw ValueError("invalid literal for int(): '" + v.as_string() + "'");
    }
  }
  throw TypeError("int() argument must be a string or a number, not '" + std::string(py_type_name(v)) + "'");
}

// Python dict key-set equality for the exact-fields checks of from_dict.
bool has_exactly(const Value& object, std::initializer_list<std::string_view> names) {
  if (object.size() != names.size())
    return false;
  return std::all_of(names.begin(), names.end(), [&](std::string_view n) { return object.find(n) != nullptr; });
}

const Value* object_member(const Value& payload, std::string_view name) {
  const Value* found = payload.find(name);
  return found != nullptr && found->is_object() ? found : nullptr;
}

std::vector<ShapeSelector> selectors_from(const Value& array) {
  std::vector<ShapeSelector> out;
  for (const Value& item : array.as_array())
    out.push_back(ShapeSelector::from_value(item));
  return out;
}

}  // namespace

// ---- TraversalSpec -------------------------------------------------------------------------------------------
Value TraversalSpec::to_value() const {
  Value out = Value::object();
  out.set("relation", relation);
  return out;
}

TraversalSpec TraversalSpec::from_value(const Value& payload) {
  const Value* relation = payload.find("relation");
  if (relation == nullptr)
    missing_key("relation");
  return TraversalSpec{string_of(*relation)};
}

// ---- construction -------------------------------------------------------------------------------------------------
ShapeSelector::ShapeSelector(std::string target_kind) {
  auto impl = std::make_shared<Impl>();
  impl->target_kind = std::move(target_kind);
  impl_ = std::move(impl);
}

ShapeSelector::ShapeSelector(Kind target_kind) : ShapeSelector(std::string(kind_name(target_kind))) {}

ShapeSelector::ShapeSelector(std::shared_ptr<const Impl> impl) noexcept : impl_(std::move(impl)) {}

template <class F>
ShapeSelector ShapeSelector::amended(F&& edit) const {
  auto copy = std::make_shared<Impl>(*impl_);
  std::forward<F>(edit)(*copy);
  return ShapeSelector(std::shared_ptr<const Impl>(std::move(copy)));
}

// ---- field access --------------------------------------------------------------------------------------------------
const std::string& ShapeSelector::target_kind() const noexcept {
  return impl_->target_kind;
}
const ShapeSelector* ShapeSelector::source_selector() const noexcept {
  const auto& source = impl_->source_selector;
  return source ? &*source : nullptr;
}
const std::optional<TraversalSpec>& ShapeSelector::traversal() const noexcept {
  return impl_->traversal;
}
const std::optional<Predicate>& ShapeSelector::predicate() const noexcept {
  return impl_->predicate;
}
const std::optional<Key>& ShapeSelector::order_key() const noexcept {
  return impl_->order_key;
}
const std::vector<std::pair<Key, bool>>& ShapeSelector::order_keys() const noexcept {
  return impl_->order_keys;
}
bool ShapeSelector::order_desc() const noexcept {
  return impl_->order_desc;
}
std::optional<std::int64_t> ShapeSelector::limit_count() const noexcept {
  return impl_->limit_count;
}
const std::vector<std::pair<std::string, std::int64_t>>& ShapeSelector::cardinality() const noexcept {
  return impl_->cardinality;
}
const std::optional<std::string>& ShapeSelector::source_node_id() const noexcept {
  return impl_->source_node_id;
}
std::optional<int> ShapeSelector::source_output_slot() const noexcept {
  return impl_->source_output_slot;
}
const std::optional<std::string>& ShapeSelector::set_operation() const noexcept {
  return impl_->set_operation;
}
const std::vector<ShapeSelector>& ShapeSelector::operands() const noexcept {
  return impl_->operands;
}
const std::vector<ShapeSelector>& ShapeSelector::incident_face_selectors() const noexcept {
  return impl_->incident_face_selectors;
}
bool ShapeSelector::incident_faces_distinct() const noexcept {
  return impl_->incident_faces_distinct;
}
std::optional<std::int64_t> ShapeSelector::incident_face_cardinality() const noexcept {
  return impl_->incident_face_cardinality;
}

// ---- fluent builders
// ---------------------------------------------------------------------------------------------------
ShapeSelector ShapeSelector::where(const Predicate& predicate) const {
  return amended([&](Impl& m) { m.predicate = m.predicate ? and_({*m.predicate, predicate}) : predicate; });
}

ShapeSelector ShapeSelector::order_by(const Key& sort_key, bool desc) const {
  return amended([&](Impl& m) {
    m.order_keys.emplace_back(sort_key, desc);
    m.order_key = sort_key;
    m.order_desc = desc;
  });
}

ShapeSelector ShapeSelector::from_source(std::string node_id, int output_slot) const {
  if (node_id.empty())
    throw ValueError("node_id must be a non-empty string");
  if (output_slot < 0)
    throw ValueError("output_slot must be >= 0");
  return amended([&](Impl& m) {
    m.source_node_id = std::move(node_id);
    m.source_output_slot = output_slot;
  });
}

ShapeSelector ShapeSelector::take(std::int64_t count) const {
  require_count(count);
  return amended([&](Impl& m) { m.limit_count = count; });
}

namespace {
void assert_count(std::vector<std::pair<std::string, std::int64_t>>& cardinality, const char* mode,
                  std::int64_t count) {
  for (auto& [name, existing] : cardinality) {
    if (name == mode) {
      existing = count;
      return;
    }
  }
  cardinality.emplace_back(mode, count);
}
}  // namespace

ShapeSelector ShapeSelector::exactly(std::int64_t count) const {
  require_count(count);
  return amended([&](Impl& m) { assert_count(m.cardinality, "exactly", count); });
}

ShapeSelector ShapeSelector::at_least(std::int64_t count) const {
  require_count(count);
  return amended([&](Impl& m) { assert_count(m.cardinality, "at_least", count); });
}

ShapeSelector ShapeSelector::at_most(std::int64_t count) const {
  require_count(count);
  return amended([&](Impl& m) { assert_count(m.cardinality, "at_most", count); });
}

ShapeSelector ShapeSelector::traverse(std::string_view relation, std::string_view to_kind) const {
  const std::string rel = text::lower(text::strip(relation));
  const std::string kind = text::lower(text::strip(to_kind));
  if (rel != "boundary")
    throw ValueError("unsupported traversal relation: " + rel);
  if (!detail::is_traversal_kind(kind))
    throw ValueError("unsupported traversal target kind: " + kind);
  auto impl = std::make_shared<Impl>();
  impl->target_kind = kind;
  impl->source_selector = *this;
  impl->traversal = TraversalSpec{rel};
  impl->source_node_id = impl_->source_node_id;
  impl->source_output_slot = impl_->source_output_slot;
  return ShapeSelector(std::shared_ptr<const Impl>(std::move(impl)));
}

ShapeSelector ShapeSelector::boundary(std::string_view to_kind) const {
  return traverse("boundary", to_kind);
}

ShapeSelector ShapeSelector::intersection(const ShapeSelector& other) const {
  if (impl_->target_kind != other.impl_->target_kind)
    throw ValueError("intersection operands must select the same topology kind");
  auto impl = std::make_shared<Impl>();
  impl->target_kind = impl_->target_kind;
  impl->set_operation = "intersection";
  impl->operands = {*this, other};
  return ShapeSelector(std::shared_ptr<const Impl>(std::move(impl)));
}

ShapeSelector ShapeSelector::shared_boundary(const ShapeSelector& other, std::string_view to_kind) const {
  return boundary(to_kind).intersection(other.boundary(to_kind));
}

ShapeSelector ShapeSelector::incident_to(std::vector<ShapeSelector> face_selectors, bool distinct) const {
  if (impl_->target_kind != "edge")
    throw ValueError("incident_to is only valid on an Edge selector");
  const bool all_faces = std::all_of(face_selectors.begin(), face_selectors.end(),
                                     [](const ShapeSelector& s) { return s.target_kind() == "face"; });
  if (face_selectors.empty() || !all_faces)
    throw TypeError("incident_to requires one or more Face selectors");
  return amended([&](Impl& m) {
    m.incident_face_selectors = std::move(face_selectors);
    m.incident_faces_distinct = distinct;
  });
}

ShapeSelector ShapeSelector::incident_face_count(std::int64_t exactly_count) const {
  if (impl_->target_kind != "edge")
    throw ValueError("incident_face_count is only valid on an Edge selector");
  require_count(exactly_count, "incident face count must be >= 0");
  return amended([&](Impl& m) { m.incident_face_cardinality = exactly_count; });
}

// ---- the semantic-layer seam
// -----------------------------------------------------------------------------------------------
std::optional<SelectorSource> ShapeSelector::source() const {
  const auto& node_id = impl_->source_node_id;
  if (!node_id)
    return std::nullopt;
  return SelectorSource{*node_id, impl_->source_output_slot.value_or(0)};
}

std::shared_ptr<const scad::ShapeSelector> ShapeSelector::from_source(const SelectorSource& anchor) const {
  return std::make_shared<const ShapeSelector>(from_source(anchor.node_id, anchor.output_slot));
}

SelectorPtr ShapeSelector::shared() const {
  return std::make_shared<const ShapeSelector>(*this);
}

// ---- serialization
// ------------------------------------------------------------------------------------------------------------
Value ShapeSelector::to_value() const {
  const Impl& m = *impl_;
  Value out = Value::object();
  out.set("target_kind", m.target_kind);
  out.set("order_desc", m.order_desc);
  Value card = Value::object();
  for (const auto& [name, count] : m.cardinality)
    card.set(name, count_value(count));
  out.set("cardinality", std::move(card));
  if (m.source_selector)
    out.set("source", m.source_selector->to_value());
  if (m.traversal)
    out.set("traversal", m.traversal->to_value());
  if (m.predicate)
    out.set("predicate", m.predicate->to_value());
  if (m.order_key)
    out.set("order_key", m.order_key->to_value());
  if (!m.order_keys.empty()) {
    Value keys = Value::array();
    for (const auto& [sort_key, desc] : m.order_keys) {
      Value entry = Value::object();
      entry.set("key", sort_key.to_value());
      entry.set("desc", desc);
      keys.push_back(std::move(entry));
    }
    out.set("order_keys", std::move(keys));
  }
  if (m.limit_count)
    out.set("limit", count_value(*m.limit_count));
  if (m.source_node_id) {
    out.set("source_node_id", *m.source_node_id);
    out.set("source_output_slot", m.source_output_slot.value_or(0));
  }
  if (m.set_operation) {
    Value set = Value::object();
    set.set("op", *m.set_operation);
    Value operands = Value::array();
    for (const ShapeSelector& operand : m.operands)
      operands.push_back(operand.to_value());
    set.set("operands", std::move(operands));
    out.set("set_operation", std::move(set));
  }
  if (!m.incident_face_selectors.empty()) {
    Value incident = Value::object();
    Value selectors = Value::array();
    for (const ShapeSelector& s : m.incident_face_selectors)
      selectors.push_back(s.to_value());
    incident.set("selectors", std::move(selectors));
    incident.set("distinct", m.incident_faces_distinct);
    out.set("incident_faces", std::move(incident));
  }
  if (m.incident_face_cardinality) {
    Value card_value = Value::object();
    card_value.set("exactly", count_value(*m.incident_face_cardinality));
    out.set("incident_face_cardinality", std::move(card_value));
  }
  return out;
}

namespace {

// The payload member `name`, or nullptr when it is absent or null.
const Value* present_member(const Value& data, std::string_view name) {
  const Value* found = data.find(name);
  return found != nullptr && !found->is_null() ? found : nullptr;
}

std::string required_target_kind(const Value& data) {
  const Value* found = data.find("target_kind");
  if (found == nullptr)
    missing_key("target_kind");
  return string_of(*found);
}

struct ParsedSetOperation {
  std::string op;
  std::vector<ShapeSelector> operands;
};

// {"op": "intersection", "operands": [...]}: at least two operands of the selector's own target kind.
ParsedSetOperation parse_set_operation(const Value& raw, const Value& data) {
  if (!raw.is_object())
    throw ValueError("selector set_operation must be an object");
  if (!has_exactly(raw, {"op", "operands"}))
    throw ValueError("selector set_operation has invalid fields");
  ParsedSetOperation out;
  out.op = text::lower(text::strip(string_of(*raw.find("op"))));
  if (out.op != "intersection")
    throw ValueError("unsupported selector set operation: " + out.op);
  const Value& raw_operands = *raw.find("operands");
  if (!raw_operands.is_array() || raw_operands.size() < 2)
    throw ValueError("selector intersection requires at least two operands");
  out.operands = selectors_from(raw_operands);
  const std::string kind = required_target_kind(data);
  if (std::any_of(out.operands.begin(), out.operands.end(),
                  [&](const ShapeSelector& s) { return s.target_kind() != kind; }))
    throw ValueError("selector intersection operands must match target_kind");
  return out;
}

struct ParsedIncidentFaces {
  std::vector<ShapeSelector> selectors;
  bool distinct = false;
};

// {"selectors": [...], "distinct": bool}: only valid on edge selectors, and the selectors must select faces.
ParsedIncidentFaces parse_incident_faces(const Value& raw, const Value& data) {
  if (!raw.is_object() || !has_exactly(raw, {"selectors", "distinct"}))
    throw ValueError("selector incident_faces has invalid fields");
  const Value* kind = data.find("target_kind");
  if (kind == nullptr || text::lower(string_of(*kind)) != "edge")
    throw ValueError("incident_faces is only valid for edge selectors");
  const Value& raw_selectors = *raw.find("selectors");
  if (!raw_selectors.is_array() || raw_selectors.size() == 0)
    throw ValueError("incident_faces requires one or more selectors");
  ParsedIncidentFaces out;
  out.selectors = selectors_from(raw_selectors);
  if (std::any_of(out.selectors.begin(), out.selectors.end(),
                  [](const ShapeSelector& s) { return s.target_kind() != "face"; }))
    throw ValueError("incident_faces selectors must select faces");
  out.distinct = truthy(*raw.find("distinct"));
  return out;
}

// The ordering keys: the "order_keys" list when present, else the single "order_key" with "order_desc".
// A list without a single key also sets the single key to its last entry (`order_key`).
std::vector<std::pair<Key, bool>> parse_order_keys(const Value& data, std::optional<Key>& order_key) {
  std::vector<std::pair<Key, bool>> order_keys;
  const Value* raw_keys = data.find("order_keys");
  if (raw_keys != nullptr && raw_keys->is_array()) {
    for (const Value& item : raw_keys->as_array()) {
      const Value* key_object = item.is_object() ? object_member(item, "key") : nullptr;
      if (key_object == nullptr)
        throw ValueError("selector order_keys entries must contain a key object");
      const Value* desc = item.find("desc");
      order_keys.emplace_back(Key::from_value(*key_object), desc != nullptr && truthy(*desc));
    }
    if (!order_key && !order_keys.empty())
      order_key = order_keys.back().first;
  } else if (order_key) {
    const Value* desc = data.find("order_desc");
    order_keys.emplace_back(*order_key, desc != nullptr && truthy(*desc));
  }
  return order_keys;
}

}  // namespace

ShapeSelector ShapeSelector::from_value(const Value& data) {
  if (!data.is_object())
    throw ValueError("selector payload must be an object");
  auto impl = std::make_shared<Impl>();
  Impl& m = *impl;

  if (const Value* raw = present_member(data, "set_operation")) {
    ParsedSetOperation parsed = parse_set_operation(*raw, data);
    m.operands = std::move(parsed.operands);
    m.set_operation = std::move(parsed.op);
  }
  if (const Value* raw = present_member(data, "incident_faces")) {
    ParsedIncidentFaces parsed = parse_incident_faces(*raw, data);
    m.incident_face_selectors = std::move(parsed.selectors);
    m.incident_faces_distinct = parsed.distinct;
  }
  if (const Value* raw = present_member(data, "incident_face_cardinality")) {
    if (!raw->is_object() || !has_exactly(*raw, {"exactly"}))
      throw ValueError("incident_face_cardinality only supports exactly");
    m.incident_face_cardinality = integer_of(*raw->find("exactly"));
  }

  if (const Value* raw = object_member(data, "source"))
    m.source_selector = from_value(*raw);
  if (const Value* raw = object_member(data, "traversal"))
    m.traversal = TraversalSpec::from_value(*raw);
  if (const Value* raw = object_member(data, "predicate"))
    m.predicate = Predicate::from_value(*raw);
  if (const Value* raw = object_member(data, "order_key"))
    m.order_key = Key::from_value(*raw);
  m.order_keys = parse_order_keys(data, m.order_key);

  m.target_kind = required_target_kind(data);
  if (const Value* desc = data.find("order_desc"))
    m.order_desc = truthy(*desc);
  if (const Value* limit = present_member(data, "limit"))
    m.limit_count = integer_of(*limit);
  if (const Value* raw = data.find("cardinality")) {
    if (!raw->is_object())
      throw TypeError("selector cardinality must be an object");
    for (const auto& [name, count] : raw->as_object())
      m.cardinality.emplace_back(name, integer_of(count));
  }
  if (const Value* raw = present_member(data, "source_node_id")) {
    m.source_node_id = string_of(*raw);
    const Value* slot = data.find("source_output_slot");
    m.source_output_slot = slot != nullptr ? static_cast<int>(integer_of(*slot)) : 0;
  }
  return ShapeSelector(std::shared_ptr<const Impl>(std::move(impl)));
}

bool ShapeSelector::operator==(const ShapeSelector& other) const {
  return impl_ == other.impl_ || values_equal(to_value(), other.to_value());
}

// ---- the module-level constructors
// -----------------------------------------------------------------------------------------------
ShapeSelector edges() {
  return ShapeSelector(Kind::Edge);
}
ShapeSelector faces() {
  return ShapeSelector(Kind::Face);
}
ShapeSelector wires() {
  return ShapeSelector(Kind::Wire);
}
ShapeSelector vertices() {
  return ShapeSelector(Kind::Vertex);
}
ShapeSelector solids() {
  return ShapeSelector(Kind::Solid);
}
ShapeSelector shells() {
  return ShapeSelector(Kind::Shell);
}

}  // namespace scad::ql
