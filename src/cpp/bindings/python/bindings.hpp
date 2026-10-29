// Shared pybind11 plumbing: type casters and the per-area registration hooks.
//
// Every area registers itself from its own bind_<area>.cpp; module.cpp only
// calls the hooks below in order.  A new area adds one declaration here and one
// call in module.cpp -- nothing else is shared.
#pragma once

#include <exception>
#include <functional>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <memory>
#include <string>

#include "exceptions.hpp"
#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"

namespace py = pybind11;

void bind_core(py::module_& m);
void bind_topo(py::module_& m);
void bind_semantic(py::module_& m);
void bind_ops_geometry(py::module_& m);
void bind_ops_features(py::module_& m);
void bind_sketch(py::module_& m);
void bind_surface(py::module_& m);
void bind_std(py::module_& m);
void bind_reactive(py::module_& m);
void bind_io(py::module_& m);
void bind_ql(py::module_& m);
void bind_render(py::module_& m);
void bind_product(py::module_& m);
void bind_sdk_compat(py::module_& m);
void bind_canonical(py::module_& m);

namespace scad::pybind {

// The Python-visible Vec3 value (what get_center()/get_normal_at() return).
// Plain tuples are accepted wherever a Vec3 is read.
struct PyVec3 {
  scad::Vec3 v;
};

// Installs the module's exception translator and the General handler.
void register_exceptions(py::module_& m);

// Python value -> scad::Value (None, bool, int, float, str, list/tuple, dict).
Value value_from_python(const py::handle& obj);
py::object value_to_python(const Value& value);

}  // namespace scad::pybind

namespace pybind11::detail {

// Vec3 <-> any 3-sequence of numbers (tuple, list, numpy array); returns a tuple.
template <>
struct type_caster<scad::Vec3> {
  PYBIND11_TYPE_CASTER(scad::Vec3, const_name("tuple[float, float, float]"));

  bool load(handle src, bool /*convert*/) {
    if (!src)
      return false;
    // A Vec3 object (or anything with x, y, z attributes).
    if (hasattr(src, "x") && hasattr(src, "y") && hasattr(src, "z") && !isinstance<sequence>(src)) {
      try {
        value = scad::Vec3{src.attr("x").cast<double>(), src.attr("y").cast<double>(), src.attr("z").cast<double>()};
        return true;
      } catch (const cast_error&) {
        return false;
      }
    }
    if (!(isinstance<sequence>(src) || isinstance<array>(src)))
      return false;
    sequence seq = reinterpret_borrow<sequence>(src);
    if (seq.size() != 3)
      return false;
    double v[3];
    for (std::size_t i = 0; i < 3; ++i) {
      object item = seq[i];
      try {
        v[i] = item.cast<double>();
      } catch (const cast_error&) {
        return false;
      }
    }
    value = scad::Vec3{v[0], v[1], v[2]};
    return true;
  }

  static handle cast(const scad::Vec3& v, return_value_policy, handle) { return make_tuple(v.x, v.y, v.z).release(); }
};

// Scalar <- float | int | an expression object (anything holding an ExprPtr).
// The expression types are bound in bind_reactive; until then only numbers load.
template <>
struct type_caster<scad::Scalar> {
  PYBIND11_TYPE_CASTER(scad::Scalar, const_name("float | Expr"));

  bool load(handle src, bool convert) {
    if (!src)
      return false;
    // An Expr/Var exposed by the reactive module.
    if (object expr_type = scad_expr_type(); expr_type && !expr_type.is_none() && isinstance(src, expr_type)) {
      value = scad::Scalar(src.cast<scad::ExprPtr>());
      return true;
    }
    if (PyFloat_Check(src.ptr()) || PyLong_Check(src.ptr()) || (convert && PyNumber_Check(src.ptr()))) {
      PyObject* number = PyNumber_Float(src.ptr());
      if (number == nullptr) {
        PyErr_Clear();
        return false;
      }
      value = scad::Scalar(PyFloat_AsDouble(number));
      Py_DECREF(number);
      return true;
    }
    return false;
  }

  static handle cast(const scad::Scalar& s, return_value_policy, handle) {
    if (s.symbolic())
      return pybind11::cast(s.expr()).release();
    return PyFloat_FromDouble(s.literal());
  }

 private:
  // The Python class that wraps scad::ExprNode; absent until bind_reactive ran.
  static object scad_expr_type() {
    static object* type = new object;  // never destroyed: static destructors run after Py_Finalize
    if (!*type) {
      try {
        *type = module_::import("simplecadapi._cpp._native").attr("ExprBase");
      } catch (const error_already_set&) {
        return none();
      }
    }
    return *type;
  }
};

// Value <-> native Python objects.
template <>
struct type_caster<scad::Value> {
  PYBIND11_TYPE_CASTER(scad::Value, const_name("Any"));

  bool load(handle src, bool) {
    try {
      value = scad::pybind::value_from_python(src);
      return true;
    } catch (const std::exception&) {
      return false;
    }
  }
  static handle cast(const scad::Value& v, return_value_policy, handle) {
    return scad::pybind::value_to_python(v).release();
  }
};

}  // namespace pybind11::detail
