// Output roles and the tags operators name them with: normalize / validate role tags,
// apply role, result and prefix tags (the tagging half of operators/_support.py).
#include <algorithm>
#include <map>
#include <set>
#include <tuple>

#include "detail.hpp"
#include "scad/core/error.hpp"
#include "scad/semantic/autotag.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad {

namespace {

using detail::object;
using Roles = std::vector<std::pair<std::string, RoleCardinality>>;

constexpr RoleCardinality kOne = RoleCardinality::One;
constexpr RoleCardinality kMany = RoleCardinality::Many;

// _OPERATION_OUTPUT_ROLE_CARDINALITY
const std::map<std::string, Roles, std::less<>>& role_table() {
  static const std::map<std::string, Roles, std::less<>> table = {
      {"make_box_rsolid",
       {{"box.bottom", kOne}, {"box.top", kOne}, {"box.front", kOne}, {"box.back", kOne}, {"box.left", kOne},
        {"box.right", kOne}}},
      {"make_cylinder_rsolid",
       {{"cylinder.start", kOne}, {"cylinder.end", kOne}, {"cylinder.side", kOne}, {"cylinder.start_boundary", kOne},
        {"cylinder.end_boundary", kOne}, {"cylinder.seam", kOne}}},
      {"make_cone_rsolid",
       {{"cone.start", kOne}, {"cone.end", kOne}, {"cone.side", kOne}, {"cone.start_boundary", kOne},
        {"cone.end_boundary", kOne}, {"cone.seam", kOne}}},
      {"make_extrude_rsolid", {{"extrusion.start", kOne}, {"extrusion.end", kOne}, {"extrusion.side", kMany}}},
      {"make_revolve_rsolid", {{"revolution.start", kOne}, {"revolution.end", kOne}, {"revolution.side", kMany}}},
      {"make_fillet_rsolid", {{"fillet.patch", kMany}}},
      {"make_chamfer_rsolid", {{"chamfer.patch", kMany}}},
      {"make_shell_rsolid",
       {{"shell.body_face", kMany}, {"shell.offset_face", kMany}, {"shell.closing_descendant", kMany},
        {"shell.wall", kMany}}},
      {"make_loft_rsolid", {{"loft.start", kOne}, {"loft.end", kOne}, {"loft.side", kMany}}},
      {"make_sweep_rsolid", {{"sweep.start", kOne}, {"sweep.end", kOne}, {"sweep.side", kMany}}},
      {"make_loft_rshell", {{"loft.start_wire", kOne}, {"loft.end_wire", kOne}, {"loft.side", kMany}}},
      {"make_twisted_sweep_rsolid",
       {{"twisted_sweep.start", kOne}, {"twisted_sweep.end", kOne}, {"twisted_sweep.side", kMany}}},
  };
  return table;
}

std::string_view cardinality_word(RoleCardinality c) { return c == kOne ? "one" : "many"; }

bool recording() noexcept { return current_recorder() != nullptr; }

// ---- topology identity (what a "name this entity" tag remembers about itself) --------

const Value* topology_identity_payload(const TagBinding& binding) {
  for (const std::string_view key : {"topology_name", "source_topology_name"}) {
    const Value* v = binding.evidence->data.find(key);
    if (v != nullptr && v->is_object()) return v;
  }
  return nullptr;
}

std::optional<std::string> topology_identity_local_name(const Shape& shape) {
  for (const TagBinding& binding : shape.local_tag_bindings()) {
    const Value* payload = topology_identity_payload(binding);
    if (payload == nullptr) continue;
    const Value* kind = payload->find("kind");
    if (kind == nullptr || !kind->is_string() || kind->as_string() != kind_name(shape.kind())) continue;
    const Value* local_name = payload->find("local_name");
    if (local_name != nullptr && local_name->is_string() && !local_name->as_string().empty())
      return local_name->as_string();
  }
  return std::nullopt;
}

std::vector<Shape> edges_of(const Shape& shape) {
  switch (shape.kind()) {
    case Kind::Edge: return {shape};
    case Kind::Wire: return detail::as_shapes(Wire(shape).edges());
    case Kind::Face: return detail::as_shapes(Face(shape).edges());
    case Kind::Shell: return detail::as_shapes(Shell(shape).edges());
    case Kind::Solid: return detail::as_shapes(Solid(shape).edges());
    case Kind::Compound: return detail::as_shapes(Compound(shape).edges());
    default: return {};
  }
}

std::vector<Shape> faces_of(const Shape& shape) {
  switch (shape.kind()) {
    case Kind::Shell: return detail::as_shapes(Shell(shape).faces());
    case Kind::Solid: return detail::as_shapes(Solid(shape).faces());
    case Kind::Compound: return detail::as_shapes(Compound(shape).faces());
    case Kind::Face: return {shape};
    default: return {};
  }
}

std::string source_name(std::string_view op, std::string_view suffix) {
  return "simplecadapi." + std::string(op) + "." + std::string(suffix);
}

// The (ref, kind) pairs the delta proves for `role`.
using RefKey = std::tuple<std::string, std::string, int, Kind, std::string>;
RefKey ref_key(const TopoRef& ref) { return {ref.graph_id, ref.node_id, ref.output_slot, ref.kind, ref.topo_id}; }

std::string lowered_metadata(const Value& metadata, std::string_view key, std::string fallback) {
  const Value* v = metadata.find(key);
  return detail::lower(v != nullptr ? detail::text_of(*v) : fallback);
}

}  // namespace

