// make_sketch_rsketch, add_*_rsketch and the ref getters.
#include <algorithm>
#include <cctype>

#include "finalize.hpp"
#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

namespace scad {

namespace {

using sketch_detail::finalize_sketch_object;
using sketch_detail::SymbolicArgs;

std::string target_path(const SketchRef& ref) {
  if (ref.kind == kPointKind && ref.subentity != "geometry") return ref.entity_id + "." + ref.subentity;
  return ref.entity_id;
}

// A freshly added entity is reported with the sketch it extends as its parameters.
Value base_params(const Sketch& updated, const std::string& entity_id) {
  Value params = Value::object();
  params.set("sketch_id", updated.sketch_id());
  params.set("entity_id", entity_id);
  return params;
}

void append_symbolic(SymbolicArgs& symbolic, const char* name, const Scalar& scalar) {
  if (scalar.symbolic()) symbolic.emplace_back(name, scalar);
}

Vec3 vec_from_value(const Value* value, const Vec3& fallback) {
  if (value == nullptr) return fallback;
  if (!value->is_array() || value->as_array().size() != 3) {
    throw ValueError("Sketch plane origin and axes must be 3-D vectors");
  }
  const auto& items = value->as_array();
  return {items[0].as_double(), items[1].as_double(), items[2].as_double()};
}

Value vec_value(const Vec3& v) { return Value(Value::Array{Value(v.x), Value(v.y), Value(v.z)}); }

// _sketch_plane_in_current_coordinates
Value plane_in_current_coordinates(const Value& plane) {
  Vec3 origin{0, 0, 0};
  Vec3 x_axis{1, 0, 0};
  Vec3 y_axis{0, 1, 0};
  if (plane.is_string()) {
    std::string token = plane.as_string();
    std::transform(token.begin(), token.end(), token.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    if (token == "XY") {
    } else if (token == "XZ") {
      y_axis = {0, 0, 1};
    } else if (token == "YZ") {
      x_axis = {0, 1, 0};
      y_axis = {0, 0, 1};
    } else {
      throw ValueError("Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping");
    }
  } else if (plane.is_object()) {
    origin = vec_from_value(plane.find("origin"), origin);
    x_axis = vec_from_value(plane.find("x_axis"), x_axis);
    y_axis = vec_from_value(plane.find("y_axis"), y_axis);
  } else {
    throw ValueError("Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping");
  }
  const CoordinateSystem& cs = current_cs();
  Value out = Value::object();
  out.set("origin", vec_value(cs.transform_point(origin)));
  out.set("x_axis", vec_value(cs.transform_vector(x_axis)));
  out.set("y_axis", vec_value(cs.transform_vector(y_axis)));
  return out;
}

}  // namespace

Sketch make_sketch_rsketch(const std::optional<std::string>& name, const Value& plane,
                           const std::optional<std::string>& sketch_id) {
  static const ErrorSpec kSpec{"make_sketch_rsketch",
                               "Failed to create a sketch document.",
                               {"The sketch name or plane payload is invalid."},
                               {"Use plane='XY', 'XZ', 'YZ', or a valid plane mapping."}};
  return guarded(kSpec, [&] {
    Sketch sketch(name, plane_in_current_coordinates(plane), sketch_id);
    Value params = Value::object();
    params.set("name", name ? Value(*name) : Value());
    params.set("plane", plane);
    params.set("sketch_id", sketch.sketch_id());
    finalize_sketch_object("make_sketch_rsketch", std::move(params), {}, sketch);
    return sketch;
  });
}

Sketch add_point_rsketch(const Sketch& sketch, const std::string& point_id, const Scalar& x, const Scalar& y) {
  static const ErrorSpec kSpec{"add_point_rsketch",
                               "Failed to add a point to the sketch.",
                               {"The sketch is invalid.", "The point id is duplicated.",
                                "The x or y value is not a valid scalar or expression."},
                               {"Use a unique point id within the sketch.",
                                "Pass numeric x/y values or valid scalar expressions."}};
  return guarded(kSpec, [&] {
    Sketch updated = sketch.clone(/*include_solve=*/false);
    updated.add_point(point_id, x, y);
    Value params = Value::object();
    params.set("sketch_id", updated.sketch_id());
    params.set("point_id", point_id);
    params.set("x", Value(evaluate_scalar(x, "x")));
    params.set("y", Value(evaluate_scalar(y, "y")));
    SymbolicArgs symbolic;
    append_symbolic(symbolic, "x", x);
    append_symbolic(symbolic, "y", y);
    finalize_sketch_object("add_point_rsketch", std::move(params), std::move(symbolic), updated, &sketch);
    return updated;
  });
}

SketchRef get_sketch_entity_rsketchref(const Sketch& sketch, const std::string& entity_id) {
  return sketch.ref(entity_id);
}

SketchRef get_sketch_point_rsketchref(const Sketch& sketch, const std::string& point_path) {
  return sketch.point_ref(point_path);
}

Sketch add_line_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& start,
                        const SketchTarget& end, bool construction) {
  static const ErrorSpec kSpec{"add_line_rsketch",
                               "Failed to add a line to the sketch.",
                               {"The line id is duplicated.", "One of the endpoint refs does not belong to this sketch.",
                                "Both endpoints resolve to the same point."},
                               {"Use a unique line id.",
                                "Create endpoints with add_point_rsketch(...) and refer to them by id."}};
  return guarded(kSpec, [&] {
    const SketchRef start_ref = sketch.resolve_target(start, {"point"});
    const SketchRef end_ref = sketch.resolve_target(end, {"point"});
    Sketch updated = sketch.clone(false);
    updated.add_line(entity_id, start_ref, end_ref, construction);
    Value params = base_params(updated, entity_id);
    params.set("start", target_path(start_ref));
    params.set("end", target_path(end_ref));
    params.set("construction", construction);
    finalize_sketch_object("add_line_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

Sketch add_circle_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& center,
                          const Scalar& radius, bool construction) {
  static const ErrorSpec kSpec{"add_circle_rsketch",
                               "Failed to add a circle to the sketch.",
                               {"The circle id is duplicated.", "The center ref does not belong to this sketch.",
                                "The radius is not positive."},
                               {"Use a unique circle id and a positive radius.",
                                "Create the center with add_point_rsketch(...) and refer to it by id."}};
  return guarded(kSpec, [&] {
    const SketchRef center_ref = sketch.resolve_target(center, {"point"});
    Sketch updated = sketch.clone(false);
    updated.add_circle(entity_id, center_ref, radius, construction);
    Value params = base_params(updated, entity_id);
    params.set("center", target_path(center_ref));
    params.set("radius", Value(evaluate_scalar(radius, "radius")));
    params.set("construction", construction);
    SymbolicArgs symbolic;
    append_symbolic(symbolic, "radius", radius);
    finalize_sketch_object("add_circle_rsketch", std::move(params), std::move(symbolic), updated, &sketch);
    return updated;
  });
}

Sketch add_ellipse_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& center,
                           const SketchTarget& major_point, const SketchTarget& minor_point, bool construction) {
  static const ErrorSpec kSpec{
      "add_ellipse_rsketch",
      "Failed to add an ellipse to the sketch.",
      {"The entity id is duplicated.", "One of the axis point refs does not belong to this sketch.",
       "The three axis points are not distinct or are degenerate.",
       "The minor axis exceeds the major axis at the initial positions."},
      {"Use a unique entity id.", "Create the center, major, and minor points first.",
       "Place the major point farther from the center than the minor point."}};
  return guarded(kSpec, [&] {
    const SketchRef center_ref = sketch.resolve_target(center, {"point"});
    const SketchRef major_ref = sketch.resolve_target(major_point, {"point"});
    const SketchRef minor_ref = sketch.resolve_target(minor_point, {"point"});
    Sketch updated = sketch.clone(false);
    updated.add_ellipse(entity_id, center_ref, major_ref, minor_ref, construction);
    Value params = base_params(updated, entity_id);
    params.set("center", target_path(center_ref));
    params.set("major_point", target_path(major_ref));
    params.set("minor_point", target_path(minor_ref));
    params.set("construction", construction);
    finalize_sketch_object("add_ellipse_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

Sketch add_bspline_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& start,
                           const SketchTarget& end, const std::vector<SketchControlPoint>& control_points,
                           int degree, const std::optional<std::vector<Scalar>>& knots,
                           const std::optional<std::vector<int>>& multiplicities,
                           const std::optional<std::vector<Scalar>>& weights, bool periodic, bool construction) {
  static const ErrorSpec kSpec{"add_bspline_rsketch",
                               "Failed to add a B-spline to the sketch.",
                               {"The entity id is duplicated.", "The start or end ref does not belong to this sketch.",
                                "Too few control points for the requested degree."},
                               {"Use a unique entity id.",
                                "Create start and end points with add_point_rsketch(...) first.",
                                "Pass at least degree+1 control points."}};
  return guarded(kSpec, [&] {
    const SketchRef start_ref = sketch.resolve_target(start, {"point"});
    const SketchRef end_ref = sketch.resolve_target(end, {"point"});
    Sketch updated = sketch.clone(false);
    updated.add_bspline(entity_id, start_ref, end_ref, control_points, degree, knots, multiplicities, weights,
                        periodic, construction);
    const Value& data = updated.entities().at(entity_id).data;
    Value params = base_params(updated, entity_id);
    params.set("start", target_path(start_ref));
    params.set("end", target_path(end_ref));
    for (const char* key : {"control_points", "degree", "knots", "multiplicities", "weights", "periodic"}) {
      params.set(key, *data.find(key));
    }
    params.set("construction", construction);
    finalize_sketch_object("add_bspline_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

Sketch add_arc_rsketch(const Sketch& sketch, const std::string& entity_id, const SketchTarget& start,
                       const SketchTarget& end, const SketchTarget& center, bool construction) {
  static const ErrorSpec kSpec{
      "add_arc_rsketch",
      "Failed to add an arc to the sketch.",
      {"The entity id is duplicated.", "The start, end, or center ref does not belong to this sketch.",
       "The start and end points are the same."},
      {"Use a unique entity id.", "Create start, end, and center points with add_point_rsketch(...) first."}};
  return guarded(kSpec, [&] {
    const SketchRef start_ref = sketch.resolve_target(start, {"point"});
    const SketchRef end_ref = sketch.resolve_target(end, {"point"});
    const SketchRef center_ref = sketch.resolve_target(center, {"point"});
    Sketch updated = sketch.clone(false);
    updated.add_arc(entity_id, start_ref, end_ref, center_ref, construction);
    Value params = base_params(updated, entity_id);
    params.set("start", target_path(start_ref));
    params.set("end", target_path(end_ref));
    params.set("center", target_path(center_ref));
    params.set("construction", construction);
    finalize_sketch_object("add_arc_rsketch", std::move(params), {}, updated, &sketch);
    return updated;
  });
}

}  // namespace scad
