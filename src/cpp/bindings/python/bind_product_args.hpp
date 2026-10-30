// Argument conversion for the product bindings.
//
// The Python operators check their argument types inside the wrapped body, so a wrong type
// is the operation's SimpleCADError (technical details "TypeError: part must be a Part"), not
// a pybind11 overload error.  The bindings therefore take py::object for every argument whose
// type is checked, and convert it here, inside scad::product::guard_operation.
#pragma once

#include <optional>
#include <string>

#include "bindings.hpp"
#include "scad/core/error.hpp"
#include "scad/product/product.hpp"

namespace scad::product_binding {

namespace sp = scad::product;

// `value` as a T, or a TypeError(message).
template <class T>
const T& typed(const py::object& value, const char* message) {
  if (!py::isinstance<T>(value))
    throw scad::TypeError(message);
  return value.cast<const T&>();
}

template <class T>
T converted(const py::object& value, const char* message) {
  try {
    return value.cast<T>();
  } catch (const py::cast_error&) {
    throw scad::TypeError(message);
  }
}

inline bool is_none(const py::object& value) {
  return value.is_none();
}

// str arguments: Python raises TypeError("<field> must be a string") for anything else.
inline std::string text(const py::object& value, const char* field) {
  if (!py::isinstance<py::str>(value))
    throw scad::TypeError(std::string(field) + " must be a string");
  return value.cast<std::string>();
}

// A display name: None, or anything str() accepts.
inline sp::OptionalString optional_name(const py::object& value) {
  if (value.is_none())
    return std::nullopt;
  return py::str(value).cast<std::string>();
}

inline scad::Scalar scalar(const py::object& value, const char* field) {
  try {
    return value.cast<scad::Scalar>();
  } catch (const py::cast_error&) {
    throw scad::TypeError(std::string(field) + " must be numeric");
  }
}

inline std::optional<scad::Scalar> optional_scalar(const py::object& value, const char* field) {
  if (value.is_none())
    return std::nullopt;
  return scalar(value, field);
}

inline double number(const py::object& value, const char* field) {
  return scalar(value, field).value();
}

// Three numbers from a list or tuple.
inline Vec3 vec3(const py::object& value, const char* field) {
  if (!py::isinstance<py::list>(value) && !py::isinstance<py::tuple>(value)) {
    throw scad::ValueError(std::string(field) + " must be a 3-element tuple or list");
  }
  const py::sequence seq = py::reinterpret_borrow<py::sequence>(value);
  if (seq.size() != 3)
    throw scad::ValueError(std::string(field) + " must be a 3-element tuple or list");
  double v[3];
  for (std::size_t i = 0; i < 3; ++i) {
    try {
      v[i] = seq[i].cast<double>();
    } catch (const py::cast_error&) {
      throw scad::TypeError(std::string(field) + "[" + std::to_string(i) + "] must be numeric");
    }
  }
  return {v[0], v[1], v[2]};
}

inline std::optional<Vec3> optional_vec3(const py::object& value, const char* field) {
  if (value.is_none())
    return std::nullopt;
  return vec3(value, field);
}

inline bool truthy(const py::object& value) {
  return PyObject_IsTrue(value.ptr()) == 1;
}

// `item` of add_component_rassembly.
inline sp::Item item_of(const py::object& value) {
  if (py::isinstance<sp::Part>(value))
    return sp::Item{value.cast<sp::PartPtr>()};
  if (py::isinstance<sp::Assembly>(value))
    return sp::Item{value.cast<sp::AssemblyPtr>()};
  throw scad::TypeError("item must be a Part or Assembly");
}

inline py::object py_item(const sp::Item& item) {
  if (const auto* part = std::get_if<sp::PartPtr>(&item))
    return py::cast(*part);
  return py::cast(std::get<sp::AssemblyPtr>(item));
}

template <class T>
py::tuple to_tuple(const std::vector<T>& items) {
  py::tuple out(items.size());
  for (std::size_t i = 0; i < items.size(); ++i)
    out[i] = py::cast(items[i]);
  return out;
}

}  // namespace scad::product_binding

void bind_product_values(py::module_& m);
