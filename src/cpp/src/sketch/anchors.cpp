// insert_spline_anchor_rsketch, remove_spline_anchor_rsketch and convert_spline_to_anchors_rsketch: edit a B-spline in
// its anchor form.
//
// The anchor form is how a pen tool draws a curve: anchors on the curve, each with an in-handle and an out-handle.  It
// is a cubic B-spline whose control points are [A0, out0, in1, A1, out1, in2, A2, ...] and whose inner knots have
// multiplicity 3 (clamped ends, unit weights): every span is a cubic Bezier from one anchor to the next, and the sketch
// solver moves every control point of such a spline (solver/model.cpp, is_bezier_chain).  Moving an anchor or a handle
// is moving a point; these operations change the structure.  Like trim and extend they work on the solved geometry.
//
// Inserting splits the span under `at` with de Casteljau's construction at the parameter of the nearest curve point, so
// the curve does not change: the two handles of that span get shorter (they keep their ids) and the new anchor gets new
// points for itself and its two handles.  Removing merges the two spans beside an anchor into one: the outer handles
// keep their directions and get the lengths that fit the old two-span curve best (least squares on samples), so a
// removal undoes an insertion exactly.  Converting writes an open, non-periodic B-spline in this form: exactly for
// degree <= 3 without weights (degree elevation and knot insertion), else as an approximation.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <map>
#include <set>

#include <Geom2dConvert_ApproxCurve.hxx>
#include <Geom2d_BSplineCurve.hxx>

#include "edit_curves.hpp"
#include "finalize.hpp"
#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

namespace scad {

namespace {

using sketch_detail::finalize_sketch_object;
using sketch_detail::Spline2;
using SplineHandle = opencascade::handle<Geom2d_BSplineCurve>;
using Pt = SketchPoint2;

// Two positions closer than this (sketch units) are the same place.
constexpr double kTol = 1e-6;
// How closely convert_spline_to_anchors_rsketch follows a curve it cannot write exactly (sketch units).
constexpr double kApproxTol = 1e-4;
// A merged handle is never shorter than this share of its old length: a fit that wants it reversed keeps it pointing
// the way it did (the tangent at the neighbouring anchor stays).
constexpr double kShortestHandle = 0.05;
constexpr int kFitSamples = 64;

std::string id_of(const SketchTarget& target) {
  return target.is_ref() ? target.ref().entity_id : target.path();
}

std::string number_text(double value) {
  char buffer[32];
  std::snprintf(buffer, sizeof buffer, "%.6g", value);
  return buffer;
}

Pt lerp(const Pt& a, const Pt& b, double t) {
  return {a.first + (b.first - a.first) * t, a.second + (b.second - a.second) * t};
}

double distance(const Pt& a, const Pt& b) {
  return std::hypot(a.first - b.first, a.second - b.second);
}

bool unit_weights(const SketchBSpline& spline) {
  if (!spline.weights)
    return true;
  return std::all_of(spline.weights->begin(), spline.weights->end(),
                     [](double w) { return std::abs(w - 1.0) <= 1e-12; });
}

// The anchor form (see the top of the file), every control point being a sketch point.
bool anchor_form(const SketchBSpline& spline) {
  if (spline.periodic || spline.degree != 3 || !unit_weights(spline))
    return false;
  const std::vector<int>& mult = spline.multiplicities;
  if (mult.size() < 2 || mult.front() != 4 || mult.back() != 4)
    return false;
  for (std::size_t i = 1; i + 1 < mult.size(); ++i)
    if (mult[i] != 3)
      return false;
  if (spline.poles.size() != 3 * (mult.size() - 1) + 1)
    return false;
  return std::all_of(spline.poles.begin(), spline.poles.end(), [](const SketchPole& pole) { return pole.is_point(); });
}

}  // namespace

// The editor of a B-spline's anchors: a solved working copy of the sketch and the ids that are taken.  A friend of
// Sketch (it rewrites the document, which the functional API of Sketch cannot do).
class SketchAnchors {
 public:
  explicit SketchAnchors(const Sketch& source) : work_(source.clone(false)) {
    SketchSolveRequest request;  // strict: a conflicting sketch has no geometry to edit
    const SketchSolveResult solved = work_.solve(request);
    for (const auto& [id, point] : solved.solved_points)
      if (work_.entities_.contains(id))
        points_[id] = point;
    for (auto& [id, entity] : work_.entities_) {
      taken_.insert(id);
      if (entity.kind == kPointKind) {
        const Pt p = points_.at(id);
        entity.data.set("x", Value(p.first));
        entity.data.set("y", Value(p.second));
      } else if (entity.kind == kCircleKind) {
        entity.data.set("radius", Value(solved.solved_scalars.at("circle:" + id + ":radius")));
      } else if (entity.kind == kBSplineKind) {
        std::vector<Pt>& poles = poles_[id];
        const std::size_t count = entity.data.find("control_points")->as_array().size();
        for (std::size_t i = 0; i < count; ++i)
          poles.push_back(solved.solved_points.at("bspline:" + id + ":pole:" + std::to_string(i)));
      }
    }
  }

