// Python bindings for the reactive area: expressions, units, the operation
// graph and the recording / recomputing session.  The work is split over
// bind_reactive_{units,exprs,graph,session}.cpp; this file holds the helpers
// they share and the entry point.
#include "bind_reactive_common.hpp"

#include <cmath>

#include "scad/core/error.hpp"
#include "scad/topo/shape.hpp"

namespace scad::pybind::reactive {

const py::object& numbers_real() {
  // Never destroyed: a static py::object would be released after the interpreter has finalized.
  PYBIND11_CONSTINIT static py::gil_safe_call_once_and_store<py::object> storage;
  return storage.call_once_and_store_result([] { return py::module_::import("numbers").attr("Real"); }).get_stored();
}

double real_number(const py::handle& value, std::string_view label) {
  if (PyBool_Check(value.ptr()) || PyObject_IsInstance(value.ptr(), numbers_real().ptr()) != 1) {
    throw scad::TypeError(std::string(label) + " must be a real number");
  }
  const py::object as_float = py::reinterpret_steal<py::object>(PyNumber_Float(value.ptr()));
  if (!as_float) {
    if (PyErr_ExceptionMatches(PyExc_OverflowError)) {
      PyErr_Clear();
      throw scad::ValueError(std::string(label) + " must be finite");
    }
    throw py::error_already_set();
  }
  return PyFloat_AS_DOUBLE(as_float.ptr());
}

double finite_real(const py::handle& value, std::string_view label) {
  const double result = real_number(value, label);
  if (!std::isfinite(result)) throw scad::ValueError(std::string(label) + " must be finite");
  return result;
}

scad::Bindings bindings_from(const py::object& mapping) {
  scad::Bindings out;
  if (mapping.is_none()) return out;
  for (const auto& item : py::cast<py::dict>(mapping)) {
    out[py::cast<std::string>(item.first)] = real_number(item.second, "Binding '" + py::cast<std::string>(item.first) + "'");
  }
  return out;
}

py::object shape_to_python(const scad::Shape& shape) {
  switch (shape.kind()) {
    case scad::Kind::Vertex: return py::cast(scad::Vertex(shape));
    case scad::Kind::Edge: return py::cast(scad::Edge(shape));
    case scad::Kind::Wire: return py::cast(scad::Wire(shape));
    case scad::Kind::Face: return py::cast(scad::Face(shape));
    case scad::Kind::Shell: return py::cast(scad::Shell(shape));
    case scad::Kind::Solid: return py::cast(scad::Solid(shape));
    case scad::Kind::Compound: return py::cast(scad::Compound(shape));
  }
  return py::cast(shape);
}

}  // namespace scad::pybind::reactive

void bind_reactive(py::module_& m) {
  using namespace scad::pybind::reactive;
  bind_reactive_units(m);
  bind_reactive_exprs(m);
  bind_reactive_graph(m);
  bind_reactive_session(m);
  bind_reactive_math(m);
}
