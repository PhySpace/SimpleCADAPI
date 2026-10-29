// The plain data of a declarative sketch: entities, constraints, references,
// and what a solve returns.  Port of the dataclasses in simplecadapi/sketch.py.
//
// Nothing here knows how to solve or to build geometry; `Sketch`
// (scad/sketch/sketch.hpp) owns the document and the solver backends consume it.
#pragma once

#include <array>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/sketch/ordered_map.hpp"

namespace scad {

// Entity kinds a sketch knows.
inline constexpr std::string_view kPointKind = "point";
inline constexpr std::string_view kLineKind = "line";
inline constexpr std::string_view kCircleKind = "circle";
inline constexpr std::string_view kArcKind = "arc";
inline constexpr std::string_view kBSplineKind = "bspline";
inline constexpr std::string_view kEllipseKind = "ellipse";

// A stable reference to a sketch entity, or to one of its points.
struct SketchRef {
  std::string sketch_id;
  std::string entity_id;
  std::string kind;
  std::string subentity = "geometry";

  Value to_value() const;
  static SketchRef from_value(const Value& data);
  std::string repr() const;
  bool operator==(const SketchRef&) const = default;
};

// What operators accept where Python accepts `SketchRef | str`: a ref, or an id
// / "entity.subentity" path resolved against the sketch.
class SketchTarget {
 public:
  SketchTarget() = default;  // empty path: only so binding layers can default-construct a slot
  SketchTarget(SketchRef ref) : ref_(std::move(ref)) {}       // NOLINT(google-explicit-constructor)
  SketchTarget(std::string path) : path_(std::move(path)) {}  // NOLINT(google-explicit-constructor)
  SketchTarget(const char* path) : path_(path) {}             // NOLINT(google-explicit-constructor)

  bool is_ref() const noexcept { return ref_.has_value(); }
  const SketchRef& ref() const { return *ref_; }
  const std::string& path() const noexcept { return path_; }

 private:
  std::optional<SketchRef> ref_;
  std::string path_;
};

// One pole of a B-spline: a sketch point (it moves with the solve) or a literal.
struct SketchPole {
  std::string point_id;  // non-empty: shares the sketch point's coordinates
  double x = 0.0;
  double y = 0.0;
  bool is_point() const noexcept { return !point_id.empty(); }
};

// The B-spline payload of an entity, parsed out of `SketchEntity::data`.
struct SketchBSpline {
  int degree = 3;
  std::vector<SketchPole> poles;
  std::vector<double> knots;
  std::vector<int> multiplicities;
  std::optional<std::vector<double>> weights;
  bool periodic = false;
};

// An entity of the sketch.  `data` is Python's `entity.data` (point ids by role,
// numbers evaluated when the entity was added); `scalars` keeps the symbolic
// originals of x / y / radius so a re-solve sees a changed parameter.
struct SketchEntity {
  std::string id;
  std::string kind;
  bool construction = false;
  Value data = Value::object();
  std::map<std::string, Scalar, std::less<>> scalars;

  // The point id stored under `role` ("start", "end", "center", "major", ...).
  const std::string& point_id(std::string_view role) const;
  // A numeric field: the (re-evaluated) scalar when symbolic, else data[key].
  double number(std::string_view key) const;
  SketchBSpline bspline() const;  // kind == "bspline"

  // {"id", "kind", "construction", **data}
  Value to_value() const;
};

struct SketchConstraint {
  std::string id;
  std::string kind;
  std::vector<SketchRef> targets;
  std::optional<Scalar> value;
  bool driving = true;
  Value metadata = Value::object();

  // evaluate_scalar(value); ValueError when the constraint has no value.
  double numeric_value() const;
  Value to_value() const;
};

struct SketchConstraintDiagnostic {
  std::optional<std::string> constraint_id;
  std::string severity;  // "warning" | "error"
  std::string code;
  std::string message;
  std::optional<double> residual;

  Value to_value() const;
};

using SketchPoint2 = std::pair<double, double>;

// Backend-neutral result of solving a sketch.
struct SketchSolveResult {
  std::string sketch_id;
  // "solved" | "underconstrained" | "conflicting" | "failed"
  std::string status;
  int dof = 0;
  double residual_norm = 0.0;
  int iterations = 0;
  OrderedMap<SketchPoint2> solved_points;
  OrderedMap<double> solved_scalars;
  OrderedMap<Value> solved_entities;
  std::vector<SketchConstraintDiagnostic> diagnostics;
  std::string backend = "unknown";
  std::string backend_version = "unknown";
  std::optional<int> backend_status_code;

  Value to_value() const;
};

// Python's `float(evaluate_scalar(x))` for the numeric fields above.
double as_float(const Scalar& scalar);

}  // namespace scad
