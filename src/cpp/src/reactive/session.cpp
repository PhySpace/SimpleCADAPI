#include "scad/reactive/session.hpp"

#include <algorithm>
#include <map>
#include <set>
#include <cstdio>
#include <tuple>
#include <unordered_set>

#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include "internal.hpp"
#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/reactive/digest.hpp"
#include "scad/reactive/geo_selection.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/reactive/node_registry.hpp"
#include "scad/reactive/param_path.hpp"

namespace scad::reactive {

namespace detail {
Session*& active_session_slot() noexcept {
  thread_local Session* active = nullptr;
  return active;
}
}  // namespace detail

namespace {

TopAbs_ShapeEnum topabs(Kind kind) {
  switch (kind) {
    case Kind::Vertex:
      return TopAbs_VERTEX;
    case Kind::Edge:
      return TopAbs_EDGE;
    case Kind::Wire:
      return TopAbs_WIRE;
    case Kind::Face:
      return TopAbs_FACE;
    case Kind::Shell:
      return TopAbs_SHELL;
    case Kind::Solid:
      return TopAbs_SOLID;
    case Kind::Compound:
      return TopAbs_COMPOUND;
  }
  return TopAbs_SHAPE;
}

Value vec_value(const Vec3& v) {
  Value out = Value::array();
  out.push_back(v.x);
  out.push_back(v.y);
  out.push_back(v.z);
  return out;
}

Value context_snapshot(const CoordinateSystem& cs) {
  Value out = Value::object();
  out.set("origin", vec_value(cs.origin()));
  out.set("x_axis", vec_value(cs.x_axis()));
  out.set("y_axis", vec_value(cs.y_axis()));
  out.set("z_axis", vec_value(cs.z_axis()));
  return out;
}

FrameNode frame_of(const std::string& node_id, const CoordinateSystem& cs) {
  FrameNode frame;
  frame.frame_id = "frame:" + node_id;
  frame.origin = cs.origin();
  frame.x_axis = cs.x_axis();
  frame.y_axis = cs.y_axis();
  frame.z_axis = cs.z_axis();
  frame.metadata = Value::object();
  frame.metadata.set("node_id", node_id);
  return frame;
}

// ---- the topology delta, in canonical order (_canonicalize_recorded_topo_delta) ----

std::string ref_key(const TopoRef& ref) {
  std::string kind(kind_name(ref.kind));
  for (char& c : kind)
    c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
  return ref.graph_id + '\x1f' + ref.node_id + '\x1f' + std::to_string(ref.output_slot) + '\x1f' + kind + '\x1f' +
         ref.topo_id;
}

std::vector<TopoRef> sorted_refs(std::vector<TopoRef> refs) {
  std::sort(refs.begin(), refs.end(), [](const TopoRef& a, const TopoRef& b) { return ref_key(a) < ref_key(b); });
  return refs;
}

std::string ref_list_key(const std::vector<TopoRef>& refs) {
  std::string out;
  for (const TopoRef& ref : refs)
    out += ref_key(ref) + '\x1e';
  return out;
}

TopoDelta canonical_delta(const TopoDelta& raw, const std::string& graph_id, const std::string& node_id) {
  TopoDelta delta = bind_topo_delta(raw, graph_id, node_id);
  for (TopoEntry& entry : delta.entries)
    entry.parent_refs = sorted_refs(std::move(entry.parent_refs));
  for (TopoRoleEntry& role : delta.roles)
    role.parent_refs = sorted_refs(std::move(role.parent_refs));
  std::sort(delta.entries.begin(), delta.entries.end(), [](const TopoEntry& a, const TopoEntry& b) {
    return std::make_tuple(ref_key(a.ref), std::string(to_string(a.event)), a.origin_role.value_or(""),
                           ref_list_key(a.parent_refs), a.metadata.dump()) <
           std::make_tuple(ref_key(b.ref), std::string(to_string(b.event)), b.origin_role.value_or(""),
                           ref_list_key(b.parent_refs), b.metadata.dump());
  });
  std::sort(delta.roles.begin(), delta.roles.end(), [](const TopoRoleEntry& a, const TopoRoleEntry& b) {
    return std::make_tuple(ref_key(a.ref), a.role, a.origin_role.value_or(""), ref_list_key(a.parent_refs),
                           a.metadata.dump()) < std::make_tuple(ref_key(b.ref), b.role, b.origin_role.value_or(""),
                                                                ref_list_key(b.parent_refs), b.metadata.dump());
  });
  const auto of_event = [&delta](TopoEvent event) {
    std::vector<TopoRef> refs;
    for (const TopoEntry& entry : delta.entries) {
      if (entry.event == event)
        refs.push_back(entry.ref);
    }
    refs = sorted_refs(std::move(refs));
    refs.erase(std::unique(refs.begin(), refs.end()), refs.end());
    return refs;
  };
  if (!delta.entries.empty()) {
    delta.preserved = of_event(TopoEvent::Preserved);
    delta.modified = of_event(TopoEvent::Modified);
    delta.generated = of_event(TopoEvent::Generated);
    delta.deleted = of_event(TopoEvent::Deleted);
  } else {
    delta.preserved = sorted_refs(std::move(delta.preserved));
    delta.modified = sorted_refs(std::move(delta.modified));
    delta.generated = sorted_refs(std::move(delta.generated));
    delta.deleted = sorted_refs(std::move(delta.deleted));
  }
  delta.section_edges = sorted_refs(std::move(delta.section_edges));
  return delta;
}

// ---- naming the entities of a delta (recording/graph.py _canonicalize_recorded_topo_delta) ----
//
// The tracker names a sub-shape by its kernel id and gives its refs temporary graph / node ids
// ("g_...", "n_..."); the recorded delta names the entities of the node's outputs by the node's own
// refs, and those of the inputs by the refs their producers gave them.

using RefIndex = std::map<std::pair<Kind, std::string>, TopoRef>;

std::string kernel_id_of(const TopoDS_Shape& shape) {
  return std::to_string(std::hash<TopoDS_Shape>{}(shape));
}

bool temporary_ref(const TopoRef& ref) {
  return ref.graph_id.starts_with("g_") && ref.node_id.starts_with("n_");
}

std::set<std::pair<Kind, std::string>> refs_of(const TopoDelta& delta) {
  std::set<std::pair<Kind, std::string>> keys;
  const auto add = [&keys](const TopoRef& ref) { keys.emplace(ref.kind, ref.topo_id); };
  for (const auto* list : {&delta.preserved, &delta.modified, &delta.generated, &delta.deleted, &delta.section_edges}) {
    for (const TopoRef& ref : *list)
      add(ref);
  }
  for (const TopoEntry& entry : delta.entries) {
    add(entry.ref);
    for (const TopoRef& parent : entry.parent_refs)
      add(parent);
  }
  for (const TopoRoleEntry& role : delta.roles) {
    add(role.ref);
    for (const TopoRef& parent : role.parent_refs)
      add(parent);
  }
  return keys;
}

// The entities of `root` the delta mentions, each with the ref `make` gives it.
template <class Make>
void index_entities(RefIndex& index, const Shape& root, const std::set<std::pair<Kind, std::string>>& wanted,
                    const Make& make, bool strict, bool overwrite = false) {
  for (const Kind kind : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid, Kind::Compound}) {
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(root.wrapped(), topabs(kind), map);
    for (int i = 1; i <= map.Extent(); ++i) {
      const std::pair<Kind, std::string> key{kind, kernel_id_of(map(i))};
      if (wanted.count(key) == 0)
        continue;
      const Shape sub = root.sub(map(i));
      TopoRef ref = make(kind, sub);
      const auto found = index.find(key);
      if (overwrite) {
        index.insert_or_assign(key, std::move(ref));
        continue;
      }
      if (found != index.end() && !(found->second == ref)) {
        // Inputs: a pick (an edge of the solid) keeps the ref of its producer, the first one wins.
        if (!strict)
          continue;
        std::string name(kind_name(kind));
        throw ValueError("ambiguous topology identity for " + name + ":" + key.second);
      }
      index.emplace(key, std::move(ref));
    }
  }
  // A shell's free-boundary wires are made, not sub-shapes: the enumeration above cannot reach them.
  if (root.kind() == Kind::Shell) {
    for (const Wire& wire : Shell(root).wires()) {
      const std::pair<Kind, std::string> key{Kind::Wire, kernel_id_of(wire.wrapped())};
      if (wanted.count(key) == 0 || index.count(key) != 0)
        continue;
      index.emplace(key, make(Kind::Wire, wire));
    }
  }
}

using KindKeys = std::set<std::pair<Kind, std::string>>;

// Entities of the node's own outputs, named by the node's refs.
RefIndex index_output_entities(const KindKeys& wanted, const std::string& graph_id, const std::string& node_id,
                               const std::vector<Shape>& outputs) {
  RefIndex output_index;
  for (std::size_t slot = 0; slot < outputs.size(); ++slot) {
    index_entities(
        output_index, outputs[slot], wanted,
        [&](Kind kind, const Shape& sub) {
          return TopoRef{graph_id, node_id, static_cast<int>(slot), kind,
                         std::string(kind_name(kind)) + "_" + sub.topo_id()};
        },
        true);
  }
  return output_index;
}

// Entities of the inputs, named by the refs their producers gave them.
RefIndex index_input_entities(const KindKeys& wanted, const std::vector<OpInput>& inputs, const OperationGraph& graph) {
  RefIndex source_index;
  // The SDK stamps every entity under a pick with the pick's reference when the pick becomes a
  // selection node, over what its producer stamped: a pick's sub-shapes name the selection node.
  const auto is_pick = [&](const OpInput& input) {
    const auto lineage = lineage_of(input.shape);
    if (!lineage)
      return false;
    const NodePtr node = graph.get_node(lineage->node_id);
    return node && node->op.rfind("make_select_", 0) == 0;
  };
  // Non-picks first, then picks, which overwrite (so the pick's node wins for its sub-shapes).
  for (const bool picks : {false, true}) {
    for (const OpInput& input : inputs) {
      if (is_pick(input) != picks)
        continue;
      const std::optional<TopoRef> own = topo_ref_of(input.shape);
      if (!own)
        continue;
      // The entities of an input carry the refs their producer gave them: the producer's graph, node and slot.
      index_entities(
          source_index, input.shape, wanted,
          [&](Kind kind, const Shape& sub) {
            const std::string topo_id = std::string(kind_name(kind)) + "_" + sub.topo_id();
            if (const auto lineage = lineage_of(sub))
              return TopoRef{lineage->graph_id, lineage->node_id, lineage->output_slot, kind, topo_id};
            return TopoRef{own->graph_id, own->node_id, own->output_slot, kind, topo_id};
          },
          false, picks);
    }
  }
  return source_index;
}

// A witness is "complete" unless its metadata says it is partial or unproven.
bool witness_complete(const Value& metadata) {
  const Value* coverage = metadata.find("coverage");
  const Value* status = metadata.find("status");
  return (coverage == nullptr || !coverage->is_string() || coverage->as_string() == "complete") &&
         (status == nullptr || !status->is_string() || status->as_string() == "proven");
}

// Maps tracker refs to recorded refs through the two indexes.
struct RefResolver {
  const RefIndex& source_index;
  const RefIndex& output_index;

