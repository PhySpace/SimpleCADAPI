// Tag, lineage and metadata access on Shape: the semantics of TaggedMixin
// (simplecadapi/core.py), over the lazily allocated SemanticState.
//
// What a shape can show, by scope:
//   local      the bindings its own entity stores
//   inherited  downward bindings of its ancestors, computed on demand from containment
//   effective  local + inherited + legacy snapshots (never lineage)
//   lineage    bindings that reach it through proven topology history (witnesses)
//
// Nothing is copied down: tagging a solid with downward propagation touches one
// entity, and its faces, wires, edges and vertices see the tag through their
// ancestors.  While a root holds no downward binding at all, inheritance is not even
// looked up.
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListIteratorOfListOfShape.hxx>

#include <algorithm>
#include <atomic>
#include <limits>
#include <set>
#include <unordered_set>

#include "internal.hpp"
#include "scad/core/error.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad {

namespace {

constexpr std::string_view kCoverageKey = "semantic.lineage.coverage";
constexpr std::size_t kNone = std::numeric_limits<std::size_t>::max();

bool is_local(const TagBinding& b) noexcept {
  return b.attachment == TagAttachment::Local;
}
bool is_legacy(const TagBinding& b) noexcept {
  return b.attachment == TagAttachment::EffectiveLegacy;
}
bool is_downward(const TagBinding& b) noexcept {
  return b.propagation().topology == TopologyPropagation::Downward;
}

bool starts_with(std::string_view s, std::string_view prefix) {
  return s.substr(0, prefix.size()) == prefix;
}

[[noreturn]] void legacy_scope_unsupported() {
  throw UnsupportedQueryCapabilityError("legacy effective tag snapshots only support effective scope");
}

// ---------------------------------------------------------------------------
// Containment, the way the Python wrapper tree links it: vertex < edge < wire < face <
// solid | shell, solid < compound (a shell inside a solid is transparent).  Links
// that enumeration established (a shell's free-boundary wires) are added.
// ---------------------------------------------------------------------------
std::vector<std::shared_ptr<Entity>> direct_parents(Registry& registry, const Entity& entity) {
  std::vector<std::shared_ptr<Entity>> out;
  auto add = [&out](std::shared_ptr<Entity> parent) {
    if (parent && std::find(out.begin(), out.end(), parent) == out.end())
      out.push_back(std::move(parent));
  };
  auto containing = [&](Kind parent_kind) {
    std::size_t found = 0;
    const auto& map = registry.ancestors(entity.kind, parent_kind);
    const int index = map.FindIndex(entity.shape);
    if (index == 0)
      return found;
    for (TopTools_ListIteratorOfListOfShape it(map.FindFromIndex(index)); it.More(); it.Next()) {
      add(registry.acquire(parent_kind, it.Value()));
      ++found;
    }
    return found;
  };
  switch (entity.kind) {
    case Kind::Vertex:
      containing(Kind::Edge);
      break;
    case Kind::Edge:
      containing(Kind::Wire);
      break;
    case Kind::Wire:
      containing(Kind::Face);
      break;
    case Kind::Face:
      if (containing(Kind::Solid) == 0)
        containing(Kind::Shell);
      break;
    case Kind::Solid:
      containing(Kind::Compound);
      break;
    case Kind::Shell:
    case Kind::Compound:
      break;
  }
  for (const auto& weak : entity.parents)
    add(weak.lock());
  return out;
}

struct AncestorNode {
  std::shared_ptr<Entity> entity;
  std::size_t from;  // index of the node this one was reached from; kNone for the start
};

// Breadth-first over the ancestors of `start`.  `visit(binding, nodes, index)` is called for
// every downward local binding of an ancestor, first sight of each binding id only; return
// true to stop.
template <class Visit>
void walk_inherited(Registry& registry, const std::shared_ptr<Entity>& start, Visit&& visit) {
  std::vector<AncestorNode> nodes;
  nodes.push_back({start, kNone});
  std::unordered_set<const Entity*> seen_entities{start.get()};
  std::unordered_set<BindingId> seen_bindings;
  for (std::size_t i = 0; i < nodes.size(); ++i) {
    if (i > 0) {
      if (const SemanticState* state = nodes[i].entity->state_if()) {
        for (const TagBinding& binding : state->bindings) {
          if (!is_local(binding) || !is_downward(binding))
            continue;
          if (!seen_bindings.insert(binding.binding_id).second)
            continue;
          if (visit(binding, nodes, i))
            return;
        }
      }
    }
    for (auto& parent : direct_parents(registry, *nodes[i].entity))
      if (seen_entities.insert(parent.get()).second)
        nodes.push_back({std::move(parent), i});
  }
}

std::vector<std::string> path_of(const std::vector<AncestorNode>& nodes, std::size_t index) {
  std::vector<std::string> path;  // ancestor first, the shape itself last
  for (; index != kNone; index = nodes[index].from)
    path.push_back(nodes[index].entity->topo_id.str());
  return path;
}

bool same_witness(const TagLineageWitness& a, const TagLineageWitness& b) {
  return a.binding.binding_id == b.binding.binding_id && a.derivation == b.derivation &&
         a.source_topo_id == b.source_topo_id && a.target_topo_id == b.target_topo_id;
}

bool any_downward(const std::vector<TagBinding>& bindings) {
  return std::any_of(bindings.begin(), bindings.end(), is_downward);
}

}  // namespace

