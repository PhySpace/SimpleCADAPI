// Dimension, Unit, the registered units and UnitValidationError.
#include "bind_reactive_common.hpp"

#include <pybind11/eval.h>

#include "scad/core/error.hpp"
#include "scad/reactive/digest.hpp"
#include "scad/reactive/errors.hpp"
#include "scad/reactive/units.hpp"

namespace scad::pybind::reactive {

using scad::reactive::Dimension;
using scad::reactive::Unit;

scad::reactive::Unit unit_from(const py::object& value) {
  if (py::isinstance<Unit>(value)) return py::cast<Unit>(value);
  if (!py::isinstance<py::str>(value)) throw scad::TypeError("Unit must be a non-empty string or Unit");
  return scad::reactive::get_unit(py::cast<std::string>(value));
}

namespace {

int exponent_of(const py::object& value, const char* what) {
  if (PyBool_Check(value.ptr()) || !PyLong_Check(value.ptr())) {
    throw scad::TypeError(std::string("Dimension ") + what + " exponent must be an integer");
  }
  return py::cast<int>(value);
}

const char* kUnitErrorSource = R"PY(
from simplecadapi._cpp.errors import SimpleCADError


class UnitValidationError(SimpleCADError):
    """Units or expression dimensions are physically inconsistent."""

    operation = "units"

    def __init__(self, message):
        message = str(message)
        guidance = {
            "operation": "units",
            "what_happened": message,
            "possible_causes": [],
            "how_to_fix": [],
            "technical_details": None,
            "signature": None,
            "documentation_hint": None,
            "measurements": [],
            "evidence": [],
            "repair": [],
            "inventory": [],
        }
        super().__init__("units", guidance, message)

    def __str__(self):
        return self.args[0]

    def __repr__(self):
        return f"{type(self).__name__}({self.args[0]!r})"
)PY";

}  // namespace