  std::optional<TopoRef> resolve(const TopoRef& ref, bool source, bool required) const {
    const RefIndex& index = source ? source_index : output_index;
    if (const auto found = index.find({ref.kind, ref.topo_id}); found != index.end())
      return found->second;
    if (temporary_ref(ref))
      return std::nullopt;
    const bool bound =
        !ref.graph_id.empty() && ref.graph_id != "pending" && !ref.node_id.empty() && ref.node_id != "pending";
    if (bound)
      return ref;
    // The SDK refuses a complete witness it cannot resolve; a tracker's witness for an entity this
    // enumeration does not reach (a wire of a surface operation) is dropped instead of failing the operation.
    if (required)
      return std::nullopt;
    return ref;
  }

  std::vector<TopoRef> resolve_parents(const std::vector<TopoRef>& parents, bool required, bool& dropped) const {
    std::vector<TopoRef> out;
    for (const TopoRef& parent : parents) {
      if (const auto resolved = resolve(parent, true, required)) {
        out.push_back(*resolved);
      } else {
        dropped = true;
      }
    }
    return out;
  }

  std::vector<TopoRef> resolve_many(const std::vector<TopoRef>& refs, bool source) const {
    std::vector<TopoRef> resolved;
    for (const TopoRef& ref : refs) {
      if (const auto found = resolve(ref, source, true))
        resolved.push_back(*found);
    }
    return resolved;
  }
};

TopoDelta resolve_recorded_delta(const TopoDelta& raw, const std::string& graph_id, const std::string& node_id,
                                 const std::vector<Shape>& outputs, const std::vector<OpInput>& inputs,
                                 const OperationGraph& graph) {
  const auto wanted = refs_of(raw);
  const RefIndex output_index = index_output_entities(wanted, graph_id, node_id, outputs);
  const RefIndex source_index = index_input_entities(wanted, inputs, graph);
  const RefResolver refs{source_index, output_index};

  TopoDelta out;
  for (const TopoEntry& entry : raw.entries) {
    const bool required = witness_complete(entry.metadata);
    const auto ref = refs.resolve(entry.ref, entry.event == TopoEvent::Deleted, required);
    bool dropped = !ref;
    std::vector<TopoRef> parents = refs.resolve_parents(entry.parent_refs, required, dropped);
    if (dropped)
      continue;
    TopoEntry item = entry;
    item.ref = *ref;
    item.parent_refs = std::move(parents);
    out.entries.push_back(std::move(item));
  }
  for (const TopoRoleEntry& role : raw.roles) {
    const bool required = witness_complete(role.metadata);
    const auto ref = refs.resolve(role.ref, false, required);
    bool dropped = !ref;
    std::vector<TopoRef> parents = refs.resolve_parents(role.parent_refs, required, dropped);
    if (dropped)
      continue;
    TopoRoleEntry item = role;
    item.ref = *ref;
    item.parent_refs = std::move(parents);
    out.roles.push_back(std::move(item));
  }
  if (out.entries.empty()) {  // what the witnesses could not name falls back to the plain lists
    out.preserved = refs.resolve_many(raw.preserved, false);
    out.modified = refs.resolve_many(raw.modified, false);
    out.generated = refs.resolve_many(raw.generated, false);
    out.deleted = refs.resolve_many(raw.deleted, true);
  }
  out.section_edges = refs.resolve_many(raw.section_edges, false);
  out.raw_event = raw.raw_event;
  return out;
}

void attach_topology(const Shape& root, const std::string& graph_id, const std::string& node_id, int slot) {
  for (const Kind kind : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid, Kind::Compound}) {
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(root.wrapped(), topabs(kind), map);
    for (int i = 1; i <= map.Extent(); ++i) {
      const Shape sub = root.sub(map(i));
      set_topo_ref(sub, TopoRef{graph_id, node_id, slot, kind, sub.topo_id()});
      // A shell's free-boundary wires are its children once enumerated: they carry the ref too.
      if (kind == Kind::Shell) {
        for (const Wire& wire : Shell(sub).wires())
          set_topo_ref(wire, TopoRef{graph_id, node_id, slot, Kind::Wire, wire.topo_id()});
      }
    }
  }
}

}  // namespace

