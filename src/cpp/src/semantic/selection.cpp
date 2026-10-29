// operators/selection.py and _support._apply_tag_rselection.
#include "scad/semantic/selection.hpp"

#include <cctype>

#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include <algorithm>
#include <map>
#include <set>
#include <unordered_set>

#include "detail.hpp"
#include "scad/core/error.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad {

namespace {

using detail::graph_source_of;
using detail::object;
using detail::output_slot_of;

// ---------------------------------------------------------------------------
// Scope enumeration (_resolve_scope_items)
// ---------------------------------------------------------------------------
std::vector<Shape> unique_vertices(const std::vector<Edge>& edges) {
  std::vector<Shape> out;
  std::unordered_set<std::string> seen;
  for (const Edge& edge : edges)
    for (const Vertex& vertex : edge.vertices())
      if (seen.insert(vertex.topo_id()).second)
        out.push_back(vertex);
  return out;
}

std::vector<Shape> scope_items(const Shape& scope, Kind target) {
  using detail::as_shapes;
  if (scope.kind() == target)
    return {scope};
  switch (target) {
    case Kind::Edge:
      switch (scope.kind()) {
        case Kind::Wire:
          return as_shapes(Wire(scope).edges());
        case Kind::Face:
          return as_shapes(Face(scope).edges());
        case Kind::Shell:
          return as_shapes(Shell(scope).edges());
        case Kind::Solid:
          return as_shapes(Solid(scope).edges());
        case Kind::Compound:
          return as_shapes(Compound(scope).edges());
        default:
          break;
      }
      break;
    case Kind::Face:
      switch (scope.kind()) {
        case Kind::Shell:
          return as_shapes(Shell(scope).faces());
        case Kind::Solid:
          return as_shapes(Solid(scope).faces());
        case Kind::Compound:
          return as_shapes(Compound(scope).faces());
        default:
          break;
      }
      break;
    case Kind::Wire:
      switch (scope.kind()) {
        case Kind::Face:
          return as_shapes(Face(scope).wires());
        case Kind::Shell:
          return as_shapes(Shell(scope).wires());
        default:
          break;
      }
      break;
    case Kind::Solid:
      if (scope.kind() == Kind::Compound)
        return as_shapes(Compound(scope).solids());
      break;
    case Kind::Vertex:
      switch (scope.kind()) {
        case Kind::Edge:
          return as_shapes(Edge(scope).vertices());
        case Kind::Wire:
          return unique_vertices(Wire(scope).edges());
        case Kind::Face:
          return unique_vertices(Face(scope).edges());
        case Kind::Shell:
          return unique_vertices(Shell(scope).edges());
        case Kind::Solid:
          return unique_vertices(Solid(scope).edges());
        case Kind::Compound:
          return unique_vertices(Compound(scope).edges());
        default:
          break;
      }
      break;
    case Kind::Shell:
    case Kind::Compound:
      break;
  }
  throw TypeError("cannot resolve QL selector scope for target_kind=" + std::string(kind_name(target)));
}

// _track_values(track, "result_roles", "result_role"): the output roles the tracker proved.
bool has_output_role(const Shape& shape, std::string_view role) {
  const Value track = shape.get_metadata("track");
  if (!track.is_object())
    return false;
  if (const Value* plural = track.find("result_roles"); plural != nullptr && plural->is_array()) {
    for (const Value& item : plural->as_array())
      if (detail::text_of(item) == role)
        return true;
    return false;
  }
  const Value* single = track.find("result_role");
  return single != nullptr && !single->is_null() && detail::text_of(*single) == role;
}

[[noreturn]] void cardinality_failure(Kind target, std::string_view mode, int expected, std::size_t got) {
  ErrorGuidance g;
  g.what_happened = "QL selector expected " + std::string(mode) + " " + std::to_string(expected) + " " +
                    std::string(kind_name(target)) + "(s), got " + std::to_string(got);
  g.possible_causes = {"The predicate does not match the actual geometry values.",
                       "OCCT split one logical face into several at a seam after a boolean.",
                       "The selector was resolved against an older shape state."};
  g.how_to_fix = {"Read the inventory: hit = matched, near_miss = what exists instead.",
                  "Re-derive selectors from the newest shape after topology-changing ops."};
  throw Error("ql." + std::string(kind_name(target)) + ".resolve", std::move(g));
}

// ---------------------------------------------------------------------------
// Shape references in tag evidence (_serialize_shape_refs, _make_selector_hint)
// ---------------------------------------------------------------------------
Value bbox_value(const Shape& shape) {
  const kernel::BoundingBox bb = shape.bounding_box();
  return object({{"min", detail::vec3_array({bb.xmin, bb.ymin, bb.zmin})},
                 {"max", detail::vec3_array({bb.xmax, bb.ymax, bb.zmax})}});
}

Value selector_hint(const Shape& shape) {
  Value hint =
      object({{"kind", std::string(kind_name(shape.kind()))}, {"tags", detail::string_array(shape.list_tags())}});
  switch (shape.kind()) {
    case Kind::Edge: {
      const Edge edge(shape);
      hint.set("length", edge.length());
      try {
        hint.set("start", detail::vec3_array(edge.start_vertex().coordinates()));
        hint.set("end", detail::vec3_array(edge.end_vertex().coordinates()));
      } catch (const std::exception&) {
        hint.set("center", detail::vec3_array(shape.center()));
      }
      break;
    }
    case Kind::Face: {
      const Face face(shape);
      hint.set("area", face.area());
      hint.set("center", detail::vec3_array(shape.center()));
      hint.set("normal", detail::vec3_array(face.normal_at()));
      break;
    }
    case Kind::Wire:
      hint.set("edge_count", static_cast<std::int64_t>(Wire(shape).edges().size()));
      hint.set("closed", Wire(shape).is_closed());
      break;
    case Kind::Vertex:
      hint.set("coordinates", detail::vec3_array(Vertex(shape).coordinates()));
      break;
    case Kind::Shell:
      hint.set("face_count", static_cast<std::int64_t>(Shell(shape).faces().size()));
      hint.set("bbox", bbox_value(shape));
      break;
    case Kind::Solid:
      hint.set("volume", Solid(shape).volume());
      hint.set("bbox", bbox_value(shape));
      break;
    case Kind::Compound:
      hint.set("volume", Compound(shape).volume());
      hint.set("solid_count", static_cast<std::int64_t>(Compound(shape).solids().size()));
      hint.set("bbox", bbox_value(shape));
      break;
  }
  return hint;
}

// The recorded reference of a shape, if the recorder attached one.
std::optional<Value> shape_ref(const Shape& shape) {
  Value ref = shape.get_runtime("topo.ref");
  if (!ref.is_object())
    ref = shape.get_metadata("topo_ref");
  if (!ref.is_object()) {
    if (Recorder* recorder = current_recorder()) {
      if (auto derived = recorder->topo_ref_value(shape))
        ref = std::move(*derived);
    }
  }
  if (!ref.is_object())
    return std::nullopt;
  ref.set("selector_hint", selector_hint(shape));
  return ref;
}

Value plain_ref(const Shape& shape) {
  return object({{"kind", std::string(kind_name(shape.kind()))}, {"topo_id", shape.topo_id()}});
}

// Recorded references for all of `shapes`, or plain {kind, topo_id} pairs when any lacks one.
std::vector<Value> shape_refs(const std::vector<Shape>& shapes) {
  std::vector<Value> refs;
  for (const Shape& shape : shapes)
    if (auto ref = shape_ref(shape))
      refs.push_back(std::move(*ref));
  if (refs.size() == shapes.size())
    return refs;
  refs.clear();
  for (const Shape& shape : shapes)
    refs.push_back(plain_ref(shape));
  return refs;
}

// ---------------------------------------------------------------------------
// Explicit targets inside a scope view (_semantic_view_target)
// ---------------------------------------------------------------------------
class ViewTargets {
 public:
  explicit ViewTargets(const Shape& view) : view_(view) {}

