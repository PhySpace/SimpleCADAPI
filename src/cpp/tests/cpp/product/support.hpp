// Shared helpers of the product doctests.
#pragma once

#include <algorithm>
#include <map>
#include <memory>
#include <string>

#include "doctest.h"

#include "scad/ops/geometry/geometry.hpp"
#include "scad/product/product.hpp"
#include "scad/reactive/session.hpp"

namespace scad::product_test {

using namespace scad;
using namespace scad::product;

inline Placement at(double x, double y, double z) {
  return Placement(Vec3{x, y, z});
}

// A unit box Part with a placement connector "axis" at `connector_origin`.
inline PartPtr part_with_axis(const std::string& id, const Vec3& connector_origin = {0, 0, 0}) {
  PartPtr part = make_part_rpart(id, make_box_rsolid(1.0, 1.0, 1.0));
  const Connector axis = make_placement_connector_rconnector("axis", Placement(connector_origin));
  return add_connector_rpart(*part, axis);
}

inline AssemblyPtr with_component(const AssemblyPtr& assembly, const PartPtr& part, const std::string& id,
                                  const Placement& placement = identity_placement()) {
  return add_component_rassembly(*assembly, Item{part}, id, placement);
}

inline ConnectorRef ref(const std::string& component, const std::string& connector = "axis") {
  return make_connector_ref_rconnectorref(component, connector);
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

inline void check_vec(const Vec3& actual, const Vec3& expected, double tolerance = 1e-9) {
  CHECK(actual.x == doctest::Approx(expected.x).epsilon(tolerance).scale(1.0));
  CHECK(actual.y == doctest::Approx(expected.y).epsilon(tolerance).scale(1.0));
  CHECK(actual.z == doctest::Approx(expected.z).epsilon(tolerance).scale(1.0));
}

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

}  // namespace scad::product_test
