// The history engine (see tracking_detail.hpp): identities, history queries,
// roles, and the assembly of a TopoDelta.
#include <atomic>
#include <TopExp.hxx>

#include <algorithm>
#include <cstdint>
#include <functional>
#include <map>
#include <random>
#include <set>
#include <unordered_set>

#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

std::string kernel_topo_id(const TopoDS_Shape& shape) {
  return std::to_string(std::hash<TopoDS_Shape>{}(shape));
}

bool is_temporary_tracking_ref(const TopoRef& ref) noexcept {
  return ref.graph_id.starts_with("g_") && ref.node_id.starts_with("n_");
}

}  // namespace scad

namespace scad::tracking {

namespace {
std::atomic<std::size_t> g_history_queries{0};
void count_history_query() noexcept { g_history_queries.fetch_add(1, std::memory_order_relaxed); }
}  // namespace

std::size_t history_query_count() noexcept { return g_history_queries.load(std::memory_order_relaxed); }

// ===========================================================================
// identities
// ===========================================================================

namespace {

std::string make_id(char prefix) {
  thread_local std::mt19937 engine{std::random_device{}()};
  static constexpr char kDigits[] = "0123456789abcdef";
  const auto bits = static_cast<std::uint32_t>(engine());
  std::string id{prefix, '_'};
  for (int shift = 28; shift >= 0; shift -= 4) id.push_back(kDigits[(bits >> shift) & 0xFU]);
  return id;
}

}  // namespace

OperationIds new_operation_ids() { return {make_id('g'), make_id('n')}; }

std::string_view kind_token(Kind kind) noexcept {
  switch (kind) {
    case Kind::Vertex: return "VERTEX";
    case Kind::Edge: return "EDGE";
    case Kind::Wire: return "WIRE";
    case Kind::Face: return "FACE";
    case Kind::Shell: return "SHELL";
    case Kind::Solid: return "SOLID";
    case Kind::Compound: return "COMPOUND";
  }
  return "";
}

Kind kind_of_shape(const TopoDS_Shape& shape, Kind fallback) noexcept {
  if (shape.IsNull()) return fallback;
  switch (shape.ShapeType()) {
    case TopAbs_VERTEX: return Kind::Vertex;
    case TopAbs_EDGE: return Kind::Edge;
    case TopAbs_WIRE: return Kind::Wire;
    case TopAbs_FACE: return Kind::Face;
    case TopAbs_SHELL: return Kind::Shell;
    case TopAbs_SOLID: return Kind::Solid;
    case TopAbs_COMPOUND: return Kind::Compound;
    default: return fallback;
  }
}

// ===========================================================================
// history queries
// ===========================================================================

bool history_wanted() noexcept { return current_tracking_policy() != TrackingPolicy::Graph; }

namespace {

void copy_into(std::vector<TopoDS_Shape>& to, const TopTools_ListOfShape& from) {
  to.clear();
  for (const TopoDS_Shape& shape : from) to.push_back(shape);
}

std::string_view pick_role(std::string_view specific, std::string_view general) {
  return specific.empty() ? general : specific;
}

}  // namespace

void query_history(HistorySource& history, const TopTools_IndexedMapOfShape& inputs, const QuerySpec& spec,
                   std::vector<Witness>& out) {
  if (!history_wanted()) return;

  const std::string origin(spec.origin_role);
  std::vector<TopoDS_Shape> modified, generated;  // reused: Modified/Generated share one buffer
  out.reserve(out.size() + static_cast<std::size_t>(inputs.Extent()));

  for (int index = 1; index <= inputs.Extent(); ++index) {
    const TopoDS_Shape& sub = inputs.FindKey(index);
    const std::string input_id = kernel_topo_id(sub);

    const bool deleted = history.is_deleted(sub);
    copy_into(modified, history.modified(sub));
    copy_into(generated, history.generated(sub));

    const auto emit = [&](std::string topo_id, TopoEvent event, Kind kind, std::string_view derivation,
                          std::string_view role) {
      Witness w;
      w.topo_id = std::move(topo_id);
      w.event = event;
      w.kind = kind;
      w.source_kind = spec.kind;
      w.origin_role = origin;
      w.input_topo_id = input_id;
      w.derivation = derivation;
      w.result_role = role;
      w.project_source_tags = spec.project_source_tags && event != TopoEvent::Deleted;
      out.push_back(std::move(w));
    };

    if (deleted) emit(input_id, TopoEvent::Deleted, spec.kind, "replacement", {});

    // A modification that returns the input itself is no modification.
    const bool modified_is_self = modified.size() == 1 && modified.front().IsSame(sub);

    // Untouched and still in the result: preserved.
    if (!deleted && modified.empty() && generated.empty() && (!spec.result || spec.result->contains(sub))) {
      emit(input_id, TopoEvent::Preserved, spec.kind, "continuation",
           pick_role(spec.preserved_role, spec.result_role));
      continue;
    }
    if (!deleted && modified_is_self && generated.empty()) {
      emit(input_id, TopoEvent::Preserved, spec.kind, "continuation",
           pick_role(spec.preserved_role, spec.result_role));
      continue;
    }

    if (!modified.empty() && !modified_is_self) {
      for (const TopoDS_Shape& shape : modified) {
        if (spec.result && !spec.result->contains(shape)) continue;
        emit(kernel_topo_id(shape), TopoEvent::Modified, kind_of_shape(shape, spec.kind), spec.modified_derivation,
             pick_role(spec.modified_role, spec.result_role));
      }
    }
    for (const TopoDS_Shape& shape : generated) {
      if (spec.result && !spec.result->contains(shape)) continue;
      emit(kernel_topo_id(shape), TopoEvent::Generated, kind_of_shape(shape, spec.kind), spec.generated_derivation,
           pick_role(spec.generated_role, spec.result_role));
    }
  }
}

void query_sub_shape_history(HistorySource& history, const TopoDS_Shape& input, TopAbs_ShapeEnum type,
                             const QuerySpec& spec, std::vector<Witness>& out) {
  if (!history_wanted()) return;
  count_history_query();
  TopTools_IndexedMapOfShape inputs;
  TopExp::MapShapes(input, type, inputs);
  query_history(history, inputs, spec, out);
}

void query_list_history(HistorySource& history, const std::vector<TopoDS_Shape>& inputs, const QuerySpec& spec,
                        std::vector<Witness>& out) {
  if (!history_wanted()) return;
  count_history_query();
  TopTools_IndexedMapOfShape distinct;
  for (const TopoDS_Shape& shape : inputs) distinct.Add(shape);
  query_history(history, distinct, spec, out);
}

// ===========================================================================
// roles
// ===========================================================================

std::optional<RoleWitness> operation_role(kernel::SubShapeIndex& result, const TopoDS_Shape& candidate,
                                          std::string_view role, std::string_view evidence_method,
                                          std::optional<std::string_view> origin_role) {
  if (!result.contains(candidate)) return std::nullopt;
  RoleWitness witness;
  witness.topo_id = kernel_topo_id(candidate);
  witness.kind = kind_of_shape(candidate, Kind::Face);
  witness.role = std::string(role);
  if (origin_role) witness.origin_role = std::string(*origin_role);
  witness.evidence_method = evidence_method;
  return witness;
}

void add_operation_role(std::vector<RoleWitness>& roles, kernel::SubShapeIndex& result,
                        const TopoDS_Shape& candidate, std::string_view role, std::string_view evidence_method,
                        std::optional<std::string_view> origin_role) {
  if (auto witness = operation_role(result, candidate, role, evidence_method, origin_role)) {
    roles.push_back(std::move(*witness));
  }
}

void add_roles_from_history(std::vector<RoleWitness>& roles, const std::vector<Witness>& witnesses,
                            std::string_view evidence_method, std::size_t begin) {
  for (std::size_t i = begin; i < witnesses.size(); ++i) {
    const Witness& w = witnesses[i];
    if (w.result_role.empty()) continue;
    RoleWitness role;
    role.topo_id = w.topo_id;
    role.kind = w.kind;
    role.role = std::string(w.result_role);
    role.origin_role = w.origin_role;
    role.input_topo_id = w.input_topo_id;
    role.source_kind = w.source_kind;
    role.evidence_method = evidence_method;
    roles.push_back(std::move(role));
  }
}

// ===========================================================================
// assembling the delta
// ===========================================================================

namespace {

constexpr std::string_view kComplete = "complete";
constexpr std::string_view kProven = "proven";
constexpr std::string_view kKernelHistory = "kernel_history";
constexpr std::string_view kKernelOperationRole = "kernel_operation_role";

using Members = Value::Object;

void put(Members& members, std::string_view key, Value value) {
  members.emplace_back(std::string(key), std::move(value));
}

Value string_or_null(const std::optional<std::string>& text) { return text ? Value(*text) : Value(); }

// The dict a history fact has in Python's `entries` lists.
Value witness_value(const Witness& w) {
  Members m;
  m.reserve(11);
  put(m, "topo_id", w.topo_id);
  put(m, "event", to_string(w.event));
  put(m, "kind", kind_token(w.kind));
  put(m, "source_kind", kind_token(w.source_kind));
  put(m, "origin_role", w.origin_role);
  put(m, "input_topo_id", w.input_topo_id);
  put(m, "derivation", w.derivation);
  put(m, "coverage", kComplete);
  put(m, "status", kProven);
  if (!w.result_role.empty()) put(m, "result_role", w.result_role);
  if (w.project_source_tags) put(m, "project_source_tags", true);
  return Value(std::move(m));
}

// The aggregate's view of a role fact.
Value role_witness_value(const RoleWitness& r) {
  Members m;
  m.reserve(9);
  put(m, "kind", kind_token(r.kind));
  put(m, "result_role", r.role);
  put(m, "origin_role", string_or_null(r.origin_role));
  put(m, "input_topo_id", string_or_null(r.input_topo_id));
  put(m, "source_kind", r.source_kind ? Value(kind_token(*r.source_kind)) : Value());
  put(m, "coverage", kComplete);
  put(m, "status", kProven);
  put(m, "evidence_kind", kKernelOperationRole);
  put(m, "evidence_method", r.evidence_method);
  return Value(std::move(m));
}

Value entry_metadata(const Witness& w) {
  Members m;
  m.reserve(7);
  put(m, "derivation", w.derivation);
  put(m, "coverage", kComplete);
  put(m, "status", kProven);
  put(m, "evidence_kind", kKernelHistory);
  put(m, "source_kind", kind_token(w.source_kind));
  if (!w.result_role.empty()) put(m, "result_role", w.result_role);
  if (w.project_source_tags) put(m, "project_source_tags", true);
  return Value(std::move(m));
}

Value role_metadata(const RoleWitness& r) {
  Members m;
  m.reserve(5);
  put(m, "coverage", kComplete);
  put(m, "status", kProven);
  put(m, "evidence_kind", kKernelOperationRole);
  put(m, "evidence_method", r.evidence_method);
  if (r.source_kind) put(m, "source_kind", kind_token(*r.source_kind));
  return Value(std::move(m));
}

// One topo_id's slot in `delta_entries` (`_aggregate_delta_entries`).  The
// compatibility lookup keeps every witness: a face can descend from several
// sources, so the first witness' fields are only a summary.
struct Aggregate {
  Members head;          // topo_id .. status
  Value::Array witnesses;
  std::set<std::string, std::less<>> events, origin_roles, result_roles;
  bool from_history = false;
  bool has_roles = false;

