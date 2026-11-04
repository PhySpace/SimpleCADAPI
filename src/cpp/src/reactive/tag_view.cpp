#include "scad/reactive/tag_view.hpp"

#include <algorithm>
#include <cctype>
#include <map>
#include <mutex>
#include <unordered_set>

#include "scad/reactive/lineage.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad::reactive {

namespace {

const Value* member(const Value& object, const char* key) {
  return object.is_object() ? object.find(key) : nullptr;
}

std::string text(const Value* value) {
  return value != nullptr && value->is_string() ? value->as_string() : std::string{};
}

std::optional<Kind> kind_from(const std::string& name) {
  std::string lowered = name;
  std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  for (const Kind k : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid, Kind::Compound}) {
    if (kind_name(k) == lowered)
      return k;
  }
  return std::nullopt;
}

bool is_tag_op(const std::string& op) {
  return op.starts_with("apply_tag");
}

bool is_selection_op(const std::string& op) {
  return op.starts_with("make_select_");
}

bool has_history(const OperationNode& node) {
  return node.topo_delta && !node.topo_delta->entries.empty();
}

// The derivation a witness proves; nullopt for one no lineage policy speaks of.
std::optional<LineageDerivation> derivation_of(const TopoEntry& entry) {
  if (entry.event == TopoEvent::Preserved)
    return LineageDerivation::Continuation;
  const std::string token = text(member(entry.metadata, "derivation"));
  try {
    return parse_lineage_derivation(token.empty() ? "continuation" : token);
  } catch (const TagValidationError&) {
    return std::nullopt;
  }
}

void carry(std::vector<CarriedTag>& into, CarriedTag tag) {
  const auto same = std::find_if(into.begin(), into.end(),
                                 [&](const CarriedTag& t) { return t.binding.binding_id == tag.binding.binding_id; });
  if (same == into.end())
    into.push_back(std::move(tag));
}

// Which piece of a split the witness's entity is (the operation numbered them when it was recorded), if it is one.
std::optional<int> piece_of(const TopoEntry& entry) {
  const Value* piece = member(entry.metadata, "piece");
  const Value* pieces = member(entry.metadata, "pieces");
  if (piece == nullptr || pieces == nullptr || !piece->is_number() || !pieces->is_number() || pieces->as_double() < 2)
    return std::nullopt;
  return static_cast<int>(piece->as_double());
}

// The binding a piece carries: the same assignment under the piece's tag, with an id of its own (bindings are told
// apart by id), derived from the original, the operation and the piece so a replay names it alike.
TagBinding piece_binding(const TagBinding& binding, const std::string& node_id, int piece) {
  TagBinding out = binding;
  out.tag = Symbol(split_tag_name(binding.tag.str(), piece));
  out.binding_id =
      BindingId("tag_binding_" + uuid5_url_hex("simplecad:split-tag:" + std::string(binding.binding_id.str()) + ":" +
                                               node_id + ":" + std::to_string(piece)));
  return out;
}

void note_split(const TagView& view, std::map<std::pair<std::string, std::string>, TagSplit>& splits,
                const CarriedTag& tag, const TopoRef& parent, const TopoEntry& entry, const OperationNode& node,
                const std::string& piece_tag) {
  (void)view;
  TagSplit& split = splits[{std::string(tag.binding.binding_id.str()), parent.node_id + '\x1f' + parent.topo_id}];
  if (split.node_id.empty()) {
    split.tag = tag.binding.tag.str();
    split.node_id = node.node_id;
    split.op = node.op;
    split.source_topo_id = parent.topo_id;
  }
  const int piece = *piece_of(entry);
  if (split.into.size() <= static_cast<std::size_t>(piece)) {
    split.into.resize(static_cast<std::size_t>(piece) + 1);
    split.pieces.resize(static_cast<std::size_t>(piece) + 1);
  }
  split.into[static_cast<std::size_t>(piece)] = piece_tag;
  split.pieces[static_cast<std::size_t>(piece)] = entry.ref;
}

// The entities a tag assignment targets, as keys of its own output (slot 0).
std::vector<std::pair<std::string, std::string>> targets_of(const TagBinding& binding) {
  std::vector<Value> refs;
  if (binding.target().kind == TagTargetKind::ExplicitRefs) {
    refs = binding.target().refs;
  } else if (binding.target().kind == TagTargetKind::SelectionQuery) {
    if (const Value* selected = member(binding.evidence->data, "selected_refs"); selected && selected->is_array())
      refs = selected->as_array();
  }
  std::vector<std::pair<std::string, std::string>> out;
  for (const Value& ref : refs) {
    const auto kind = kind_from(text(member(ref, "kind")));
    const std::string topo_id = text(member(ref, "topo_id"));
    if (kind && !topo_id.empty())
      out.emplace_back(tag_view_key(0, *kind, topo_id), topo_id);
  }
  return out;
}