std::string_view to_string(NodeStatus status) noexcept {
  switch (status) {
    case NodeStatus::Clean:
      return "clean";
    case NodeStatus::Dirty:
      return "dirty";
    case NodeStatus::Failed:
      return "failed";
    case NodeStatus::Blocked:
      return "blocked";
  }
  return "";
}

// ---------------------------------------------------------------------------
// Construction and activation
// ---------------------------------------------------------------------------

Session::Session(Options options)
    : graph_(options.graph_id, options.ns),
      options_(options),
      registry_(options.registry != nullptr ? options.registry : &ExecutorRegistry::global()) {}

Session::~Session() {
  // Destroyed while still installed: leave the thread as it was found.  stop() is noexcept, so nothing
  // can escape this destructor and no try/catch is needed around it.
  if (scope_)
    stop();
}

void Session::start() {
  if (scope_)
    throw RuntimeError("GraphSession is already active");
  previous_active_ = detail::active_session_slot();
  detail::active_session_slot() = this;
  scope_.emplace(this);
  ambient_.emplace(&bindings_);
}

void Session::stop() noexcept {
  if (!scope_)
    return;
  ambient_.reset();
  scope_.reset();
  detail::active_session_slot() = previous_active_;
  previous_active_ = nullptr;
}

Session* Session::active_session() noexcept {
  return detail::active_session_slot();
}