  Sketch insert(const SketchTarget& spline_target, const SketchPosition& at) {
    const SketchEntity subject = anchor_spline(spline_target);
    const SketchBSpline definition = subject.bspline();
    const std::vector<Pt>& poles = poles_.at(subject.id);
    std::vector<std::string> ids = pole_ids(definition);
    const Pt click = position_of(at);
    Spline2 shape;
    shape.poles = poles;
    shape.knots = definition.knots;
    shape.multiplicities = definition.multiplicities;
    const double u = sketch_detail::nearest_parameter(sketch_detail::make_spline2(shape), click);
    const std::vector<double>& knots = definition.knots;
    std::size_t span = 0;
    while (span + 2 < knots.size() && u >= knots[span + 1])
      ++span;
    const double t = (u - knots[span]) / (knots[span + 1] - knots[span]);
    const std::size_t first = 3 * span;
    const Pt& p0 = poles[first];
    const Pt& p1 = poles[first + 1];
    const Pt& p2 = poles[first + 2];
    const Pt& p3 = poles[first + 3];
    // de Casteljau: the span from p0 to p3 is the span p0 a d m followed by the span m e c p3
    const Pt a = lerp(p0, p1, t);
    const Pt b = lerp(p1, p2, t);
    const Pt c = lerp(p2, p3, t);
    const Pt d = lerp(a, b, t);
    const Pt e = lerp(b, c, t);
    const Pt m = lerp(d, e, t);
    if (distance(m, p0) < kTol || distance(m, p3) < kTol)
      throw ValueError("'" + subject.id + "' already has an anchor there ('" +
                       ids[distance(m, p0) < kTol ? first : first + 3] + "'): pick a place between two anchors");

    std::vector<SketchEntity> made;
    // The span's handles get shorter.  A handle another entity or another pole shares cannot move without moving that
    // too: the spline takes a new point there instead.
    const auto shorten = [&](std::size_t index, const Pt& to) {
      if (shared(ids[index], subject, ids))
        ids[index] = new_point(to, made);
      else
        move_point(ids[index], to);
    };
    shorten(first + 1, a);
    shorten(first + 2, c);
    const std::string in = new_point(d, made);
    const std::string anchor = new_point(m, made);
    const std::string out = new_point(e, made);
    ids.insert(ids.begin() + static_cast<std::ptrdiff_t>(first + 2), {in, anchor, out});
    std::vector<double> new_knots = knots;
    std::vector<int> mults = definition.multiplicities;
    new_knots.insert(new_knots.begin() + static_cast<std::ptrdiff_t>(span + 1), u);
    mults.insert(mults.begin() + static_cast<std::ptrdiff_t>(span + 1), 3);
    write(subject, ids, new_knots, mults, made);
    notes_.push_back("anchor '" + anchor + "' (handles '" + in + "' and '" + out + "') inserted in '" + subject.id +
                     "' between '" + ids[first] + "' and '" + ids[first + 6] + "'");
    return finish("insert_spline_anchor_rsketch");
  }

