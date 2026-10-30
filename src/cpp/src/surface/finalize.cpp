// The surface area's seam to the semantic layer; see finalize.hpp.
//
// Each overload does the tail of the Python operator it belongs to, in Python's order, on top of
// include/scad/semantic/finalize.hpp (track summary, recording, role / result tags, lineage).
#include "finalize.hpp"

#include <algorithm>
#include <map>
#include <set>

#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include "scad/core/error.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/semantic/tracking.hpp"
#include "scad/topo/tag_factories.hpp"
#include "scad/topo/tagging.hpp"

namespace scad::surface::detail {

namespace {

constexpr const char* kCoverageKey = "semantic.lineage.coverage";

OpRecord to_op_record(OperationRecord record, std::optional<TopoDelta> delta = std::nullopt) {
  OpRecord out;
  out.labels = std::move(record.labels);
  out.op = std::move(record.op);
  out.params = std::move(record.params);
  out.symbolic = std::move(record.symbolic);
  out.inputs = std::move(record.inputs);
  out.delta = std::move(delta);
  // The ordered inputs these builders replay from (_finalize_derived_shape).
  static const std::set<std::string, std::less<>> kOrderedInputOps = {
      "make_ruled_surface_rface", "make_gordon_surface_rface", "make_surface_patch_rface",     "trim_surface_rface",
      "make_loft_rshell",         "sew_faces_rshell",          "make_solid_from_shell_rsolid", "fill_holes_rshell"};
  if (Recorder* recorder = current_recorder(); recorder != nullptr && kOrderedInputOps.count(out.op) != 0) {
    std::vector<Shape> shapes;
    for (const OpInput& input : out.inputs)
      shapes.push_back(input.shape);
    // A recorder that keeps no references (the test double) answers nothing: the record stays as it is.
    if (std::optional<Value> refs = recorder->input_refs(shapes)) {
      if (!refs->is_array() || refs->as_array().size() != shapes.size())
        throw ValueError(out.op + " requires every ordered input to have a graph reference");
      out.params.set("input_refs", std::move(*refs));
    }
  }
  return out;
}

// The default labels of a surface node: built from numbers or derived from shapes, then the kind.
std::vector<std::string> default_labels(const OperationRecord& record, Kind kind) {
  return {record.inputs.empty() ? "primitive" : "derived", "surface", std::string(kind_name(kind))};
}

// _surface_tag_output: "<prefix>.<kind>" on the result.
void apply_prefix_tag(Shape& result, const TagPrefix& prefix) {
  if (!prefix)
    return;
  result.apply_tag(normalize_tag(*prefix, true) + "." + std::string(kind_name(result.kind())), false);
}

// _carry_face_provenance: result face mapped[i] continues source face i.
void carry_face_provenance(const std::vector<Face>& result_faces, const std::vector<Face>& source_faces,
                           std::optional<std::vector<int>> mapped, bool allow_orientation_change,
                           bool replace_local_bindings) {
  if (!mapped) {
    mapped.emplace();
    for (const Face& source : source_faces) {
      std::vector<int> matches;
      for (std::size_t i = 0; i < result_faces.size(); ++i)
        if (result_faces[i].wrapped().IsSame(source.wrapped()))
          matches.push_back(static_cast<int>(i));
      if (matches.size() != 1)
        throw ValueError("face continuation mapping is incomplete or ambiguous");
      mapped->push_back(matches.front());
    }
  }
  const std::set<int> distinct(mapped->begin(), mapped->end());
  if (mapped->size() != source_faces.size() || distinct.size() != result_faces.size())
    throw ValueError("face continuation mapping is not one-to-one");

  for (std::size_t i = 0; i < source_faces.size(); ++i) {
    const Face& source = source_faces[i];
    const int result_index = (*mapped)[i];
    if (result_index < 0 || static_cast<std::size_t>(result_index) >= result_faces.size())
      throw ValueError("face continuation mapping contains an invalid result index");
    Face face = result_faces[static_cast<std::size_t>(result_index)];

    const Value provenance = source.get_metadata("provenance");
    if (provenance.is_object() && !allow_orientation_change) {
      const Value* construction = provenance.find("construction");
      if (construction != nullptr && construction->is_string() && construction->as_string() == "exact_transcription" &&
          !face.wrapped().IsEqual(source.wrapped()))
        throw ValueError("sewing modified an exact-transcription input face");
    }
    if (replace_local_bindings) {
      std::vector<TagBinding> projected;
      for (const TagBinding& binding : source.local_tag_bindings())
        if (lineage_policy_allows(binding.propagation(), LineageDerivation::Continuation))
          projected.push_back(binding);
      face.replace_local_tag_bindings(std::move(projected));
    }
    attach_lineage_from_source(source, face, LineageDerivation::Continuation, "face_continuation", "complete");
    if (provenance.is_object())
      face.set_metadata("provenance", provenance);
    face.set_runtime(kCoverageKey, "complete");
  }
}

bool has_semantic_state(const Shape& shape) {
  return !shape.local_bindings().empty() || !shape.lineage_witnesses().empty() || shape.metadata().size() != 0 ||
         shape.runtime().size() != 0;
}

// The entities of `source` that kept their identity in `target` carry their state with them.
void move_state_to_identical_entities(const Shell& source, const Solid& target) {
  for (const TopAbs_ShapeEnum type : {TopAbs_SHELL, TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE, TopAbs_VERTEX}) {
    TopTools_IndexedMapOfShape source_map, target_map;
    TopExp::MapShapes(source.wrapped(), type, source_map);
    TopExp::MapShapes(target.wrapped(), type, target_map);
    for (int i = 1; i <= source_map.Extent(); ++i) {
      const TopoDS_Shape& from = source_map(i);
      const int j = target_map.FindIndex(from);
      if (j == 0)
        continue;
      const Shape source_entity = source.sub(from);
      if (!has_semantic_state(source_entity))
        continue;
      Shape target_entity = target.sub(target_map(j));
      target_entity.copy_semantic_state_from(source_entity);
    }
  }
}

// ---- loft ---------------------------------------------------------------------------------------
using Members = std::map<std::pair<Kind, std::string>, Shape>;

std::string upper_kind_name(Kind kind) {
  std::string name(kind_name(kind));
  std::transform(name.begin(), name.end(), name.begin(),
                 [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  return name;
}

// The faces and boundary wires of `shell` by the kernel id the delta's roles name.
Members role_candidates(const Shell& shell) {
  Members out;
  for (const Face& face : shell.faces())
    out.emplace(std::pair{Kind::Face, kernel_topo_id(face.wrapped())}, face);
  for (const Wire& wire : shell.wires())
    out.emplace(std::pair{Kind::Wire, kernel_topo_id(wire.wrapped())}, wire);
  return out;
}

// _apply_loft_role_metadata: each proven role is also written into the member's `track` metadata,
// which is what the output_role selectors read.
void apply_loft_role_metadata(const Members& members, const TopoDelta& delta, const std::string& op) {
  for (const TopoRoleEntry& entry : delta.roles) {
    const auto found = members.find({entry.ref.kind, entry.ref.topo_id});
    if (found == members.end())
      continue;
    Shape member = found->second;
    Value track = member.get_metadata("track", Value::object());
    if (!track.is_object())
      track = Value::object();
    std::set<std::string> roles{entry.role};
    if (const Value* existing = track.find("result_roles"); existing != nullptr && existing->is_array())
      for (const Value& role : existing->as_array())
        if (role.is_string())
          roles.insert(role.as_string());
    Value role_list = Value::array();
    for (const std::string& role : roles)
      role_list.push_back(role);
    track.set("op", op);
    track.set("topo_id", entry.ref.topo_id);
    track.set("kind", upper_kind_name(entry.ref.kind));
    track.set("coverage", "complete");
    track.set("status", "proven");
    track.set("result_roles", std::move(role_list));
    member.set_metadata("track", std::move(track));
  }
}

// _apply_shell_loft_tag_prefix
Shell apply_shell_loft_tag_prefix(Shell shell, const LoftOutput& output) {
  if (!output.tags.tag_prefix)
    return shell;
  const std::string prefix = normalize_tag(*output.tags.tag_prefix, true);
  const std::string source = "simplecadapi.loft_rshell.tag_prefix";
  Shape result = apply_topology_identity_tag(shell, NativeSelector::exactly_one(Kind::Shell), prefix + ".shell",
                                             Kind::Shell, "shell", source);
  const std::pair<bool, std::pair<const char*, const char*>> ends[] = {{output.has_start, {"loft.start_wire", "start"}},
                                                                       {output.has_end, {"loft.end_wire", "end"}}};
  for (const auto& [present, names] : ends) {
    if (!present)
      continue;
    result = apply_topology_identity_tag(result, NativeSelector::with_output_role(Kind::Wire, names.first, true),
                                         prefix + ".wire." + names.second, Kind::Wire, names.second, source);
  }
  result = apply_topology_identity_tag(result, NativeSelector::with_output_role(Kind::Face, "loft.side", false),
                                       prefix + ".face.side", Kind::Face, "side", source);
  return Shell(result);
}

}  // namespace

// =====================================================================================================
Face finalize_surface_output(Face result, FaceOutput output) {
  for (const Shape& source : output.fragment_sources)
    attach_lineage_from_source(source, result, LineageDerivation::Fragment, output.record.op, "partial");
  const bool primitive = output.record.inputs.empty();
  if (output.record.labels.empty()) {
    output.record.labels = default_labels(output.record, Kind::Face);
    if (output.record.op == "trim_surface_rface")
      output.record.labels.push_back("trimmed");
  }
  OpRecord record = to_op_record(std::move(output.record));
  Face finalized = primitive ? finalize_primitive<Face>(std::move(result), std::move(record))
                             : finalize_derived<Face>(std::move(result), FinalizeSpec{.record = std::move(record)});
  apply_prefix_tag(finalized, output.tag_prefix);
  return finalized;
}

Shell finalize_surface_output(Shell result, LoftOutput output) {
  apply_loft_role_metadata(role_candidates(result), output.delta, output.record.op);

  FinalizeSpec spec;
  spec.tags.result_tag = output.tags.result_tag;
  spec.tags.roles = {{"loft.start_wire", output.tags.start_wire_tag},
                     {"loft.end_wire", output.tags.end_wire_tag},
                     {"loft.side", output.tags.side_faces_tag}};
  if (output.record.labels.empty())
    output.record.labels = default_labels(output.record, Kind::Shell);
  spec.record = to_op_record(std::move(output.record), output.delta);
  const Shell finalized = finalize_derived<Shell>(std::move(result), std::move(spec));
  return apply_shell_loft_tag_prefix(finalized, output);
}

Shell finalize_surface_output(Shell result, SewnOutput output) {
  if (output.record.labels.empty())
    output.record.labels = default_labels(output.record, Kind::Shell);
  Shell finalized =
      finalize_derived<Shell>(std::move(result), FinalizeSpec{.record = to_op_record(std::move(output.record))});
  carry_face_provenance(finalized.faces(), output.sources, std::move(output.result_face_indices), false, true);
  apply_prefix_tag(finalized, output.tag_prefix);
  return finalized;
}

Shell finalize_surface_output(Shell result, FilledOutput output) {
  if (output.record.labels.empty())
    output.record.labels = default_labels(output.record, Kind::Shell);
  Shell finalized =
      finalize_derived<Shell>(std::move(result), FinalizeSpec{.record = to_op_record(std::move(output.record))});
  apply_prefix_tag(finalized, output.tag_prefix);
  return finalized;
}

Solid finalize_surface_output(Solid result, SolidifiedOutput output) {
  if (output.record.labels.empty())
    output.record.labels = default_labels(output.record, Kind::Solid);
  move_state_to_identical_entities(output.source, result);
  attach_lineage_from_source(output.source, result, LineageDerivation::Continuation, "make_solid_from_shell_rsolid",
                             "partial");
  Solid finalized =
      finalize_derived<Solid>(std::move(result), FinalizeSpec{.record = to_op_record(std::move(output.record))});
  carry_face_provenance(finalized.faces(), output.source.faces(), std::nullopt, true, false);
  apply_prefix_tag(finalized, output.tag_prefix);
  return finalized;
}

std::vector<Wire> finalize_surface_output(std::vector<Wire> result, BoundariesOutput output) {
  if (current_recorder() == nullptr)
    return result;
  OpRecord record = to_op_record(std::move(output.record));
  record.semantic_delta = semantic_delta_for_output(record.op, static_cast<int>(result.size()), "Profile");
  record.empty_list_result = result.empty();
  record_operation(record, std::vector<Shape>(result.begin(), result.end()));
  return result;
}

}  // namespace scad::surface::detail
