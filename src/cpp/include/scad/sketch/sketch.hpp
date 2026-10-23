// The declarative sketch document: port of simplecadapi/sketch.py::Sketch.
//
// A Sketch is intent-level 2D: named points, lines, circles, arcs, ellipses and
// B-splines plus constraints between them.  It is a plain value (copy it to
// "update" it); the operators in scad/sketch/operators.hpp are the functional
// API on top, the solver backends (scad/sketch/solver.hpp) turn it into
// coordinates, and scad/sketch/profile.hpp promotes solved loops to wires/faces.
#pragma once

#include <array>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/sketch/ordered_map.hpp"
#include "scad/sketch/solver.hpp"
#include "scad/sketch/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// One B-spline control point as the caller gave it: a sketch point, or a literal.
struct SketchControlPoint {
  std::optional<SketchTarget> point;
  std::array<double, 2> xy{0.0, 0.0};

  SketchControlPoint() = default;
  SketchControlPoint(SketchTarget target) : point(std::move(target)) {}   // NOLINT(google-explicit-constructor)
  SketchControlPoint(std::string path) : point(SketchTarget(std::move(path))) {}  // NOLINT
  SketchControlPoint(const char* path) : point(SketchTarget(path)) {}     // NOLINT
  SketchControlPoint(double x, double y) : xy{x, y} {}
  SketchControlPoint(std::array<double, 2> literal) : xy(literal) {}      // NOLINT
};

struct SketchSolveRequest {
  bool require_fully_constrained = false;
  bool strict = true;
  double tolerance = 1e-7;
  int max_iterations = 80;
  // Null: the process default backend.
  std::shared_ptr<SketchSolverBackend> backend;
};

// The sketch plane as an orthonormal frame (normal = x cross y).
struct SketchPlaneFrame {
  Vec3 origin;
  Vec3 x_axis;
  Vec3 y_axis;
  Vec3 normal;
};

class Sketch {
 public:
  // `plane`: "XY" | "XZ" | "YZ" or {"origin", "x_axis", "y_axis"}.  ValueError
  // for anything else.  Without a `sketch_id` one is allocated (see
  // SketchIdAllocatorScope, else "sketch_<8 hex>").
  explicit Sketch(std::optional<std::string> name = std::nullopt, Value plane = Value("XY"),
                  std::optional<std::string> sketch_id = std::nullopt);

  // ---- identity -----------------------------------------------------------
  const std::string& sketch_id() const noexcept { return sketch_id_; }
  const std::optional<std::string>& name() const noexcept { return name_; }
  const Value& plane() const noexcept { return plane_; }
  Value& metadata() noexcept { return metadata_; }
  const Value& metadata() const noexcept { return metadata_; }
  // Where a recorded graph attaches its node (graph.node_id, ...): not part of the sketch's content.  Like the
  // product values, a sketch's runtime and metadata dictionaries stay writable through a const reference.
  Value& runtime() noexcept { return runtime_; }
  const Value& runtime() const noexcept { return runtime_; }
  void set_runtime(std::string key, Value value) const { runtime_.set(std::move(key), std::move(value)); }
  Value get_runtime(std::string_view key, Value fallback = {}) const {
    const Value* found = runtime_.find(key);
    return found != nullptr ? *found : std::move(fallback);
  }
  void set_metadata(std::string key, Value value) const { metadata_.set(std::move(key), std::move(value)); }

  // ---- document -----------------------------------------------------------
  const OrderedMap<SketchEntity>& entities() const noexcept { return entities_; }
  const std::vector<SketchConstraint>& constraints() const noexcept { return constraints_; }
  const std::optional<SketchSolveResult>& last_solve_result() const noexcept { return last_solve_; }
  void clear_solve_result() noexcept { last_solve_.reset(); }

  // A copy (the functional "update" step).  Curves are shared, not copied.
  Sketch clone(bool include_solve = true) const;

  Value to_value() const;
  static Sketch from_value(const Value& data);

