// Helpers the geometry operators share.  Private to src/ops/geometry.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <TopoDS.hxx>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/features.hpp"
#include "scad/ops/geometry/params.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/reactive/session.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/topo/recorder.hpp"

namespace scad::geometry_detail {

// Python's `get_active_session() is not None`: the profile makers then build their
// result out of recorded edge / wire operations instead of one primitive.  Any
// recorder counts, so everything that is recorded can be replayed.
inline bool graph_recording() {
  return reactive::Session::active_session() != nullptr || current_recorder() != nullptr;
}

// An argument point, evaluated and placed in world coordinates through the current system.
inline Vec3 place_point(const Scalar3& point, std::string_view label) {
  return current_cs().transform_point(evaluate_point(point, label));
}
inline Vec3 place_vector(const Scalar3& vector, std::string_view label) {
  return current_cs().transform_vector(evaluate_point(vector, label));
}

// The record of an operation.  It is only worth building when something records it; the
// op name alone is enough for the track summary.
template <class Build>
OpRecord record_for(std::string_view op, Build&& build) {
  if (current_recorder() != nullptr)
    return std::forward<Build>(build)();
  OpRecord stub;
  stub.op = std::string(op);
  return stub;
}

template <class T, class Build>
T finalize_primitive_with(T shape, std::string_view op, Build&& build) {
  return finalize_primitive(std::move(shape), record_for(op, std::forward<Build>(build)));
}

// FinalizeSpec for a derived result (no role tags).
inline FinalizeSpec derived_spec(OpRecord record) {
  FinalizeSpec spec;
  spec.record = std::move(record);
  return spec;
}

// "simplecadapi.<operation>.tag_prefix": the authoring source of an operator's prefix tags.
inline std::string prefix_source(std::string_view operation) {
  return "simplecadapi." + std::string(operation) + ".tag_prefix";
}

// `shape` with its tag prefix applied: the handle to return (it is a detached view
// when a recorder is installed).
template <class T>
T with_shape_prefix(T shape, const OptionalString& tag_prefix, std::string_view operation) {
  return T(apply_shape_tag_prefix(std::move(shape), tag_prefix, T::kKind, prefix_source(operation)));
}

// `_apply_profile_tag_prefix` for the one-edge profiles (circle, ellipse): the edge is named
// `edge_tag`, or `default_edge_name`, whenever a prefix or an edge tag was asked for.
template <class T>
T with_profile_prefix(T shape, const OptionalString& tag_prefix, const OptionalString& edge_tag,
                      std::string_view default_edge_name, std::string_view operation) {
  std::optional<std::vector<std::string>> edge_names;
  if (tag_prefix || edge_tag) {
    edge_names = std::vector<std::string>{edge_tag && !edge_tag->empty() ? *edge_tag : std::string(default_edge_name)};
  }
  return T(apply_profile_tag_prefix(std::move(shape), tag_prefix, edge_names, prefix_source(operation)));
}

// `face._metadata = wire._metadata.copy()`
inline void copy_metadata(const Shape& from, Shape& to) {
  const Value& metadata = from.metadata();
  if (!metadata.is_object())
    return;
  for (const auto& [key, value] : metadata.as_object())
    to.set_metadata(key, value);
}

// The non-session tail of the planar profile makers: the face of a finished wire, recorded
// as `simple_op`, carrying the wire's metadata and edge identity tags.
template <class Build>
Face profile_face(const Wire& wire, std::string_view simple_op, std::string_view operation,
                  const OptionalString& tag_prefix, Build&& build) {
  Face face(kernel::make_face_from_wire(TopoDS::Wire(wire.wrapped())));
  copy_metadata(wire, face);
  Face result = finalize_primitive_with(std::move(face), simple_op, std::forward<Build>(build));
  result = Face(copy_exact_topology_identity_tags(std::move(result), {wire}, operation));
  return with_shape_prefix(std::move(result), tag_prefix, operation);
}

}  // namespace scad::geometry_detail
