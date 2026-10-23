// The inverse of to_value(TopoDelta) / to_value(SemanticDelta): what a serialized graph holds.
#include <algorithm>
#include <cctype>

#include "scad/core/error.hpp"
#include "scad/topo/delta.hpp"

namespace scad {

namespace {

std::string lower(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return text;
}

std::string text_of(const Value& object, const char* key, std::string fallback = {}) {
  const Value* found = object.find(key);
  return found != nullptr && found->is_string() ? found->as_string() : fallback;
}

Kind kind_named(const std::string& name) {
  const std::string wanted = lower(name);
  for (const Kind kind : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid, Kind::Compound}) {
    if (kind_name(kind) == wanted) return kind;
  }
  throw ValueError("unknown topology kind '" + name + "'");
}

TopoRef ref_from_value(const Value& item) {
  if (!item.is_object()) throw ValueError("topology reference must be an object");
  TopoRef ref;
  ref.graph_id = text_of(item, "graph_id", "pending");
  ref.node_id = text_of(item, "node_id", "pending");
  if (const Value* slot = item.find("output_slot"); slot != nullptr && slot->is_number()) {
    ref.output_slot = static_cast<int>(slot->is_int() ? slot->as_int() : static_cast<std::int64_t>(slot->as_double()));
  }
  ref.kind = kind_named(text_of(item, "kind", "face"));
  ref.topo_id = text_of(item, "topo_id");
  return ref;
}

std::vector<TopoRef> refs_from_value(const Value* list) {
  std::vector<TopoRef> out;
  if (list == nullptr || !list->is_array()) return out;
  for (const Value& item : list->as_array()) out.push_back(ref_from_value(item));
  return out;
}

TopoEvent event_named(const std::string& name) {
  const std::string wanted = lower(name);
  for (const TopoEvent event : {TopoEvent::Preserved, TopoEvent::Modified, TopoEvent::Generated, TopoEvent::Deleted}) {
    if (to_string(event) == wanted) return event;
  }
  throw ValueError("unknown topology event '" + name + "'");
}

std::optional<std::string> optional_text(const Value& object, const char* key) {
  const Value* found = object.find(key);
  if (found == nullptr || !found->is_string()) return std::nullopt;
  return found->as_string();
}

std::vector<SemanticRef> semantic_refs(const Value* list) {
  std::vector<SemanticRef> out;
  if (list == nullptr || !list->is_array()) return out;
  for (const Value& item : list->as_array()) {
    SemanticRef ref;
    ref.graph_id = text_of(item, "graph_id", "pending");
    ref.node_id = text_of(item, "node_id", "pending");
    ref.entity_type = text_of(item, "entity_type");
    ref.entity_id = text_of(item, "entity_id");
    out.push_back(std::move(ref));
  }
  return out;
}

}  // namespace

TopoDelta topo_delta_from_value(const Value& payload) {
  if (!payload.is_object()) throw ValueError("topology delta must be an object");
  TopoDelta delta;
  delta.preserved = refs_from_value(payload.find("preserved"));
  delta.modified = refs_from_value(payload.find("modified"));
  delta.generated = refs_from_value(payload.find("generated"));
  delta.deleted = refs_from_value(payload.find("deleted"));
  delta.section_edges = refs_from_value(payload.find("section_edges"));
  if (const Value* entries = payload.find("entries"); entries != nullptr && entries->is_array()) {
    for (const Value& item : entries->as_array()) {
      TopoEntry entry;
      if (const Value* ref = item.find("ref")) entry.ref = ref_from_value(*ref);
      entry.event = event_named(text_of(item, "event", "preserved"));
      entry.origin_role = optional_text(item, "origin_role");
      entry.parent_refs = refs_from_value(item.find("parent_refs"));
      if (const Value* metadata = item.find("metadata"); metadata != nullptr && metadata->is_object()) entry.metadata = *metadata;
      delta.entries.push_back(std::move(entry));
    }
  }
  if (const Value* roles = payload.find("roles"); roles != nullptr && roles->is_array()) {
    for (const Value& item : roles->as_array()) {
      TopoRoleEntry entry;
      if (const Value* ref = item.find("ref")) entry.ref = ref_from_value(*ref);
      entry.role = text_of(item, "role");
      entry.origin_role = optional_text(item, "origin_role");
      entry.parent_refs = refs_from_value(item.find("parent_refs"));
      if (const Value* metadata = item.find("metadata"); metadata != nullptr && metadata->is_object()) entry.metadata = *metadata;
      delta.roles.push_back(std::move(entry));
    }
  }
  if (const Value* raw = payload.find("raw_event"); raw != nullptr && raw->is_object()) delta.raw_event = *raw;
  return delta;
}

SemanticDelta semantic_delta_from_value(const Value& payload) {
  if (!payload.is_object()) throw ValueError("semantic delta must be an object");
  SemanticDelta delta;
  delta.created = semantic_refs(payload.find("created"));
  delta.modified = semantic_refs(payload.find("modified"));
  delta.deleted = semantic_refs(payload.find("deleted"));
  if (const Value* metadata = payload.find("metadata"); metadata != nullptr && metadata->is_object()) delta.metadata = *metadata;
  return delta;
}

}  // namespace scad
