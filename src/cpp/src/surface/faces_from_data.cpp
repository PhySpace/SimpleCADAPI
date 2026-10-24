// make_bezier_surface_rface, make_cylindrical_surface_rface, fit_point_grid_rface:
// faces built from numbers.
#include <algorithm>
#include <cmath>

#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>

#include "finalize.hpp"
#include "internal.hpp"
#include "scad/core/coordinate_system.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/surface/fitter.hpp"
#include "scad/surface/hooks.hpp"
#include "scad/surface/operators.hpp"

namespace scad {

using namespace surface::detail;

// ---------------------------------------------------------------------------------------------
// make_bezier_surface_rface
// ---------------------------------------------------------------------------------------------
namespace {

TopoDS_Face bezier_face(const PointGrid& points, const std::optional<WeightGrid>& weights) {
  const int rows = static_cast<int>(points.size());
  const int columns = static_cast<int>(points.front().size());
  TColgp_Array2OfPnt poles(1, rows, 1, columns);
  for (int r = 0; r < rows; ++r)
    for (int c = 0; c < columns; ++c)
      poles.SetValue(r + 1, c + 1, kernel::to_pnt(points[static_cast<std::size_t>(r)][static_cast<std::size_t>(c)]));
  if (!weights) return face_from_surface(new Geom_BezierSurface(poles));

  TColStd_Array2OfReal grid(1, rows, 1, columns);
  for (int r = 0; r < rows; ++r)
    for (int c = 0; c < columns; ++c)
      grid.SetValue(r + 1, c + 1, (*weights)[static_cast<std::size_t>(r)][static_cast<std::size_t>(c)]);
  return face_from_surface(new Geom_BezierSurface(poles, grid));
}

void check_bezier_weights(const WeightGrid& weights, const PointGrid& points) {
  if (weights.size() != points.size() ||
      std::any_of(weights.begin(), weights.end(), [&](const auto& row) { return row.size() != points.front().size(); }))
    throw ValueError("Bezier weights must match the control-point grid");
  for (const auto& row : weights)
    for (double weight : row)
      if (weight <= 0 || !std::isfinite(weight)) throw ValueError("Bezier weights must be positive finite values");
}

}  // namespace

Face make_bezier_surface_rface(const PointGrid& control_points, const std::optional<WeightGrid>& weights,
                               const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec{"make_bezier_surface_rface",
                               "Failed to create the Bezier surface face.",
                               {"The control-point grid is invalid or degenerate.", "The kernel rejected the Bezier surface."},
                               {"Pass a rectangular finite grid with at least two rows and columns.",
                                "Use positive finite weights with the same dimensions as the grid."}};
  return operator_scope(kSpec, [&] {
    const PointGrid local = checked_point_grid(control_points);
    const PointGrid global = to_global(local);
    if (weights) check_bezier_weights(*weights, local);

    Value params = Value::object();
    params.set("control_points", to_value(local));
    params.set("weights", to_value(weights));
    params.set("tag_prefix", to_value(tag_prefix));
    return finalize_surface_output(Face(bezier_face(global, weights)),
                                   FaceOutput{.record = {.op = "make_bezier_surface_rface", .params = std::move(params)},
                                    .tag_prefix = tag_prefix});
  });
}

// ---------------------------------------------------------------------------------------------
// make_cylindrical_surface_rface
// ---------------------------------------------------------------------------------------------
namespace {

void require_dimension(const Scalar& value, UnitDimension expected, const char* message) {
  const ScalarUnits units = scalar_units(value);
  if (units.uses_units && units.dimension != expected) throw ValueError(message);
}

Vec3 evaluated(const ScalarVec3& v) { return {v[0].value(), v[1].value(), v[2].value()}; }

Value vec_value(const Vec3& v) { return Value(Value::Array{v.x, v.y, v.z}); }

// OCP's canonical in-plane X axis for a local normal.
Vec3 default_plane_x_direction(const Vec3& normal) {
  const gp_Ax2 frame(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(normal.x, normal.y, normal.z));
  return kernel::from_dir(frame.XDirection());
}

TopoDS_Face cylindrical_face(double radius, const std::pair<double, double>& u, const std::pair<double, double>& v,
                             const Vec3& origin, const Vec3& axis, const Vec3& x_direction, double tolerance) {
  const Handle(Geom_CylindricalSurface) surface = new Geom_CylindricalSurface(
      gp_Ax3(kernel::to_pnt(origin), gp_Dir(axis.x, axis.y, axis.z), gp_Dir(x_direction.x, x_direction.y, x_direction.z)),
      radius);
  BRepBuilderAPI_MakeFace builder(surface, u.first, u.second, v.first, v.second, tolerance);
  if (!builder.IsDone() || builder.Face().IsNull())
    throw ValueError("OCP could not create the bounded cylindrical surface face");
  const TopoDS_Face face = builder.Face();
  if (!BRepCheck_Analyzer(face).IsValid()) throw ValueError("bounded cylindrical surface face is invalid");
  return face;
}

}  // namespace

Face make_cylindrical_surface_rface(const Scalar& radius, const ScalarRange& u_range, const ScalarRange& v_range,
                                    const CylindricalSurfaceOptions& options) {
  static const ErrorSpec kSpec{"make_cylindrical_surface_rface",
                               "Failed to create the cylindrical surface face.",
                               {"The radius, U/V ranges, or tolerance is invalid.", "The axis frame is degenerate or parallel.",
                                "The kernel rejected the bounded cylindrical surface."},
                               {"Use model length units for radius, V, and tolerance.",
                                "Pass increasing finite U bounds as unitless raw radians.",
                                "Keep the U span at or below one revolution and provide non-parallel axis directions."}};
  return operator_scope(kSpec, [&] {
    require_dimension(radius, UnitDimension::Length, "radius must use model length units");
    for (const Scalar* value : {&u_range.first, &u_range.second})
      require_dimension(*value, UnitDimension::Dimensionless,
                        "u_range must use unitless raw radians; unit-aware angle values evaluate in degrees");
    for (const Scalar* value : {&v_range.first, &v_range.second})
      require_dimension(*value, UnitDimension::Length, "v_range must use model length units");
    require_dimension(options.tolerance, UnitDimension::Length, "tolerance must use model length units");

    const double radius_value = radius.value();
    const std::pair<double, double> u{u_range.first.value(), u_range.second.value()};
    const std::pair<double, double> v{v_range.first.value(), v_range.second.value()};
    const double tolerance_value = options.tolerance.value();
    if (!std::isfinite(radius_value) || radius_value <= 0.0) throw ValueError("radius must be a positive finite value");
    if (!std::isfinite(u.first) || !std::isfinite(u.second)) throw ValueError("u_range must contain two finite values");
    if (!std::isfinite(v.first) || !std::isfinite(v.second)) throw ValueError("v_range must contain two finite values");
    const double u_span = u.second - u.first;
    const double v_span = v.second - v.first;
    if (u_span <= Precision::PConfusion() || u_span > 2.0 * kPi + Precision::Angular())
      throw ValueError("u_range must be increasing and span at most one revolution");
    if (v_span <= Precision::Confusion()) throw ValueError("v_range must be increasing beyond kernel confusion");
    if (!std::isfinite(tolerance_value) || tolerance_value <= 0.0)
      throw ValueError("tolerance must be a positive finite value");

    const Vec3 origin = evaluated(options.origin);
    const Vec3 axis = evaluated(options.axis);
    // A non-finite axis has no default X; the finite check below reports it.
    const Vec3 x_direction = options.x_direction ? evaluated(*options.x_direction)
                             : axis.is_finite()  ? default_plane_x_direction(axis)
                                                 : axis;
    if (!origin.is_finite() || !axis.is_finite() || !x_direction.is_finite())
      throw ValueError("origin, axis, and x_direction must be finite 3D values");
    const double axis_norm = axis.norm();
    const double x_norm = x_direction.norm();
    if (axis_norm <= 1e-12 || x_norm <= 1e-12) throw ValueError("axis and x_direction must be non-zero");
    if (std::abs(axis.dot(x_direction)) / (axis_norm * x_norm) >= 1.0 - 1e-12)
      throw ValueError("axis and x_direction must not be parallel");

    const CoordinateSystem& cs = current_cs();
    const TopoDS_Face face = cylindrical_face(radius_value, u, v, cs.transform_point(origin), cs.transform_vector(axis),
                                              cs.transform_vector(x_direction), tolerance_value);

    Value params = Value::object();
    params.set("radius", radius_value);
    params.set("u_range", Value(Value::Array{u.first, u.second}));
    params.set("v_range", Value(Value::Array{v.first, v.second}));
    params.set("origin", vec_value(origin));
    params.set("axis", vec_value(axis));
    params.set("x_direction", options.x_direction ? vec_value(x_direction) : Value());
    params.set("tolerance", tolerance_value);
    params.set("tag_prefix", to_value(options.tag_prefix));
    SymbolicArgs symbolic;
    note_symbolic(symbolic, "radius", radius);
    note_symbolic(symbolic, "u_range[0]", u_range.first);
    note_symbolic(symbolic, "u_range[1]", u_range.second);
    note_symbolic(symbolic, "v_range[0]", v_range.first);
    note_symbolic(symbolic, "v_range[1]", v_range.second);
    for (std::size_t i = 0; i < 3; ++i) {
      const std::string index = "[" + std::to_string(i) + "]";
      note_symbolic(symbolic, "origin" + index, options.origin[i]);
      note_symbolic(symbolic, "axis" + index, options.axis[i]);
      if (options.x_direction) note_symbolic(symbolic, "x_direction" + index, (*options.x_direction)[i]);
    }
    note_symbolic(symbolic, "tolerance", options.tolerance);
    return finalize_surface_output(Face(face), FaceOutput{.record = {.op = "make_cylindrical_surface_rface",
                                                                    .params = std::move(params),
                                                                    .symbolic = std::move(symbolic)},
                                                          .tag_prefix = options.tag_prefix});
  });
}

// ---------------------------------------------------------------------------------------------
// fit_point_grid_rface
// ---------------------------------------------------------------------------------------------
Face fit_point_grid_rface(const PointGrid& points, const FitPointGridOptions& options) {
  static const ErrorSpec kSpec{"fit_point_grid_rface",
                               "Failed to fit a B-spline surface face.",
                               {"The point grid or fitting controls are invalid.", "The kernel fitting algorithm did not converge."},
                               {"Pass a rectangular finite point grid and positive tolerance.",
                                "Keep degree_min <= degree_max and use non-negative smoothing weights."}};
  return operator_scope(kSpec, [&] {
    const double tolerance = require_positive_finite(options.tolerance, "tolerance");
    if (options.degree_min < 1 || options.degree_max < options.degree_min)
      throw ValueError("degree_max must be greater than or equal to degree_min");
    if (options.smoothing)
      for (double weight : *options.smoothing)
        if (!std::isfinite(weight) || weight < 0)
          throw ValueError("smoothing must contain three finite non-negative weights");
    const PointGrid local = checked_point_grid(points);
    const PointGrid global = to_global(local);

    const Handle(Geom_BSplineSurface) fitted = surface::surface_fitter()->fit_point_grid(
        global, {.tolerance = tolerance,
                 .degree_min = options.degree_min,
                 .degree_max = options.degree_max,
                 .smoothing = options.smoothing});

    Value params = Value::object();
    params.set("points", to_value(local));
    params.set("tolerance", tolerance);
    params.set("degree_min", options.degree_min);
    params.set("degree_max", options.degree_max);
    Value smoothing;
    if (options.smoothing)
      smoothing = Value(Value::Array{(*options.smoothing)[0], (*options.smoothing)[1], (*options.smoothing)[2]});
    params.set("smoothing", std::move(smoothing));
    params.set("tag_prefix", to_value(options.tag_prefix));
    return finalize_surface_output(Face(face_from_surface(fitted)),
                                   FaceOutput{.record = {.op = "fit_point_grid_rface", .params = std::move(params)},
                                    .tag_prefix = options.tag_prefix});
  });
}

}  // namespace scad
