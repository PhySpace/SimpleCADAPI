// trim_rsketch, extend_rsketch, diff_sketch_rsketchdiff and inspect_sketch_rsketchcrossings.
//
// Both edits work on the *solved* geometry: the sketch is solved first, every point is moved to where the solver put
// it, and the cuts are computed on those coordinates.  Lines, circles, arcs and B-splines can be cut; lines and
// B-splines can be extended; lines, circles, arcs, B-splines and ellipses cut (an ellipse is never a subject: the
// sketch has no elliptic arc).  An arc runs counter-clockwise from `start` to `end` around `center`.
//
// Line / circle / arc pairs meet in closed form (`line_params`, `angle_params`); a pair with a B-spline or an ellipse
// meets through OCCT (`edit_curves.hpp`, Geom2dAPI_InterCurveCurve), a tangent touch being one cut.  A B-spline is cut
// on its own parameter: each kept piece is a new B-spline (OCCT Segment), its first and last control points are its
// end points and its inner control points are sketch points (an original control point is reused where the piece
// keeps it unchanged, the others are new).  A closed B-spline (periodic, or starting and ending on one point) needs
// two cuts, like a circle.  A B-spline end is extended curvature-continuously (GeomLib::ExtendCurveToPoint) towards
// where its end tangent meets the next entity, then cut at the first crossing.
//
// Constraints: a constraint on an end point stays with that point (so with the piece that keeps that end); a tangent
// constraint at a B-spline end (at_a / at_b) moves to the piece that keeps that end; any other constraint naming the
// cut entity goes, and so does every constraint on an original control point no entity uses any more (that point is
// removed).
#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <tuple>

#include <Geom2d_Circle.hxx>
#include <Geom2d_Ellipse.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <gp_Ax2d.hxx>

#include "edit_curves.hpp"
#include "finalize.hpp"
#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"
#include "scad/sketch/operators.hpp"

namespace scad {

namespace {

using sketch_detail::Crossing2;
using sketch_detail::finalize_sketch_object;
using sketch_detail::Spline2;
using CurveHandle = opencascade::handle<Geom2d_Curve>;
using SplineHandle = opencascade::handle<Geom2d_BSplineCurve>;

// Two positions closer than this (sketch units) are the same place: a crossing this close to an end is not a cut, and
// a cut this close to an existing point reuses it.
constexpr double kTol = 1e-6;
constexpr double kTwoPi = 2.0 * kPi;
using Pt = SketchPoint2;

double wrap(double angle) {
  angle = std::fmod(angle, kTwoPi);
  if (angle < 0.0)
    angle += kTwoPi;
  return angle >= kTwoPi ? 0.0 : angle;
}

bool finite(double v) {
  return std::isfinite(v);
}

// The kinds that meet in closed form.
bool closed_form(const std::string& kind) {
  return kind == kLineKind || kind == kCircleKind || kind == kArcKind;
}

// The kinds that can be cut.
bool trimmable(const std::string& kind) {
  return closed_form(kind) || kind == kBSplineKind;
}

// The kinds that cut (and that crossings lists).
bool cutting(const std::string& kind) {
  return trimmable(kind) || kind == kEllipseKind;
}

std::string id_of(const SketchTarget& target) {
  return target.is_ref() ? target.ref().entity_id : target.path();
}

// ---- geometry on the solved coordinates
// ------------------------------------------------------------------------------

struct Circ {
  Pt center;
  double radius;
};

struct Geometry {
  std::map<std::string, Pt, std::less<>> points;
  std::map<std::string, double, std::less<>> radii;  // circles

  Pt at(const SketchEntity& entity, std::string_view role) const { return points.at(entity.point_id(role)); }

  Circ circle_of(const SketchEntity& entity) const {
    const Pt c = at(entity, "center");
    if (entity.kind == kCircleKind)
      return {c, radii.at(entity.id)};
    const Pt s = at(entity, "start");
    return {c, std::hypot(s.first - c.first, s.second - c.second)};
  }

  // (start angle, counter-clockwise sweep) of an arc.
  std::pair<double, double> arc_span(const SketchEntity& entity) const {
    const Pt c = at(entity, "center");
    const Pt s = at(entity, "start");
    const Pt e = at(entity, "end");
    const double start = std::atan2(s.second - c.second, s.first - c.first);
    const double end = std::atan2(e.second - c.second, e.first - c.first);
    const double sweep = wrap(end - start);
    return {start, sweep == 0.0 ? kTwoPi : sweep};
  }

  std::map<std::string, std::vector<Pt>, std::less<>> poles;  // B-splines: the solved control points

  Spline2 spline_of(const SketchEntity& entity) const {
    const SketchBSpline definition = entity.bspline();
    Spline2 out;
    out.degree = definition.degree;
    out.poles = poles.at(entity.id);
    out.knots = definition.knots;
    out.multiplicities = definition.multiplicities;
    if (definition.weights)
      out.weights = *definition.weights;
    out.periodic = definition.periodic;
    return out;
  }

  SplineHandle spline(const SketchEntity& entity) const { return sketch_detail::make_spline2(spline_of(entity)); }

