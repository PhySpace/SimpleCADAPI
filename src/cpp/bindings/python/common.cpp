// Exception translation and Value <-> Python conversion.
#include "bindings.hpp"

#include <stdexcept>

#include <pybind11/eval.h>

#include "scad/core/error.hpp"
#include "scad/reactive/errors.hpp"

namespace scad::pybind {

namespace {

py::dict guidance_to_dict(const Error& e) {
  const ErrorGuidance& g = e.guidance();
  py::dict d;
  d["operation"] = e.operation();
  d["what_happened"] = g.what_happened;
  d["possible_causes"] = g.possible_causes;
  d["how_to_fix"] = g.how_to_fix;
  d["technical_details"] = g.technical_details.empty() ? py::none() : py::object(py::str(g.technical_details));
  d["signature"] = g.signature.empty() ? py::none() : py::object(py::str(g.signature));
  d["documentation_hint"] =
      g.documentation_hint.empty() ? py::none() : py::object(py::str(g.documentation_hint));
  py::list measurements;
  for (const auto& m : g.measurements) {
    py::dict item;
    item["name"] = m.name;
    if (const auto* scalar = std::get_if<double>(&m.value)) item["value"] = *scalar;
    else {
      const auto& v = std::get<std::array<double, 3>>(m.value);
      item["value"] = py::make_tuple(v[0], v[1], v[2]);
    }
    item["unit"] = m.unit;
    measurements.append(item);
  }
  d["measurements"] = measurements;
  py::list evidence;
  for (const auto& ev : g.evidence) {
    py::dict item;
    item["kind"] = ev.kind;
    item["path"] = ev.path;
    item["view"] = ev.view;
    item["caption"] = ev.caption;
    py::dict symbols;
    for (const auto& [k, v] : ev.symbols) symbols[py::str(k)] = v;
    item["symbols"] = symbols;
    evidence.append(item);
  }
  d["evidence"] = evidence;
  d["repair"] = g.repair;
  py::list inventory;
  for (const auto& entry : g.inventory) {
    py::dict item;
    item["symbol"] = entry.symbol;
    item["status"] = entry.status;
    item["description"] = entry.description;
    inventory.append(item);
  }
  d["inventory"] = inventory;
  return d;
}

void set_python_error(const Exception& e) {
  PyObject* type = PyExc_RuntimeError;
  switch (e.py_kind()) {
    case PyKind::ValueError: type = PyExc_ValueError; break;
    case PyKind::TypeError: type = PyExc_TypeError; break;
    case PyKind::IndexError: type = PyExc_IndexError; break;
    case PyKind::KeyError: type = PyExc_KeyError; break;
    case PyKind::RuntimeError: type = PyExc_RuntimeError; break;
    case PyKind::NotImplementedError: type = PyExc_NotImplementedError; break;
  }
  PyErr_SetString(type, e.what());
}

}  // namespace

void register_exceptions(py::module_&) {
  py::register_exception_translator([](std::exception_ptr p) {
    try {
      if (p) std::rethrow_exception(p);
    } catch (const Error& e) {
      try {
        py::object errors = py::module_::import("simplecadapi._cpp.errors");
        // The message-first families are real classes in the SDK: which one this is travels with the error.
        const char* family = "";
        if (dynamic_cast<const UnsupportedQueryCapabilityError*>(&e) != nullptr) family = "UnsupportedQueryCapabilityError";
        else if (dynamic_cast<const SemanticCapabilityError*>(&e) != nullptr) family = "SemanticCapabilityError";
        else if (dynamic_cast<const TagValidationError*>(&e) != nullptr) family = "TagValidationError";
        py::object exc = errors.attr("make_error")(e.operation(), guidance_to_dict(e), std::string(e.what()), family);
        PyErr_SetObject(reinterpret_cast<PyObject*>(Py_TYPE(exc.ptr())), exc.ptr());
      } catch (const py::error_already_set&) {
        // errors.py unavailable (partial import): degrade to a plain ValueError with the same text.
        PyErr_Clear();
        PyErr_SetString(PyExc_ValueError, e.what());
      }
    } catch (const Exception& e) {
      set_python_error(e);
    }
    // Anything else falls through to pybind11's built-in translators.
  });
}

Value value_from_python(const py::handle& obj) {
  if (obj.is_none()) return Value();
  if (py::isinstance<py::bool_>(obj)) return Value(obj.cast<bool>());
  if (py::isinstance<py::int_>(obj)) return Value(obj.cast<std::int64_t>());
  if (py::isinstance<py::float_>(obj)) return Value(obj.cast<double>());
  if (py::isinstance<py::str>(obj)) return Value(obj.cast<std::string>());
  if (py::isinstance<py::dict>(obj)) {
    Value out = Value::object();
    for (const auto& item : obj.cast<py::dict>()) out.set(py::str(item.first).cast<std::string>(), value_from_python(item.second));
    return out;
  }
  if (py::isinstance<py::sequence>(obj)) {
    Value out = py::isinstance<py::tuple>(obj) ? Value::tuple() : Value::array();
    for (const auto& item : obj.cast<py::sequence>()) out.push_back(value_from_python(item));
    return out;
  }
  if (PyNumber_Check(obj.ptr())) return Value(obj.cast<double>());  // numpy scalars
  throw std::invalid_argument(std::string("cannot convert Python ") +
                              std::string(py::str(py::type::of(obj).attr("__name__"))) + " to a Value");
}

py::object value_to_python(const Value& v) {
  if (v.is_null()) return py::none();
  if (v.is_bool()) return py::bool_(v.as_bool());
  if (v.is_int()) return py::int_(v.as_int());
  if (v.is_double()) return py::float_(v.as_double());
  if (v.is_string()) return py::str(v.as_string());
  if (v.is_tuple()) {
    py::tuple out(v.size());
    std::size_t at = 0;
    for (const auto& item : v.as_array()) out[at++] = value_to_python(item);
    return std::move(out);
  }
  if (v.is_array()) {
    py::list out;
    for (const auto& item : v.as_array()) out.append(value_to_python(item));
    return std::move(out);
  }
  py::dict out;
  for (const auto& [key, item] : v.as_object()) out[py::str(key)] = value_to_python(item);
  return std::move(out);
}

}  // namespace scad::pybind
