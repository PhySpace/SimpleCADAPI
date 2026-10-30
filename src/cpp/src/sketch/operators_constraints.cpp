// The constrain_*_rsketch family.  Like the Python code, none of these wraps its
// failures: a bad target is a plain ValueError.
#include "finalize.hpp"
#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

namespace scad {

namespace {

using sketch_detail::finalize_sketch_object;
using sketch_detail::SymbolicArgs;
using Kinds = std::vector<std::string>;

const Kinds kPoint{"point"};
const Kinds kLine{"line"};
const Kinds kEllipse{"ellipse"};
const Kinds kLineCircleArc{"line", "circle", "arc"};
const Kinds kLineCircleArcSplineEllipse{"line", "circle", "arc", "bspline", "ellipse"};
const Kinds kCircleArcEllipse{"circle", "arc", "ellipse"};
const Kinds kCircleArc{"circle", "arc"};
const Kinds kLineArcSpline{"line", "arc", "bspline"};
const Kinds kAny{};

std::string target_path(const SketchRef& ref) {
  if (ref.kind == kPointKind && ref.subentity != "geometry")
    return ref.entity_id + "." + ref.subentity;
  return ref.entity_id;
}

struct Target {
  SketchTarget target;
  const Kinds& expected;
};

struct ConstraintCall {
  std::string kind;
  std::vector<Target> targets;
  std::optional<Scalar> value;
  SketchConstraintId constraint_id;
  bool driving = true;
  Value metadata;  // null = none
};

// _constrain_rsketch
Sketch constrain(const Sketch& sketch, const ConstraintCall& call) {
  std::vector<SketchRef> refs;
  refs.reserve(call.targets.size());
  for (const Target& item : call.targets)
    refs.push_back(sketch.resolve_target(item.target, item.expected));

  Sketch updated = sketch.clone(/*include_solve=*/false);
  updated.add_constraint(call.kind, refs, call.value, call.constraint_id, call.driving,
                         call.metadata.is_null() ? Value::object() : call.metadata);

  Value::Array paths;
  for (const SketchRef& ref : refs)
    paths.emplace_back(target_path(ref));
  Value params = Value::object();
  params.set("sketch_id", updated.sketch_id());
  params.set("kind", call.kind);
  params.set("targets", Value(std::move(paths)));
  params.set("value", call.value ? Value(evaluate_scalar(*call.value, "value")) : Value());
  params.set("constraint_id", call.constraint_id ? Value(*call.constraint_id) : Value());
  params.set("driving", call.driving);
  params.set("metadata", call.metadata.is_null() ? Value::object() : call.metadata);
  SymbolicArgs symbolic;
  if (call.value && call.value->symbolic())
    symbolic.emplace_back("value", *call.value);
  finalize_sketch_object("make_constrain_" + call.kind + "_rsketch", std::move(params), std::move(symbolic), updated,
                         &sketch);
  return updated;
}

Sketch two(const Sketch& s, const char* kind, const SketchTarget& a, const Kinds& ka, const SketchTarget& b,
           const Kinds& kb, const SketchConstraintId& id) {
  return constrain(s, {kind, {{a, ka}, {b, kb}}, std::nullopt, id, true, Value()});
}

Sketch two_points(const Sketch& s, const char* kind, const SketchTarget& a, const SketchTarget& b,
                  const SketchConstraintId& id) {
  return two(s, kind, a, kPoint, b, kPoint, id);
}

Sketch two_lines(const Sketch& s, const char* kind, const SketchTarget& a, const SketchTarget& b,
                 const SketchConstraintId& id) {
  return two(s, kind, a, kLine, b, kLine, id);
}

Sketch dimension(const Sketch& s, const char* kind, std::vector<Target> targets, const Scalar& value,
                 const SketchConstraintId& id, bool driving) {
  return constrain(s, {kind, std::move(targets), value, id, driving, Value()});
}

}  // namespace

Sketch constrain_rsketch(const Sketch& sketch, const std::string& kind, const std::vector<SketchTarget>& targets,
                         const std::optional<Scalar>& value, const SketchConstraintId& constraint_id, bool driving,
                         Value metadata) {
  static const Kinds kAny;  // no kind is required of a target
  ConstraintCall call{kind, {}, value, constraint_id, driving, std::move(metadata)};
  for (const SketchTarget& target : targets)
    call.targets.push_back({target, kAny});
  return constrain(sketch, call);
}

Sketch constrain_coincident_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const SketchConstraintId& id) {
  return two_points(sketch, "coincident", a, b, id);
}

Sketch constrain_connect_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                 const SketchConstraintId& id) {
  return two_points(sketch, "coincident", a, b, id);
}

Sketch constrain_point_on_rsketch(const Sketch& sketch, const SketchTarget& point, const SketchTarget& entity,
                                  const SketchConstraintId& id) {
  return two(sketch, "point_on", point, kPoint, entity, kLineCircleArc, id);
}

Sketch constrain_horizontal_rsketch(const Sketch& sketch, const SketchTarget& line, const SketchConstraintId& id) {
  return constrain(sketch, {"horizontal", {{line, kLine}}, std::nullopt, id, true, Value()});
}

Sketch constrain_vertical_rsketch(const Sketch& sketch, const SketchTarget& line, const SketchConstraintId& id) {
  return constrain(sketch, {"vertical", {{line, kLine}}, std::nullopt, id, true, Value()});
}

Sketch constrain_points_horizontal_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                           const SketchConstraintId& id) {
  return two_points(sketch, "points_horizontal", a, b, id);
}