  // The OCCT curve of a line, circle, arc, ellipse or B-spline.  `bounded`: a line is its segment and an arc its
  // span (both a hair longer, so a crossing on an end is found); else they are the whole line / circle.
  CurveHandle curve(const SketchEntity& entity, bool bounded) const {
    if (entity.kind == kBSplineKind)
      return spline(entity);
    if (entity.kind == kLineKind) {
      const Pt p1 = at(entity, "start");
      const Pt p2 = at(entity, "end");
      const double len = std::hypot(p2.first - p1.first, p2.second - p1.second);
      const opencascade::handle<Geom2d_Line> line =
          new Geom2d_Line(gp_Pnt2d(p1.first, p1.second), gp_Dir2d(p2.first - p1.first, p2.second - p1.second));
      if (!bounded)
        return line;
      return new Geom2d_TrimmedCurve(line, -kTol, len + kTol);
    }
    if (entity.kind == kEllipseKind) {
      const Pt c = at(entity, "center");
      Pt major = at(entity, "major");
      Pt minor = at(entity, "minor");
      double a = std::hypot(major.first - c.first, major.second - c.second);
      double b = std::hypot(minor.first - c.first, minor.second - c.second);
      if (b > a) {
        std::swap(major, minor);
        std::swap(a, b);
      }
      const gp_Ax2d axis(gp_Pnt2d(c.first, c.second), gp_Dir2d(major.first - c.first, major.second - c.second));
      return new Geom2d_Ellipse(axis, a, b);
    }
    const Circ circle = circle_of(entity);
    const opencascade::handle<Geom2d_Circle> full = new Geom2d_Circle(
        gp_Ax2d(gp_Pnt2d(circle.center.first, circle.center.second), gp_Dir2d(1.0, 0.0)), circle.radius);
    if (entity.kind == kCircleKind || !bounded)
      return full;
    const auto [start, sweep] = arc_span(entity);
    const double tol = kTol / circle.radius;
    if (sweep + 2.0 * tol >= kTwoPi)
      return full;
    return new Geom2d_TrimmedCurve(full, start - tol, start + sweep + tol);
  }
};

// Where `a` (its whole line / circle unless `bounded`) meets `b` (bounded), with the parameter on each.
std::vector<Crossing2> curve_hits(const Geometry& g, const SketchEntity& a, bool bounded, const SketchEntity& b) {
  const auto degenerate = [&](const SketchEntity& e) {
    if (e.kind == kLineKind) {
      const Pt p1 = g.at(e, "start");
      const Pt p2 = g.at(e, "end");
      return std::hypot(p2.first - p1.first, p2.second - p1.second) < kTol;
    }
    if (e.kind == kCircleKind || e.kind == kArcKind)
      return g.circle_of(e).radius < kTol;
    if (e.kind == kEllipseKind) {
      const Pt c = g.at(e, "center");
      for (const char* role : {"major", "minor"}) {
        const Pt p = g.at(e, role);
        if (std::hypot(p.first - c.first, p.second - c.second) < kTol)
          return true;
      }
    }
    return false;
  };
  if (degenerate(a) || degenerate(b))
    return {};
  return sketch_detail::intersect2(g.curve(a, bounded), g.curve(b, true), kTol);
}

bool on_arc(double angle, double start, double sweep, double tol) {
  const double d = wrap(angle - start);
  return d <= sweep + tol || d >= kTwoPi - tol;
}

// The parameters t (point = p + t * d) where the line p -> p + d meets the circle; one value when it is tangent.
std::vector<double> line_circle(Pt p, double dx, double dy, const Circ& circle) {
  const double len2 = dx * dx + dy * dy;
  if (len2 < kTol * kTol)
    return {};
  const double fx = p.first - circle.center.first;
  const double fy = p.second - circle.center.second;
  const double qb = 2.0 * (fx * dx + fy * dy);
  const double qc = fx * fx + fy * fy - circle.radius * circle.radius;
  const double disc = qb * qb - 4.0 * len2 * qc;
  const double scale = std::max({qb * qb, std::abs(4.0 * len2 * qc), 1e-30});
  if (disc < -1e-9 * scale)
    return {};
  const double root = std::sqrt(std::max(disc, 0.0));
  const double t1 = (-qb - root) / (2.0 * len2);
  const double t2 = (-qb + root) / (2.0 * len2);
  if ((t2 - t1) * std::sqrt(len2) < kTol)
    return {0.5 * (t1 + t2)};
  return {t1, t2};
}

// The parameters t along line `a` where it meets entity `b` (t in [0, 1] is on the segment); b is a line (limited to
// its segment), a circle (any t) or an arc (only the part on the arc).
std::vector<double> line_params(const Geometry& g, const SketchEntity& a, const SketchEntity& b) {
  const Pt p1 = g.at(a, "start");
  const Pt p2 = g.at(a, "end");
  const double dx = p2.first - p1.first;
  const double dy = p2.second - p1.second;
  const double len = std::hypot(dx, dy);
  if (!closed_form(b.kind)) {
    std::vector<double> found;
    for (const Crossing2& hit : curve_hits(g, a, false, b))
      found.push_back(((hit.at.first - p1.first) * dx + (hit.at.second - p1.second) * dy) / (len * len));
    return found;
  }
  if (b.kind == kLineKind) {
    const Pt p3 = g.at(b, "start");
    const Pt p4 = g.at(b, "end");
    const double ex = p4.first - p3.first;
    const double ey = p4.second - p3.second;
    const double elen = std::hypot(ex, ey);
    const double det = dx * ey - dy * ex;
    if (std::abs(det) < 1e-9 * len * elen)
      return {};  // parallel (or collinear): no single crossing
    const double t = ((p3.first - p1.first) * ey - (p3.second - p1.second) * ex) / det;
    const double u = ((p3.first - p1.first) * dy - (p3.second - p1.second) * dx) / det;
    const double tol_u = kTol / elen;
    return (u >= -tol_u && u <= 1.0 + tol_u) ? std::vector<double>{t} : std::vector<double>{};
  }
  const Circ circle = g.circle_of(b);
  std::vector<double> found = line_circle(p1, dx, dy, circle);
  if (b.kind == kArcKind) {
    const auto [start, sweep] = g.arc_span(b);
    std::erase_if(found, [&](double t) {
      const double angle =
          std::atan2(p1.second + t * dy - circle.center.second, p1.first + t * dx - circle.center.first);
      return !on_arc(angle, start, sweep, kTol / circle.radius);
    });
  }
  return found;
}

// The angles (in [0, 2 pi)) on circle / arc `a` where it meets entity `b`.
std::vector<double> angle_params(const Geometry& g, const SketchEntity& a, const SketchEntity& b) {
  const Circ circle = g.circle_of(a);
  std::vector<Pt> hits;
  if (!closed_form(b.kind)) {
    for (const Crossing2& hit : curve_hits(g, a, false, b))
      hits.push_back(hit.at);
  } else if (b.kind == kLineKind) {
    const Pt p1 = g.at(b, "start");
    const Pt p2 = g.at(b, "end");
    const double dx = p2.first - p1.first;
    const double dy = p2.second - p1.second;
    const double tol_t = kTol / std::hypot(dx, dy);
    for (const double t : line_circle(p1, dx, dy, circle))
      if (t >= -tol_t && t <= 1.0 + tol_t)
        hits.emplace_back(p1.first + t * dx, p1.second + t * dy);
  } else {
    const Circ other = g.circle_of(b);
    const double ox = other.center.first - circle.center.first;
    const double oy = other.center.second - circle.center.second;
    const double d = std::hypot(ox, oy);
    const double r = circle.radius;
    const double s = other.radius;
    if (d >= kTol && std::abs(r - s) - kTol <= d && d <= r + s + kTol) {
      const double along = (r * r - s * s + d * d) / (2.0 * d);
      const double h = std::sqrt(std::max(r * r - along * along, 0.0));
      const double mx = circle.center.first + along * ox / d;
      const double my = circle.center.second + along * oy / d;
      hits.emplace_back(mx + h * oy / d, my - h * ox / d);
      if (h > kTol)
        hits.emplace_back(mx - h * oy / d, my + h * ox / d);
    }
    if (b.kind == kArcKind) {
      const auto [start, sweep] = g.arc_span(b);
      std::erase_if(hits, [&](const Pt& p) {
        return !on_arc(std::atan2(p.second - other.center.second, p.first - other.center.first), start, sweep,
                       kTol / other.radius);
      });
    }
  }
  std::vector<double> angles;
  for (const Pt& p : hits)
    angles.push_back(wrap(std::atan2(p.second - circle.center.second, p.first - circle.center.first)));
  return angles;
}

// ---- cuts
// -----------------------------------------------------------------------------------------------------------------

// A place along the subject where one or more entities cross it.
struct Cut {
  double at;                         // t along a line, an angle on a circle / arc
  std::vector<std::string> cutters;  // ids, in sketch order
};

// Sort `raw` (position, cutter) and merge the ones that are the same place (within `merge`).
std::vector<Cut> merge_cuts(std::vector<std::pair<double, std::string>> raw, double merge) {
  std::stable_sort(raw.begin(), raw.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
  std::vector<Cut> cuts;
  for (auto& [at, id] : raw) {
    if (!cuts.empty() && at - cuts.back().at < merge) {
      if (std::find(cuts.back().cutters.begin(), cuts.back().cutters.end(), id) == cuts.back().cutters.end())
        cuts.back().cutters.push_back(id);
    } else {
      cuts.push_back({at, {id}});
    }
  }
  return cuts;
}

bool uses_point(const SketchEntity& entity, const std::string& point_id) {
  for (const char* role : {"start", "end", "center", "major", "minor"}) {
    const Value* value = entity.data.find(role);
    if (value != nullptr && value->is_string() && value->as_string() == point_id)
      return true;
  }
  if (entity.kind == kBSplineKind) {
    for (const SketchPole& pole : entity.bspline().poles)
      if (pole.is_point() && pole.point_id == point_id)
        return true;
  }
  return false;
}

}  // namespace

// The editor: a solved working copy of the sketch, the ids that are taken, and the edits.  A friend of Sketch (it
// rewrites the document, which the functional API of Sketch cannot do).
class SketchEditor {
 public:
  // strict: a conflicting sketch has no geometry to cut (an inspection passes false and looks at what the solver left)
  explicit SketchEditor(const Sketch& source, bool strict = true) : work_(source.clone(false)) {
    SketchSolveRequest request;
    request.strict = strict;
    const SketchSolveResult solved = work_.solve(request);
    for (const auto& [id, point] : solved.solved_points)
      if (work_.entities_.contains(id))
        geo_.points[id] = point;
    for (auto& [id, entity] : work_.entities_) {
      taken_.insert(id);
      if (entity.kind == kPointKind) {
        const Pt p = geo_.points.at(id);
        entity.data.set("x", Value(p.first));
        entity.data.set("y", Value(p.second));
      } else if (entity.kind == kCircleKind) {
        const double r = solved.solved_scalars.at("circle:" + id + ":radius");
        geo_.radii[id] = r;
        entity.data.set("radius", Value(r));
      } else if (entity.kind == kBSplineKind) {
        std::vector<Pt>& poles = geo_.poles[id];
        const std::size_t count = entity.data.find("control_points")->as_array().size();
        for (std::size_t i = 0; i < count; ++i)
          poles.push_back(solved.solved_points.at("bspline:" + id + ":pole:" + std::to_string(i)));
      }
    }
    for (const SketchConstraint& constraint : work_.constraints_)
      taken_constraints_.insert(constraint.id);
  }

