#include "bindings.hpp"
#include "occt/occt.hpp"
#include "scad/core/error.hpp"

PYBIND11_MODULE(_native, m, py::mod_gil_not_used()) {
  m.doc() = "SimpleCADAPI on OpenCASCADE, implemented in C++ (pybind11).";
  scad::set_error_module_name("simplecadapi._cpp");
  scad::pybind::register_exceptions(m);

  bind_core(m);
  bind_topo(m);
  bind_reactive(m);   // before the operator areas: they accept Scalar expressions
  bind_semantic(m);
  bind_io(m);
  bind_ql(m);
  bind_render(m);
  bind_ops_geometry(m);
  bind_ops_features(m);
  bind_sketch(m);
  bind_surface(m);
  bind_std(m);
  bind_product(m);
  bind_canonical(m);
  bind_sdk_compat(m);  // names the Python layers above import from the lower modules
  scad::pybind::occt::bind_occt(m);  // the OCCT classes the kept Python layers use (OCP's names)
}
