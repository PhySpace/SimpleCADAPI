#include "scad/kernel/convert.hpp"

#include <string>

#include "scad/core/error.hpp"

namespace scad::kernel {

gp_Dir to_dir(const Vec3& v, const char* what) {
  if (!v.is_finite() || v.norm() <= 1e-15) {
    throw ValueError(std::string(what) + " must be a finite, non-zero vector, got " + scad::to_string(v));
  }
  return gp_Dir(v.x, v.y, v.z);
}

}  // namespace scad::kernel
