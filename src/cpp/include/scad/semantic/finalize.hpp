// How an operator finishes: the semantic half of operators/_support.py.
//
// Every operator ends with one call into this header.  It does, in Python's order:
// validate the role tags the caller asked for, project tracking evidence and source
// tags onto the result, attach the `track` summary, record the operation (with its
// topology delta) through the Recorder hook, then apply role / result / prefix tags.
//
//   // extrude_rsolid(profile, direction, distance, tag_prefix, result_tag, start_face_tag, ...)
//   static const char* kOp = "make_extrude_rsolid";
//   OutputTags tags{.tag_prefix = tag_prefix,
//                   .result_tag = result_tag,
//                   .roles = {{"extrusion.start", start_face_tag},
//                             {"extrusion.end", end_face_tag},
//                             {"extrusion.side", side_faces_tag}}};
//   plan_output_tags(kOp, tags);            // optional: fail on bad tag names before doing any work
//   TrackedResult tracked = tracked_extrude(...);
//   tracked.shape.apply_tag("solid.extrusion", false);
//   return finalize_tracked_solid(std::move(tracked),
//       {.record = {.op = kOp,
//                   .params = params,                      // JSON-like, evaluated numbers
//                   .symbolic = symbolic,                  // only the Var/Expr arguments
//                   .inputs = {{profile, "profile"}}},
//        .tags = tags,
//        .roles = {.start = "extrusion.start", .end = "extrusion.end", .side = "extrusion.side"}});
//
// Primitives that have no tracking evidence end with `finalize_primitive`.  Shapes that
// carry an operator-built delta (loft shells, sewn faces, ...) end with `finalize_derived`.
//
// Tagging is done in place when no recorder is installed.  With a recorder every tag
// assignment is a graph node (as in Python), so the result is a detached view, and the
// returned handle is the one the operator must hand back to its caller.
#pragma once

#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/core/engaged.hpp"
#include "scad/core/value.hpp"
#include "scad/semantic/selection.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// ===========================================================================
// 1. What an operator lets its caller name
// ===========================================================================

// One output role and the tag the caller wants on it: {"extrusion.start", start_face_tag}.
// An empty `tag` (the argument was None) means "not requested".
struct RoleTag {
  std::string role;
  std::optional<std::string> tag;
};

struct OutputTags {
  std::optional<std::string> tag_prefix;  // names the result and its parts: "<prefix>.solid", "<prefix>.face.top"
  std::optional<std::string> result_tag;  // tag on the result entity itself
  std::vector<RoleTag> roles;             // in the operator's declaration order
};

enum class RoleCardinality { One, Many };

struct RoleAssignment {
  std::string role;
  RoleCardinality cardinality = RoleCardinality::One;
  std::string tag;  // normalized
};

// The roles an operation can name, in declaration order (_OPERATION_OUTPUT_ROLE_CARDINALITY).
// KeyError for an operation the table does not know.
const std::vector<std::pair<std::string, RoleCardinality>>& operation_output_roles(std::string_view op);

// _normalize_operation_role_tags.  ValueError for duplicate roles, unknown roles, malformed tags.
std::vector<RoleAssignment> normalize_operation_role_tags(std::string_view op, const std::vector<RoleTag>& named);

// _validate_operation_output_roles: each requested role must be proven by the
// delta with the right cardinality and a single topology kind (SemanticCapabilityError
// otherwise).  Returns role -> the kind its entities have.
std::map<std::string, Kind> validate_operation_output_roles(const TopoDelta& delta,
                                                            const std::vector<RoleAssignment>& assignments);

// Everything in OutputTags that can be checked before any geometry is built.
struct OutputTagPlan {
  std::vector<RoleAssignment> assignments;
  std::optional<std::string> result_tag;  // normalized
  std::optional<std::string> tag_prefix;  // normalized
};
OutputTagPlan plan_output_tags(std::string_view op, const OutputTags& tags);

// The result roles a tag_prefix names: role token -> "<prefix>.face.start" etc.
struct FeatureRoles {
  std::string start, end, side;  // face roles -> "<prefix>.face.start" / ".end" / ".side" (empty = none)
  // (role, local name): the unique edge / face holding `role` becomes "<prefix>.edge.<name>" / "<prefix>.face.<name>".
  std::vector<std::pair<std::string, std::string>> edges, faces;
};

// ===========================================================================
// 2. Finishing an operator
// ===========================================================================

struct FinalizeSpec {
  // op, params, symbolic arguments, inputs, node labels.  `delta` and `semantic_delta`
  // are filled in here (a delta given by the operator is kept for derived shapes).
  OpRecord record;
  OutputTags tags;
  FeatureRoles roles;
  // Consumed shapes that are not in record.inputs but whose tags/edges should still be projected.
  std::vector<Shape> extra_sources;
};

// _finalize_tracked_solid: for any result kind.  Under TrackingPolicy::Graph the
// delta is dropped and nothing is projected.
Shape finalize_tracked_shape(Shape shape, TopoDelta delta, DeltaEntries entries, FinalizeSpec spec);

template <class T>
T finalize_tracked(T shape, TopoDelta delta, DeltaEntries entries, FinalizeSpec spec) {
  return T(finalize_tracked_shape(std::move(shape), std::move(delta), std::move(entries), std::move(spec)));
}

