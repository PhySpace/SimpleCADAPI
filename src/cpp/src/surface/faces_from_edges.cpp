// make_ruled_surface_rface, make_gordon_surface_rface, make_surface_patch_rface:
// faces built from edges.
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepFill.hxx>
#include <TopoDS.hxx>

#include "finalize.hpp"
#include "gordon.hpp"
#include "internal.hpp"
#include "scad/surface/fitter.hpp"
#include "scad/surface/operators.hpp"

namespace scad {

using namespace surface;
using namespace surface::detail;

namespace surface::detail {

TopoDS_Face fill_face(const FillingProblem& problem, const std::vector<TopoDS_Wire>& holes) {
  TopoDS_Face face = surface_fitter()->fill(problem);
  if (holes.empty()) return face;
  BRepBuilderAPI_MakeFace builder(face);
  for (const TopoDS_Wire& hole : holes) builder.Add(hole);
  if (!builder.IsDone()) throw ValueError("OCP could not trim the filled surface with hole wires");
  return builder.Face();
}

}  // namespace surface::detail

// ---------------------------------------------------------------------------------------------
Face make_ruled_surface_rface(const Edge& edge_a, const Edge& edge_b, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec{"make_ruled_surface_rface",
                               "Failed to create the ruled surface face.",
                               {"The inputs are not edges.", "The two edges cannot define a ruled surface."},
                               {"Pass two valid Edge objects with compatible parameterization."}};
  return operator_scope(kSpec, [&] {
    const TopoDS_Face face = BRepFill::Face(TopoDS::Edge(edge_a.wrapped()), TopoDS::Edge(edge_b.wrapped()));
    if (face.IsNull()) throw ValueError("OCP ruled-surface construction returned a null face");

    Value params = Value::object();
    params.set("tag_prefix", to_value(tag_prefix));
    return finalize_surface_output(
        Face(face), FaceOutput{.record = {.op = "make_ruled_surface_rface",
                                          .params = std::move(params),
                                          .inputs = {{edge_a, "edge_a"}, {edge_b, "edge_b"}}},
                               .tag_prefix = tag_prefix});
  });
}

// ---------------------------------------------------------------------------------------------
Face make_gordon_surface_rface(const std::vector<Edge>& profiles, const std::vector<Edge>& guides, double tolerance,
                               const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec{"make_gordon_surface_rface",
                               "Failed to create the Gordon surface face.",
                               {"The curve network is too small, non-intersecting, or inconsistent.",
                                "The kernel Gordon interpolation failed."},
                               {"Pass at least two profiles and two guides whose endpoints form a compatible network.",
                                "Increase tolerance only when the source curves are numerically noisy."}};
  return operator_scope(kSpec, [&] {
    if (profiles.size() < 2 || guides.size() < 2)
      throw ValueError("Gordon surfaces require at least two profiles and two guides");
    require_positive_finite(tolerance, "tolerance");

    std::vector<Handle(Geom_Curve)> profile_curves, guide_curves;
    for (const Edge& edge : profiles) profile_curves.push_back(network_curve_of(TopoDS::Edge(edge.wrapped())));
    for (const Edge& edge : guides) guide_curves.push_back(network_curve_of(TopoDS::Edge(edge.wrapped())));
    const Handle(Geom_BSplineSurface) fitted = surface::surface_fitter()->gordon(profile_curves, guide_curves, tolerance);

    Value params = Value::object();
    params.set("profile_count", static_cast<std::int64_t>(profiles.size()));
    params.set("guide_count", static_cast<std::int64_t>(guides.size()));
    params.set("tolerance", tolerance);
    params.set("tag_prefix", to_value(tag_prefix));
    FaceOutput output{.record = {.op = "make_gordon_surface_rface", .params = std::move(params)}, .tag_prefix = tag_prefix};
    for (const Edge& edge : profiles) output.record.inputs.push_back({edge, "profile"});
    for (const Edge& edge : guides) output.record.inputs.push_back({edge, "guide"});
    return finalize_surface_output(Face(face_from_surface(fitted)), std::move(output));
  });
}

// ---------------------------------------------------------------------------------------------
Face make_surface_patch_rface(const std::vector<SurfaceBoundary>& boundaries, const SurfacePatchOptions& options) {
  static const ErrorSpec kSpec{
      "make_surface_patch_rface",
      "Failed to fill the constrained surface patch.",
      {"A boundary is invalid, open, or incompatible with its support face.",
       "The filling controls are invalid or the kernel did not converge."},
      {"Pass non-empty SurfaceBoundary values with valid Edge objects.",
       "Use C0/G1/G2 continuity and explicit positive filling tolerances.",
       "For patches that must share exact boundary edges with neighbors and sew into a closed shell, build them with "
       "make_gordon_surface_rface on a shared edge network instead; filling re-fits boundaries and breaks edge identity."}};
  return operator_scope(kSpec, [&] {
    if (boundaries.empty()) throw ValueError("boundaries must be a non-empty SurfaceBoundary sequence");
    const SurfaceFillingSettings settings = options.settings.value_or(SurfaceFillingSettings{});
    settings.validate();

    OperationRecord record{.op = "make_surface_patch_rface"};
    FillingProblem problem;
    problem.settings = settings;
    std::int64_t support_count = 0;
    Value boundary_dicts = Value::array();
    for (const SurfaceBoundary& boundary : boundaries) {
      record.inputs.push_back({boundary.edge, "boundary"});
      FillingBoundary item{.edge = TopoDS::Edge(boundary.edge.wrapped()), .continuity = boundary.continuity};
      if (boundary.support) {
        record.inputs.push_back({*boundary.support, "support"});
        item.support = TopoDS::Face(boundary.support->wrapped());
        ++support_count;
      }
      problem.boundaries.push_back(std::move(item));
      boundary_dicts.push_back(boundary.as_dict());
    }
    std::vector<TopoDS_Wire> holes;
    for (const Wire& hole : options.holes) {
      record.inputs.push_back({hole, "hole"});
      holes.push_back(TopoDS::Wire(hole.wrapped()));
    }
    problem.points = constraint_points_to_global(options.points);

    const TopoDS_Face face = fill_face(problem, holes);

    record.params = Value::object();
    record.params.set("boundary_count", static_cast<std::int64_t>(boundaries.size()));
    record.params.set("support_count", support_count);
    record.params.set("hole_count", static_cast<std::int64_t>(holes.size()));
    record.params.set("boundaries", std::move(boundary_dicts));
    record.params.set("points", to_value(options.points));
    record.params.set("settings", settings.as_dict());
    record.params.set("tag_prefix", to_value(options.tag_prefix));
    return finalize_surface_output(Face(face), FaceOutput{.record = std::move(record), .tag_prefix = options.tag_prefix});
  });
}

}  // namespace scad
