// trim_rsketch, extend_rsketch and diff_sketch_rsketchdiff.
//
// Both edits work on the *solved* geometry: the sketch is solved first, every point is moved to where the solver put
// it, and the cuts are computed on those coordinates.  Lines, circles and arcs are the entities that can be cut or
// extended and that can cut; ellipses and B-splines are neither (they are skipped as cutters and refused as subjects).
// An arc runs counter-clockwise from `start` to `end` around `center`.
#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <tuple>

#include "finalize.hpp"
#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"
#include "scad/sketch/operators.hpp"

namespace scad {

namespace {

using sketch_detail::finalize_sketch_object;

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

bool curve_kind(const std::string& kind) {
  return kind == kLineKind || kind == kCircleKind || kind == kArcKind;
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
};

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
  if (b.kind == kLineKind) {
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
  explicit SketchEditor(const Sketch& source) : work_(source.clone(false)) {
    SketchSolveRequest request;  // strict: a conflicting sketch has no geometry to cut
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
      }
    }
    for (const SketchConstraint& constraint : work_.constraints_)
      taken_constraints_.insert(constraint.id);
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
    if (subject.kind != kLineKind)
      throw ValueError("'" + id + "' is a " + subject.kind + ": only a line can be extended");
    std::vector<SketchEntity> pool;
    if (to) {
      const std::string to_id = id_of(*to);
      const SketchEntity* target = work_.entities_.find(to_id);
      if (target == nullptr)
        throw ValueError("there is no entity '" + to_id + "' to extend to");
      if (to_id == id)
        throw ValueError("'" + id + "' cannot be extended to itself");
      if (!curve_kind(target->kind))
        throw ValueError("'" + to_id + "' is a " + target->kind + ": a line extends to a line, circle or arc");
      pool.push_back(*target);
    } else {
      pool = cutters(subject, std::nullopt);
    }
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
      throw ValueError("nothing is ahead of the " + end + " of '" + id + "'" +
                       (to ? " on '" + id_of(*to) + "'" : std::string()));
    const std::string moved = subject.point_id(end);
    for (const auto& [other_id, other] : work_.entities_)
      if (other_id != id && uses_point(other, moved))
        throw ValueError("the " + end + " of '" + id + "' (point '" + moved + "') is shared with '" + other_id +
                         "': extending it would move that entity too");
    const double t = best->first;
    SketchEntity& point = work_.entities_.at(moved);
    point.data.set("x", Value(p1.first + t * dx));
    point.data.set("y", Value(p1.second + t * dy));
    point.scalars.erase("x");  // the position now comes from the cutter, not from a parameter
    point.scalars.erase("y");
    // dimensions that no longer hold
    std::vector<SketchConstraint> kept;
    for (SketchConstraint& constraint : work_.constraints_) {
      bool stale = false;
      for (const SketchRef& target : constraint.targets) {
        if (constraint.kind == "length" && target.entity_id == id)
          stale = true;
        if ((constraint.value.has_value() || constraint.kind == "fix") && target_point(target) == moved)
          stale = true;
      }
      if (stale)
        notes_.push_back("constraint '" + constraint.id + "' (" + constraint.kind +
                         ") no longer holds and was dropped");
      else
        kept.push_back(std::move(constraint));
    }
    work_.constraints_ = std::move(kept);
    add_point_on(moved, {best->second});
    return finish("extend_rsketch");
  }

 private:
  // What a trim adds: new points, new pieces, the constraints the pieces get.
  struct Plan {
    std::vector<SketchEntity> points;
    std::vector<SketchEntity> pieces;
    std::vector<std::pair<std::string, std::vector<std::string>>> ties;  // (point, the entities that cut there)
    std::vector<std::string> inherit;                                    // horizontal / vertical, per line piece
  };

  SketchEntity subject_of(const SketchTarget& target, const char* verb) const {
    const std::string id = id_of(target);
    const SketchEntity* entity = work_.entities_.find(id);
    if (entity == nullptr)
      throw ValueError("there is no entity '" + id + "' in the sketch");
    if (!curve_kind(entity->kind))
      throw ValueError("'" + id + "' is a " + entity->kind + ": only lines, circles and arcs can be " + verb);
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
        if (!curve_kind(entity->kind))
          throw ValueError("against names '" + id + "', a " + entity->kind + ": only lines, circles and arcs cut");
        if (seen.insert(id).second)
          out.push_back(*entity);
      }
      return out;
    }
    for (const auto& [id, entity] : work_.entities_)
      if (id != subject.id && curve_kind(entity.kind) && !entity.construction)
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
    for (const auto& [entity_id, entity] : work_.entities_)
      for (const char* role : {"start", "end", "center", "major", "minor"})
        if (const Value* value = entity.data.find(role); value != nullptr && value->is_string())
          used.insert(value->as_string());
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