IsolatedRecording::IsolatedRecording() : previous_(detail::active_session_slot()) {
  detail::active_session_slot() = nullptr;
}
IsolatedRecording::~IsolatedRecording() {
  detail::active_session_slot() = previous_;
}

std::string Session::allocate_object_id(std::string_view prefix) {
  const std::size_t next = ++object_counters_[std::string(prefix)];
  char suffix[16];
  std::snprintf(suffix, sizeof suffix, "_%08zx", next);
  return graph_.namespaced(prefix) + suffix;
}

// ---------------------------------------------------------------------------
// Recording
// ---------------------------------------------------------------------------

void Session::record(const OpRecord& record, const std::vector<Shape>& outputs) {
  record_impl(record, outputs, false);
}

NodePtr Session::record_node(const OpRecord& record, const std::vector<Shape>& outputs) {
  return record_impl(record, outputs, false);
}

NodePtr Session::active_node_for(const Shape& shape) {
  const std::optional<Lineage> lineage = lineage_of(shape);
  if (!lineage)
    return nullptr;
  return active_node_for(*lineage);
}

NodePtr Session::active_node_for(const Lineage& lineage) {
  if (NodePtr node = graph_.get_node(lineage.node_id))
    return node;
  if (!lineage.graph_id.empty() && lineage.graph_id != graph_.graph_id())
    return nullptr;
  if (options_.shared_lineage) {
    if (const NodePtr foreign = find_registered_node(graph_.graph_id(), lineage.node_id))
      return graph_.adopt(foreign);
  }
  return nullptr;
}

