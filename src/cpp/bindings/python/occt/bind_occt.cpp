#include "occt.hpp"

namespace scad::pybind::occt {

void bind_occt(py::module_& m) {
  py::module_ occt = m.def_submodule("_occt", "OCCT classes under their OCP names (see occt.hpp)");
  bind_core(occt);
  bind_query(occt);
  bind_algo(occt);
  bind_step(occt);
}

}  // namespace scad::pybind::occt