  Sketch remove(const SketchTarget& spline_target, const SketchTarget& anchor_target) {
    const SketchEntity subject = anchor_spline(spline_target);
    const SketchBSpline definition = subject.bspline();
    const std::vector<Pt>& poles = poles_.at(subject.id);
    std::vector<std::string> ids = pole_ids(definition);
    const std::string anchor = id_of(anchor_target);
    const std::size_t last = ids.size() - 1;
    std::size_t j = 0;
    for (std::size_t i = 3; i < last; i += 3)
      if (ids[i] == anchor)
        j = i;
    if (j == 0) {
      if (anchor == ids.front() || anchor == ids.back())
        throw ValueError("'" + anchor + "' is an end of '" + subject.id +
                         "': an end anchor cannot be removed (trim the spline, or delete it)");
      for (std::size_t i = 0; i <= last; ++i)
        if (i % 3 != 0 && ids[i] == anchor)
          throw ValueError("'" + anchor + "' is a handle of '" + subject.id +
                           "', not an anchor: remove an anchor (a point on the curve)");
      std::string inner;
      for (std::size_t i = 3; i < last; i += 3)
        inner += (inner.empty() ? "'" : ", '") + ids[i] + "'";
      throw ValueError("'" + anchor + "' is not an anchor of '" + subject.id + "'" +
                       (inner.empty() ? std::string(": it has only its two end anchors")
                                      : " (the anchors that can be removed: " + inner + ")"));
    }
    const std::size_t span = j / 3;  // the spans span - 1 and span become one
    const std::vector<double>& knots = definition.knots;
    const Pt& a0 = poles[j - 3];
    const Pt& a3 = poles[j + 3];
    const Pt d0{poles[j - 2].first - a0.first, poles[j - 2].second - a0.second};
    const Pt d1{poles[j + 2].first - a3.first, poles[j + 2].second - a3.second};
    // The handles' new lengths (as multiples of the old ones): least squares between the merged span and samples of the
    // two spans, over the same parameter range.  A zero-length handle, or one something else holds, stays as it is.
    Spline2 shape;
    shape.poles = poles;
    shape.knots = knots;
    shape.multiplicities = definition.multiplicities;
    const SplineHandle curve = sketch_detail::make_spline2(shape);
    const bool free0 = std::hypot(d0.first, d0.second) > kTol && !held(ids[j - 2], subject, ids);
    const bool free1 = std::hypot(d1.first, d1.second) > kTol && !held(ids[j + 2], subject, ids);
    double m11 = 0.0, m12 = 0.0, m22 = 0.0, v1 = 0.0, v2 = 0.0;
    for (int i = 0; i <= kFitSamples; ++i) {
      const double t = static_cast<double>(i) / kFitSamples;
      const Pt s = sketch_detail::value_at(curve, knots[span - 1] + t * (knots[span + 1] - knots[span - 1]));
      const double b0 = (1 - t) * (1 - t) * (1 - t);
      const double b1 = 3 * (1 - t) * (1 - t) * t;
      const double b2 = 3 * (1 - t) * t * t;
      const double b3 = t * t * t;
      const Pt r{s.first - a0.first * (b0 + b1) - a3.first * (b2 + b3),
                 s.second - a0.second * (b0 + b1) - a3.second * (b2 + b3)};
      const double dot01 = d0.first * d1.first + d0.second * d1.second;
      m11 += b1 * b1 * (d0.first * d0.first + d0.second * d0.second);
      m12 += b1 * b2 * dot01;
      m22 += b2 * b2 * (d1.first * d1.first + d1.second * d1.second);
      v1 += b1 * (d0.first * r.first + d0.second * r.second);
      v2 += b2 * (d1.first * r.first + d1.second * r.second);
    }
    double alpha = 1.0;
    double beta = 1.0;
    const auto fit_alpha = [&] { alpha = std::max((v1 - m12 * beta) / m11, kShortestHandle); };
    const auto fit_beta = [&] { beta = std::max((v2 - m12 * alpha) / m22, kShortestHandle); };
    const double det = m11 * m22 - m12 * m12;
    if (free0 && free1 && std::abs(det) > 1e-12 * std::max(m11 * m22, 1e-300)) {
      alpha = (v1 * m22 - v2 * m12) / det;
      beta = (m11 * v2 - m12 * v1) / det;
      if (alpha < kShortestHandle) {
        alpha = kShortestHandle;
        fit_beta();
      } else if (beta < kShortestHandle) {
        beta = kShortestHandle;
        fit_alpha();
      }
    } else {
      if (free0)
        fit_alpha();
      if (free1)
        fit_beta();
    }
    if (free0)
      move_point(ids[j - 2], {a0.first + alpha * d0.first, a0.second + alpha * d0.second});
    if (free1)
      move_point(ids[j + 2], {a3.first + beta * d1.first, a3.second + beta * d1.second});

    const std::vector<std::string> gone{ids[j - 1], ids[j], ids[j + 1]};
    ids.erase(ids.begin() + static_cast<std::ptrdiff_t>(j - 1), ids.begin() + static_cast<std::ptrdiff_t>(j + 2));
    std::vector<double> new_knots = knots;
    std::vector<int> mults = definition.multiplicities;
    new_knots.erase(new_knots.begin() + static_cast<std::ptrdiff_t>(span));
    mults.erase(mults.begin() + static_cast<std::ptrdiff_t>(span));
    write(subject, ids, new_knots, mults, {});
    drop_unused(gone, subject);
    return finish("remove_spline_anchor_rsketch");
  }