std::optional<ValueLineage> Session::record_value_op(const OpRecord& op, const std::vector<ValueLineage>& inputs) {
  if (pending_value_output_ || !pending_inputs_.empty()) {  // the caller declared the inputs and takes the result
    record_impl(op, {}, false);
    return std::nullopt;
  }
  std::vector<NodePtr> nodes;
  for (const ValueLineage& input : inputs) {
    if (const NodePtr node = active_node_for(Lineage{input.graph_id, input.node_id, input.output_slot}))
      nodes.push_back(node);
  }
  expect_value_op(std::move(nodes), true);
  const NodePtr node = record_impl(op, {}, false);
  return ValueLineage{graph_.graph_id(), node->node_id, 0};
}

namespace {

bool is_select_op(std::string_view op) {
  return op.rfind("make_select_", 0) == 0;
}

constexpr std::string_view kApplyTagOp = "apply_tag_rselection";

}  // namespace

std::optional<Shape> Session::selection_source_for(const Shape& shape) {
  // A face or edge handed over by a recorded output whose enumeration this handle did not come from.
  if (const auto ref = topo_ref_of(shape)) {
    const auto state = states_.find(ref->node_id);
    if (state != states_.end() && ref->output_slot >= 0 &&
        static_cast<std::size_t>(ref->output_slot) < state->second.outputs.size() && !lineage_of(shape)) {
      const Shape& root = state->second.outputs[static_cast<std::size_t>(ref->output_slot)];
      if (!root.same_entity(shape))
        return root;
    }
  }
  std::vector<Shape> stack = shape.known_parents();
  std::vector<Shape> seen;
  const TopAbs_ShapeEnum wanted = detail::topabs_of(shape.kind());
  while (!stack.empty()) {
    const Shape source = stack.front();
    stack.erase(stack.begin());
    if (source.same_entity(shape))
      continue;
    if (std::any_of(seen.begin(), seen.end(), [&](const Shape& s) { return s.same_entity(source); }))
      continue;
    seen.push_back(source);
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(source.wrapped(), wanted, map);
    if (map.Contains(shape.wrapped()) && active_node_for(source))
      return source;
    for (Shape& above : source.known_parents())
      stack.push_back(std::move(above));
  }
  return std::nullopt;
}

NodePtr Session::ensure_source_has_own_selection_node(const Shape& source) {
  NodePtr node = active_node_for(source);
  if (!node || is_select_op(node->op) || node->op == kApplyTagOp)
    return node;
  const std::optional<Shape> parent = selection_source_for(source);
  if (!parent)
    return node;
  ensure_selection_nodes(*parent, {source});
  return active_node_for(source);
}

std::vector<std::string> Session::record_geo_selection_nodes(const Shape& source, const Shape& selected) {
  const NodePtr source_node = active_node_for(source);
  if (!source_node)
    return {};
  const std::string op = detail::selection_op_name(selected.kind());
  if (op.empty())
    return {};  // the SDK has no selection node for a compound
  const NodePtr selected_node = active_node_for(selected);

  OpRecord rec;
  rec.op = op;
  rec.params = Value::object();
  rec.params.set("target_kind", detail::kind_token(selected));
  const auto source_lineage = lineage_of(source);
  rec.params.set("source_output_slot", static_cast<std::int64_t>(source_lineage ? source_lineage->output_slot : 0));
  rec.params.set("geo_selector", make_geo_exact_selector(selected, &source));
  rec.inputs.push_back(OpInput{source, "source"});
  if (selected_node && selected_node->op == kApplyTagOp && selected_node != source_node)
    rec.inputs.push_back(OpInput{selected, "selected"});
  SemanticDelta semantic;
  semantic.created.push_back({"pending", "pending", "Selection", op + ":0"});
  semantic.metadata = Value::object();
  semantic.metadata.set("op", op);
  rec.semantic_delta = std::move(semantic);
  pending_source_index_ = detail::index_in_source(source, selected);
  const NodePtr node = record_impl(rec, {selected}, true);
  return {node->node_id};
}

std::vector<std::string> Session::ensure_selection_nodes(const Shape& source, const std::vector<Shape>& picked) {
  const NodePtr source_node = ensure_source_has_own_selection_node(source);
  if (!source_node)
    return {};
  std::vector<std::string> ids;
  for (const Shape& shape : picked) {
    if (const NodePtr existing = active_node_for(shape); existing && is_select_op(existing->op)) {
      ids.push_back(existing->node_id);
      continue;
    }
    for (std::string& id : record_geo_selection_nodes(source, shape))
      ids.push_back(std::move(id));
  }
  return ids;
}

