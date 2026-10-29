// Helpers shared by the translation units of the surface area.  Not installed.
#pragma once

#include <cmath>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <Geom_Surface.hxx>
#include <Precision.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Wire.hxx>

#include "scad/core/error.hpp"
#include "scad/core/value.hpp"
#include "scad/surface/fitter.hpp"
#include "scad/surface/types.hpp"

namespace scad::surface::detail {

// An operator body, run so that every failure -- ours or OpenCASCADE's -- leaves as the
// operator's scad::Error (the `_wrap_public_api_error` of the Python operators).
template <class F>
decltype(auto) operator_scope(const ErrorSpec& spec, F&& body) {
  return guarded(spec, [&]() -> decltype(auto) { return occt_guard(body); });
}

// "<label> must be a positive finite value" (ValueError).
double require_positive_finite(double value, std::string_view label);

// ---- grids ---------------------------------------------------------------------------
// _surface_point_grid: at least 2 x 2, rectangular, finite.
PointGrid checked_point_grid(const PointGrid& points);
// _surface_global_point_grid / _surface_global_points: through the current coordinate system.
PointGrid to_global(const PointGrid& points);
std::vector<Vec3> constraint_points_to_global(const std::vector<Vec3>& points);
Value to_value(const PointGrid& grid);
Value to_value(const std::vector<Vec3>& points);
Value to_value(const std::optional<WeightGrid>& weights);

// A Scalar argument that was symbolic goes to the recorder under its parameter name
// ("radius", "u_range[0]"); plain numbers are only in the recorded params.
using SymbolicArgs = std::vector<std::pair<std::string, Scalar>>;
void note_symbolic(SymbolicArgs& out, std::string name, const Scalar& value);

// The tag_prefix parameter as the recorder stores it: the string or null.
Value to_value(const TagPrefix& tag_prefix);

// BRepBuilderAPI_MakeFace(surface, Precision::Confusion()); ValueError when OpenCASCADE refuses.
TopoDS_Face face_from_surface(const Handle(Geom_Surface) & surface);

// The face the fitter fills over `problem`, trimmed by `holes` when there are any.
TopoDS_Face fill_face(const FillingProblem& problem, const std::vector<TopoDS_Wire>& holes);

// ---- sewing and shells ---------------------------------------------------------------------
struct SewnShell {
  TopoDS_Shell shell;
  std::vector<int> result_face_indices;  // input face i is result face result_face_indices[i]
};
// BRepBuilderAPI_Sewing at exactly `tolerance`; the result is one connected shell holding every
// input face once (ValueError otherwise).
SewnShell sew_faces_with_history(const std::vector<TopoDS_Face>& faces, double tolerance);
TopoDS_Shell sew_faces(const std::vector<TopoDS_Face>& faces, double tolerance);
TopoDS_Shell shell_from_face(const TopoDS_Face& face);
// The unique closed and then open free-boundary wires of `shell` at `tolerance`.
std::vector<TopoDS_Wire> free_boundaries(const TopoDS_Shape& shell, double tolerance);

// The single face of a shape that is a face or holds exactly one.
TopoDS_Face single_face(const TopoDS_Shape& shape, std::string_view what);

}  // namespace scad::surface::detail
