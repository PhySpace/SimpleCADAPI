// topology/autotag.py: evidence-gated semantic projection of tracking data.
//
// The witness dictionaries the tracker produces are read as Values with the
// Python defaults for missing keys, so a witness means here exactly what it means
// there.  Nothing is inferred: a face or edge without a matching proven witness is
// marked partial / unknown.
#include "scad/semantic/autotag.hpp"

#include <algorithm>
#include <map>
#include <set>

#include "detail.hpp"
#include "scad/core/error.hpp"
#include "scad/core/packed_value.hpp"
#include "scad/semantic/tracking.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad {

namespace {

using detail::lower;
using detail::object;
using detail::upper;

// ---- Python-flavoured reads of witness dictionaries ------------------------------

const Value* member(const Value& dict, std::string_view key) {
  return dict.find(key);
}

bool present(const Value* v) {
  return v != nullptr && !v->is_null();
}

// str(value) as Python prints it.
std::string py_str(const Value& v) {
  if (v.is_string())
    return v.as_string();
  if (v.is_null())
    return "None";
  if (v.is_bool())
    return v.as_bool() ? "True" : "False";
  return v.dump();
}

// str(d.get(key, fallback))
std::string str_of(const Value& dict, std::string_view key, std::string fallback) {
  const Value* v = member(dict, key);
  return v == nullptr ? std::move(fallback) : py_str(*v);
}

// _event_name: stripped lower-case name, or nullopt.
std::optional<std::string> event_name(const Value* v) {
  if (!present(v))
    return std::nullopt;
  std::string token = lower(detail::strip(py_str(*v)));
  if (token.empty())
    return std::nullopt;
  return token;
}

Value optional_text(const std::optional<std::string>& s) {
  return s ? Value(*s) : Value();
}

bool truthy(const Value* v) {
  if (v == nullptr || v->is_null())
    return false;
  if (v->is_bool())
    return v->as_bool();
  if (v->is_int())
    return v->as_int() != 0;
  if (v->is_double())
    return v->as_double() != 0.0;
  if (v->is_string())
    return !v->as_string().empty();
  return v->size() != 0;
}

std::string kind_token(Kind kind) {
  return upper(kind_name(kind));
}

// ---- delta entries ----------------------------------------------------------------

Value ref_value(const TopoRef& ref) {
  return object({{"graph_id", ref.graph_id},
                 {"node_id", ref.node_id},
                 {"output_slot", ref.output_slot},
                 {"kind", kind_token(ref.kind)},
                 {"topo_id", ref.topo_id}});
}

const Value* by_key(const DeltaEntries& entries, std::string_view key) {
  const auto it = entries.find(std::string(key));
  return it != entries.end() ? &it->second : nullptr;
}

// _normalized_witnesses
std::vector<Value> normalized_witnesses(const Value& entry) {
  std::vector<Value> out;
  const Value* raw = member(entry, "witnesses");
  if (raw != nullptr && raw->is_array() && raw->size() != 0) {
    for (const Value& item : raw->as_array())
      if (item.is_object())
        out.push_back(item);
    return out;
  }
  out.push_back(entry);
  return out;
}

// _matching_entry
std::optional<Value> matching_entry(const DeltaEntries& entries, std::string_view topo_id, Kind kind) {
  const Value* entry = by_key(entries, topo_id);
  if (entry == nullptr || !entry->is_object())
    return std::nullopt;
  const std::string expected = kind_token(kind);
  std::vector<Value> witnesses;
  for (Value& witness : normalized_witnesses(*entry)) {
    const Value* own = member(witness, "kind");
    const Value* fallback = member(*entry, "kind");
    const std::string actual = own != nullptr ? py_str(*own) : (fallback != nullptr ? py_str(*fallback) : expected);
    if (upper(actual) == expected)
      witnesses.push_back(std::move(witness));
  }
  if (witnesses.empty())
    return std::nullopt;
  Value matched = *entry;
  matched.set("kind", expected);
  Value list = Value::array();
  for (Value& w : witnesses)
    list.push_back(std::move(w));
  matched.set("witnesses", std::move(list));
  return matched;
}

// _normalized_tracking_witness
Value normalized_tracking_witness(const Value& witness, Kind default_kind) {
  const Value* source_kind = member(witness, "source_kind");
  const std::optional<std::string> event = event_name(member(witness, "event"));
  Value result = object({
      {"kind", "topology_change"},
      {"topo_kind", upper(str_of(witness, "kind", kind_token(default_kind)))},
      {"source_kind", present(source_kind) ? Value(upper(py_str(*source_kind))) : Value()},
      {"event", optional_text(event)},
      {"origin_role", member(witness, "origin_role") != nullptr ? *member(witness, "origin_role") : Value()},
      {"input_topo_id", member(witness, "input_topo_id") != nullptr ? *member(witness, "input_topo_id") : Value()},
      {"derivation", lower(str_of(witness, "derivation", "unknown"))},
      {"coverage", lower(str_of(witness, "coverage", "complete"))},
      {"status", lower(str_of(witness, "status", "proven"))},
      {"evidence_kind", lower(str_of(witness, "evidence_kind", "kernel_history"))},
  });
  for (const std::string_view key : {"result_role", "evidence_method", "project_source_tags"})
    if (const Value* v = member(witness, key); present(v))
      result.set(std::string(key), *v);
  if (const Value* refs = member(witness, "parent_refs"); present(refs))
    result.set("parent_refs", *refs);
  if (truthy(member(witness, "section")))
    result.set("section", true);
  return result;
}

Value sorted_strings(const std::set<std::string>& items) {
  Value out = Value::array();
  for (const auto& item : items)
    out.push_back(item);
  return out;
}

// _tracking_payload
Value tracking_payload(const Value& entry, std::string_view op, std::string_view topo_id, Kind kind) {
  std::vector<Value> witnesses;
  for (const Value& item : normalized_witnesses(entry))
    witnesses.push_back(normalized_tracking_witness(item, kind));

  std::set<std::string> events, origin_roles, result_roles;
  bool all_complete = !witnesses.empty(), all_proven = !witnesses.empty();
  for (const Value& w : witnesses) {
    if (const Value* v = member(w, "event"); present(v))
      events.insert(py_str(*v));
    if (const Value* v = member(w, "origin_role"); present(v))
      origin_roles.insert(py_str(*v));
    if (const Value* v = member(w, "result_role"); present(v))
      result_roles.insert(py_str(*v));
    all_complete = all_complete && py_str(*member(w, "coverage")) == "complete";
    all_proven = all_proven && py_str(*member(w, "status")) == "proven";
  }

  Value list = Value::array();
  for (Value& w : witnesses)
    list.push_back(std::move(w));
  Value payload = object({
      {"schema_version", "1.0"},
      {"kind", "topology_change"},
      {"op", std::string(op)},
      {"operation", operation_alias(op)},
      {"topo_id", std::string(topo_id)},
      {"topo_kind", kind_token(kind)},
      {"coverage", all_complete ? "complete" : "partial"},
      {"status", all_proven ? "proven" : "unknown"},
      {"events", sorted_strings(events)},
      {"origin_roles", sorted_strings(origin_roles)},
      {"result_roles", sorted_strings(result_roles)},
      {"witnesses", std::move(list)},
  });
  if (events.size() == 1)
    payload.set("event", *events.begin());
  if (origin_roles.size() == 1)
    payload.set("origin_role", *origin_roles.begin());
  if (result_roles.size() == 1)
    payload.set("result_role", *result_roles.begin());
  return payload;
}

// _unknown_tracking_payload
Value unknown_tracking_payload(std::string_view op, std::string_view topo_id, Kind kind) {
  return object({
      {"schema_version", "1.0"},
      {"kind", "topology_change"},
      {"op", std::string(op)},
      {"operation", operation_alias(op)},
      {"topo_id", std::string(topo_id)},
      {"topo_kind", kind_token(kind)},
      {"coverage", "partial"},
      {"status", "unknown"},
      {"events", Value::array()},
      {"origin_roles", Value::array()},
      {"result_roles", Value::array()},
      {"witnesses", Value::array()},
  });
}

// The unknown payload is a pure function of (op, topo id, kind): stored as that recipe.
constexpr unsigned char kUnknownTrackRecipe = 1;

Value expand_unknown_track(const Value& args) {
  const auto& a = args.as_array();
  return unknown_tracking_payload(a.at(0).as_string(), a.at(1).as_string(), static_cast<Kind>(a.at(2).as_int()));
}

[[maybe_unused]] const bool kRecipesRegistered = [] {
  PackedValue::register_recipe(kUnknownTrackRecipe, &expand_unknown_track);
  return true;
}();

void set_unknown_track(Shape& shape, std::string_view op, const std::string& topo_id, Kind kind) {
  shape.set_metadata_recipe(
      "track", kUnknownTrackRecipe,
      Value(Value::Array{Value(std::string(op)), Value(topo_id), Value(static_cast<std::int64_t>(kind))}));
}

// ---- lineage and projection --------------------------------------------------------

std::optional<LineageDerivation> lineage_derivation_or_none(const std::string& token) {
  try {
    return parse_lineage_derivation(token);
  } catch (const TagValidationError&) {
    return std::nullopt;
  }
}

const Shape* source_of(const Value& witness, const TopologyIndex& sources) {
  const Value* id = member(witness, "input_topo_id");
  return present(id) ? sources.find(py_str(*id)) : nullptr;
}

// _carry_source_lineage: attach source bindings only through policy-allowed kernel witnesses.
void carry_source_lineage(Shape& target, const Value& entry, const TopologyIndex& sources, std::string_view op) {
  for (const Value& witness : normalized_witnesses(entry)) {
    const std::string derivation_token = lower(str_of(witness, "derivation", "unknown"));
    const auto derivation = lineage_derivation_or_none(derivation_token);
    if (!derivation)
      continue;  // an operation role can be complete without proving tag lineage
    const Shape* source = source_of(witness, sources);
    if (source == nullptr)
      continue;

    const std::string coverage = str_of(witness, "coverage", "complete");
    TagEvidence evidence;
    evidence.kind = TagEvidenceKind::TopologyChange;
    evidence.data =
        object({{"op", std::string(op)},
                {"event", optional_text(event_name(member(witness, "event")))},
                {"origin_role", member(witness, "origin_role") != nullptr ? *member(witness, "origin_role") : Value()},
                {"coverage", coverage},
                {"derivation", derivation_token}});

    std::vector<TagBinding> bindings = source->local_tag_bindings();
    for (const TagLineageWitness& carried : source->lineage_witnesses())
      if (carried.coverage == "complete" && lineage_policy_allows(carried.binding.propagation(), carried.derivation))
        bindings.push_back(carried.binding);
    // One binding per id; the later record of an id replaces the earlier, keeping its place.
    std::vector<TagBinding> unique;
    for (TagBinding& binding : bindings) {
      const auto at = std::find_if(unique.begin(), unique.end(),
                                   [&](const TagBinding& b) { return b.binding_id == binding.binding_id; });
      if (at != unique.end())
        *at = std::move(binding);
      else
        unique.push_back(std::move(binding));
    }
    for (const TagBinding& binding : unique) {
      if (!lineage_policy_allows(binding.propagation(), *derivation))
        continue;
      target.add_tag_lineage(binding, *derivation, source->topo_id(), evidence, coverage);
    }
  }
}

// _apply_operation_role_bindings
void apply_operation_role_bindings(Shape& target, const Value& track, std::string_view op) {
  const Value* witnesses = member(track, "witnesses");
  if (witnesses == nullptr || !witnesses->is_array())
    return;
  for (const Value& witness : witnesses->as_array()) {
    const Value* role = member(witness, "result_role");
    if (!present(role) || py_str(*member(witness, "status")) != "proven" ||
        py_str(*member(witness, "coverage")) != "complete")
      continue;
    const std::string role_text = py_str(*role);
    const std::string tag = std::string(kind_name(target.kind())) + "." + role_text;
    target.add_binding(operation_role_tag_binding(tag, op, role_text, target.topo_id(),
                                                  str_of(witness, "evidence_method", "unknown")));
  }
}

bool is_dict(const Value* v) {
  return v != nullptr && v->is_object();
}

// _project_source_bindings
void project_source_bindings(Shape& target, const Value& entry, const TopologyIndex& sources, std::string_view op,
                             bool require_lineage_policy,
                             const std::map<std::string, std::set<std::string>>& topology_source_targets) {
  for (const Value& witness : normalized_witnesses(entry)) {
    if (!truthy(member(witness, "project_source_tags")))
      continue;
    if (lower(str_of(witness, "coverage", "partial")) != "complete" ||
        lower(str_of(witness, "status", "unknown")) != "proven")
      continue;
    const Shape* source = source_of(witness, sources);
    if (source == nullptr)
      continue;

    const std::string derivation = lower(str_of(witness, "derivation", "unknown"));
    const std::optional<std::string> event = event_name(member(witness, "event"));
    const Value* explicit_role = member(witness, "result_role");
    const std::string role = truthy(explicit_role) ? py_str(*explicit_role) : event.value_or(derivation);
    std::string evidence_method;
    if (const Value* given = member(witness, "evidence_method"); present(given)) {
      evidence_method = py_str(*given);
    } else if (event == "preserved") {
      evidence_method = "Identity";
    } else if (event == "modified") {
      evidence_method = "Modified";
    } else if (event == "generated") {
      evidence_method = "Generated";
    } else {
      evidence_method = "KernelHistory";
    }

    for (const TagBinding& binding : source->local_tag_bindings()) {
      const Value& evidence = binding.evidence->data;
      const bool is_user = binding.producer().kind == TagProducerKind::UserOperation;
      const bool is_prior_projection = binding.producer().kind == TagProducerKind::AutoRule &&
                                       binding.producer().rule_id == "simplecad.feature_source_tag_projection";
      const bool is_output_naming = is_dict(member(evidence, "operation_output_role")) ||
                                    is_dict(member(evidence, "source_operation_output_role"));
      const bool is_topology_naming =
          is_dict(member(evidence, "topology_name")) || is_dict(member(evidence, "source_topology_name"));

      if (is_topology_naming) {
        std::set<std::string> source_ids;
        for (const Value& item : normalized_witnesses(entry))
          if (const Value* id = member(item, "input_topo_id"); present(id))
            source_ids.insert(py_str(*id));
        // Python looks the table up by the source's entity id although it is keyed by kernel id, so
        // a topology-named binding is never projected through this path; kept for parity.
        const auto exact = topology_source_targets.find(source->topo_id());
        const bool exact_match = exact != topology_source_targets.end() && exact->second.size() == 1 &&
                                 *exact->second.begin() == target.topo_id();
        if (source_ids.size() != 1 || !exact_match)
          continue;  // never project a topology identity through a split or merge
      }
      if (require_lineage_policy) {
        if ((!is_output_naming && !is_topology_naming) || (!is_user && !is_prior_projection))
          continue;
      } else if (!(is_user || is_prior_projection)) {
        continue;
      }
      if (require_lineage_policy && !lineage_policy_allows(binding.propagation(), parse_lineage_derivation(derivation)))
        continue;
      target.add_binding(projected_tag_binding(binding, op, role, source->topo_id(), target.topo_id(), evidence_method,
                                               target.kind() == Kind::Face && is_topology_naming
                                                   ? TopologyPropagation::Downward
                                                   : TopologyPropagation::Local));
    }
  }
}

// _lineage_coverage
std::string lineage_coverage(const Value& entry, const TopologyIndex& sources) {
  for (const Value& witness : normalized_witnesses(entry)) {
    if (lower(str_of(witness, "coverage", "partial")) != "complete")
      return "partial";
    const Value* id = member(witness, "input_topo_id");
    if (present(id) && sources.find(py_str(*id)) == nullptr)
      return "partial";
  }
  return "complete";
}

// ---- the members of a shape ---------------------------------------------------------

std::vector<Shape> faces_of(const Shape& shape) {
  switch (shape.kind()) {
    case Kind::Face:
      return {shape};
    case Kind::Shell:
      return detail::as_shapes(Shell(shape).faces());
    case Kind::Solid:
      return detail::as_shapes(Solid(shape).faces());
    case Kind::Compound:
      return detail::as_shapes(Compound(shape).faces());
    default:
      return {};
  }
}

std::vector<Shape> edges_of(const Shape& shape) {
  switch (shape.kind()) {
    case Kind::Edge:
      return {shape};
    case Kind::Wire:
      return detail::as_shapes(Wire(shape).edges());
    case Kind::Face:
      return detail::as_shapes(Face(shape).edges());
    case Kind::Shell:
      return detail::as_shapes(Shell(shape).edges());
    case Kind::Solid:
      return detail::as_shapes(Solid(shape).edges());
    case Kind::Compound:
      return detail::as_shapes(Compound(shape).edges());
    default:
      return {};
  }
}

}  // namespace

