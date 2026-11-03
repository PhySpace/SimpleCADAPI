// What a parameter means, in the signature itself: the Python-facing types of the bound operations.
//
// A binding declares `const Length& radius` instead of `const Scalar& radius`; the value converts to the Scalar the
// kernel takes (so the body of the binding does not change), and the signature pybind writes reads `radius: Length`.
// The names are the typing aliases of `simplecadapi.types`, so the stubs, the API pages and the operation catalog
// (`simplecadapi.catalog`) all read the meaning from the one place it is written: the binding.
//
//   Length      a distance (mm by default; a `scad.var` with a length unit)            float | Expr
//   Angle       an angle in degrees                                                     float | Expr
//   Point3      a position (x, y, z)                                                    3 x (float | Expr)
//   Direction3  a direction or an axis (its length does not matter)                     3 x (float | Expr)
//   Vector3     an offset (direction and length)                                        3 x (float | Expr)
//
// Plain `Scalar` stays for numbers without a unit (a factor, a tolerance); plain `Scalar3` for anything else.
#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>

#include "scad/core/scalar.hpp"

namespace scad::pybind {

template <class Tag>
struct Quantity {
  Scalar value;
  // The binding passes it on as is.
  operator const Scalar&() const { return value; }  // NOLINT(google-explicit-constructor)
};

template <class Tag>
struct Quantity3 {
  std::array<Scalar, 3> value;
  operator const std::array<Scalar, 3>&() const { return value; }  // NOLINT(google-explicit-constructor)
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

using Length = Quantity<LengthTag>;
using Angle = Quantity<AngleTag>;
using Point3 = Quantity3<PointTag>;
using Direction3 = Quantity3<DirectionTag>;
using Vector3 = Quantity3<VectorTag>;

}  // namespace scad::pybind

namespace pybind11::detail {

// Loads and casts exactly as Scalar does; only the name in the signature differs.
template <class Tag>
struct type_caster<scad::pybind::Quantity<Tag>> {
  PYBIND11_TYPE_CASTER(scad::pybind::Quantity<Tag>, Tag::name);

  bool load(handle src, bool convert) {
    make_caster<scad::Scalar> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<scad::Scalar&&>(std::move(inner));
    return true;
  }
  static handle cast(const scad::pybind::Quantity<Tag>& q, return_value_policy policy, handle parent) {
    return make_caster<scad::Scalar>::cast(q.value, policy, parent);
  }
};

template <class Tag>
struct type_caster<scad::pybind::Quantity3<Tag>> {
  PYBIND11_TYPE_CASTER(scad::pybind::Quantity3<Tag>, Tag::name);

  bool load(handle src, bool convert) {
    make_caster<std::array<scad::Scalar, 3>> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<std::array<scad::Scalar, 3>&&>(std::move(inner));
    return true;
  }
  static handle cast(const scad::pybind::Quantity3<Tag>& q, return_value_policy policy, handle parent) {
    return make_caster<std::array<scad::Scalar, 3>>::cast(q.value, policy, parent);
  }
};

}  // namespace pybind11::detail