  Sketch convert(const SketchTarget& spline_target) {
    const SketchEntity subject = spline_entity(spline_target);
    const SketchBSpline definition = subject.bspline();
    if (anchor_form(definition)) {
      notes_.push_back("'" + subject.id + "' is already in anchor form: nothing changed");
      return finish("convert_spline_to_anchors_rsketch");
    }
    if (definition.periodic)
      throw ValueError("'" + subject.id +
                       "' is periodic: only an open B-spline (or one that starts and ends on one point) has an "
                       "anchor form");
    Spline2 shape;
    shape.degree = definition.degree;
    shape.poles = poles_.at(subject.id);
    shape.knots = definition.knots;
    shape.multiplicities = definition.multiplicities;
    if (!unit_weights(definition))
      shape.weights = *definition.weights;
    SplineHandle curve = sketch_detail::make_spline2(shape);
    if (curve->Degree() > 3 || curve->IsRational()) {
      Geom2dConvert_ApproxCurve approx(curve, kApproxTol, GeomAbs_C1, 400, 3);
      if (!approx.HasResult())
        throw ValueError("'" + subject.id + "' could not be approximated by cubic spans within " +
                         number_text(kApproxTol));
      curve = approx.Curve();
      notes_.push_back(
          "'" + subject.id + "' (" +
          (definition.degree > 3 ? "degree " + std::to_string(definition.degree) : std::string("rational")) +
          ") has no exact anchor form: it was approximated (largest deviation " + number_text(approx.MaxError()) + ")");
    }
    if (curve->Degree() < 3)
      curve->IncreaseDegree(3);
    for (int i = 2; i < curve->NbKnots(); ++i)
      curve->IncreaseMultiplicity(i, 3);
    const Spline2 result = sketch_detail::spline2_of(curve);

    // The ends keep their points; an inner control point that did not move keeps its id, the others are new points.
    std::vector<std::string> originals = pole_ids(definition);
    std::set<std::string> reused;
    std::vector<SketchEntity> made;
    std::vector<std::string> ids;
    const std::string start = subject.point_id("start");
    const std::string end = subject.point_id("end");
    for (std::size_t i = 0; i < result.poles.size(); ++i) {
      if (i == 0 || i + 1 == result.poles.size()) {
        ids.push_back(i == 0 ? start : end);
        continue;
      }
      std::string id;
      for (const std::string& candidate : originals)
        if (!candidate.empty() && candidate != start && candidate != end && reused.count(candidate) == 0 &&
            distance(points_.at(candidate), result.poles[i]) < kTol) {
          id = candidate;
          break;
        }
      if (id.empty())
        id = new_point(result.poles[i], made);
      reused.insert(id);
      ids.push_back(id);
    }
    write(subject, ids, result.knots, result.multiplicities, made);
    drop_unused(originals, subject);
    return finish("convert_spline_to_anchors_rsketch");
  }

