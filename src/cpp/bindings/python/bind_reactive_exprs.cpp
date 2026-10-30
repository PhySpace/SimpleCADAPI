// Const, Var, Expr and their operators; var(), const(), sin() ...; the
// expression graph; canonicalize_params.
#include "bind_reactive_common.hpp"

#include <cmath>
#include <functional>
#include <optional>
#include <unordered_set>

#include "scad/core/error.hpp"
#include "scad/reactive/digest.hpp"
#include "scad/reactive/expr.hpp"
#include "scad/reactive/expr_graph.hpp"

namespace scad::pybind::reactive {

namespace sr = scad::reactive;
using sr::Const;
using sr::DimensionTolerance;
using sr::Expr;
using sr::ScalarNode;
using sr::ScalarPtr;
using sr::Var;

ScalarPtr lift(const py::handle& value) {
  if (py::isinstance<ScalarNode>(value))
    return py::cast<ScalarPtr>(value);
  if (PyBool_Check(value.ptr()))
    throw scad::TypeError("Boolean values are not valid scalar expression inputs");
  if (PyLong_Check(value.ptr()) || PyFloat_Check(value.ptr()) ||
      PyObject_IsInstance(value.ptr(), numbers_real().ptr()) == 1)
    return sr::Const::make(real_number(value, "value"));
  throw scad::TypeError("Unsupported scalar expression value: " + py::cast<std::string>(py::repr(py::type::of(value))));
}

namespace {

using ExprResult = std::shared_ptr<const Expr>;

ExprResult binary(const char* op, const ScalarPtr& self, const py::handle& other, bool reflected) {
  ScalarPtr rhs = lift(other);
  return Expr::make(
      op, reflected ? std::vector<ScalarPtr>{std::move(rhs), self} : std::vector<ScalarPtr>{self, std::move(rhs)});
}

ExprResult unary(const char* op, const ScalarPtr& value) {
  return Expr::make(op, {value});
}

// ---- the numeric protocol -------------------------------------------------------------------------------------
//
// A Var or Expr is used where Python wants a number: comparisons, int(), round(), format(), indexing, numpy.  Those
// are decisions, not formulas, so they read the value the expression has now -- the same value float(x) gives (a
// saved parameter replaces a Var's default).  Arithmetic (+ - * / **, abs, neg) is the part that stays symbolic and
// keeps the link to the parameters.  bool(x) stays an error (see __bool__): spell the comparison, `x > 0`.

// There is deliberately no __array__: marimo takes an object that has one for a numpy array and keys the cell cache by
// its value alone, which would drop the name, unit, tolerance and comment of a Var from the key (a changed comment
// would no longer redo the cells that read it).  numpy takes float(x).
double now(const ScalarPtr& s) {
  return s->eval(nullptr);
}

// The other operand of a comparison or a rounding division: an expression or a real number (never a bool: the same
// rule as arithmetic).  nullopt means "not mine": the operator returns NotImplemented and Python tries the other side.
std::optional<double> other_value(const py::handle& other) {
  if (py::isinstance<ScalarNode>(other))
    return now(py::cast<ScalarPtr>(other));
  if (PyBool_Check(other.ptr()))
    return std::nullopt;
  if (PyLong_Check(other.ptr()) || PyFloat_Check(other.ptr()) ||
      PyObject_IsInstance(other.ptr(), numbers_real().ptr()) == 1) {
    const double value = PyFloat_AsDouble(other.ptr());  // numpy scalars and ints go through __float__ / __index__
    if (value == -1.0 && PyErr_Occurred())
      throw py::error_already_set();
    return value;
  }
  return std::nullopt;
}

py::object not_implemented() {
  return py::reinterpret_borrow<py::object>(Py_NotImplemented);
}

template <class Compare>
py::object compared(const ScalarPtr& s, const py::object& other, Compare compare) {
  const std::optional<double> value = other_value(other);
  if (!value)
    return not_implemented();
  return py::bool_(compare(now(s), *value));
}

// list * var, "ab" * var: Python's own repetition, which asks the Var for __index__.
bool is_repeatable_sequence(const py::handle& o) {
  return PyList_Check(o.ptr()) || PyTuple_Check(o.ptr()) || PyUnicode_Check(o.ptr()) || PyBytes_Check(o.ptr()) ||
         PyByteArray_Check(o.ptr());
}

py::object multiplied(const ScalarPtr& s, const py::object& other, bool reflected) {
  if (is_repeatable_sequence(other))
    return not_implemented();
  return py::cast(binary("mul", s, other, reflected));
}

py::object floor_divided(const ScalarPtr& s, const py::object& other, bool reflected) {
  const std::optional<double> value = other_value(other);
  if (!value)
    return not_implemented();
  const double self = now(s);
  const double numerator = reflected ? *value : self, denominator = reflected ? self : *value;
  return py::module_::import("builtins")
      .attr("float")(py::module_::import("operator").attr("floordiv")(numerator, denominator));
}

py::object remainder_of(const ScalarPtr& s, const py::object& other, bool reflected) {
  const std::optional<double> value = other_value(other);
  if (!value)
    return not_implemented();
  const double self = now(s);
  const double numerator = reflected ? *value : self, denominator = reflected ? self : *value;
  return py::module_::import("operator").attr("mod")(numerator, denominator);
}

DimensionTolerance tolerance_from(const py::object& value) {
  if (py::isinstance<DimensionTolerance>(value))
    return py::cast<DimensionTolerance>(value);
  if (PyBool_Check(value.ptr()))
    throw scad::TypeError("Tolerance must be a real number or a two-value sequence");
  if (PyObject_IsInstance(value.ptr(), numbers_real().ptr()) == 1) {
    return DimensionTolerance::symmetric(finite_real(value, "deviation"));
  }
  if (py::isinstance<py::sequence>(value) && !py::isinstance<py::str>(value) && !py::isinstance<py::bytes>(value)) {
    const auto seq = py::cast<py::sequence>(value);
    if (py::len(seq) != 2)
      throw scad::ValueError("Asymmetric tolerance must contain exactly two deviations");
    return DimensionTolerance(finite_real(seq[0], "lower_deviation"), finite_real(seq[1], "upper_deviation"));
  }
  throw scad::TypeError("Tolerance must be a real number or a two-value sequence");
}

std::optional<std::string> optional_comment(const py::object& comment) {
  if (comment.is_none())
    return std::nullopt;
  if (!py::isinstance<py::str>(comment))
    throw scad::ValueError("Variable comment must be a string when provided");
  return py::cast<std::string>(comment);
}

// The editor description from var(...)'s keyword arguments.
sr::ParamUi ui_from(const py::object& ui, const py::object& control, const py::object& min, const py::object& max,
                    const py::object& step, const py::object& label, const py::object& group) {
  sr::ParamUi out;
  if (!ui.is_none())
    out = sr::parse_ui_comment(py::cast<std::string>(ui));
  if (!control.is_none())
    out.control = py::cast<std::string>(control);
  const auto number = [](const py::object& v, const char* what) {
    if (PyBool_Check(v.ptr()) || !(PyLong_Check(v.ptr()) || PyFloat_Check(v.ptr()))) {
      throw scad::TypeError(std::string("ui option ") + what + " must be a number");
    }
    return sr::UiNumber{py::cast<double>(v), PyLong_Check(v.ptr()) != 0};
  };
  if (!min.is_none())
    out.min = number(min, "min");
  if (!max.is_none())
    out.max = number(max, "max");
  if (!step.is_none())
    out.step = number(step, "step");
  if (!label.is_none())
    out.label = py::cast<std::string>(label);
  if (!group.is_none())
    out.group = py::cast<std::string>(group);
  return out;
}

std::shared_ptr<const Var> make_python_var(const py::object& name, const py::object& default_value,
                                           const py::object& comment, const py::object& tolerance,
                                           const py::object& unit, const py::object& tolerance_unit,
                                           const std::string& expr_id, sr::ParamUi ui) {
  if (!py::isinstance<py::str>(name) || py::cast<std::string>(name).empty()) {
    throw scad::ValueError("Variable name must be a non-empty string");
  }
  sr::VarSpec spec;
  spec.name = py::cast<std::string>(name);
  spec.default_value = finite_real(default_value, "Variable default");
  spec.comment = optional_comment(comment);
  if (!tolerance.is_none())
    spec.tolerance = tolerance_from(tolerance);
  if (!unit.is_none())
    spec.unit = unit_from(unit);
  if (!tolerance_unit.is_none())
    spec.tolerance_unit = unit_from(tolerance_unit);
  spec.expr_id = expr_id;
  spec.ui = std::move(ui);
  return Var::make(std::move(spec));
}

// `bindings` None: the defaults (what Var.evaluate() means).
double evaluate_node(const ScalarPtr& node, const py::object& bindings) {
  if (bindings.is_none())
    return node->eval(nullptr);
  const scad::Bindings values = bindings_from(bindings);
  return node->eval(&values);
}

// evaluate_scalar(): what an operator does with a scalar argument -- the active session's edits apply.
double evaluate_operand(const ScalarPtr& node, const py::object& bindings) {
  if (bindings.is_none())
    return node->eval(scad::ambient_bindings());
  return evaluate_node(node, bindings);
}

py::object evaluate_value(const py::object& value, const py::object& bindings) {
  if (py::isinstance<py::tuple>(value)) {
    py::list items;
    for (const auto& item : value)
      items.append(evaluate_value(py::reinterpret_borrow<py::object>(item), bindings));
    return py::tuple(items);
  }
  if (py::isinstance<py::list>(value)) {
    py::list out;
    for (const auto& item : value)
      out.append(evaluate_value(py::reinterpret_borrow<py::object>(item), bindings));
    return std::move(out);
  }
  if (py::isinstance<py::dict>(value)) {
    py::dict out;
    for (const auto& item : py::cast<py::dict>(value)) {
      out[item.first] = evaluate_value(py::reinterpret_borrow<py::object>(item.second), bindings);
    }
    return std::move(out);
  }
  const bool scalar = py::isinstance<ScalarNode>(value) || PyLong_Check(value.ptr()) || PyFloat_Check(value.ptr());
  if (scalar && !PyBool_Check(value.ptr()))
    return py::float_(evaluate_operand(lift(value), bindings));
  return value;
}

// canonicalize_params for Python structures: tuples stay tuples, lists lists.
struct Canonical {
  py::object numeric;
  py::object exprs;  // None when nothing in `numeric` was symbolic
};

Canonical canonicalize_value(const py::object& value, sr::ExpressionGraph& graph) {
  if (py::isinstance<py::tuple>(value) || py::isinstance<py::list>(value)) {
    py::list numeric, exprs;
    bool any = false;
    for (const auto& item : value) {
      Canonical c = canonicalize_value(py::reinterpret_borrow<py::object>(item), graph);
      numeric.append(c.numeric);
      exprs.append(c.exprs);
      any = any || !c.exprs.is_none();
    }
    py::object n = py::isinstance<py::tuple>(value) ? py::object(py::tuple(numeric)) : py::object(numeric);
    return {n, any ? py::object(exprs) : py::none()};
  }
  if (py::isinstance<py::dict>(value)) {
    py::dict numeric, exprs;
    for (const auto& item : py::cast<py::dict>(value)) {
      Canonical c = canonicalize_value(py::reinterpret_borrow<py::object>(item.second), graph);
      numeric[py::str(item.first)] = c.numeric;
      if (!c.exprs.is_none())
        exprs[py::str(item.first)] = c.exprs;
    }
    return {numeric, py::len(exprs) > 0 ? py::object(exprs) : py::none()};
  }
  if (py::isinstance<ScalarNode>(value)) {
    const ScalarPtr registered = graph.register_expr(py::cast<ScalarPtr>(value));
    py::dict ref;
    ref["expr_id"] = registered->expr_id();
    return {py::float_(registered->eval(nullptr)), ref};
  }
  if ((PyLong_Check(value.ptr()) || PyFloat_Check(value.ptr())) && !PyBool_Check(value.ptr())) {
    return {py::float_(py::cast<double>(value)), py::none()};
  }
  return {value, py::none()};
}

}  // namespace

void bind_reactive_exprs(py::module_& m) {
  py::class_<DimensionTolerance>(m, "DimensionTolerance")
      .def(py::init([](const py::object& lower, const py::object& upper) {
             return DimensionTolerance(finite_real(lower, "lower_deviation"), finite_real(upper, "upper_deviation"));
           }),
           py::arg("lower_deviation"), py::arg("upper_deviation"))
      .def_static("symmetric",
                  [](const py::object& deviation) {
                    return DimensionTolerance::symmetric(finite_real(deviation, "deviation"));
                  })
      .def_property_readonly("lower_deviation", &DimensionTolerance::lower_deviation)
      .def_property_readonly("upper_deviation", &DimensionTolerance::upper_deviation)
      .def_property_readonly("width", &DimensionTolerance::width)
      .def("to_dict", [](const DimensionTolerance& t) { return value_to_python(t.to_value()); })
      .def_static("from_dict",
                  [](const py::object& data) { return DimensionTolerance::from_value(value_from_python(data)); })
      .def("__eq__",
           [](const DimensionTolerance& a, const py::object& b) {
             return py::isinstance<DimensionTolerance>(b) && a == py::cast<DimensionTolerance>(b);
           })
      .def("__hash__",
           [](const DimensionTolerance& t) {
             return std::hash<double>{}(t.lower_deviation()) * 31 + std::hash<double>{}(t.upper_deviation());
           })
      .def("__repr__", [](const DimensionTolerance& t) {
        return "DimensionTolerance(lower_deviation=" + sr::py_float_repr(t.lower_deviation()) +
               ", upper_deviation=" + sr::py_float_repr(t.upper_deviation()) + ")";
      });

  // ExprBase holds the shared node; Const / Var / Expr are its three kinds.
  py::class_<scad::ExprNode, py::smart_holder>(m, "_ExprNode");
  py::class_<ScalarNode, scad::ExprNode, py::smart_holder> base(m, "ExprBase");
  base.def_property_readonly("expr_id", &ScalarNode::expr_id)
      .def(
          "evaluate", [](const ScalarPtr& self, const py::object& bindings) { return evaluate_node(self, bindings); },
          py::arg("bindings") = py::none())
      .def("__float__", [](const ScalarPtr& self) { return now(self); })
      .def("__int__",
           [](const ScalarPtr& self) { return py::reinterpret_steal<py::object>(PyLong_FromDouble(now(self))); })
      .def("__index__",
           [](const ScalarPtr& self) {
             const double value = now(self);
             if (!std::isfinite(value) || value != std::floor(value))
               throw scad::TypeError(self->repr() + " has the value " +
                                     py::cast<std::string>(py::str(py::float_(value))) +
                                     ", which is not a whole number: it cannot be used as an index or a count");
             return py::reinterpret_steal<py::object>(PyLong_FromDouble(value));
           })
      .def(
          "__round__",
          [](const ScalarPtr& self, const py::object& digits) {
            return py::module_::import("builtins").attr("round")(py::float_(now(self)), digits);
          },
          py::arg("ndigits") = py::none())
      .def("__floor__", [](const ScalarPtr& self) { return py::module_::import("math").attr("floor")(now(self)); })
      .def("__ceil__", [](const ScalarPtr& self) { return py::module_::import("math").attr("ceil")(now(self)); })
      .def("__trunc__", [](const ScalarPtr& self) { return py::module_::import("math").attr("trunc")(now(self)); })
      .def("__format__",
           [](const ScalarPtr& self, const py::object& spec) {
             return py::module_::import("builtins").attr("format")(py::float_(now(self)), spec);
           })
      .def("__str__", [](const ScalarPtr& self) { return py::cast<std::string>(py::str(py::float_(now(self)))); })
      .def(
          "__lt__", [](const ScalarPtr& s, const py::object& o) { return compared(s, o, std::less<double>()); },
          py::is_operator())
      .def(
          "__le__", [](const ScalarPtr& s, const py::object& o) { return compared(s, o, std::less_equal<double>()); },
          py::is_operator())
      .def(
          "__gt__", [](const ScalarPtr& s, const py::object& o) { return compared(s, o, std::greater<double>()); },
          py::is_operator())
      .def(
          "__ge__",
          [](const ScalarPtr& s, const py::object& o) { return compared(s, o, std::greater_equal<double>()); },
          py::is_operator())
      .def(
          "__floordiv__", [](const ScalarPtr& s, const py::object& o) { return floor_divided(s, o, false); },
          py::is_operator())
      .def(
          "__rfloordiv__", [](const ScalarPtr& s, const py::object& o) { return floor_divided(s, o, true); },
          py::is_operator())
      .def(
          "__mod__", [](const ScalarPtr& s, const py::object& o) { return remainder_of(s, o, false); },
          py::is_operator())
      .def(
          "__rmod__", [](const ScalarPtr& s, const py::object& o) { return remainder_of(s, o, true); },
          py::is_operator())
      // 2.2.6 pins this with a test (the reason is not recorded there): the error stays; compare explicitly.
      .def("__bool__",
           [](const ScalarPtr&) -> bool {
             throw scad::TypeError("Expression objects do not define truthiness. Evaluate them explicitly first.");
           })
      .def(
          "__add__", [](const ScalarPtr& s, const py::object& o) { return binary("add", s, o, false); },
          py::is_operator())
      .def(
          "__radd__", [](const ScalarPtr& s, const py::object& o) { return binary("add", s, o, true); },
          py::is_operator())
      .def(
          "__sub__", [](const ScalarPtr& s, const py::object& o) { return binary("sub", s, o, false); },
          py::is_operator())
      .def(
          "__rsub__", [](const ScalarPtr& s, const py::object& o) { return binary("sub", s, o, true); },
          py::is_operator())
      .def(
          "__mul__", [](const ScalarPtr& s, const py::object& o) { return multiplied(s, o, false); }, py::is_operator())
      .def(
          "__rmul__", [](const ScalarPtr& s, const py::object& o) { return multiplied(s, o, true); }, py::is_operator())
      .def(
          "__truediv__", [](const ScalarPtr& s, const py::object& o) { return binary("div", s, o, false); },
          py::is_operator())
      .def(
          "__rtruediv__", [](const ScalarPtr& s, const py::object& o) { return binary("div", s, o, true); },
          py::is_operator())
      .def(
          "__pow__", [](const ScalarPtr& s, const py::object& o) { return binary("pow", s, o, false); },
          py::is_operator())
      .def(
          "__rpow__", [](const ScalarPtr& s, const py::object& o) { return binary("pow", s, o, true); },
          py::is_operator())
      .def("__neg__", [](const ScalarPtr& s) { return unary("neg", s); })
      .def("__abs__", [](const ScalarPtr& s) { return unary("abs", s); })
      .def("__eq__",
           [](const ScalarPtr& s, const py::object& o) {
             if (py::isinstance<ScalarNode>(o))
               return sr::same_expression(*s, *py::cast<ScalarPtr>(o));  // two expressions: the same formula
             const std::optional<double> value = other_value(o);         // an expression and a number: the same value
             return value && now(s) == *value;
           })
      .def("__hash__", [](const ScalarPtr& s) { return std::hash<std::string>{}(s->expr_id()); })
      .def("__repr__", [](const ScalarPtr& s) { return s->repr(); });

  py::class_<Const, ScalarNode, py::smart_holder>(m, "Const")
      .def(py::init([](const py::object& value, const std::string& expr_id) {
             return std::const_pointer_cast<Const>(Const::make(finite_real(value, "value"), expr_id));
           }),
           py::arg("value"), py::arg("expr_id") = "")
      .def_property_readonly("value", &Const::value);

  py::class_<Var, ScalarNode, py::smart_holder>(m, "Var")
      .def(py::init([](const py::object& name, const py::object& default_value, const py::object& comment,
                       const std::string& expr_id, const py::object& tolerance, const py::object& unit,
                       const py::object& tolerance_unit, const py::object& ui, const py::object& control,
                       const py::object& min, const py::object& max, const py::object& step, const py::object& label,
                       const py::object& group) {
             return std::const_pointer_cast<Var>(make_python_var(name, default_value, comment, tolerance, unit,
                                                                 tolerance_unit, expr_id,
                                                                 ui_from(ui, control, min, max, step, label, group)));
           }),
           py::arg("name"), py::arg("default"), py::arg("comment") = py::none(), py::arg("expr_id") = "",
           py::arg("tolerance") = py::none(), py::arg("unit") = py::none(), py::arg("tolerance_unit") = py::none(),
           py::kw_only(), py::arg("ui") = py::none(), py::arg("control") = py::none(), py::arg("min") = py::none(),
           py::arg("max") = py::none(), py::arg("step") = py::none(), py::arg("label") = py::none(),
           py::arg("group") = py::none())
      .def_property_readonly("name", &Var::name)
      .def_property_readonly("default", &Var::default_value)
      .def_property_readonly(
          "comment",
          [](const Var& v) -> py::object { return v.comment() ? py::object(py::str(*v.comment())) : py::none(); })
      .def_property_readonly(
          "tolerance", [](const Var& v) -> py::object { return v.tolerance() ? py::cast(*v.tolerance()) : py::none(); })
      .def_property_readonly("unit",
                             [](const Var& v) -> py::object { return v.unit() ? py::cast(*v.unit()) : py::none(); })
      .def_property_readonly(
          "tolerance_unit",
          [](const Var& v) -> py::object { return v.tolerance_unit() ? py::cast(*v.tolerance_unit()) : py::none(); })
      .def_property_readonly(
          "dimension", [](const Var& v) -> py::object { return v.dimension() ? py::cast(*v.dimension()) : py::none(); })
      .def_property_readonly("canonical_default", &Var::canonical_default)
      .def_property_readonly("canonical_tolerance",
                             [](const Var& v) -> py::object {
                               const auto t = v.canonical_tolerance();
                               return t ? py::cast(*t) : py::none();
                             })
      .def_property_readonly("ui", [](const Var& v) { return value_to_python(v.param_spec().to_value()); })
      .def("param_spec", [](const Var& v) { return value_to_python(v.param_spec().to_value()); })
      .def("with_default",
           [](const Var& v, const py::object& value) { return v.with_default(finite_real(value, "Variable default")); })
      .def("replace", [](const Var& v, const py::kwargs& changes) {
        // dataclasses.replace: every field kept unless given; expr_id included.
        const py::object none = py::none();
        const auto get = [&](const char* key, const py::object& fallback) {
          return changes.contains(key) ? py::reinterpret_borrow<py::object>(changes[key]) : fallback;
        };
        for (const auto& item : changes) {
          const std::string key = py::cast<std::string>(item.first);
          static const std::unordered_set<std::string> allowed{"name",      "default", "comment",       "expr_id",
                                                               "tolerance", "unit",    "tolerance_unit"};
          if (allowed.count(key) == 0)
            throw scad::TypeError("Var.replace() got an unexpected field '" + key + "'");
        }
        const py::object current_tolerance = v.tolerance() ? py::cast(*v.tolerance()) : none;
        const py::object current_unit = v.unit() ? py::cast(*v.unit()) : none;
        const py::object current_tol_unit = v.tolerance_unit() ? py::cast(*v.tolerance_unit()) : none;
        const py::object current_comment = v.comment() ? py::object(py::str(*v.comment())) : none;
        return make_python_var(get("name", py::str(v.name())), get("default", py::float_(v.default_value())),
                               get("comment", current_comment), get("tolerance", current_tolerance),
                               get("unit", current_unit), get("tolerance_unit", current_tol_unit),
                               py::cast<std::string>(get("expr_id", py::str(v.expr_id()))), v.ui());
      });

  py::class_<Expr, ScalarNode, py::smart_holder>(m, "Expr")
      .def(py::init([](const std::string& op, const py::object& args, const std::string& expr_id) {
             std::vector<ScalarPtr> nodes;
             for (const auto& arg : args) {
               if (!py::isinstance<ScalarNode>(arg))
                 throw scad::TypeError("Expression arguments must be scalar expression nodes");
               nodes.push_back(py::cast<ScalarPtr>(arg));
             }
             return std::const_pointer_cast<Expr>(Expr::make(op, std::move(nodes), expr_id));
           }),
           py::arg("op"), py::arg("args"), py::arg("expr_id") = "")
      .def_property_readonly("op", &Expr::op)
      .def_property_readonly("args", [](const Expr& e) {
        py::tuple out(e.args().size());
        for (std::size_t i = 0; i < e.args().size(); ++i)
          out[i] = py::cast(e.args()[i]);
        return out;
      });

  m.def(
      "const", [](const py::object& value) { return sr::make_const(finite_real(value, "Constant value")); },
      py::arg("value"));
  m.def(
      "var",
      [](const py::object& name, const py::object& default_value, const py::object& comment,
         const py::object& tolerance, const py::object& unit, const py::object& tolerance_unit, const py::object& ui,
         const py::object& control, const py::object& min, const py::object& max, const py::object& step,
         const py::object& label, const py::object& group) {
        return make_python_var(name, default_value, comment, tolerance, unit, tolerance_unit, "",
                               ui_from(ui, control, min, max, step, label, group));
      },
      py::arg("name"), py::arg("default"), py::arg("comment") = py::none(), py::arg("tolerance") = py::none(),
      py::kw_only(), py::arg("unit") = py::none(), py::arg("tolerance_unit") = py::none(), py::arg("ui") = py::none(),
      py::arg("control") = py::none(), py::arg("min") = py::none(), py::arg("max") = py::none(),
      py::arg("step") = py::none(), py::arg("label") = py::none(), py::arg("group") = py::none(),
      "Create a physical or legacy scalar variable.\n\n"
      "`ui` (the text of a `# ui:` comment) or control/min/max/step/label/group describe the slider, number box\n"
      "or toggle an editor shows for it.");

  const struct {
    const char* name;
    const char* op;
  } functions[] = {{"sin", "sin"},   {"cos", "cos"},   {"tan", "tan"},  {"sqrt", "sqrt"},
                   {"acos", "acos"}, {"asin", "asin"}, {"atan", "atan"}};
  for (const auto& fn : functions) {
    const std::string op = fn.op;
    m.def(fn.name, [op](const py::object& value) { return Expr::make(op, {lift(value)}); }, py::arg("value"));
  }
  m.def(
      "atan2", [](const py::object& y, const py::object& x) { return Expr::make("atan2", {lift(y), lift(x)}); },
      py::arg("y"), py::arg("x"));

  m.def("lift_scalar", [](const py::object& value) { return lift(value); }, py::arg("value"));
  m.def(
      "evaluate_scalar",
      [](const py::object& value, const py::object& bindings) { return evaluate_operand(lift(value), bindings); },
      py::arg("value"), py::arg("bindings") = py::none(),
      "The number a scalar stands for: defaults, the active GraphSession's variable edits, or `bindings`.");
  m.def("evaluate_value", &evaluate_value, py::arg("value"), py::arg("bindings") = py::none());
  m.def(
      "infer_dimension",
      [](const py::object& value) -> py::object {
        const auto dimension = sr::infer_dimension(lift(value));
        return dimension ? py::cast(*dimension) : py::none();
      },
      py::arg("value"));
  m.def(
      "expression_uses_units", [](const py::object& value) { return sr::expression_uses_units(lift(value)); },
      py::arg("value"));

  py::class_<sr::ExpressionGraph>(m, "ExpressionGraph")
      .def(py::init<>())
      .def_property_readonly("node_count", &sr::ExpressionGraph::node_count)
      .def(
          "get",
          [](const sr::ExpressionGraph& g, const std::string& id) -> py::object {
            const ScalarPtr node = g.get(id);
            return node ? py::cast(node) : py::none();
          },
          py::arg("expr_id"))
      .def(
          "register", [](sr::ExpressionGraph& g, const py::object& value) { return g.register_expr(lift(value)); },
          py::arg("value"))
      .def("to_dict", [](const sr::ExpressionGraph& g) { return value_to_python(g.to_value()); })
      .def_static("from_dict",
                  [](const py::object& data) { return sr::ExpressionGraph::from_value(value_from_python(data)); });

  m.def(
      "canonicalize_params",
      [](const py::object& params, sr::ExpressionGraph& graph) {
        py::dict numeric, exprs;
        if (!params.is_none()) {
          for (const auto& item : py::cast<py::dict>(params)) {
            const std::string key = py::cast<std::string>(py::str(item.first));
            if (sr::is_discrete_param_name(key)) {
              numeric[py::str(key)] = item.second;
              continue;
            }
            Canonical c = canonicalize_value(py::reinterpret_borrow<py::object>(item.second), graph);
            numeric[py::str(key)] = c.numeric;
            if (!c.exprs.is_none())
              exprs[py::str(key)] = c.exprs;
          }
        }
        return py::make_tuple(numeric, exprs);
      },
      py::arg("params"), py::arg("expression_graph"));

  m.def(
      "referenced_expressions",
      [](const py::object& param_exprs, const sr::ExpressionGraph& graph) {
        const std::vector<ScalarPtr> found = sr::referenced_expressions(value_from_python(param_exprs), graph);
        py::tuple out(found.size());
        for (std::size_t i = 0; i < found.size(); ++i)
          out[i] = py::cast(found[i]);
        return out;
      },
      py::arg("param_exprs"), py::arg("expression_graph"));

  m.def(
      "parse_ui_comment",
      [](const std::string& text) {
        const sr::ParamUi ui = sr::parse_ui_comment(text);
        const sr::ParamSpec spec = sr::make_param_spec("", sr::ParamKind::Float, Value(0.0), ui);
        Value out = Value::object();
        out.set("control", ui.control.empty() ? Value() : Value(ui.control));
        out.set("min", ui.min ? ui.min->to_value() : Value());
        out.set("max", ui.max ? ui.max->to_value() : Value());
        out.set("step", ui.step ? ui.step->to_value() : Value());
        out.set("unit", ui.unit ? Value(*ui.unit) : Value());
        out.set("label", ui.label ? Value(*ui.label) : Value());
        Value issues = Value::array();
        for (const std::string& issue : ui.issues)
          issues.push_back(issue);
        out.set("issues", issues);
        (void)spec;
        return value_to_python(out);
      },
      py::arg("text"), "Parse the text of a `# ui:` comment (slider(1, 5, step=1, unit='mm')).");
  m.def(
      "make_param_spec",
      [](const std::string& name, const std::string& kind, const py::object& default_value, const py::object& ui,
         const std::string& declared) {
        sr::ParamKind k = sr::ParamKind::Float;
        if (kind == "int")
          k = sr::ParamKind::Int;
        else if (kind == "bool")
          k = sr::ParamKind::Bool;
        else if (kind != "float")
          throw scad::ValueError("kind must be 'float', 'int' or 'bool'");
        const sr::ParamUi parsed = ui.is_none() ? sr::ParamUi{} : sr::parse_ui_comment(py::cast<std::string>(ui));
        return value_to_python(
            sr::make_param_spec(name, k, value_from_python(default_value), parsed, declared).to_value());
      },
      py::arg("name"), py::arg("kind"), py::arg("default"), py::arg("ui") = py::none(),
      py::arg("declared") = "literal");
}

}  // namespace scad::pybind::reactive
