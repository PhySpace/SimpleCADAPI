#include "model.hpp"

#include <algorithm>
#include <cmath>

#include "scad/core/error.hpp"

namespace scad::sketch_solver {

namespace {

// A B-spline is a cubic Bezier chain for the solver when the control polygon
// *is* the Bezier polygon: cubic, non-periodic, unit weights, clamped ends
// (multiplicity 4) and C0 interior knots (multiplicity 3).
bool is_bezier_chain(const SketchBSpline& spline) {
  if (spline.periodic || spline.degree != 3) return false;
  if (spline.weights) {
    for (const double w : *spline.weights) {
      if (std::abs(w - 1.0) > 1e-12) return false;
    }
  }
  const auto& mult = spline.multiplicities;
  if (mult.size() < 2 || mult.front() != 4 || mult.back() != 4) return false;
  for (std::size_t i = 1; i + 1 < mult.size(); ++i) {
    if (mult[i] != 3) return false;
  }
  return (spline.poles.size() - 1) % 3 == 0;
}

}  // namespace

Model::Model(const Sketch& s) : sketch(s) {
  create_parameters();
  for (const SketchConstraint& constraint : sketch.constraints()) {
    if (constraint.driving && constraint.kind == "fix") apply_fix(target(constraint, 0));
  }
  add_arc_rules();
  for (const SketchConstraint& constraint : sketch.constraints()) {
    if (!constraint.driving) {
      measurements.push_back(&constraint);
    } else if (constraint.kind != "fix") {
      lower(constraint);
    }
  }
  system.finalize();
}

void Model::create_parameters() {
  for (const auto& [id, entity] : sketch.entities()) {
    if (entity.kind == kPointKind) {
      points.emplace(id, system.params.add_point(entity.number("x"), entity.number("y")));
    }
  }
  for (const auto& [id, entity] : sketch.entities()) {
    if (entity.kind == kPointKind || entity.kind == kLineKind || entity.kind == kArcKind ||
        entity.kind == kEllipseKind) {
      continue;
    }
    if (entity.kind == kCircleKind) {
      radius_params.emplace(id, system.params.add(entity.number("radius")));
    } else if (entity.kind == kBSplineKind) {
      create_spline(entity);
    } else {
      throw ValueError("Unsupported sketch entity kind '" + entity.kind + "'");
    }
  }
}

void Model::create_spline(const SketchEntity& entity) {
  SplineModel model;
  model.definition = entity.bspline();
  model.cubic_bezier = is_bezier_chain(model.definition);
  const auto& poles = model.definition.poles;
  const bool open_ends = !model.definition.periodic;
  for (std::size_t i = 0; i < poles.size(); ++i) {
    std::string bound = poles[i].point_id;
    if (bound.empty() && open_ends && i == 0) bound = entity.point_id("start");
    if (bound.empty() && open_ends && i + 1 == poles.size()) bound = entity.point_id("end");
    if (!bound.empty()) {
      model.poles.push_back(point_by_id(bound));  // shares the sketch point's parameters
    } else {
      model.poles.push_back(system.params.add_point(poles[i].x, poles[i].y, /*fixed=*/!model.cubic_bezier));
    }
  }
  if (model.cubic_bezier) {
    for (std::size_t i = 0; i + 1 < poles.size(); i += 3) {
      const int base = static_cast<int>(i);
      model.segments.push_back({base, base + 1, base + 2, base + 3});
    }
  }
  splines.emplace(entity.id, std::move(model));
}

void Model::freeze(const Pt& p) {
  system.params[p.x].fixed = true;
  system.params[p.y].fixed = true;
}

void Model::apply_fix(const SketchRef& ref) {
  const SketchEntity& e = entity(ref);
  if (ref.kind == kPointKind || e.kind == kPointKind) {
    freeze(point(ref));
  } else if (e.kind == kLineKind || e.kind == kArcKind) {
    freeze(point_by_id(e.point_id("start")));
    freeze(point_by_id(e.point_id("end")));
    if (e.kind == kArcKind) freeze(point_by_id(e.point_id("center")));
  } else if (e.kind == kBSplineKind) {
    for (const Pt& pole : splines.at(e.id).poles) freeze(pole);
  } else if (e.kind == kEllipseKind) {
    for (const char* role : {"center", "major", "minor"}) freeze(point_by_id(e.point_id(role)));
  } else if (e.kind == kCircleKind) {
    freeze(point_by_id(e.point_id("center")));
    system.params[radius_params.at(e.id)].fixed = true;
  } else {
    throw ValueError("Cannot fix sketch entity kind '" + e.kind + "'");
  }
}

// An arc's endpoints are equidistant from its center (SolveSpace builds this
// into the arc entity itself).
void Model::add_arc_rules() {
  for (const auto& [id, entity] : sketch.entities()) {
    if (entity.kind != kArcKind) continue;
    const Pt center = point_by_id(entity.point_id("center"));
    const Pt start = point_by_id(entity.point_id("start"));
    const Pt end = point_by_id(entity.point_id("end"));
    system.begin_block("");
    equation([=](const Env& e) { return length(e(start) - e(center)) - length(e(end) - e(center)); });
  }
}

void Model::lower(const SketchConstraint& constraint) {
  system.begin_block(constraint.id);
  if (is_basic_kind(constraint.kind)) {
    lower_basic(*this, constraint);
  } else if (is_symmetry_kind(constraint.kind)) {
    lower_symmetry(*this, constraint);
  } else if (constraint.kind == "tangent") {
    lower_tangent(*this, constraint);
  } else {
    throw ValueError("Unsupported sketch constraint kind '" + constraint.kind + "'");
  }
}

// ---- lookups ----------------------------------------------------------------
const SketchEntity& Model::entity(const SketchRef& ref) const { return sketch.entities().at(ref.entity_id); }
const SketchEntity& Model::entity_by_id(const std::string& id) const { return sketch.entities().at(id); }

Pt Model::point_by_id(const std::string& id) const {
  const auto found = points.find(id);
  if (found == points.end()) throw ValueError("Unknown sketch point '" + id + "'");
  return found->second;
}

Pt Model::point(const SketchRef& ref) const { return point_by_id(sketch.resolve_point_id(ref)); }

LineRef Model::line(const SketchEntity& e) const {
  if (e.kind != kLineKind) throw ValueError("Sketch entity '" + e.id + "' is kind '" + e.kind + "', expected a line");
  return {point_by_id(e.point_id("start")), point_by_id(e.point_id("end"))};
}
LineRef Model::line(const SketchRef& ref) const { return line(entity(ref)); }

RadiusRef Model::radius_ref(const SketchRef& ref) const {
  const SketchEntity& e = entity(ref);
  RadiusRef r;
  if (e.kind == kCircleKind) {
    r.param = radius_params.at(e.id);
  } else if (e.kind == kArcKind) {
    r.center = point_by_id(e.point_id("center"));
    r.start = point_by_id(e.point_id("start"));
  } else {
    throw ValueError("Sketch entity '" + e.id + "' is kind '" + e.kind + "' and has no radius");
  }
  return r;
}

Pt Model::circle_center(const SketchRef& ref) const {
  const SketchEntity& e = entity(ref);
  if (e.kind != kCircleKind && e.kind != kArcKind && e.kind != kEllipseKind) {
    throw ValueError("Entity '" + e.id + "' has no circular center");
  }
  return point_by_id(e.point_id("center"));
}

double Model::initial_radius(const SketchRef& ref) const {
  const SketchEntity& e = entity(ref);
  if (e.kind == kCircleKind) return initial(radius_params.at(e.id));
  const SketchPoint2 center = initial(point_by_id(e.point_id("center")));
  const SketchPoint2 start = initial(point_by_id(e.point_id("start")));
  return std::hypot(center.first - start.first, center.second - start.second);
}

const SketchRef& Model::target(const SketchConstraint& constraint, std::size_t index) const {
  if (index >= constraint.targets.size()) {
    throw ValueError("Sketch constraint '" + constraint.id + "' (" + constraint.kind + ") needs at least " +
                     std::to_string(index + 1) + " target(s)");
  }
  return constraint.targets[index];
}

}  // namespace scad::sketch_solver
