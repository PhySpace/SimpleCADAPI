#include "scad/core/scalar.hpp"

#include <cmath>

#include "scad/core/error.hpp"

namespace scad {

namespace {
thread_local const Bindings* g_ambient = nullptr;
}

const Bindings* ambient_bindings() noexcept { return g_ambient; }

AmbientBindingsScope::AmbientBindingsScope(const Bindings* bindings) noexcept : previous_(g_ambient) { g_ambient = bindings; }
AmbientBindingsScope::~AmbientBindingsScope() { g_ambient = previous_; }

double Scalar::value(const Bindings* bindings) const {
  return expr_ ? expr_->eval(bindings != nullptr ? bindings : g_ambient) : value_;
}

double evaluate_scalar(const Scalar& s, std::string_view label, const Bindings* bindings) {
  const double v = s.value(bindings);
  if (!std::isfinite(v)) {
    throw ValueError(std::string(label) + " must be a finite number, got " +
                     (std::isnan(v) ? "nan" : (v > 0 ? "inf" : "-inf")));
  }
  return v;
}

}  // namespace scad
