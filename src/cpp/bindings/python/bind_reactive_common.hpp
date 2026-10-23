// Helpers shared by the bind_reactive*.cpp files.
#pragma once

#include <string>
#include <string_view>

#include "bindings.hpp"
#include "scad/reactive/expr.hpp"
#include "scad/reactive/units.hpp"
#include "scad/topo/shape.hpp"

namespace scad::pybind::reactive {

// numbers.Real (kept alive for the life of the process).
const py::object& numbers_real();

// `_finite_scalar`: a real number (never a bool) that is finite.  TypeError
// for anything else, ValueError for NaN / infinity / an int too large for a double.
double finite_real(const py::handle& value, std::string_view label);
// A real number that need not be finite (a unit scale is checked by Unit).
double real_number(const py::handle& value, std::string_view label);

// Mapping[str, float] | None -> Bindings (values must be real numbers).
scad::Bindings bindings_from(const py::object& mapping);

// A Python Unit/str -> Unit (get_unit).
scad::reactive::Unit unit_from(const py::object& value);

// The node of a Python scalar: Var/Const/Expr -> itself, a number -> a Const.
// TypeError for anything else (lift_scalar).
scad::reactive::ScalarPtr lift(const py::handle& value);

// A shape as the Python class of its kind (Solid, Face, ...).
py::object shape_to_python(const scad::Shape& shape);

void bind_reactive_units(py::module_& m);
void bind_reactive_exprs(py::module_& m);
void bind_reactive_graph(py::module_& m);
void bind_reactive_session(py::module_& m);
void bind_reactive_math(py::module_& m);

}  // namespace scad::pybind::reactive