void bind_reactive_units(py::module_& m) {
  // UnitValidationError is a Python class (a SimpleCADError subclass whose str() is the bare message).
  py::dict scope;
  py::exec(kUnitErrorSource, scope);
  m.attr("UnitValidationError") = scope["UnitValidationError"];
  py::register_exception_translator([](std::exception_ptr p) {
    try {
      if (p) std::rethrow_exception(p);
    } catch (const scad::reactive::UnitValidationError& e) {
      py::object cls = py::module_::import("simplecadapi._cpp._native").attr("UnitValidationError");
      PyErr_SetObject(cls.ptr(), cls(e.guidance().what_happened).ptr());
    }
  });

  py::class_<Dimension>(m, "Dimension")
      .def(py::init([](const py::object& length, const py::object& angle) {
             return Dimension{exponent_of(length, "length"), exponent_of(angle, "angle")};
           }),
           py::arg("length") = 0, py::arg("angle") = 0)
      .def_property_readonly("length", [](const Dimension& d) { return d.length; })
      .def_property_readonly("angle", [](const Dimension& d) { return d.angle; })
      .def_property_readonly("name", &Dimension::name)
      .def_property_readonly("symbol", &Dimension::symbol)
      .def_property_readonly("is_dimensionless", &Dimension::is_dimensionless)
      .def_property_readonly("is_design_dimension", &Dimension::is_design_dimension)
      .def("multiply", &Dimension::multiply)
      .def("divide", &Dimension::divide)
      .def("power", [](const Dimension& d, const py::object& exponent) { return d.power(exponent_of(exponent, "")); })
      .def("square_root", &Dimension::square_root)
      .def("to_dict", [](const Dimension& d) { return value_to_python(d.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return Dimension::from_value(value_from_python(data)); })
      .def("__eq__", [](const Dimension& a, const py::object& b) { return py::isinstance<Dimension>(b) && a == py::cast<Dimension>(b); })
      .def("__hash__", [](const Dimension& d) { return std::hash<int>{}(d.length) * 31 + std::hash<int>{}(d.angle); })
      .def("__repr__", [](const Dimension& d) {
        return "Dimension(length=" + std::to_string(d.length) + ", angle=" + std::to_string(d.angle) + ")";
      });

  py::class_<Unit>(m, "Unit")
      .def(py::init([](const py::object& symbol, const py::object& dimension, const py::object& scale) {
             if (!py::isinstance<py::str>(symbol)) throw scad::ValueError("Unit symbol must be a non-empty string");
             if (!py::isinstance<Dimension>(dimension)) throw scad::TypeError("Unit dimension must be a Dimension");
             return Unit(py::cast<std::string>(symbol), py::cast<Dimension>(dimension),
                         real_number(scale, "Unit scale"));
           }),
           py::arg("symbol"), py::arg("dimension"), py::arg("scale_to_canonical"))
      .def_property_readonly("symbol", &Unit::symbol)
      .def_property_readonly("dimension", &Unit::dimension)
      .def_property_readonly("scale_to_canonical", &Unit::scale_to_canonical)
      .def("to_canonical", [](const Unit& u, const py::object& v) { return u.to_canonical(finite_real(v, "Value in " + u.symbol())); })
      .def("from_canonical", [](const Unit& u, const py::object& v) { return u.from_canonical(finite_real(v, "Canonical value")); })
      .def("to_dict", [](const Unit& u) { return value_to_python(u.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return Unit::from_value(value_from_python(data)); })
      .def("__eq__", [](const Unit& a, const py::object& b) { return py::isinstance<Unit>(b) && a == py::cast<Unit>(b); })
      .def("__hash__", [](const Unit& u) { return std::hash<std::string>{}(u.symbol()); })
      .def("__repr__", [](const Unit& u) {
        return "Unit(symbol=" + scad::reactive::py_str_repr(u.symbol()) + ", dimension=Dimension(length=" +
               std::to_string(u.dimension().length) + ", angle=" + std::to_string(u.dimension().angle) +
               "), scale_to_canonical=" + scad::reactive::py_float_repr(u.scale_to_canonical()) + ")";
      });

  namespace sr = scad::reactive;
  m.attr("DIMENSIONLESS") = py::cast(sr::kDimensionless);
  m.attr("LENGTH") = py::cast(sr::kLength);
  m.attr("AREA") = py::cast(sr::kArea);
  m.attr("VOLUME") = py::cast(sr::kVolume);
  m.attr("ANGLE") = py::cast(sr::kAngle);
  const struct {
    const char* name;
    const Unit& (*unit)();
  } registered[] = {
      {"MM", sr::units::mm},           {"CM", sr::units::cm},           {"M", sr::units::m},
      {"INCH", sr::units::inch},       {"FOOT", sr::units::foot},       {"DEGREE", sr::units::degree},
      {"RADIAN", sr::units::radian},   {"ONE", sr::units::one},         {"PERCENT", sr::units::percent},
      {"SQUARE_MM", sr::units::square_mm}, {"SQUARE_CM", sr::units::square_cm}, {"SQUARE_M", sr::units::square_m},
      {"SQUARE_INCH", sr::units::square_inch}, {"SQUARE_FOOT", sr::units::square_foot},
      {"CUBIC_MM", sr::units::cubic_mm}, {"CUBIC_CM", sr::units::cubic_cm}, {"CUBIC_M", sr::units::cubic_m},
      {"CUBIC_INCH", sr::units::cubic_inch}, {"CUBIC_FOOT", sr::units::cubic_foot},
  };
  for (const auto& entry : registered) m.attr(entry.name) = py::cast(entry.unit());

  m.def("get_unit", [](const py::object& value) -> py::object {
    if (py::isinstance<Unit>(value)) return value;
    if (!py::isinstance<py::str>(value)) throw scad::TypeError("Unit must be a non-empty string or Unit");
    return py::cast(sr::get_unit(py::cast<std::string>(value)));
  }, py::arg("value"));
  m.def("unit_to_payload", [](const py::object& unit) {
    if (!py::isinstance<Unit>(unit)) throw scad::TypeError("Unit payload serialization requires a Unit");
    return value_to_python(sr::unit_to_payload(py::cast<Unit>(unit)));
  });
  m.def("unit_from_payload", [](const py::object& payload) {
    if (py::isinstance<Unit>(payload)) return py::cast<Unit>(payload);
    return sr::unit_from_payload(value_from_python(payload));
  });
  m.def("canonical_unit_for_dimension", &sr::canonical_unit_for_dimension, py::arg("dimension"));
  m.def("convert_value", [](const py::object& value, const py::object& from, const py::object& to) {
    return sr::convert_value(finite_real(value, "Value"), unit_from(from), unit_from(to));
  }, py::arg("value"), py::arg("from_unit"), py::arg("to_unit"));
}

}  // namespace scad::pybind::reactive
