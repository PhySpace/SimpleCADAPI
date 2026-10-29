#include "scad/product/placement.hpp"

#include <cmath>

#include "scad/core/error.hpp"
#include "scad/product/validation.hpp"

namespace scad::product {

namespace {

constexpr double kAxisTolerance = 1e-9;
constexpr double kOrthogonalTolerance = 1e-7;
constexpr double kExactTolerance = 2.0e-6;

Vec3 normalize_axis(const Vec3& value, const char* field) {
  const Vec3 vec = finite_vec3(value, field);
  const double length = vec.norm();
  if (length <= kAxisTolerance)
    throw ValueError(std::string(field) + " must be a non-zero vector");
  return {vec.x / length, vec.y / length, vec.z / length};
}

}  // namespace

Placement::Placement(Vec3 origin, Vec3 x_axis, Vec3 y_axis) {
  origin_ = finite_vec3(origin, "origin");
  x_ = normalize_axis(x_axis, "x_axis");
  y_ = normalize_axis(y_axis, "y_axis");
  if (std::abs(x_.dot(y_)) > kOrthogonalTolerance)
    throw ValueError("x_axis and y_axis must be orthogonal");
  const Vec3 z = x_.cross(y_);
  const double z_norm = z.norm();
  if (z_norm <= kAxisTolerance)
    throw ValueError("x_axis and y_axis must define a right-handed frame");
  z_ = {z.x / z_norm, z.y / z_norm, z.z / z_norm};
}

Placement::Placement(Exact, const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis, const Vec3& z_axis)
    : origin_(origin), x_(x_axis), y_(y_axis), z_(z_axis) {}

Placement Placement::from_exact_frame(const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis, const Vec3& z_axis) {
  const Vec3 o = finite_vec3(origin, "origin");
  const Vec3 x = finite_vec3(x_axis, "x_axis");
  const Vec3 y = finite_vec3(y_axis, "y_axis");
  const Vec3 z = finite_vec3(z_axis, "z_axis");
  const std::pair<const char*, Vec3> axes[] = {{"x_axis", x}, {"y_axis", y}, {"z_axis", z}};
  for (const auto& [name, axis] : axes) {
    if (std::abs(axis.norm() - 1.0) > kExactTolerance)
      throw ValueError(std::string(name) + " must be a unit vector");
  }
  const std::pair<const char*, double> dots[] = {
      {"x_axis/y_axis", x.dot(y)}, {"x_axis/z_axis", x.dot(z)}, {"y_axis/z_axis", y.dot(z)}};
  for (const auto& [name, dot] : dots) {
    if (std::abs(dot) > kExactTolerance)
      throw ValueError(std::string(name) + " must be orthogonal");
  }
  if (x.cross(y).dot(z) <= 0.9)
    throw ValueError("axes must define a right-handed frame");
  return Placement(Exact{}, o, x, y, z);
}

Vec3 Placement::transform_point(const Vec3& point) const {
  const Vec3 local = finite_vec3(point, "point");
  return {origin_.x + local.x * x_.x + local.y * y_.x + local.z * z_.x,
          origin_.y + local.x * x_.y + local.y * y_.y + local.z * z_.y,
          origin_.z + local.x * x_.z + local.y * y_.z + local.z * z_.z};
}

Vec3 Placement::transform_vector(const Vec3& vector) const {
  const Vec3 local = finite_vec3(vector, "vector");
  return {local.x * x_.x + local.y * y_.x + local.z * z_.x, local.x * x_.y + local.y * y_.y + local.z * z_.y,
          local.x * x_.z + local.y * y_.z + local.z * z_.z};
}

Placement Placement::compose(const Placement& child) const {
  return Placement(transform_point(child.origin_), transform_vector(child.x_), transform_vector(child.y_));
}

Value Placement::to_dict() const {
  Value out = Value::object();
  out.set("origin", to_array(origin_));
  out.set("x_axis", to_array(x_));
  out.set("y_axis", to_array(y_));
  out.set("z_axis", to_array(z_));
  return out;
}

bool Placement::operator==(const Placement& other) const noexcept {
  return origin_ == other.origin_ && x_ == other.x_ && y_ == other.y_ && z_ == other.z_;
}

Placement identity_placement() {
  return Placement(Vec3{0, 0, 0});
}

Placement inverse_placement(const Placement& placement) {
  const Vec3& o = placement.origin();
  const Vec3& x = placement.x_axis();
  const Vec3& y = placement.y_axis();
  const Vec3& z = placement.z_axis();
  return Placement(Vec3{-o.dot(x), -o.dot(y), -o.dot(z)}, Vec3{x.x, y.x, z.x}, Vec3{x.y, y.y, z.y});
}

Placement relative_placement(const Placement& base, const Placement& target) {
  return inverse_placement(base).compose(target);
}

Placement rotate_z_placement(double angle_degrees) {
  const double angle = finite_float(angle_degrees, "angle_degrees") * (kPi / 180.0);
  const double c = std::cos(angle);
  const double s = std::sin(angle);
  return Placement(Vec3{0, 0, 0}, Vec3{c, s, 0}, Vec3{-s, c, 0});
}

Placement translate_z_placement(double distance) {
  return Placement(Vec3{0, 0, finite_float(distance, "distance")});
}

}  // namespace scad::product
