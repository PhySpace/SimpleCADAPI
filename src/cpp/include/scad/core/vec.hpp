// Small value types for 3D points/vectors.  No OCCT here: conversions live in
// scad/kernel/convert.hpp.
#pragma once

#include <array>
#include <cmath>
#include <string>

namespace scad {

inline constexpr double kPi = 3.14159265358979323846264338327950288;

struct Vec3 {
  double x = 0.0;
  double y = 0.0;
  double z = 0.0;

  constexpr Vec3() = default;
  constexpr Vec3(double x_, double y_, double z_) : x(x_), y(y_), z(z_) {}
  constexpr explicit Vec3(const std::array<double, 3>& a) : x(a[0]), y(a[1]), z(a[2]) {}

  constexpr std::array<double, 3> array() const { return {x, y, z}; }

  constexpr Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
  constexpr Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
  constexpr Vec3 operator-() const { return {-x, -y, -z}; }
  constexpr Vec3 operator*(double s) const { return {x * s, y * s, z * s}; }
  constexpr Vec3 operator/(double s) const { return {x / s, y / s, z / s}; }
  Vec3& operator+=(const Vec3& o) {
    x += o.x;
    y += o.y;
    z += o.z;
    return *this;
  }
  Vec3& operator-=(const Vec3& o) {
    x -= o.x;
    y -= o.y;
    z -= o.z;
    return *this;
  }
  Vec3& operator*=(double s) {
    x *= s;
    y *= s;
    z *= s;
    return *this;
  }

  constexpr bool operator==(const Vec3& o) const { return x == o.x && y == o.y && z == o.z; }
  constexpr bool operator!=(const Vec3& o) const { return !(*this == o); }

  constexpr double dot(const Vec3& o) const { return x * o.x + y * o.y + z * o.z; }
  constexpr Vec3 cross(const Vec3& o) const { return {y * o.z - z * o.y, z * o.x - x * o.z, x * o.y - y * o.x}; }
  double norm() const { return std::sqrt(dot(*this)); }
  double distance(const Vec3& o) const { return (*this - o).norm(); }
  bool is_finite() const { return std::isfinite(x) && std::isfinite(y) && std::isfinite(z); }

  // Unit vector, or zero vector when the length is 0 (callers check).
  Vec3 normalized() const {
    const double n = norm();
    return n == 0.0 ? Vec3{} : Vec3{x / n, y / n, z / n};
  }
};

constexpr Vec3 operator*(double s, const Vec3& v) {
  return v * s;
}

// "(x, y, z)" with Python's repr-style shortest float form is not needed
// anywhere that matters; %.17g keeps the value exact.
std::string to_string(const Vec3& v);

}  // namespace scad
