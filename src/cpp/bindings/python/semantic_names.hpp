// More signature names for what a parameter means (see semantic_types.hpp), for the surface and sketch bindings.
//
//   Renamed<T, Tag>  a T, loaded and cast exactly as T is; the signature says Tag::name
//   PointVec3     a position (x, y, z) read exactly as scad::Vec3 is (a 3-sequence, or an object with x, y, z);
//                 the signature says simplecadapi.types.Point3
//   Choice<Tag>   text with fixed choices, read exactly as std::string is; the signature says Literal[...]
//   Named<Tag>    any Python object (the binding checks it, as with a py::object parameter); the signature says the
//                 types the binding accepts
//
// The sketch casters (bind_sketch.cpp) name a position in the sketch plane simplecadapi.types.Point2.
#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <string>

#include "scad/core/vec.hpp"
#include "semantic_types.hpp"

namespace scad::pybind {

// A value loaded and cast exactly as T is, under another name in the signature.
template <class T, class Tag>
struct Renamed {
  T value;
  operator const T&() const { return value; }  // NOLINT(google-explicit-constructor)
};

using PointVec3 = Renamed<Vec3, PointTag>;
template <class Tag>
using Choice = Renamed<std::string, Tag>;

template <class Tag>
struct Named {
  pybind11::object value;
};

}  // namespace scad::pybind

namespace pybind11::detail {

template <class T, class Tag>
struct type_caster<scad::pybind::Renamed<T, Tag>> {
  using Type = scad::pybind::Renamed<T, Tag>;
  PYBIND11_TYPE_CASTER(Type, Tag::name);

  bool load(handle src, bool convert) {
    make_caster<T> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<T&&>(std::move(inner));
    return true;
  }
  static handle cast(const Type& r, return_value_policy policy, handle parent) {
    return make_caster<T>::cast(r.value, policy, parent);
  }
};

template <class Tag>
struct type_caster<scad::pybind::Named<Tag>> {
  PYBIND11_TYPE_CASTER(scad::pybind::Named<Tag>, Tag::name);

  bool load(handle src, bool /*convert*/) {
    if (!src)
      return false;
    value.value = reinterpret_borrow<object>(src);
    return true;
  }
  static handle cast(const scad::pybind::Named<Tag>& n, return_value_policy, handle) { return n.value.inc_ref(); }
};

}  // namespace pybind11::detail
