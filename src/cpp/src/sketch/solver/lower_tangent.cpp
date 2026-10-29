// Tangency: line/circle and circle/circle through a helper contact point (the
// SolveSpace decomposition py-slvs uses), arc/line and the cubic cases through
// the tangent direction at the selected endpoint.
#include <cmath>
#include <string>

#include "model.hpp"
#include "scad/core/error.hpp"

namespace scad::sketch_solver {

namespace {

std::optional<std::string> selector(const SketchConstraint& c, const char* key) {
  const Value* value = c.metadata.find(key);
  if (value == nullptr || value->is_null())
    return std::nullopt;
  return value->as_string();
}

bool is_curve_kind(const std::string& kind) {
  return kind == kArcKind || kind == kBSplineKind;
}

// radius ⟂ line at the contact point T, with T on both the circle and the line.
void line_circle_tangent(Model& m, const SketchRef& line_ref, const SketchRef& circle_ref) {
  const Pt center = m.circle_center(circle_ref);
  const RadiusRef radius = m.radius_ref(circle_ref);
  const LineRef line = m.line(line_ref);

  const SketchPoint2 c0 = m.initial(center);
  const SketchPoint2 s0 = m.initial(line.start);
  const SketchPoint2 e0 = m.initial(line.end);
  const double dx = e0.first - s0.first;
  const double dy = e0.second - s0.second;
  const double denominator = dx * dx + dy * dy;
  if (denominator <= 1e-18)
    throw ValueError("A tangent constraint requires a non-degenerate line");
  const double parameter = ((c0.first - s0.first) * dx + (c0.second - s0.second) * dy) / denominator;
  const Pt contact = m.helper_point(s0.first + parameter * dx, s0.second + parameter * dy);

  m.equation([=](const Env& e) { return length(e(contact) - e(center)) - radius(e); });
  m.equation([=](const Env& e) { return cross(e(contact) - e(line.start), line.direction(e)); });
  m.equation([=](const Env& e) { return dot(e(contact) - e(center), line.direction(e)); });
}

void circle_circle_tangent(Model& m, const SketchRef& a_ref, const SketchRef& b_ref, const std::string& mode) {
  const Pt center_a = m.circle_center(a_ref);
  const Pt center_b = m.circle_center(b_ref);
  const RadiusRef radius_a = m.radius_ref(a_ref);
  const RadiusRef radius_b = m.radius_ref(b_ref);

  const SketchPoint2 a0 = m.initial(center_a);
  const SketchPoint2 b0 = m.initial(center_b);
  double dx = b0.first - a0.first;
  double dy = b0.second - a0.second;
  double magnitude = std::hypot(dx, dy);
  if (magnitude <= 1e-18) {
    dx = 1.0;
    dy = 0.0;
    magnitude = 1.0;
  }
  const double r_a = m.initial_radius(a_ref);
  const double sign = mode == "external" ? 1.0 : (r_a >= m.initial_radius(b_ref) ? 1.0 : -1.0);
  const Pt contact = m.helper_point(a0.first + sign * r_a * dx / magnitude, a0.second + sign * r_a * dy / magnitude);

  m.equation([=](const Env& e) { return length(e(contact) - e(center_a)) - radius_a(e); });
  m.equation([=](const Env& e) { return length(e(contact) - e(center_b)) - radius_b(e); });
  m.equation([=](const Env& e) { return cross(e(contact) - e(center_a), e(contact) - e(center_b)); });
}

// The endpoint tangent direction of a curve entity (not normalised).
struct Tangent {
  enum class Kind { ArcRadius, Cubic } kind = Kind::ArcRadius;
  Pt center, endpoint;  // arc: the radius vector, rotated a quarter turn
  Pt from, to;          // cubic: to - from
  V2 operator()(const Env& e) const {
    if (kind == Kind::ArcRadius) {
      const V2 radius = e(endpoint) - e(center);
      return {-radius.y, radius.x};
    }
    return e(to) - e(from);
  }
};

Tangent curve_tangent(const Model& m, const SketchRef& ref, const std::string& at) {
  const SketchEntity& entity = m.entity(ref);
  Tangent t;
  if (entity.kind == kArcKind) {
    t.kind = Tangent::Kind::ArcRadius;
    t.center = m.point_by_id(entity.point_id("center"));
    t.endpoint = m.point_by_id(entity.point_id(at == "end" ? "end" : "start"));
    return t;
  }
  const SplineModel& spline = m.splines.at(entity.id);
  if (!spline.cubic_bezier || spline.segments.empty()) {
    throw ValueError("B-spline '" + entity.id + "' is not representable as cubic Bezier segments by the sketch solver");
  }
  t.kind = Tangent::Kind::Cubic;
  if (at == "end") {
    const auto& last = spline.segments.back();
    t.from = spline.poles[static_cast<std::size_t>(last[2])];
    t.to = spline.poles[static_cast<std::size_t>(last[3])];
  } else {
    const auto& first = spline.segments.front();
    t.from = spline.poles[static_cast<std::size_t>(first[0])];
    t.to = spline.poles[static_cast<std::size_t>(first[1])];
  }
  return t;
}

}  // namespace

void lower_tangent(Model& m, const SketchConstraint& c) {
  const SketchRef& ref_a = m.target(c, 0);
  const SketchRef& ref_b = m.target(c, 1);
  const std::string& kind_a = m.entity(ref_a).kind;
  const std::string& kind_b = m.entity(ref_b).kind;
  const std::string mode = selector(c, "mode").value_or("external");
  const std::optional<std::string> at[2] = {selector(c, "at_a"), selector(c, "at_b")};

  if ((kind_a == kLineKind && kind_b == kCircleKind) || (kind_a == kCircleKind && kind_b == kLineKind)) {
    line_circle_tangent(m, kind_a == kLineKind ? ref_a : ref_b, kind_a == kLineKind ? ref_b : ref_a);
    return;
  }
  if (kind_a == kCircleKind && kind_b == kCircleKind) {
    circle_circle_tangent(m, ref_a, ref_b, mode);
    return;
  }

  const std::string kinds[2] = {kind_a, kind_b};
  const SketchRef* refs[2] = {&ref_a, &ref_b};
  const auto unsupported = [&] {
    return ValueError("Unsupported tangent target kinds '" + kind_a + "' and '" + kind_b + "'");
  };
  if (!is_curve_kind(kind_a) && !is_curve_kind(kind_b))
    throw unsupported();
  // The validated end of each curve target ("start" or "end"); empty for a target that is not a curve.
  std::string curve_end[2];
  for (int i = 0; i < 2; ++i) {
    if (!is_curve_kind(kinds[i]))
      continue;
    const std::optional<std::string>& requested = at[i];
    if (!requested || (*requested != "start" && *requested != "end")) {
      throw ValueError("Tangent constraint '" + c.id + "' requires at_" + (i == 0 ? "a" : "b") + "='start' or 'end'");
    }
    curve_end[i] = *requested;
  }

  const bool has_line = kind_a == kLineKind || kind_b == kLineKind;
  if (has_line) {
    const int curve = is_curve_kind(kind_a) ? 0 : 1;
    const int line_index = 1 - curve;
    if (kinds[line_index] != kLineKind)
      throw unsupported();
    const LineRef line = m.line(*refs[line_index]);
    const Tangent tangent = curve_tangent(m, *refs[curve], curve_end[curve]);
    if (kinds[curve] == kArcKind) {
      // The line direction is perpendicular to the radius at the selected endpoint.
      const SketchEntity& arc = m.entity(*refs[curve]);
      const Pt center = m.point_by_id(arc.point_id("center"));
      const Pt endpoint = m.point_by_id(arc.point_id(curve_end[curve] == "end" ? "end" : "start"));
      m.equation([=](const Env& e) { return dot(line.direction(e), e(endpoint) - e(center)); });
    } else {
      m.equation([=](const Env& e) { return cross(tangent(e), line.direction(e)); });
    }
    return;
  }
  if (is_curve_kind(kind_a) && is_curve_kind(kind_b)) {
    const Tangent ta = curve_tangent(m, ref_a, curve_end[0]);
    const Tangent tb = curve_tangent(m, ref_b, curve_end[1]);
    m.equation([=](const Env& e) { return cross(ta(e), tb(e)); });
    return;
  }
  throw unsupported();
}

}  // namespace scad::sketch_solver