// Whether the assignment named one entity (not a set of them).
bool names_one(const TagBinding& binding) {
  return targets_of(binding).size() <= 1;
}

// The view of `node`, given the views of its inputs.
TagView build_view(const OperationNode& node,
                   const std::unordered_map<const OperationNode*, std::shared_ptr<const TagView>>& done) {
  TagView view;
  const auto input_view = [&](const NodePtr& input) -> const TagView& {
    static const TagView empty;
    const auto found = done.find(input.get());
    return found != done.end() ? *found->second : empty;
  };
  const int first_slot = node.bindings.empty() ? 0 : node.bindings.front().output_slot;
  // Keys of one slot of an input, renamed to this node's single output.
  const auto pass_on = [&](const TagView& from, int slot, const std::string& only_kind) {
    const std::string prefix = std::to_string(slot) + '\x1f';
    for (const auto& [key, tags] : from) {
      if (!key.starts_with(prefix))
        continue;
      const std::string rest = key.substr(prefix.size());
      if (!only_kind.empty() && !rest.starts_with(only_kind + '\x1f'))
        continue;
      auto& into = view["0\x1f" + rest];
      for (const CarriedTag& tag : tags)
        carry(into, tag);
    }
  };

  if (!has_history(node)) {
    if (node.inputs.empty())
      return view;  // a creator: nothing upstream
    if (is_selection_op(node.op)) {
      pass_on(input_view(node.inputs.front()), first_slot, text(member(node.params, "target_kind")));
      return view;
    }
    if (!is_tag_op(node.op))
      return view;  // no history: the tags end here
    pass_on(input_view(node.inputs.front()), first_slot, {});
    const Value* payload = member(node.params, "tag_binding");
    if (payload == nullptr || !payload->is_object())
      return view;
    TagBinding binding;
    try {
      binding = tag_binding_from_value(*payload);
    } catch (const std::exception&) {
      return view;  // a malformed payload names nothing
    }
    for (const auto& [key, topo_id] : targets_of(binding))
      carry(view[key], CarriedTag{binding, LineageDerivation::Continuation, node.node_id, topo_id, node.op});
    return view;
  }

  // An entity of an input is named by the node that made it, which may sit behind identity ops (a tag node keeps
  // its producer as the topology owner): map every such owner to the views that hold its entities.
  struct Holder {
    const TagView* view;
    bool alias;  // the view is an identity op's: keyed by slot 0
  };
  std::unordered_map<std::string, std::vector<Holder>> holders;
  for (const NodePtr& input : node.inputs) {
    const TagView& held = input_view(input);
    holders[input->node_id].push_back({&held, false});
    NodePtr owner = input;
    while (owner && !has_history(*owner) && (is_tag_op(owner->op) || is_selection_op(owner->op)) &&
           !owner->inputs.empty()) {
      owner = owner->inputs.front();
      holders[owner->node_id].push_back({&held, true});
    }
  }
  const auto carried_by = [&](const TopoRef& parent) {
    std::vector<const CarriedTag*> out;
    const auto found = holders.find(parent.node_id);
    if (found == holders.end())
      return out;
    for (const Holder& holder : found->second) {
      const auto hit =
          holder.view->find(tag_view_key(holder.alias ? 0 : parent.output_slot, parent.kind, parent.topo_id));
      if (hit == holder.view->end())
        continue;
      for (const CarriedTag& tag : hit->second)
        out.push_back(&tag);
    }
    return out;
  };

  // The splits of this node, by (binding, entity it was), in the order they are met.
  std::map<std::pair<std::string, std::string>, TagSplit> splits;
  for (const TopoEntry& entry : node.topo_delta->entries) {
    if (entry.event == TopoEvent::Deleted)
      continue;
    const std::optional<LineageDerivation> derivation = derivation_of(entry);
    if (!derivation)
      continue;
    // Continuation only: a generated entity named after its source is the operation's own projected binding
    // (semantic/autotag.cpp), stored on it when the operation ran.
    if (entry.event == TopoEvent::Generated)
      continue;
    const std::string key = tag_view_key(entry.ref.output_slot, entry.ref.kind, entry.ref.topo_id);
    const std::optional<int> piece = piece_of(entry);
    for (const TopoRef& parent : entry.parent_refs) {
      for (const CarriedTag* tag : carried_by(parent)) {
        if (parent.kind != entry.ref.kind || !lineage_policy_allows(tag->binding.propagation(), *derivation))
          continue;
        CarriedTag next = *tag;
        next.derivation = *derivation;
        next.op = node.op;
        // A tag that names one entity follows it as a reference does: split, the pieces are named <tag>.split<i>.  A
        // tag given to several entities at once names a set (every side face of an extrusion): a piece of a member is
        // still a member, so it keeps the tag and nothing is reported.
        if (piece && names_one(tag->binding)) {
          next.binding = piece_binding(tag->binding, node.node_id, *piece);
          note_split(view, splits, *tag, parent, entry, node, next.binding.tag.str());
        }
        carry(view[key], std::move(next));
      }
    }
  }
  for (auto& [_, split] : splits)
    view.splits.push_back(std::move(split));
  return view;
}

