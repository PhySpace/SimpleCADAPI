// Shapes and checks shared by the ops_features tests.
#pragma once

#include <algorithm>
#include <string>
#include <vector>

#include "doctest.h"
#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/ql/ql.hpp"

namespace scad::feature_test {

inline bool has_tag(const Shape& shape, std::string_view tag) { return shape.has_tag(tag, TagScope::Effective); }

template <class T>
std::size_t count_tagged(const std::vector<T>& shapes, std::string_view tag) {
  return static_cast<std::size_t>(std::count_if(shapes.begin(), shapes.end(), [&](const T& s) { return has_tag(s, tag); }));
}

inline Solid box(double w, double h, double d, const Scalar3& at = scalar3(0, 0, 0)) { return make_box_rsolid(w, h, d, at); }

// The faces of `solid` whose outward normal points along `axis` (0, 1, 2).
inline std::vector<Face> faces_facing(const Solid& solid, int axis) {
  std::vector<Face> out;
  for (const Face& face : solid.faces()) {
    const Vec3 n = face.normal_at();
    if ((axis == 0 ? n.x : axis == 1 ? n.y : n.z) > 0.9) out.push_back(face);
  }
  return out;
}

// The edges of `solid` whose midpoint lies at z within `tolerance` of `z`.
inline std::vector<Edge> edges_at_z(const Solid& solid, double z, double tolerance = 1e-6) {
  std::vector<Edge> out;
  for (const Edge& edge : solid.edges()) {
    if (std::abs(edge.center().z - z) < tolerance) out.push_back(edge);
  }
  return out;
}

// The Error an operation throws; fails the test when it does not.
template <class F>
Error failure_of(F&& call) {
  try {
    call();
  } catch (const Error& e) {
    return e;
  }
  FAIL("the operation did not fail");
  throw 0;
}

inline double measurement(const Error& error, std::string_view name) {
  for (const ErrorMeasurement& m : error.guidance().measurements) {
    if (m.name == name) return std::get<double>(m.value);
  }
  FAIL("no measurement " << name);
  return 0.0;
}

}  // namespace scad::feature_test
