// How a surface operator finishes: the one place the area touches the semantic layer.
//
// Each result kind has one `finalize_surface_output` overload.  It does what Python's
// `_finalize_primitive_shape` / `_finalize_derived_shape` and the operators' own tail do:
// attach the `track` summary, record the operation, carry tags and provenance from the
// inputs, apply the caller's tag_prefix / role tags.  Operators build geometry, describe it
// in one of the structs below, and return what this function returns.
//
// include/scad/semantic/finalize.hpp is the home of the shared pipeline; wiring these
// overloads to it changes finalize.cpp only.
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/surface/operators.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad::surface::detail {

// What the recorder is told about the operation.
struct OperationRecord {
  std::string op;                                           // the recorded name ("make_loft_rshell")
  Value params = Value::object();                           // evaluated numbers, JSON-like
  std::vector<std::pair<std::string, Scalar>> symbolic;     // only the Var/Expr arguments
  std::vector<OpInput> inputs;
  // The node labels (`tags=` of record_operation_if_active); empty = {primitive|derived, surface, <kind>}.
  std::vector<std::string> labels;
};

// A Face, whether built from data (`inputs` empty) or from shapes.
struct FaceOutput {
  OperationRecord record;
  TagPrefix tag_prefix;
  // trim_surface_rface: the shapes whose tags continue onto the result as partial fragments.
  std::vector<Shape> fragment_sources;
};
Face finalize_surface_output(Face result, FaceOutput output);

// loft_rshell.  `delta` carries the kernel-proven roles ("loft.side", "loft.start_wire",
// "loft.end_wire") of the result's faces and boundary wires.
struct LoftOutput {
  OperationRecord record;
  TopoDelta delta;
  LoftShellTags tags;
  bool has_start = false;
  bool has_end = false;
};
Shell finalize_surface_output(Shell result, LoftOutput output);

// sew_faces_rshell: input face i became result face `result_face_indices[i]`.
struct SewnOutput {
  OperationRecord record;
  TagPrefix tag_prefix;
  std::vector<Face> sources;
  std::vector<int> result_face_indices;
};
Shell finalize_surface_output(Shell result, SewnOutput output);

// fill_holes_rshell.
struct FilledOutput {
  OperationRecord record;
  TagPrefix tag_prefix;
};
Shell finalize_surface_output(Shell result, FilledOutput output);

// make_solid_from_shell_rsolid: the semantic state of the shell's entities moves to the
// identical entities of the solid.
struct SolidifiedOutput {
  OperationRecord record;
  TagPrefix tag_prefix;
  Shell source;
};
Solid finalize_surface_output(Solid result, SolidifiedOutput output);

// free_boundaries_rwirelist: zero or more Wires, one output slot each.
struct BoundariesOutput {
  OperationRecord record;
  Shell source;
};
std::vector<Wire> finalize_surface_output(std::vector<Wire> result, BoundariesOutput output);

}  // namespace scad::surface::detail
