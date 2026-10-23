// sew_faces_rshell and the sewing helpers shared with the shell operators.
#include <algorithm>
#include <set>

#include <BRepBuilderAPI_Sewing.hxx>
#include <BRep_Builder.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>
#include <TopoDS.hxx>

#include "finalize.hpp"
#include "internal.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/surface/operators.hpp"

namespace scad {

namespace surface::detail {

TopoDS_Shell shell_from_face(const TopoDS_Face& face) {
  BRep_Builder builder;
  TopoDS_Shell shell;
  builder.MakeShell(shell);
  builder.Add(shell, face);
  return shell;
}

SewnShell sew_faces_with_history(const std::vector<TopoDS_Face>& faces, double tolerance) {
  BRepBuilderAPI_Sewing sewing(tolerance, true, true, false, false);
  sewing.SetNonManifoldMode(false);
  sewing.SetLocalTolerancesMode(false);
  sewing.SetMinTolerance(tolerance);
  sewing.SetMaxTolerance(tolerance);
  for (const TopoDS_Face& face : faces) sewing.Add(face);
  sewing.Perform();
  if (sewing.NbMultipleEdges() != 0) throw ValueError("face sewing produced non-manifold multiple edges");
  if (sewing.NbDeletedFaces() != 0) throw ValueError("face sewing deleted one or more input faces");

  const TopoDS_Shape shape = sewing.SewedShape();
  if (shape.IsNull()) throw ValueError("OCP sewing returned a null shape");
  TopoDS_Shell shell;
  if (shape.ShapeType() == TopAbs_SHELL) {
    shell = TopoDS::Shell(shape);
  } else if (shape.ShapeType() == TopAbs_FACE) {
    shell = shell_from_face(TopoDS::Face(shape));
  } else {
    const std::vector<TopoDS_Shape> shells = kernel::explore(shape, TopAbs_SHELL);
    if (shells.size() != 1)
      throw ValueError("faces do not sew into exactly one connected shell; OCP produced " +
                       std::to_string(shells.size()) + " shell components");
    shell = TopoDS::Shell(shells.front());
  }

  const std::vector<TopoDS_Face> result_faces = kernel::faces_of(shell);
  if (result_faces.size() != faces.size())
    throw ValueError("face sewing did not preserve every input face: expected " + std::to_string(faces.size()) +
                     ", got " + std::to_string(result_faces.size()));

  SewnShell out{shell, {}};
  for (const TopoDS_Face& source : faces) {
    const TopoDS_Shape mapped = sewing.ModifiedSubShape(source);
    if (mapped.IsNull() || mapped.ShapeType() != TopAbs_FACE)
      throw ValueError("face sewing history did not retain one input face");
    std::vector<int> matches;
    for (std::size_t i = 0; i < result_faces.size(); ++i)
      if (result_faces[i].IsSame(mapped)) matches.push_back(static_cast<int>(i));
    if (matches.size() != 1) throw ValueError("face sewing history is incomplete or ambiguous");
    out.result_face_indices.push_back(matches.front());
  }
  const std::set<int> distinct(out.result_face_indices.begin(), out.result_face_indices.end());
  if (distinct.size() != result_faces.size()) throw ValueError("face sewing history is not one-to-one");
  return out;
}

TopoDS_Shell sew_faces(const std::vector<TopoDS_Face>& faces, double tolerance) {
  return sew_faces_with_history(faces, tolerance).shell;
}

std::vector<TopoDS_Wire> free_boundaries(const TopoDS_Shape& shell, double tolerance) {
  const ShapeAnalysis_FreeBounds analysis(shell, tolerance, false, true);
  std::vector<TopoDS_Wire> unique;
  for (const TopoDS_Shape& group : {analysis.GetClosedWires(), analysis.GetOpenWires()})
    for (const TopoDS_Wire& wire : kernel::wires_of(group)) {
      const bool seen = std::any_of(unique.begin(), unique.end(), [&](const TopoDS_Wire& w) { return w.IsSame(wire); });
      if (!seen) unique.push_back(wire);
    }
  return unique;
}

}  // namespace surface::detail

using namespace surface::detail;

Shell sew_faces_rshell(const std::vector<Face>& faces, double tolerance, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec{
      "sew_faces_rshell",
      "Failed to sew faces into one shell.",
      {"Faces are disconnected or their gaps exceed tolerance.", "The sewing result contains multiple shell components.",
       "Faces built with make_surface_patch_rface re-fit their boundary edges, so patches no longer share exact boundaries."},
      {"Pass connected Face objects and a positive sewing tolerance.",
       "When freeform patches must share exact boundary edges, build them with make_gordon_surface_rface on a shared "
       "edge network before sewing."}};
  return operator_scope(kSpec, [&] {
    if (faces.empty()) throw ValueError("sew_faces_rshell requires a non-empty Face sequence");
    require_positive_finite(tolerance, "tolerance");
    std::vector<TopoDS_Face> raw;
    for (const Face& face : faces) raw.push_back(TopoDS::Face(face.wrapped()));
    SewnShell sewn = sew_faces_with_history(raw, tolerance);

    Value params = Value::object();
    params.set("face_count", static_cast<std::int64_t>(faces.size()));
    params.set("tolerance", tolerance);
    params.set("tag_prefix", to_value(tag_prefix));
    SewnOutput output{.record = {.op = "sew_faces_rshell", .params = std::move(params)},
                      .tag_prefix = tag_prefix,
                      .sources = faces,
                      .result_face_indices = std::move(sewn.result_face_indices)};
    for (const Face& face : faces) output.record.inputs.push_back({face, "face"});
    return finalize_surface_output(Shell(sewn.shell), std::move(output));
  });
}

}  // namespace scad
