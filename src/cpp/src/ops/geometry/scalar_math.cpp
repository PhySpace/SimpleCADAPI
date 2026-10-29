#include "scad/ops/geometry/scalar_math.hpp"

#include "scad/reactive/expr.hpp"

namespace scad {

namespace {

using reactive::Sym;

template <class Literal, class Symbolic>
Num combine(const Num& a, const Num& b, Literal literal, Symbolic symbolic) {
  if (!a.symbolic() && !b.symbolic())
    return Num(literal(a.literal(), b.literal()));
  return Num(symbolic(Sym(a.scalar()), Sym(b.scalar())).scalar());
}

}  // namespace

Num operator+(const Num& a, const Num& b) {
  return combine(a, b, [](double x, double y) { return x + y; }, [](const Sym& x, const Sym& y) { return x + y; });
}
Num operator-(const Num& a, const Num& b) {
  return combine(a, b, [](double x, double y) { return x - y; }, [](const Sym& x, const Sym& y) { return x - y; });
}
Num operator*(const Num& a, const Num& b) {
  return combine(a, b, [](double x, double y) { return x * y; }, [](const Sym& x, const Sym& y) { return x * y; });
}
Num operator/(const Num& a, const Num& b) {
  return combine(a, b, [](double x, double y) { return x / y; }, [](const Sym& x, const Sym& y) { return x / y; });
}
Num operator-(const Num& a) {
  if (!a.symbolic())
    return Num(-a.literal());
  return Num((-Sym(a.scalar())).scalar());
}

}  // namespace scad