// ---------------------------------------------------------------------------
// Storing bindings
// ---------------------------------------------------------------------------
void Shape::add_binding(TagBinding binding) {
  binding.validate();
  SemanticState& state = entity_->state();
  const bool duplicate = std::any_of(state.bindings.begin(), state.bindings.end(),
                                     [&](const TagBinding& b) { return b.binding_id == binding.binding_id; });
  if (duplicate)
    return;
  if (is_downward(binding))
    registry_->has_downward_bindings = true;
  state.bindings.push_back(std::move(binding));
}

void Shape::add_tag(std::string_view tag) {
  add_binding(internal_tag_binding(normalize_tag(tag, true)));
}

void Shape::apply_tag(std::string_view tag, bool propagate) {
  InternalTagOptions options;
  options.topology = propagate ? TopologyPropagation::Downward : TopologyPropagation::Local;
  add_binding(internal_tag_binding(normalize_tag(tag, true), options));
}

void Shape::add_tag_lineage(const TagBinding& binding, LineageDerivation derivation, std::string_view source_topo_id,
                            TagEvidence evidence, std::string_view coverage) {
  TagLineageWitness witness;
  witness.binding = binding;
  witness.derivation = derivation;
  witness.source_topo_id = std::string(source_topo_id);
  witness.target_topo_id = topo_id();
  witness.evidence = std::move(evidence);
  witness.coverage = std::string(coverage);
  add_lineage_witness(std::move(witness));
}

void Shape::add_lineage_witness(TagLineageWitness witness) {
  witness.validate();
  SemanticState& state = entity_->state();
  const bool duplicate = std::any_of(state.lineage.begin(), state.lineage.end(),
                                     [&](const TagLineageWitness& w) { return same_witness(w, witness); });
  if (!duplicate)
    state.lineage.push_back(std::move(witness));
}

std::size_t Shape::remove_tag_bindings(std::string_view tag, TagProducerKind matching) {
  const std::string normalized = normalize_tag(tag, true);
  SemanticState* state = entity_->sem.get();
  if (state == nullptr)
    return 0;
  const auto doomed = [&](const TagBinding& b) { return b.tag == normalized && b.producer().kind == matching; };
  const auto removed = static_cast<std::size_t>(std::count_if(state->bindings.begin(), state->bindings.end(), doomed));
  if (removed != 0) {
    state->bindings.erase(std::remove_if(state->bindings.begin(), state->bindings.end(), doomed),
                          state->bindings.end());
  }
  return removed;
}

std::size_t Shape::remove_tag_bindings(std::string_view tag, const TagProducer& matching) {
  const std::string normalized = normalize_tag(tag, true);
  SemanticState* state = entity_->sem.get();
  if (state == nullptr)
    return 0;
  const auto doomed = [&](const TagBinding& b) { return b.tag == normalized && b.producer() == matching; };
  const auto removed = static_cast<std::size_t>(std::count_if(state->bindings.begin(), state->bindings.end(), doomed));
  if (removed != 0) {
    state->bindings.erase(std::remove_if(state->bindings.begin(), state->bindings.end(), doomed),
                          state->bindings.end());
  }
  return removed;
}

