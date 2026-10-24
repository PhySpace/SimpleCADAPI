// The OCCT classes the Python layers above the C++ library still talk to (STEP/BREP inspection, drawing, DXF,
// translators), exposed under the names and with the call shapes of the `OCP` package -- so that code written
// against OCP runs on the OpenCASCADE this module already carries, and OCP itself is not needed.
//
// Only what those layers (and their tests) call is bound: the surface is measured, not copied.  Every class lives
// in the flat submodule `simplecadapi._cpp._native._occt`; the pure-Python package `simplecadapi._cpp.occt` lays it out
// in OCP's module structure (`from simplecadapi._cpp.occt.TopoDS import TopoDS_Shape`).
//
// Calls follow OCP, not C++: out-parameters are mutated in place (`BRepAdaptor_Curve.D1(u, pnt, vec)`), a static
// method `Foo::Bar` is `Foo.Bar_s`, an enum value is both `Enum.Name` and a module-level `Name`.
#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>
#include <pybind11/operators.h>

#include <Standard_Handle.hxx>

namespace py = pybind11;

// OCCT's reference-counted classes (Geom_*, Poly_Triangulation, TDocStd_Document, ...) travel as opencascade::handle.
PYBIND11_DECLARE_HOLDER_TYPE(T, opencascade::handle<T>, true)
namespace pybind11::detail {
template <typename T>
struct holder_helper<opencascade::handle<T>> {
  static const T* get(const opencascade::handle<T>& p) { return p.get(); }
};
}  // namespace pybind11::detail

namespace scad::pybind::occt {

// Each area registers its classes on the flat submodule, in this order (a class may name one registered before it).
void bind_core(py::module_& m);    // gp_*, enums, TopLoc, TopoDS_*, TopExp, TopTools_*, Precision, BRep_Tool/Builder
void bind_query(py::module_& m);   // BRepAdaptor_*, BRepGProp/GProp, Bnd/BRepBndLib, classifiers, extrema, Geom_* curves/surfaces
void bind_algo(py::module_& m);    // booleans, builders, primitives, fillet, transform/copy, mesh, HLR, shape upgrade
void bind_step(py::module_& m);    // STEP/XCAF/TDF/TCollection/Quantity/Step*, BinTools, IO of BREP

void bind_occt(py::module_& m);

}  // namespace scad::pybind::occt

#include <TopAbs_ShapeEnum.hxx>
#include <TopoDS.hxx>
#include <TopoDS_CompSolid.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>

namespace scad::pybind::occt {

// A shape as the Python class of its type (TopoDS_Solid, ...): `.wrapped` of a native shape, and what an explorer
// hands back once the caller has asked for a type.
inline py::object shape_to_python(const TopoDS_Shape& shape) {
  if (shape.IsNull()) return py::cast(shape);
  switch (shape.ShapeType()) {
    case TopAbs_VERTEX: return py::cast(TopoDS::Vertex(shape));
    case TopAbs_EDGE: return py::cast(TopoDS::Edge(shape));
    case TopAbs_WIRE: return py::cast(TopoDS::Wire(shape));
    case TopAbs_FACE: return py::cast(TopoDS::Face(shape));
    case TopAbs_SHELL: return py::cast(TopoDS::Shell(shape));
    case TopAbs_SOLID: return py::cast(TopoDS::Solid(shape));
    case TopAbs_COMPSOLID: return py::cast(TopoDS::CompSolid(shape));
    case TopAbs_COMPOUND: return py::cast(TopoDS::Compound(shape));
    default: return py::cast(shape);
  }
}

}  // namespace scad::pybind::occt
