#include "gordon.hpp"

#include <algorithm>
#include <cmath>

#include <BRepAdaptor_Curve.hxx>
#include <BRep_Tool.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomConvert.hxx>
#include <GeomConvert_ApproxCurve.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Conic.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <Precision.hxx>
#include <TopLoc_Location.hxx>

#include "scad/core/error.hpp"

#ifdef SCAD_WITH_GORDON
#include <occ_gordon/occ_gordon.h>
#endif

namespace scad::surface::detail {

Handle(Geom_Curve) network_curve_of(const TopoDS_Edge& edge) {
  const BRepAdaptor_Curve adaptor(edge);
  double first = 0.0, last = 0.0;
  Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
  if (curve.IsNull())
    throw ValueError("Gordon network edges must carry a 3D curve");

  const GeomAbs_CurveType type = adaptor.GetType();
  const bool freeform = type == GeomAbs_BSplineCurve || type == GeomAbs_BezierCurve;
  if (adaptor.IsPeriodic() && adaptor.IsClosed())
    return curve;
  const bool whole = std::abs(adaptor.FirstParameter() - curve->FirstParameter()) <= Precision::PConfusion() &&
                     std::abs(adaptor.LastParameter() - curve->LastParameter()) <= Precision::PConfusion();
  if (freeform && whole)
    return curve;
  return new Geom_TrimmedCurve(curve, adaptor.FirstParameter(), adaptor.LastParameter());
}

#ifdef SCAD_WITH_GORDON
namespace {

bool is_conic(const Handle(Geom_Curve) & curve) {
  if (curve->IsKind(STANDARD_TYPE(Geom_Conic)))
    return true;
  if (const Handle(Geom_TrimmedCurve) trimmed = Handle(Geom_TrimmedCurve)::DownCast(curve))
    return trimmed->BasisCurve()->IsKind(STANDARD_TYPE(Geom_Conic));
  return false;
}

// BSplineAlgorithms.to_bsplines of ocp_gordon: B-splines are copied; circles and ellipses are
// approximated by a C2 non-rational spline (an exact rational one would defeat the exactness
// guard of the network reparametrization); everything else converts exactly.
Handle(Geom_BSplineCurve) as_bspline(const Handle(Geom_Curve) & curve) {
  if (const Handle(Geom_BSplineCurve) spline = Handle(Geom_BSplineCurve)::DownCast(curve))
    return Handle(Geom_BSplineCurve)::DownCast(spline->Copy());

  if (is_conic(curve)) {
    const gp_Pnt start = curve->Value(curve->FirstParameter());
    double size = 0.0;
    for (int i = 1; i < 3; ++i) {
      const double u = (1.0 - i / 4.0) * curve->FirstParameter() + (i / 4.0) * curve->LastParameter();
      size = std::max(size, start.Distance(curve->Value(u)));
    }
    const double tolerance = Precision::Approximation() * size / 200.0;
    const GeomConvert_ApproxCurve approximation(curve, tolerance, GeomAbs_C2, 64, 5);
    if (approximation.HasResult() && approximation.MaxError() < tolerance)
      return approximation.Curve();
  }
  return GeomConvert::CurveToBSplineCurve(curve);
}

std::vector<Handle(Geom_BSplineCurve)> as_bsplines(const std::vector<Handle(Geom_Curve)>& curves) {
  std::vector<Handle(Geom_BSplineCurve)> out;
  out.reserve(curves.size());
  for (const auto& curve : curves)
    out.push_back(as_bspline(curve));
  return out;
}

}  // namespace

Handle(Geom_BSplineSurface) interpolate_curve_network(const std::vector<Handle(Geom_Curve)>& profiles,
                                                      const std::vector<Handle(Geom_Curve)>& guides, double tolerance) {
  return occ_gordon::interpolate_curve_network(as_bsplines(profiles), as_bsplines(guides), tolerance);
}
#else
Handle(Geom_BSplineSurface)
    interpolate_curve_network(const std::vector<Handle(Geom_Curve)>&, const std::vector<Handle(Geom_Curve)>&, double) {
  throw NotImplementedError(
      "this build of simplecadapi._cpp was configured with SCAD_WITH_GORDON=OFF and cannot interpolate curve networks");
}
#endif

}  // namespace scad::surface::detail
