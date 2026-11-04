// Point, line and dimension constraints.  Each equation is the SolveSpace form
// py-slvs lowers to (docs/sketch-solver.md has the table).
#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>
#include <vector>
#include <set>
#include <string>

#include "model.hpp"
#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"

namespace scad::sketch_solver {

namespace {

const std::set<std::string>& basic_kinds() {
  static const std::set<std::string> kinds{
      "coincident",    "horizontal", "vertical",     "points_horizontal", "points_vertical", "parallel",
      "perpendicular", "collinear",  "equal_length", "equal_radius",      "distance",        "distance_x",
      "distance_y",    "length",     "major_radius", "minor_radius",      "radius",          "diameter",
      "point_on",      "angle",      "concentric",   "midpoint"};
  return kinds;
}

// Python's `value % 360.0` (result in [0, 360)).
double positive_mod(double value, double modulus) {
  return value - modulus * std::floor(value / modulus);
}

// The point of a (rational) B-spline at `u` by de Boor on the knot span `span` of the flat knot vector `flat`
// (outside that span the same polynomial piece continues).  Works on doubles and on Duals.
template <class Number, class PolePoint>
std::pair<Number, Number> de_boor(const std::vector<double>& flat, int degree, int span,
                                  const std::vector<PolePoint>& poles, const std::vector<double>& weights,
                                  const Number& u) {
  std::vector<Number> wx;
  std::vector<Number> wy;
  std::vector<Number> w;
  for (int j = 0; j <= degree; ++j) {
    const auto index = static_cast<std::size_t>(span - degree + j);
    const double weight = weights.empty() ? 1.0 : weights[index];
    wx.push_back(poles[index].first * Number(weight));
    wy.push_back(poles[index].second * Number(weight));
    w.push_back(Number(weight));
  }
  for (int r = 1; r <= degree; ++r) {
    for (int j = degree; j >= r; --j) {
      const double left = flat[static_cast<std::size_t>(j + span - degree)];
      const double right = flat[static_cast<std::size_t>(j + 1 + span - r)];
      const Number alpha = (u - Number(left)) / Number(right - left);
      const Number beta = Number(1.0) - alpha;
      const auto k = static_cast<std::size_t>(j);
      wx[k] = beta * wx[k - 1] + alpha * wx[k];
      wy[k] = beta * wy[k - 1] + alpha * wy[k];
      w[k] = beta * w[k - 1] + alpha * w[k];
    }
  }
  const auto top = static_cast<std::size_t>(degree);
  return {wx[top] / w[top], wy[top] / w[top]};
}

// point_on(p, B-spline): a helper unknown u (the parameter of the foot) and p = C(u).  The knot span is the one of
// the point's starting foot, so the equation's support stays local (two poles more than the degree).
void lower_point_on_bspline(Model& m, const Pt& p, const SketchEntity& target) {
  const SplineModel& spline = m.splines.at(target.id);
  const SketchBSpline& definition = spline.definition;
  if (definition.periodic)
    throw ValueError("point_on a periodic B-spline ('" + target.id + "') is not supported by the sketch solver");
  const int degree = definition.degree;
  if (2 * (degree + 1) + 3 > kSlots) {
    throw ValueError("point_on a degree " + std::to_string(degree) + " B-spline ('" + target.id +
                     "') involves more unknowns than the native solver supports");
  }
  std::vector<double> flat;
  for (std::size_t i = 0; i < definition.knots.size(); ++i)
    for (int k = 0; k < definition.multiplicities[i]; ++k)
      flat.push_back(definition.knots[i]);
  const std::vector<double> weights = definition.weights.value_or(std::vector<double>{});
  std::vector<SketchPoint2> start_poles;
  for (const Pt& pole : spline.poles)
    start_poles.push_back(m.initial(pole));
  const int pole_count = static_cast<int>(spline.poles.size());
  // the foot of the point's start position: dense samples per span, then a few narrowing passes
  const SketchPoint2 seed = m.initial(p);
  int best_span = degree;
  double best_u = flat[static_cast<std::size_t>(degree)];
  double best_distance = std::numeric_limits<double>::infinity();
  const auto distance_at = [&](int span, double u) {
    const auto [x, y] = de_boor<double>(flat, degree, span, start_poles, weights, u);
    return std::hypot(x - seed.first, y - seed.second);
  };
  for (int span = degree; span < pole_count; ++span) {
    const double a = flat[static_cast<std::size_t>(span)];
    const double b = flat[static_cast<std::size_t>(span + 1)];
    if (!(b > a))
      continue;
    constexpr int kSamples = 32;
    double step = (b - a) / kSamples;
    double u_best = a;
    double d_best = std::numeric_limits<double>::infinity();
    for (int i = 0; i <= kSamples; ++i) {
      const double u = a + step * i;
      if (const double d = distance_at(span, u); d < d_best) {
        d_best = d;
        u_best = u;
      }
    }
    for (int pass = 0; pass < 30; ++pass) {
      for (const double u : {std::max(a, u_best - step), std::min(b, u_best + step)})
        if (const double d = distance_at(span, u); d < d_best) {
          d_best = d;
          u_best = u;
        }
      step *= 0.5;
    }
    if (d_best < best_distance) {
      best_distance = d_best;
      best_u = u_best;
      best_span = span;
    }
  }
  const int u = m.system.params.add(best_u);
  const std::vector<Pt> poles = spline.poles;
  const int span = best_span;
  const auto curve_at = [=](const Env& e) {
    std::vector<std::pair<Dual, Dual>> local(poles.size());
    for (int j = span - degree; j <= span; ++j) {
      const V2 v = e(poles[static_cast<std::size_t>(j)]);
      local[static_cast<std::size_t>(j)] = {v.x, v.y};
    }
    return de_boor<Dual>(flat, degree, span, local, weights, e(u));
  };
  m.equation([=](const Env& e) { return e(p).x - curve_at(e).first; });
  m.equation([=](const Env& e) { return e(p).y - curve_at(e).second; });
}

// point_on(p, ellipse): the distances to the foci add up to the major diameter.
void lower_point_on_ellipse(Model& m, const Pt& p, const SketchEntity& target) {
  const Pt center = m.point_by_id(target.point_id("center"));
  const Pt major = m.point_by_id(target.point_id("major"));
  const Pt minor = m.point_by_id(target.point_id("minor"));
  m.equation([=](const Env& e) {
    const V2 c = e(center);
    const V2 axis = e(major) - c;
    const Dual a = length(axis);
    const Dual b = length(e(minor) - c);
    const Dual focal = sqrt(a * a - b * b) / a;
    const V2 offset{axis.x * focal, axis.y * focal};
    const V2 here = e(p);
    return length(here - (c + offset)) + length(here - (c - offset)) - Dual(2.0) * a;
  });
}

void lower_point_on(Model& m, const SketchConstraint& c) {
  const Pt p = m.point(m.target(c, 0));
  const SketchEntity& target = m.entity(m.target(c, 1));
  if (target.kind == kLineKind) {
    const LineRef line = m.line(target);
    m.equation([=](const Env& e) { return cross(e(p) - e(line.start), line.direction(e)); });
  } else if (target.kind == kCircleKind || target.kind == kArcKind) {
    const Pt center = m.circle_center(m.target(c, 1));
    const RadiusRef radius = m.radius_ref(m.target(c, 1));
    m.equation([=](const Env& e) { return length(e(p) - e(center)) - radius(e); });
  } else if (target.kind == kBSplineKind) {
    lower_point_on_bspline(m, p, target);
  } else if (target.kind == kEllipseKind) {
    lower_point_on_ellipse(m, p, target);
  } else {
    throw ValueError("Unsupported point_on target kind '" + target.kind + "'");
  }
}

void lower_angle(Model& m, const SketchConstraint& c) {
  // SolveSpace constrains the undirected angle between the two directions; the
  // two directed solutions both satisfy it and the solver stays in the basin of
  // the initial geometry, so fold the directed value to its smaller magnitude.
  const double value = c.numeric_value();
  double magnitude = positive_mod(value, 360.0);
  if (magnitude < 1e-9 || std::abs(magnitude - 360.0) < 1e-9) {
    throw ValueError(
        "A driving angle of 0/360 degrees means the lines are parallel \xE2\x80\x94 use "
        "constrain_parallel_rsketch instead");
  }
  magnitude = std::min(magnitude, 360.0 - magnitude);
  const double cosine = std::cos(magnitude * kPi / 180.0);
  const LineRef a = m.line(m.target(c, 0));
  const LineRef b = m.line(m.target(c, 1));
  m.equation([=](const Env& e) {
    const V2 da = a.direction(e);
    const V2 db = b.direction(e);
    return dot(da, db) / (length(da) * length(db)) - cosine;
  });
}

void lower_length(Model& m, const SketchConstraint& c) {
  const SketchEntity& e0 = m.entity(m.target(c, 0));
  if (e0.kind != kLineKind) {
    throw ValueError("Driving length constraints are supported only for lines; use driving=False to measure " +
                     e0.kind + " length");
  }
  const LineRef line = m.line(e0);
  const double value = c.numeric_value();
  m.equation([=](const Env& e) { return length(line.direction(e)) - value; });
}

void lower_ellipse_radius(Model& m, const SketchConstraint& c) {
  const SketchEntity& ellipse = m.entity(m.target(c, 0));
  if (ellipse.kind != kEllipseKind) {
    throw ValueError("'" + c.kind + "' requires an ellipse target, got '" + ellipse.kind + "'");
  }
  const Pt center = m.point_by_id(ellipse.point_id("center"));
  const Pt axis = m.point_by_id(ellipse.point_id(c.kind == "major_radius" ? "major" : "minor"));
  const double value = c.numeric_value();
  m.equation([=](const Env& e) { return length(e(axis) - e(center)) - value; });
}

}  // namespace

bool is_basic_kind(const std::string& kind) {
  return basic_kinds().count(kind) != 0;
}

void lower_basic(Model& m, const SketchConstraint& c) {
  const std::string& kind = c.kind;
  if (kind == "coincident") {
    const Pt a = m.point(m.target(c, 0));
    const Pt b = m.point(m.target(c, 1));
    m.equation([=](const Env& e) { return e(a.x) - e(b.x); });
    m.equation([=](const Env& e) { return e(a.y) - e(b.y); });
  } else if (kind == "concentric") {
    const Pt a = m.circle_center(m.target(c, 0));
    const Pt b = m.circle_center(m.target(c, 1));
    m.equation([=](const Env& e) { return e(a.x) - e(b.x); });
    m.equation([=](const Env& e) { return e(a.y) - e(b.y); });
  } else if (kind == "horizontal") {
    const LineRef line = m.line(m.target(c, 0));
    m.equation([=](const Env& e) { return e(line.start.y) - e(line.end.y); });
  } else if (kind == "vertical") {
    const LineRef line = m.line(m.target(c, 0));
    m.equation([=](const Env& e) { return e(line.start.x) - e(line.end.x); });
  } else if (kind == "points_horizontal") {
    const Pt a = m.point(m.target(c, 0));
    const Pt b = m.point(m.target(c, 1));
    m.equation([=](const Env& e) { return e(a.y) - e(b.y); });
  } else if (kind == "points_vertical") {
    const Pt a = m.point(m.target(c, 0));
    const Pt b = m.point(m.target(c, 1));
    m.equation([=](const Env& e) { return e(a.x) - e(b.x); });
  } else if (kind == "parallel") {
    const LineRef a = m.line(m.target(c, 0));
    const LineRef b = m.line(m.target(c, 1));
    m.equation([=](const Env& e) { return cross(a.direction(e), b.direction(e)); });
  } else if (kind == "perpendicular") {
    const LineRef a = m.line(m.target(c, 0));
    const LineRef b = m.line(m.target(c, 1));
    m.equation([=](const Env& e) { return dot(a.direction(e), b.direction(e)); });
  } else if (kind == "collinear") {
    const LineRef a = m.line(m.target(c, 0));
    const LineRef b = m.line(m.target(c, 1));
    m.equation([=](const Env& e) { return cross(a.direction(e), b.direction(e)); });
    m.equation([=](const Env& e) { return cross(e(a.start) - e(b.start), b.direction(e)); });
  } else if (kind == "equal_length") {
    const LineRef a = m.line(m.target(c, 0));
    const LineRef b = m.line(m.target(c, 1));
    m.equation([=](const Env& e) { return length(a.direction(e)) - length(b.direction(e)); });
  } else if (kind == "equal_radius") {
    const RadiusRef a = m.radius_ref(m.target(c, 0));
    const RadiusRef b = m.radius_ref(m.target(c, 1));
    m.equation([=](const Env& e) { return a(e) - b(e); });
  } else if (kind == "distance") {
    const Pt a = m.point(m.target(c, 0));
    const Pt b = m.point(m.target(c, 1));
    const double value = c.numeric_value();
    m.equation([=](const Env& e) { return length(e(a) - e(b)) - value; });
  } else if (kind == "distance_x" || kind == "distance_y") {
    // target = point_b - point_a along the axis (SimpleCAD's sign convention).
    const Pt a = m.point(m.target(c, 0));
    const Pt b = m.point(m.target(c, 1));
    const double value = c.numeric_value();
    if (kind == "distance_x") {
      m.equation([=](const Env& e) { return e(b.x) - e(a.x) - value; });
    } else {
      m.equation([=](const Env& e) { return e(b.y) - e(a.y) - value; });
    }
  } else if (kind == "length") {
    lower_length(m, c);
  } else if (kind == "major_radius" || kind == "minor_radius") {
    lower_ellipse_radius(m, c);
  } else if (kind == "radius" || kind == "diameter") {
    const double diameter = c.numeric_value() * (kind == "radius" ? 2.0 : 1.0);
    const RadiusRef radius = m.radius_ref(m.target(c, 0));
    m.equation([=](const Env& e) { return radius(e) * 2.0 - diameter; });
  } else if (kind == "point_on") {
    lower_point_on(m, c);
  } else if (kind == "angle") {
    lower_angle(m, c);
  } else if (kind == "midpoint") {
    const Pt p = m.point(m.target(c, 0));
    const LineRef line = m.line(m.target(c, 1));
    m.equation([=](const Env& e) { return e(p.x) - (e(line.start.x) + e(line.end.x)) * 0.5; });
    m.equation([=](const Env& e) { return e(p.y) - (e(line.start.y) + e(line.end.y)) * 0.5; });
  }
}

}  // namespace scad::sketch_solver