  // Where two non-construction lines, circles or arcs cross away from every point of the sketch: [{at: [x, y],
  // entities: [a, b]}], in entity order.  The same crossings trim cuts at; a crossing that is already a point is not
  // listed.
  Value crossings() const {
    std::vector<const SketchEntity*> curves;
    for (const auto& [id, entity] : work_.entities_)
      if (cutting(entity.kind) && !entity.construction)
        curves.push_back(&entity);
    Value::Array out;
    std::vector<Pt> seen;
    for (const auto& [id, p] : geo_.points)
      seen.push_back(p);
    const auto keep = [&](const Pt& p, const SketchEntity& a, const SketchEntity& b) {
      for (const Pt& q : seen)
        if (std::hypot(p.first - q.first, p.second - q.second) <= kTol * 10.0)
          return;
      seen.push_back(p);
      Value item = Value::object();
      item.set("at", Value(Value::Array{Value(p.first), Value(p.second)}));
      item.set("entities", Value(Value::Array{Value(a.id), Value(b.id)}));
      out.push_back(std::move(item));
    };
    for (std::size_t i = 0; i < curves.size(); ++i) {
      for (std::size_t j = i + 1; j < curves.size(); ++j) {
        const SketchEntity& a = *curves[i];
        const SketchEntity& b = *curves[j];
        if (!closed_form(a.kind) || !closed_form(b.kind)) {
          for (const Crossing2& hit : curve_hits(geo_, a, true, b))
            keep(hit.at, a, b);
          continue;
        }
        if (a.kind == kLineKind) {
          const Pt p1 = geo_.at(a, "start");
          const Pt p2 = geo_.at(a, "end");
          const double len = std::hypot(p2.first - p1.first, p2.second - p1.second);
          if (len < kTol)
            continue;
          for (const double t : line_params(geo_, a, b))
            if (t >= -kTol / len && t <= 1.0 + kTol / len)
              keep({p1.first + t * (p2.first - p1.first), p1.second + t * (p2.second - p1.second)}, a, b);
          continue;
        }
        const Circ circle = geo_.circle_of(a);
        if (circle.radius < kTol)
          continue;
        for (const double angle : angle_params(geo_, a, b)) {
          if (a.kind == kArcKind) {
            const auto [start, sweep] = geo_.arc_span(a);
            if (!on_arc(angle, start, sweep, kTol / circle.radius))
              continue;
          }
          keep({circle.center.first + circle.radius * std::cos(angle),
                circle.center.second + circle.radius * std::sin(angle)},
               a, b);
        }
      }
    }
    return Value(std::move(out));
  }

  Sketch trim(const SketchTarget& entity_target, const SketchPosition& at,
              const std::optional<std::vector<SketchTarget>>& against) {
    const SketchEntity subject = subject_of(entity_target, "trimmed");
    const Pt click = position_of(at);
    std::vector<SketchEntity> others = cutters(subject, against);
    const std::string& id = subject.id;
    Plan plan;

    if (subject.kind == kLineKind) {
      const Pt p1 = geo_.at(subject, "start");
      const Pt p2 = geo_.at(subject, "end");
      const double dx = p2.first - p1.first;
      const double dy = p2.second - p1.second;
      const double len = std::hypot(dx, dy);
      require_extent(id, len);
      const double t_at =
          std::clamp(((click.first - p1.first) * dx + (click.second - p1.second) * dy) / (len * len), 0.0, 1.0);
      std::vector<std::pair<double, std::string>> raw;
      for (const SketchEntity& other : others)
        for (const double t : line_params(geo_, subject, other))
          if (t * len > kTol && (1.0 - t) * len > kTol)
            raw.emplace_back(t, other.id);
      const std::vector<Cut> cuts = merge_cuts(raw, kTol / len);
      const Cut* before = nullptr;
      const Cut* after = nullptr;
      for (const Cut& cut : cuts) {
        if (cut.at <= t_at)
          before = &cut;
        else if (after == nullptr)
          after = &cut;
      }
      std::string before_point;
      std::string after_point;
      if (before != nullptr)
        before_point = point_at(plan, p1.first + before->at * dx, p1.second + before->at * dy);
      if (after != nullptr)
        after_point = point_at(plan, p1.first + after->at * dx, p1.second + after->at * dy);
      if (before == nullptr && after == nullptr)
        notes_.push_back(id + " had nothing crossing it: removed whole");
      if (before != nullptr)
        add_piece(plan, subject, kLineKind, subject.point_id("start"), before_point, {});
      if (after != nullptr)
        add_piece(plan, subject, kLineKind, after_point, subject.point_id("end"), {});
      if (before != nullptr)
        plan.ties.emplace_back(before_point, before->cutters);
      if (after != nullptr)
        plan.ties.emplace_back(after_point, after->cutters);
      for (const SketchConstraint& constraint : work_.constraints_)
        if (constraint.targets.size() == 1 && constraint.targets[0].entity_id == id &&
            (constraint.kind == "horizontal" || constraint.kind == "vertical"))
          plan.inherit.push_back(constraint.kind);
    } else if (subject.kind == kBSplineKind) {
      trim_spline(plan, subject, click, others);
    } else {
      trim_round(plan, subject, click, others);
    }
    commit(subject, plan);
    return finish("trim_rsketch");
  }