void Session::ensure_selection_input_nodes(const std::vector<Shape>& inputs) {
  for (const Shape& shape : inputs) {
    if (active_node_for(shape))
      continue;
    if (const std::optional<Shape> source = selection_source_for(shape))
      ensure_selection_nodes(*source, {shape});
  }
}

std::optional<Value> Session::input_refs(const std::vector<Shape>& inputs) {
  ensure_selection_input_nodes(inputs);
  return serialize_shape_refs(inputs);
}

void Session::record_selection(const Shape& source, const std::vector<Shape>& picked, const std::string&) {
  (void)ensure_selection_nodes(source, picked);
}

InputBinding Session::bind_input(const OpInput& input, std::vector<NodePtr>& input_nodes,
                                 std::vector<ExternalInput>& externals) {
  InputBinding binding;
  binding.role = input.role;
  std::optional<Lineage> lineage = lineage_of(input.shape);
  if (!lineage) {
    if (const auto ref = topo_ref_of(input.shape)) {
      if (!ref->graph_id.empty() && ref->graph_id != graph_.graph_id()) {
        throw ValueError("value contains topology reference '" + ref->topo_id + "' from graph '" + ref->graph_id +
                         "', active graph is '" + graph_.graph_id() + "'");
      }
      if (!graph_.get_node(ref->node_id) &&
          !(options_.shared_lineage && find_registered_node(ref->graph_id, ref->node_id))) {
        throw ValueError("value contains topology reference '" + ref->topo_id + "' for unknown node '" + ref->node_id +
                         "'");
      }
      // A face or edge of a recorded output used as an input: it becomes a
      // selection node, so that it follows its source when that is rebuilt.
      // A node adopted from another session has no outputs here: the pick stays an external input.
      const auto source_state = states_.find(ref->node_id);
      if (source_state != states_.end() && ref->output_slot >= 0 &&
          static_cast<std::size_t>(ref->output_slot) < source_state->second.outputs.size()) {
        ensure_selection_nodes(source_state->second.outputs[static_cast<std::size_t>(ref->output_slot)], {input.shape});
        lineage = lineage_of(input.shape);
      }
    }
  }
  if (!lineage) {
    externals.push_back(ExternalInput{input.shape, "x" + std::to_string(++external_counter_)});
    return binding;
  }
  if (!lineage->graph_id.empty() && lineage->graph_id != graph_.graph_id()) {
    throw ValueError("value contains graph node '" + lineage->node_id + "' from graph '" + lineage->graph_id +
                     "', active graph is '" + graph_.graph_id() + "'");
  }
  NodePtr node = graph_.get_node(lineage->node_id);
  if (!node && options_.shared_lineage) {
    if (const NodePtr foreign = find_registered_node(graph_.graph_id(), lineage->node_id))
      node = graph_.adopt(foreign);
  }
  if (!node) {
    throw ValueError("value contains graph node '" + lineage->node_id + "' not owned by active graph '" +
                     graph_.graph_id() + "'");
  }
  binding.node_id = node->node_id;
  binding.output_slot = lineage->output_slot;
  if (std::none_of(input_nodes.begin(), input_nodes.end(), [&node](const NodePtr& n) { return n == node; })) {
    input_nodes.push_back(node);
  }
  return binding;
}

