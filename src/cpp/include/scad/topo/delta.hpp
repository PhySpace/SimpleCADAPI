// What an operation did to topology: port of the delta types in
// simplecadapi/topology/model.py (TopoRef, TopoEntry, TopoRoleEntry, TopoDelta,
// SemanticRef, SemanticDelta).
//
// A delta lists, per sub-shape of an operation's output (and, for deletions, of
// its inputs), whether it was preserved, modified, generated or deleted, plus
// "role" evidence (the extrusion's first cap, ...) and the parents it descends
// from.  Tag lineage is projected through these records.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

enum class TopoEvent { Preserved, Modified, Generated, Deleted };
std::string_view to_string(TopoEvent event) noexcept;

// Reference to a sub-shape of a recorded operation's output.  graph_id/node_id
// are "pending" until the recorder binds them.
struct TopoRef {
  std::string graph_id{"pending"};
  std::string node_id{"pending"};
  int output_slot = 0;
  Kind kind = Kind::Face;
  std::string topo_id;
  bool operator==(const TopoRef&) const = default;
};

struct SemanticRef {
  std::string graph_id{"pending"};
  std::string node_id{"pending"};
  std::string entity_type;
  std::string entity_id;
  bool operator==(const SemanticRef&) const = default;
};

struct TopoEntry {
  TopoRef ref;
  TopoEvent event = TopoEvent::Preserved;
  std::optional<std::string> origin_role;  // "body" / "tool" / ...
  std::vector<TopoRef> parent_refs;
  Value metadata = Value::object();
};

// Kernel-backed output role of a result entity ("extrude.first_cap").  The role
// is a dot token, lower-case; independent of the topology event.
struct TopoRoleEntry {
  TopoRef ref;
  std::string role;
  std::optional<std::string> origin_role;
  std::vector<TopoRef> parent_refs;
  Value metadata = Value::object();
};

struct TopoDelta {
  std::vector<TopoRef> preserved, modified, generated, deleted, section_edges;
  std::vector<TopoEntry> entries;
  std::vector<TopoRoleEntry> roles;
  Value raw_event = Value::object();
};

struct SemanticDelta {
  std::vector<SemanticRef> created, modified, deleted;
  Value metadata = Value::object();
};

// Rebind "pending" graph/node ids once the recorder has assigned them.
TopoDelta bind_topo_delta(const TopoDelta& delta, const std::string& graph_id, const std::string& node_id);
SemanticDelta bind_semantic_delta(const SemanticDelta& delta, const std::string& graph_id, const std::string& node_id);

Value to_value(const TopoRef& ref);
Value to_value(const TopoDelta& delta);
Value to_value(const SemanticDelta& delta);

// The inverse of to_value (kind and event names in either case); ValueError for a malformed payload.
TopoDelta topo_delta_from_value(const Value& payload);
SemanticDelta semantic_delta_from_value(const Value& payload);

}  // namespace scad
