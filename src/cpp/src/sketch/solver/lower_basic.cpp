// Point, line and dimension constraints.  Each equation is the SolveSpace form
// py-slvs lowers to (docs/sketch-solver.md has the table).
#include <algorithm>
#include <cmath>
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
