#include "scad/ops/geometry/types.hpp"

namespace scad {

Vec3 evaluate_point(const Scalar3& point, std::string_view label) {
  const std::string name(label);
  return {evaluate_scalar(point[0], name + "[0]"), evaluate_scalar(point[1], name + "[1]"),
          evaluate_scalar(point[2], name + "[2]")};
}

}  // namespace scad