bool Shape::remove_tag(std::string_view tag, TagScope scope) {
  if (scope != TagScope::Local)
    throw ValueError("only local tags can be removed");
  return remove_tag_bindings(tag, TagProducerKind::UserOperation) != 0;
}

bool Shape::remove_tag_binding(std::string_view binding_id) {
  if (binding_id.empty())
    throw ValueError("binding_id must be a non-empty string");
  SemanticState* state = entity_->sem.get();
  if (state == nullptr)
    return false;
  const auto before = state->bindings.size();
  state->bindings.erase(std::remove_if(state->bindings.begin(), state->bindings.end(),
                                       [&](const TagBinding& b) { return b.binding_id == binding_id; }),
                        state->bindings.end());
  return state->bindings.size() != before;
}

void Shape::replace_local_tag_bindings(std::vector<TagBinding> bindings) {
  for (const auto& b : bindings)
    b.validate();
  SemanticState& state = entity_->state();
  state.bindings.erase(std::remove_if(state.bindings.begin(), state.bindings.end(), is_local), state.bindings.end());
  if (any_downward(bindings))
    registry_->has_downward_bindings = true;
  for (auto& b : bindings)
    state.bindings.push_back(std::move(b));
}

void Shape::set_legacy_tags(const std::vector<std::string>& tags) {
  std::vector<TagBinding> imported;
  imported.reserve(tags.size());
  for (const auto& tag : tags)
    imported.push_back(legacy_tag_binding(normalize_tag(tag, true), "Imported from a direct legacy _tags assignment."));
  SemanticState& state = entity_->state();
  state.bindings = std::move(imported);
  state.lineage.clear();
}

void Shape::refresh_tag_cache(bool recursive) {
  (void)recursive;  // tag names are read off the bindings: there is no cache to refresh
}

const std::vector<TagBinding>& Shape::local_bindings() const {
  static const std::vector<TagBinding> empty;
  const SemanticState* state = entity_->state_if();
  return state != nullptr ? state->bindings : empty;
}

const std::vector<TagLineageWitness>& Shape::lineage_witnesses() const {
  static const std::vector<TagLineageWitness> empty;
  const SemanticState* state = entity_->state_if();
  return state != nullptr ? state->lineage : empty;
}

// ---------------------------------------------------------------------------
// Reading bindings
// ---------------------------------------------------------------------------
std::vector<TagBinding> Shape::local_tag_bindings() const {
  std::vector<TagBinding> out;
  for (const auto& b : local_bindings())
    if (is_local(b))
      out.push_back(b);
  return out;
}

std::vector<TagBinding> Shape::legacy_effective_bindings() const {
  std::vector<TagBinding> out;
  for (const auto& b : local_bindings())
    if (is_legacy(b))
      out.push_back(b);
  return out;
}

std::vector<InheritedTagBinding> Shape::inherited_tag_bindings_with_paths() const {
  std::vector<InheritedTagBinding> out;
  if (!registry_->has_downward_bindings)
    return out;
  walk_inherited(*registry_, entity_,
                 [&](const TagBinding& binding, const std::vector<AncestorNode>& nodes, std::size_t at) {
                   out.push_back({binding, path_of(nodes, at)});
                   return false;
                 });
  return out;
}

std::vector<TagBinding> Shape::inherited_tag_bindings() const {
  std::vector<TagBinding> out;
  if (!registry_->has_downward_bindings)
    return out;
  walk_inherited(*registry_, entity_, [&](const TagBinding& binding, const std::vector<AncestorNode>&, std::size_t) {
    out.push_back(binding);
    return false;
  });
  return out;
}

std::vector<TagBinding> Shape::lineage_tag_bindings() const {
  const SemanticState* state = entity_->state_if();
  Value coverage_scratch;
  const Value* coverage = state != nullptr ? state->peek_runtime(kCoverageKey, coverage_scratch) : nullptr;
  if (coverage == nullptr || !coverage->is_string() || coverage->as_string() != "complete") {
    const std::string available =
        coverage == nullptr ? "none" : (coverage->is_string() ? coverage->as_string() : coverage->dump());
    throw UnsupportedQueryCapabilityError("lineage tag scope requires complete topology history; coverage=" +
                                          available);
  }
  std::vector<TagBinding> out;
  if (state == nullptr)
    return out;
  for (const auto& w : state->lineage)
    if (w.coverage != "complete")
      throw UnsupportedQueryCapabilityError("lineage tag scope has incomplete lineage witnesses");
  std::set<std::string> seen;
  for (const auto& w : state->lineage)
    if (lineage_policy_allows(w.binding.propagation(), w.derivation) && seen.insert(w.binding.binding_id).second)
      out.push_back(w.binding);
  return out;
}