 private:
  SketchEntity spline_entity(const SketchTarget& target) const {
    const std::string id = id_of(target);
    const SketchEntity* entity = work_.entities_.find(id);
    if (entity == nullptr)
      throw ValueError("there is no entity '" + id + "' in the sketch");
    if (entity->kind != kBSplineKind)
      throw ValueError("'" + id + "' is a " + entity->kind + ", not a B-spline");
    return *entity;
  }

  SketchEntity anchor_spline(const SketchTarget& target) const {
    SketchEntity entity = spline_entity(target);
    if (!anchor_form(entity.bspline()))
      throw ValueError("'" + entity.id +
                       "' is not in anchor form (a cubic B-spline of Bezier spans: inner knots of multiplicity 3, "
                       "every control point a sketch point): convert it first with "
                       "convert_spline_to_anchors_rsketch");
    return entity;
  }

  // The point id of every control point ("" for a literal pole).
  static std::vector<std::string> pole_ids(const SketchBSpline& spline) {
    std::vector<std::string> out;
    for (const SketchPole& pole : spline.poles)
      out.push_back(pole.point_id);
    return out;
  }

  Pt position_of(const SketchPosition& at) const {
    if (!at.is_point()) {
      const Pt xy = at.xy();
      if (!std::isfinite(xy.first) || !std::isfinite(xy.second))
        throw ValueError("at must be a finite point (x, y) in sketch coordinates");
      return xy;
    }
    const std::string id = id_of(at.point());
    const SketchEntity* point = work_.entities_.find(id);
    if (point == nullptr || point->kind != kPointKind)
      throw ValueError("'" + id + "' is not a point of the sketch: 'at' is a point id or (x, y)");
    return points_.at(id);
  }

  bool used_by_other(const std::string& point, const SketchEntity& subject) const {
    for (const auto& [id, entity] : work_.entities_) {
      if (id == subject.id || entity.kind == kPointKind)
        continue;
      for (const char* role : {"start", "end", "center", "major", "minor"})
        if (const Value* value = entity.data.find(role);
            value != nullptr && value->is_string() && value->as_string() == point)
          return true;
      if (entity.kind == kBSplineKind)
        for (const SketchPole& pole : entity.bspline().poles)
          if (pole.point_id == point)
            return true;
    }
    return false;
  }

  // Another entity uses the point, or it is more than one pole of this spline.
  bool shared(const std::string& point, const SketchEntity& subject, const std::vector<std::string>& ids) const {
    return used_by_other(point, subject) || std::count(ids.begin(), ids.end(), point) > 1;
  }

  // As shared, or a constraint names the point: it is not ours to move.
  bool held(const std::string& point, const SketchEntity& subject, const std::vector<std::string>& ids) const {
    if (shared(point, subject, ids))
      return true;
    return std::any_of(work_.constraints_.begin(), work_.constraints_.end(),
                       [&](const SketchConstraint& constraint) { return names(constraint, point); });
  }

