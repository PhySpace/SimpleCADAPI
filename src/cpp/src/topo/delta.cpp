#include "scad/topo/delta.hpp"

#include <cctype>

namespace scad {

std::string_view to_string(TopoEvent event) noexcept {
  switch (event) {
    case TopoEvent::Preserved:
      return "preserved";
    case TopoEvent::Modified:
      return "modified";
    case TopoEvent::Generated:
      return "generated";
    case TopoEvent::Deleted:
      return "deleted";
  }
  return "";
}

namespace {

bool unbound(const std::string& id) {
  return id.empty() || id == "pending";
}

TopoRef bind_ref(TopoRef ref, const std::string& graph_id, const std::string& node_id) {
  if (unbound(ref.graph_id))
    ref.graph_id = graph_id;
  if (unbound(ref.node_id))
    ref.node_id = node_id;
  return ref;
}

std::vector<TopoRef> bind_refs(const std::vector<TopoRef>& refs, const std::string& g, const std::string& n) {
  std::vector<TopoRef> out;
  out.reserve(refs.size());
  for (const auto& r : refs)
    out.push_back(bind_ref(r, g, n));
  return out;
}

Value refs_value(const std::vector<TopoRef>& refs) {
  Value out = Value::array();
  for (const auto& r : refs)
    out.push_back(to_value(r));
  return out;
}

}  // namespace

TopoDelta bind_topo_delta(const TopoDelta& d, const std::string& g, const std::string& n) {
  TopoDelta out;
  out.preserved = bind_refs(d.preserved, g, n);
  out.modified = bind_refs(d.modified, g, n);
  out.generated = bind_refs(d.generated, g, n);
  out.deleted = bind_refs(d.deleted, g, n);
  out.section_edges = bind_refs(d.section_edges, g, n);
  for (auto entry : d.entries) {
    entry.ref = bind_ref(entry.ref, g, n);
    entry.parent_refs = bind_refs(entry.parent_refs, g, n);
    out.entries.push_back(std::move(entry));
  }
  for (auto role : d.roles) {
    role.ref = bind_ref(role.ref, g, n);
    role.parent_refs = bind_refs(role.parent_refs, g, n);
    out.roles.push_back(std::move(role));
  }
  out.raw_event = d.raw_event;
  return out;
}

SemanticDelta bind_semantic_delta(const SemanticDelta& d, const std::string& g, const std::string& n) {
  auto bind = [&](std::vector<SemanticRef> refs) {
    for (auto& r : refs) {
      if (unbound(r.graph_id))
        r.graph_id = g;
      if (unbound(r.node_id))
        r.node_id = n;
    }
    return refs;
  };
  SemanticDelta out;
  out.created = bind(d.created);
  out.modified = bind(d.modified);
  out.deleted = bind(d.deleted);
  out.metadata = d.metadata;
  return out;
}

Value to_value(const TopoRef& ref) {
  Value v = Value::object();
  v.set("graph_id", ref.graph_id);
  v.set("node_id", ref.node_id);
  v.set("output_slot", ref.output_slot);
  std::string kind(kind_name(ref.kind));  // the SDK's TopoKind member names are upper case
  for (char& c : kind)
    c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
  v.set("kind", std::move(kind));
  v.set("topo_id", ref.topo_id);
  return v;
}

Value to_value(const TopoDelta& d) {
  Value v = Value::object();
  v.set("preserved", refs_value(d.preserved));
  v.set("modified", refs_value(d.modified));
  v.set("generated", refs_value(d.generated));
  v.set("deleted", refs_value(d.deleted));
  v.set("section_edges", refs_value(d.section_edges));
  Value entries = Value::array();
  for (const auto& e : d.entries) {
    Value item = Value::object();
    item.set("ref", to_value(e.ref));
    std::string event(to_string(e.event));  // the SDK's TopoEvent member names are upper case
    for (char& c : event)
      c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    item.set("event", std::move(event));
    item.set("origin_role", e.origin_role ? Value(*e.origin_role) : Value());
    item.set("parent_refs", refs_value(e.parent_refs));
    item.set("metadata", e.metadata);
    entries.push_back(std::move(item));
  }
  v.set("entries", std::move(entries));
  Value roles = Value::array();
  for (const auto& r : d.roles) {
    Value item = Value::object();
    item.set("ref", to_value(r.ref));
    item.set("role", r.role);
    item.set("origin_role", r.origin_role ? Value(*r.origin_role) : Value());
    item.set("parent_refs", refs_value(r.parent_refs));
    item.set("metadata", r.metadata);
    roles.push_back(std::move(item));
  }
  v.set("roles", std::move(roles));
  v.set("raw_event", d.raw_event);
  return v;
}

Value to_value(const SemanticDelta& d) {
  auto refs = [](const std::vector<SemanticRef>& list) {
    Value out = Value::array();
    for (const auto& r : list) {
      Value item = Value::object();
      item.set("graph_id", r.graph_id);
      item.set("node_id", r.node_id);
      item.set("entity_type", r.entity_type);
      item.set("entity_id", r.entity_id);
      out.push_back(std::move(item));
    }
    return out;
  };
  Value v = Value::object();
  v.set("created", refs(d.created));
  v.set("modified", refs(d.modified));
  v.set("deleted", refs(d.deleted));
  v.set("metadata", d.metadata);
  return v;
}

}  // namespace scad
