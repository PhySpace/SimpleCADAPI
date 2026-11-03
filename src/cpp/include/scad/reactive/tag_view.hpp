// Tags as a view over recorded history.
//
// A tag assignment is a graph node (apply_tag_rselection, and every op-kwarg tag such as top_face_tag=): its
// `tag_binding` parameter holds the binding and the entities it targets.  The tags an entity of node N's output
// carries from upstream are therefore computed, not copied: N's view is built from the views of its inputs and
// N's own TopoDelta, witness by witness, as each binding's lineage policy allows:
//
//   * preserved / modified (same kind)   carried when lineage_policy_allows(binding, derivation)
//                                         (continuation_fragment, the default: every piece of a split face);
//   * generated                          not a continuation: an entity generated from a tagged source (an edge's
//                                         fillet patch, a profile edge's side face) carries the operation's own
//                                         projected binding, stored on it when the operation ran (autotag.cpp)
//                                         and carried on with the shapes (the graph does not record it);
//   * deleted / not witnessed / an op without history: not carried, the tag ends there.
//
// The view knows the bindings the graph records.  What only shapes know (imported sidecar facts, sketch topology
// names, tags assigned outside a session, projected names) stays on the shapes and is carried there.
//
// Identity ops (tag assignments, selections) pass their input's view on unchanged.  A view is computed once per
// node object (nodes are immutable) and memoised; building it costs O(entries of the node's delta).
//
// install_tag_view() makes the topo layer ask this view for an entity's lineage witnesses, so has_tag /
// list_tags / list_tag_bindings / explain_tag (and every ql.tag) see it.  See design-docs/stable-refs-design.md 3.1.
#pragma once

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "scad/reactive/graph.hpp"
#include "scad/topo/shape.hpp"
#include "scad/topo/tagging.hpp"

namespace scad::reactive {

// One binding carried to one entity of a node's output.
struct CarriedTag {
  TagBinding binding;
  LineageDerivation derivation = LineageDerivation::Continuation;
  std::string source_node_id;  // where the binding was assigned
  std::string source_topo_id;  // the entity it was assigned to there (recorded form, "face_face_5")
  std::string op;              // the op of the last step that carried it
};

// "<slot>\x1f<kind>\x1f<recorded topo id>" -> the bindings carried to that entity.
using TagView = std::unordered_map<std::string, std::vector<CarriedTag>>;

std::string tag_view_key(int output_slot, Kind kind, const std::string& recorded_topo_id);

// The view of `node` (memoised).  Never null for a non-null node.
std::shared_ptr<const TagView> tag_view(const NodePtr& node);

// The lineage witnesses the history carries to `entity`, a sub-shape of a recorded output (empty otherwise).
std::vector<TagLineageWitness> history_witnesses(const Shape& entity);

// Install history_witnesses as the topo layer's history-witness provider.  Idempotent.
void install_tag_view() noexcept;

}  // namespace scad::reactive