std::vector<TagBinding> Shape::list_tag_bindings(TagScope scope) const {
  const SemanticState* state = entity_->state_if();
  if (scope != TagScope::Effective && state != nullptr && state->has_legacy())
    legacy_scope_unsupported();
  switch (scope) {
    case TagScope::Local:
      return local_tag_bindings();
    case TagScope::Inherited:
      return inherited_tag_bindings();
    case TagScope::Lineage:
      return lineage_tag_bindings();
    case TagScope::Effective:
      break;
  }
  std::vector<TagBinding> all = local_tag_bindings();
  for (auto& b : inherited_tag_bindings())
    all.push_back(std::move(b));
  for (auto& b : legacy_effective_bindings())
    all.push_back(std::move(b));
  std::vector<TagBinding> unique;
  std::set<std::string> seen;
  for (auto& b : all)
    if (seen.insert(b.binding_id).second)
      unique.push_back(std::move(b));
  return unique;
}

std::vector<std::string> Shape::list_tags(TagScope scope) const {
  const SemanticState* state = entity_->state_if();
  if (scope != TagScope::Effective && state != nullptr && state->has_legacy())
    legacy_scope_unsupported();
  std::set<std::string> names;
  switch (scope) {
    case TagScope::Local:
      if (state != nullptr)
        for (const auto& b : state->bindings)
          if (!is_legacy(b))
            names.insert(b.tag.str());
      break;
    case TagScope::Inherited:
      for (const auto& b : inherited_tag_bindings())
        names.insert(b.tag);
      break;
    case TagScope::Lineage:
      for (const auto& b : lineage_tag_bindings())
        names.insert(b.tag);
      break;
    case TagScope::Effective:
      if (state != nullptr)
        for (const auto& b : state->bindings)
          names.insert(b.tag.str());
      for (const auto& b : inherited_tag_bindings())
        names.insert(b.tag.str());
      break;
  }
  return {names.begin(), names.end()};
}

bool Shape::has_stored_tag(std::string_view tag) const {
  const SemanticState* state = entity_->state_if();
  const std::optional<Symbol> symbol = Symbol::find(tag);
  if (!symbol || state == nullptr)
    return false;
  return std::any_of(state->bindings.begin(), state->bindings.end(),
                     [&](const TagBinding& b) { return b.tag == *symbol && !is_legacy(b); });
}

bool Shape::has_tag(std::string_view tag, TagScope scope) const {
  const SemanticState* state = entity_->state_if();
  if (scope != TagScope::Effective && state != nullptr && state->has_legacy())
    legacy_scope_unsupported();
  // The lineage scope answers (or refuses: incomplete history) whatever the name is.
  if (scope == TagScope::Lineage) {
    const auto bindings = lineage_tag_bindings();
    const std::optional<Symbol> wanted = Symbol::find(tag);
    return wanted &&
           std::any_of(bindings.begin(), bindings.end(), [&](const TagBinding& b) { return b.tag == *wanted; });
  }
  // A name nobody interned cannot be held by any binding.
  const std::optional<Symbol> symbol = Symbol::find(tag);
  if (!symbol)
    return false;
  const auto holds = [&](bool legacy) {
    return state != nullptr && std::any_of(state->bindings.begin(), state->bindings.end(), [&](const TagBinding& b) {
             return b.tag == *symbol && is_legacy(b) == legacy;
           });
  };
  const auto stored = [&] { return holds(false); };
  const auto inherited = [&] {
    if (!registry_->has_downward_bindings)
      return false;
    bool found = false;
    walk_inherited(*registry_, entity_, [&](const TagBinding& b, const std::vector<AncestorNode>&, std::size_t) {
      found = b.tag == *symbol;
      return found;
    });
    return found;
  };
  switch (scope) {
    case TagScope::Local:
      return stored();
    case TagScope::Inherited:
      return inherited();
    case TagScope::Effective:
      return stored() || holds(true) || inherited();
    case TagScope::Lineage: {
      const auto bindings = lineage_tag_bindings();
      return std::any_of(bindings.begin(), bindings.end(), [&](const TagBinding& b) { return b.tag == *symbol; });
    }
  }
  return false;
}

