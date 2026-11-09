// Plane-curve helpers for the sketch edits (trim / extend / crossings) on curves that have no closed-form
// intersection: B-splines and ellipses.  OCCT 2D curves in, plain numbers out.  Internal to the sketch library.
#pragma once

#include <utility>
#include <vector>

#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_Curve.hxx>

namespace scad::sketch_detail {

using Pt2 = std::pair<double, double>;

// A planar (rational) B-spline as numbers: what a sketch `bspline` entity stores, with its solved poles.
struct Spline2 {
  int degree = 3;
  std::vector<Pt2> poles;
  std::vector<double> knots;  // distinct values
  std::vector<int> multiplicities;
  std::vector<double> weights;  // empty: non-rational
  bool periodic = false;
};

opencascade::handle<Geom2d_BSplineCurve> make_spline2(const Spline2& spline);
// The numbers of an OCCT spline; the knots are rescaled to [0, 1] (the geometry does not change) and unit weights
// are dropped.
Spline2 spline2_of(const opencascade::handle<Geom2d_BSplineCurve>& curve);

// A place where two curves meet: the point and its parameter on each curve.  A tangent touch is one crossing; an
// overlap gives its two ends.
struct Crossing2 {
  Pt2 at;
  double on_a = 0.0;
  double on_b = 0.0;
};
std::vector<Crossing2> intersect2(const opencascade::handle<Geom2d_Curve>& a,
                                  const opencascade::handle<Geom2d_Curve>& b, double tolerance);

// The parameter of the point of `curve` nearest `p` (the ends count).
double nearest_parameter(const opencascade::handle<Geom2d_Curve>& curve, const Pt2& p);
// The parameter step that moves about `distance` along `curve`.
double parameter_resolution(const opencascade::handle<Geom2d_Curve>& curve, double distance);
Pt2 value_at(const opencascade::handle<Geom2d_Curve>& curve, double u);

// The part of `spline` between u1 < u2.  A periodic spline may be cut across its seam (u2 beyond the last
// parameter, u2 - u1 at most a period).
opencascade::handle<Geom2d_BSplineCurve> segment2(const opencascade::handle<Geom2d_BSplineCurve>& spline, double u1,
                                                  double u2);
// `first` followed by `second` (the end of the first is the start of the second).
opencascade::handle<Geom2d_BSplineCurve> join2(const opencascade::handle<Geom2d_BSplineCurve>& first,
                                               const opencascade::handle<Geom2d_BSplineCurve>& second);
// `spline` extended curvature-continuously from its end (`at_end`) or start to `target` (GeomLib, at z = 0).
opencascade::handle<Geom2d_BSplineCurve> extend2(const opencascade::handle<Geom2d_BSplineCurve>& spline, bool at_end,
                                                 const Pt2& target);

}  // namespace scad::sketch_detail
