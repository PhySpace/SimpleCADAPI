// How an operator finishes (operators/_support.py): semantic deltas, the track summary,
// the record call, lineage helpers and semantic ids.
#include "scad/semantic/finalize.hpp"

#include <algorithm>
#include <functional>
#include <map>
#include <set>

#include "detail.hpp"
#include "scad/core/error.hpp"
#include "scad/semantic/autotag.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad {

namespace {

using detail::object;

bool in(std::string_view op, std::initializer_list<std::string_view> names) {
  return std::find(names.begin(), names.end(), op) != names.end();
}

// SemanticRef entity type of an operation's output (_semantic_delta_for_output).
std::string entity_type_of(std::string_view op) {
  if (in(op, {"make_point", "make_point_rvertex"})) return "Point";

  if (in(op, {"make_sketch_rsketch", "add_point_rsketch", "add_line_rsketch", "add_circle_rsketch",
              "add_arc_rsketch", "add_bspline_rsketch", "make_wire_from_sketch_rwire", "make_face_from_sketch_rface",
              "make_constrain_coincident_rsketch", "make_constrain_point_on_rsketch", "make_constrain_horizontal_rsketch",
              "make_constrain_vertical_rsketch", "make_constrain_points_horizontal_rsketch",
              "make_constrain_points_vertical_rsketch", "make_constrain_line_distance_rsketch",
              "make_constrain_normal_rsketch", "make_constrain_mirror_rsketch", "make_constrain_midpoint_points_rsketch",
              "make_constrain_parallel_rsketch", "make_constrain_perpendicular_rsketch",
              "make_constrain_collinear_rsketch", "make_constrain_tangent_rsketch", "make_constrain_concentric_rsketch",
              "make_constrain_midpoint_rsketch", "make_constrain_symmetric_rsketch",
              "make_constrain_equal_length_rsketch", "make_constrain_equal_radius_rsketch",
              "make_constrain_distance_rsketch", "make_constrain_distance_x_rsketch", "make_constrain_distance_y_rsketch",
              "make_constrain_length_rsketch", "make_constrain_angle_rsketch", "make_constrain_radius_rsketch",
              "make_constrain_major_radius_rsketch", "make_constrain_minor_radius_rsketch",
              "make_constrain_diameter_rsketch", "make_constrain_fix_rsketch"}))
    return "Sketch";

  if (in(op, {"make_line", "make_circle_edge", "make_circle_wire", "make_circle_face", "make_rectangle_wire",
              "make_rectangle_face", "make_segment_wire", "make_three_point_arc", "make_three_point_arc_wire",
              "make_angle_arc", "make_angle_arc_wire", "make_spline", "make_spline_wire", "make_polyline_wire",
              "make_helix", "make_helix_wire", "make_face_from_wire", "make_wire_from_edges", "make_line_redge",
              "make_circle_redge", "make_three_point_arc_redge", "make_angle_arc_redge", "make_spline_redge",
              "make_helix_redge", "make_face_from_wire_rface", "make_wire_from_edges_rwire"}))
    return detail::ends_with(op, "_face") || in(op, {"make_face_from_wire", "make_face_from_wire_rface"}) ? "Sketch"
                                                                                                        : "Profile";

  if (in(op, {"make_box", "make_cylinder", "make_cone", "make_sphere", "make_box_rsolid", "make_cylinder_rsolid",
              "make_cone_rsolid", "make_sphere_rsolid", "extrude", "revolve", "loft", "sweep", "helical_sweep",
              "fillet", "chamfer", "shell", "cut", "union", "intersect", "translate", "rotate", "mirror",
              "make_extrude_rsolid", "make_revolve_rsolid", "make_loft_rsolid", "make_sweep_rsolid",
              "make_twisted_sweep_rsolid", "make_fillet_rsolid", "make_chamfer_rsolid", "make_shell_rsolid",
              "make_cut_rsolid", "make_union_rsolid", "make_intersect_rsolid", "make_translate_rshape",
              "make_rotate_rshape", "make_mirror_rshape", "load_brep_region_rsolid"}))
    return in(op, {"extrude", "revolve", "loft", "sweep", "fillet", "chamfer", "shell", "cut", "union", "intersect",
                   "make_extrude_rsolid", "make_revolve_rsolid", "make_loft_rsolid", "make_sweep_rsolid",
                   "make_twisted_sweep_rsolid", "make_fillet_rsolid", "make_chamfer_rsolid", "make_shell_rsolid",
                   "make_cut_rsolid", "make_union_rsolid", "make_intersect_rsolid"})
               ? "Feature"
               : "Body";

  return "ShapeOutput";
}

// The free-form labels the SDK's operators pass as `tags=` when they record (a graph node's `tags`).
std::vector<std::string> node_labels_for_op(std::string_view op) {
  static const std::map<std::string_view, std::vector<std::string>, std::less<>> table = {
      {"add_arc_rsketch", {"arc", "sketch"}},
      {"add_bspline_rsketch", {"bspline", "sketch"}},
      {"add_circle_rsketch", {"circle", "sketch"}},
      {"add_ellipse_rsketch", {"ellipse", "sketch"}},
      {"add_line_rsketch", {"line", "sketch"}},
      {"add_point_rsketch", {"point", "sketch"}},
      {"fill_holes_rshell", {"derived", "shell", "surface"}},
      {"fit_point_grid_rface", {"face", "primitive", "surface"}},
      {"make_2d_cut_rface", {"derived", "face"}},
      {"make_2d_intersect_rface", {"derived", "face"}},
      {"make_2d_union_rface", {"derived", "face"}},
      {"make_angle_arc_redge", {"edge", "primitive"}},
      {"make_angle_arc_wire", {"primitive", "wire"}},
      {"make_bezier_surface_rface", {"face", "primitive", "surface"}},
      {"make_circle_face", {"face", "primitive"}},
      {"make_circle_redge", {"edge", "primitive"}},
      {"make_circle_wire", {"primitive", "wire"}},
      {"make_cylindrical_surface_rface", {"face", "primitive", "surface"}},
      {"make_ellipse_face", {"face", "primitive"}},
      {"make_ellipse_redge", {"edge", "primitive"}},
      {"make_ellipse_wire", {"primitive", "wire"}},
      {"make_face_from_sketch_rface", {"derived", "face", "sketch"}},
      {"make_face_from_wire_rface", {"derived", "face"}},
      {"make_face_from_wires_rface", {"derived", "face"}},
      {"make_gordon_surface_rface", {"derived", "face", "surface"}},
      {"make_helix_redge", {"edge", "primitive"}},
      {"make_helix_wire", {"primitive", "wire"}},
      {"make_interpolated_spline_redge", {"edge", "primitive"}},
      {"make_interpolated_spline_wire", {"primitive", "wire"}},
      {"make_line_redge", {"edge", "primitive"}},
      {"make_loft_rshell", {"derived", "shell", "surface"}},
      {"make_point_rvertex", {"primitive", "vertex"}},
      {"make_polyline_wire", {"primitive", "wire"}},
      {"make_rectangle_face", {"face", "primitive"}},
      {"make_rectangle_wire", {"primitive", "wire"}},
      {"make_ruled_surface_rface", {"derived", "face", "surface"}},
      {"make_segment_wire", {"primitive", "wire"}},
      {"make_sketch_rsketch", {"sketch"}},
      {"make_solid_from_shell_rsolid", {"derived", "solid", "surface"}},
      {"make_sphere_rsolid", {"primitive", "solid"}},
      {"make_spline_redge", {"edge", "primitive"}},
      {"make_spline_wire", {"primitive", "wire"}},
      {"make_surface_patch_rface", {"derived", "face", "surface"}},
      {"make_three_point_arc_redge", {"edge", "primitive"}},
      {"make_three_point_arc_wire", {"primitive", "wire"}},
      {"make_wire_from_edges_rwire", {"derived", "wire"}},
      {"make_wire_from_sketch_rwire", {"derived", "sketch", "wire"}},
      {"sew_faces_rshell", {"derived", "shell", "surface"}},
      {"trim_surface_rface", {"derived", "face", "surface", "trimmed"}},
  };
  if (const auto found = table.find(op); found != table.end()) return found->second;
  if (detail::starts_with(op, "make_constrain_") && detail::ends_with(op, "_rsketch")) return {"constraint", "sketch"};
  return {};
}

void apply_node_labels(OpRecord& record) {
  if (record.labels.empty()) record.labels = node_labels_for_op(record.op);
}

std::vector<Shape> consumed_shapes(const FinalizeSpec& spec) {
  std::vector<Shape> sources;
  sources.reserve(spec.record.inputs.size() + spec.extra_sources.size());
  for (const OpInput& input : spec.record.inputs) sources.push_back(input.shape);
  for (const Shape& extra : spec.extra_sources) sources.push_back(extra);
  return sources;
}

void record_now(OpRecord& record, const Shape& shape) {
  record.semantic_delta = semantic_delta_for_output(record.op);
  apply_node_labels(record);
  record_operation(record, {shape});
}

// Role / result / prefix tags, in Python's order.
Shape apply_output_tags(Shape shape, const FinalizeSpec& spec, const OutputTagPlan& plan,
                        const std::map<std::string, Kind>& target_kinds, const TopoDelta& delta,
                        const std::vector<Shape>& sources) {
  Shape tagged = apply_operation_role_tags(std::move(shape), spec.record.op, plan.assignments, target_kinds,
                                           plan.result_tag);
  return apply_feature_tag_prefix(std::move(tagged), plan.tag_prefix, spec.record.op, delta, spec.roles, sources);
}

}  // namespace

