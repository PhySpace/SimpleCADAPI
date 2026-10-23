#include "scad/core/vec.hpp"

#include <cstdio>

namespace scad {

std::string to_string(const Vec3& v) {
  char buf[128];
  std::snprintf(buf, sizeof buf, "(%.17g, %.17g, %.17g)", v.x, v.y, v.z);
  return buf;
}

}  // namespace scad
