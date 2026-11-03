// What a parameter means, in the signature itself: the Python-facing types of the bound operations.
//
// A binding declares `const Length& radius` instead of `const Scalar& radius`; the value converts to what the kernel
// takes (so the body of the binding does not change), and the signature pybind writes reads
// `radius: simplecadapi.types.Length`.  The names are the typing aliases of `simplecadapi.types`, so the stubs, the API
// pages and the operation catalog (`simplecadapi.catalog`) all read the meaning from the one place it is written: here,
// in the binding.  There are two tools and the names built from them:
//
//   Renamed<T, Tag>  a T, loaded and cast exactly as T is (same conversions, same errors); the signature says
//   Tag::name. AnyOf<Tag>       any Python object, passed on as the py::object the binding read before (the binding or
//   the
//                    operation checks it, with the errors it always raised); the signature says the types it accepts.
//
//   Length      a distance (mm by default; a `scad.var` with a length unit)            float | Expr
//   Angle       an angle in degrees                                                     float | Expr
//   Point3      a position (x, y, z)                                                    3 x (float | Expr)
//   Direction3  a direction or an axis (its length does not matter)                     3 x (float | Expr)
//   Vector3     an offset (direction and length)                                        3 x (float | Expr)
//   PointVec3 / DirectionVec  a position / a direction read as a plain Vec3 (no expressions)
//   PlainQuantity<Tag>        a meaning above read as a plain double (no expressions)
//   Count       a whole number of things
//   Choice<Tag> text with fixed choices; Tag::name is the Literal[...] that lists them
//
// Plain `Scalar` stays for numbers without a unit (a factor, a tolerance); plain `Scalar3` for anything else.  A tag is
// a struct with `static constexpr auto name = <pybind descr>`; SCAD_SIGNATURE_NAME declares one, and type_name<T>() is
// the descr pybind prints for a bound class.
#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <string>
#include <utility>

#include "scad/core/scalar.hpp"
#include "scad/core/vec.hpp"

namespace scad::pybind {

template <class T, class Tag>
struct Renamed {
  T value;
  // The binding passes it on as is.
  operator const T&() const { return value; }  // NOLINT(google-explicit-constructor)
};

template <class Tag>
struct AnyOf {
  pybind11::object value;
  operator const pybind11::object&() const { return value; }  // NOLINT(google-explicit-constructor)
  bool is_none() const { return value.is_none(); }
  template <class T>
  T cast() const {
    return value.cast<T>();
  }
};

struct LengthTag {
  static constexpr auto name = pybind11::detail::const_name("simplecadapi.types.Length");
};
struct AngleTag {
  static constexpr auto name = pybind11::detail::const_name("simplecadapi.types.Angle");
};
struct PointTag {
  static constexpr auto name = pybind11::detail::const_name("simplecadapi.types.Point3");
};
struct DirectionTag {
  static constexpr auto name = pybind11::detail::const_name("simplecadapi.types.Direction3");
};
struct VectorTag {
  static constexpr auto name = pybind11::detail::const_name("simplecadapi.types.Vector3");
};
struct CountTag {
  static constexpr auto name = pybind11::detail::const_name("simplecadapi.types.Count");
};

using Length = Renamed<Scalar, LengthTag>;
using Angle = Renamed<Scalar, AngleTag>;
using Point3 = Renamed<std::array<Scalar, 3>, PointTag>;
using Direction3 = Renamed<std::array<Scalar, 3>, DirectionTag>;
using Vector3 = Renamed<std::array<Scalar, 3>, VectorTag>;
using PointVec3 = Renamed<Vec3, PointTag>;
using DirectionVec = Renamed<Vec3, DirectionTag>;
template <class Tag>
using PlainQuantity = Renamed<double, Tag>;
using Count = Renamed<int, CountTag>;
template <class Tag>
using Choice = Renamed<std::string, Tag>;

// The descr pybind prints for a bound class.
template <class T>
constexpr auto type_name() {
  return pybind11::detail::make_caster<T>::name;
}
// Words for the names.
inline constexpr auto kOr = pybind11::detail::const_name(" | ");
inline constexpr auto kOrNone = pybind11::detail::const_name(" | None");

}  // namespace scad::pybind

// Declares a tag: SCAD_SIGNATURE_NAME(PartName, type_name<sp::Part>());
#define SCAD_SIGNATURE_NAME(Struct, ...)        \
  struct Struct {                               \
    static constexpr auto name = (__VA_ARGS__); \
  }

namespace pybind11::detail {

template <class T, class Tag>
struct type_caster<scad::pybind::Renamed<T, Tag>> {
  using Type = scad::pybind::Renamed<T, Tag>;  // the macro takes no comma
  PYBIND11_TYPE_CASTER(Type, Tag::name);

  bool load(handle src, bool convert) {
    make_caster<T> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<T&&>(std::move(inner));
    return true;
  }
  static handle cast(const Type& renamed, return_value_policy policy, handle parent) {
    return make_caster<T>::cast(renamed.value, policy, parent);
  }
};

template <class Tag>
struct type_caster<scad::pybind::AnyOf<Tag>> {
  PYBIND11_TYPE_CASTER(scad::pybind::AnyOf<Tag>, Tag::name);

  bool load(handle src, bool /*convert*/) {
    if (!src)
      return false;
    value.value = reinterpret_borrow<object>(src);
    return true;
  }
  static handle cast(const scad::pybind::AnyOf<Tag>& any, return_value_policy, handle) { return any.value.inc_ref(); }
};

}  // namespace pybind11::detail
