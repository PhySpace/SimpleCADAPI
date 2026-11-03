// Signature types for bindings that convert their arguments themselves.
//
// Some operations take py::object and check the type inside the operation (the product operators, so a wrong type is
// the operation's SimpleCADError, not a pybind overload error), or read a value the Python way (`str(value)`,
// `int(value)`).  Their signature would read `object`.  `Typed<Name>` keeps the py::object (it accepts anything, as
// before) and prints Name in the signature; `Shown<T, Name>` converts exactly as T does and prints Name.  The body of
// the binding does not change: both convert to what it took before.
//
//   const Typed<PartName>& part        part: simplecadapi._cpp._native.Part     (any object reaches the body)
//   Shown<double, LengthTag> diameter  diameter: simplecadapi.types.Length      (loaded as a double)
//
// A name is a struct with `static constexpr auto name = <pybind descr>`; the class names come from the registered
// types (`type_name<T>()`), so they print the way pybind prints the class itself.
#pragma once

#include <pybind11/pybind11.h>

#include <utility>

#include "semantic_types.hpp"

namespace scad::pybind {

template <class Name>
struct Typed {
  pybind11::object value;
  operator const pybind11::object&() const { return value; }  // NOLINT(google-explicit-constructor)
  bool is_none() const { return value.is_none(); }
  template <class T>
  T cast() const {
    return value.cast<T>();
  }
};

template <class T, class Name>
struct Shown {
  T value;
  operator const T&() const { return value; }  // NOLINT(google-explicit-constructor)
};

// The descr pybind prints for a bound class.
template <class T>
constexpr auto type_name() {
  return pybind11::detail::make_caster<T>::name;
}

// Words for the names.
inline constexpr auto kOr = pybind11::detail::const_name(" | ");
inline constexpr auto kOrNone = pybind11::detail::const_name(" | None");

}  // namespace scad::pybind

// Declares a name struct: SCAD_SIGNATURE_NAME(PartName, type_name<sp::Part>());
#define SCAD_SIGNATURE_NAME(Struct, ...)        \
  struct Struct {                               \
    static constexpr auto name = (__VA_ARGS__); \
  }

namespace pybind11::detail {

template <class Name>
struct type_caster<scad::pybind::Typed<Name>> {
  PYBIND11_TYPE_CASTER(scad::pybind::Typed<Name>, Name::name);

  bool load(handle src, bool /*convert*/) {
    if (!src)
      return false;
    value.value = reinterpret_borrow<object>(src);
    return true;
  }
  static handle cast(const scad::pybind::Typed<Name>& v, return_value_policy, handle) { return v.value.inc_ref(); }
};

template <class T, class Name>
struct type_caster<scad::pybind::Shown<T, Name>> {
  using Self = scad::pybind::Shown<T, Name>;  // the macro takes no comma
  PYBIND11_TYPE_CASTER(Self, Name::name);

  bool load(handle src, bool convert) {
    make_caster<T> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<T&&>(std::move(inner));
    return true;
  }
  static handle cast(const scad::pybind::Shown<T, Name>& v, return_value_policy policy, handle parent) {
    return make_caster<T>::cast(v.value, policy, parent);
  }
};

}  // namespace pybind11::detail
