#include "scad/reactive/element_ref.hpp"

#include <algorithm>
#include <map>
#include <optional>
#include <set>
#include <unordered_map>
#include <unordered_set>

#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include "internal.hpp"
#include "scad/core/error.hpp"

namespace scad::reactive {

std::string_view to_string(RefStatus status) noexcept {
  switch (status) {
    case RefStatus::Ok:
      return "ok";
    case RefStatus::Split:
      return "split";
    case RefStatus::Merged:
      return "merged";
    case RefStatus::Lost:
      return "lost";
  }
  return "";
}

namespace {

// Graph ids are left out: a restored cell's nodes and the live ones name one entity by node and topo id.
std::string member_key(const std::string& node_id, int slot, Kind kind, const std::string& topo_id) {
  return node_id + '\x1f' + std::to_string(slot) + '\x1f' + std::string(kind_name(kind)) + '\x1f' + topo_id;
}
std::string member_key(const TopoRef& ref) {
  return member_key(ref.node_id, ref.output_slot, ref.kind, ref.topo_id);
}

// Ops whose output is the input, re-attributed (a tag assignment) or cut down to sub-shapes that keep the
// source's topo ids (a selection): the only ones a lineage may cross without recorded history.
bool identity_op(const std::string& op) {
  return op.starts_with("make_select_") || op.starts_with("apply_tag") || op == "attach_semantic_graph_node";
}

int rank(TopoEvent event) {
  switch (event) {
    case TopoEvent::Preserved:
      return 0;
    case TopoEvent::Modified:
      return 1;
    case TopoEvent::Generated:
      return 2;
    case TopoEvent::Deleted:
      return 3;
  }
  return 0;
}

std::string text_field(const Value& metadata, const char* key) {
  if (!metadata.is_object())
    return {};
  const Value* found = metadata.find(key);
  return found != nullptr && found->is_string() ? found->as_string() : std::string{};
}

bool has_history(const OperationNode& node) {
  if (!node.topo_delta)
    return false;
  const TopoDelta& d = *node.topo_delta;
  return !d.entries.empty();
}

// Every entity the anchor became, at every node on the way (a DAG: one entity can continue down several branches).
struct Members {
  std::unordered_map<std::string, TopoRef> by_key;
  std::vector<std::string> order;                     // insertion order, for deterministic output
  std::unordered_map<std::string, std::string> root;  // alias key -> the key of the entity it re-names

  // An identity op's alias names the same entity: the key of the entity it stands for.
  std::string canonical(const std::string& key) const {
    const auto found = root.find(key);
    return found == root.end() ? key : found->second;
  }

  std::unordered_map<std::string, std::vector<std::string>> by_node;  // node id -> member keys, in order

