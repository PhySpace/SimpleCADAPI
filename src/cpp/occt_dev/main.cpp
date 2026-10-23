#include "../bindings/python/occt/occt.hpp"

PYBIND11_MODULE(_occt_dev, m) {
  scad::pybind::occt::bind_occt(m);  // creates the `_occt` submodule: _occt_dev._occt.<Class>
  m.attr("flat") = m.attr("_occt");
}
