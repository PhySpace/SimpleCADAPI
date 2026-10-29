// Forward-mode automatic differentiation over a fixed number of local slots.
//
// Every equation of the sketch system depends on a handful of unknowns (a
// tangent between a cubic and a line touches twelve at most), so a Dual carries
// its value and the partials with respect to those local slots.  The solver
// maps the slots back to global unknown indices (see system.hpp).
#pragma once

#include <array>
#include <cmath>

namespace scad::sketch_solver {

// Capacity of one equation's support.  Lowering fails with a clear error when
// an equation needs more.
inline constexpr int kSlots = 20;

struct Dual {
  double v = 0.0;
  std::array<double, kSlots> g{};

  Dual() = default;
  Dual(double constant) : v(constant) {}  // NOLINT(google-explicit-constructor)
};

inline Dual operator+(const Dual& a, const Dual& b) {
  Dual r(a.v + b.v);
  for (int i = 0; i < kSlots; ++i)
    r.g[static_cast<std::size_t>(i)] = a.g[static_cast<std::size_t>(i)] + b.g[static_cast<std::size_t>(i)];
  return r;
}
inline Dual operator-(const Dual& a, const Dual& b) {
  Dual r(a.v - b.v);
  for (int i = 0; i < kSlots; ++i)
    r.g[static_cast<std::size_t>(i)] = a.g[static_cast<std::size_t>(i)] - b.g[static_cast<std::size_t>(i)];
  return r;
}
inline Dual operator-(const Dual& a) {
  Dual r(-a.v);
  for (int i = 0; i < kSlots; ++i)
    r.g[static_cast<std::size_t>(i)] = -a.g[static_cast<std::size_t>(i)];
  return r;
}
inline Dual operator*(const Dual& a, const Dual& b) {
  Dual r(a.v * b.v);
  for (int i = 0; i < kSlots; ++i) {
    const auto k = static_cast<std::size_t>(i);
    r.g[k] = a.g[k] * b.v + b.g[k] * a.v;
  }
  return r;
}
inline Dual operator/(const Dual& a, const Dual& b) {
  const double inverse = 1.0 / b.v;
  Dual r(a.v * inverse);
  for (int i = 0; i < kSlots; ++i) {
    const auto k = static_cast<std::size_t>(i);
    r.g[k] = (a.g[k] - r.v * b.g[k]) * inverse;
  }
  return r;
}

// d|x|/dx is taken as 0 at x = 0 (a zero-length vector has no direction): the
// solver then sees a flat residual instead of NaN and the damping handles it.
inline Dual sqrt(const Dual& a) {
  if (!(a.v > 0.0))
    return Dual(0.0);
  const double root = std::sqrt(a.v);
  Dual r(root);
  const double scale = 0.5 / root;
  for (int i = 0; i < kSlots; ++i)
    r.g[static_cast<std::size_t>(i)] = a.g[static_cast<std::size_t>(i)] * scale;
  return r;
}

}  // namespace scad::sketch_solver
