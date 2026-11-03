// Parameter types that only change what the signature says, for the bound operations of ops_geometry/ops_features.
//
//   TypedObject<Tag>  any Python object, passed on as the py::object the binding read before; the signature prints
//                     Tag::name (`Sequence[Edge] | ShapeSelector`, `simplecadapi.types.Point3`, ...).  The binding
//                     validates it itself, with the errors it raised before.
//   Choice<Tag>       a str, loaded as std::string; the signature prints Tag::name (`Literal['Right', 'Left']`).
//   PlainQuantity<Tag> a float (no expression), loaded as double; prints a meaning of semantic_types.hpp.
//   DirectionVec      a Vec3 (a 3-sequence or an object with x, y, z); prints simplecadapi.types.Direction3.
//   Count             an int; prints simplecadapi.types.Count.
#pragma once

#include <string>

#include "bindings.hpp"

namespace scad::pybind {

template <class Tag>
struct TypedObject {
  pybind11::object value;
  operator const pybind11::object&() const { return value; }  // NOLINT(google-explicit-constructor)
};

template <class Tag>
struct Choice {
  std::string value;
  operator const std::string&() const { return value; }  // NOLINT(google-explicit-constructor)
};

template <class Tag>
struct PlainQuantity {
  double value;
  operator double() const { return value; }  // NOLINT(google-explicit-constructor)
};

struct DirectionVec {
  Vec3 value;
  operator const Vec3&() const { return value; }  // NOLINT(google-explicit-constructor)
};

struct Count {
  int value;
  operator int() const { return value; }  // NOLINT(google-explicit-constructor)
};

struct CountTag {
  static constexpr auto name = pybind11::detail::const_name("simplecadapi.types.Count");
};

}  // namespace scad::pybind

namespace pybind11::detail {

template <class Tag>
struct type_caster<scad::pybind::TypedObject<Tag>> {
  PYBIND11_TYPE_CASTER(scad::pybind::TypedObject<Tag>, Tag::name);

  bool load(handle src, bool) {
    if (!src)
      return false;
    value.value = reinterpret_borrow<object>(src);
    return true;
  }
  static handle cast(const scad::pybind::TypedObject<Tag>& o, return_value_policy, handle) { return o.value.inc_ref(); }
};

template <class Tag>
struct type_caster<scad::pybind::Choice<Tag>> {
  PYBIND11_TYPE_CASTER(scad::pybind::Choice<Tag>, Tag::name);

  bool load(handle src, bool convert) {
    make_caster<std::string> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<std::string&&>(std::move(inner));
    return true;
  }
  static handle cast(const scad::pybind::Choice<Tag>& c, return_value_policy policy, handle parent) {
    return make_caster<std::string>::cast(c.value, policy, parent);
  }
};

template <class Tag>
struct type_caster<scad::pybind::PlainQuantity<Tag>> {
  PYBIND11_TYPE_CASTER(scad::pybind::PlainQuantity<Tag>, Tag::name);

  bool load(handle src, bool convert) {
    make_caster<double> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<double>(inner);
    return true;
  }
  static handle cast(const scad::pybind::PlainQuantity<Tag>& q, return_value_policy policy, handle parent) {
    return make_caster<double>::cast(q.value, policy, parent);
  }
};

template <>
struct type_caster<scad::pybind::DirectionVec> {
  PYBIND11_TYPE_CASTER(scad::pybind::DirectionVec, scad::pybind::DirectionTag::name);

  bool load(handle src, bool convert) {
    make_caster<scad::Vec3> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<scad::Vec3&&>(std::move(inner));
    return true;
  }
  static handle cast(const scad::pybind::DirectionVec& d, return_value_policy policy, handle parent) {
    return make_caster<scad::Vec3>::cast(d.value, policy, parent);
  }
};

template <>
struct type_caster<scad::pybind::Count> {
  PYBIND11_TYPE_CASTER(scad::pybind::Count, scad::pybind::CountTag::name);

  bool load(handle src, bool convert) {
    make_caster<int> inner;
    if (!inner.load(src, convert))
      return false;
    value.value = cast_op<int>(inner);
    return true;
  }
  static handle cast(const scad::pybind::Count& c, return_value_policy policy, handle parent) {
    return make_caster<int>::cast(c.value, policy, parent);
  }
};

}  // namespace pybind11::detail
