#include "edit_curves.hpp"

#include <algorithm>
#include <cmath>

#include <Geom2dAPI_InterCurveCurve.hxx>
#include <Geom2dAPI_ProjectPointOnCurve.hxx>
#include <Geom2dAdaptor_Curve.hxx>
#include <Geom2dConvert_CompCurveToBSplineCurve.hxx>
#include <Geom2dInt_GInter.hxx>
#include <GeomLib.hxx>
#include <Geom_BSplineCurve.hxx>
#include <IntRes2d_IntersectionPoint.hxx>
#include <IntRes2d_IntersectionSegment.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array1OfPnt2d.hxx>

#include "scad/core/error.hpp"

namespace scad::sketch_detail {

namespace {

TColStd_Array1OfReal reals(const std::vector<double>& values) {
  TColStd_Array1OfReal out(1, static_cast<int>(values.size()));
  for (std::size_t i = 0; i < values.size(); ++i)
    out.SetValue(static_cast<int>(i) + 1, values[i]);
  return out;
}

TColStd_Array1OfInteger integers(const std::vector<int>& values) {
  TColStd_Array1OfInteger out(1, static_cast<int>(values.size()));
  for (std::size_t i = 0; i < values.size(); ++i)
    out.SetValue(static_cast<int>(i) + 1, values[i]);
  return out;
}

std::vector<double> reals_of(const TColStd_Array1OfReal& values) {
  std::vector<double> out;
  for (int i = values.Lower(); i <= values.Upper(); ++i)
    out.push_back(values(i));
  return out;
}

Crossing2 crossing_of(const IntRes2d_IntersectionPoint& point) {
  return {{point.Value().X(), point.Value().Y()}, point.ParamOnFirst(), point.ParamOnSecond()};
}

}  // namespace

opencascade::handle<Geom2d_BSplineCurve> make_spline2(const Spline2& spline) {
  return occt_guard([&] {
    TColgp_Array1OfPnt2d poles(1, static_cast<int>(spline.poles.size()));
    for (std::size_t i = 0; i < spline.poles.size(); ++i)
      poles.SetValue(static_cast<int>(i) + 1, gp_Pnt2d(spline.poles[i].first, spline.poles[i].second));
    const TColStd_Array1OfReal knots = reals(spline.knots);
    const TColStd_Array1OfInteger mults = integers(spline.multiplicities);
    if (spline.weights.empty())
      return opencascade::handle<Geom2d_BSplineCurve>(
          new Geom2d_BSplineCurve(poles, knots, mults, spline.degree, spline.periodic));
    return opencascade::handle<Geom2d_BSplineCurve>(
        new Geom2d_BSplineCurve(poles, reals(spline.weights), knots, mults, spline.degree, spline.periodic));
  });
}

Spline2 spline2_of(const opencascade::handle<Geom2d_BSplineCurve>& curve) {
  Spline2 out;
  out.degree = curve->Degree();
  out.periodic = curve->IsPeriodic();
  for (int i = 1; i <= curve->NbPoles(); ++i)
    out.poles.emplace_back(curve->Pole(i).X(), curve->Pole(i).Y());
  out.knots = reals_of(curve->Knots());
  const double first = out.knots.front();
  const double span = out.knots.back() - first;
  for (double& knot : out.knots)
    knot = (knot - first) / span;
  out.knots.front() = 0.0;
  out.knots.back() = 1.0;
  for (int i = 1; i <= curve->NbKnots(); ++i)
    out.multiplicities.push_back(curve->Multiplicity(i));
  if (curve->IsRational()) {
    TColStd_Array1OfReal weights(1, curve->NbPoles());
    curve->Weights(weights);
    out.weights = reals_of(weights);
    if (std::all_of(out.weights.begin(), out.weights.end(), [](double w) { return std::abs(w - 1.0) <= 1e-12; }))
      out.weights.clear();
  }
  return out;
}

std::vector<Crossing2> intersect2(const opencascade::handle<Geom2d_Curve>& a,
                                  const opencascade::handle<Geom2d_Curve>& b, double tolerance) {
  return occt_guard([&] {
    std::vector<Crossing2> out;
    const Geom2dAPI_InterCurveCurve inter(a, b, tolerance);
    const Geom2dInt_GInter& found = inter.Intersector();
    if (!found.IsDone())
      return out;
    for (int i = 1; i <= found.NbPoints(); ++i)
      out.push_back(crossing_of(found.Point(i)));
    for (int i = 1; i <= found.NbSegments(); ++i) {
      const IntRes2d_IntersectionSegment& segment = found.Segment(i);
      if (segment.HasFirstPoint())
        out.push_back(crossing_of(segment.FirstPoint()));
      if (segment.HasLastPoint())
        out.push_back(crossing_of(segment.LastPoint()));
    }
    return out;
  });
}

double nearest_parameter(const opencascade::handle<Geom2d_Curve>& curve, const Pt2& p) {
  return occt_guard([&] {
    const gp_Pnt2d point(p.first, p.second);
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    double best = first;
    double best_distance = curve->Value(first).Distance(point);
    if (const double d = curve->Value(last).Distance(point); d < best_distance) {
      best = last;
      best_distance = d;
    }
    Geom2dAPI_ProjectPointOnCurve projection(point, curve, first, last);
    if (projection.NbPoints() > 0 && projection.LowerDistance() < best_distance)
      best = projection.LowerDistanceParameter();
    return best;
  });
}

double parameter_resolution(const opencascade::handle<Geom2d_Curve>& curve, double distance) {
  return occt_guard([&] { return Geom2dAdaptor_Curve(curve).Resolution(distance); });
}

Pt2 value_at(const opencascade::handle<Geom2d_Curve>& curve, double u) {
  const gp_Pnt2d p = curve->Value(u);
  return {p.X(), p.Y()};
}

opencascade::handle<Geom2d_BSplineCurve> segment2(const opencascade::handle<Geom2d_BSplineCurve>& spline, double u1,
                                                  double u2) {
  return occt_guard([&] {
    opencascade::handle<Geom2d_BSplineCurve> copy = opencascade::handle<Geom2d_BSplineCurve>::DownCast(spline->Copy());
    copy->Segment(u1, u2);
    if (copy->IsPeriodic())
      copy->SetNotPeriodic();
    return copy;
  });
}

opencascade::handle<Geom2d_BSplineCurve> join2(const opencascade::handle<Geom2d_BSplineCurve>& first,
                                               const opencascade::handle<Geom2d_BSplineCurve>& second) {
  return occt_guard([&] {
    Geom2dConvert_CompCurveToBSplineCurve joined(first);
    if (!joined.Add(second, 1e-6, /*After=*/true))
      throw ValueError("the two parts of the B-spline do not meet at its seam");
    return joined.BSplineCurve();
  });
}

opencascade::handle<Geom2d_BSplineCurve> extend2(const opencascade::handle<Geom2d_BSplineCurve>& spline, bool at_end,
                                                 const Pt2& target) {
  return occt_guard([&] {
    TColgp_Array1OfPnt poles(1, spline->NbPoles());
    for (int i = 1; i <= spline->NbPoles(); ++i)
      poles.SetValue(i, gp_Pnt(spline->Pole(i).X(), spline->Pole(i).Y(), 0.0));
    opencascade::handle<Geom_BSplineCurve> lifted;
    TColStd_Array1OfReal weights(1, spline->NbPoles());
    spline->Weights(weights);
    if (spline->IsRational())
      lifted = new Geom_BSplineCurve(poles, weights, spline->Knots(), spline->Multiplicities(), spline->Degree(),
                                     spline->IsPeriodic());
    else
      lifted = new Geom_BSplineCurve(poles, spline->Knots(), spline->Multiplicities(), spline->Degree(),
                                     spline->IsPeriodic());
    opencascade::handle<Geom_BoundedCurve> curve = lifted;
    GeomLib::ExtendCurveToPoint(curve, gp_Pnt(target.first, target.second, 0.0), /*Cont=*/2, at_end);
    const opencascade::handle<Geom_BSplineCurve> extended = opencascade::handle<Geom_BSplineCurve>::DownCast(curve);
    if (extended.IsNull())
      throw ValueError("the B-spline could not be extended");
    TColgp_Array1OfPnt2d flat(1, extended->NbPoles());
    for (int i = 1; i <= extended->NbPoles(); ++i)
      flat.SetValue(i, gp_Pnt2d(extended->Pole(i).X(), extended->Pole(i).Y()));
    if (extended->IsRational()) {
      TColStd_Array1OfReal extended_weights(1, extended->NbPoles());
      extended->Weights(extended_weights);
      return opencascade::handle<Geom2d_BSplineCurve>(new Geom2d_BSplineCurve(
          flat, extended_weights, extended->Knots(), extended->Multiplicities(), extended->Degree(), false));
    }
    return opencascade::handle<Geom2d_BSplineCurve>(
        new Geom2d_BSplineCurve(flat, extended->Knots(), extended->Multiplicities(), extended->Degree(), false));
  });
}

}  // namespace scad::sketch_detail
