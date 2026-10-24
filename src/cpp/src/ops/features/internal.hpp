// Helpers the feature operators share.  Private to src/ops/features.
#pragma once

#include <string>
#include <string_view>
#include <utility>

#include <TopoDS.hxx>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/features.hpp"
#include "scad/ops/features/support.hpp"
#include "scad/ops/features/tags.hpp"
#include "scad/semantic/finalize.hpp"
#include "scad/topo/recorder.hpp"

namespace scad::features_detail {

// The role tags of a sweep-family operator, by the roles its operation proves.
inline OutputTags sweep_output_tags(const SweepTags& tags, std::string start, std::string end, std::string side) {
  OutputTags out;
  out.tag_prefix = tags.tag_prefix;
  out.result_tag = tags.result_tag;
  out.roles = {{std::move(start), tags.start_face_tag}, {std::move(end), tags.end_face_tag},
               {std::move(side), tags.side_faces_tag}};
  return out;
}

// The face of a closed wire (BRepBuilderAPI_MakeFace, planar only).
inline Face face_of_wire(const Wire& wire) { return Face(kernel::make_face_from_wire(TopoDS::Wire(wire.wrapped()))); }

// A direction given in current coordinates, placed in the world.
inline Vec3 place_vector(const Vec3& local) { return current_cs().transform_vector(local); }
inline Vec3 place_point(const Vec3& local) { return current_cs().transform_point(local); }

// The step of an operator that never reaches the recorder's shapes with tags: stamp the
// "track" summary and hand the operation to the recorder.
inline void record_plain(Shape& shape, OpRecord record) {
  attach_track_summary(shape, record.op);
  record_operation(record, {shape});
}

}  // namespace scad::features_detail
