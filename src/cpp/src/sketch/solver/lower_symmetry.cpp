// Symmetry-flavoured constraints: symmetric, mirror, midpoint_points, line_distance
// and normal.  py-slvs builds these from helper entities (its addSymmetricLine
// mirrors about the workplane axis whatever the axis entity is); the equations
// below are what those helpers reduce to once their auxiliary points are eliminated.
#include <algorithm>
#include <cmath>
#include <set>
#include <string>

#include "model.hpp"
#include "scad/core/error.hpp"

namespace scad::sketch_solver {

namespace {

// P and Q mirror each other about the axis iff the midpoint of PQ lies on the
// axis and PQ is perpendicular to it.
void symmetric_about_line(Model& m, const Pt& p, const Pt& q, const LineRef& axis) {
  m.equation([=](const Env& e) {
    const V2 midpoint = (e(p) + e(q)) * 0.5;
    return cross(midpoint - e(axis.start), axis.direction(e));
  });
  m.equation([=](const Env& e) { return dot(e(q) - e(p), axis.direction(e)); });
}

double distance(const SketchPoint2& a, const SketchPoint2& b) {
  return std::hypot(a.first - b.first, a.second - b.second);
}

// Which points of two same-kind entities mirror each other: lines and arcs match
// endpoints by nearest initial position, circles match centers.
std::vector<std::pair<std::string, std::string>> mirror_point_pairs(const Model& m, const SketchEntity& a,
                                                                    const SketchEntity& b) {
  if (a.kind == kCircleKind)
    return {{a.point_id("center"), b.point_id("center")}};
  std::vector<std::string> a_points{a.point_id("start"), a.point_id("end")};
  std::vector<std::string> b_points{b.point_id("start"), b.point_id("end")};
  const auto initial = [&m](const std::string& id) { return m.initial(m.point_by_id(id)); };
  const double direct =
      distance(initial(a_points[0]), initial(b_points[0])) + distance(initial(a_points[1]), initial(b_points[1]));
  const double flipped =
      distance(initial(a_points[0]), initial(b_points[1])) + distance(initial(a_points[1]), initial(b_points[0]));
  if (flipped < direct)
    std::reverse(b_points.begin(), b_points.end());
  std::vector<std::pair<std::string, std::string>> pairs{{a_points[0], b_points[0]}, {a_points[1], b_points[1]}};
  if (a.kind == kArcKind)
    pairs.emplace_back(a.point_id("center"), b.point_id("center"));
  return pairs;
}

void lower_mirror(Model& m, const SketchConstraint& c) {
  const SketchEntity& a = m.entity(m.target(c, 0));
  const SketchEntity& b = m.entity(m.target(c, 2));
  if (a.kind != b.kind) {
    throw ValueError("Mirror constraint requires two entities of the same kind, got '" + a.kind + "' and '" + b.kind +
                     "'");
  }
  const SketchEntity& axis_entity = m.entity(m.target(c, 1));
  if (axis_entity.kind != kLineKind)
    throw ValueError("Mirror constraint requires a line as its axis");
  const LineRef axis = m.line(axis_entity);
  for (const auto& [id_a, id_b] : mirror_point_pairs(m, a, b)) {
    symmetric_about_line(m, m.point_by_id(id_a), m.point_by_id(id_b), axis);
  }
}

void lower_midpoint_points(Model& m, const SketchConstraint& c) {
  const std::string mid_id = m.sketch.resolve_point_id(m.target(c, 0));
  const std::string a_id = m.sketch.resolve_point_id(m.target(c, 1));
  const std::string b_id = m.sketch.resolve_point_id(m.target(c, 2));
  if (std::set<std::string>{mid_id, a_id, b_id}.size() != 3) {
    throw ValueError("A midpoint-points constraint requires three distinct points");
  }
  const Pt mid = m.point_by_id(mid_id);
  const Pt a = m.point_by_id(a_id);
  const Pt b = m.point_by_id(b_id);
  // M is the midpoint of A and B iff |AM| = |MB| and the two segments are parallel.
  m.equation([=](const Env& e) { return length(e(mid) - e(a)) - length(e(b) - e(mid)); });
  m.equation([=](const Env& e) { return cross(e(mid) - e(a), e(b) - e(mid)); });
}

void lower_line_distance(Model& m, const SketchConstraint& c) {
  const double value = c.numeric_value();
  if (value <= 0.0)
    throw ValueError("A line-to-line distance must be positive");
  const SketchEntity& a = m.entity(m.target(c, 0));
  const SketchEntity& b = m.entity(m.target(c, 1));
  if (a.kind != kLineKind || b.kind != kLineKind)
    throw ValueError("A line-to-line distance requires two line entities");
  // Drive line a's start point against line b, keeping the side it starts on.
  const Pt probe = m.point_by_id(a.point_id("start"));
  const LineRef line = m.line(b);
  const SketchPoint2 b_start = m.initial(line.start);
  const SketchPoint2 b_end = m.initial(line.end);
  const SketchPoint2 p0 = m.initial(probe);
  const double initial_cross = (b_end.first - b_start.first) * (p0.second - b_start.second) -
                               (b_end.second - b_start.second) * (p0.first - b_start.first);
  const double target = initial_cross >= 0.0 ? value : -value;
  m.equation([=](const Env& e) {
    const V2 direction = line.direction(e);
    return cross(direction, e(probe) - e(line.start)) / length(direction) - target;
  });
}

void lower_normal(Model& m, const SketchConstraint& c) {
  const SketchEntity& first = m.entity(m.target(c, 0));
  const SketchEntity& second = m.entity(m.target(c, 1));
  const auto is_curve = [](const SketchEntity& e) { return e.kind == kCircleKind || e.kind == kArcKind; };
  std::size_t line_index = 2;
  std::size_t curve_index = 2;
  for (std::size_t i = 0; i < 2; ++i) {
    const SketchEntity& e = i == 0 ? first : second;
    if (line_index == 2 && e.kind == kLineKind)
      line_index = i;
    if (curve_index == 2 && is_curve(e))
      curve_index = i;
  }
  if (line_index == 2 || curve_index == 2) {
    throw ValueError("A normal constraint requires one line and one circle or arc");
  }
  // A line normal to a circle or arc passes through its center.
  const Pt center = m.circle_center(m.target(c, curve_index));
  const LineRef line = m.line(m.target(c, line_index));
  m.equation([=](const Env& e) { return cross(e(center) - e(line.start), line.direction(e)); });
}

}  // namespace

bool is_symmetry_kind(const std::string& kind) {
  return kind == "symmetric" || kind == "mirror" || kind == "midpoint_points" || kind == "line_distance" ||
         kind == "normal";
}

void lower_symmetry(Model& m, const SketchConstraint& c) {
  if (c.kind == "symmetric") {
    symmetric_about_line(m, m.point(m.target(c, 0)), m.point(m.target(c, 1)), m.line(m.target(c, 2)));
  } else if (c.kind == "mirror") {
    lower_mirror(m, c);
  } else if (c.kind == "midpoint_points") {
    lower_midpoint_points(m, c);
  } else if (c.kind == "line_distance") {
    lower_line_distance(m, c);
  } else if (c.kind == "normal") {
    lower_normal(m, c);
  }
}

}  // namespace scad::sketch_solver
