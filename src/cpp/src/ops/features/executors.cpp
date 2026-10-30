// Executors of the feature operations: rebuild an output from the recorded parameters and the
// current inputs (reactive/registry.hpp).  Each calls the public operator, with the numbers the
// recorder holds now; the tags the original call asked for are separate recorded nodes.
#include "scad/ops/features/executors.hpp"

#include <string>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"

namespace scad {

namespace {

using Params = const Value&;
using Inputs = const std::vector<OpInput>&;
using reactive::ScalarValues;

// ---- reading what was recorded ---------------------------------------------------------------
const Value& param(Params params, std::string_view key) {
  const Value* found = params.find(key);
  if (found == nullptr)
    throw ValueError("recorded parameter '" + std::string(key) + "' is missing");
  return *found;
}

Scalar number(Params p, std::string_view key) {
  return Scalar(param(p, key).as_double());
}
double real(Params p, std::string_view key) {
  return param(p, key).as_double();
}
bool flag(Params p, std::string_view key) {
  return param(p, key).as_bool();
}
std::string text(Params p, std::string_view key) {
  return param(p, key).as_string();
}

Vec3 vec_of(const Value& value) {
  const Value::Array& items = value.as_array();
  if (items.size() != 3)
    throw ValueError("a recorded vector must have three coordinates");
  return {items[0].as_double(), items[1].as_double(), items[2].as_double()};
}
Scalar3 point(Params p, std::string_view key) {
  return scalar3(vec_of(param(p, key)));
}

const Shape& input(Inputs inputs, std::size_t index) {
  if (index >= inputs.size())
    throw ValueError("the operation lost an input");
  return inputs[index].shape;
}

// The inputs from `first` on, as shapes of one kind.
template <class T>
std::vector<T> rest(Inputs inputs, std::size_t first, std::size_t last) {
  std::vector<T> out;
  for (std::size_t i = first; i < last && i < inputs.size(); ++i)
    out.emplace_back(inputs[i].shape);
  return out;
}

std::vector<Shape> one(const Shape& shape) {
  return {shape};
}
std::vector<Shape> many(const std::vector<Solid>& solids) {
  return std::vector<Shape>(solids.begin(), solids.end());
}

// ---- sweeps and local features --------------------------------------------------------------
void register_sweeps(reactive::ExecutorRegistry& registry) {
  registry.add("make_extrude_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(extrude_rsolid(input(in, 0), point(p, "direction"), number(p, "distance")));
  });
  registry.add("make_revolve_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(revolve_rsolid(input(in, 0), point(p, "axis"), number(p, "angle"), point(p, "origin")));
  });
  registry.add("make_loft_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    std::vector<Shape> profiles;
    for (const OpInput& i : in)
      profiles.push_back(i.shape);
    return one(loft_rsolid(profiles, flag(p, "ruled"), {text(p, "tracking_policy"), {}}));
  });
  registry.add("make_sweep_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(sweep_rsolid(Face(input(in, 0)), Wire(input(in, 1)), flag(p, "is_frenet")));
  });
  registry.add("make_twisted_sweep_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    TwistedSweepOptions options;
    options.guide_radius = number(p, "guide_radius");
    return one(twisted_sweep_rsolid(input(in, 0), number(p, "distance"), number(p, "twist_angle"), point(p, "axis"),
                                    point(p, "origin"), options));
  });
  registry.add("make_extrude_taper_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(extrude_taper_rsolid(Face(input(in, 0)), point(p, "vector"), number(p, "taper"), flag(p, "flip_inner")));
  });
  registry.add("make_extrude_until_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(extrude_until_rsolid(Face(input(in, 0)), rest<Solid>(in, 1, in.size()), point(p, "direction"),
                                    text(p, "until")));
  });
  registry.add("make_sweep_multisection_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    const auto count = static_cast<std::size_t>(param(p, "profile_count").as_int());
    std::vector<Shape> profiles;
    for (std::size_t i = 0; i < count; ++i)
      profiles.push_back(input(in, i));
    std::optional<Binormal> binormal;
    if (const Value* wire = p.find("binormal_is_wire"); wire != nullptr && wire->is_bool() && wire->as_bool()) {
      binormal = Binormal(Wire(input(in, count + 1)));
    } else if (!param(p, "binormal").is_null()) {
      binormal = Binormal(point(p, "binormal"));
    }
    return one(sweep_multisection_rsolid(profiles, Wire(input(in, count)), flag(p, "is_frenet"), binormal));
  });
}