  // Whether a constraint names the point (by its id, or as <entity>.start|end|...).
  bool names(const SketchConstraint& constraint, const std::string& point) const {
    for (const SketchRef& target : constraint.targets) {
      if (target.entity_id == point)
        return true;
      if (target.kind != kPointKind || target.subentity == "geometry")
        continue;
      const SketchEntity* entity = work_.entities_.find(target.entity_id);
      if (entity != nullptr && entity->kind != kPointKind)
        if (const Value* value = entity->data.find(target.subentity);
            value != nullptr && value->is_string() && value->as_string() == point)
          return true;
    }
    return false;
  }

  std::string new_point(const Pt& at, std::vector<SketchEntity>& made) {
    SketchEntity point;
    for (int n = 1;; ++n) {
      point.id = "p" + std::to_string(n);
      if (taken_.insert(point.id).second)
        break;
    }
    point.kind = std::string(kPointKind);
    point.data.set("x", Value(at.first));
    point.data.set("y", Value(at.second));
    points_[point.id] = at;
    made.push_back(point);
    return point.id;
  }

  // Move a control point the edit reshapes: a dimension or fix on it no longer holds and is dropped.
  void move_point(const std::string& id, const Pt& to) {
    SketchEntity& point = work_.entities_.at(id);
    point.data.set("x", Value(to.first));
    point.data.set("y", Value(to.second));
    point.scalars.erase("x");  // the position now comes from the edit, not from a parameter
    point.scalars.erase("y");
    points_[id] = to;
    drop_constraints({id}, "moved");
  }

  // Remove the constraints that name one of `points`, each with a note.
  void drop_constraints(const std::set<std::string>& points, const char* why) {
    std::vector<SketchConstraint> kept;
    for (SketchConstraint& constraint : work_.constraints_) {
      const auto named = std::find_if(points.begin(), points.end(),
                                      [&](const std::string& point) { return names(constraint, point); });
      if (named == points.end()) {
        kept.push_back(std::move(constraint));
        continue;
      }
      notes_.push_back("constraint '" + constraint.id + "' (" + constraint.kind + ") on point '" + *named +
                       "', which " + why + ", was dropped");
    }
    work_.constraints_ = std::move(kept);
  }

  // Give the spline the control points `ids` and the knots; the new points go just before it.
  void write(const SketchEntity& subject, const std::vector<std::string>& ids, const std::vector<double>& knots,
             const std::vector<int>& mults, const std::vector<SketchEntity>& made) {
    SketchEntity& entity = work_.entities_.at(subject.id);
    Value::Array poles;
    for (const std::string& id : ids) {
      Value pole = Value::object();
      pole.set("point_id", id);
      poles.push_back(std::move(pole));
    }
    entity.data.set("control_points", Value(std::move(poles)));
    entity.data.set("degree", 3);
    Value::Array knot_values;
    for (const double knot : knots)
      knot_values.emplace_back(knot);
    entity.data.set("knots", Value(std::move(knot_values)));
    Value::Array mult_values;
    for (const int mult : mults)
      mult_values.emplace_back(mult);
    entity.data.set("multiplicities", Value(std::move(mult_values)));
    entity.data.set("weights", Value());
    entity.data.set("periodic", false);
    if (made.empty())
      return;
    OrderedMap<SketchEntity> rebuilt;
    for (auto& [id, item] : work_.entities_) {
      if (id == subject.id)
        for (const SketchEntity& point : made)
          rebuilt.set(point.id, point);
      rebuilt.set(id, std::move(item));
    }
    work_.entities_ = std::move(rebuilt);
  }