  Sketch extend(const SketchTarget& entity_target, const std::string& end, const std::optional<SketchTarget>& to) {
    if (end != "start" && end != "end")
      throw ValueError("end must be 'start' or 'end', got '" + end + "'");
    const SketchEntity subject = subject_of(entity_target, "extended");
    const std::string& id = subject.id;
    if (subject.kind != kLineKind && subject.kind != kBSplineKind)
      throw ValueError("'" + id + "' is a " + subject.kind + ": only a line or a B-spline can be extended");
    std::vector<SketchEntity> pool;
    if (to) {
      const std::string to_id = id_of(*to);
      const SketchEntity* target = work_.entities_.find(to_id);
      if (target == nullptr)
        throw ValueError("there is no entity '" + to_id + "' to extend to");
      if (to_id == id)
        throw ValueError("'" + id + "' cannot be extended to itself");
      if (!cutting(target->kind))
        throw ValueError("'" + to_id + "' is a " + target->kind +
                         ": an entity extends to a line, circle, arc, ellipse or B-spline");
      pool.push_back(*target);
    } else {
      pool = cutters(subject, std::nullopt);
    }
    const auto nothing_ahead = [&] {
      return ValueError("nothing is ahead of the " + end + " of '" + id + "'" +
                        (to ? " on '" + id_of(*to) + "'" : std::string()));
    };
    Pt reached;
    std::string cutter;
    std::optional<Spline2> reshaped;  // a B-spline's new shape
    if (subject.kind == kBSplineKind) {
      std::tie(reached, cutter, reshaped) = extend_spline(subject, end == "end", pool);
      if (cutter.empty())
        throw nothing_ahead();
    } else {
      const Pt p1 = geo_.at(subject, "start");
      const Pt p2 = geo_.at(subject, "end");
      const double dx = p2.first - p1.first;
      const double dy = p2.second - p1.second;
      const double len = std::hypot(dx, dy);
      require_extent(id, len);
      const bool forward = end == "end";
      std::optional<std::pair<double, std::string>> best;
      for (const SketchEntity& other : pool)
        for (const double t : line_params(geo_, subject, other)) {
          const bool ahead = forward ? (t - 1.0) * len > kTol : (-t) * len > kTol;
          if (!ahead)
            continue;
          if (!best || (forward ? t < best->first : t > best->first))
            best = {t, other.id};
        }
      if (!best)
        throw nothing_ahead();
      reached = {p1.first + best->first * dx, p1.second + best->first * dy};
      cutter = best->second;
    }
    const std::string moved = subject.point_id(end);
    for (const auto& [other_id, other] : work_.entities_)
      if (other_id != id && uses_point(other, moved))
        throw ValueError("the " + end + " of '" + id + "' (point '" + moved + "') is shared with '" + other_id +
                         "': extending it would move that entity too");
    SketchEntity& point = work_.entities_.at(moved);
    point.data.set("x", Value(reached.first));
    point.data.set("y", Value(reached.second));
    point.scalars.erase("x");  // the position now comes from the cutter, not from a parameter
    point.scalars.erase("y");
    geo_.points[moved] = reached;
    // dimensions that no longer hold (and, for a B-spline, its tangent at the moved end and a fix of its shape)
    const std::string at_key[2] = {"at_a", "at_b"};
    std::vector<SketchConstraint> kept;
    for (SketchConstraint& constraint : work_.constraints_) {
      bool stale = false;
      for (std::size_t i = 0; i < constraint.targets.size(); ++i) {
        const SketchRef& target = constraint.targets[i];
        if (constraint.kind == "length" && target.entity_id == id)
          stale = true;
        if ((constraint.value.has_value() || constraint.kind == "fix") && target_point(target) == moved)
          stale = true;
        if (reshaped && target.entity_id == id && constraint.kind == "fix")
          stale = true;
        if (reshaped && target.entity_id == id && constraint.kind == "tangent" && i < 2) {
          const Value* selector = constraint.metadata.find(at_key[i]);
          if (selector != nullptr && selector->is_string() && selector->as_string() == end)
            stale = true;
        }
      }
      if (stale)
        notes_.push_back("constraint '" + constraint.id + "' (" + constraint.kind +
                         ") no longer holds and was dropped");
      else
        kept.push_back(std::move(constraint));
    }
    work_.constraints_ = std::move(kept);
    if (reshaped)
      reshape_spline(subject, *reshaped);
    add_point_on(moved, {cutter});
    return finish("extend_rsketch");
  }

 private:
  // What a trim adds: new points, new pieces, the constraints the pieces get.
  struct Plan {
    std::vector<SketchEntity> points;
    std::vector<SketchEntity> pieces;
    std::vector<std::pair<std::string, std::vector<std::string>>> ties;  // (point, the entities that cut there)
    std::vector<std::string> inherit;                                    // horizontal / vertical, per line piece
    std::map<std::string, std::string> keeps_end;  // B-spline: "start" / "end" -> the piece that keeps that end
  };

  SketchEntity subject_of(const SketchTarget& target, const char* verb) const {
    const std::string id = id_of(target);
    const SketchEntity* entity = work_.entities_.find(id);
    if (entity == nullptr)
      throw ValueError("there is no entity '" + id + "' in the sketch");
    if (!trimmable(entity->kind))
      throw ValueError("'" + id + "' is a " + entity->kind + ": only lines, circles and arcs can be " + verb +
                       " (and B-splines)");
    return *entity;
  }

  Pt position_of(const SketchPosition& at) const {
    if (!at.is_point()) {
      const Pt xy = at.xy();
      if (!finite(xy.first) || !finite(xy.second))
        throw ValueError("at must be a finite point (x, y) in sketch coordinates");
      return xy;
    }
    const std::string id = id_of(at.point());
    const SketchEntity* point = work_.entities_.find(id);
    if (point == nullptr)
      throw ValueError("there is no point '" + id + "' in the sketch to use as 'at'");
    if (point->kind != kPointKind)
      throw ValueError("'" + id + "' is a " + point->kind + ", not a point: 'at' is a point id or (x, y)");
    return geo_.points.at(id);
  }

  std::vector<SketchEntity> cutters(const SketchEntity& subject,
                                    const std::optional<std::vector<SketchTarget>>& against) const {
    std::vector<SketchEntity> out;
    if (against) {
      std::set<std::string> seen;
      for (const SketchTarget& target : *against) {
        const std::string id = id_of(target);
        const SketchEntity* entity = work_.entities_.find(id);
        if (entity == nullptr)
          throw ValueError("against names '" + id + "', which is not an entity of the sketch");
        if (id == subject.id)
          throw ValueError("against names '" + id + "', the entity being cut");
        if (!cutting(entity->kind))
          throw ValueError("against names '" + id + "', a " + entity->kind +
                           ": only lines, circles, arcs, ellipses and B-splines cut");
        if (seen.insert(id).second)
          out.push_back(*entity);
      }
      return out;
    }
    for (const auto& [id, entity] : work_.entities_)
      if (id != subject.id && cutting(entity.kind) && !entity.construction)
        out.push_back(entity);
    return out;
  }

  static void require_extent(const std::string& id, double length) {
    if (length < kTol)
      throw ValueError("'" + id + "' has no length (its end points coincide), so it has no direction");
  }

  std::string free_id(const char* prefix) {
    for (int n = 1;; ++n) {
      std::string candidate = prefix + std::to_string(n);
      if (taken_.insert(candidate).second)
        return candidate;
    }
  }

  std::string free_constraint(const std::string& kind) {
    for (int n = 0;; ++n) {
      std::string candidate = "c_" + kind + "_" + std::to_string(n);
      if (taken_constraints_.insert(candidate).second)
        return candidate;
    }
  }