// ---------------------------------------------------------------------------
// Semantic deltas and the track summary
// ---------------------------------------------------------------------------
SemanticDelta semantic_delta_for_output(std::string_view op, int output_count, std::string_view entity_type) {
  const std::string resolved = entity_type.empty() ? entity_type_of(op) : std::string(entity_type);
  SemanticDelta delta;
  for (int slot = 0; slot < output_count; ++slot)
    delta.created.push_back({"pending", "pending", resolved, std::string(op) + ":" + std::to_string(slot)});
  delta.metadata = object({{"op", std::string(op)}});
  return delta;
}

SemanticDelta semantic_created(std::string_view entity_type, std::string_view entity_id, Value metadata) {
  SemanticDelta delta;
  delta.created.push_back({"pending", "pending", std::string(entity_type), std::string(entity_id)});
  delta.metadata = std::move(metadata);
  return delta;
}

SemanticDelta semantic_modified(std::string_view entity_type, std::string_view entity_id, Value metadata) {
  SemanticDelta delta;
  delta.modified.push_back({"pending", "pending", std::string(entity_type), std::string(entity_id)});
  delta.metadata = std::move(metadata);
  return delta;
}

void attach_track_summary(Shape& shape, std::string_view op, const TopoDelta* delta, const DeltaEntries* entries) {
  Value track = object({{"op", std::string(op)}});
  if (delta != nullptr) {
    track.set("has_delta", true);
    track.set("preserved", static_cast<std::int64_t>(delta->preserved.size()));
    track.set("modified", static_cast<std::int64_t>(delta->modified.size()));
    track.set("generated", static_cast<std::int64_t>(delta->generated.size()));
    track.set("deleted", static_cast<std::int64_t>(delta->deleted.size()));
  }
  if (entries != nullptr && !entries->empty()) track.set("entry_count", static_cast<std::int64_t>(entries->size()));
  shape.set_metadata_deferred("track", track);
}