// ---------------------------------------------------------------------------
// Public pieces
// ---------------------------------------------------------------------------
std::string topology_key(const Shape& shape) {
  return kernel_topo_id(shape.wrapped());
}

void TopologyIndex::add(const Shape& shape) {
  shapes_.insert_or_assign(topology_key(shape), shape);
}

const Shape* TopologyIndex::find(std::string_view id) const {
  const auto it = shapes_.find(id);
  return it != shapes_.end() ? &it->second : nullptr;
}

std::string operation_alias(std::string_view op) {
  std::string token = lower(detail::strip(op));
  if (detail::starts_with(token, "op."))
    token.erase(0, 3);
  if (detail::starts_with(token, "make_"))
    token.erase(0, 5);
  for (const std::string_view suffix : {"_rsolid", "_rshape", "_rface", "_rwire", "_redge"})
    if (detail::ends_with(token, suffix))
      return token.substr(0, token.size() - suffix.size());
  return token;
}

DeltaEntries entries_from_delta(const TopoDelta& delta) {
  DeltaEntries result;
  for (const TopoEntry& entry : delta.entries) {
    Value parents = Value::array();
    for (const TopoRef& ref : entry.parent_refs)
      parents.push_back(ref_value(ref));
    const auto metadata = [&](std::string_view key, Value fallback) {
      const Value* v = entry.metadata.find(key);
      return v != nullptr ? *v : std::move(fallback);
    };
    const std::string event = std::string(to_string(entry.event));
    Value input_id = entry.parent_refs.empty() ? Value() : Value(entry.parent_refs.front().topo_id);
    Value witness = object({
        {"topo_id", entry.ref.topo_id},
        {"kind", kind_token(entry.ref.kind)},
        {"event", event},
        {"origin_role", optional_text(entry.origin_role)},
        {"input_topo_id", input_id},
        {"parent_refs", std::move(parents)},
        {"derivation", metadata("derivation", "unknown")},
        {"coverage", metadata("coverage", "complete")},
        {"status", metadata("status", "proven")},
        {"evidence_kind", metadata("evidence_kind", "kernel_history")},
        {"source_kind", metadata("source_kind", Value())},
    });
    auto found = result.find(entry.ref.topo_id);
    if (found == result.end()) {
      found = result
                  .emplace(entry.ref.topo_id, object({{"topo_id", entry.ref.topo_id},
                                                      {"kind", kind_token(entry.ref.kind)},
                                                      {"event", event},
                                                      {"origin_role", optional_text(entry.origin_role)},
                                                      {"input_topo_id", input_id},
                                                      {"derivation", *witness.find("derivation")},
                                                      {"coverage", *witness.find("coverage")},
                                                      {"status", *witness.find("status")},
                                                      {"witnesses", Value::array()}}))
                  .first;
    }
    found->second.find("witnesses")->push_back(std::move(witness));
  }
  return result;
}