Sketch constrain_points_vertical_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                         const SketchConstraintId& id) {
  return two_points(sketch, "points_vertical", a, b, id);
}

Sketch constrain_line_distance_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                       const Scalar& value, const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "line_distance", {{a, kLine}, {b, kLine}}, value, id, driving);
}

Sketch constrain_normal_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                const SketchConstraintId& id) {
  return two(sketch, "normal", a, kLineCircleArc, b, kLineCircleArc, id);
}

Sketch constrain_mirror_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& axis,
                                const SketchTarget& b, const SketchConstraintId& id) {
  return constrain(
      sketch, {"mirror", {{a, kLineCircleArc}, {axis, kLine}, {b, kLineCircleArc}}, std::nullopt, id, true, Value()});
}

Sketch constrain_midpoint_points_rsketch(const Sketch& sketch, const SketchTarget& mid, const SketchTarget& a,
                                         const SketchTarget& b, const SketchConstraintId& id) {
  return constrain(sketch,
                   {"midpoint_points", {{mid, kPoint}, {a, kPoint}, {b, kPoint}}, std::nullopt, id, true, Value()});
}

Sketch constrain_parallel_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                  const SketchConstraintId& id) {
  return two_lines(sketch, "parallel", a, b, id);
}

Sketch constrain_perpendicular_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                       const SketchConstraintId& id) {
  return two_lines(sketch, "perpendicular", a, b, id);
}

Sketch constrain_collinear_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                   const SketchConstraintId& id) {
  return two_lines(sketch, "collinear", a, b, id);
}

Sketch constrain_tangent_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                 const std::optional<std::string>& at_a, const std::optional<std::string>& at_b,
                                 const std::string& mode, const SketchConstraintId& id) {
  const auto valid_selector = [](const std::optional<std::string>& at) {
    return !at || *at == "start" || *at == "end";
  };
  if (!valid_selector(at_a) || !valid_selector(at_b)) {
    throw ValueError("Tangent endpoint selectors must be 'start' or 'end'");
  }
  if (mode != "external" && mode != "internal")
    throw ValueError("Tangent mode must be 'external' or 'internal'");
  Value metadata = Value::object();
  metadata.set("at_a", at_a ? Value(*at_a) : Value());
  metadata.set("at_b", at_b ? Value(*at_b) : Value());
  metadata.set("mode", mode);
  return constrain(sketch, {"tangent",
                            {{a, kLineCircleArcSplineEllipse}, {b, kLineCircleArcSplineEllipse}},
                            std::nullopt,
                            id,
                            true,
                            std::move(metadata)});
}

Sketch constrain_concentric_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const SketchConstraintId& id) {
  return two(sketch, "concentric", a, kCircleArcEllipse, b, kCircleArcEllipse, id);
}

Sketch constrain_midpoint_rsketch(const Sketch& sketch, const SketchTarget& point, const SketchTarget& line,
                                  const SketchConstraintId& id) {
  return two(sketch, "midpoint", point, kPoint, line, kLine, id);
}

Sketch constrain_symmetric_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                   const SketchTarget& axis, const SketchConstraintId& id) {
  return constrain(sketch, {"symmetric", {{a, kPoint}, {b, kPoint}, {axis, kLine}}, std::nullopt, id, true, Value()});
}

Sketch constrain_equal_length_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                      const SketchConstraintId& id) {
  return two_lines(sketch, "equal_length", a, b, id);
}

Sketch constrain_equal_radius_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                      const SketchConstraintId& id) {
  return two(sketch, "equal_radius", a, kCircleArc, b, kCircleArc, id);
}

Sketch constrain_distance_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                  const Scalar& value, const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "distance", {{a, kPoint}, {b, kPoint}}, value, id, driving);
}

Sketch constrain_distance_x_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const Scalar& value, const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "distance_x", {{a, kPoint}, {b, kPoint}}, value, id, driving);
}

Sketch constrain_distance_y_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b,
                                    const Scalar& value, const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "distance_y", {{a, kPoint}, {b, kPoint}}, value, id, driving);
}

Sketch constrain_length_rsketch(const Sketch& sketch, const SketchTarget& line, const Scalar& value,
                                const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "length", {{line, kLineArcSpline}}, value, id, driving);
}

Sketch constrain_angle_rsketch(const Sketch& sketch, const SketchTarget& a, const SketchTarget& b, const Scalar& value,
                               const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "angle", {{a, kLine}, {b, kLine}}, value, id, driving);
}

Sketch constrain_radius_rsketch(const Sketch& sketch, const SketchTarget& circle, const Scalar& value,
                                const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "radius", {{circle, kCircleArc}}, value, id, driving);
}

Sketch constrain_diameter_rsketch(const Sketch& sketch, const SketchTarget& circle, const Scalar& value,
                                  const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "diameter", {{circle, kCircleArc}}, value, id, driving);
}

Sketch constrain_major_radius_rsketch(const Sketch& sketch, const SketchTarget& ellipse, const Scalar& value,
                                      const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "major_radius", {{ellipse, kEllipse}}, value, id, driving);
}

Sketch constrain_minor_radius_rsketch(const Sketch& sketch, const SketchTarget& ellipse, const Scalar& value,
                                      const SketchConstraintId& id, bool driving) {
  return dimension(sketch, "minor_radius", {{ellipse, kEllipse}}, value, id, driving);
}

Sketch constrain_fix_rsketch(const Sketch& sketch, const SketchTarget& target, const SketchConstraintId& id) {
  return constrain(sketch, {"fix", {{target, kAny}}, std::nullopt, id, true, Value()});
}

}  // namespace scad