// ---------------------------------------------------------------------------
// Role tables, normalization and validation
// ---------------------------------------------------------------------------
const std::vector<std::pair<std::string, RoleCardinality>>& operation_output_roles(std::string_view op) {
  const auto& table = role_table();
  const auto it = table.find(op);
  if (it == table.end()) throw Exception(PyKind::KeyError, "'" + std::string(op) + "'");
  return it->second;
}

std::vector<RoleAssignment> normalize_operation_role_tags(std::string_view op, const std::vector<RoleTag>& named) {
  // Operations without role tags (booleans, transforms) have no table row, and need none.
  if (std::none_of(named.begin(), named.end(), [](const RoleTag& item) { return item.tag.has_value(); })) return {};
  const Roles& specs = operation_output_roles(op);
  std::map<std::string, std::string> requested;
  for (const RoleTag& item : named) {
    if (!item.tag) continue;
    if (requested.count(item.role) != 0) throw ValueError("duplicate role tag assignment: " + item.role);
    requested.emplace(item.role, normalize_tag(*item.tag, true));
  }

  std::string unknown;
  for (const auto& entry : requested) {
    // a named variable, not a structured binding: Apple clang 15 (Xcode 15.4) cannot capture one in the lambda
    const std::string& role = entry.first;
    const bool known = std::any_of(specs.begin(), specs.end(), [&](const auto& spec) { return spec.first == role; });
    if (!known) unknown += (unknown.empty() ? "" : ", ") + role;
  }
  if (!unknown.empty()) {
    std::string expected;
    for (const auto& spec : specs) expected += (expected.empty() ? "" : ", ") + spec.first;
    throw ValueError("unsupported output role(s) for " + std::string(op) + ": " + unknown + "; expected one of " + expected);
  }

  std::vector<RoleAssignment> out;
  for (const auto& [role, cardinality] : specs)
    if (const auto it = requested.find(role); it != requested.end()) out.push_back({role, cardinality, it->second});
  return out;
}

std::map<std::string, Kind> validate_operation_output_roles(const TopoDelta& delta,
                                                            const std::vector<RoleAssignment>& assignments) {
  std::map<std::string, Kind> target_kinds;
  for (const RoleAssignment& assignment : assignments) {
    std::set<RefKey> refs;
    std::set<Kind> kinds;
    for (const TopoRoleEntry& entry : delta.roles) {
      if (entry.role != assignment.role) continue;
      if (lowered_metadata(entry.metadata, "coverage", "complete") != "complete") continue;
      if (lowered_metadata(entry.metadata, "status", "proven") != "proven") continue;
      refs.insert(ref_key(entry.ref));
      kinds.insert(entry.ref.kind);
    }
    if (assignment.cardinality == kOne && refs.size() != 1) {
      throw SemanticCapabilityError("operation output role '" + assignment.role +
                                    "' requires exactly one kernel-proven result, got " + std::to_string(refs.size()));
    }
    if (assignment.cardinality == kMany && refs.empty())
      throw SemanticCapabilityError("operation output role '" + assignment.role +
                                    "' requires at least one kernel-proven result");
    if (kinds.size() != 1)
      throw SemanticCapabilityError("operation output role '" + assignment.role +
                                    "' does not resolve to one topology kind");
    target_kinds[assignment.role] = *kinds.begin();
  }
  return target_kinds;
}

OutputTagPlan plan_output_tags(std::string_view op, const OutputTags& tags) {
  OutputTagPlan plan;
  plan.assignments = normalize_operation_role_tags(op, tags.roles);
  if (tags.result_tag) plan.result_tag = normalize_tag(*tags.result_tag, true);
  if (tags.tag_prefix) plan.tag_prefix = normalize_tag(*tags.tag_prefix, true);
  return plan;
}

