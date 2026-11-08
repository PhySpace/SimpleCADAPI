// explode_rassembly: the placements of an assembly pushed apart, for an exploded view.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <set>

#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/transforms.hpp"
#include "scad/product/guard.hpp"
#include "scad/product/operators.hpp"
#include "record.hpp"

namespace scad::product {

using namespace detail;

namespace {

struct Box {
  Vec3 low{0, 0, 0}, high{0, 0, 0};
  bool empty = true;

  void add(const Vec3& p) {
    if (empty) {
      low = high = p;
      empty = false;
      return;
    }
    low = {std::min(low.x, p.x), std::min(low.y, p.y), std::min(low.z, p.z)};
    high = {std::max(high.x, p.x), std::max(high.y, p.y), std::max(high.z, p.z)};
  }
  void add(const Box& other) {
    if (other.empty)
      return;
    add(other.low);
    add(other.high);
  }
  Vec3 center() const { return (low + high) * 0.5; }
  double diagonal() const { return (high - low).norm(); }
};

// The box of every Part body below `item`, placed by `placement` (in the frame the placement maps into).
void collect_box(const Item& item, const Placement& placement, Box& box) {
  if (const auto* part = std::get_if<PartPtr>(&item)) {
    const TopoDS_Shape placed = kernel::place_shape((*part)->body().wrapped(), placement.origin(), placement.x_axis(),
                                                    placement.y_axis(), placement.z_axis());
    const kernel::BoundingBox b = kernel::bounding_box(placed);
    box.add(Vec3{b.xmin, b.ymin, b.zmin});
    box.add(Vec3{b.xmax, b.ymax, b.zmax});
    return;
  }
  for (const Component& component : std::get<AssemblyPtr>(item)->components())
    collect_box(component.item, placement.compose(component.placement), box);
}

// "c0, c1, c2" (at most eight, then "...").
std::string list_ids(const std::vector<std::string>& ids) {
  if (ids.empty())
    return "none";
  std::string out;
  for (std::size_t i = 0; i < ids.size() && i < 8; ++i)
    out += (i == 0 ? "" : ", ") + ids[i];
  return ids.size() > 8 ? out + ", ..." : out;
}

std::string number_text(double value) {
  char buffer[32];
  std::snprintf(buffer, sizeof buffer, "%.6g", value);
  return buffer;
}

Value vec_value(const Vec3& v) {
  return Value(Value::Array{Value(v.x), Value(v.y), Value(v.z)});
}

Vec3 unit_of(const Vec3& v, const std::string& what) {
  if (!v.is_finite() || v.norm() < 1e-12)
    throw ValueError(what + " must be a finite, nonzero vector, got " + to_string(v));
  return v.normalized();
}

}  // namespace

AssemblyPtr explode_rassembly(const Assembly& assembly, const Scalar& factor_value, const std::optional<Vec3>& center,
                              const std::optional<Vec3>& axis, const std::map<std::string, Vec3>& directions,
                              const std::map<std::string, double>& weights) {
  return guard_operation("explode_rassembly", [&] {
    const double factor = factor_value.value();
    if (!std::isfinite(factor))
      throw ValueError("factor must be a finite number, got " + number_text(factor));
    if (center && !center->is_finite())
      throw ValueError("center must be a finite point, got " + to_string(*center));
    std::optional<Vec3> axis_unit;
    if (axis)
      axis_unit = unit_of(*axis, "axis");
    const std::vector<std::string> ids = assembly.component_ids();
    const std::set<std::string> known(ids.begin(), ids.end());
    std::map<std::string, Vec3> unit_directions;
    for (const auto& [id, direction] : directions) {
      if (known.count(id) == 0)
        throw ValueError("directions names '" + id + "', which is not a component of assembly '" +
                         assembly.assembly_id() + "' (components: " + list_ids(ids) + ")");
      unit_directions[id] = unit_of(direction, "the direction of component '" + id + "'");
    }
    for (const auto& [id, weight] : weights) {
      if (known.count(id) == 0)
        throw ValueError("weights names '" + id + "', which is not a component of assembly '" + assembly.assembly_id() +
                         "' (components: " + list_ids(ids) + ")");
      if (!std::isfinite(weight))
        throw ValueError("the weight of component '" + id + "' must be a finite number, got " + number_text(weight));
    }

    // where each component is: the centre of the box of its bodies (its origin when it holds none)
    std::map<std::string, Vec3> centers;
    Box all;
    for (const Component& component : assembly.components()) {
      Box box;
      collect_box(component.item, component.placement, box);
      if (box.empty)
        box.add(component.placement.origin());
      centers[component.component_id] = box.center();
      all.add(box);
    }
    const Vec3 middle = center ? *center : all.center();
    const double size = all.diagonal();
    if (!assembly.components().empty() && size < 1e-12)
      throw ValueError("the components of assembly '" + assembly.assembly_id() +
                       "' occupy a single point: there is no size to scale the explosion by");

    auto result = std::make_shared<const Assembly>(assembly);
    Value moved = Value::object();
    Value stationary = Value(Value::Array{});
    for (const Component& component : assembly.components()) {
      const std::string& id = component.component_id;
      const Vec3 from_middle = centers.at(id) - middle;
      Vec3 direction;  // zero: the component has none and stays
      if (const auto given = unit_directions.find(id); given != unit_directions.end()) {
        direction = given->second;
      } else if (axis_unit) {
        const double along = from_middle.dot(*axis_unit);
        if (std::abs(along) > 1e-9 * size)
          direction = *axis_unit * (along > 0.0 ? 1.0 : -1.0);
      } else if (from_middle.norm() > 1e-9 * size) {
        direction = from_middle.normalized();
      }
      const auto weight = weights.find(id);
      const Vec3 shift = direction * (factor * (weight == weights.end() ? 1.0 : weight->second) * size);
      if (direction.norm() == 0.0)
        stationary.as_array().emplace_back(id);
      moved.set(id, vec_value(shift));
      const Placement& p = component.placement;
      result = std::make_shared<const Assembly>(result->with_component_placement(
          id, Placement::from_exact_frame(p.origin() + shift, p.x_axis(), p.y_axis(), p.z_axis())));
    }

    Value info = Value::object();
    info.set("factor", factor);
    info.set("size", size);
    info.set("center", vec_value(middle));
    info.set("displacements", moved);
    info.set("stationary", stationary);
    result->set_metadata("explode", info);

    record_value(
        [&] {
          Value params = Value::object();
          params.set("assembly_id", assembly.assembly_id());
          params.set("factor", factor);
          params.set("center", center ? vec_value(*center) : Value());
          params.set("axis", axis ? vec_value(*axis) : Value());
          Value dir_params = Value::object();
          for (const auto& [id, direction] : directions)
            dir_params.set(id, vec_value(direction));
          params.set("directions", std::move(dir_params));
          Value weight_params = Value::object();
          for (const auto& [id, weight] : weights)
            weight_params.set(id, weight);
          params.set("weights", std::move(weight_params));
          OpRecord record = op_record("explode_rassembly", std::move(params));
          if (factor_value.symbolic())
            record.symbolic.emplace_back("factor", factor_value);
          record.semantic_delta = semantic_modified("Assembly", assembly.assembly_id(), info);
          return record;
        },
        result, assembly);
    return result;
  });
}

}  // namespace scad::product
