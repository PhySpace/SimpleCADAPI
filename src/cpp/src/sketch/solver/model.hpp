// Lowering context: maps a Sketch document onto a System.
//
// Model owns the parameter table and equations while the sketch is walked once:
// points and radii become parameters, `fix` constraints freeze parameters, and
// every other driving constraint appends the residual equations SolveSpace
// would (see docs/sketch-solver.md for the catalogue).  The result-assembly and
// measurement code read the same maps, so the document is interpreted once.
#pragma once

#include <array>
#include <string>
#include <unordered_map>
#include <vector>

#include "scad/sketch/sketch.hpp"
#include "system.hpp"

namespace scad::sketch_solver {

// A B-spline's solver representation.
struct SplineModel {
  SketchBSpline definition;
  std::vector<Pt> poles;  // coordinates of each pole (shared with sketch points where bound)
  bool cubic_bezier = false;
  std::vector<std::array<int, 4>> segments;  // pole indices per Bezier segment
};

// R of a circle (its radius parameter) or of an arc (|start - center|).
struct RadiusRef {
  int param = -1;
  Pt center;
  Pt start;
  Dual operator()(const Env& env) const {
    if (param >= 0) return env(param);
    return length(env(start) - env(center));
  }
};

// A line entity's endpoints.
struct LineRef {
  Pt start;
  Pt end;
  V2 direction(const Env& env) const { return env(end) - env(start); }
};

class Model {
 public:
  explicit Model(const Sketch& sketch);

  const Sketch& sketch;
  System system;
  std::unordered_map<std::string, Pt> points;           // point entity -> parameters
  std::unordered_map<std::string, int> radius_params;   // circle entity -> radius parameter
  std::unordered_map<std::string, SplineModel> splines; // bspline entity -> representation
  std::vector<const SketchConstraint*> measurements;    // driving == false, in order

  // ---- lookups used by lowering and assembly -----------------------------
  const SketchEntity& entity(const SketchRef& ref) const;
  const SketchEntity& entity_by_id(const std::string& id) const;
  Pt point(const SketchRef& ref) const;
  Pt point_by_id(const std::string& id) const;
  LineRef line(const SketchRef& ref) const;
  LineRef line(const SketchEntity& entity) const;
  RadiusRef radius_ref(const SketchRef& ref) const;
  // The center point of a circle, arc or ellipse.
  Pt circle_center(const SketchRef& ref) const;

  // Initial (document) value of a parameter / point.
  double initial(int param) const { return system.params[param].value; }
  SketchPoint2 initial(const Pt& p) const { return {initial(p.x), initial(p.y)}; }
  double initial_radius(const SketchRef& ref) const;

  // ---- building ------------------------------------------------------------
  const SketchRef& target(const SketchConstraint& constraint, std::size_t index) const;
  void equation(Residual fn) { system.add_equation(std::move(fn)); }
  // A new unknown point (a tangent contact point).
  Pt helper_point(double x, double y) { return system.params.add_point(x, y); }

 private:
  void create_parameters();
  void create_spline(const SketchEntity& entity);
  void apply_fix(const SketchRef& ref);
  void freeze(const Pt& p);
  void add_arc_rules();
  void lower(const SketchConstraint& constraint);
};

// Constraint-family lowering (one function per source file).
void lower_basic(Model& model, const SketchConstraint& constraint);
void lower_symmetry(Model& model, const SketchConstraint& constraint);
void lower_tangent(Model& model, const SketchConstraint& constraint);
// True when `kind` is handled by the corresponding function above.
bool is_basic_kind(const std::string& kind);
bool is_symmetry_kind(const std::string& kind);

}  // namespace scad::sketch_solver
