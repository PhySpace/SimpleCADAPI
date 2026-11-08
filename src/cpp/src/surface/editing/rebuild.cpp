// rebuild_curve_redge / rebuild_surface_rface: refit an edge's curve or a face's surface to a chosen degree and
// pole count (or the fewest poles that meet a tolerance), in the shape's own parametrisation.
#include <algorithm>
#include <cmath>
#include <functional>
#include <string>

#include <BRepTools.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopoDS.hxx>

#include "access.hpp"
#include "finish.hpp"
#include "fit.hpp"
#include "scad/surface/editing.hpp"

namespace scad {

using namespace surface::editing;

namespace {

constexpr int kMaxPoles = 256;

// The next pole count to try when the tolerance is not met yet.
int grow(int poles) {
  return poles + std::max(1, poles / 2);
}

void check_degree(int degree, const char* label) {
  if (degree < 1 || degree > Geom_BSplineCurve::MaxDegree())
    throw ValueError(std::string(label) + " must be between 1 and " + std::to_string(Geom_BSplineCurve::MaxDegree()));
}

void check_pole_count(const std::optional<int>& poles, int degree, const char* label) {
  if (poles && (*poles < degree + 1 || *poles > kMaxPoles))
    throw ValueError(std::string(label) + " must be at least the degree + 1 (" + std::to_string(degree + 1) +
                     ") and at most " + std::to_string(kMaxPoles));
}

Handle(Geom_BSplineCurve)
    fit_curve(const Handle(Geom_Curve) & source, double first, double last, int degree, int poles, double& deviation) {
  const int samples = std::max(8 * poles, 64);
  const std::vector<double> parameters = even_parameters(first, last, samples);
  std::vector<gp_XYZ> values;
  values.reserve(parameters.size());
  for (double t : parameters)
    values.push_back(source->Value(t).XYZ());
  const KnotVector knots = uniform_clamped_knots(first, last, poles, degree);
  const std::vector<gp_XYZ> fitted = fit_poles(parameters, values, knots, degree, poles);
  TColgp_Array1OfPnt pole_array(1, poles);
  for (int i = 0; i < poles; ++i)
    pole_array.SetValue(i + 1, gp_Pnt(fitted[static_cast<std::size_t>(i)]));
  Handle(Geom_BSplineCurve) curve =
      new Geom_BSplineCurve(pole_array, knot_array(knots), multiplicity_array(knots), degree);
  deviation = 0.0;
  for (std::size_t k = 0; k + 1 < parameters.size(); ++k) {
    const double t = 0.5 * (parameters[k] + parameters[k + 1]);
    deviation = std::max(deviation, source->Value(t).Distance(curve->Value(t)));
    deviation = std::max(deviation, source->Value(parameters[k]).Distance(curve->Value(parameters[k])));
  }
  return curve;
}

struct Domain {
  double u1, u2, v1, v2;
};

Handle(Geom_BSplineSurface) fit_surface(const Handle(Geom_Surface) & source, const Domain& d, int u_degree,
                                        int v_degree, int u_poles, int v_poles, double& deviation) {
  const std::vector<double> us = even_parameters(d.u1, d.u2, std::max(4 * u_poles, 24));
  const std::vector<double> vs = even_parameters(d.v1, d.v2, std::max(4 * v_poles, 24));
  const KnotVector u_knots = uniform_clamped_knots(d.u1, d.u2, u_poles, u_degree);
  const KnotVector v_knots = uniform_clamped_knots(d.v1, d.v2, v_poles, v_degree);
  // Separable least squares: each sample row along v, then each resulting pole column along u.
  std::vector<std::vector<gp_XYZ>> rows;  // rows[k][j]: the v-fit of sample row u_k
  rows.reserve(us.size());
  for (double u : us) {
    std::vector<gp_XYZ> values;
    values.reserve(vs.size());
    for (double v : vs)
      values.push_back(source->Value(u, v).XYZ());
    rows.push_back(fit_poles(vs, values, v_knots, v_degree, v_poles));
  }
  TColgp_Array2OfPnt pole_grid(1, u_poles, 1, v_poles);
  for (int j = 0; j < v_poles; ++j) {
    std::vector<gp_XYZ> column;
    column.reserve(us.size());
    for (const auto& row : rows)
      column.push_back(row[static_cast<std::size_t>(j)]);
    const std::vector<gp_XYZ> fitted = fit_poles(us, column, u_knots, u_degree, u_poles);
    for (int i = 0; i < u_poles; ++i)
      pole_grid.SetValue(i + 1, j + 1, gp_Pnt(fitted[static_cast<std::size_t>(i)]));
  }
  Handle(Geom_BSplineSurface) surface =
      new Geom_BSplineSurface(pole_grid, knot_array(u_knots), knot_array(v_knots), multiplicity_array(u_knots),
                              multiplicity_array(v_knots), u_degree, v_degree);
  deviation = 0.0;
  for (std::size_t a = 0; a + 1 < us.size(); ++a)
    for (std::size_t b = 0; b + 1 < vs.size(); ++b) {
      const double u = 0.5 * (us[a] + us[a + 1]), v = 0.5 * (vs[b] + vs[b + 1]);
      deviation = std::max(deviation, source->Value(u, v).Distance(surface->Value(u, v)));
    }
  return surface;
}

}  // namespace

Edge rebuild_curve_redge(const Edge& edge, const RebuildCurveOptions& options) {
  static const ErrorSpec kSpec{
      "rebuild_curve_redge",
      "Failed to rebuild the curve of the edge.",
      {"The degree, pole count or tolerance is invalid.", "The tolerance cannot be met with at most 256 poles."},
      {"Use 1 <= degree <= 25 and pole_count >= degree + 1.", "Raise the tolerance, or give pole_count explicitly."}};
  return edit_scope(kSpec, [&] {
    if (edge.wrapped().IsNull())
      throw ValueError("edge must not be null");
    check_degree(options.degree, "degree");
    check_pole_count(options.pole_count, options.degree, "pole_count");
    if (!options.pole_count && (!std::isfinite(options.tolerance) || options.tolerance <= 0.0))
      throw ValueError("tolerance must be a positive finite value");
    const CurveRep rep = curve_rep(TopoDS::Edge(edge.wrapped()));
    double deviation = 0.0;
    Handle(Geom_BSplineCurve) curve;
    if (options.pole_count) {
      curve = fit_curve(rep.curve, rep.first, rep.last, options.degree, *options.pole_count, deviation);
    } else {
      for (int poles = options.degree + 1;; poles = grow(poles)) {
        curve = fit_curve(rep.curve, rep.first, rep.last, options.degree, std::min(poles, kMaxPoles), deviation);
        if (deviation <= options.tolerance)
          break;
        if (poles >= kMaxPoles)
          throw ValueError("the tolerance cannot be met with " + std::to_string(kMaxPoles) + " poles (deviation " +
                           std::to_string(deviation) + ")");
      }
    }
    Value params = Value::object();
    params.set("degree", options.degree);
    params.set("pole_count", options.pole_count ? Value(*options.pole_count) : Value());
    params.set("tolerance", options.tolerance);
    return finish_edge(edge, "rebuild_curve_redge", std::move(params), options.tag_prefix, curve, rep.location);
  });
}

Face rebuild_surface_rface(const Face& face, const RebuildSurfaceOptions& options) {
  static const ErrorSpec kSpec{"rebuild_surface_rface",
                               "Failed to rebuild the surface of the face.",
                               {"The degrees, pole counts or tolerance are invalid.",
                                "The tolerance cannot be met with at most 256 x 256 poles."},
                               {"Use 1 <= degree <= 25 and pole counts >= degree + 1.",
                                "Give both pole counts, or neither (then the tolerance decides)."}};
  return edit_scope(kSpec, [&] {
    if (face.wrapped().IsNull())
      throw ValueError("face must not be null");
    check_degree(options.u_degree, "u_degree");
    check_degree(options.v_degree, "v_degree");
    check_pole_count(options.u_pole_count, options.u_degree, "u_pole_count");
    check_pole_count(options.v_pole_count, options.v_degree, "v_pole_count");
    if (options.u_pole_count.has_value() != options.v_pole_count.has_value())
      throw ValueError("give both u_pole_count and v_pole_count, or neither");
    if (!options.u_pole_count && (!std::isfinite(options.tolerance) || options.tolerance <= 0.0))
      throw ValueError("tolerance must be a positive finite value");
    const TopoDS_Face f = TopoDS::Face(face.wrapped());
    const SurfaceRep rep = surface_rep(f);
    // A bounded B-spline keeps its whole domain (its natural boundary stays one); anything else is refitted over the
    // face's (u, v) bounds, which hold every trimming loop.
    Domain d{};
    if (const Handle(Geom_BSplineSurface) bspline = bspline_copy(rep.surface))
      bspline->Bounds(d.u1, d.u2, d.v1, d.v2);
    else
      BRepTools::UVBounds(f, d.u1, d.u2, d.v1, d.v2);
    if (!std::isfinite(d.u2 - d.u1) || !std::isfinite(d.v2 - d.v1) || d.u2 <= d.u1 || d.v2 <= d.v1)
      throw ValueError("the face has no finite (u, v) bounds to refit over");
    double deviation = 0.0;
    Handle(Geom_BSplineSurface) surface;
    if (options.u_pole_count) {
      surface = fit_surface(rep.surface, d, options.u_degree, options.v_degree, *options.u_pole_count,
                            *options.v_pole_count, deviation);
    } else {
      int u_poles = options.u_degree + 1, v_poles = options.v_degree + 1;
      for (;;) {
        surface = fit_surface(rep.surface, d, options.u_degree, options.v_degree, u_poles, v_poles, deviation);
        if (deviation <= options.tolerance)
          break;
        if (u_poles >= kMaxPoles && v_poles >= kMaxPoles)
          throw ValueError("the tolerance cannot be met with " + std::to_string(kMaxPoles) + " x " +
                           std::to_string(kMaxPoles) + " poles (deviation " + std::to_string(deviation) + ")");
        u_poles = std::min(grow(u_poles), kMaxPoles);
        v_poles = std::min(grow(v_poles), kMaxPoles);
      }
    }
    Value params = Value::object();
    params.set("u_degree", options.u_degree);
    params.set("v_degree", options.v_degree);
    params.set("u_pole_count", options.u_pole_count ? Value(*options.u_pole_count) : Value());
    params.set("v_pole_count", options.v_pole_count ? Value(*options.v_pole_count) : Value());
    params.set("tolerance", options.tolerance);
    return finish_face(face, "rebuild_surface_rface", std::move(params), options.tag_prefix, surface, rep.location);
  });
}

}  // namespace scad