inline Solid finalize_tracked_solid(TrackedResult tracked, FinalizeSpec spec) {
  return Solid(finalize_tracked_shape(std::move(tracked.shape), std::move(tracked.delta),
                                      std::move(tracked.delta_entries), std::move(spec)));
}

// Booleans: the caller has already checked that `result.solid` is set.
inline Solid finalize_tracked_solid(TrackedBooleanResult result, FinalizeSpec spec) {
  return Solid(finalize_tracked_shape(
      require_engaged(std::move(result.solid), "the caller checked that the boolean produced a solid"),
      std::move(result.delta), std::move(result.delta_entries), std::move(spec)));
}

// _finalize_derived_shape: record a shape that has no tracking evidence of its own.
// spec.record.delta may carry an operator-built delta (roles), against which any
// requested role tags are validated.
Shape finalize_derived_shape(Shape shape, FinalizeSpec spec);

template <class T>
T finalize_derived(T shape, FinalizeSpec spec) {
  return T(finalize_derived_shape(std::move(shape), std::move(spec)));
}

// _finalize_primitive_shape / _finalize_primitive_solid: track summary + record; no tags.
Shape finalize_primitive_shape(Shape shape, OpRecord record);

template <class T>
T finalize_primitive(T shape, OpRecord record) {
  return T(finalize_primitive_shape(std::move(shape), std::move(record)));
}

// _finalize_runtime_object: operations whose output is not a shape (sketches, parts, ...).
// `entity_type` is the SemanticRef entity type: "Sketch", "Part", ...
// `inputs` are the lineages of its value inputs; the answer is the lineage its result takes.
std::optional<ValueLineage> finalize_runtime_object(OpRecord record, std::string_view entity_type = "Sketch",
                                                    const std::vector<ValueLineage>& inputs = {});

// ===========================================================================
// 3. The steps, for operators that need to interleave their own work
// ===========================================================================

// _semantic_delta_for_output: `created` refs "<op>:<slot>"; entity_type "" picks it from the op name.
SemanticDelta semantic_delta_for_output(std::string_view op, int output_count = 1, std::string_view entity_type = {});
SemanticDelta semantic_created(std::string_view entity_type, std::string_view entity_id,
                               Value metadata = Value::object());
SemanticDelta semantic_modified(std::string_view entity_type, std::string_view entity_id,
                                Value metadata = Value::object());

// _attach_track_summary: metadata "track" = {op, has_delta, preserved, ..., entry_count}.
void attach_track_summary(Shape& shape, std::string_view op, const TopoDelta* delta = nullptr,
                          const DeltaEntries* entries = nullptr);

// _apply_operation_role_tags.  Returns the tagged shape (see the note on views above).
Shape apply_operation_role_tags(Shape shape, std::string_view op, const std::vector<RoleAssignment>& assignments,
                                const std::map<std::string, Kind>& target_kinds,
                                const std::optional<std::string>& result_tag);

// _apply_feature_tag_prefix: names the solid, its start/end/side faces and role edges/faces with the prefix.
Shape apply_feature_tag_prefix(Shape solid, const std::optional<std::string>& tag_prefix, std::string_view op,
                               const TopoDelta& delta, const FeatureRoles& roles,
                               const std::vector<Shape>& source_shapes = {});

// _apply_shape_tag_prefix: "<prefix>.<kind>" on the shape itself ("wire", "face", ...).
Shape apply_shape_tag_prefix(Shape shape, const std::optional<std::string>& tag_prefix, Kind kind,
                             std::string_view authoring_source);

// _apply_profile_tag_prefix: for Wire / Face profiles: "<prefix>.<kind>" plus one tag per edge.
// `edge_tags` (when given) must have one entry per edge; the default names are line1, line2, ....
Shape apply_profile_tag_prefix(Shape shape, const std::optional<std::string>& tag_prefix,
                               const std::optional<std::vector<std::string>>& edge_tags,
                               std::string_view authoring_source);

// _apply_topology_identity_tag: a downward (faces) / local (everything else) tag that also
// records its `topology_name` identity, so it can follow the entity through later operations.
Shape apply_topology_identity_tag(Shape scope, const TagTargets& targets, std::string_view tag, Kind kind,
                                  std::string_view local_name, std::string_view authoring_source);

// _copy_exact_topology_identity_tags: carry the named edge tags of `sources` onto the
// identical edges of `target`.
Shape copy_exact_topology_identity_tags(Shape target, const std::vector<Shape>& sources, std::string_view operation);

// _attach_lineage_from_source: record `source`'s tags as lineage of `target` under `derivation`.
void attach_lineage_from_source(const Shape& source, Shape& target, LineageDerivation derivation, std::string_view op,
                                std::string_view coverage = "complete");

// _copy_runtime_state: copy `source`'s runtime values to `target`, except mesh caches.
void copy_runtime_state(const Shape& source, Shape& target);

// _merge_topo_deltas; nullopt for an empty list.
std::optional<TopoDelta> merge_topo_deltas(const std::vector<TopoDelta>& deltas);

// ===========================================================================
// 4. Semantic ids (parts, assemblies, materials ... unique within a recorded session)
// ===========================================================================

// _reserve_semantic_id: ValueError on a duplicate while a recorder is installed; otherwise a no-op.
void reserve_semantic_id(std::string_view kind, std::string_view value);

}  // namespace scad