  // The id of a point at (x, y): an existing one when it is already there, else a new one.
  std::string point_at(Plan& plan, double x, double y) {
    for (const auto& [id, p] : geo_.points)
      if (std::hypot(p.first - x, p.second - y) < kTol)
        return id;
    SketchEntity point;
    point.id = free_id("p");
    point.kind = std::string(kPointKind);
    point.data.set("x", Value(x));
    point.data.set("y", Value(y));
    geo_.points[point.id] = {x, y};
    plan.points.push_back(point);
    return point.id;
  }

  void add_piece(Plan& plan, const SketchEntity& subject, std::string_view kind, const std::string& start,
                 const std::string& end, const std::string& center) {
    SketchEntity piece;
    piece.id = free_id(kind == kLineKind ? "l" : "a");
    piece.kind = std::string(kind);
    piece.construction = subject.construction;
    piece.data.set("start", start);
    piece.data.set("end", end);
    if (!center.empty())
      piece.data.set("center", center);
    plan.pieces.push_back(std::move(piece));
  }

  // The circle / arc half of trim.
  void trim_round(Plan& plan, const SketchEntity& subject, const Pt& click, const std::vector<SketchEntity>& others) {
    const std::string& id = subject.id;
    const Circ circle = geo_.circle_of(subject);
    const bool is_circle = subject.kind == kCircleKind;
    double start = 0.0;
    double sweep = kTwoPi;
    if (!is_circle)
      std::tie(start, sweep) = geo_.arc_span(subject);
    const double tol_angle = kTol / circle.radius;
    std::vector<std::pair<double, std::string>> raw;
    for (const SketchEntity& other : others)
      for (const double angle : angle_params(geo_, subject, other)) {
        const double rel = wrap(angle - start);
        if (is_circle || (rel > tol_angle && rel < sweep - tol_angle))
          raw.emplace_back(angle, other.id);
      }
    std::vector<Cut> cuts = merge_cuts(raw, tol_angle);
    if (is_circle && cuts.size() > 1 && cuts.front().at + kTwoPi - cuts.back().at < tol_angle) {
      // the first and the last cut are the same place across the seam at angle 0
      for (const std::string& cutter : cuts.back().cutters)
        cuts.front().cutters.push_back(cutter);
      cuts.pop_back();
    }
    const double at_angle = wrap(std::atan2(click.second - circle.center.second, click.first - circle.center.first));
    const std::string center = subject.point_id("center");
    const auto cut_point = [&](double angle) {
      return point_at(plan, circle.center.first + circle.radius * std::cos(angle),
                      circle.center.second + circle.radius * std::sin(angle));
    };
    // arcs to make: (from cut or null = the arc's own start, to cut or null = its own end)
    std::vector<std::pair<const Cut*, const Cut*>> make;
    if (is_circle) {
      if (cuts.empty()) {
        notes_.push_back(id + " had nothing crossing it: removed whole");
        return;
      }
      if (cuts.size() == 1)
        throw ValueError("'" + id + "' is crossed once: a circle needs two cuts to leave an arc");
      std::size_t holder = cuts.size() - 1;
      for (std::size_t i = 0; i < cuts.size(); ++i)
        if (cuts[i].at <= at_angle)
          holder = i;
      for (std::size_t i = 0; i < cuts.size(); ++i)
        if (i != holder)
          make.emplace_back(&cuts[i], &cuts[(i + 1) % cuts.size()]);
    } else {
      const Cut* before = nullptr;
      const Cut* after = nullptr;
      const double rel_at = wrap(at_angle - start);
      for (const Cut& cut : cuts) {
        if (wrap(cut.at - start) <= rel_at)
          before = &cut;
        else if (after == nullptr)
          after = &cut;
      }
      if (before == nullptr && after == nullptr) {
        notes_.push_back(id + " had nothing crossing it: removed whole");
        return;
      }
      if (before != nullptr)
        make.emplace_back(nullptr, before);
      if (after != nullptr)
        make.emplace_back(after, nullptr);
    }
    for (const auto& [from, to] : make) {
      const std::string a = from == nullptr ? subject.point_id("start") : cut_point(from->at);
      const std::string b = to == nullptr ? subject.point_id("end") : cut_point(to->at);
      add_piece(plan, subject, kArcKind, a, b, center);
      if (from != nullptr)
        plan.ties.emplace_back(a, from->cutters);
      if (to != nullptr)
        plan.ties.emplace_back(b, to->cutters);
    }
  }

  // ---- B-splines

  // The control point ids of `spline`, a new shape of (a part of) `original`: `start` and `end` first and last, and
  // in between an original control point where the pole has not moved (each at most once, see `taken`), else a new
  // point (appended to `new_points`).
  Value::Array pole_ids(std::vector<SketchEntity>& new_points, const SketchEntity& original, const Spline2& spline,
                        const std::string& start, const std::string& end, std::set<std::string>& taken) {
    const bool closed = original.point_id("start") == original.point_id("end");
    std::vector<std::string> candidates;
    for (const SketchPole& pole : original.bspline().poles) {
      const bool own_end = pole.point_id == original.point_id("start") || pole.point_id == original.point_id("end");
      if (pole.is_point() && (closed || !own_end))
        candidates.push_back(pole.point_id);
    }
    Value::Array out;
    for (std::size_t i = 0; i < spline.poles.size(); ++i) {
      std::string id;
      if (i == 0) {
        id = start;
      } else if (i + 1 == spline.poles.size()) {
        id = end;
      } else {
        const Pt& p = spline.poles[i];
        for (const std::string& candidate : candidates) {
          const Pt q = geo_.points.at(candidate);
          if (candidate != start && candidate != end && taken.count(candidate) == 0 &&
              std::hypot(p.first - q.first, p.second - q.second) < kTol) {
            id = candidate;
            break;
          }
        }
        if (id.empty()) {
          SketchEntity point;
          point.id = free_id("p");
          point.kind = std::string(kPointKind);
          point.data.set("x", Value(p.first));
          point.data.set("y", Value(p.second));
          geo_.points[point.id] = p;
          new_points.push_back(point);
          id = point.id;
        }
        taken.insert(id);
      }
      Value pole = Value::object();
      pole.set("point_id", id);
      out.push_back(std::move(pole));
    }
    return out;
  }

  static void set_spline_data(SketchEntity& entity, const std::string& start, const std::string& end,
                              Value::Array poles, const Spline2& spline) {
    entity.data.set("start", start);
    entity.data.set("end", end);
    entity.data.set("control_points", Value(std::move(poles)));
    entity.data.set("degree", spline.degree);
    Value::Array knots;
    for (const double knot : spline.knots)
      knots.emplace_back(knot);
    entity.data.set("knots", Value(std::move(knots)));
    Value::Array mults;
    for (const int mult : spline.multiplicities)
      mults.emplace_back(mult);
    entity.data.set("multiplicities", Value(std::move(mults)));
    if (spline.weights.empty()) {
      entity.data.set("weights", Value());
    } else {
      Value::Array weights;
      for (const double weight : spline.weights)
        weights.emplace_back(weight);
      entity.data.set("weights", Value(std::move(weights)));
    }
    entity.data.set("periodic", false);
  }