// ---------------------------------------------------------------------------
// Finishing an operator
// ---------------------------------------------------------------------------
Shape finalize_tracked_shape(Shape shape, TopoDelta delta, DeltaEntries entries, FinalizeSpec spec) {
  const OutputTagPlan plan = plan_output_tags(spec.record.op, spec.tags);
  // Roles are checked against the full delta, so a bad request fails before anything is recorded.
  const std::map<std::string, Kind> target_kinds = validate_operation_output_roles(delta, plan.assignments);
  const std::vector<Shape> sources = consumed_shapes(spec);

  const bool tracked = current_tracking_policy() != TrackingPolicy::Graph;
  if (tracked) apply_tracking_tags(shape, delta, entries, TrackingContext{spec.record.op, sources});
  attach_track_summary(shape, spec.record.op, tracked ? &delta : nullptr, tracked ? &entries : nullptr);

  if (current_recorder() != nullptr) {
    spec.record.delta = tracked ? std::optional<TopoDelta>(delta) : std::nullopt;
    record_now(spec.record, shape);
  }
  return apply_output_tags(std::move(shape), spec, plan, target_kinds, delta, sources);
}

Shape finalize_derived_shape(Shape shape, FinalizeSpec spec) {
  const OutputTagPlan plan = plan_output_tags(spec.record.op, spec.tags);
  const TopoDelta delta = spec.record.delta.value_or(TopoDelta{});
  const std::map<std::string, Kind> target_kinds = validate_operation_output_roles(delta, plan.assignments);
  const std::vector<Shape> sources = consumed_shapes(spec);

  attach_track_summary(shape, spec.record.op);
  if (current_recorder() != nullptr) record_now(spec.record, shape);
  return apply_output_tags(std::move(shape), spec, plan, target_kinds, delta, sources);
}

Shape finalize_primitive_shape(Shape shape, OpRecord record) {
  attach_track_summary(shape, record.op);
  if (current_recorder() != nullptr) record_now(record, shape);
  return shape;
}

std::optional<ValueLineage> finalize_runtime_object(OpRecord record, std::string_view entity_type,
                                                    const std::vector<ValueLineage>& inputs) {
  Recorder* recorder = current_recorder();
  if (recorder == nullptr) return std::nullopt;
  record.semantic_delta = semantic_delta_for_output(record.op, 1, entity_type);
  apply_node_labels(record);
  return recorder->record_value_op(record, inputs);
}