struct Cache {
  std::mutex mutex;
  std::unordered_map<const OperationNode*,
                     std::pair<std::weak_ptr<const OperationNode>, std::shared_ptr<const TagView>>>
      views;
};

Cache& cache() {
  static Cache instance;
  return instance;
}

std::vector<TagLineageWitness> provider(const Shape& entity) {
  return history_witnesses(entity);
}

}  // namespace

std::string split_tag_name(std::string_view tag, int piece) {
  return std::string(tag) + ".split" + std::to_string(piece + 1);
}

std::vector<TagSplit> tag_splits(const NodePtr& node) {
  std::vector<TagSplit> out;
  if (!node)
    return out;
  tag_view(node);  // builds (and caches) the views of the whole closure
  Cache& c = cache();
  for (const NodePtr& item : upstream_closure({node})) {
    std::shared_ptr<const TagView> view;
    {
      const std::lock_guard<std::mutex> lock(c.mutex);
      if (const auto found = c.views.find(item.get()); found != c.views.end() && found->second.first.lock() == item)
        view = found->second.second;
    }
    if (!view)
      view = tag_view(item);
    out.insert(out.end(), view->splits.begin(), view->splits.end());
  }
  return out;
}

std::string tag_view_key(int output_slot, Kind kind, const std::string& recorded_topo_id) {
  return std::to_string(output_slot) + '\x1f' + std::string(kind_name(kind)) + '\x1f' + recorded_topo_id;
}

std::shared_ptr<const TagView> tag_view(const NodePtr& node) {
  if (!node)
    return std::make_shared<const TagView>();
  Cache& c = cache();
  {
    const std::lock_guard<std::mutex> lock(c.mutex);
    if (const auto found = c.views.find(node.get());
        found != c.views.end() && !found->second.first.expired() && found->second.first.lock() == node)
      return found->second.second;
  }
  // Inputs first, each once: the views of the whole upstream closure, reusing what is cached.
  std::unordered_map<const OperationNode*, std::shared_ptr<const TagView>> done;
  for (const NodePtr& item : upstream_closure({node})) {
    std::shared_ptr<const TagView> view;
    {
      const std::lock_guard<std::mutex> lock(c.mutex);
      if (const auto found = c.views.find(item.get()); found != c.views.end() && found->second.first.lock() == item)
        view = found->second.second;
    }
    if (!view) {
      view = std::make_shared<const TagView>(build_view(*item, done));
      const std::lock_guard<std::mutex> lock(c.mutex);
      if (c.views.size() > 16384) {
        for (auto it = c.views.begin(); it != c.views.end();)
          it = it->second.first.expired() ? c.views.erase(it) : std::next(it);
      }
      c.views[item.get()] = {item, view};
    }
    done.emplace(item.get(), std::move(view));
  }
  return done.at(node.get());
}

std::vector<TagLineageWitness> history_witnesses(const Shape& entity) {
  const Shape root = entity.root();
  const auto opaque = root.graph_node();
  if (!opaque)
    return {};
  const auto node = std::static_pointer_cast<const OperationNode>(opaque);
  const std::optional<Lineage> lineage = lineage_of(root);
  const int slot = lineage ? lineage->output_slot : 0;
  const std::shared_ptr<const TagView> view = tag_view(node);
  const auto found =
      view->find(tag_view_key(slot, entity.kind(), std::string(kind_name(entity.kind())) + "_" + entity.topo_id()));
  if (found == view->end())
    return {};
  std::vector<TagLineageWitness> out;
  out.reserve(found->second.size());
  for (const CarriedTag& tag : found->second) {
    TagLineageWitness witness;
    witness.binding = tag.binding;
    witness.derivation = tag.derivation;
    witness.source_topo_id = tag.source_topo_id;
    witness.target_topo_id = entity.topo_id();
    TagEvidence evidence;
    evidence.kind = TagEvidenceKind::TopologyChange;
    evidence.data = Value::object();
    evidence.data.set("op", tag.op);
    evidence.data.set("derivation", std::string(to_string(tag.derivation)));
    evidence.data.set("coverage", "complete");
    evidence.data.set("assigned_at", tag.source_node_id);
    evidence.data.set("via", "recorded_history");
    witness.evidence = Cow<TagEvidence>(std::move(evidence));
    witness.coverage = "complete";
    out.push_back(std::move(witness));
  }
  return out;
}

void install_tag_view() noexcept {
  set_history_witness_provider(&provider);
}

}  // namespace scad::reactive