  void add_spline_piece(Plan& plan, const SketchEntity& subject, const SplineHandle& curve, const std::string& start,
                        const std::string& end, std::set<std::string>& taken) {
    const Spline2 spline = sketch_detail::spline2_of(curve);
    Value::Array poles = pole_ids(plan.points, subject, spline, start, end, taken);
    SketchEntity piece;
    piece.id = free_id("s");
    piece.kind = std::string(kBSplineKind);
    piece.construction = subject.construction;
    set_spline_data(piece, start, end, std::move(poles), spline);
    plan.pieces.push_back(std::move(piece));
  }

  // The B-spline half of trim.
  void trim_spline(Plan& plan, const SketchEntity& subject, const Pt& click, const std::vector<SketchEntity>& others) {
    const std::string& id = subject.id;
    const SplineHandle curve = geo_.spline(subject);
    const bool periodic = curve->IsPeriodic();
    const bool closed = periodic || subject.point_id("start") == subject.point_id("end");
    const double u0 = curve->FirstParameter();
    const double u1 = curve->LastParameter();
    const double period = u1 - u0;
    const double res = std::max(sketch_detail::parameter_resolution(curve, kTol), 1e-12);
    const Pt first = sketch_detail::value_at(curve, u0);
    const Pt last = sketch_detail::value_at(curve, u1);
    const auto apart = [](const Pt& a, const Pt& b) {
      return std::hypot(a.first - b.first, a.second - b.second) > kTol;
    };
    std::vector<std::pair<double, std::string>> raw;
    for (const SketchEntity& other : others)
      for (const Crossing2& hit : curve_hits(geo_, subject, true, other)) {
        if (closed)
          raw.emplace_back(u1 - hit.on_a <= res ? u0 : hit.on_a, other.id);  // the seam is u0
        else if (apart(hit.at, first) && apart(hit.at, last))
          raw.emplace_back(hit.on_a, other.id);
      }
    std::vector<Cut> cuts = merge_cuts(raw, res);
    if (closed && cuts.size() > 1 && cuts.front().at + period - cuts.back().at < res) {
      for (const std::string& cutter : cuts.back().cutters)
        cuts.front().cutters.push_back(cutter);
      cuts.pop_back();
    }
    const double u_at = sketch_detail::nearest_parameter(curve, click);
    const auto cut_point = [&](double u) {
      const Pt p = sketch_detail::value_at(curve, u);
      return point_at(plan, p.first, p.second);
    };
    std::set<std::string> taken;
    if (!closed) {
      const Cut* before = nullptr;
      const Cut* after = nullptr;
      for (const Cut& cut : cuts) {
        if (cut.at <= u_at)
          before = &cut;
        else if (after == nullptr)
          after = &cut;
      }
      if (before == nullptr && after == nullptr) {
        notes_.push_back(id + " had nothing crossing it: removed whole");
        return;
      }
      const std::string before_point = before != nullptr ? cut_point(before->at) : std::string();
      const std::string after_point = after != nullptr ? cut_point(after->at) : std::string();
      if (before != nullptr) {
        add_spline_piece(plan, subject, sketch_detail::segment2(curve, u0, before->at), subject.point_id("start"),
                         before_point, taken);
        plan.keeps_end["start"] = plan.pieces.back().id;
        plan.ties.emplace_back(before_point, before->cutters);
      }
      if (after != nullptr) {
        add_spline_piece(plan, subject, sketch_detail::segment2(curve, after->at, u1), after_point,
                         subject.point_id("end"), taken);
        plan.keeps_end["end"] = plan.pieces.back().id;
        plan.ties.emplace_back(after_point, after->cutters);
      }
      return;
    }
    if (cuts.empty()) {
      notes_.push_back(id + " had nothing crossing it: removed whole");
      return;
    }
    if (cuts.size() == 1)
      throw ValueError("'" + id + "' is crossed once: a closed B-spline needs two cuts to leave a piece");
    std::size_t holder = cuts.size() - 1;
    for (std::size_t i = 0; i < cuts.size(); ++i)
      if (cuts[i].at <= u_at)
        holder = i;
    std::vector<std::string> points;
    for (const Cut& cut : cuts)
      points.push_back(cut_point(cut.at));
    for (std::size_t i = 0; i < cuts.size(); ++i) {
      if (i == holder)
        continue;
      const std::size_t next = (i + 1) % cuts.size();
      const double a = cuts[i].at;
      const double b = cuts[next].at;
      SplineHandle piece;
      if (next != 0)
        piece = sketch_detail::segment2(curve, a, b);
      else if (periodic)
        piece = sketch_detail::segment2(curve, a, b + period);
      else if (b - u0 <= res)
        piece = sketch_detail::segment2(curve, a, u1);  // the last cut is on the seam
      else
        piece = sketch_detail::join2(sketch_detail::segment2(curve, a, u1), sketch_detail::segment2(curve, u0, b));
      add_spline_piece(plan, subject, piece, points[i], points[next], taken);
      plan.ties.emplace_back(points[i], cuts[i].cutters);
      plan.ties.emplace_back(points[next], cuts[next].cutters);
    }
  }

  // Extend a B-spline from its end (`at_end`) or start: (where it now ends, the entity it reaches, its new shape);
  // an empty entity id when nothing is ahead.
  std::tuple<Pt, std::string, std::optional<Spline2>> extend_spline(const SketchEntity& subject, bool at_end,
                                                                    const std::vector<SketchEntity>& pool) const {
    const std::string& id = subject.id;
    const SplineHandle curve = geo_.spline(subject);
    if (curve->IsPeriodic() || subject.point_id("start") == subject.point_id("end"))
      throw ValueError("'" + id + "' is a closed B-spline: it has no free end to extend");
    const double u_end = at_end ? curve->LastParameter() : curve->FirstParameter();
    gp_Pnt2d tip;
    gp_Vec2d tangent;
    curve->D1(u_end, tip, tangent);
    if (tangent.Magnitude() < 1e-12)
      throw ValueError("the " + std::string(at_end ? "end" : "start") + " of '" + id + "' has no direction");
    if (!at_end)
      tangent.Reverse();
    // where the end tangent meets the next entity: the extension is aimed there
    const opencascade::handle<Geom2d_Line> ray = new Geom2d_Line(tip, gp_Dir2d(tangent));
    std::optional<std::pair<double, std::string>> aim;
    for (const SketchEntity& other : pool)
      for (const Crossing2& hit : sketch_detail::intersect2(ray, geo_.curve(other, true), kTol))
        if (hit.on_a > kTol && (!aim || hit.on_a < aim->first))
          aim = {hit.on_a, other.id};
    if (!aim)
      return {Pt{}, std::string(), std::nullopt};
    const gp_Pnt2d target = tip.Translated(gp_Vec2d(gp_Dir2d(tangent)) * aim->first);
    const SplineHandle extended = sketch_detail::extend2(curve, at_end, {target.X(), target.Y()});
    // the original end on the extended curve, then the first crossing past it
    const double u_join = sketch_detail::nearest_parameter(extended, {tip.X(), tip.Y()});
    const double res = std::max(sketch_detail::parameter_resolution(extended, kTol), 1e-12);
    std::optional<std::pair<double, std::string>> hit_at;
    for (const SketchEntity& other : pool)
      for (const Crossing2& hit : sketch_detail::intersect2(extended, geo_.curve(other, true), kTol)) {
        const double ahead = at_end ? hit.on_a - u_join : u_join - hit.on_a;
        if (ahead > res && (!hit_at || ahead < (at_end ? hit_at->first - u_join : u_join - hit_at->first)))
          hit_at = {hit.on_a, other.id};
      }
    if (!hit_at)
      hit_at = {at_end ? extended->LastParameter() : extended->FirstParameter(), aim->second};
    const SplineHandle result = at_end ? sketch_detail::segment2(extended, extended->FirstParameter(), hit_at->first)
                                       : sketch_detail::segment2(extended, hit_at->first, extended->LastParameter());
    // a cubic Bezier chain stays one (the solver moves its poles and keeps end tangents only on such a chain)
    const SketchBSpline definition = subject.bspline();
    const std::vector<double> weights = definition.weights.value_or(std::vector<double>{});
    const bool bezier_chain =
        definition.degree == 3 && !definition.periodic &&
        std::all_of(weights.begin(), weights.end(), [](double w) { return std::abs(w - 1.0) <= 1e-12; }) &&
        std::all_of(definition.multiplicities.begin() + 1, definition.multiplicities.end() - 1,
                    [](int m) { return m == 3; });
    if (bezier_chain && result->Degree() == 3 && !result->IsRational())
      for (int i = 2; i < result->NbKnots(); ++i)
        result->IncreaseMultiplicity(i, 3);
    Spline2 shape = sketch_detail::spline2_of(result);
    return {at_end ? shape.poles.back() : shape.poles.front(), hit_at->second, std::move(shape)};
  }