Shape apply_tracking_tags(Shape result, const TopoDelta& delta, const DeltaEntries& given_entries,
                          const TrackingContext& context) {
  const DeltaEntries entries = given_entries.empty() ? entries_from_delta(delta) : given_entries;
  const std::string& op = context.op;

  TopologyIndex source_faces, source_edges;
  for (const Shape& source : context.sources) {
    for (const Shape& face : faces_of(source))
      source_faces.add(face);
    for (const Shape& edge : edges_of(source))
      source_edges.add(edge);
  }

  // Which result faces a source edge's projected tags may land on: only a one-to-one story is told.
  std::map<std::string, std::set<std::string>> topology_source_targets;
  for (const auto& [target_id, entry] : entries) {
    if (upper(py_str(entry.find("kind") != nullptr ? *entry.find("kind") : Value(""))) != "FACE")
      continue;
    for (const Value& witness : normalized_witnesses(entry)) {
      const Value* source_id = member(witness, "input_topo_id");
      if (truthy(member(witness, "project_source_tags")) && upper(str_of(witness, "source_kind", "")) == "EDGE" &&
          present(source_id))
        topology_source_targets[py_str(*source_id)].insert(target_id);
    }
  }

  for (Shape& face : faces_of(result)) {
    const std::string topo_id = topology_key(face);
    const auto entry = matching_entry(entries, topo_id, Kind::Face);
    if (!entry) {
      set_unknown_track(face, op, topo_id, Kind::Face);
      face.set_runtime_deferred("semantic.lineage.coverage", "partial");
      continue;
    }
    const Value track = tracking_payload(*entry, op, topo_id, Kind::Face);
    face.set_metadata_deferred("track", track);
    apply_operation_role_bindings(face, track, op);
    face.set_runtime_deferred("semantic.lineage.coverage", lineage_coverage(*entry, source_faces));
    const bool proven = py_str(*track.find("status")) == "proven";
    if (!source_faces.empty() && proven) {
      carry_source_lineage(face, *entry, source_faces, op);
      project_source_bindings(face, *entry, source_faces, op, true, topology_source_targets);
    }
    if (!source_edges.empty() && proven)
      project_source_bindings(face, *entry, source_edges, op, false, topology_source_targets);
  }

  std::set<std::string> section_ids;
  for (const TopoRef& ref : delta.section_edges)
    if (ref.kind == Kind::Edge)
      section_ids.insert(ref.topo_id);

  for (Shape& edge : edges_of(result)) {
    const std::string topo_id = topology_key(edge);
    const auto entry = matching_entry(entries, topo_id, Kind::Edge);
    if (!entry && section_ids.count(topo_id) == 0) {
      set_unknown_track(edge, op, topo_id, Kind::Edge);
      edge.set_runtime_deferred("semantic.lineage.coverage", "partial");
      continue;  // the unknown payload names no roles, so there is nothing else to apply
    }
    Value track =
        entry ? tracking_payload(*entry, op, topo_id, Kind::Edge) : unknown_tracking_payload(op, topo_id, Kind::Edge);
    if (section_ids.count(topo_id) != 0) {
      track.set("section", true);
      track.set("derivation", "intersection");
      if (!entry) {
        Value section_witness = object({{"kind", "topology_change"},
                                        {"topo_kind", "EDGE"},
                                        {"source_kind", Value()},
                                        {"event", "generated"},
                                        {"origin_role", Value()},
                                        {"input_topo_id", Value()},
                                        {"derivation", "intersection"},
                                        {"coverage", "complete"},
                                        {"status", "proven"},
                                        {"evidence_kind", "kernel_section_edges"},
                                        {"section", true}});
        Value witnesses = Value::array();
        witnesses.push_back(std::move(section_witness));
        Value generated = Value::array();
        generated.push_back("generated");
        track.set("coverage", "complete");
        track.set("status", "proven");
        track.set("event", "generated");
        track.set("events", std::move(generated));
        track.set("witnesses", std::move(witnesses));
      }
    }
    edge.set_metadata_deferred("track", track);
    apply_operation_role_bindings(edge, track, op);
    edge.set_runtime_deferred("semantic.lineage.coverage", entry ? lineage_coverage(*entry, source_edges) : "partial");
    if (entry && !source_edges.empty() && py_str(*track.find("status")) == "proven")
      carry_source_lineage(edge, *entry, source_edges, op);
  }
  return result;
}

}  // namespace scad