  bool has(const TopoRef& ref) const { return by_key.count(member_key(ref)) != 0; }
  void add(const TopoRef& ref) {
    const std::string key = member_key(ref);
    if (by_key.emplace(key, ref).second) {
      order.push_back(key);
      by_node[ref.node_id].push_back(key);
    }
  }
};

struct Death {
  std::size_t order = 0;
  std::string node_id;
  std::string reason;
};

std::string param_text(const Value& params, const char* key) {
  return text_field(params, key);
}

void sort_unique(std::vector<TopoRef>& refs) {
  std::sort(refs.begin(), refs.end(), [](const TopoRef& a, const TopoRef& b) { return member_key(a) < member_key(b); });
  refs.erase(std::unique(refs.begin(), refs.end(),
                         [](const TopoRef& a, const TopoRef& b) { return member_key(a) == member_key(b); }),
             refs.end());
}

}  // namespace

ResolvedRef resolve_by_history(const NodePtr& target, const ElementAnchor& anchor, int target_slot, FollowMode mode) {
  ResolvedRef out;
  if (!target) {
    out.reason = "unknown_node";
    return out;
  }
  const std::vector<NodePtr> closure = upstream_closure({target});
  std::size_t start = closure.size();
  for (std::size_t i = 0; i < closure.size(); ++i) {
    if (closure[i]->node_id == anchor.node_id) {
      start = i;
      break;
    }
  }
  if (start == closure.size()) {
    out.reason = "not_downstream";
    out.lost_at = target->node_id;
    return out;
  }

  Members members;
  members.add(TopoRef{closure[start]->graph_id, anchor.node_id, anchor.output_slot, anchor.kind, anchor.topo_id});
  std::vector<Death> deaths;

  for (std::size_t order = start + 1; order < closure.size(); ++order) {
    const OperationNode& node = *closure[order];
    // The members this node consumed: entities of the outputs of its inputs.
    std::vector<TopoRef> consumed;
    std::unordered_set<std::string> seen_inputs;
    for (const NodePtr& input : node.inputs) {
      if (!seen_inputs.insert(input->node_id).second)
        continue;
      const auto found = members.by_node.find(input->node_id);
      if (found == members.by_node.end())
        continue;
      for (const std::string& key : found->second)
        consumed.push_back(members.by_key.at(key));
    }
    if (consumed.empty())
      continue;

    RefHop hop;
    hop.node_id = node.node_id;
    hop.op = node.op;

    if (!has_history(node)) {
      if (!identity_op(node.op)) {
        deaths.push_back({order, node.node_id, "no_history"});
        continue;
      }
      // An identity op names what it passes on by the same topo ids.  A selection passes on sub-shapes of
      // one kind only.
      const std::string only = param_text(node.params, "target_kind");
      hop.untracked = true;
      for (const TopoRef& ref : consumed) {
        if (!only.empty() && only != kind_name(ref.kind))
          continue;
        TopoRef alias = ref;
        alias.graph_id = node.graph_id;
        alias.node_id = node.node_id;
        alias.output_slot = 0;
        hop.from.push_back(ref);
        hop.to.push_back(alias);
      }
      for (std::size_t i = 0; i < hop.to.size(); ++i) {
        members.add(hop.to[i]);
        members.root.emplace(member_key(hop.to[i]), members.canonical(member_key(hop.from[i])));
      }
      if (!hop.to.empty())
        out.hops.push_back(std::move(hop));
      continue;
    }

    // A node with history: continue the consumed members through the witnesses that name them.
    // Witnesses name an input entity by the node that made it, not by the identity op that passed it on: match
    // by the entity, and remember which consumed member (alias) stands for it.
    std::map<std::string, std::string> consumed_keys;  // canonical key -> consumed member key
    for (const TopoRef& ref : consumed)
      consumed_keys.emplace(members.canonical(member_key(ref)), member_key(ref));
    const auto lookup = [&](const TopoRef& ref) -> std::string {
      const auto found = consumed_keys.find(members.canonical(member_key(ref)));
      return found == consumed_keys.end() ? std::string{} : found->first;
    };
    std::set<std::string> mentioned, continued, deleted;
    std::vector<TopoRef> successors;
    std::set<std::string> successor_keys;
    for (const TopoEntry& entry : node.topo_delta->entries) {
      if (entry.event == TopoEvent::Deleted) {
        const std::string key = lookup(entry.ref);
        if (!key.empty()) {
          mentioned.insert(key);
          deleted.insert(key);
          hop.from.push_back(entry.ref);
          hop.event = TopoEvent::Deleted;
        }
        continue;
      }
      std::vector<std::string> hits;
      for (const TopoRef& parent : entry.parent_refs) {
        const std::string key = lookup(parent);
        if (!key.empty())
          hits.push_back(key);
      }
      if (hits.empty())
        continue;
      mentioned.insert(hits.begin(), hits.end());
      const bool same_kind = entry.ref.kind == anchor.kind;
      const bool follows = mode == FollowMode::Derived || (same_kind && entry.event != TopoEvent::Generated);
      if (!follows)
        continue;
      continued.insert(hits.begin(), hits.end());
      for (const std::string& key : hits)
        hop.from.push_back(members.by_key.at(consumed_keys.at(key)));
      if (hop.event != TopoEvent::Deleted && rank(entry.event) > rank(hop.event))
        hop.event = entry.event;
      if (hop.derivation.empty())
        hop.derivation = text_field(entry.metadata, "derivation");
      if (successor_keys.insert(member_key(entry.ref)).second)
        successors.push_back(entry.ref);
    }
    // A successor that is also a modification of an entity of the same kind outside the lineage absorbed it: a merge
    // (a boolean's section edges are generated by both operands, which is no merge of faces).
    for (const TopoEntry& entry : node.topo_delta->entries) {
      if (entry.event == TopoEvent::Deleted || entry.event == TopoEvent::Generated ||
          successor_keys.count(member_key(entry.ref)) == 0)
        continue;
      for (const TopoRef& parent : entry.parent_refs) {
        if (parent.kind == entry.ref.kind && lookup(parent).empty() && !members.has(parent))
          hop.merged = true;
      }
    }
    for (const TopoRef& ref : successors) {
      members.add(ref);
      hop.to.push_back(ref);
    }
    for (const TopoRef& ref : consumed) {
      const std::string key = members.canonical(member_key(ref));
      if (continued.count(key) != 0)
        continue;
      deaths.push_back({order, node.node_id,
                        deleted.count(key) != 0 ? "deleted" : (mentioned.count(key) != 0 ? "replaced" : "no_history")});
    }
    sort_unique(hop.from);
    if (!hop.from.empty() || !hop.to.empty())
      out.hops.push_back(std::move(hop));
  }

  for (const std::string& key : members.by_node[target->node_id]) {
    const TopoRef& ref = members.by_key.at(key);
    if (ref.output_slot == target_slot && (mode == FollowMode::Derived || ref.kind == anchor.kind))
      out.targets.push_back(ref);
  }
  sort_unique(out.targets);
  if (out.targets.empty()) {
    if (!deaths.empty()) {
      const Death& last = *std::max_element(deaths.begin(), deaths.end(),
                                            [](const Death& a, const Death& b) { return a.order < b.order; });
      out.lost_at = last.node_id;
      out.reason = last.reason;
    } else {
      out.lost_at = target->node_id;
      out.reason = "not_in_target";
    }
    return out;
  }
  // Keep the hops on the way to the targets (a branch that leads elsewhere is not this reference's history),
  // and call it merged only when one of those merged.
  std::set<std::string> needed;
  for (const TopoRef& ref : out.targets)
    needed.insert(member_key(ref));
  std::vector<RefHop> path;
  for (auto hop = out.hops.rbegin(); hop != out.hops.rend(); ++hop) {
    const bool leads = std::any_of(hop->to.begin(), hop->to.end(),
                                   [&](const TopoRef& ref) { return needed.count(member_key(ref)) != 0; });
    if (!leads)
      continue;
    for (const TopoRef& ref : hop->from)
      needed.insert(member_key(ref));
    path.push_back(std::move(*hop));
  }
  std::reverse(path.begin(), path.end());
  out.hops = std::move(path);
  const bool merged = std::any_of(out.hops.begin(), out.hops.end(), [](const RefHop& h) { return h.merged; });
  out.status = out.targets.size() > 1 ? RefStatus::Split : (merged ? RefStatus::Merged : RefStatus::Ok);
  return out;
}

std::vector<ElementAnchor> anchors_for_role(const NodePtr& start, std::string_view role) {
  std::vector<ElementAnchor> out;
  // A tag assignment re-attributes the output of the node that made it (extrude_rsolid(..., end_face_tag=...)
  // returns the tag node's value): the roles are that node's.
  NodePtr node = start;
  while (node && !has_history(*node) && identity_op(node->op) && !node->inputs.empty())
    node = node->inputs.front();
  if (!node || !node->topo_delta)
    return out;
  for (const TopoRoleEntry& entry : node->topo_delta->roles) {
    if (entry.role == role && entry.ref.node_id == node->node_id)
      out.push_back(ElementAnchor{node->node_id, entry.ref.output_slot, entry.ref.kind, entry.ref.topo_id});
  }
  return out;
}

std::vector<Shape> subshapes_by_recorded_id(const Shape& root, Kind kind, const std::vector<std::string>& ids) {
  std::vector<std::optional<Shape>> found(ids.size());
  TopTools_IndexedMapOfShape map;
  TopExp::MapShapes(root.wrapped(), detail::topabs_of(kind), map);
  const std::string prefix = std::string(kind_name(kind)) + "_";
  for (int i = 1; i <= map.Extent(); ++i) {
    const Shape sub = root.sub(map(i));
    const std::string recorded = prefix + sub.topo_id();
    for (std::size_t k = 0; k < ids.size(); ++k) {
      if (!found[k] && ids[k] == recorded)
        found[k] = sub;
    }
  }
  std::vector<Shape> out;
  for (std::size_t k = 0; k < ids.size(); ++k) {
    if (!found[k])
      throw ValueError("no " + std::string(kind_name(kind)) + " '" + ids[k] + "' in the shape");
    out.push_back(*found[k]);
  }
  return out;
}

Value to_value(const ResolvedRef& resolved) {
  Value out = Value::object();
  out.set("status", std::string(to_string(resolved.status)));
  Value targets = Value::array();
  for (const TopoRef& ref : resolved.targets)
    targets.push_back(scad::to_value(ref));
  out.set("targets", std::move(targets));
  Value hops = Value::array();
  for (const RefHop& hop : resolved.hops) {
    Value item = Value::object();
    item.set("node_id", hop.node_id);
    item.set("op", hop.op);
    item.set("event", std::string(scad::to_string(hop.event)));
    item.set("derivation", hop.derivation);
    item.set("untracked", hop.untracked);
    item.set("merged", hop.merged);
    Value from = Value::array(), to = Value::array();
    for (const TopoRef& ref : hop.from)
      from.push_back(scad::to_value(ref));
    for (const TopoRef& ref : hop.to)
      to.push_back(scad::to_value(ref));
    item.set("from", std::move(from));
    item.set("to", std::move(to));
    hops.push_back(std::move(item));
  }
  out.set("hops", std::move(hops));
  out.set("lost_at", resolved.lost_at.empty() ? Value() : Value(resolved.lost_at));
  out.set("reason", resolved.reason.empty() ? Value() : Value(resolved.reason));
  return out;
}

}  // namespace scad::reactive
