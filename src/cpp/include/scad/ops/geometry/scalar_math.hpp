// Arithmetic on "a float or an expression", the way Python does it.
//
// `center[0] + dx * 0.5` is a float when every operand is a float and an `Expr` as soon
// as one is symbolic.  The session path of the profile makers (rectangle, ...) records
// its edges with such mixed values, so a literal model records plain numbers and a
// parametric one records expressions of its variables.  `Num` keeps that rule; the
// reactive `Sym` would turn even literals into expression nodes.
#pragma once

#include "scad/core/scalar.hpp"

namespace scad {

class Num {
 public:
  Num(double value) noexcept : scalar_(value) {}   // NOLINT(google-explicit-constructor)
  Num(int value) noexcept : scalar_(value) {}      // NOLINT(google-explicit-constructor)
  Num(Scalar scalar) : scalar_(std::move(scalar)) {}  // NOLINT(google-explicit-constructor)

  bool symbolic() const noexcept { return scalar_.symbolic(); }
  const Scalar& scalar() const noexcept { return scalar_; }
  // The literal of a non-symbolic value.
  double literal() const noexcept { return scalar_.literal(); }

 private:
  Scalar scalar_;
};

Num operator+(const Num& a, const Num& b);
Num operator-(const Num& a, const Num& b);
Num operator*(const Num& a, const Num& b);
Num operator/(const Num& a, const Num& b);
Num operator-(const Num& a);

}  // namespace scad