  // The points of `candidates` that no entity uses any more go, with the constraints that name them.
  void drop_unused(const std::vector<std::string>& candidates, const SketchEntity& subject) {
    const SketchBSpline now = work_.entities_.at(subject.id).bspline();
    std::set<std::string> gone;
    for (const std::string& id : candidates) {
      if (id.empty() || !work_.entities_.contains(id) || used_by_other(id, subject) ||
          std::any_of(now.poles.begin(), now.poles.end(), [&](const SketchPole& pole) { return pole.point_id == id; }))
        continue;
      gone.insert(id);
    }
    if (gone.empty())
      return;
    drop_constraints(gone, "is no longer on the spline");
    OrderedMap<SketchEntity> pruned;
    for (auto& [id, entity] : work_.entities_)
      if (gone.count(id) == 0)
        pruned.set(id, std::move(entity));
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
  std::map<std::string, Pt, std::less<>> points_;
  std::map<std::string, std::vector<Pt>, std::less<>> poles_;  // B-splines: the solved control points
  std::set<std::string> taken_;
  std::vector<std::string> notes_;
};

// ---- the operators
// ------------------------------------------------------------------------------------------------------

namespace {

Value position_param(const SketchPosition& at) {
  if (at.is_point())
    return Value(id_of(at.point()));
  return Value(Value::Array{Value(at.xy().first), Value(at.xy().second)});
}

}  // namespace

Sketch insert_spline_anchor_rsketch(const Sketch& sketch, const SketchTarget& spline, const SketchPosition& at) {
  static const ErrorSpec kSpec{
      "insert_spline_anchor_rsketch",
      "Failed to insert an anchor into the sketch B-spline.",
      {"The spline id does not exist or is not a B-spline.",
       "The B-spline is not in anchor form (cubic Bezier spans: inner knots of multiplicity 3).",
       "'at' is not a finite point (x, y) or the id of a point of the sketch.",
       "The nearest place on the curve already is an anchor.",
       "The sketch constraints are conflicting, so there is no geometry to edit."},
      {"Pass the id of a B-spline and a point (x, y) on or near the curve, between two anchors.",
       "Convert a control-point B-spline first with convert_spline_to_anchors_rsketch.",
       "Inspect the sketch with inspect_sketch_rsketchresult(..., strict=False) and fix the constraints first."}};
  return guarded(kSpec, [&] {
    Sketch updated = SketchAnchors(sketch).insert(spline, at);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("spline", id_of(spline));
    params.set("at", position_param(at));
    finalize_sketch_object("insert_spline_anchor_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

Sketch remove_spline_anchor_rsketch(const Sketch& sketch, const SketchTarget& spline, const SketchTarget& anchor) {
  static const ErrorSpec kSpec{
      "remove_spline_anchor_rsketch",
      "Failed to remove an anchor from the sketch B-spline.",
      {"The spline id does not exist or is not a B-spline.",
       "The B-spline is not in anchor form (cubic Bezier spans: inner knots of multiplicity 3).",
       "The anchor is an end of the spline, a handle, or not a point of the spline.",
       "The sketch constraints are conflicting, so there is no geometry to edit."},
      {"Pass the id of a B-spline and the point id of one of its inner anchors.",
       "Convert a control-point B-spline first with convert_spline_to_anchors_rsketch.",
       "Inspect the sketch with inspect_sketch_rsketchresult(..., strict=False) and fix the constraints first."}};
  return guarded(kSpec, [&] {
    Sketch updated = SketchAnchors(sketch).remove(spline, anchor);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("spline", id_of(spline));
    params.set("anchor", id_of(anchor));
    finalize_sketch_object("remove_spline_anchor_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

Sketch convert_spline_to_anchors_rsketch(const Sketch& sketch, const SketchTarget& spline) {
  static const ErrorSpec kSpec{
      "convert_spline_to_anchors_rsketch",
      "Failed to convert the sketch B-spline to anchor form.",
      {"The spline id does not exist or is not a B-spline.", "The B-spline is periodic.",
       "The sketch constraints are conflicting, so there is no geometry to convert."},
      {"Pass the id of an open B-spline (or one that starts and ends on one point).",
       "Inspect the sketch with inspect_sketch_rsketchresult(..., strict=False) and fix the constraints first."}};
  return guarded(kSpec, [&] {
    Sketch updated = SketchAnchors(sketch).convert(spline);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("spline", id_of(spline));
    finalize_sketch_object("convert_spline_to_anchors_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

}  // namespace scad
