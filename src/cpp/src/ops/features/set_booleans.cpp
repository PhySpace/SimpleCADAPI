// boolean_rsolidlist and the 2D booleans (operators/boolean.py).
#include <BRepCheck_Analyzer.hxx>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>

#include <algorithm>

#include "internal.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/booleans.hpp"

namespace scad {

namespace {

// make_compound_always: a compound holding every shape, even a single one.
TopoDS_Shape compound_of(const std::vector<Solid>& solids) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  for (const Solid& solid : solids) builder.Add(compound, solid.wrapped());
  return compound;
}

bool is_valid(const TopoDS_Shape& shape) {
  return occt_guard([&] { return BRepCheck_Analyzer(shape).IsValid(); });
}

}  // namespace

std::vector<Solid> boolean_rsolidlist(const std::vector<Solid>& left, const std::vector<Solid>& right,
                                      std::string_view operation) {
  if (operation != "cut" && operation != "intersect" && operation != "union") {
    throw ValueError("operation must be cut, intersect or union");
  }
  std::vector<Solid> inputs = left;
  inputs.insert(inputs.end(), right.begin(), right.end());
  for (const Solid& body : inputs) {
    if (body.wrapped().IsNull() || !is_valid(body.wrapped())) {
      throw ValueError("boolean groups must contain valid nonempty topology");
    }
  }

  std::optional<TopoDS_Shape> shape;
  if (operation == "union") {
    if (!inputs.empty()) {
      std::vector<TopoDS_Shape> parts;
      for (const Solid& body : inputs) parts.push_back(body.wrapped());
      shape = kernel::fuse_shapes(parts);
    }
  } else if (left.empty() || (operation == "intersect" && right.empty())) {
    // an empty operand leaves nothing
  } else if (operation == "cut") {
    std::vector<TopoDS_Shape> tools;
    for (const Solid& body : right) tools.push_back(body.wrapped());
    shape = kernel::cut_shapes(compound_of(left), tools);
  } else {
    shape = kernel::common_shapes({compound_of(left), compound_of(right)});
  }
  if (shape && !is_valid(*shape)) throw ValueError("set boolean produced invalid topology");

  std::vector<Solid> result;
  if (shape) {
    for (const TopoDS_Solid& solid : kernel::solids_of(*shape)) result.emplace_back(solid);
  }
  for (Solid& body : result) {
    for (const Solid& source : inputs) {
      attach_lineage_from_source(source, body, LineageDerivation::Continuation, "make_boolean_rsolidlist", "partial");
    }
  }

  FeatureRecord rec("make_boolean_rsolidlist");
  rec.param("operation", Value(std::string(operation)))
      .param("left_count", Value(static_cast<std::int64_t>(left.size())))
      .param("right_count", Value(static_cast<std::int64_t>(right.size())));
  for (const Solid& body : left) rec.input(body, "left");
  for (const Solid& body : right) rec.input(body, "right");
  OpRecord record = std::move(rec).take();
  if (Recorder* recorder = current_recorder()) {
    std::vector<Shape> ordered;
    for (const OpInput& input : record.inputs) ordered.push_back(input.shape);
    if (auto refs = recorder->input_refs(ordered)) record.params.set("input_refs", std::move(*refs));
  }
  record_operation(std::move(record), std::vector<Shape>(result.begin(), result.end()));
  return result;
}

namespace {

// The single face of a 2D boolean's answer.
Face single_face(const TopoDS_Shape& result, std::string_view operation) {
  const std::vector<TopoDS_Face> faces = kernel::faces_of(result);
  if (faces.size() != 1) {
    throw ValueError(std::string(operation) + " expected exactly 1 face in the result, got " + std::to_string(faces.size()));
  }
  return Face(faces.front());
}

// The shared tail of the 2D booleans: derived metadata and a record labelled "derived"/"face".
Face finish_2d(Face result, std::string_view op, const Face& first, const Face& second, bool merge_second) {
  inherit_metadata(result, {&first});
  if (merge_second) inherit_metadata(result, {&second});
  FinalizeSpec spec;
  spec.record.op = std::string(op);
  spec.record.params = Value::object();
  spec.record.inputs = {{first, "face"}, {second, "face"}};
  spec.record.labels = {"derived", "face"};
  return finalize_derived(std::move(result), std::move(spec));
}

// Both operands must be faces; `run` answers with the kernel's shape.
template <class Run>
Face boolean_2d(const ErrorSpec& spec, std::string_view op, const Shape& a, const Shape& b, const char* name_a,
                const char* name_b, bool merge, Run&& run) {
  return guarded(spec, [&]() -> Face {
    if (a.kind() != Kind::Face) throw ValueError(std::string(name_a) + " must be a Face");
    if (b.kind() != Kind::Face) throw ValueError(std::string(name_b) + " must be a Face");
    return finish_2d(single_face(run(), spec.operation), op, Face(a), Face(b), merge);
  });
}

}  // namespace

namespace {
const ErrorSpec& cut_spec() {
  static const ErrorSpec spec{"make_2d_cut_rface",
                              "Failed to subtract one face from another.",
                              {"The body or tool is not a Face.", "The faces do not overlap or are not coplanar.",
                               "The kernel could not compute a stable 2D difference."},
                              {"Pass two valid Face objects.", "Ensure both faces lie on the same plane.",
                               "Verify the tool face overlaps the body face."}};
  return spec;
}

const ErrorSpec& union_spec() {
  static const ErrorSpec spec{"make_2d_union_rface",
                              "Failed to union two faces.",
                              {"One or both inputs are not Face objects.", "The faces do not overlap or touch.",
                               "The faces are not coplanar."},
                              {"Pass two valid Face objects.", "Ensure the faces overlap or share a boundary.",
                               "Ensure both faces lie on the same plane."}};
  return spec;
}

const ErrorSpec& intersect_spec() {
  static const ErrorSpec spec{"make_2d_intersect_rface",
                              "Failed to intersect two faces.",
                              {"One or both inputs are not Face objects.", "The faces do not overlap.",
                               "The faces are not coplanar."},
                              {"Pass two valid Face objects.", "Ensure the faces have a non-empty overlap region.",
                               "Ensure both faces lie on the same plane."}};
  return spec;
}

}  // namespace

void reject_face_operand(std::string_view operation, std::string_view name) {
  const ErrorSpec& spec = operation == "make_2d_cut_rface"     ? cut_spec()
                          : operation == "make_2d_union_rface" ? union_spec()
                                                               : intersect_spec();
  const ValueError cause(std::string(name) + " must be a Face");
  raise_harness_error(spec, cause);
}

Face make_2d_cut_rface(const Shape& body, const Shape& tool) {
  const ErrorSpec& spec = cut_spec();
  return boolean_2d(spec, "make_2d_cut_rface", body, tool, "body", "tool", false,
                    [&] { return kernel::cut_shapes(body.wrapped(), {tool.wrapped()}); });
}

Face make_2d_union_rface(const Shape& face_a, const Shape& face_b) {
  const ErrorSpec& spec = union_spec();
  return boolean_2d(spec, "make_2d_union_rface", face_a, face_b, "face_a", "face_b", true,
                    [&] { return kernel::fuse_shapes({face_a.wrapped(), face_b.wrapped()}, false, std::nullopt, true); });
}

Face make_2d_intersect_rface(const Shape& face_a, const Shape& face_b) {
  const ErrorSpec& spec = intersect_spec();
  return boolean_2d(spec, "make_2d_intersect_rface", face_a, face_b, "face_a", "face_b", true,
                    [&] { return kernel::common_shapes({face_a.wrapped(), face_b.wrapped()}); });
}

}  // namespace scad
