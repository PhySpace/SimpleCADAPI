#include "bindings.hpp"

#include "scad/core/coordinate_system.hpp"
#include <cmath>
#include <cstdio>

#include "scad/core/error.hpp"

namespace {

py::array_t<double> as_array(const scad::Vec3& v) {
  py::array_t<double> a(3);
  auto r = a.mutable_unchecked<1>();
  r(0) = v.x;
  r(1) = v.y;
  r(2) = v.z;
  return a;
}

scad::Vec3 vec_from_python(const py::object& o) {
  return o.cast<scad::Vec3>();
}

}  // namespace

void bind_core(py::module_& m) {
  using scad::pybind::PyVec3;
  py::class_<PyVec3>(m, "Vec3")
      .def(py::init([](double x, double y, double z) { return PyVec3{{x, y, z}}; }))
      .def_property_readonly("x", [](const PyVec3& p) { return p.v.x; })
      .def_property_readonly("y", [](const PyVec3& p) { return p.v.y; })
      .def_property_readonly("z", [](const PyVec3& p) { return p.v.z; })
      .def("to_tuple", [](const PyVec3& p) { return py::make_tuple(p.v.x, p.v.y, p.v.z); })
      .def("__iter__", [](const PyVec3& p) { return py::iter(py::make_tuple(p.v.x, p.v.y, p.v.z)); })
      .def("dot", [](const PyVec3& p, const scad::Vec3& o) { return p.v.dot(o); })
      .def("norm", [](const PyVec3& p) { return p.v.norm(); })
      .def("normalized",
           [](const PyVec3& p) {
             if (p.v.norm() <= 1e-15)
               throw scad::ValueError("Cannot normalize a zero-length vector");
             return PyVec3{p.v.normalized()};
           })
      .def("getAngle",
           [](const PyVec3& p, const scad::Vec3& o) {
             const double sn = p.v.norm(), on = o.norm();
             if (sn <= 1e-15 || on <= 1e-15)
               throw scad::ValueError("Cannot compute angle with a zero-length vector");
             return std::acos(std::max(-1.0, std::min(1.0, p.v.dot(o) / (sn * on))));
           })
      .def("__mul__", [](const PyVec3& p, double s) { return PyVec3{p.v * s}; })
      .def("__rmul__", [](const PyVec3& p, double s) { return PyVec3{p.v * s}; })
      .def("__repr__", [](const PyVec3& p) {
        char buf[160];
        std::snprintf(buf, sizeof buf, "Vec3(%.6g, %.6g, %.6g)", p.v.x, p.v.y, p.v.z);
        return std::string(buf);
      });

  using scad::CoordinateSystem;
  using scad::Workplane;

  py::class_<CoordinateSystem>(m, "CoordinateSystem")
      .def(py::init([](const py::object& origin, const py::object& x_axis, const py::object& y_axis) {
             return CoordinateSystem(vec_from_python(origin), vec_from_python(x_axis), vec_from_python(y_axis));
           }),
           py::arg("origin") = py::make_tuple(0, 0, 0), py::arg("x_axis") = py::make_tuple(1, 0, 0),
           py::arg("y_axis") = py::make_tuple(0, 1, 0))
      .def_property_readonly("origin", [](const CoordinateSystem& c) { return as_array(c.origin()); })
      .def_property_readonly("x_axis", [](const CoordinateSystem& c) { return as_array(c.x_axis()); })
      .def_property_readonly("y_axis", [](const CoordinateSystem& c) { return as_array(c.y_axis()); })
      .def_property_readonly("z_axis", [](const CoordinateSystem& c) { return as_array(c.z_axis()); })
      .def("transform_point", [](const CoordinateSystem& c,
                                 const py::object& p) { return as_array(c.transform_point(vec_from_python(p))); })
      .def("transform_vector", [](const CoordinateSystem& c,
                                  const py::object& v) { return as_array(c.transform_vector(vec_from_python(v))); })
      .def("_format_string", &CoordinateSystem::to_string, py::arg("indent") = 0)
      .def("__str__", [](const CoordinateSystem& c) { return c.to_string(0); })
      .def("__repr__", &CoordinateSystem::repr);

  // The world frame as a module constant, like simplecadapi.WORLD_CS.
  m.attr("WORLD_CS") = py::cast(scad::world_cs());

  py::class_<Workplane>(m, "SimpleWorkplane")
      .def(py::init([](const py::object& origin, const py::object& normal, const py::object& x_dir) {
             return std::make_unique<Workplane>(vec_from_python(origin), vec_from_python(normal),
                                                vec_from_python(x_dir));
           }),
           py::arg("origin") = py::make_tuple(0, 0, 0), py::arg("normal") = py::make_tuple(0, 0, 1),
           py::arg("x_dir") = py::make_tuple(1, 0, 0))
      .def_property_readonly("cs", &Workplane::cs, py::return_value_policy::reference_internal)
      .def(
          "__enter__",
          [](Workplane& w) -> Workplane& {
            w.enter();
            return w;
          },
          py::return_value_policy::reference)
      .def("__exit__", [](Workplane& w, const py::object&, const py::object&, const py::object&) { w.exit(); })
      .def("_format_string", &Workplane::to_string, py::arg("indent") = 0, py::arg("show_coordinate_system") = true)
      .def("__str__", [](const Workplane& w) { return w.to_string(0, true); })
      .def("__repr__", &Workplane::repr);
  m.attr("Workplane") = m.attr("SimpleWorkplane");

  m.def("get_current_cs", [] { return scad::current_cs(); });

  // use_coordinate_system(cs): context manager over the same stack.
  struct CsScope {
    explicit CsScope(CoordinateSystem c) : cs_(std::move(c)) {}
    CoordinateSystem cs_;
    std::unique_ptr<scad::CoordinateSystemScope> scope_;
  };
  py::class_<CsScope>(m, "_CoordinateSystemScope")
      .def("__enter__", [](CsScope& s) { s.scope_ = std::make_unique<scad::CoordinateSystemScope>(s.cs_); })
      .def("__exit__", [](CsScope& s, const py::object&, const py::object&, const py::object&) { s.scope_.reset(); });
  m.def("use_coordinate_system", [](const CoordinateSystem& cs) { return CsScope(cs); });
}
