#include "scad/std/validation.hpp"

#include <cmath>
#include <string>

#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"

namespace scad::stdlib {

double validate_positive(std::string_view name, double value) {
  if (!std::isfinite(value))
    throw ValueError(std::string(name) + " must be finite");
  if (value <= 0.0)
    throw ValueError(std::string(name) + " must be positive");
  return value;
}

double validate_non_negative(std::string_view name, double value) {
  if (!std::isfinite(value))
    throw ValueError(std::string(name) + " must be finite");
  if (value < 0.0)
    throw ValueError(std::string(name) + " must be non-negative");
  return value;
}

double positive_finite(std::string_view name, double value) {
  if (!std::isfinite(value) || value <= 0.0)
    throw ValueError(std::string(name) + " must be positive and finite");
  return value;
}

double non_negative_finite(std::string_view name, double value) {
  if (!std::isfinite(value) || value < 0.0)
    throw ValueError(std::string(name) + " must be non-negative and finite");
  return value;
}

double radians(double deg) noexcept {
  return deg * (kPi / 180.0);
}
double degrees(double rad) noexcept {
  return rad * (180.0 / kPi);
}

}  // namespace scad::stdlib