NodePtr Session::record_impl(const OpRecord& record, const std::vector<Shape>& outputs, bool selection) {
  CanonicalParams canonical = canonicalize_params(record.params, record.symbolic, expressions_);

  std::vector<NodePtr> input_nodes;
  std::vector<InputBinding> bindings;
  std::vector<ExternalInput> externals;
  for (const OpInput& input : record.inputs)
    bindings.push_back(bind_input(input, input_nodes, externals));

  bool value_output = false;
  if (!selection) {  // a pick recorded on the way is not the operation the caller announced
    for (const ValueLineage& value : record.value_inputs) {
      const NodePtr node = active_node_for(Lineage{value.graph_id, value.node_id, value.output_slot});
      if (node &&
          std::none_of(input_nodes.begin(), input_nodes.end(), [&node](const NodePtr& n) { return n == node; })) {
        bindings.push_back(InputBinding{node->node_id, 0, "value"});
        input_nodes.push_back(node);
      }
    }
    for (NodePtr& pending : pending_inputs_) {
      if (std::none_of(input_nodes.begin(), input_nodes.end(), [&pending](const NodePtr& n) { return n == pending; })) {
        bindings.push_back(InputBinding{pending->node_id, 0, "value"});
        input_nodes.push_back(pending);
      }
    }
    value_output = pending_value_output_ && outputs.empty();
    clear_value_op();
  }

  const std::string node_id = record.node_id.empty() || selection ? graph_.allocate_node_id() : record.node_id;
  const CoordinateSystem& cs = current_cs();
  FrameNode frame = frame_of(node_id, cs);

  NodeSpec spec;
  spec.op = record.op;
  spec.params = std::move(canonical.numeric);
  spec.param_exprs = std::move(canonical.exprs);
  spec.inputs = std::move(input_nodes);
  spec.bindings = std::move(bindings);
  spec.node_id = node_id;
  spec.output_count =
      value_output || (outputs.empty() && !record.empty_list_result) ? 1 : static_cast<int>(outputs.size());
  spec.semantic_delta = record.semantic_delta;
  if (record.delta) {
    spec.topo_delta = canonical_delta(
        resolve_recorded_delta(*record.delta, graph_.graph_id(), node_id, outputs, record.inputs, graph_),
        graph_.graph_id(), node_id);
  }
  spec.tags.insert(record.labels.begin(), record.labels.end());
  spec.context = context_snapshot(cs);
  if (options_.source_provider)
    spec.source = options_.source_provider();
  spec.expressions = referenced_expressions(spec.param_exprs, expressions_);
  spec.symbolic = record.symbolic;
  spec.frame = frame;
  spec.source_index = std::exchange(pending_source_index_, std::nullopt);
  spec.symbolic.erase(
      std::remove_if(spec.symbolic.begin(), spec.symbolic.end(),
                     [](const auto& entry) { return is_discrete_param_name(ParamPath::parse(entry.first).key); }),
      spec.symbolic.end());

  const NodePtr node = graph_.add_node(std::move(spec));
  last_node_ = node;
  if (options_.shared_lineage)
    register_node(node);
  frames_.add(std::move(frame));

  NodeState& state = states_[node_id];
  state.outputs = outputs;
  state.value_output = value_output;
  state.externals = std::move(externals);
  state.key = node_key(*node, node->params);
  note_var_use(*node, state);
  memo_insert(state.key, state.outputs);
  attach_outputs(node, outputs, selection);
  return node;
}

std::optional<Value> Session::topo_ref_value(const Shape& shape) {
  const std::optional<TopoRef> ref = topo_ref_of(shape);
  if (!ref)
    return std::nullopt;
  TopoRef named = *ref;
  named.topo_id = std::string(kind_name(named.kind)) + "_" + named.topo_id;
  return to_value(named);
}

std::optional<NodeReservation> Session::reserve_node(std::string_view prefix) {
  return NodeReservation{graph_.graph_id(), graph_.allocate_node_id(prefix)};
}

void Session::expect_value_op(std::vector<NodePtr> inputs, bool value_output) {
  pending_inputs_ = std::move(inputs);
  pending_value_output_ = value_output;
}

void Session::clear_value_op() noexcept {
  pending_inputs_.clear();
  pending_value_output_ = false;
}

void Session::attach_outputs(const NodePtr& node_ptr, const std::vector<Shape>& outputs, bool selection) {
  const OperationNode& node = *node_ptr;
  for (std::size_t slot = 0; slot < outputs.size(); ++slot) {
    const Shape& handle = outputs[slot];  // a copy would share the same entity
    if (node.op == kApplyTagOp)
      keep_topology_owner(handle);
    set_lineage(handle, Lineage{graph_.graph_id(), node.node_id, static_cast<int>(slot)}, node.op);
    handle.set_graph_node(node_ptr);  // the value keeps its node, whatever becomes of the session
    // A tag node only re-attributes the shape's graph lineage (attach_semantic_graph_node): what it
    // contains stays named by the nodes that made it.
    if (!selection && node.op != kApplyTagOp && options_.attach_topology_refs) {
      attach_topology(handle, graph_.graph_id(), node.node_id, static_cast<int>(slot));
    }
  }
}

void Session::note_var_use(const OperationNode& node, NodeState& state) {
  for (const auto& [path, scalar] : node.symbolic) {
    for (const std::shared_ptr<const Var>& var : referenced_vars(scalar)) {
      declare_var(var);
      auto& names = state.var_names;
      if (std::find(names.begin(), names.end(), var->name()) == names.end()) {
        names.push_back(var->name());
        users_[var->name()].push_back(node.node_id);
      }
    }
  }
}