  // ---- refs ---------------------------------------------------------------
  SketchRef ref(const std::string& entity_id, const std::optional<std::string>& kind = std::nullopt,
                const std::string& subentity = "geometry") const;
  // "p0", or "line.start" / "circle.center" / "arc.end" / "ellipse.major" ...
  SketchRef point_ref(const std::string& path) const;
  // `expected`: the kinds the target may have (empty: any).
  SketchRef resolve_target(const SketchTarget& target, const std::vector<std::string>& expected = {}) const;
  void validate_ref(const SketchRef& ref) const;
  // The point entity a ref designates ("line.start" -> the line's start point id).
  std::string resolve_point_id(const SketchRef& ref) const;

  // ---- building (each mutates; the operators clone first) ----------------
  SketchRef add_point(const std::string& point_id, const Scalar& x, const Scalar& y);
  Sketch& add_line(const std::string& entity_id, const SketchRef& start, const SketchRef& end,
                   bool construction = false);
  Sketch& add_circle(const std::string& entity_id, const SketchRef& center, const Scalar& radius,
                     bool construction = false);
  Sketch& add_arc(const std::string& entity_id, const SketchRef& start, const SketchRef& end,
                  const SketchRef& center, bool construction = false);
  Sketch& add_ellipse(const std::string& entity_id, const SketchRef& center, const SketchRef& major_point,
                      const SketchRef& minor_point, bool construction = false);
  Sketch& add_bspline(const std::string& entity_id, const SketchRef& start, const SketchRef& end,
                      const std::vector<SketchControlPoint>& control_points, int degree = 3,
                      const std::optional<std::vector<Scalar>>& knots = std::nullopt,
                      const std::optional<std::vector<int>>& multiplicities = std::nullopt,
                      const std::optional<std::vector<Scalar>>& weights = std::nullopt, bool periodic = false,
                      bool construction = false);
  Sketch& add_constraint(const std::string& kind, const std::vector<SketchRef>& targets,
                         const std::optional<Scalar>& value = std::nullopt,
                         const std::optional<std::string>& constraint_id = std::nullopt, bool driving = true,
                         Value metadata = Value::object());

  // ---- solving ------------------------------------------------------------
  // Runs the backend and remembers the result.  `strict`: conflicting / failed
  // raise the structured sketch_solve error; `require_fully_constrained`: DOF > 0 raises.
  SketchSolveResult solve(const SketchSolveRequest& request = {});
  // The last solve, solving (strict) first when there is none.
  const SketchSolveResult& solved_result();

  // ---- plane --------------------------------------------------------------
  SketchPlaneFrame plane_frame() const;
  Vec3 point3(const SketchPoint2& point) const;
  Vec3 plane_normal() const;

  // ---- legacy curve container (Sketch([wire])) ---------------------------
  Sketch& add_curve(const Shape& curve);  // Edge or Wire, ValueError otherwise
  std::vector<Shape> curves() const { return curves_; }
  std::vector<Wire> closed_wires() const;

 private:
  void add_entity(SketchEntity entity);
  SketchPoint2 entity_xy(const std::string& point_id) const;

  std::string sketch_id_;
  std::optional<std::string> name_;
  Value plane_;
  mutable Value metadata_ = Value::object();
  mutable Value runtime_ = Value::object();
  OrderedMap<SketchEntity> entities_;
  std::vector<SketchConstraint> constraints_;
  std::optional<SketchSolveResult> last_solve_;
  std::vector<Shape> curves_;
};

// While alive, make_sketch_rsketch-style id allocation asks `allocate` first
// (the reactive session installs one so replayed sketches get stable ids).
// Returning nullopt falls back to the random id.  Thread-local, nests.
class SketchIdAllocatorScope {
 public:
  using Allocator = std::function<std::optional<std::string>()>;
  explicit SketchIdAllocatorScope(Allocator allocate);
  ~SketchIdAllocatorScope();
  SketchIdAllocatorScope(const SketchIdAllocatorScope&) = delete;
  SketchIdAllocatorScope& operator=(const SketchIdAllocatorScope&) = delete;

 private:
  Allocator allocate_;
  const Allocator* previous_;
};
std::optional<std::string> allocate_sketch_id();

}  // namespace scad
