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

}  // namespace scad::reactive