std::vector<Value> Shape::explain_tag(std::string_view tag, TagScope scope) const {
  const std::string normalized = normalize_tag(tag, true);
  const auto inherited = inherited_tag_bindings_with_paths();
  const SemanticState* state = entity_->state_if();

  std::vector<Value> explanations;
  for (const TagBinding& binding : list_tag_bindings(scope)) {
    if (binding.tag != normalized)
      continue;
    Value item = Value::object();
    item.set("scope", std::string(scad::to_string(scope)));
    item.set("binding_id", binding.binding_id.str());
    item.set("producer", binding.producer().to_value());
    item.set("attachment", std::string(scad::to_string(binding.attachment)));
    item.set("binding", binding.to_value());

    const auto via = std::find_if(inherited.begin(), inherited.end(), [&](const InheritedTagBinding& i) {
      return i.binding.binding_id == binding.binding_id;
    });
    if (via != inherited.end()) {
      item.set("attachment", std::string(scad::to_string(TagAttachment::Inherited)));
      Value path = Value::array();
      for (const auto& id : via->path)
        path.push_back(id);
      item.set("topology_path", std::move(path));
    }

    Value witnesses = Value::array();
    if (state != nullptr) {
      for (const auto& w : state->lineage) {
        if (w.binding.binding_id != binding.binding_id || !lineage_policy_allows(binding.propagation(), w.derivation))
          continue;
        Value entry = Value::object();
        entry.set("derivation", std::string(scad::to_string(w.derivation)));
        entry.set("source_topo_id", w.source_topo_id);
        entry.set("target_topo_id", w.target_topo_id);
        entry.set("coverage", w.coverage);
        entry.set("evidence", w.evidence->to_value());
        witnesses.push_back(std::move(entry));
      }
    }
    if (witnesses.size() != 0)
      item.set("lineage", std::move(witnesses));
    explanations.push_back(std::move(item));
  }
  return explanations;
}

// ---------------------------------------------------------------------------
// Metadata and runtime values
// ---------------------------------------------------------------------------
void Shape::set_metadata(std::string key, Value value) {
  entity_->state().set_value(false, std::move(key), std::move(value));
}

bool Shape::has_metadata_key(std::string_view key) const {
  const SemanticState* state = entity_->state_if();
  return state != nullptr && state->has_key(false, key);
}

void Shape::set_metadata_deferred(std::string_view key, const Value& value) {
  SemanticState& state = entity_->state();
  if (state.has_key(false, key))
    state.metadata().set(std::string(key), value);
  else
    state.defer(false, Symbol(key), value);
}

void Shape::set_metadata_recipe(std::string_view key, unsigned char recipe, const Value& args) {
  SemanticState& state = entity_->state();
  if (state.has_key(false, key))
    state.metadata().set(std::string(key), PackedValue::from_recipe(recipe, args).unpack());
  else
    state.defer_packed(false, Symbol(key), PackedValue::from_recipe(recipe, args));
}

void Shape::set_runtime_deferred(std::string_view key, const Value& value) {
  SemanticState& state = entity_->state();
  if (state.has_key(true, key))
    state.runtime().set(std::string(key), value);
  else
    state.defer(true, Symbol(key), value);
}

Value Shape::get_metadata(std::string_view key, Value fallback) const {
  const SemanticState* state = entity_->state_if();
  if (state != nullptr) {
    Value scratch;
    if (const Value* v = state->peek(false, key, scratch))
      return *v;
  }
  return fallback;
}

const Value& Shape::metadata() const {
  static const Value empty = Value::object();
  const SemanticState* state = entity_->state_if();
  return state != nullptr ? state->metadata() : empty;
}

void Shape::set_runtime(std::string key, Value value) {
  entity_->state().set_value(true, std::move(key), std::move(value));
}

Value Shape::get_runtime(std::string_view key, Value fallback) const {
  const SemanticState* state = entity_->state_if();
  if (state != nullptr) {
    Value scratch;
    if (const Value* v = state->peek(true, key, scratch))
      return *v;
  }
  return fallback;
}

