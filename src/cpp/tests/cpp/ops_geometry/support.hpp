// Shared helpers of the ops_geometry doctests.
#pragma once

#include <string>
#include <vector>

#include "doctest.h"

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/reactive/session.hpp"
#include "scad/topo/shape.hpp"

namespace scad::geometry_test {

inline bool has_tag(const Shape& shape, const std::string& tag) {
  return shape.has_tag(tag, TagScope::Local);
}

template <class Handles>
int count_with_tag(const Handles& handles, const std::string& tag) {
  int count = 0;
  for (const auto& handle : handles)
    count += has_tag(handle, tag) ? 1 : 0;
  return count;
}

// The error an operator throws, or null.
template <class F>
std::unique_ptr<Error> failure_of(F&& call) {
  try {
    call();
  } catch (const Error& e) {
    return std::make_unique<Error>(e);
  }
  return nullptr;
}

inline void check_box(const Shape& shape, const Vec3& lo, const Vec3& hi, double tol = 1e-7) {
  const auto b = shape.bounding_box();
  CHECK(b.xmin == doctest::Approx(lo.x).epsilon(tol));
  CHECK(b.ymin == doctest::Approx(lo.y).epsilon(tol));
  CHECK(b.zmin == doctest::Approx(lo.z).epsilon(tol));
  CHECK(b.xmax == doctest::Approx(hi.x).epsilon(tol));
  CHECK(b.ymax == doctest::Approx(hi.y).epsilon(tol));
  CHECK(b.zmax == doctest::Approx(hi.z).epsilon(tol));
}

// A recorder installed for the lifetime of the object.
struct Recording {
  reactive::Session session;
  Recording() { session.start(); }
  ~Recording() { session.stop(); }
  std::vector<std::string> ops() const {
    std::vector<std::string> out;
    for (const auto& node : session.graph().nodes())
      out.push_back(node->op);
    return out;
  }
};

}  // namespace scad::geometry_test