// ---------------------------------------------------------------------------
// Applying tags
// ---------------------------------------------------------------------------
Shape apply_topology_identity_tag(Shape scope, const TagTargets& targets, std::string_view tag, Kind kind,
                                  std::string_view local_name, std::string_view authoring_source) {
  const std::string normalized = normalize_tag(tag, true);
  TagAssignOptions options;
  options.authoring_source = std::string(authoring_source);
  options.extra_evidence = object({{"topology_name", object({{"kind", std::string(kind_name(kind))},
                                                             {"name", normalized},
                                                             {"local_name", normalize_tag(local_name, true)}})}});
  options.clone_scope = recording();
  return assign_tag(scope, targets, normalized,
                    kind == Kind::Face ? TopologyPropagation::Downward : TopologyPropagation::Local,
                    LineagePolicy::ContinuationFragment, options);
}

Shape apply_operation_role_tags(Shape shape, std::string_view op, const std::vector<RoleAssignment>& assignments,
                                const std::map<std::string, Kind>& target_kinds,
                                const std::optional<std::string>& result_tag) {
  if (assignments.empty() && !result_tag) return shape;

  const auto source_node = detail::graph_source_of(shape);
  const auto node_id = [&]() { return source_node ? Value(source_node->node_id) : Value(); };
  const int slot = detail::output_slot_of(shape);

  Shape result = shape;
  for (const RoleAssignment& assignment : assignments) {
    TagAssignOptions options;
    options.authoring_source = source_name(op, "role_tag");
    options.extra_evidence = object({{"operation_output_role", object({{"source_node_id", node_id()},
                                                                       {"source_output_slot", slot},
                                                                       {"operation", std::string(op)},
                                                                       {"role", assignment.role},
                                                                       {"cardinality", std::string(cardinality_word(assignment.cardinality))}})}});
    options.clone_scope = recording();
    result = assign_tag(result,
                        NativeSelector::with_output_role(target_kinds.at(assignment.role), assignment.role,
                                                         assignment.cardinality == kOne),
                        assignment.tag, TopologyPropagation::Local, LineagePolicy::ContinuationFragment, options);
  }
  if (result_tag) {
    TagAssignOptions options;
    options.authoring_source = source_name(op, "result_tag");
    options.extra_evidence = object({{"operation_result", object({{"source_node_id", node_id()},
                                                                  {"source_output_slot", slot},
                                                                  {"operation", std::string(op)}})}});
    options.clone_scope = recording();
    result = assign_tag(result, NativeSelector::exactly_one(shape.kind()), *result_tag, TopologyPropagation::Local,
                        LineagePolicy::ContinuationFragment, options);
  }
  return result;
}

Shape apply_shape_tag_prefix(Shape shape, const std::optional<std::string>& tag_prefix, Kind kind,
                             std::string_view authoring_source) {
  if (!tag_prefix) return shape;
  const std::string prefix = normalize_tag(*tag_prefix, true);
  return apply_topology_identity_tag(std::move(shape), NativeSelector::exactly_one(kind),
                                     prefix + "." + std::string(kind_name(kind)), kind, kind_name(kind),
                                     authoring_source);
}

Shape apply_profile_tag_prefix(Shape shape, const std::optional<std::string>& tag_prefix,
                               const std::optional<std::vector<std::string>>& edge_tags,
                               std::string_view authoring_source) {
  if (!tag_prefix && !edge_tags) return shape;
  std::optional<std::string> prefix;
  if (tag_prefix) prefix = normalize_tag(*tag_prefix, true);
  Shape result = prefix ? apply_shape_tag_prefix(shape, prefix, shape.kind(), authoring_source) : shape;

  const std::vector<Shape> edges = edges_of(shape);
  std::vector<std::string> local_names;
  if (edge_tags) {
    local_names = *edge_tags;
  } else {
    for (std::size_t i = 0; i < edges.size(); ++i) local_names.push_back("line" + std::to_string(i + 1));
  }
  if (local_names.size() != edges.size())
    throw ValueError("edge_tags must contain exactly " + std::to_string(edges.size()) + " tags, got " +
                     std::to_string(local_names.size()));

  for (std::size_t i = 0; i < edges.size(); ++i) {
    const std::string local_name = normalize_tag(local_names[i], true);
    const std::string edge_tag = prefix ? *prefix + ".edge." + local_name : local_name;
    result = apply_topology_identity_tag(std::move(result), std::vector<Shape>{edges[i]}, edge_tag, Kind::Edge,
                                         local_name, authoring_source);
  }
  return result;
}