  Value finish() && {
    put(head, "witnesses", Value(std::move(witnesses)));
    const auto strings = [](const std::set<std::string, std::less<>>& set) {
      Value::Array items;
      items.reserve(set.size());
      for (const std::string& s : set) items.emplace_back(s);
      return Value(std::move(items));
    };
    if (from_history) {
      put(head, "events", strings(events));
      put(head, "origin_roles", strings(origin_roles));
    }
    if (has_roles) put(head, "result_roles", strings(result_roles));
    return Value(std::move(head));
  }
};

DeltaEntries aggregate_entries(const Witness* first, const Witness* last, const std::vector<RoleWitness>& roles) {
  std::map<std::string, Aggregate, std::less<>> by_id;

  for (const Witness* w = first; w != last; ++w) {
    auto [it, inserted] = by_id.try_emplace(w->topo_id);
    Aggregate& agg = it->second;
    if (inserted) {
      agg.head.reserve(12);
      put(agg.head, "topo_id", w->topo_id);
      put(agg.head, "kind", kind_token(w->kind));
      put(agg.head, "event", to_string(w->event));
      put(agg.head, "origin_role", w->origin_role);
      put(agg.head, "input_topo_id", w->input_topo_id);
      put(agg.head, "derivation", w->derivation);
      put(agg.head, "coverage", kComplete);
      put(agg.head, "status", kProven);
      agg.from_history = true;
    }
    agg.witnesses.push_back(witness_value(*w));
    agg.events.emplace(to_string(w->event));
    agg.origin_roles.insert(w->origin_role);
    if (!w->result_role.empty()) agg.result_roles.emplace(w->result_role);
  }

  for (const RoleWitness& r : roles) {
    auto [it, inserted] = by_id.try_emplace(r.topo_id);
    Aggregate& agg = it->second;
    if (inserted) {
      agg.head.reserve(12);
      put(agg.head, "topo_id", r.topo_id);
      put(agg.head, "kind", kind_token(r.kind));
      put(agg.head, "event", Value());
      put(agg.head, "origin_role", string_or_null(r.origin_role));
      put(agg.head, "input_topo_id", string_or_null(r.input_topo_id));
      put(agg.head, "derivation", "unknown");
      put(agg.head, "coverage", kComplete);
      put(agg.head, "status", kProven);
    }
    agg.witnesses.push_back(role_witness_value(r));
    agg.result_roles.insert(r.role);
    agg.has_roles = true;
  }

  DeltaEntries out;
  for (auto& [id, agg] : by_id) out.emplace_hint(out.end(), id, std::move(agg).finish());
  return out;
}

std::string role_key(const RoleWitness& r) {
  std::string key(kind_token(r.kind));
  key.push_back('\x1f');
  key += r.topo_id;
  key.push_back('\x1f');
  key += r.role;
  if (r.input_topo_id && r.source_kind) {
    key.push_back('\x1f');
    key += kind_token(*r.source_kind);
    key.push_back('\x1f');
    key += *r.input_topo_id;
  }
  return key;
}

}  // namespace

Finished DeltaBuilder::finish() && {
  Finished out;
  TopoDelta& delta = out.delta;
  const auto make_ref = [this](Kind kind, const std::string& id) {
    TopoRef ref;
    ref.graph_id = ids_.graph_id;
    ref.node_id = ids_.node_id;
    ref.output_slot = 0;
    ref.kind = kind;
    ref.topo_id = id;
    return ref;
  };

  delta.entries.reserve(witnesses.size());
  for (const Witness& w : witnesses) {
    TopoRef ref = make_ref(w.kind, w.topo_id);
    switch (w.event) {
      case TopoEvent::Preserved: delta.preserved.push_back(ref); break;
      case TopoEvent::Modified: delta.modified.push_back(ref); break;
      case TopoEvent::Generated: delta.generated.push_back(ref); break;
      case TopoEvent::Deleted: delta.deleted.push_back(ref); break;
    }
    TopoEntry entry;
    entry.ref = std::move(ref);
    entry.event = w.event;
    entry.origin_role = w.origin_role;
    entry.parent_refs.push_back(make_ref(w.source_kind, w.input_topo_id));
    entry.metadata = entry_metadata(w);
    delta.entries.push_back(std::move(entry));
  }

  for (const std::string& id : section_edge_ids) delta.section_edges.push_back(make_ref(Kind::Edge, id));

  std::unordered_set<std::string> seen_roles;
  delta.roles.reserve(roles.size());
  for (const RoleWitness& r : roles) {
    if (!seen_roles.insert(role_key(r)).second) continue;
    TopoRoleEntry entry;
    entry.ref = make_ref(r.kind, r.topo_id);
    entry.role = r.role;
    entry.origin_role = r.origin_role;
    if (r.input_topo_id && r.source_kind) entry.parent_refs.push_back(make_ref(*r.source_kind, *r.input_topo_id));
    entry.metadata = role_metadata(r);
    delta.roles.push_back(std::move(entry));
  }

  const Witness* begin = witnesses.data();
  const Witness* end = begin + witnesses.size();
  const Witness* split = begin + std::min(yielding_prefix, witnesses.size());
  out.delta_entries = aggregate_entries(split, end, roles);
  if (split != begin) {
    for (auto& [id, value] : aggregate_entries(begin, split, {})) out.delta_entries.try_emplace(id, std::move(value));
  }
  return out;
}

}  // namespace scad::tracking
