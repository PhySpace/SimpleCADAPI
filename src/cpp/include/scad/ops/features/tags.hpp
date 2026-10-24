// The keyword-only tag options of the feature operators.
//
// Every option is "name this result / these faces": an empty option is "not requested".
// The role tags (start / end / side faces, fillet patches ...) must be proven by the
// kernel's history of the operation, so asking for one the operation cannot prove is an
// error, never a guess.
#pragma once

#include "scad/ops/geometry/types.hpp"  // OptionalString

namespace scad {

// extrude_rsolid, revolve_rsolid, loft_rsolid, sweep_rsolid, twisted_sweep_rsolid.
struct SweepTags {
  OptionalString tag_prefix;  // "<prefix>.solid", "<prefix>.face.start", ...
  OptionalString result_tag;  // on the solid itself
  OptionalString start_face_tag, end_face_tag, side_faces_tag;
};

// fillet_rsolid, chamfer_rsolid.
struct BlendTags {
  OptionalString result_tag;
  OptionalString generated_faces_tag;  // the blend patches
};

// shell_rsolid.
struct ShellTags {
  OptionalString result_tag;
  OptionalString body_faces_tag, offset_faces_tag, closing_faces_tag, wall_edges_tag;
};

}  // namespace scad
