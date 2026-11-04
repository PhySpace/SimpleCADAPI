#include "bindings.hpp"

#include "scad/core/tolerance.hpp"
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
             if (p.v.norm() <= scad::tol::kZeroDirectionNorm)
               throw scad::ValueError("Cannot normalize a zero-length vector");
             return PyVec3{p.v.normalized()};
           })
      .def("getAngle",
           [](const PyVec3& p, const scad::Vec3& o) {
             const double sn = p.v.norm(), on = o.norm();
             if (sn <= scad::tol::kZeroDirectionNorm || on <= scad::tol::kZeroDirectionNorm)
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

  const auto tuple3 = [](const scad::Vec3& v) { return py::make_tuple(v.x, v.y, v.z); };
  py::class_<Workplane>(m, "SimpleWorkplane",
                        "A workplane: a frame in world coordinates, and the context manager that makes it the current "
                        "coordinate system (`with wp:`).  A value: it can be entered again, pickled, and given to "
                        "make_sketch_rsketch(plane=wp).")
      .def(py::init([](const py::object& origin, const py::object& normal, const py::object& x_dir) {
             return std::make_unique<Workplane>(vec_from_python(origin), vec_from_python(normal),
                                                vec_from_python(x_dir));
           }),
           py::arg("origin") = py::make_tuple(0, 0, 0), py::arg("normal") = py::make_tuple(0, 0, 1),
           py::arg("x_dir") = py::make_tuple(1, 0, 0))
      .def_static(
          "_from_frame",
          [](const py::object& origin, const py::object& x_axis, const py::object& y_axis) {
            return Workplane::from_frame(
                CoordinateSystem(vec_from_python(origin), vec_from_python(x_axis), vec_from_python(y_axis)));
          },
          py::arg("origin"), py::arg("x_axis"), py::arg("y_axis"))
      .def_property_readonly("cs", &Workplane::cs, py::return_value_policy::reference_internal)
      .def_property_readonly(
          "origin", [tuple3](const Workplane& w) { return tuple3(w.origin()); }, "The origin in world coordinates.")
      .def_property_readonly(
          "normal", [tuple3](const Workplane& w) { return tuple3(w.normal()); },
          "The unit normal (the local z axis) in world coordinates.")
      .def_property_readonly(
          "x_dir", [tuple3](const Workplane& w) { return tuple3(w.x_dir()); }, "The unit x axis in world coordinates.")
      .def_property_readonly(
          "y_dir", [tuple3](const Workplane& w) { return tuple3(w.y_dir()); }, "The unit y axis in world coordinates.")
      .def_property_readonly(
          "plane", [](const Workplane& w) { return scad::pybind::value_to_python(w.plane_value()); },
          "The frame as a sketch plane mapping {'origin', 'x_axis', 'y_axis'} (world coordinates).")
      .def(
          "point",
          [tuple3](const Workplane& w, double u, double v, double h) {
            return tuple3(w.cs().transform_point({u, v, h}));
          },
          py::arg("u"), py::arg("v"), py::arg("w") = 0.0,
          "The world point (x, y, z) at (u, v) in the plane (and w along its normal): where a point drawn on this "
          "workplane is, so it moves with the workplane.")
      .def(
          "__enter__",
          [](Workplane& w) -> Workplane& {
            w.enter();
            return w;
          },
          py::return_value_policy::reference)
      .def("__exit__", [](Workplane& w, const py::object&, const py::object&, const py::object&) { w.exit(); })
      .def("set_metadata",
           [](const Workplane& w, const std::string& key, const scad::Value& value) { w.set_metadata(key, value); })
      .def(
          "get_metadata",
          [](const Workplane& w, const std::string& key, const scad::Value& fallback) {
            return w.get_metadata(key, fallback);
          },
          py::arg("key"), py::arg("default") = scad::Value())
      .def("_set_runtime",
           [](const Workplane& w, const std::string& key, const scad::Value& value) { w.set_runtime(key, value); })
      .def(
          "_get_runtime",
          [](const Workplane& w, const std::string& key, const scad::Value& fallback) {
            return w.get_runtime(key, fallback);
          },
          py::arg("key"), py::arg("default") = scad::Value())
      .def("_metadata_dict", [](const Workplane& w) { return scad::pybind::value_to_python(w.metadata()); })
      .def("_runtime_dict", [](const Workplane& w) { return scad::pybind::value_to_python(w.runtime()); })
      .def("__copy__", [](const Workplane& w) { return Workplane(w); })
      .def(
          "__deepcopy__", [](const Workplane& w, const py::object&) { return Workplane(w); }, py::arg("memo"))
      // The cell cache pickles cell outputs: the exact frame, then the dictionaries (the graph lineage is in
      // the runtime one, so a restored workplane is still the output of the node that made it).
      .def(py::pickle(
          [tuple3](const Workplane& w) {
            return py::make_tuple(tuple3(w.origin()), tuple3(w.x_dir()), tuple3(w.y_dir()),
                                  scad::pybind::value_to_python(w.metadata()),
                                  scad::pybind::value_to_python(w.runtime()));
          },
          [](const py::tuple& state) {
            if (state.size() != 5)
              throw std::runtime_error("Invalid SimpleWorkplane state");
            Workplane w = Workplane::from_frame(
                CoordinateSystem(vec_from_python(state[0]), vec_from_python(state[1]), vec_from_python(state[2])));
            for (const auto& [key, value] : state[3].cast<py::dict>())
              w.set_metadata(key.cast<std::string>(), scad::pybind::value_from_python(value));
            for (const auto& [key, value] : state[4].cast<py::dict>())
              w.set_runtime(key.cast<std::string>(), scad::pybind::value_from_python(value));
            return w;
          }))
      .def("_format_string", &Workplane::to_string, py::arg("indent") = 0, py::arg("show_coordinate_system") = true)
      .def("__str__", [](const Workplane& w) { return w.to_string(0, true); })
      .def("__repr__", &Workplane::repr);
  m.attr("Workplane") = m.attr("SimpleWorkplane");

  m.def("get_current_cs", [] { return scad::current_cs(); });
  // The recorded workplane the innermost frame comes from: {"graph_id", "node_id", "output_slot"} or None.
  m.def("get_current_frame_source", []() -> py::object {
    const scad::FrameSource* source = scad::current_frame_source();
    if (source == nullptr)
      return py::none();
    py::dict out;
    out["graph_id"] = source->graph_id;
    out["node_id"] = source->node_id;
    out["output_slot"] = source->output_slot;
    return std::move(out);
  });

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
