// simplecadapi.math: fit_cubic_bspline_control_points and BSplineFitResult.
#include "bind_reactive_common.hpp"

#include "scad/core/error.hpp"
#include <cmath>

#include "scad/reactive/bspline_fit.hpp"

namespace scad::pybind::reactive {

namespace sr = scad::reactive;

namespace {

double as_float(const py::handle& value) {
  const py::object number = py::reinterpret_steal<py::object>(PyNumber_Float(value.ptr()));
  if (!number)
    throw py::error_already_set();
  return PyFloat_AS_DOUBLE(number.ptr());
}

py::tuple tuple_of(const std::vector<double>& values) {
  py::tuple out(values.size());
  for (std::size_t i = 0; i < values.size(); ++i)
    out[i] = values[i];
  return out;
}

}  // namespace

void bind_reactive_math(py::module_& m) {
  py::module_ math = m.def_submodule("math", "Math helpers for CAD-friendly curve parameterization.");
  // Importable as <package>.math, like simplecadapi.math.
  const std::string qualified = scad::error_module_name() + ".math";
  math.attr("__name__") = qualified;
  py::module_::import("sys").attr("modules")[py::str(qualified)] = math;

  const auto bind_into = [](py::module_& target) {
    py::class_<sr::BSplineFit>(target, "BSplineFitResult")
        .def_readonly("degree", &sr::BSplineFit::degree)
        .def_property_readonly("control_points",
                               [](const sr::BSplineFit& f) {
                                 py::tuple out(f.control_points.size());
                                 for (std::size_t i = 0; i < f.control_points.size(); ++i)
                                   out[i] = tuple_of(f.control_points[i]);
                                 return out;
                               })
        .def_property_readonly("knots", [](const sr::BSplineFit& f) { return tuple_of(f.knots); })
        .def_property_readonly("sample_parameters",
                               [](const sr::BSplineFit& f) { return tuple_of(f.sample_parameters); })
        .def_readonly("max_error", &sr::BSplineFit::max_error)
        .def_readonly("rms_error", &sr::BSplineFit::rms_error)
        .def_readonly("tolerance", &sr::BSplineFit::tolerance)
        .def_readonly("fairing", &sr::BSplineFit::fairing)
        .def_readonly("iterations", &sr::BSplineFit::iterations)
        .def_readonly("converged", &sr::BSplineFit::converged)
        .def_property_readonly("control_count", &sr::BSplineFit::control_count)
        .def_property_readonly("dimension", &sr::BSplineFit::dimension)
        .def_property_readonly("unique_knots", [](const sr::BSplineFit& f) { return tuple_of(f.unique_knots()); })
        .def_property_readonly("multiplicities",
                               [](const sr::BSplineFit& f) {
                                 const std::vector<int> values = f.multiplicities();
                                 py::tuple out(values.size());
                                 for (std::size_t i = 0; i < values.size(); ++i)
                                   out[i] = values[i];
                                 return out;
                               })
        .def(
            "evaluate",
            [](const sr::BSplineFit& f, const py::object& parameter) {
              return tuple_of(f.evaluate(as_float(parameter)));
            },
            py::arg("parameter"))
        .def("to_dict", [](const sr::BSplineFit& f) { return value_to_python(f.to_value()); });

    target.def(
        "fit_cubic_bspline_control_points",
        [](const py::object& sample_points, const py::object& tolerance, const py::object& max_control_points,
           const py::object& fairing, const py::object& duplicate_tolerance, const py::object& knot_tolerance,
           bool raise_on_failure) {
          sr::BSplineFitOptions options;
          options.tolerance = as_float(tolerance);
          options.fairing = as_float(fairing);
          options.knot_tolerance = as_float(knot_tolerance);
          options.duplicate_tolerance = as_float(duplicate_tolerance);
          if (!max_control_points.is_none())
            options.max_control_points = py::cast<int>(max_control_points);
          options.raise_on_failure = raise_on_failure;
          if (options.tolerance <= 0.0 || !std::isfinite(options.tolerance)) {
            throw scad::ValueError("tolerance must be a finite positive number");
          }
          std::vector<std::vector<double>> samples;
          std::size_t index = 0;
          for (const auto& item : sample_points) {
            std::vector<double> point;
            try {
              for (const auto& component : item)
                point.push_back(as_float(component));
            } catch (const py::error_already_set&) {
              throw scad::ValueError("sample point " + std::to_string(index) + " is not a numeric sequence");
            }
            samples.push_back(std::move(point));
            ++index;
          }
          return sr::fit_cubic_bspline_control_points(samples, options);
        },
        py::arg("sample_points"), py::kw_only(), py::arg("tolerance") = 1e-3,
        py::arg("max_control_points") = py::none(), py::arg("fairing") = 1e-6, py::arg("duplicate_tolerance") = 1e-12,
        py::arg("knot_tolerance") = 1e-9, py::arg("raise_on_failure") = true,
        "Fit a minimal cubic B-spline control polygon to sampled curve points.");
  };
  bind_into(math);
  // The top level re-exports the same objects, like simplecadapi.__init__.
  m.attr("BSplineFitResult") = math.attr("BSplineFitResult");
  m.attr("fit_cubic_bspline_control_points") = math.attr("fit_cubic_bspline_control_points");
}

}  // namespace scad::pybind::reactive
