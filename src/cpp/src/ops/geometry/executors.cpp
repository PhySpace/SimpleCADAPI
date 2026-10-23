#include "scad/ops/geometry/executors.hpp"

#include <string>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/ops/geometry/arcs.hpp"
#include "scad/ops/geometry/brep_region.hpp"
#include "scad/ops/geometry/circles.hpp"
#include "scad/ops/geometry/faces.hpp"
#include "scad/ops/geometry/helix.hpp"
#include "scad/ops/geometry/lines.hpp"
#include "scad/ops/geometry/primitives.hpp"
#include "scad/ops/geometry/splines.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

namespace {

using reactive::ScalarValues;

// ---- reading recorded parameters --------------------------------------------------------

const Value& param(const Value& params, std::string_view key) {
  const Value* found = params.find(key);
  if (found == nullptr) throw ValueError("recorded parameter '" + std::string(key) + "' is missing");
  return *found;
}

Scalar number(const Value& params, std::string_view key) { return Scalar(param(params, key).as_double()); }

Scalar3 point_of(const Value& value) {
  const Value::Array& items = value.as_array();
  if (items.size() != 3) throw ValueError("a recorded point must have three coordinates");
  return scalar3(items[0].as_double(), items[1].as_double(), items[2].as_double());
}
Scalar3 point(const Value& params, std::string_view key) { return point_of(param(params, key)); }

std::optional<Scalar3> optional_point(const Value& params, std::string_view key) {
  const Value& value = param(params, key);
  return value.is_null() ? std::nullopt : std::optional<Scalar3>(point_of(value));
}

ScalarPoint coordinates_of(const Value& value) {
  ScalarPoint out;
  for (const Value& item : value.as_array()) out.emplace_back(item.as_double());
  return out;
}

std::vector<ScalarPoint> point_list(const Value& params, std::string_view key) {
  std::vector<ScalarPoint> out;
  for (const Value& item : param(params, key).as_array()) out.push_back(coordinates_of(item));
  return out;
}

std::optional<ScalarList> optional_scalars(const Value& params, std::string_view key) {
  const Value& value = param(params, key);
  if (value.is_null()) return std::nullopt;
  return coordinates_of(value);
}

OptionalString optional_text(const Value& params, std::string_view key) {
  const Value* value = params.find(key);
  if (value == nullptr || value->is_null()) return std::nullopt;
  return value->as_string();
}

template <class T>
std::vector<Shape> one(const T& shape) {
  return {shape};
}

std::vector<Edge> edges_of(const std::vector<OpInput>& inputs) {
  std::vector<Edge> edges;
  edges.reserve(inputs.size());
  for (const OpInput& input : inputs) edges.emplace_back(input.shape);
  return edges;
}

const Shape& input_at(const std::vector<OpInput>& inputs, std::size_t index) {
  if (index >= inputs.size()) throw ValueError("a recorded operation lost an input shape");
  return inputs[index].shape;
}

using Params = const Value&;
using Inputs = const std::vector<OpInput>&;

// ---- executors by family ------------------------------------------------------------------

void register_curves(reactive::ExecutorRegistry& registry) {
  registry.add("make_point_rvertex", [](Params p, Inputs, const ScalarValues&) {
    return one(make_point_rvertex(number(p, "x"), number(p, "y"), number(p, "z")));
  });
  registry.add("make_line_redge", [](Params p, Inputs, const ScalarValues&) {
    return one(make_line_redge(point(p, "start"), point(p, "end")));
  });
  registry.add("make_circle_redge", [](Params p, Inputs, const ScalarValues&) {
    return one(make_circle_redge(point(p, "center"), number(p, "radius"), point(p, "normal")));
  });
  registry.add("make_ellipse_redge", [](Params p, Inputs, const ScalarValues&) {
    return one(make_ellipse_redge(point(p, "center"), number(p, "major_radius"), number(p, "minor_radius"),
                                  point(p, "normal"), optional_point(p, "major_direction")));
  });
  registry.add("make_three_point_arc_redge", [](Params p, Inputs, const ScalarValues&) {
    return one(make_three_point_arc_redge(point(p, "start"), point(p, "middle"), point(p, "end")));
  });
  registry.add("make_angle_arc_redge", [](Params p, Inputs, const ScalarValues&) {
    return one(make_angle_arc_redge(point(p, "center"), number(p, "radius"), number(p, "start_angle"),
                                    number(p, "end_angle"), point(p, "normal")));
  });
  registry.add("make_helix_redge", [](Params p, Inputs, const ScalarValues&) {
    return one(make_helix_redge(number(p, "pitch"), number(p, "height"), number(p, "radius"), point(p, "center"),
                                point(p, "dir"), param(p, "handedness").as_string()));
  });
}

void register_splines(reactive::ExecutorRegistry& registry) {
  registry.add("make_spline_redge", [](Params p, Inputs, const ScalarValues&) {
    SplineSpec spec;
    spec.control_points = point_list(p, "control_points");
    spec.degree = static_cast<double>(param(p, "degree").as_int());
    spec.knots = optional_scalars(p, "knots");
    std::vector<int> multiplicities;
    for (const Value& m : param(p, "multiplicities").as_array()) multiplicities.push_back(static_cast<int>(m.as_int()));
    spec.multiplicities = std::move(multiplicities);
    spec.weights = optional_scalars(p, "weights");
    spec.periodic = param(p, "periodic").as_bool();
    return one(make_spline_redge(spec));
  });
  registry.add("make_interpolated_spline_redge", [](Params p, Inputs, const ScalarValues&) {
    return one(make_interpolated_spline_redge({.points = point_list(p, "points"),
                                               .periodic = param(p, "periodic").as_bool(),
                                               .tolerance = number(p, "tolerance")}));
  });
}

void register_assemblies(reactive::ExecutorRegistry& registry) {
  registry.add("make_wire_from_edges_rwire", [](Params, Inputs inputs, const ScalarValues&) {
    return one(make_wire_from_edges_rwire(edges_of(inputs)));
  });
  registry.add("make_face_from_wire_rface", [](Params p, Inputs inputs, const ScalarValues&) {
    return one(make_face_from_wire_rface(input_at(inputs, 0), point(p, "normal")));
  });
  registry.add("make_face_from_wires_rface", [](Params p, Inputs inputs, const ScalarValues&) {
    std::vector<Shape> inner;
    for (std::size_t i = 1; i < inputs.size(); ++i) inner.push_back(inputs[i].shape);
    return one(make_face_from_wires_rface(input_at(inputs, 0), inner, point(p, "normal")));
  });
}

void register_primitives(reactive::ExecutorRegistry& registry) {
  registry.add("make_box_rsolid", [](Params p, Inputs, const ScalarValues&) {
    return one(make_box_rsolid(number(p, "width"), number(p, "height"), number(p, "depth"),
                               point(p, "bottom_face_center")));
  });
  registry.add("make_cylinder_rsolid", [](Params p, Inputs, const ScalarValues&) {
    return one(make_cylinder_rsolid(number(p, "radius"), number(p, "height"), point(p, "bottom_face_center"),
                                    point(p, "axis")));
  });
  registry.add("make_cone_rsolid", [](Params p, Inputs, const ScalarValues&) {
    return one(make_cone_rsolid(number(p, "bottom_radius"), number(p, "height"), number(p, "top_radius"),
                                point(p, "bottom_face_center"), point(p, "axis")));
  });
  registry.add("make_sphere_rsolid", [](Params p, Inputs, const ScalarValues&) {
    return one(make_sphere_rsolid(number(p, "radius"), point(p, "center")));
  });
  registry.add("load_brep_region_rsolid", [](Params p, Inputs, const ScalarValues&) {
    return one(load_brep_region_rsolid(param(p, "path").as_string(), param(p, "sha256").as_string(),
                                       optional_text(p, "tag_prefix")));
  });
  registry.add("load_brep_region_rshell", [](Params p, Inputs, const ScalarValues&) {
    return one(load_brep_region_rshell(param(p, "path").as_string(), param(p, "sha256").as_string(),
                                       optional_text(p, "tag_prefix")));
  });
}

}  // namespace

void register_geometry_executors(reactive::ExecutorRegistry& registry) {
  register_curves(registry);
  register_splines(registry);
  register_assemblies(registry);
  register_primitives(registry);
}

}  // namespace scad
