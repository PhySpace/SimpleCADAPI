// make_solid_from_shell_rsolid, free_boundaries_rwirelist, fill_holes_rshell.
#include <cmath>

#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepLib.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS.hxx>

#include "finalize.hpp"
#include "internal.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/surface/fitter.hpp"
#include "scad/surface/operators.hpp"

namespace scad {

using namespace surface;
using namespace surface::detail;

namespace {

TopoDS_Solid solid_from_shell(const TopoDS_Shell& shell) {
  if (!BRep_Tool::IsClosed(shell))
    throw ValueError("solid-from-shell requires a closed shell");
  if (!BRepCheck_Analyzer(shell).IsValid())
    throw ValueError("solid-from-shell requires a valid shell");
  BRepBuilderAPI_MakeSolid maker(shell);
  if (!maker.IsDone())
    throw ValueError("OCP solid-from-shell builder failed");
  TopoDS_Solid solid = maker.Solid();
  if (solid.IsNull() || !BRepLib::OrientClosedSolid(solid))
    throw ValueError("OCP could not orient the closed solid");
  if (!BRepCheck_Analyzer(solid).IsValid())
    throw ValueError("solid created from shell is invalid");
  GProp_GProps properties;
  BRepGProp::VolumeProperties(solid, properties);
  const double volume = properties.Mass();
  if (!std::isfinite(volume) || volume <= 0.0)
    throw ValueError("solid created from shell must have positive finite volume");
  return solid;
}

TopoDS_Shell fill_shell_holes(const TopoDS_Shell& shell, const std::optional<std::vector<int>>& hole_indices,
                              double tolerance, const SurfaceFillingSettings& settings) {
  const std::vector<TopoDS_Wire> boundaries = free_boundaries(shell, tolerance);
  std::vector<int> selected;
  if (hole_indices) {
    selected = *hole_indices;
  } else {
    for (std::size_t i = 0; i < boundaries.size(); ++i)
      selected.push_back(static_cast<int>(i));
  }
  std::vector<TopoDS_Face> faces = kernel::faces_of(shell);
  for (const int requested : selected) {
    const int count = static_cast<int>(boundaries.size());
    const int index = requested < 0 ? requested + count : requested;  // Python list indexing
    if (index < 0 || index >= count)
      throw IndexError("list index out of range");
    const TopoDS_Wire& wire = boundaries[static_cast<std::size_t>(index)];
    if (!BRep_Tool::IsClosed(wire))
      throw ValueError("free boundary " + std::to_string(requested) + " is open and cannot be filled as a hole");
    FillingProblem problem;
    problem.settings = settings;
    for (const TopoDS_Edge& edge : kernel::edges_of(wire))
      problem.boundaries.push_back({.edge = edge});
    faces.push_back(fill_face(problem, {}));
  }
  return sew_faces(faces, tolerance);
}

}  // namespace

Solid make_solid_from_shell_rsolid(const Shell& shell, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec{
      "make_solid_from_shell_rsolid",
      "Failed to create a solid from the shell.",
      {"The input is not a Shell.", "The shell is open, invalid, or cannot be oriented as one material boundary."},
      {"Sew a valid closed shell before converting it to a solid.",
       "Inspect free boundaries and face orientation when conversion fails."}};
  return operator_scope(kSpec, [&] {
    const TopoDS_Solid solid = solid_from_shell(TopoDS::Shell(shell.wrapped()));
    Value params = Value::object();
    params.set("tag_prefix", to_value(tag_prefix));
    return finalize_surface_output(Solid(solid), SolidifiedOutput{.record = {.op = "make_solid_from_shell_rsolid",
                                                                             .params = std::move(params),
                                                                             .inputs = {{shell, "shell"}}},
                                                                  .tag_prefix = tag_prefix,
                                                                  .source = shell});
  });
}

std::vector<Wire> free_boundaries_rwirelist(const Shell& shell, double tolerance) {
  static const ErrorSpec kSpec{"free_boundaries_rwirelist",
                               "Failed to extract free boundary wires.",
                               {"The input is not a valid Shell.", "The boundary analysis tolerance is invalid."},
                               {"Pass a Shell and a positive finite tolerance."}};
  return operator_scope(kSpec, [&] {
    require_positive_finite(tolerance, "tolerance");
    std::vector<Wire> wires;
    for (const TopoDS_Wire& wire : free_boundaries(shell.wrapped(), tolerance))
      wires.emplace_back(wire);
    Value params = Value::object();
    params.set("tolerance", tolerance);
    return finalize_surface_output(std::move(wires), BoundariesOutput{.record = {.op = "free_boundaries_rwirelist",
                                                                                 .params = std::move(params),
                                                                                 .inputs = {{shell, "shell"}}},
                                                                      .source = shell});
  });
}

Shell fill_holes_rshell(const Shell& shell, const FillHolesOptions& options) {
  static const ErrorSpec kSpec{"fill_holes_rshell",
                               "Failed to fill selected shell holes.",
                               {"A selected boundary is not a closed hole or the index is out of range.",
                                "The filling or sewing operation failed."},
                               {"Use free_boundaries_rwirelist() to inspect valid boundary indices before filling."}};
  return operator_scope(kSpec, [&] {
    require_positive_finite(options.tolerance, "tolerance");
    const SurfaceFillingSettings settings = options.settings.value_or(SurfaceFillingSettings{});
    settings.validate();
    const TopoDS_Shell sewn =
        fill_shell_holes(TopoDS::Shell(shell.wrapped()), options.hole_indices, options.tolerance, settings);

    Value params = Value::object();
    Value indices;
    if (options.hole_indices) {
      indices = Value::array();
      for (int index : *options.hole_indices)
        indices.push_back(index);
    }
    params.set("hole_indices", std::move(indices));
    params.set("tolerance", options.tolerance);
    params.set("settings", settings.as_dict());
    params.set("tag_prefix", to_value(options.tag_prefix));
    return finalize_surface_output(
        Shell(sewn),
        FilledOutput{.record = {.op = "fill_holes_rshell", .params = std::move(params), .inputs = {{shell, "shell"}}},
                     .tag_prefix = options.tag_prefix});
  });
}

}  // namespace scad