  Shape resolve(const Shape& target) {
    const TopTools_IndexedMapOfShape& members = members_of(target.kind());
    if (members.Contains(target.wrapped()))
      return view_.sub(target.wrapped());
    if (target.kind() == Kind::Wire) {
      // A wire rebuilt from the same edges is the same topology.
      std::vector<TopoDS_Shape> matches;
      for (int i = 1; i <= members.Extent(); ++i)
        if (same_edges(members(i), target.wrapped()))
          matches.push_back(members(i));
      if (matches.size() == 1)
        return view_.sub(matches.front());
      if (matches.size() > 1)
        throw ValueError("tag target resolves ambiguously inside the assignment scope");
    }
    throw ValueError("tag target does not belong to the assignment scope");
  }

 private:
  const TopTools_IndexedMapOfShape& members_of(Kind kind) {
    auto it = members_.find(kind);
    if (it == members_.end()) {
      TopTools_IndexedMapOfShape map;
      TopExp::MapShapes(view_.wrapped(), to_topabs_kind(kind), map);
      it = members_.emplace(kind, std::move(map)).first;
    }
    return it->second;
  }

  static TopAbs_ShapeEnum to_topabs_kind(Kind kind) {
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

  static bool same_edges(const TopoDS_Shape& a, const TopoDS_Shape& b) {
    TopTools_IndexedMapOfShape left, right;
    TopExp::MapShapes(a, TopAbs_EDGE, left);
    TopExp::MapShapes(b, TopAbs_EDGE, right);
    if (left.Extent() != right.Extent())
      return false;
    for (int i = 1; i <= left.Extent(); ++i)
      if (!right.Contains(left(i)))
        return false;
    return true;
  }

  const Shape& view_;
  std::map<Kind, TopTools_IndexedMapOfShape> members_;
};

}  // namespace

// ---------------------------------------------------------------------------
// NativeSelector
// ---------------------------------------------------------------------------
NativeSelector::NativeSelector(Kind target, std::optional<std::string> output_role, Count mode, int count,
                               std::optional<SelectorSource> source)
    : target_(target), output_role_(std::move(output_role)), mode_(mode), count_(count), source_(std::move(source)) {
  if (count_ < 0)
    throw ValueError("count must be >= 0");
}

SelectorPtr NativeSelector::exactly_one(Kind target) {
  return std::make_shared<NativeSelector>(target, std::nullopt, Count::Exactly, 1);
}

SelectorPtr NativeSelector::with_output_role(Kind target, std::string_view role, bool exactly_one) {
  const std::string trimmed = detail::strip(role);
  if (trimmed.empty())
    throw ValueError("role_name must be a non-empty string");
  return std::make_shared<NativeSelector>(target, detail::lower(trimmed), exactly_one ? Count::Exactly : Count::AtLeast,
                                          1);
}

std::vector<Shape> NativeSelector::resolve(const Shape& scope) const {
  std::vector<Shape> items = scope_items(scope, target_);
  if (output_role_) {
    items.erase(std::remove_if(items.begin(), items.end(),
                               [&](const Shape& item) { return !has_output_role(item, *output_role_); }),
                items.end());
  }
  if (mode_ == Count::Exactly && static_cast<int>(items.size()) != count_)
    cardinality_failure(target_, "exactly", count_, items.size());
  if (mode_ == Count::AtLeast && static_cast<int>(items.size()) < count_)
    cardinality_failure(target_, "at least", count_, items.size());
  return items;
}

Value NativeSelector::to_value() const {
  Value cardinality = Value::object();
  cardinality.set(mode_ == Count::Exactly ? "exactly" : "at_least", count_);
  Value payload = object({{"target_kind", std::string(kind_name(target_))},
                          {"order_desc", false},
                          {"cardinality", std::move(cardinality)}});
  if (output_role_) {
    payload.set(
        "predicate",
        object({{"kind", "output_role"}, {"data", object({{"role", *output_role_}})}, {"children", Value::array()}}));
  }
  if (source_) {
    payload.set("source_node_id", source_->node_id);
    payload.set("source_output_slot", source_->output_slot);
  }
  return payload;
}

std::shared_ptr<const ShapeSelector> NativeSelector::from_source(const SelectorSource& source) const {
  return std::make_shared<NativeSelector>(target_, output_role_, mode_, count_, source);
}

// ---------------------------------------------------------------------------
// Assignment
// ---------------------------------------------------------------------------
Shape clone_semantic_view(const Shape& shape) {
  return shape.clone_view();
}

namespace {

// Resolves the tag targets against the scope's view: through a selector (anchored to the scope's graph
// node when it declares none) or from explicit shapes. Fills `target` with the recorded description.
std::vector<Shape> resolve_tag_targets(const TagTargets& targets, const Shape& view,
                                       const std::optional<SelectorSource>& source_node, TagTarget& target) {
  std::vector<Shape> selected;
  if (const SelectorPtr& given = targets.selector()) {
    SelectorPtr selector = given;
    if (source_node) {
      if (const auto declared = selector->source()) {
        if (declared->node_id != source_node->node_id || declared->output_slot != source_node->output_slot)
          throw ValueError("tag selector source does not match the assignment scope");
      } else if (SelectorPtr anchored = selector->from_source(*source_node)) {
        selector = std::move(anchored);
      }
    }
    selected = selector->resolve(view);
    target.kind = TagTargetKind::SelectionQuery;
    target.selector = selector->to_value();
  } else {
    const std::vector<Shape>& explicit_shapes = targets.shapes();
    if (explicit_shapes.empty())
      throw ValueError("tag assignment targets cannot be empty");
    ViewTargets in_view(view);
    for (const Shape& item : explicit_shapes)
      selected.push_back(in_view.resolve(item));
    target.kind = TagTargetKind::ExplicitRefs;
    target.refs = shape_refs(explicit_shapes);
  }
  return selected;
}

// References of the selected shapes for the binding's evidence. The picks are handles of the scope's
// own view: they carry no container link, so a recorded reference is named from the scope's node
// (the SDK stamps every entity of a recorded output).
Value selected_ref_values(const std::vector<Shape>& selected, const std::optional<NodeReservation>& reservation,
                          const std::optional<SelectorSource>& source_node, int source_slot) {
  const auto scoped_ref = [&](const Shape& item) -> std::optional<Value> {
    if (auto ref = shape_ref(item))
      return ref;
    if (!reservation || !source_node)
      return std::nullopt;
    std::string kind(kind_name(item.kind()));
    for (char& c : kind)
      c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    Value ref = object({{"graph_id", reservation->graph_id},
                        {"kind", kind},
                        {"node_id", source_node->node_id},
                        {"output_slot", static_cast<std::int64_t>(source_slot)},
                        {"topo_id", std::string(kind_name(item.kind())) + "_" + item.topo_id()}});
    ref.set("selector_hint", selector_hint(item));
    return ref;
  };
  Value selected_refs = Value::array();
  std::vector<Value> refs;
  for (const Shape& item : selected) {
    if (auto ref = scoped_ref(item))
      refs.push_back(std::move(*ref));
  }
  // All-or-nothing: if any pick cannot be named from the scope, fall back to plain shape references.
  if (refs.size() == selected.size()) {
    for (Value& ref : refs)
      selected_refs.push_back(std::move(ref));
  } else {
    for (const Value& ref : shape_refs(selected))
      selected_refs.push_back(ref);
  }
  return selected_refs;
}

// The user-operation tag binding; with a reserved node its id is derived from the node (deterministic),
// otherwise a fresh id is minted.
TagBinding make_tag_binding(const std::string& normalized, TopologyPropagation topology, LineagePolicy lineage,
                            const TagAssignOptions& options, std::size_t selected_count, Value selected_refs,
                            TagTarget target, const std::optional<NodeReservation>& reservation,
                            const std::optional<SelectorSource>& source_node, int source_slot) {
  TagBinding binding;
  binding.tag = normalized;
  binding.policy.mut().producer.kind = TagProducerKind::UserOperation;
  if (reservation)
    binding.policy.mut().producer.node_id = reservation->node_id;
  if (source_node)
    binding.policy.mut().scope.node_id = source_node->node_id;
  binding.policy.mut().scope.output_slot = source_slot;
  binding.policy.mut().target = std::move(target);
  binding.policy.mut().propagation.topology = topology;
  binding.policy.mut().propagation.lineage = lineage;
  binding.evidence.mut().kind = TagEvidenceKind::QueryExecution;
  binding.evidence.mut().data.set("authoring_source", options.authoring_source);
  binding.evidence.mut().data.set("selected_count", static_cast<std::int64_t>(selected_count));
  binding.evidence.mut().data.set("selected_refs", std::move(selected_refs));
  if (options.extra_evidence.is_object())
    for (const auto& [key, value] : options.extra_evidence.as_object())
      binding.evidence.mut().data.set(key, value);
  binding.certainty = TagCertainty::Asserted;
  binding.lifecycle = TagLifecycle::Assertion;
  if (reservation)
    binding.binding_id = BindingId("tag_binding_" + uuid5_url_hex("simplecad:user-tag:" + reservation->graph_id + ":" +
                                                                  reservation->node_id + ":" + normalized));
  else
    binding.binding_id = new_binding_id();
  binding.validate();
  return binding;
}

}  // namespace

Shape assign_tag(const Shape& scope, const TagTargets& targets, std::string_view tag, TopologyPropagation topology,
                 LineagePolicy lineage, const TagAssignOptions& options) {
  const std::string normalized = normalize_tag(tag, true);
  Recorder* const recorder = current_recorder();
  const std::optional<SelectorSource> source_node = graph_source_of(scope);
  const int source_slot = source_node ? source_node->output_slot : output_slot_of(scope);

  Shape view = options.clone_scope ? clone_semantic_view(scope) : scope;

  TagTarget target;
  std::vector<Shape> selected = resolve_tag_targets(targets, view, source_node, target);
  std::unordered_set<std::string> seen;
  for (const Shape& item : selected)
    if (!seen.insert(item.topo_id()).second)
      throw ValueError("tag assignment targets contain ambiguous duplicate entities");
  if (selected.empty())
    throw ValueError("tag assignment resolved no targets");

  std::optional<NodeReservation> reservation;
  if (recorder != nullptr && source_node)
    reservation = recorder->reserve_node("n");

  Value selected_refs = selected_ref_values(selected, reservation, source_node, source_slot);
  const TagBinding binding =
      make_tag_binding(normalized, topology, lineage, options, selected.size(), std::move(selected_refs),
                       std::move(target), reservation, source_node, source_slot);
  for (Shape& item : selected)
    item.add_binding(binding);

  if (recorder != nullptr && source_node) {
    OpRecord record;
    record.op = "apply_tag_rselection";
    record.params = object({{"tag_binding", binding.to_value()}});
    record.inputs.push_back({scope, "scope"});
    if (reservation)
      record.node_id = reservation->node_id;
    recorder->record(record, {view});
  }
  return view;
}

// ---------------------------------------------------------------------------
// The public operators
// ---------------------------------------------------------------------------
Shape apply_tag_rselection(const Shape& scope, const TagTargets& targets, std::string_view tag,
                           TopologyPropagation topology, LineagePolicy lineage) {
  static const ErrorSpec kSpec{
      "apply_tag_rselection",
      "Failed to attach the tag to the selected shapes.",
      {"The assignment scope or target selection is invalid.", "The tag value is empty or malformed.",
       "The selector resolved no targets or references foreign topology."},
      {"Pass a valid scope and a non-empty ShapeSelector or shape sequence.",
       "Use a normalized tag string such as 'role.mounting_surface' or 'group.fasteners'.",
       "Ensure every explicit target belongs to the assignment scope."}};
  return guarded(kSpec, [&] { return assign_tag(scope, targets, tag, topology, lineage); });
}

Shape apply_tag(const Shape& shape, std::string_view tag) {
  static const ErrorSpec kSpec{"apply_tag",
                               "Failed to attach the tag to the shape.",
                               {"The shape is invalid.", "The tag value is empty or malformed."},
                               {"Pass a valid shape object.",
                                "Use a normalized tag string such as 'role.mounting_surface' or 'group.fasteners'."}};
  return guarded(kSpec, [&] {
    TagAssignOptions options;
    options.clone_scope = false;
    assign_tag(shape, TagTargets(NativeSelector::exactly_one(shape.kind())), tag, TopologyPropagation::Local,
               LineagePolicy::ContinuationFragment, options);
    return shape;
  });
}

std::vector<std::string> list_tags(const Shape& shape, TagScope scope) {
  static const ErrorSpec kSpec{"list_tags",
                               "Failed to list tags on the shape.",
                               {"The shape is invalid.", "The object is not a SimpleCAD shape."},
                               {"Pass a valid Vertex, Edge, Wire, Face, or Solid object."}};
  return guarded(kSpec, [&] { return shape.list_tags(scope); });
}

std::vector<Value> explain_tag(const Shape& shape, std::string_view tag, TagScope scope) {
  static const ErrorSpec kSpec{
      "explain_tag",
      "Failed to explain the tag on the shape.",
      {"The shape or tag is invalid.", "The requested scope requires unavailable semantic evidence."},
      {"Pass a valid shape and normalized tag token.",
       "Request a supported scope or provide complete topology history."}};
  return guarded(kSpec, [&] { return shape.explain_tag(normalize_tag(tag, true), scope); });
}

std::vector<Face> select_faces_by_tag(const Solid& solid, std::string_view tag, TagScope scope) {
  static const ErrorSpec kSpec{"select_faces_by_tag",
                               "Failed to select faces by tag.",
                               {"The solid is invalid.", "The tag string is invalid."},
                               {"Pass a valid Solid object.", "Use the exact face tag that was previously assigned."}};
  return guarded(kSpec, [&] {
    const std::string normalized = normalize_tag(tag, true);
    std::vector<Face> out;
    for (const Face& face : solid.faces())
      if (face.has_tag(normalized, scope))
        out.push_back(face);
    return out;
  });
}

std::vector<Edge> select_edges_by_tag(const Shape& shape, std::string_view tag, TagScope scope) {
  static const ErrorSpec kSpec{
      "select_edges_by_tag",
      "Failed to select edges by tag.",
      {"The input shape is neither a Face nor a Solid.", "The shape is invalid.", "The tag string is invalid."},
      {"Pass a Face or Solid object.", "Use the exact edge tag that was previously assigned.",
       "If selection is empty unexpectedly, inspect the available edge tags first."}};
  return guarded(kSpec, [&] {
    const std::string normalized = normalize_tag(tag, true);
    std::vector<Edge> edges;
    if (shape.kind() == Kind::Face)
      edges = Face(shape).edges();
    else if (shape.kind() == Kind::Solid)
      edges = Solid(shape).edges();
    else
      throw ValueError("Edges can only be selected from a face or a solid");
    std::vector<Edge> out;
    for (const Edge& edge : edges)
      if (edge.has_tag(normalized, scope))
        out.push_back(edge);
    return out;
  });
}

}  // namespace scad