const Value& Shape::runtime() const {
  static const Value empty = Value::object();
  const SemanticState* state = entity_->state_if();
  return state != nullptr ? state->runtime() : empty;
}

// ---------------------------------------------------------------------------
// Copying semantic state
// ---------------------------------------------------------------------------
void Shape::copy_tag_state_from(const Shape& source) {
  const SemanticState* from = source.entity_->state_if();
  if (from == nullptr) {
    if (SemanticState* to = entity_->sem.get()) {
      to->bindings.clear();
      to->lineage.clear();
    }
    return;
  }
  SemanticState& to = entity_->state();
  to.bindings = from->bindings;
  to.lineage = from->lineage;
  if (any_downward(to.bindings))
    registry_->has_downward_bindings = true;
}

// _copy_semantic_state_from: tags, lineage, and the metadata/runtime that is not tied to
// a graph node, a topology reference or a mesh.
void Shape::copy_semantic_state_from(const Shape& source) {
  copy_tag_state_from(source);
  const SemanticState* from = source.entity_->state_if();
  SemanticState& to = entity_->state();
  to.clear_dictionaries();
  if (from == nullptr)
    return;
  for (const auto& [key, value] : from->metadata().as_object())
    if (key != "graph" && key != "topo_ref")
      to.metadata().set(key, value);
  for (const auto& [key, value] : from->runtime().as_object())
    if (!starts_with(key, "graph.") && !starts_with(key, "topo.") && !starts_with(key, "mesh."))
      to.runtime().set(key, value);
}

// clone_semantic_shape_view: a new root over the same geometry in which every entity
// carries a copy of the matching source entity's complete state (graph attachments
// included), under the same topo id.
namespace {
std::atomic<std::size_t> g_clone_views{0};
}

std::size_t Shape::clone_view_count() noexcept {
  return g_clone_views.load(std::memory_order_relaxed);
}

Shape Shape::clone_view() const {
  g_clone_views.fetch_add(1, std::memory_order_relaxed);
  Shape view = Shape::from_occt(shape_);
  Registry& from = *registry_;
  Registry& to = *view.registry_;

  const auto copy_state = [&](const Entity& source, Entity& target) {
    if (const SemanticState* state = source.state_if()) {
      target.state() = *state;
      if (any_downward(state->bindings))
        to.has_downward_bindings = true;
    }
  };
  const auto copy_entity = [&](const Entity& source, Entity& target) {
    copy_state(source, target);
    // A shell's free-boundary wires are made, not found in the shape: the view shares the same
    // wires and the state they hold (roles, tags), or it would enumerate new, empty ones.
    if (source.kind == Kind::Shell && source.free_wires != nullptr) {
      target.free_wires = std::make_unique<std::vector<TopoDS_Wire>>(*source.free_wires);
      for (const TopoDS_Wire& wire : *source.free_wires) {
        const auto wire_source = from.peek(Kind::Wire, wire);
        if (wire_source == nullptr || wire_source->state_if() == nullptr)
          continue;
        const auto wire_target = to.acquire(Kind::Wire, wire);
        wire_target->topo_id = wire_source->topo_id;
        copy_state(*wire_source, *wire_target);
      }
    }
  };

  if (shape_.IsSame(from.root())) {
    // Same root, same numbering: only entities that hold state need visiting.
    from.for_each_entity([&](const Entity& source) {
      if (source.state_if() == nullptr || !to.contains(source.kind, source.shape))
        return;
      copy_entity(source, *to.acquire(source.kind, source.shape));
    });
    return view;
  }

  // A sub-shape handle: the new root numbers its entities from scratch, so give every
  // one of them the id it has in the source and copy what the source knows.
  static constexpr Kind kinds[] = {Kind::Vertex, Kind::Edge,  Kind::Wire,    Kind::Face,
                                   Kind::Shell,  Kind::Solid, Kind::Compound};
  for (const Kind kind : kinds) {
    TopTools_IndexedMapOfShape members;
    TopExp::MapShapes(shape_, to_topabs(kind), members);
    for (int i = 1; i <= members.Extent(); ++i) {
      const TopoDS_Shape& member = members(i);
      const auto source = from.acquire(kind, member);
      const auto target = to.acquire(kind, member);
      target->topo_id = source->topo_id;
      copy_entity(*source, *target);
    }
  }
  return view;
}

}  // namespace scad
