// Stable element references, resolved through recorded operation history (spike, stage 0/1).
//
// An element reference names a sub-shape by where it was born -- an anchor: (node, slot, kind,
// recorded topo id) -- and is resolved against a later node by walking the TopoDelta every node
// on the way recorded from OCCT's Modified / Generated / IsDeleted history.  The answer is a
// status (ok / split / merged / lost), the entities of the target node the anchor became, and the
// hops that got there.  Nothing is guessed: no geometry is consulted, and an entity whose history
// is missing at some node is reported lost there with the reason, never replaced by another one.
//
// See design-docs/stable-refs-design.md.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/reactive/graph.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive {

enum class RefStatus { Ok, Split, Merged, Lost };
std::string_view to_string(RefStatus status) noexcept;

// Which events continue a lineage.  Identity: Preserved and Modified entities of the anchor's own
// kind (a face stays a face).  Derived: also Generated entities and kind changes (an edge's fillet
// patch), Onshape's startTracking.
enum class FollowMode { Identity, Derived };

// One node on the path that touched the lineage.
struct RefHop {
  std::string node_id;
  std::string op;
  // The strongest event at this node: Deleted > Generated > Modified > Preserved.
  TopoEvent event = TopoEvent::Preserved;
  std::string derivation;     // the witness's metadata "derivation" (fragment, continuation, ...)
  std::vector<TopoRef> from;  // lineage members the node consumed
  std::vector<TopoRef> to;    // what they became in the node's output
  bool untracked = false;     // the node recorded no history: its output was aliased by topo id
  bool merged = false;        // an output entity also absorbed an entity outside the lineage
};

struct ResolvedRef {
  RefStatus status = RefStatus::Lost;
  std::vector<TopoRef> targets;  // entities of the target node's output slot
  std::vector<RefHop> hops;
  // For a lost reference: where the lineage ended, and why ("deleted", "no_history",
  // "not_downstream", "unknown_node").
  std::string lost_at;
  std::string reason;
};

struct ElementAnchor {
  std::string node_id;
  int output_slot = 0;
  Kind kind = Kind::Face;
  std::string topo_id;  // recorded form: "face_face_5"
};

// Resolve `anchor` against output `target_slot` of `target`, walking `target` and its upstream closure.
ResolvedRef resolve_by_history(const NodePtr& target, const ElementAnchor& anchor, int target_slot = 0,
                               FollowMode mode = FollowMode::Identity);

// The anchor of a node's role entity ("extrude.first_cap", "box.top"), from the node's delta roles.
std::vector<ElementAnchor> anchors_for_role(const NodePtr& node, std::string_view role);

// The sub-shapes of `root` with the recorded topo id ("face_face_5": kind name, '_', the root's own topo id).
std::vector<Shape> subshapes_by_recorded_id(const Shape& root, Kind kind, const std::vector<std::string>& ids);

Value to_value(const ResolvedRef& resolved);

// ---- anchors that survive re-execution -------------------------------------------------------------------
//
// A node id counts the operations of its cell ("<cell>_node_<n>"), so an operation inserted earlier in the cell
// shifts every later id and a stored node id then names another operation.  A stable anchor names the node by
// (feature, op, occurrence): the cell (graph namespace) it was recorded in, its op name, and how many nodes of
// that feature with that op are *its own ancestors* (upstream of it, not merely recorded before it).  An inserted
// operation of another kind never shifts it, nor does one of the same kind unless it feeds this very node.
//
// Two nodes can share a key without either being upstream of the other (two primitives of one cell).  The key
// then carries the digest of the node's own parameters: the candidate whose parameters are unchanged wins; when
// none or several do, the anchor is ambiguous and resolves to nothing (locate_all lists the candidates), never to a
// guess.  The entity is named by its kernel role (+ ordinal among the node's entities with that role) when it has
// one, by the positional topo id otherwise.

struct StableNodeKey {
  std::string feature;  // the graph namespace of the node ("" outside a cell)
  std::string op;
  int occurrence = 0;
  std::string params_digest;  // tie-break only; not part of the identity
  bool operator==(const StableNodeKey& other) const {
    return feature == other.feature && op == other.op && occurrence == other.occurrence;
  }
};

struct StableAnchor {
  StableNodeKey node;
  int output_slot = 0;
  Kind kind = Kind::Face;
  std::string role;      // empty: by topo id
  int role_ordinal = 0;  // among the node's entities with that role, in recorded order
  std::string topo_id;   // the recorded topo id when it was made (a hint; the only name when `role` is empty)
};

// The feature (namespace) part of a node id: "cellA_node_0000002a" -> "cellA", "node_00000001" -> "".
std::string node_feature(std::string_view node_id);

// The stable key of `node` (computed from its own upstream closure).
StableNodeKey stable_key_of(const NodePtr& node);

// The nodes upstream of (or equal to) `within` with that key (feature, op, occurrence), inputs first.
std::vector<NodePtr> find_by_stable_key(const NodePtr& within, const StableNodeKey& key);

// The one node a key names: the only candidate, or the only one whose parameters are unchanged; nullptr otherwise.
NodePtr pick_by_stable_key(const NodePtr& within, const StableNodeKey& key);

// Where the entity `anchor` names was born: follow its single same-kind parent back through every node that only
// preserved or modified it (a selection is crossed to its source), stopping at a creator, at the node that
// generated it, merged it from several parents, or split it from its parent (the piece is named there).
// ValueError when the anchor's node is not `within` or upstream of it.
ElementAnchor trace_to_birth(const NodePtr& within, const ElementAnchor& anchor);

// The stable form of `anchor` (traced to its birth first), whose node must be `within` or upstream of it.
// ValueError otherwise.
StableAnchor stabilize(const NodePtr& within, const ElementAnchor& anchor);

// The anchor a stable anchor names in the graph of `within` (nullopt: no such node, or the role has fewer
// entities than the ordinal).
std::optional<ElementAnchor> locate(const NodePtr& within, const StableAnchor& anchor);

Value to_value(const StableAnchor& anchor);
StableAnchor stable_anchor_from_value(const Value& value);

}  // namespace scad::reactive