  // Give the B-spline `subject` the shape `spline` (its end points keep their ids).
  void reshape_spline(const SketchEntity& subject, const Spline2& spline) {
    std::vector<SketchEntity> new_points;
    std::set<std::string> taken;
    const std::string start = subject.point_id("start");
    const std::string end = subject.point_id("end");
    Value::Array poles = pole_ids(new_points, subject, spline, start, end, taken);
    set_spline_data(work_.entities_.at(subject.id), start, end, std::move(poles), spline);
    OrderedMap<SketchEntity> rebuilt;
    for (auto& [entity_id, entity] : work_.entities_) {
      if (entity_id == subject.id)
        for (const SketchEntity& point : new_points)
          rebuilt.set(point.id, point);
      rebuilt.set(entity_id, std::move(entity));
    }
    work_.entities_ = std::move(rebuilt);
    drop_unused_poles(subject);
  }

  // The inner control points of `original` that no entity uses any more go, with the constraints on them.
  void drop_unused_poles(const SketchEntity& original) {
    if (original.kind != kBSplineKind)
      return;
    std::set<std::string> gone;
    for (const SketchPole& pole : original.bspline().poles) {
      if (!pole.is_point() || pole.point_id == original.point_id("start") ||
          pole.point_id == original.point_id("end") || !work_.entities_.contains(pole.point_id))
        continue;
      bool used = false;
      for (const auto& [entity_id, entity] : work_.entities_)
        used = used || uses_point(entity, pole.point_id);
      if (!used)
        gone.insert(pole.point_id);
    }
    if (gone.empty())
      return;
    std::vector<SketchConstraint> kept;
    for (SketchConstraint& constraint : work_.constraints_) {
      const bool names_gone = std::any_of(
          constraint.targets.begin(), constraint.targets.end(),
          [&](const SketchRef& t) { return gone.count(t.entity_id) != 0 || gone.count(target_point(t)) != 0; });
      if (!names_gone)
        kept.push_back(std::move(constraint));
    }
    work_.constraints_ = std::move(kept);
    OrderedMap<SketchEntity> pruned;
    for (auto& [entity_id, entity] : work_.entities_)
      if (gone.count(entity_id) == 0)
        pruned.set(entity_id, std::move(entity));
    work_.entities_ = std::move(pruned);
  }

  // The point a constraint target designates ("" when it is not a point).
  std::string target_point(const SketchRef& ref) const {
    if (ref.kind != kPointKind)
      return {};
    const SketchEntity* entity = work_.entities_.find(ref.entity_id);
    if (entity == nullptr)
      return {};
    if (entity->kind == kPointKind)
      return entity->id;
    return entity->data.find(ref.subentity) != nullptr ? entity->point_id(ref.subentity) : std::string();
  }

  // point_on(point, cutter) for the first cutter, unless the point already is an end of one of them or is tied to it.
  void add_point_on(const std::string& point, const std::vector<std::string>& cutter_ids) {
    for (const std::string& id : cutter_ids)
      if (uses_point(work_.entities_.at(id), point))
        return;
    for (const SketchConstraint& constraint : work_.constraints_)
      if (constraint.kind == "point_on" && constraint.targets.size() == 2 &&
          target_point(constraint.targets[0]) == point &&
          std::find(cutter_ids.begin(), cutter_ids.end(), constraint.targets[1].entity_id) != cutter_ids.end())
        return;
    const std::string& cutter = cutter_ids.front();
    const SketchEntity& entity = work_.entities_.at(cutter);
    work_.add_constraint("point_on",
                         {SketchRef{work_.sketch_id(), point, std::string(kPointKind), "geometry"},
                          SketchRef{work_.sketch_id(), cutter, entity.kind, "geometry"}},
                         std::nullopt, free_constraint("point_on"));
  }

  // Replace the subject by the plan, move the constraints, and drop the points nothing uses any more.
  void commit(const SketchEntity& subject, const Plan& plan) {
    const std::string& id = subject.id;
    // constraints on <entity>.start|end|center stay on the point; the ones naming the entity itself go
    std::vector<SketchConstraint> kept;
    for (SketchConstraint& constraint : work_.constraints_) {
      for (SketchRef& target : constraint.targets)
        if (target.kind == kPointKind && target.entity_id == id && target.subentity != "geometry" &&
            subject.data.find(target.subentity) != nullptr)
          target = SketchRef{target.sketch_id, subject.point_id(target.subentity), std::string(kPointKind), "geometry"};
      if (constraint.kind == "tangent" && !plan.keeps_end.empty())
        carry_tangent(constraint, id, plan.keeps_end);
      const bool names_subject = std::any_of(constraint.targets.begin(), constraint.targets.end(),
                                             [&](const SketchRef& t) { return t.entity_id == id; });
      if (!names_subject)
        kept.push_back(std::move(constraint));
    }
    work_.constraints_ = std::move(kept);

    OrderedMap<SketchEntity> rebuilt;
    for (auto& [entity_id, entity] : work_.entities_) {
      if (entity_id != id) {
        rebuilt.set(entity_id, std::move(entity));
        continue;
      }
      for (const SketchEntity& point : plan.points)
        rebuilt.set(point.id, point);
      for (const SketchEntity& piece : plan.pieces)
        rebuilt.set(piece.id, piece);
    }
    work_.entities_ = std::move(rebuilt);

    for (const SketchEntity& piece : plan.pieces)
      for (const std::string& kind : plan.inherit)
        if (piece.kind == kLineKind)
          work_.add_constraint(kind, {SketchRef{work_.sketch_id(), piece.id, std::string(kLineKind), "geometry"}},
                               std::nullopt, free_constraint(kind));
    for (const auto& [point, cutter_ids] : plan.ties)
      add_point_on(point, cutter_ids);

    // points only the removed entity used (and no constraint names) would be orphans left behind by this edit
    std::set<std::string> used;
    for (const auto& [entity_id, entity] : work_.entities_) {
      for (const char* role : {"start", "end", "center", "major", "minor"})
        if (const Value* value = entity.data.find(role); value != nullptr && value->is_string())
          used.insert(value->as_string());
      if (entity.kind == kBSplineKind)
        for (const SketchPole& pole : entity.bspline().poles)
          if (pole.is_point())
            used.insert(pole.point_id);
    }
    for (const SketchConstraint& constraint : work_.constraints_)
      for (const SketchRef& target : constraint.targets) {
        used.insert(target.entity_id);
        if (const std::string point = target_point(target); !point.empty())
          used.insert(point);
      }
    std::set<std::string> was_used_by_subject;
    for (const char* role : {"start", "end", "center"})
      if (const Value* value = subject.data.find(role); value != nullptr && value->is_string())
        was_used_by_subject.insert(value->as_string());
    OrderedMap<SketchEntity> pruned;
    for (auto& [entity_id, entity] : work_.entities_) {
      const bool orphan =
          entity.kind == kPointKind && used.count(entity_id) == 0 && was_used_by_subject.count(entity_id) != 0;
      if (!orphan)
        pruned.set(entity_id, std::move(entity));
    }
    work_.entities_ = std::move(pruned);
    drop_unused_poles(subject);
  }

