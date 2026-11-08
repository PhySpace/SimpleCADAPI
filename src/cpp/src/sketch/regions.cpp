#include "regions.hpp"

#include <algorithm>
#include <cmath>
#include <string>

#include "edit_curves.hpp"
#include "scad/core/vec.hpp"

namespace scad::sketch_detail {

namespace {

using Pt = SketchPoint2;
constexpr int kArcSteps = 24;
constexpr int kCurveSteps = 32;

Pt solved(const SketchSolveResult& result, const std::string& id) {
  return result.solved_points.at(id);
}

// Points along an edge entity from its start to its end, in sketch coordinates.
std::vector<Pt> edge_points(const SketchEntity& entity, const SketchSolveResult& result) {
  const Pt s = solved(result, entity.point_id("start"));
  const Pt e = solved(result, entity.point_id("end"));
  if (entity.kind == kLineKind)
    return {s, e};
  std::vector<Pt> out;
  if (entity.kind == kArcKind) {
    const Pt c = solved(result, entity.point_id("center"));
    const double r = std::hypot(s.first - c.first, s.second - c.second);
    const double a0 = std::atan2(s.second - c.second, s.first - c.first);
    double sweep = std::atan2(e.second - c.second, e.first - c.first) - a0;
    while (sweep <= 1e-12)
      sweep += 2.0 * kPi;
    for (int i = 0; i <= kArcSteps; ++i) {
      const double a = a0 + sweep * i / kArcSteps;
      out.emplace_back(c.first + r * std::cos(a), c.second + r * std::sin(a));
    }
    return out;
  }
  // a B-spline: its solved control points
  const SketchBSpline definition = entity.bspline();
  Spline2 spline;
  spline.degree = definition.degree;
  for (std::size_t i = 0; i < definition.poles.size(); ++i)
    spline.poles.push_back(solved(result, "bspline:" + entity.id + ":pole:" + std::to_string(i)));
  spline.knots = definition.knots;
  spline.multiplicities = definition.multiplicities;
  if (definition.weights)
    spline.weights = *definition.weights;
  spline.periodic = definition.periodic;
  const auto curve = make_spline2(spline);
  const double u0 = curve->FirstParameter();
  const double u1 = curve->LastParameter();
  for (int i = 0; i <= kCurveSteps; ++i)
    out.push_back(value_at(curve, u0 + (u1 - u0) * i / kCurveSteps));
  return out;
}

// The closed profile as a polygon (sketch coordinates); empty for an open chain.
std::vector<Pt> polygon_of(const Sketch& sketch, const SketchSolveResult& result, const SketchProfile& profile) {
  std::vector<Pt> out;
  if (!profile.closed)
    return out;
  const SketchEntity& first = sketch.entities().at(profile.entity_ids.front());
  if (profile.kind == "circle" || profile.kind == "ellipse") {
    const Pt c = solved(result, first.point_id("center"));
    Pt u{0, 0};
    Pt v{0, 0};
    if (profile.kind == "circle") {
      const double r = result.solved_scalars.at("circle:" + first.id + ":radius");
      u = {r, 0};
      v = {0, r};
    } else {
      const Pt major = solved(result, first.point_id("major"));
      const Pt minor = solved(result, first.point_id("minor"));
      u = {major.first - c.first, major.second - c.second};
      v = {minor.first - c.first, minor.second - c.second};
    }
    for (int i = 0; i < 2 * kArcSteps; ++i) {
      const double a = kPi * i / kArcSteps;
      out.emplace_back(c.first + u.first * std::cos(a) + v.first * std::sin(a),
                       c.second + u.second * std::cos(a) + v.second * std::sin(a));
    }
    return out;
  }
  for (std::size_t i = 0; i < profile.entity_ids.size(); ++i) {
    std::vector<Pt> points = edge_points(sketch.entities().at(profile.entity_ids[i]), result);
    if (profile.reversed[i])
      std::reverse(points.begin(), points.end());
    out.insert(out.end(), points.begin(), points.end() - 1);  // the last point is the next edge's first
  }
  return out;
}

double area(const std::vector<Pt>& polygon) {
  double sum = 0.0;
  for (std::size_t i = 0; i < polygon.size(); ++i) {
    const Pt& a = polygon[i];
    const Pt& b = polygon[(i + 1) % polygon.size()];
    sum += a.first * b.second - b.first * a.second;
  }
  return std::abs(sum) / 2.0;
}

bool inside(const Pt& p, const std::vector<Pt>& polygon) {
  bool in = false;
  for (std::size_t i = 0, j = polygon.size() - 1; i < polygon.size(); j = i++) {
    const Pt& a = polygon[i];
    const Pt& b = polygon[j];
    if ((a.second > p.second) != (b.second > p.second) &&
        p.first < (b.first - a.first) * (p.second - a.second) / (b.second - a.second) + a.first)
      in = !in;
  }
  return in;
}

// Is `inner` inside `outer`: the smaller one, with most of its points inside (a shared corner or a touching edge is
// on the boundary and may count either way).
bool contains(const std::vector<Pt>& outer, double outer_area, const std::vector<Pt>& inner, double inner_area) {
  if (outer.size() < 3 || inner.empty() || inner_area >= outer_area)
    return false;
  std::size_t hits = 0;
  for (const Pt& p : inner)
    hits += inside(p, outer) ? 1 : 0;
  return 2 * hits > inner.size();
}

}  // namespace

std::vector<ProfileNesting> profile_nesting(const Sketch& sketch, const SketchSolveResult& result,
                                            const std::vector<SketchProfile>& profiles) {
  std::vector<std::vector<Pt>> polygons;
  std::vector<double> areas;
  for (const SketchProfile& profile : profiles) {
    polygons.push_back(polygon_of(sketch, result, profile));
    areas.push_back(polygons.back().size() >= 3 ? area(polygons.back()) : 0.0);
  }
  std::vector<ProfileNesting> out(profiles.size());
  for (std::size_t i = 0; i < profiles.size(); ++i) {
    if (!profiles[i].closed)
      continue;
    int parent = -1;
    for (std::size_t j = 0; j < profiles.size(); ++j) {
      if (j == i || !profiles[j].closed || !contains(polygons[j], areas[j], polygons[i], areas[i]))
        continue;
      if (parent < 0 || areas[j] < areas[static_cast<std::size_t>(parent)])
        parent = static_cast<int>(j);  // the smallest loop around it is the one it lies directly inside
    }
    out[i].parent = parent;
  }
  for (std::size_t i = 0; i < profiles.size(); ++i) {
    if (!profiles[i].closed)
      continue;
    int depth = 0;
    for (int at = out[i].parent; at >= 0 && depth <= static_cast<int>(profiles.size());
         at = out[static_cast<std::size_t>(at)].parent)
      ++depth;
    out[i].depth = depth;
  }
  return out;
}

}  // namespace scad::sketch_detail