Shape apply_feature_tag_prefix(Shape solid, const std::optional<std::string>& tag_prefix, std::string_view op,
                               const TopoDelta& delta, const FeatureRoles& roles,
                               const std::vector<Shape>& source_shapes) {
  if (!tag_prefix) return solid;
  const std::string prefix = normalize_tag(*tag_prefix, true);
  const std::string authoring = source_name(op, "tag_prefix");

  Shape result = apply_topology_identity_tag(solid, NativeSelector::exactly_one(Kind::Solid), prefix + ".solid",
                                             Kind::Solid, "solid", authoring);

  const std::pair<const std::string*, const char*> ends[] = {{&roles.start, "start"}, {&roles.end, "end"}, {&roles.side, "side"}};
  for (const auto& [role, local_name] : ends) {
    if (role->empty()) continue;
    const bool one = std::string_view(local_name) != "side";
    result = apply_topology_identity_tag(std::move(result), NativeSelector::with_output_role(Kind::Face, *role, one),
                                         prefix + ".face." + local_name, Kind::Face, local_name, authoring);
  }

  if (!roles.side.empty()) {
    // A side face may descend from several profile edges (a loft side joins the matching edges of two
    // sections), and one edge may feed several faces: a name is carried over only when the kernel
    // history proves a bijection.
    TopologyIndex source_edges, result_faces;
    for (const Shape& source : source_shapes)
      for (const Shape& edge : edges_of(source)) source_edges.add(edge);
    for (const Shape& face : faces_of(result)) result_faces.add(face);

    std::vector<std::pair<std::string, std::string>> correspondence;  // (result face id, source edge id)
    for (const TopoRoleEntry& entry : delta.roles) {
      if (entry.role != roles.side) continue;
      std::vector<const TopoRef*> parent_edges;
      for (const TopoRef& parent : entry.parent_refs)
        if (parent.kind == Kind::Edge) parent_edges.push_back(&parent);
      if (parent_edges.size() != 1) continue;
      correspondence.emplace_back(entry.ref.topo_id, parent_edges.front()->topo_id);
    }
    std::map<std::string, std::set<std::string>> target_sources, source_targets;
    for (const auto& [target_id, source_id] : correspondence) {
      target_sources[target_id].insert(source_id);
      source_targets[source_id].insert(target_id);
    }
    for (const auto& [target_id, source_id] : correspondence) {
      if (target_sources[target_id].size() != 1 || source_targets[source_id].size() != 1) continue;
      const Shape* source_edge = source_edges.find(source_id);
      const Shape* target_face = result_faces.find(target_id);
      if (source_edge == nullptr || target_face == nullptr) continue;
      const auto edge_name = topology_identity_local_name(*source_edge);
      if (!edge_name) continue;
      result = apply_topology_identity_tag(std::move(result), std::vector<Shape>{*target_face},
                                           prefix + ".face.side." + *edge_name, Kind::Face, "side." + *edge_name,
                                           source_name(op, "profile_edge_tag"));
    }
  }

  for (const auto& [role, local_name] : roles.edges)
    result = apply_topology_identity_tag(std::move(result), NativeSelector::with_output_role(Kind::Edge, role, true),
                                         prefix + ".edge." + local_name, Kind::Edge, local_name, authoring);
  for (const auto& [role, local_name] : roles.faces)
    result = apply_topology_identity_tag(std::move(result), NativeSelector::with_output_role(Kind::Face, role, true),
                                         prefix + ".face." + local_name, Kind::Face, local_name, authoring);
  return result;
}

Shape copy_exact_topology_identity_tags(Shape target, const std::vector<Shape>& sources, std::string_view operation) {
  std::vector<Shape> source_members;
  for (const Shape& source : sources)
    for (Shape& member : edges_of(source))
      if (member.kind() == Kind::Edge) source_members.push_back(std::move(member));

  Shape result = target;
  for (const Shape& member : edges_of(target)) {
    if (member.kind() != Kind::Edge) continue;
    const Shape* match = nullptr;
    std::size_t matches = 0;
    for (const Shape& candidate : source_members) {
      if (!candidate.is_same(member)) continue;
      match = &candidate;
      ++matches;
    }
    if (matches != 1) continue;
    for (const TagBinding& binding : match->local_tag_bindings()) {
      const Value* identity = topology_identity_payload(binding);
      if (identity == nullptr) continue;
      const Value* local_name = identity->find("local_name");
      if (local_name == nullptr || !local_name->is_string() || local_name->as_string().empty()) continue;
      result = apply_topology_identity_tag(std::move(result), std::vector<Shape>{member}, binding.tag, Kind::Edge,
                                           local_name->as_string(), source_name(operation, "identity_tag"));
    }
  }
  return result;
}

}  // namespace scad