std::string Session::node_key(const OperationNode& node, const Value& params) const {
  std::string text = node.node_id;
  text += '\n';
  text += node.op;
  text += '\n';
  text += params.dump();
  const NodeState& own = state_of(node.node_id);
  std::size_t external = 0;
  for (const InputBinding& binding : node.bindings) {
    text += '\n';
    if (binding.external()) {
      text += "x:" + own.externals.at(external++).token;
    } else {
      // A node adopted from another session (shared lineage) has no state here: its id stands for it.
      const auto input = states_.find(binding.node_id);
      text += "n:" + (input != states_.end() ? input->second.key : binding.node_id) + "#" +
              std::to_string(binding.output_slot);
    }
  }
  return sha256_hex(text);
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

void Session::validate_graph_ownership(const Shape& value) const {
  if (const auto lineage = lineage_of(value)) {
    if (!lineage->graph_id.empty() && lineage->graph_id != graph_.graph_id()) {
      throw ValueError("value contains graph node '" + lineage->node_id + "' from graph '" + lineage->graph_id +
                       "', active graph is '" + graph_.graph_id() + "'");
    }
    if (!graph_.get_node(lineage->node_id)) {
      throw ValueError("value contains graph node '" + lineage->node_id + "' not owned by active graph '" +
                       graph_.graph_id() + "'");
    }
  }
  if (const auto ref = topo_ref_of(value)) {
    if (ref->graph_id != graph_.graph_id()) {
      throw ValueError("value contains topology reference '" + ref->topo_id + "' from graph '" + ref->graph_id +
                       "', active graph is '" + graph_.graph_id() + "'");
    }
    if (!graph_.get_node(ref->node_id)) {
      throw ValueError("value contains topology reference '" + ref->topo_id + "' for unknown node '" + ref->node_id +
                       "'");
    }
  }
}

std::vector<std::string> Session::capture_result(const std::vector<Shape>& values) {
  for (const Shape& value : values)
    validate_graph_ownership(value);
  std::vector<std::string> ids;
  for (const Shape& value : values) {
    if (const auto lineage = lineage_of(value)) {
      if (std::find(ids.begin(), ids.end(), lineage->node_id) == ids.end())
        ids.push_back(lineage->node_id);
    }
  }
  if (ids.empty()) {
    throw ValueError("capture_result() requires a value containing at least one graph-backed shape or semantic value");
  }
  has_explicit_results_ = true;
  for (const std::string& id : ids) {
    if (std::find(result_node_ids_.begin(), result_node_ids_.end(), id) == result_node_ids_.end()) {
      result_node_ids_.push_back(id);
    }
  }
  for (const Shape& value : values)
    captured_.push_back(value);
  return ids;
}

void Session::clear_results() {
  result_node_ids_.clear();
  captured_.clear();
  has_explicit_results_ = false;
}

std::vector<Shape> Session::captured_shapes() const {
  std::vector<Shape> out;
  out.reserve(captured_.size());
  for (const Shape& shape : captured_)
    out.push_back(current(shape));
  return out;
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

Session::NodeState& Session::state_of(std::string_view node_id) {
  const auto found = states_.find(std::string(node_id));
  if (found == states_.end())
    throw KeyError("unknown node id '" + std::string(node_id) + "'");
  return found->second;
}

const Session::NodeState& Session::state_of(std::string_view node_id) const {
  const auto found = states_.find(std::string(node_id));
  if (found == states_.end())
    throw KeyError("unknown node id '" + std::string(node_id) + "'");
  return found->second;
}

const std::vector<Shape>& Session::outputs(std::string_view node_id) const {
  return state_of(node_id).outputs;
}

const Shape& Session::output(std::string_view node_id, int slot) const {
  const std::vector<Shape>& all = state_of(node_id).outputs;
  if (slot < 0 || static_cast<std::size_t>(slot) >= all.size()) {
    throw IndexError("node '" + std::string(node_id) + "' has " + std::to_string(all.size()) + " output(s); no slot " +
                     std::to_string(slot));
  }
  return all[static_cast<std::size_t>(slot)];
}

Shape Session::current(const Shape& shape) const {
  if (const auto lineage = lineage_of(shape)) {
    if (!lineage->graph_id.empty() && lineage->graph_id != graph_.graph_id()) {
      throw ValueError("shape belongs to graph '" + lineage->graph_id + "', this session records '" +
                       graph_.graph_id() + "'");
    }
    return output(lineage->node_id, lineage->output_slot);
  }
  if (const auto ref = topo_ref_of(shape)) {
    if (ref->graph_id != graph_.graph_id()) {
      throw ValueError("shape belongs to graph '" + ref->graph_id + "', this session records '" + graph_.graph_id() +
                       "'");
    }
    const Shape& root = output(ref->node_id, ref->output_slot);
    const auto index = detail::topo_index(ref->topo_id);
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(root.wrapped(), topabs(ref->kind), map);
    if (index && static_cast<int>(*index) < map.Extent())
      return root.sub(map(static_cast<int>(*index) + 1));
    throw ValueError("the rebuilt output has no " + ref->topo_id);
  }
  throw ValueError("shape was not recorded by this session");
}

}  // namespace scad::reactive
