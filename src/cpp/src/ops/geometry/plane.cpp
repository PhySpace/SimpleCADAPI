#include "scad/ops/geometry/plane.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <string>

#include <gp_Ax2.hxx>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"

namespace scad {

PlaneAxes orthonormal_plane_axes(const Vec3& normal) {
  const double norm = normal.norm();
  if (norm <= 1e-12) throw ValueError("The normal vector cannot be a zero vector");
  const Vec3 z = normal / norm;
  const Vec3 reference = std::abs(z.z) > 0.9 ? Vec3{1.0, 0.0, 0.0} : Vec3{0.0, 0.0, 1.0};
  // Gram-Schmidt: the reference stays away from z, so the projection never degenerates.
  Vec3 x = reference - z * reference.dot(z);
  const double x_norm = x.norm();
  if (x_norm <= 1e-12) throw ValueError("Cannot build a local coordinate system from the given normal vector");
  x = x / x_norm;
  Vec3 y = z.cross(x);
  y = y / y.norm();
  return {z, x, y};
}

Vec3 default_plane_x_direction(const Vec3& normal) {
  return occt_guard([&] {
    const gp_Ax2 axes(gp_Pnt(0.0, 0.0, 0.0), kernel::to_dir(normal, "normal"));
    return kernel::from_dir(axes.XDirection());
  });
}

namespace {

Vec3 member_or(const Value& plane, const char* key, const Vec3& fallback) {
  const Value* member = plane.find(key);
  if (member == nullptr) return fallback;
  if (!member->is_array() || member->as_array().size() != 3) {
    throw ValueError("Sketch plane origin and axes must be 3-vectors");
  }
  const auto& items = member->as_array();
  return {items[0].as_double(), items[1].as_double(), items[2].as_double()};
}

PlaneFrame named_plane(std::string token) {
  std::transform(token.begin(), token.end(), token.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  if (token == "XY") return {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
  if (token == "XZ") return {{0, 0, 0}, {1, 0, 0}, {0, 0, 1}};
  if (token == "YZ") return {{0, 0, 0}, {0, 1, 0}, {0, 0, 1}};
  throw ValueError("Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping");
}

}  // namespace

PlaneFrame sketch_plane_in_current_coordinates(const Value& plane) {
  PlaneFrame local;
  if (plane.is_string()) {
    local = named_plane(plane.as_string());
  } else if (plane.is_object()) {
    local = {member_or(plane, "origin", {0, 0, 0}), member_or(plane, "x_axis", {1, 0, 0}),
             member_or(plane, "y_axis", {0, 1, 0})};
  } else {
    throw ValueError("Sketch plane must be 'XY', 'XZ', 'YZ', or a plane mapping");
  }
  const CoordinateSystem& cs = current_cs();
  return {cs.transform_point(local.origin), cs.transform_vector(local.x_axis), cs.transform_vector(local.y_axis)};
}

}  // namespace scad
