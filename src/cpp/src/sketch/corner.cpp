// fillet_corner_rsketch and chamfer_corner_rsketch: round or cut the corner where two lines meet.
//
// Both work on the *solved* geometry (the sketch is solved first, strictly), like trim and extend.  The two lines must
// share an end point, the corner.  Each line is shortened to the point where the arc (or chamfer) leaves it, the corner
// point goes away unless something else uses it, and the new geometry is defined by constraints so a re-solve keeps it:
// a fillet gets a tangent constraint with each line and a driving radius, a chamfer a driving length and a driving
// angle.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <map>
#include <set>

#include "finalize.hpp"
#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"
#include "scad/sketch/operators.hpp"

namespace scad {

namespace {

using sketch_detail::finalize_sketch_object;

constexpr double kTol = 1e-6;
using Pt = SketchPoint2;

std::string id_of(const SketchTarget& target) {
  return target.is_ref() ? target.ref().entity_id : target.path();
}

std::string number_text(double value) {
  char buffer[32];
  std::snprintf(buffer, sizeof buffer, "%.6g", value);
  return buffer;
}

// Constraints that name a line (as a whole) and still hold when the line gets shorter: they speak of its direction or
// of the infinite line it lies on.
bool holds_for_shorter_line(const std::string& kind) {
  static const std::set<std::string> kinds{"horizontal", "vertical", "parallel",      "perpendicular",
                                           "collinear",  "angle",    "line_distance", "tangent",
                                           "normal",     "point_on", "symmetric",     "mirror"};
  return kinds.count(kind) != 0;
}

// The two lines of a corner and what the corner is made of.
struct Corner {
  SketchEntity a, b;
  std::string role_a, role_b;  // "start" | "end": the end of each line that is the corner
  std::string point;           // the shared point
  Pt p, far_a, far_b;          // corner, the other end of a, the other end of b
  double len_a = 0.0, len_b = 0.0;
  double cos_angle = 0.0;  // between the two lines, seen from the corner
  double sin_angle = 0.0;
  Pt dir_a, dir_b;  // unit vectors from the corner along a and b
};

}  // namespace

class SketchCorner {
 public:
  explicit SketchCorner(const Sketch& source) : work_(source.clone(false)) {
    SketchSolveRequest request;  // strict: a conflicting sketch has no geometry to round
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
      }
    }
    for (const SketchConstraint& constraint : work_.constraints_)
      taken_constraints_.insert(constraint.id);
  }

  Sketch fillet(const SketchTarget& a, const SketchTarget& b, double radius, const Scalar& radius_value) {
    if (!std::isfinite(radius) || radius <= 0.0)
      throw ValueError("radius must be a finite number greater than zero, got " + number_text(radius));
    const Corner corner = locate(a, b);
    const double half_tan = corner.sin_angle / (1.0 + corner.cos_angle);  // tan(angle / 2)
    const double shorter = std::min(corner.len_a, corner.len_b);
    const double tangent = radius / half_tan;  // distance from the corner to the tangent points
    if (tangent > shorter - kTol) {
      const bool a_shorter = corner.len_a <= corner.len_b;
      throw ValueError("radius " + number_text(radius) + " is too large for the corner of '" + corner.a.id + "' and '" +
                       corner.b.id + "': the shorter line ('" + (a_shorter ? corner.a.id : corner.b.id) + "', length " +
                       number_text(shorter) + ") allows a radius of at most " + number_text(shorter * half_tan) +
                       " at this corner angle");
    }
    const double half_sin = std::sqrt((1.0 - corner.cos_angle) / 2.0);  // sin(angle / 2)
    const Pt bisector = unit({corner.dir_a.first + corner.dir_b.first, corner.dir_a.second + corner.dir_b.second});
    const double reach = radius / half_sin;
    const Pt center{corner.p.first + bisector.first * reach, corner.p.second + bisector.second * reach};
    const Pt ta = along(corner.p, corner.dir_a, tangent);
    const Pt tb = along(corner.p, corner.dir_b, tangent);

    Plan plan;
    plan.ta = new_point(plan, ta);
    plan.tb = new_point(plan, tb);
    const std::string center_id = new_point(plan, center);
    // the arc runs counter-clockwise from its start to its end
    const double turn = (ta.first - center.first) * (tb.second - center.second) -
                        (ta.second - center.second) * (tb.first - center.first);
    const bool a_first = turn > 0.0;
    SketchEntity arc;
    arc.id = free_id("a");
    arc.kind = std::string(kArcKind);
    arc.construction = corner.a.construction && corner.b.construction;
    arc.data.set("start", a_first ? plan.ta : plan.tb);
    arc.data.set("end", a_first ? plan.tb : plan.ta);
    arc.data.set("center", center_id);
    plan.curve = arc;
    apply(corner, plan);

    const auto ref = [&](const std::string& id, std::string_view kind) {
      return SketchRef{work_.sketch_id(), id, std::string(kind), "geometry"};
    };
    const auto tangent_to = [&](const std::string& line, const char* end) {
      Value metadata = Value::object();
      metadata.set("at_a", Value());
      metadata.set("at_b", std::string(end));
      metadata.set("mode", "external");
      work_.add_constraint("tangent", {ref(line, kLineKind), ref(arc.id, kArcKind)}, std::nullopt,
                           free_constraint("tangent"), true, std::move(metadata));
    };
    tangent_to(corner.a.id, a_first ? "start" : "end");
    tangent_to(corner.b.id, a_first ? "end" : "start");
    work_.add_constraint("radius", {ref(arc.id, kArcKind)}, radius_value, free_constraint("radius"));
    return finish("fillet_corner_rsketch");
  }

  Sketch chamfer(const SketchTarget& a, const SketchTarget& b, double distance) {
    if (!std::isfinite(distance) || distance <= 0.0)
      throw ValueError("distance must be a finite number greater than zero, got " + number_text(distance));
    const Corner corner = locate(a, b);
    const double shorter = std::min(corner.len_a, corner.len_b);
    if (distance > shorter - kTol) {
      const bool a_shorter = corner.len_a <= corner.len_b;
      throw ValueError("distance " + number_text(distance) + " is too large for the corner of '" + corner.a.id +
                       "' and '" + corner.b.id + "': the shorter line ('" + (a_shorter ? corner.a.id : corner.b.id) +
                       "', length " + number_text(shorter) + ") allows a distance of less than " +
                       number_text(shorter));
    }
    const Pt ta = along(corner.p, corner.dir_a, distance);
    const Pt tb = along(corner.p, corner.dir_b, distance);
    Plan plan;
    plan.ta = new_point(plan, ta);
    plan.tb = new_point(plan, tb);
    SketchEntity line;
    line.id = free_id("l");
    line.kind = std::string(kLineKind);
    line.construction = corner.a.construction && corner.b.construction;
    line.data.set("start", plan.ta);
    line.data.set("end", plan.tb);
    plan.curve = line;
    apply(corner, plan);

    // the chamfer is as long as the chord of the cut and makes the angle it has with the line a: with the lines'
    // own constraints that defines it
    const double chord = std::hypot(tb.first - ta.first, tb.second - ta.second);
    const Pt a_dir = unit({corner.far_a.first - corner.p.first, corner.far_a.second - corner.p.second});
    const bool a_toward_corner = corner.role_a == "end";  // the line a runs start -> end
    const Pt a_vector = a_toward_corner ? Pt{-a_dir.first, -a_dir.second} : a_dir;
    const Pt c_vector = unit({tb.first - ta.first, tb.second - ta.second});
    const double cosine = std::clamp(a_vector.first * c_vector.first + a_vector.second * c_vector.second, -1.0, 1.0);
    const double degrees = std::acos(cosine) * 180.0 / kPi;
    const auto ref = [&](const std::string& id) {
      return SketchRef{work_.sketch_id(), id, std::string(kLineKind), "geometry"};
    };
    work_.add_constraint("length", {ref(line.id)}, Scalar(chord), free_constraint("length"));
    work_.add_constraint("angle", {ref(corner.a.id), ref(line.id)}, Scalar(degrees), free_constraint("angle"));
    return finish("chamfer_corner_rsketch");
  }

 private:
  struct Plan {
    std::vector<SketchEntity> points;
    std::string ta, tb;  // the new end points of a and b
    SketchEntity curve;  // the arc / the chamfer line
  };

  static Pt unit(const Pt& v) {
    const double n = std::hypot(v.first, v.second);
    return {v.first / n, v.second / n};
  }

  static Pt along(const Pt& from, const Pt& dir, double distance) {
    return {from.first + dir.first * distance, from.second + dir.second * distance};
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

  std::string new_point(Plan& plan, const Pt& at) {
    SketchEntity point;
    point.id = free_id("p");
    point.kind = std::string(kPointKind);
    point.data.set("x", Value(at.first));
    point.data.set("y", Value(at.second));
    points_[point.id] = at;
    plan.points.push_back(point);
    return point.id;
  }

  const SketchEntity& line_of(const SketchTarget& target, const char* which) const {
    const std::string id = id_of(target);
    const SketchEntity* entity = work_.entities_.find(id);
    if (entity == nullptr)
      throw ValueError("there is no entity '" + id + "' in the sketch (" + which + ")");
    if (entity->kind != kLineKind)
      throw ValueError("'" + id + "' is a " + entity->kind + ": a corner is made of two lines");
    return *entity;
  }

  Corner locate(const SketchTarget& a_target, const SketchTarget& b_target) const {
    Corner corner;
    corner.a = line_of(a_target, "a");
    corner.b = line_of(b_target, "b");
    if (corner.a.id == corner.b.id)
      throw ValueError("a and b are both '" + corner.a.id + "': a corner is made of two different lines");
    bool found = false;
    for (const char* ra : {"start", "end"}) {
      for (const char* rb : {"start", "end"}) {
        if (!found && corner.a.point_id(ra) == corner.b.point_id(rb)) {
          found = true;
          corner.role_a = ra;
          corner.role_b = rb;
          corner.point = corner.a.point_id(ra);
        }
      }
    }
    if (!found)
      throw ValueError("'" + corner.a.id + "' and '" + corner.b.id + "' do not share an end point (their ends are " +
                       corner.a.point_id("start") + ", " + corner.a.point_id("end") + " and " +
                       corner.b.point_id("start") + ", " + corner.b.point_id("end") +
                       "): a corner is where two lines meet at one point");
    corner.p = points_.at(corner.point);
    corner.far_a = points_.at(corner.a.point_id(corner.role_a == "start" ? "end" : "start"));
    corner.far_b = points_.at(corner.b.point_id(corner.role_b == "start" ? "end" : "start"));
    const Pt va{corner.far_a.first - corner.p.first, corner.far_a.second - corner.p.second};
    const Pt vb{corner.far_b.first - corner.p.first, corner.far_b.second - corner.p.second};
    corner.len_a = std::hypot(va.first, va.second);
    corner.len_b = std::hypot(vb.first, vb.second);
    if (corner.len_a < kTol || corner.len_b < kTol)
      throw ValueError("'" + (corner.len_a < kTol ? corner.a.id : corner.b.id) +
                       "' has no length (its end points coincide), so it has no direction");
    corner.dir_a = unit(va);
    corner.dir_b = unit(vb);
    corner.cos_angle = corner.dir_a.first * corner.dir_b.first + corner.dir_a.second * corner.dir_b.second;
    corner.sin_angle = std::abs(corner.dir_a.first * corner.dir_b.second - corner.dir_a.second * corner.dir_b.first);
    if (corner.sin_angle < 1e-9)
      throw ValueError("'" + corner.a.id + "' and '" + corner.b.id + "' are parallel (they leave the corner '" +
                       corner.point + "' " + (corner.cos_angle > 0.0 ? "the same way" : "in opposite directions") +
                       "): there is no corner to round");
    return corner;
  }

  // False for a constraint that names `line` as a whole and does not hold once the line is shorter.
  static bool keeps_line(const SketchConstraint& constraint, const std::string& line) {
    for (const SketchRef& target : constraint.targets)
      if (target.entity_id == line && target.kind != kPointKind)
        return holds_for_shorter_line(constraint.kind);
    return true;
  }

  // Put the plan in the document: the new end points of the lines, the new entities, the constraints that move.
  void apply(const Corner& corner, const Plan& plan) {
    work_.entities_.at(corner.a.id).data.set(corner.role_a, plan.ta);
    work_.entities_.at(corner.b.id).data.set(corner.role_b, plan.tb);

    // constraints on <line>.<corner end> stay on the corner point; constraints that name a line and no longer hold go
    std::vector<SketchConstraint> kept;
    for (SketchConstraint& constraint : work_.constraints_) {
      for (SketchRef& target : constraint.targets) {
        const bool on_a = target.entity_id == corner.a.id && target.subentity == corner.role_a;
        const bool on_b = target.entity_id == corner.b.id && target.subentity == corner.role_b;
        if (target.kind == kPointKind && (on_a || on_b))
          target = SketchRef{target.sketch_id, corner.point, std::string(kPointKind), "geometry"};
      }
      const bool holds = keeps_line(constraint, corner.a.id) && keeps_line(constraint, corner.b.id);
      if (holds) {
        kept.push_back(std::move(constraint));
      } else {
        notes_.push_back("constraint '" + constraint.id + "' (" + constraint.kind +
                         ") no longer holds and was dropped");
      }
    }
    work_.constraints_ = std::move(kept);

    // does anything still use the corner point?
    bool used = false;
    for (const auto& [id, entity] : work_.entities_)
      for (const char* role : {"start", "end", "center", "major", "minor"})
        if (const Value* value = entity.data.find(role);
            value != nullptr && value->is_string() && value->as_string() == corner.point)
          used = true;
    for (const SketchConstraint& constraint : work_.constraints_)
      for (const SketchRef& target : constraint.targets)
        if (target.entity_id == corner.point)
          used = true;

    // new entities go right after the later of the two lines
    std::size_t later = 0;
    std::size_t index = 0;
    for (const auto& [id, entity] : work_.entities_) {
      if (id == corner.a.id || id == corner.b.id)
        later = index;
      ++index;
    }
    OrderedMap<SketchEntity> rebuilt;
    index = 0;
    for (auto& [id, entity] : work_.entities_) {
      if (id == corner.point && !used) {
        ++index;
        continue;
      }
      rebuilt.set(id, std::move(entity));
      if (index == later) {
        for (const SketchEntity& point : plan.points)
          rebuilt.set(point.id, point);
        rebuilt.set(plan.curve.id, plan.curve);
      }
      ++index;
    }
    work_.entities_ = std::move(rebuilt);

    if (!used)
      return;
    // The corner stays (something is constrained to it), so the lines keep the place they had: a construction line from
    // the corner to each new end, collinear with its line, is the part of the line that was cut off.
    notes_.push_back("point '" + corner.point +
                     "' is still used by constraints and was kept as the sharp corner; the cut-off " +
                     "parts of the lines stay as construction lines");
    OrderedMap<SketchEntity> with_legs;
    for (auto& [id, entity] : work_.entities_) {
      with_legs.set(id, std::move(entity));
      if (id == plan.curve.id) {
        for (const auto& [line, end] : {std::pair{corner.a.id, plan.ta}, std::pair{corner.b.id, plan.tb}}) {
          SketchEntity leg;
          leg.id = free_id("l");
          leg.kind = std::string(kLineKind);
          leg.construction = true;
          leg.data.set("start", corner.point);
          leg.data.set("end", end);
          with_legs.set(leg.id, leg);
          legs_.emplace_back(line, leg.id);
        }
      }
    }
    work_.entities_ = std::move(with_legs);
    for (const auto& [line, leg] : legs_)
      work_.add_constraint("collinear",
                           {SketchRef{work_.sketch_id(), line, std::string(kLineKind), "geometry"},
                            SketchRef{work_.sketch_id(), leg, std::string(kLineKind), "geometry"}},
                           std::nullopt, free_constraint("collinear"));
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
  std::set<std::string> taken_;
  std::set<std::string> taken_constraints_;
  std::vector<std::string> notes_;
  std::vector<std::pair<std::string, std::string>> legs_;
};

// ---- the operators
// ------------------------------------------------------------------------------------------------------

Sketch fillet_corner_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b, const Scalar& radius) {
  static const ErrorSpec kSpec{
      "fillet_corner_rsketch",
      "Failed to fillet the sketch corner.",
      {"a or b does not exist, or is not a line.", "The two lines do not share an end point.",
       "The lines are parallel, so there is no corner.",
       "The radius is not a positive number, or is too large for the shorter line.",
       "The sketch constraints are conflicting, so there is no geometry to round."},
      {"Pass the ids of two lines that meet at a shared point (build them from the same point id).",
       "Use a radius below the maximum named in the message, or lengthen the shorter line.",
       "Inspect the sketch with inspect_sketch_rsketchresult(..., strict=False) and fix the constraints first."}};
  return guarded(kSpec, [&] {
    Sketch updated = SketchCorner(sketch).fillet(a, b, as_float(radius), radius);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("a", id_of(a));
    params.set("b", id_of(b));
    params.set("radius", as_float(radius));
    sketch_detail::SymbolicArgs symbolic;
    if (radius.symbolic())
      symbolic.emplace_back("radius", radius);
    finalize_sketch_object("fillet_corner_rsketch", std::move(params), std::move(symbolic), updated, &sketch);
    return updated;
  });
}

Sketch chamfer_corner_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                              const Scalar& distance) {
  static const ErrorSpec kSpec{
      "chamfer_corner_rsketch",
      "Failed to chamfer the sketch corner.",
      {"a or b does not exist, or is not a line.", "The two lines do not share an end point.",
       "The lines are parallel, so there is no corner.",
       "The distance is not a positive number, or is not shorter than the shorter line.",
       "The sketch constraints are conflicting, so there is no geometry to cut."},
      {"Pass the ids of two lines that meet at a shared point (build them from the same point id).",
       "Use a distance below the length of the shorter line.",
       "Inspect the sketch with inspect_sketch_rsketchresult(..., strict=False) and fix the constraints first."}};
  return guarded(kSpec, [&] {
    Sketch updated = SketchCorner(sketch).chamfer(a, b, as_float(distance));
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("a", id_of(a));
    params.set("b", id_of(b));
    params.set("distance", as_float(distance));
    sketch_detail::SymbolicArgs symbolic;
    if (distance.symbolic())
      symbolic.emplace_back("distance", distance);
    finalize_sketch_object("chamfer_corner_rsketch", std::move(params), std::move(symbolic), updated, &sketch);
    return updated;
  });
}

}  // namespace scad