  // A tangent at an end of the cut B-spline (at_a / at_b) moves to the piece that keeps that end.
  static void carry_tangent(SketchConstraint& constraint, const std::string& id,
                            const std::map<std::string, std::string>& keeps_end) {
    const char* keys[2] = {"at_a", "at_b"};
    std::vector<SketchRef> targets = constraint.targets;
    for (std::size_t i = 0; i < targets.size() && i < 2; ++i) {
      if (targets[i].entity_id != id)
        continue;
      const Value* selector = constraint.metadata.find(keys[i]);
      if (selector == nullptr || !selector->is_string())
        return;
      const auto piece = keeps_end.find(selector->as_string());
      if (piece == keeps_end.end())
        return;
      targets[i].entity_id = piece->second;
    }
    constraint.targets = std::move(targets);
  }

  Sketch finish(const char* operation) {
    Value notes = Value(Value::Array{});
    for (const std::string& note : notes_)
      notes.as_array().emplace_back(note);
    Value edit = Value::object();
    edit.set("operation", operation);
    edit.set("notes", notes);
    work_.metadata().set("last_edit", edit);
    work_.clear_solve_result();
    return std::move(work_);
  }

  Sketch work_;
  Geometry geo_;
  std::set<std::string> taken_;
  std::set<std::string> taken_constraints_;
  std::vector<std::string> notes_;
};

// ---- the operators
// ------------------------------------------------------------------------------------------------------

Sketch trim_rsketch(const Sketch& sketch, const SketchTarget& entity, const SketchPosition& at,
                    const std::optional<std::vector<SketchTarget>>& against) {
  static const ErrorSpec kSpec{
      "trim_rsketch",
      "Failed to trim the sketch entity.",
      {"The entity id does not exist, or is not a line, circle or arc.",
       "'at' is not a finite point (x, y) or the id of a point of the sketch.",
       "The sketch constraints are conflicting, so there is no geometry to cut.",
       "A circle is crossed only once: it needs two cuts to leave an arc.",
       "'against' names an entity that does not exist or cannot cut."},
      {"Pass an existing line / circle / arc id and a point (x, y) on the part to remove.",
       "Inspect the sketch with inspect_sketch_rsketchresult(..., strict=False) and fix the constraints first.",
       "Use against=[...] to name the entities that cut, or add the missing crossing entity."}};
  return guarded(kSpec, [&] {
    Sketch updated = SketchEditor(sketch).trim(entity, at, against);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("entity", id_of(entity));
    if (at.is_point())
      params.set("at", id_of(at.point()));
    else
      params.set("at", Value(Value::Array{Value(at.xy().first), Value(at.xy().second)}));
    if (against) {
      Value::Array ids;
      for (const SketchTarget& target : *against)
        ids.emplace_back(id_of(target));
      params.set("against", Value(std::move(ids)));
    } else {
      params.set("against", Value());
    }
    finalize_sketch_object("trim_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

Sketch extend_rsketch(const Sketch& sketch, const SketchTarget& entity, const std::string& end,
                      const std::optional<SketchTarget>& to) {
  static const ErrorSpec kSpec{
      "extend_rsketch",
      "Failed to extend the sketch line.",
      {"The entity id does not exist or is not a line.", "'end' is not 'start' or 'end'.",
       "Nothing (or not the entity named by 'to') lies ahead of that end of the line.",
       "The end point is shared with another entity, which would move too.",
       "The sketch constraints are conflicting, so there is no geometry to extend."},
      {"Pass an existing line id and end='start' or end='end'.",
       "Name the target with to=<id>, or draw the entity the line should reach.",
       "Split the shared point first (give the line its own end point) or extend the other entity instead."}};
  return guarded(kSpec, [&] {
    Sketch updated = SketchEditor(sketch).extend(entity, end, to);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("entity", id_of(entity));
    params.set("end", end);
    params.set("to", to ? Value(id_of(*to)) : Value());
    finalize_sketch_object("extend_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

Value SketchDiff::to_value() const {
  const auto list = [](const std::vector<std::string>& ids) {
    Value::Array out;
    for (const std::string& id : ids)
      out.emplace_back(id);
    return Value(std::move(out));
  };
  Value out = Value::object();
  out.set("created", list(created));
  out.set("removed", list(removed));
  out.set("changed", list(changed));
  out.set("created_constraints", list(created_constraints));
  out.set("removed_constraints", list(removed_constraints));
  out.set("changed_constraints", list(changed_constraints));
  return out;
}

Value inspect_sketch_rsketchcrossings(const Sketch& sketch) {
  static const ErrorSpec kSpec{"inspect_sketch_rsketchcrossings",
                               "Failed to list where the sketch's curves cross.",
                               {"An argument is not a Sketch."},
                               {"Pass a sketch; a conflicting one is solved as far as it goes (strict=False)."}};
  return guarded(kSpec, [&] { return SketchEditor(sketch, /*strict=*/false).crossings(); });
}

SketchDiff diff_sketch_rsketchdiff(const Sketch& before, const Sketch& after) {
  static const ErrorSpec kSpec{"diff_sketch_rsketchdiff",
                               "Failed to compare the two sketches.",
                               {"An argument is not a Sketch."},
                               {"Pass the sketch before and the sketch after an edit."}};
  return guarded(kSpec, [&] {
    SketchDiff diff;
    for (const auto& [id, entity] : after.entities()) {
      const SketchEntity* old = before.entities().find(id);
      if (old == nullptr)
        diff.created.push_back(id);
      else if (!(old->to_value() == entity.to_value()))
        diff.changed.push_back(id);
    }
    for (const auto& [id, entity] : before.entities())
      if (!after.entities().contains(id))
        diff.removed.push_back(id);
    std::map<std::string, Value> old_constraints;
    for (const SketchConstraint& constraint : before.constraints())
      old_constraints.emplace(constraint.id, constraint.to_value());
    std::set<std::string> now;
    for (const SketchConstraint& constraint : after.constraints()) {
      now.insert(constraint.id);
      const auto old = old_constraints.find(constraint.id);
      if (old == old_constraints.end())
        diff.created_constraints.push_back(constraint.id);
      else if (!(old->second == constraint.to_value()))
        diff.changed_constraints.push_back(constraint.id);
    }
    for (const SketchConstraint& constraint : before.constraints())
      if (now.count(constraint.id) == 0)
        diff.removed_constraints.push_back(constraint.id);
    return diff;
  });
}

}  // namespace scad