void register_blends(reactive::ExecutorRegistry& registry) {
  registry.add("make_fillet_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(fillet_rsolid(Solid(input(in, 0)), rest<Edge>(in, 1, in.size()), number(p, "radius")));
  });
  registry.add("make_chamfer_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    ChamferOptions options;
    if (!param(p, "angle").is_null())
      options.angle = real(p, "angle");
    if (!param(p, "reference_direction").is_null())
      options.reference_direction = vec_of(param(p, "reference_direction"));
    return one(chamfer_rsolid(Solid(input(in, 0)), rest<Edge>(in, 1, in.size()), number(p, "distance"), options));
  });
  registry.add("make_shell_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(shell_rsolid(Solid(input(in, 0)), rest<Face>(in, 1, in.size()), number(p, "thickness")));
  });
  registry.add("make_offset_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(offset_rsolid(Solid(input(in, 0)), number(p, "amount"), rest<Face>(in, 1, in.size()),
                             {real(p, "tolerance"), text(p, "kind")}));
  });
  registry.add("make_draft_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(draft_rsolid(Solid(input(in, 0)), rest<Face>(in, 1, in.size()), number(p, "angle"),
                            point(p, "plane_origin"), point(p, "plane_normal")));
  });
}

// ---- booleans -----------------------------------------------------------------------------------
void register_booleans(reactive::ExecutorRegistry& registry) {
  registry.add("make_union_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    UnionOptions options;
    options.clean = flag(p, "clean");
    options.glue = flag(p, "glue");
    options.tol = real(p, "tol");
    options.tracking_policy = text(p, "tracking_policy");
    return one(union_rsolid(rest<Solid>(in, 0, in.size()), options));
  });
  registry.add("make_cut_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(
        cut_rsolid(rest<Solid>(in, 0, in.size()), {flag(p, "skip_non_intersecting"), text(p, "tracking_policy")}));
  });
  registry.add("make_cut_rsolid_list", [](Params p, Inputs in, const ScalarValues&) {
    return many(
        cut_rsolid_list(rest<Solid>(in, 0, in.size()), {flag(p, "skip_non_intersecting"), text(p, "tracking_policy")}));
  });
  registry.add("make_intersect_rsolid", [](Params, Inputs in, const ScalarValues&) {
    return one(intersect_rsolid(rest<Solid>(in, 0, in.size())));
  });
  registry.add("make_boolean_rsolidlist", [](Params p, Inputs in, const ScalarValues&) {
    const auto left = static_cast<std::size_t>(param(p, "left_count").as_int());
    return many(boolean_rsolidlist(rest<Solid>(in, 0, left), rest<Solid>(in, left, in.size()), text(p, "operation")));
  });
  registry.add("make_2d_cut_rface", [](Params, Inputs in, const ScalarValues&) {
    return one(make_2d_cut_rface(input(in, 0), input(in, 1)));
  });
  registry.add("make_2d_union_rface", [](Params, Inputs in, const ScalarValues&) {
    return one(make_2d_union_rface(input(in, 0), input(in, 1)));
  });
  registry.add("make_2d_intersect_rface", [](Params, Inputs in, const ScalarValues&) {
    return one(make_2d_intersect_rface(input(in, 0), input(in, 1)));
  });
}

// ---- transforms and patterns ----------------------------------------------------------------------
void register_transforms(reactive::ExecutorRegistry& registry) {
  registry.add("make_translate_rshape", [](Params p, Inputs in, const ScalarValues&) {
    return one(translate_shape(input(in, 0), point(p, "vector")));
  });
  registry.add("make_rotate_rshape", [](Params p, Inputs in, const ScalarValues&) {
    return one(rotate_shape(input(in, 0), number(p, "angle"), point(p, "axis"), point(p, "origin")));
  });
  registry.add("make_mirror_rshape", [](Params p, Inputs in, const ScalarValues&) {
    return one(mirror_shape(input(in, 0), point(p, "plane_origin"), point(p, "plane_normal")));
  });
  registry.add("make_scale_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    return one(scale_rsolid(Solid(input(in, 0)), point(p, "factors"), point(p, "center")));
  });
  registry.add("make_transform_rsolid", [](Params p, Inputs in, const ScalarValues&) {
    std::vector<std::vector<Scalar>> matrix;
    for (const Value& row : param(p, "matrix").as_array()) {
      std::vector<Scalar>& cells = matrix.emplace_back();
      for (const Value& cell : row.as_array())
        cells.emplace_back(cell.as_double());
    }
    return one(transform_rsolid(Solid(input(in, 0)), matrix));
  });
  registry.add("linear_pattern", [](Params p, Inputs in, const ScalarValues&) {
    return linear_pattern_rsolidlist(input(in, 0), point(p, "direction"), static_cast<int>(param(p, "count").as_int()),
                                     number(p, "spacing"));
  });
  registry.add("radial_pattern", [](Params p, Inputs in, const ScalarValues&) {
    return radial_pattern_rsolidlist(input(in, 0), point(p, "center"), point(p, "axis"),
                                     static_cast<int>(param(p, "count").as_int()), number(p, "total_rotation_angle"));
  });
}

}  // namespace

void register_features_executors(reactive::ExecutorRegistry& registry) {
  register_sweeps(registry);
  register_blends(registry);
  register_booleans(registry);
  register_transforms(registry);
}

}  // namespace scad