// ---------------------------------------------------------------------------
// Lineage and runtime helpers
// ---------------------------------------------------------------------------
namespace {

int coverage_rank(std::string_view coverage) {
  if (coverage == "complete") return 0;
  if (coverage == "partial") return 1;
  if (coverage == "none") return 2;
  return -1;
}

// The weakest of the known coverage words; "complete" when none is known.
std::string weakest_coverage(std::initializer_list<std::string_view> values) {
  std::string out = "complete";
  int best = 0;
  for (const auto value : values) {
    const int rank = coverage_rank(value);
    if (rank > best) {
      best = rank;
      out = std::string(value);
    }
  }
  return out;
}

std::string runtime_coverage(const Shape& shape) {
  const Value v = shape.get_runtime("semantic.lineage.coverage");
  return v.is_string() ? v.as_string() : std::string();
}

}  // namespace

void attach_lineage_from_source(const Shape& source, Shape& target, LineageDerivation derivation,
                                std::string_view op, std::string_view coverage) {
  const std::string effective = weakest_coverage({coverage, runtime_coverage(source)});

  struct Carried {
    TagBinding binding;
    std::string coverage;
  };
  std::vector<Carried> carried;
  const auto find = [&](const std::string& id) {
    return std::find_if(carried.begin(), carried.end(), [&](const Carried& c) { return c.binding.binding_id == id; });
  };
  for (TagBinding& binding : source.local_tag_bindings())
    if (lineage_policy_allows(binding.propagation(), derivation)) carried.push_back({std::move(binding), effective});
  for (const TagLineageWitness& witness : source.lineage_witnesses()) {
    if (!lineage_policy_allows(witness.binding.propagation(), witness.derivation) ||
        !lineage_policy_allows(witness.binding.propagation(), derivation))
      continue;
    const std::string witness_coverage = weakest_coverage({effective, witness.coverage});
    const auto existing = find(witness.binding.binding_id);
    if (existing != carried.end()) existing->coverage = weakest_coverage({existing->coverage, witness_coverage});
    else carried.push_back({witness.binding, witness_coverage});
  }

  for (const Carried& item : carried) {
    TagEvidence evidence;
    evidence.kind = TagEvidenceKind::TopologyChange;
    evidence.data = object({{"op", std::string(op)},
                            {"derivation", std::string(to_string(derivation))},
                            {"coverage", item.coverage}});
    target.add_tag_lineage(item.binding, derivation, source.topo_id(), std::move(evidence), item.coverage);
  }
  target.set_runtime_deferred("semantic.lineage.coverage", weakest_coverage({runtime_coverage(target), effective}));
}

void copy_runtime_state(const Shape& source, Shape& target) {
  if (!source.runtime().is_object()) return;
  for (const auto& [key, value] : source.runtime().as_object()) {
    // A transformed BRep owns new geometry: its mesh is never the source's.
    if (key == "mesh.error" || key == "mesh.default" || detail::starts_with(key, "mesh:")) continue;
    target.set_runtime(key, value);
  }
}

std::optional<TopoDelta> merge_topo_deltas(const std::vector<TopoDelta>& deltas) {
  if (deltas.empty()) return std::nullopt;
  TopoDelta merged;
  Value steps = Value::array();
  std::int64_t index = 0;
  const auto append = [](std::vector<TopoRef>& to, const std::vector<TopoRef>& from) {
    to.insert(to.end(), from.begin(), from.end());
  };
  for (const TopoDelta& delta : deltas) {
    append(merged.preserved, delta.preserved);
    append(merged.modified, delta.modified);
    append(merged.generated, delta.generated);
    append(merged.deleted, delta.deleted);
    append(merged.section_edges, delta.section_edges);
    merged.entries.insert(merged.entries.end(), delta.entries.begin(), delta.entries.end());
    steps.push_back(object({{"index", index++},
                            {"preserved", static_cast<std::int64_t>(delta.preserved.size())},
                            {"modified", static_cast<std::int64_t>(delta.modified.size())},
                            {"generated", static_cast<std::int64_t>(delta.generated.size())},
                            {"deleted", static_cast<std::int64_t>(delta.deleted.size())},
                            {"section_edges", static_cast<std::int64_t>(delta.section_edges.size())}}));
  }
  merged.raw_event = object({{"steps", std::move(steps)}});
  return merged;
}

// ---------------------------------------------------------------------------
// Semantic ids
// ---------------------------------------------------------------------------
void reserve_semantic_id(std::string_view kind, std::string_view value) {
  Recorder* recorder = current_recorder();
  if (recorder == nullptr) return;
  auto& registry = recorder->semantic_ids[std::string(kind)];
  if (!registry.insert(std::string(value)).second)
    throw ValueError("duplicate " + std::string(kind) + " id in active GraphSession: " + std::string(value));
}

}  // namespace scad
