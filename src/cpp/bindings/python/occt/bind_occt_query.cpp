// Geometry and measurement: Geom_* curves/surfaces, Geom2d_Curve, GeomAbs_*, TColgp_/TColStd_ arrays, BRepAdaptor_*,
// GProp/BRepGProp, Bnd_Box/BRepBndLib, solid/face classifiers, BRepExtrema, BRepLProp, GCPnts, GeomAPI_*, GeomConvert,
// Poly_*, ShapeAnalysis_ShapeTolerance, BRepTools (OuterWire/UVBounds/Clean; the stream Read/Write are the step
// file's), BRepTools_WireExplorer, BRepCheck_*.
//
// Conventions (see docs/OCCT_BINDINGS.md): out-parameters are mutated in place, `Foo::Bar` static is `Bar_s`,
// reference-counted classes travel as opencascade::handle.  Where OCP returns a tuple for a C++ out-parameter
// (Geom_Surface.Bounds, BRepTools.UVBounds_s, ParOnFaceS1, ...) a tuple is returned here too.
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_Result.hxx>
#include <BRepCheck_Shell.hxx>
#include <BRepCheck_Status.hxx>
#include <BRepClass3d_SClassifier.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepClass_FClassifier.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepExtrema_SupportType.hxx>
#include <BRepGProp.hxx>
#include <BRepLProp_SLProps.hxx>
#include <BRepTools.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <Bnd_Box.hxx>
#include <GCPnts_QuasiUniformDeflection.hxx>
#include <GCPnts_TangentialDeflection.hxx>
#include <GProp_GProps.hxx>
#include <Geom2d_Curve.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_Shape.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <GeomConvert.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_BoundedCurve.hxx>
#include <Geom_BoundedSurface.hxx>
#include <Geom_Circle.hxx>
#include <Geom_Conic.hxx>
#include <Geom_Curve.hxx>
#include <Geom_ElementarySurface.hxx>
#include <Geom_Ellipse.hxx>
#include <Geom_Geometry.hxx>
#include <Geom_Line.hxx>
#include <Geom_Plane.hxx>
#include <Geom_Surface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <Poly_Triangle.hxx>
#include <Poly_Triangulation.hxx>
#include <ShapeAnalysis_ShapeTolerance.hxx>
#include <StdFail_NotDone.hxx>
#include <Standard_Failure.hxx>
#include <Standard_NullObject.hxx>
#include <Standard_OutOfRange.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopAbs_State.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Cone.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Elips.hxx>
#include <gp_Hypr.hxx>
#include <gp_Lin.hxx>
#include <gp_Parab.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Sphere.hxx>
#include <gp_Torus.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <gp_Vec2d.hxx>

#include "occt.hpp"

namespace scad::pybind::occt {

namespace {

template <class T>
using H = opencascade::handle<T>;

[[noreturn]] void out_of_range(const char* what) {
  throw Standard_OutOfRange(what);
}

inline void check_index(int i, int lo, int hi, const char* what = "index out of range") {
  if (i < lo || i > hi)
    out_of_range(what);
}

// ---- TColgp / TColStd arrays ---------------------------------------------------------------------------------
// NCollection_Array1 does not range-check in release builds; a Python caller must not be able to read or write
// past the buffer, so every access is checked and raises Standard_OutOfRange.
template <class Array, class Item>
void bind_array1(py::module_& m, const char* name) {
  py::class_<Array>(m, name)
      .def(py::init<>())
      .def(py::init([](int lo, int hi) {
             if (hi < lo - 1)
               out_of_range("upper bound below lower bound");
             return Array(lo, hi);
           }),
           py::arg("theLower"), py::arg("theUpper"))
      .def(py::init([](const Array& other) { return Array(other); }), py::arg("theOther"))
      .def(
          "Assign", [](Array& a, const Array& o) { a.Assign(o); }, py::arg("theOther"))
      .def(
          "UpdateLowerBound", [](Array& a, int lo) { a.UpdateLowerBound(lo); }, py::arg("theLower"))
      .def(
          "UpdateUpperBound", [](Array& a, int hi) { a.UpdateUpperBound(hi); }, py::arg("theUpper"))
      .def(
          "Resize", [](Array& a, int lo, int hi, bool copy) { a.Resize(lo, hi, copy); }, py::arg("theLower"),
          py::arg("theUpper"), py::arg("theToCopyData"))
      .def(
          "Init", [](Array& a, const Item& v) { a.Init(v); }, py::arg("theValue"))
      .def("Size", [](const Array& a) { return a.Size(); })
      .def("Length", [](const Array& a) { return a.Length(); })
      .def("IsEmpty", [](const Array& a) { return a.IsEmpty(); })
      .def("Lower", [](const Array& a) { return a.Lower(); })
      .def("Upper", [](const Array& a) { return a.Upper(); })
      .def("First",
           [](const Array& a) {
             if (a.IsEmpty())
               out_of_range("empty array");
             return a.First();
           })
      .def("Last",
           [](const Array& a) {
             if (a.IsEmpty())
               out_of_range("empty array");
             return a.Last();
           })
      .def(
          "Value",
          [](const Array& a, int i) {
            check_index(i, a.Lower(), a.Upper());
            return a.Value(i);
          },
          py::arg("theIndex"))
      .def(
          "SetValue",
          [](Array& a, int i, const Item& v) {
            check_index(i, a.Lower(), a.Upper());
            a.SetValue(i, v);
          },
          py::arg("theIndex"), py::arg("theItem"))
      .def("__len__", [](const Array& a) { return a.Length(); })
      .def("__iter__", [](const Array& a) {
        py::list items;
        for (int i = a.Lower(); i <= a.Upper(); ++i)
          items.append(py::cast(a.Value(i)));
        return py::iter(items);
      });
}

template <class Array, class Item>
void bind_array2(py::module_& m, const char* name) {
  py::class_<Array>(m, name)
      .def(py::init<>())
      .def(py::init([](int rl, int ru, int cl, int cu) { return Array(rl, ru, cl, cu); }), py::arg("theRowLower"),
           py::arg("theRowUpper"), py::arg("theColLower"), py::arg("theColUpper"))
      .def(py::init([](const Array& other) { return Array(other); }), py::arg("theOther"))
      .def("Size", [](const Array& a) { return a.Size(); })
      .def("Length", [](const Array& a) { return a.Length(); })
      .def("NbRows", [](const Array& a) { return a.NbRows(); })
      .def("NbColumns", [](const Array& a) { return a.NbColumns(); })
      .def("RowLength", [](const Array& a) { return a.RowLength(); })
      .def("ColLength", [](const Array& a) { return a.ColLength(); })
      .def("LowerRow", [](const Array& a) { return a.LowerRow(); })
      .def("UpperRow", [](const Array& a) { return a.UpperRow(); })
      .def("LowerCol", [](const Array& a) { return a.LowerCol(); })
      .def("UpperCol", [](const Array& a) { return a.UpperCol(); })
      .def(
          "Value",
          [](const Array& a, int r, int c) {
            check_index(r, a.LowerRow(), a.UpperRow(), "row out of range");
            check_index(c, a.LowerCol(), a.UpperCol(), "column out of range");
            return a.Value(r, c);
          },
          py::arg("theRow"), py::arg("theCol"))
      .def(
          "SetValue",
          [](Array& a, int r, int c, const Item& v) {
            check_index(r, a.LowerRow(), a.UpperRow(), "row out of range");
            check_index(c, a.LowerCol(), a.UpperCol(), "column out of range");
            a.SetValue(r, c, v);
          },
          py::arg("theRow"), py::arg("theCol"), py::arg("theItem"))
      .def("__len__", [](const Array& a) { return a.Length(); });
}

// A copy of an OCCT-owned array handed back by Poles()/Knots()/... (OCP returns a fresh array too).
template <class Array>
Array copy_of(const Array& a) {
  return Array(a);
}

template <class Cls>
void curve_evaluators(Cls& cls) {
  cls.def(
         "D0", [](const Geom_Curve& c, double u, gp_Pnt& p) { c.D0(u, p); }, py::arg("U"), py::arg("P"))
      .def(
          "D1", [](const Geom_Curve& c, double u, gp_Pnt& p, gp_Vec& v1) { c.D1(u, p, v1); }, py::arg("U"),
          py::arg("P"), py::arg("V1"))
      .def(
          "D2", [](const Geom_Curve& c, double u, gp_Pnt& p, gp_Vec& v1, gp_Vec& v2) { c.D2(u, p, v1, v2); },
          py::arg("U"), py::arg("P"), py::arg("V1"), py::arg("V2"))
      .def(
          "D3",
          [](const Geom_Curve& c, double u, gp_Pnt& p, gp_Vec& v1, gp_Vec& v2, gp_Vec& v3) { c.D3(u, p, v1, v2, v3); },
          py::arg("U"), py::arg("P"), py::arg("V1"), py::arg("V2"), py::arg("V3"))
      .def(
          "DN", [](const Geom_Curve& c, double u, int n) { return c.DN(u, n); }, py::arg("U"), py::arg("N"))
      .def("Value", [](const Geom_Curve& c, double u) { return c.Value(u); }, py::arg("U"));
}

}  // namespace

void bind_query(py::module_& m) {
  // ---- Standard_Failure: OCCT's exceptions are not std::exception, so give Python a real exception type ----------
  {
    static PyObject* failure_type =
        PyErr_NewException("simplecadapi._cpp._native._occt.Standard_Failure", PyExc_Exception, nullptr);
    Py_INCREF(failure_type);
    m.attr("Standard_Failure") = py::reinterpret_borrow<py::object>(failure_type);
    py::register_exception_translator([](std::exception_ptr p) {
      try {
        if (p)
          std::rethrow_exception(p);
      } catch (const Standard_Failure& e) {
        const char* msg = e.GetMessageString();
        std::string text = e.DynamicType()->Name();
        if (msg != nullptr && *msg != '\0')
          text += std::string(": ") + msg;
        PyErr_SetString(failure_type, text.c_str());
      }
    });
  }

  // ---- enums --------------------------------------------------------------------------------------------------
  py::enum_<GeomAbs_CurveType>(m, "GeomAbs_CurveType")
      .value("GeomAbs_Line", GeomAbs_Line)
      .value("GeomAbs_Circle", GeomAbs_Circle)
      .value("GeomAbs_Ellipse", GeomAbs_Ellipse)
      .value("GeomAbs_Hyperbola", GeomAbs_Hyperbola)
      .value("GeomAbs_Parabola", GeomAbs_Parabola)
      .value("GeomAbs_BezierCurve", GeomAbs_BezierCurve)
      .value("GeomAbs_BSplineCurve", GeomAbs_BSplineCurve)
      .value("GeomAbs_OffsetCurve", GeomAbs_OffsetCurve)
      .value("GeomAbs_OtherCurve", GeomAbs_OtherCurve)
      .export_values();
  py::enum_<GeomAbs_SurfaceType>(m, "GeomAbs_SurfaceType")
      .value("GeomAbs_Plane", GeomAbs_Plane)
      .value("GeomAbs_Cylinder", GeomAbs_Cylinder)
      .value("GeomAbs_Cone", GeomAbs_Cone)
      .value("GeomAbs_Sphere", GeomAbs_Sphere)
      .value("GeomAbs_Torus", GeomAbs_Torus)
      .value("GeomAbs_BezierSurface", GeomAbs_BezierSurface)
      .value("GeomAbs_BSplineSurface", GeomAbs_BSplineSurface)
      .value("GeomAbs_SurfaceOfRevolution", GeomAbs_SurfaceOfRevolution)
      .value("GeomAbs_SurfaceOfExtrusion", GeomAbs_SurfaceOfExtrusion)
      .value("GeomAbs_OffsetSurface", GeomAbs_OffsetSurface)
      .value("GeomAbs_OtherSurface", GeomAbs_OtherSurface)
      .export_values();
  py::enum_<BRepCheck_Status>(m, "BRepCheck_Status")
      .value("BRepCheck_NoError", BRepCheck_NoError)
      .value("BRepCheck_InvalidPointOnCurve", BRepCheck_InvalidPointOnCurve)
      .value("BRepCheck_InvalidPointOnCurveOnSurface", BRepCheck_InvalidPointOnCurveOnSurface)
      .value("BRepCheck_InvalidPointOnSurface", BRepCheck_InvalidPointOnSurface)
      .value("BRepCheck_No3DCurve", BRepCheck_No3DCurve)
      .value("BRepCheck_Multiple3DCurve", BRepCheck_Multiple3DCurve)
      .value("BRepCheck_Invalid3DCurve", BRepCheck_Invalid3DCurve)
      .value("BRepCheck_NoCurveOnSurface", BRepCheck_NoCurveOnSurface)
      .value("BRepCheck_InvalidCurveOnSurface", BRepCheck_InvalidCurveOnSurface)
      .value("BRepCheck_InvalidCurveOnClosedSurface", BRepCheck_InvalidCurveOnClosedSurface)
      .value("BRepCheck_InvalidSameRangeFlag", BRepCheck_InvalidSameRangeFlag)
      .value("BRepCheck_InvalidSameParameterFlag", BRepCheck_InvalidSameParameterFlag)
      .value("BRepCheck_InvalidDegeneratedFlag", BRepCheck_InvalidDegeneratedFlag)
      .value("BRepCheck_FreeEdge", BRepCheck_FreeEdge)
      .value("BRepCheck_InvalidMultiConnexity", BRepCheck_InvalidMultiConnexity)
      .value("BRepCheck_InvalidRange", BRepCheck_InvalidRange)
      .value("BRepCheck_EmptyWire", BRepCheck_EmptyWire)
      .value("BRepCheck_RedundantEdge", BRepCheck_RedundantEdge)
      .value("BRepCheck_SelfIntersectingWire", BRepCheck_SelfIntersectingWire)
      .value("BRepCheck_NoSurface", BRepCheck_NoSurface)
      .value("BRepCheck_InvalidWire", BRepCheck_InvalidWire)
      .value("BRepCheck_RedundantWire", BRepCheck_RedundantWire)
      .value("BRepCheck_IntersectingWires", BRepCheck_IntersectingWires)
      .value("BRepCheck_InvalidImbricationOfWires", BRepCheck_InvalidImbricationOfWires)
      .value("BRepCheck_EmptyShell", BRepCheck_EmptyShell)
      .value("BRepCheck_RedundantFace", BRepCheck_RedundantFace)
      .value("BRepCheck_InvalidImbricationOfShells", BRepCheck_InvalidImbricationOfShells)
      .value("BRepCheck_UnorientableShape", BRepCheck_UnorientableShape)
      .value("BRepCheck_NotClosed", BRepCheck_NotClosed)
      .value("BRepCheck_NotConnected", BRepCheck_NotConnected)
      .value("BRepCheck_SubshapeNotInShape", BRepCheck_SubshapeNotInShape)
      .value("BRepCheck_BadOrientation", BRepCheck_BadOrientation)
      .value("BRepCheck_BadOrientationOfSubshape", BRepCheck_BadOrientationOfSubshape)
      .value("BRepCheck_InvalidPolygonOnTriangulation", BRepCheck_InvalidPolygonOnTriangulation)
      .value("BRepCheck_InvalidToleranceValue", BRepCheck_InvalidToleranceValue)
      .value("BRepCheck_EnclosedRegion", BRepCheck_EnclosedRegion)
      .value("BRepCheck_CheckFail", BRepCheck_CheckFail)
      .export_values();
  py::enum_<BRepExtrema_SupportType>(m, "BRepExtrema_SupportType")
      .value("BRepExtrema_IsVertex", BRepExtrema_IsVertex)
      .value("BRepExtrema_IsOnEdge", BRepExtrema_IsOnEdge)
      .value("BRepExtrema_IsInFace", BRepExtrema_IsInFace)
      .export_values();

  // ---- gp types the core file does not carry (surface/curve carriers returned by the adaptors) ------------------
  py::class_<gp_Vec2d>(m, "gp_Vec2d")
      .def(py::init<>())
      .def(py::init<double, double>())
      .def("X", &gp_Vec2d::X)
      .def("Y", &gp_Vec2d::Y)
      .def("Coord", [](const gp_Vec2d& v) { return py::make_tuple(v.X(), v.Y()); })
      .def("Magnitude", &gp_Vec2d::Magnitude);

  py::class_<gp_Sphere>(m, "gp_Sphere")
      .def(py::init<>())
      .def(py::init<const gp_Ax3&, double>())
      .def("Radius", &gp_Sphere::Radius)
      .def("Location", [](const gp_Sphere& s) { return s.Location(); })
      .def("Position", [](const gp_Sphere& s) { return s.Position(); })
      .def("XAxis", [](const gp_Sphere& s) { return s.XAxis(); })
      .def("YAxis", [](const gp_Sphere& s) { return s.YAxis(); });

  py::class_<gp_Cone>(m, "gp_Cone")
      .def(py::init<>())
      .def(py::init<const gp_Ax3&, double, double>())
      .def("RefRadius", &gp_Cone::RefRadius)
      .def("SemiAngle", &gp_Cone::SemiAngle)
      .def("Apex", [](const gp_Cone& c) { return c.Apex(); })
      .def("Location", [](const gp_Cone& c) { return c.Location(); })
      .def("Position", [](const gp_Cone& c) { return c.Position(); })
      .def("Axis", [](const gp_Cone& c) { return c.Axis(); })
      .def("XAxis", [](const gp_Cone& c) { return c.XAxis(); })
      .def("YAxis", [](const gp_Cone& c) { return c.YAxis(); });

  py::class_<gp_Torus>(m, "gp_Torus")
      .def(py::init<>())
      .def(py::init<const gp_Ax3&, double, double>())
      .def("MajorRadius", &gp_Torus::MajorRadius)
      .def("MinorRadius", &gp_Torus::MinorRadius)
      .def("Location", [](const gp_Torus& t) { return t.Location(); })
      .def("Position", [](const gp_Torus& t) { return t.Position(); })
      .def("Axis", [](const gp_Torus& t) { return t.Axis(); })
      .def("XAxis", [](const gp_Torus& t) { return t.XAxis(); })
      .def("YAxis", [](const gp_Torus& t) { return t.YAxis(); });

  py::class_<gp_Hypr>(m, "gp_Hypr")
      .def(py::init<>())
      .def(py::init<const gp_Ax2&, double, double>())
      .def("MajorRadius", &gp_Hypr::MajorRadius)
      .def("MinorRadius", &gp_Hypr::MinorRadius)
      .def("Location", [](const gp_Hypr& h) { return h.Location(); })
      .def("Position", [](const gp_Hypr& h) { return h.Position(); })
      .def("Axis", [](const gp_Hypr& h) { return h.Axis(); })
      .def("XAxis", [](const gp_Hypr& h) { return h.XAxis(); })
      .def("YAxis", [](const gp_Hypr& h) { return h.YAxis(); });

  py::class_<gp_Parab>(m, "gp_Parab")
      .def(py::init<>())
      .def(py::init<const gp_Ax2&, double>())
      .def("Focal", &gp_Parab::Focal)
      .def("Location", [](const gp_Parab& p) { return p.Location(); })
      .def("Position", [](const gp_Parab& p) { return p.Position(); })
      .def("Axis", [](const gp_Parab& p) { return p.Axis(); })
      .def("XAxis", [](const gp_Parab& p) { return p.XAxis(); })
      .def("YAxis", [](const gp_Parab& p) { return p.YAxis(); });

  // Members of the core file's gp_Pln / gp_Cylinder that the inspection layers call and the core file lacks.
  py::reinterpret_borrow<py::class_<gp_Pln>>(m.attr("gp_Pln"))
      .def("XAxis", [](const gp_Pln& p) { return p.XAxis(); })
      .def("YAxis", [](const gp_Pln& p) { return p.YAxis(); });
  py::reinterpret_borrow<py::class_<gp_Cylinder>>(m.attr("gp_Cylinder"))
      .def("XAxis", [](const gp_Cylinder& c) { return c.XAxis(); })
      .def("YAxis", [](const gp_Cylinder& c) { return c.YAxis(); });

  // ---- arrays -------------------------------------------------------------------------------------------------
  bind_array1<TColgp_Array1OfPnt, gp_Pnt>(m, "TColgp_Array1OfPnt");
  bind_array1<TColStd_Array1OfReal, double>(m, "TColStd_Array1OfReal");
  bind_array1<TColStd_Array1OfInteger, int>(m, "TColStd_Array1OfInteger");
  bind_array2<TColgp_Array2OfPnt, gp_Pnt>(m, "TColgp_Array2OfPnt");
  bind_array2<TColStd_Array2OfReal, double>(m, "TColStd_Array2OfReal");

  // HArray1 is a Standard_Transient that is also an Array1: bound on its own, with the same members.
  py::class_<TColgp_HArray1OfPnt, H<TColgp_HArray1OfPnt>>(m, "TColgp_HArray1OfPnt")
      .def(py::init([](int lo, int hi) {
             if (hi < lo - 1)
               out_of_range("upper bound below lower bound");
             return new TColgp_HArray1OfPnt(lo, hi);
           }),
           py::arg("theLower"), py::arg("theUpper"))
      .def(py::init([](int lo, int hi, const gp_Pnt& v) { return new TColgp_HArray1OfPnt(lo, hi, v); }),
           py::arg("theLower"), py::arg("theUpper"), py::arg("theValue"))
      .def(py::init([](const TColgp_Array1OfPnt& other) { return new TColgp_HArray1OfPnt(other); }),
           py::arg("theOther"))
      .def("Array1", [](const TColgp_HArray1OfPnt& a) { return TColgp_Array1OfPnt(a.Array1()); })
      .def(
          "Init", [](TColgp_HArray1OfPnt& a, const gp_Pnt& v) { a.Init(v); }, py::arg("theValue"))
      .def("Size", [](const TColgp_HArray1OfPnt& a) { return a.Size(); })
      .def("Length", [](const TColgp_HArray1OfPnt& a) { return a.Length(); })
      .def("IsEmpty", [](const TColgp_HArray1OfPnt& a) { return a.IsEmpty(); })
      .def("Lower", [](const TColgp_HArray1OfPnt& a) { return a.Lower(); })
      .def("Upper", [](const TColgp_HArray1OfPnt& a) { return a.Upper(); })
      .def("First",
           [](const TColgp_HArray1OfPnt& a) {
             if (a.IsEmpty())
               out_of_range("empty array");
             return a.First();
           })
      .def("Last",
           [](const TColgp_HArray1OfPnt& a) {
             if (a.IsEmpty())
               out_of_range("empty array");
             return a.Last();
           })
      .def(
          "Value",
          [](const TColgp_HArray1OfPnt& a, int i) {
            check_index(i, a.Lower(), a.Upper());
            return a.Value(i);
          },
          py::arg("theIndex"))
      .def(
          "SetValue",
          [](TColgp_HArray1OfPnt& a, int i, const gp_Pnt& v) {
            check_index(i, a.Lower(), a.Upper());
            a.SetValue(i, v);
          },
          py::arg("theIndex"), py::arg("theItem"))
      .def("__len__", [](const TColgp_HArray1OfPnt& a) { return a.Length(); })
      .def("__iter__", [](const TColgp_HArray1OfPnt& a) {
        py::list items;
        for (int i = a.Lower(); i <= a.Upper(); ++i)
          items.append(py::cast(a.Value(i)));
        return py::iter(items);
      });

  // ---- Geom_Geometry / Geom_Curve family -------------------------------------------------------------------------
  py::class_<Geom_Geometry, H<Geom_Geometry>>(m, "Geom_Geometry")
      .def("Copy", [](const Geom_Geometry& g) { return g.Copy(); })
      .def(
          "Transform", [](Geom_Geometry& g, const gp_Trsf& t) { g.Transform(t); }, py::arg("T"))
      .def(
          "Transformed", [](const Geom_Geometry& g, const gp_Trsf& t) { return g.Transformed(t); }, py::arg("T"))
      .def(
          "Translate", [](Geom_Geometry& g, const gp_Vec& v) { g.Translate(v); }, py::arg("V"))
      .def("Translated", [](const Geom_Geometry& g, const gp_Vec& v) { return g.Translated(v); }, py::arg("V"));

  py::class_<Geom_Curve, H<Geom_Curve>, Geom_Geometry> curve(m, "Geom_Curve");
  curve.def("Reverse", [](Geom_Curve& c) { c.Reverse(); })
      .def(
          "ReversedParameter", [](const Geom_Curve& c, double u) { return c.ReversedParameter(u); }, py::arg("U"))
      .def(
          "TransformedParameter",
          [](const Geom_Curve& c, double u, const gp_Trsf& t) { return c.TransformedParameter(u, t); }, py::arg("U"),
          py::arg("T"))
      .def(
          "ParametricTransformation",
          [](const Geom_Curve& c, const gp_Trsf& t) { return c.ParametricTransformation(t); }, py::arg("T"))
      .def("Reversed", [](const Geom_Curve& c) { return c.Reversed(); })
      .def("FirstParameter", [](const Geom_Curve& c) { return c.FirstParameter(); })
      .def("LastParameter", [](const Geom_Curve& c) { return c.LastParameter(); })
      .def("IsClosed", [](const Geom_Curve& c) { return c.IsClosed(); })
      .def("IsPeriodic", [](const Geom_Curve& c) { return c.IsPeriodic(); })
      .def("Period", [](const Geom_Curve& c) { return c.Period(); })
      .def("Continuity", [](const Geom_Curve& c) { return c.Continuity(); })
      .def("IsCN", [](const Geom_Curve& c, int n) { return c.IsCN(n); }, py::arg("N"));
  curve_evaluators(curve);

  py::class_<Geom_BoundedCurve, H<Geom_BoundedCurve>, Geom_Curve>(m, "Geom_BoundedCurve")
      .def("StartPoint", [](const Geom_BoundedCurve& c) { return c.StartPoint(); })
      .def("EndPoint", [](const Geom_BoundedCurve& c) { return c.EndPoint(); });

  py::class_<Geom_BSplineCurve, H<Geom_BSplineCurve>, Geom_BoundedCurve>(m, "Geom_BSplineCurve")
      .def(py::init([](const TColgp_Array1OfPnt& poles, const TColStd_Array1OfReal& knots,
                       const TColStd_Array1OfInteger& mults, int degree,
                       bool periodic) { return new Geom_BSplineCurve(poles, knots, mults, degree, periodic); }),
           py::arg("Poles"), py::arg("Knots"), py::arg("Multiplicities"), py::arg("Degree"),
           py::arg("Periodic") = false)
      .def(py::init(
               [](const TColgp_Array1OfPnt& poles, const TColStd_Array1OfReal& weights,
                  const TColStd_Array1OfReal& knots, const TColStd_Array1OfInteger& mults, int degree, bool periodic,
                  bool check) { return new Geom_BSplineCurve(poles, weights, knots, mults, degree, periodic, check); }),
           py::arg("Poles"), py::arg("Weights"), py::arg("Knots"), py::arg("Multiplicities"), py::arg("Degree"),
           py::arg("Periodic") = false, py::arg("CheckRational") = true)
      .def(
          "IncreaseDegree", [](Geom_BSplineCurve& c, int d) { c.IncreaseDegree(d); }, py::arg("Degree"))
      .def(
          "IncreaseMultiplicity", [](Geom_BSplineCurve& c, int i, int mult) { c.IncreaseMultiplicity(i, mult); },
          py::arg("Index"), py::arg("M"))
      .def(
          "IncreaseMultiplicity",
          [](Geom_BSplineCurve& c, int i1, int i2, int mult) { c.IncreaseMultiplicity(i1, i2, mult); }, py::arg("I1"),
          py::arg("I2"), py::arg("M"))
      .def(
          "IncrementMultiplicity",
          [](Geom_BSplineCurve& c, int i1, int i2, int mult) { c.IncrementMultiplicity(i1, i2, mult); }, py::arg("I1"),
          py::arg("I2"), py::arg("M"))
      .def(
          "InsertKnot",
          [](Geom_BSplineCurve& c, double u, int mult, double tol, bool add) { c.InsertKnot(u, mult, tol, add); },
          py::arg("U"), py::arg("M") = 1, py::arg("ParametricTolerance") = 0.0, py::arg("Add") = true)
      .def(
          "RemoveKnot",
          [](Geom_BSplineCurve& c, int index, int mult, double tol) { return c.RemoveKnot(index, mult, tol); },
          py::arg("Index"), py::arg("M"), py::arg("Tolerance"))
      .def(
          "Segment", [](Geom_BSplineCurve& c, double u1, double u2, double tol) { c.Segment(u1, u2, tol); },
          py::arg("U1"), py::arg("U2"), py::arg("theTolerance") = 1e-9)
      .def(
          "SetKnot", [](Geom_BSplineCurve& c, int i, double k) { c.SetKnot(i, k); }, py::arg("Index"), py::arg("K"))
      .def(
          "SetKnot", [](Geom_BSplineCurve& c, int i, double k, int mult) { c.SetKnot(i, k, mult); }, py::arg("Index"),
          py::arg("K"), py::arg("M"))
      .def(
          "SetKnots", [](Geom_BSplineCurve& c, const TColStd_Array1OfReal& k) { c.SetKnots(k); }, py::arg("K"))
      .def("SetPeriodic", [](Geom_BSplineCurve& c) { c.SetPeriodic(); })
      .def("SetNotPeriodic", [](Geom_BSplineCurve& c) { c.SetNotPeriodic(); })
      .def(
          "SetOrigin", [](Geom_BSplineCurve& c, int i) { c.SetOrigin(i); }, py::arg("Index"))
      .def(
          "SetOrigin", [](Geom_BSplineCurve& c, double u, double tol) { c.SetOrigin(u, tol); }, py::arg("U"),
          py::arg("Tol"))
      .def(
          "SetPole", [](Geom_BSplineCurve& c, int i, const gp_Pnt& p) { c.SetPole(i, p); }, py::arg("Index"),
          py::arg("P"))
      .def(
          "SetPole", [](Geom_BSplineCurve& c, int i, const gp_Pnt& p, double w) { c.SetPole(i, p, w); },
          py::arg("Index"), py::arg("P"), py::arg("Weight"))
      .def(
          "SetWeight", [](Geom_BSplineCurve& c, int i, double w) { c.SetWeight(i, w); }, py::arg("Index"),
          py::arg("Weight"))
      .def(
          "IsG1", [](const Geom_BSplineCurve& c, double u1, double u2, double ang) { return c.IsG1(u1, u2, ang); },
          py::arg("theTf"), py::arg("theTl"), py::arg("theAngTol"))
      .def("IsRational", [](const Geom_BSplineCurve& c) { return c.IsRational(); })
      .def("Degree", [](const Geom_BSplineCurve& c) { return c.Degree(); })
      .def("FirstUKnotIndex", [](const Geom_BSplineCurve& c) { return c.FirstUKnotIndex(); })
      .def("LastUKnotIndex", [](const Geom_BSplineCurve& c) { return c.LastUKnotIndex(); })
      .def(
          "Knot",
          [](const Geom_BSplineCurve& c, int i) {
            check_index(i, 1, c.NbKnots());
            return c.Knot(i);
          },
          py::arg("Index"))
      .def(
          "Knots", [](const Geom_BSplineCurve& c, TColStd_Array1OfReal& k) { c.Knots(k); }, py::arg("K"))
      .def("Knots", [](const Geom_BSplineCurve& c) { return copy_of(c.Knots()); })
      .def("KnotSequence", [](const Geom_BSplineCurve& c) { return copy_of(c.KnotSequence()); })
      .def(
          "Multiplicity",
          [](const Geom_BSplineCurve& c, int i) {
            check_index(i, 1, c.NbKnots());
            return c.Multiplicity(i);
          },
          py::arg("Index"))
      .def(
          "Multiplicities", [](const Geom_BSplineCurve& c, TColStd_Array1OfInteger& mm) { c.Multiplicities(mm); },
          py::arg("M"))
      .def("Multiplicities", [](const Geom_BSplineCurve& c) { return copy_of(c.Multiplicities()); })
      .def("NbKnots", [](const Geom_BSplineCurve& c) { return c.NbKnots(); })
      .def("NbPoles", [](const Geom_BSplineCurve& c) { return c.NbPoles(); })
      .def(
          "Pole",
          [](const Geom_BSplineCurve& c, int i) {
            check_index(i, 1, c.NbPoles());
            return c.Pole(i);
          },
          py::arg("Index"))
      .def(
          "Poles", [](const Geom_BSplineCurve& c, TColgp_Array1OfPnt& p) { c.Poles(p); }, py::arg("P"))
      .def("Poles", [](const Geom_BSplineCurve& c) { return copy_of(c.Poles()); })
      .def(
          "Weight",
          [](const Geom_BSplineCurve& c, int i) {
            check_index(i, 1, c.NbPoles());
            return c.Weight(i);
          },
          py::arg("Index"))
      .def(
          "Weights", [](const Geom_BSplineCurve& c, TColStd_Array1OfReal& w) { c.Weights(w); }, py::arg("W"))
      .def("Weights",
           [](const Geom_BSplineCurve& c) -> py::object {
             const TColStd_Array1OfReal* w = c.Weights();  // null for a non-rational curve: OCP hands back None
             return w == nullptr ? py::none() : py::cast(TColStd_Array1OfReal(*w));
           })
      .def_static("MaxDegree_s", []() { return Geom_BSplineCurve::MaxDegree(); });

  py::class_<Geom_BezierCurve, H<Geom_BezierCurve>, Geom_BoundedCurve>(m, "Geom_BezierCurve")
      .def(py::init([](const TColgp_Array1OfPnt& poles) { return new Geom_BezierCurve(poles); }), py::arg("CurvePoles"))
      .def(py::init([](const TColgp_Array1OfPnt& poles, const TColStd_Array1OfReal& w) {
             return new Geom_BezierCurve(poles, w);
           }),
           py::arg("CurvePoles"), py::arg("PoleWeights"))
      .def(
          "Increase", [](Geom_BezierCurve& c, int d) { c.Increase(d); }, py::arg("Degree"))
      .def(
          "InsertPoleAfter", [](Geom_BezierCurve& c, int i, const gp_Pnt& p) { c.InsertPoleAfter(i, p); },
          py::arg("Index"), py::arg("P"))
      .def(
          "InsertPoleAfter", [](Geom_BezierCurve& c, int i, const gp_Pnt& p, double w) { c.InsertPoleAfter(i, p, w); },
          py::arg("Index"), py::arg("P"), py::arg("Weight"))
      .def(
          "InsertPoleBefore", [](Geom_BezierCurve& c, int i, const gp_Pnt& p) { c.InsertPoleBefore(i, p); },
          py::arg("Index"), py::arg("P"))
      .def(
          "InsertPoleBefore",
          [](Geom_BezierCurve& c, int i, const gp_Pnt& p, double w) { c.InsertPoleBefore(i, p, w); }, py::arg("Index"),
          py::arg("P"), py::arg("Weight"))
      .def(
          "RemovePole", [](Geom_BezierCurve& c, int i) { c.RemovePole(i); }, py::arg("Index"))
      .def(
          "Segment", [](Geom_BezierCurve& c, double u1, double u2) { c.Segment(u1, u2); }, py::arg("U1"), py::arg("U2"))
      .def(
          "SetPole", [](Geom_BezierCurve& c, int i, const gp_Pnt& p) { c.SetPole(i, p); }, py::arg("Index"),
          py::arg("P"))
      .def(
          "SetPole", [](Geom_BezierCurve& c, int i, const gp_Pnt& p, double w) { c.SetPole(i, p, w); },
          py::arg("Index"), py::arg("P"), py::arg("Weight"))
      .def(
          "SetWeight", [](Geom_BezierCurve& c, int i, double w) { c.SetWeight(i, w); }, py::arg("Index"),
          py::arg("Weight"))
      .def("IsRational", [](const Geom_BezierCurve& c) { return c.IsRational(); })
      .def("Degree", [](const Geom_BezierCurve& c) { return c.Degree(); })
      .def("NbPoles", [](const Geom_BezierCurve& c) { return c.NbPoles(); })
      .def(
          "Pole",
          [](const Geom_BezierCurve& c, int i) {
            check_index(i, 1, c.NbPoles());
            return c.Pole(i);
          },
          py::arg("Index"))
      .def(
          "Poles", [](const Geom_BezierCurve& c, TColgp_Array1OfPnt& p) { c.Poles(p); }, py::arg("P"))
      .def("Poles", [](const Geom_BezierCurve& c) { return copy_of(c.Poles()); })
      .def(
          "Weight",
          [](const Geom_BezierCurve& c, int i) {
            check_index(i, 1, c.NbPoles());
            return c.Weight(i);
          },
          py::arg("Index"))
      .def(
          "Weights", [](const Geom_BezierCurve& c, TColStd_Array1OfReal& w) { c.Weights(w); }, py::arg("W"))
      .def("Weights",
           [](const Geom_BezierCurve& c) -> py::object {
             const TColStd_Array1OfReal* w = c.Weights();  // null for a non-rational curve: OCP hands back None
             return w == nullptr ? py::none() : py::cast(TColStd_Array1OfReal(*w));
           })
      .def_static("MaxDegree_s", []() { return Geom_BezierCurve::MaxDegree(); });

  py::class_<Geom_TrimmedCurve, H<Geom_TrimmedCurve>, Geom_BoundedCurve>(m, "Geom_TrimmedCurve")
      .def(py::init([](const H<Geom_Curve>& c, double u1, double u2, bool sense, bool adjust) {
             return new Geom_TrimmedCurve(c, u1, u2, sense, adjust);
           }),
           py::arg("C").none(false), py::arg("U1"), py::arg("U2"), py::arg("Sense") = true,
           py::arg("theAdjustPeriodic") = true)
      .def(
          "SetTrim",
          [](Geom_TrimmedCurve& c, double u1, double u2, bool sense, bool adjust) { c.SetTrim(u1, u2, sense, adjust); },
          py::arg("U1"), py::arg("U2"), py::arg("Sense") = true, py::arg("theAdjustPeriodic") = true)
      .def("BasisCurve", [](const Geom_TrimmedCurve& c) { return c.BasisCurve(); });

  py::class_<Geom_Conic, H<Geom_Conic>, Geom_Curve>(m, "Geom_Conic")
      .def(
          "SetAxis", [](Geom_Conic& c, const gp_Ax1& a) { c.SetAxis(a); }, py::arg("theA1"))
      .def(
          "SetLocation", [](Geom_Conic& c, const gp_Pnt& p) { c.SetLocation(p); }, py::arg("theP"))
      .def(
          "SetPosition", [](Geom_Conic& c, const gp_Ax2& a) { c.SetPosition(a); }, py::arg("theA2"))
      .def("Axis", [](const Geom_Conic& c) { return c.Axis(); })
      .def("Location", [](const Geom_Conic& c) { return c.Location(); })
      .def("Position", [](const Geom_Conic& c) { return c.Position(); })
      .def("XAxis", [](const Geom_Conic& c) { return c.XAxis(); })
      .def("YAxis", [](const Geom_Conic& c) { return c.YAxis(); })
      .def("Eccentricity", [](const Geom_Conic& c) { return c.Eccentricity(); });

  py::class_<Geom_Circle, H<Geom_Circle>, Geom_Conic>(m, "Geom_Circle")
      .def(py::init([](const gp_Circ& c) { return new Geom_Circle(c); }), py::arg("C"))
      .def(py::init([](const gp_Ax2& a, double r) { return new Geom_Circle(a, r); }), py::arg("A2"), py::arg("Radius"))
      .def(
          "SetCirc", [](Geom_Circle& c, const gp_Circ& v) { c.SetCirc(v); }, py::arg("C"))
      .def(
          "SetRadius", [](Geom_Circle& c, double r) { c.SetRadius(r); }, py::arg("R"))
      .def("Circ", [](const Geom_Circle& c) { return c.Circ(); })
      .def("Radius", [](const Geom_Circle& c) { return c.Radius(); });

  py::class_<Geom_Ellipse, H<Geom_Ellipse>, Geom_Conic>(m, "Geom_Ellipse")
      .def(py::init([](const gp_Elips& e) { return new Geom_Ellipse(e); }), py::arg("E"))
      .def(py::init([](const gp_Ax2& a, double major, double minor) { return new Geom_Ellipse(a, major, minor); }),
           py::arg("A2"), py::arg("MajorRadius"), py::arg("MinorRadius"))
      .def(
          "SetElips", [](Geom_Ellipse& e, const gp_Elips& v) { e.SetElips(v); }, py::arg("E"))
      .def(
          "SetMajorRadius", [](Geom_Ellipse& e, double r) { e.SetMajorRadius(r); }, py::arg("MajorRadius"))
      .def(
          "SetMinorRadius", [](Geom_Ellipse& e, double r) { e.SetMinorRadius(r); }, py::arg("MinorRadius"))
      .def("Elips", [](const Geom_Ellipse& e) { return e.Elips(); })
      .def("MajorRadius", [](const Geom_Ellipse& e) { return e.MajorRadius(); })
      .def("MinorRadius", [](const Geom_Ellipse& e) { return e.MinorRadius(); })
      .def("Focal", [](const Geom_Ellipse& e) { return e.Focal(); })
      .def("Focus1", [](const Geom_Ellipse& e) { return e.Focus1(); })
      .def("Focus2", [](const Geom_Ellipse& e) { return e.Focus2(); })
      .def("Directrix1", [](const Geom_Ellipse& e) { return e.Directrix1(); })
      .def("Directrix2", [](const Geom_Ellipse& e) { return e.Directrix2(); });

  py::class_<Geom_Line, H<Geom_Line>, Geom_Curve>(m, "Geom_Line")
      .def(py::init([](const gp_Ax1& a) { return new Geom_Line(a); }), py::arg("A1"))
      .def(py::init([](const gp_Lin& l) { return new Geom_Line(l); }), py::arg("L"))
      .def(py::init([](const gp_Pnt& p, const gp_Dir& d) { return new Geom_Line(p, d); }), py::arg("P"), py::arg("V"))
      .def(
          "SetLin", [](Geom_Line& l, const gp_Lin& v) { l.SetLin(v); }, py::arg("L"))
      .def(
          "SetDirection", [](Geom_Line& l, const gp_Dir& d) { l.SetDirection(d); }, py::arg("V"))
      .def(
          "SetLocation", [](Geom_Line& l, const gp_Pnt& p) { l.SetLocation(p); }, py::arg("P"))
      .def(
          "SetPosition", [](Geom_Line& l, const gp_Ax1& a) { l.SetPosition(a); }, py::arg("A1"))
      .def("Lin", [](const Geom_Line& l) { return l.Lin(); })
      .def("Position", [](const Geom_Line& l) { return l.Position(); });

  // ---- Geom_Surface family ------------------------------------------------------------------------------------
  py::class_<Geom_Surface, H<Geom_Surface>, Geom_Geometry>(m, "Geom_Surface")
      .def("UReverse", [](Geom_Surface& s) { s.UReverse(); })
      .def("UReversed", [](const Geom_Surface& s) { return s.UReversed(); })
      .def(
          "UReversedParameter", [](const Geom_Surface& s, double u) { return s.UReversedParameter(u); }, py::arg("U"))
      .def("VReverse", [](Geom_Surface& s) { s.VReverse(); })
      .def("VReversed", [](const Geom_Surface& s) { return s.VReversed(); })
      .def(
          "VReversedParameter", [](const Geom_Surface& s, double v) { return s.VReversedParameter(v); }, py::arg("V"))
      .def("IsUClosed", [](const Geom_Surface& s) { return s.IsUClosed(); })
      .def("IsVClosed", [](const Geom_Surface& s) { return s.IsVClosed(); })
      .def("IsUPeriodic", [](const Geom_Surface& s) { return s.IsUPeriodic(); })
      .def("UPeriod", [](const Geom_Surface& s) { return s.UPeriod(); })
      .def("IsVPeriodic", [](const Geom_Surface& s) { return s.IsVPeriodic(); })
      .def("VPeriod", [](const Geom_Surface& s) { return s.VPeriod(); })
      .def(
          "UIso", [](const Geom_Surface& s, double u) { return s.UIso(u); }, py::arg("U"))
      .def(
          "VIso", [](const Geom_Surface& s, double v) { return s.VIso(v); }, py::arg("V"))
      .def("Continuity", [](const Geom_Surface& s) { return s.Continuity(); })
      .def(
          "IsCNu", [](const Geom_Surface& s, int n) { return s.IsCNu(n); }, py::arg("N"))
      .def(
          "IsCNv", [](const Geom_Surface& s, int n) { return s.IsCNv(n); }, py::arg("N"))
      .def(
          "D0", [](const Geom_Surface& s, double u, double v, gp_Pnt& p) { s.D0(u, v, p); }, py::arg("U"), py::arg("V"),
          py::arg("P"))
      .def(
          "D1",
          [](const Geom_Surface& s, double u, double v, gp_Pnt& p, gp_Vec& d1u, gp_Vec& d1v) {
            s.D1(u, v, p, d1u, d1v);
          },
          py::arg("U"), py::arg("V"), py::arg("P"), py::arg("D1U"), py::arg("D1V"))
      .def(
          "D2",
          [](const Geom_Surface& s, double u, double v, gp_Pnt& p, gp_Vec& d1u, gp_Vec& d1v, gp_Vec& d2u, gp_Vec& d2v,
             gp_Vec& d2uv) { s.D2(u, v, p, d1u, d1v, d2u, d2v, d2uv); },
          py::arg("U"), py::arg("V"), py::arg("P"), py::arg("D1U"), py::arg("D1V"), py::arg("D2U"), py::arg("D2V"),
          py::arg("D2UV"))
      .def(
          "D3",
          [](const Geom_Surface& s, double u, double v, gp_Pnt& p, gp_Vec& d1u, gp_Vec& d1v, gp_Vec& d2u, gp_Vec& d2v,
             gp_Vec& d2uv, gp_Vec& d3u, gp_Vec& d3v, gp_Vec& d3uuv,
             gp_Vec& d3uvv) { s.D3(u, v, p, d1u, d1v, d2u, d2v, d2uv, d3u, d3v, d3uuv, d3uvv); },
          py::arg("U"), py::arg("V"), py::arg("P"), py::arg("D1U"), py::arg("D1V"), py::arg("D2U"), py::arg("D2V"),
          py::arg("D2UV"), py::arg("D3U"), py::arg("D3V"), py::arg("D3UUV"), py::arg("D3UVV"))
      .def(
          "DN", [](const Geom_Surface& s, double u, double v, int nu, int nv) { return s.DN(u, v, nu, nv); },
          py::arg("U"), py::arg("V"), py::arg("Nu"), py::arg("Nv"))
      .def(
          "Value", [](const Geom_Surface& s, double u, double v) { return s.Value(u, v); }, py::arg("U"), py::arg("V"))
      .def(
          "TransformParameters",
          [](const Geom_Surface& s, const gp_Trsf& t) {
            double u = 0.0, v = 0.0;
            s.TransformParameters(u, v, t);
            return py::make_tuple(u, v);
          },
          py::arg("T"))
      .def("Bounds", [](const Geom_Surface& s) {
        double u1 = 0.0, u2 = 0.0, v1 = 0.0, v2 = 0.0;
        s.Bounds(u1, u2, v1, v2);
        return py::make_tuple(u1, u2, v1, v2);
      });

  py::class_<Geom_BoundedSurface, H<Geom_BoundedSurface>, Geom_Surface>(m, "Geom_BoundedSurface");

  py::class_<Geom_BSplineSurface, H<Geom_BSplineSurface>, Geom_BoundedSurface>(m, "Geom_BSplineSurface")
      .def(py::init([](const TColgp_Array2OfPnt& poles, const TColStd_Array1OfReal& uk, const TColStd_Array1OfReal& vk,
                       const TColStd_Array1OfInteger& um, const TColStd_Array1OfInteger& vm, int ud, int vd, bool up,
                       bool vp) { return new Geom_BSplineSurface(poles, uk, vk, um, vm, ud, vd, up, vp); }),
           py::arg("Poles"), py::arg("UKnots"), py::arg("VKnots"), py::arg("UMults"), py::arg("VMults"),
           py::arg("UDegree"), py::arg("VDegree"), py::arg("UPeriodic") = false, py::arg("VPeriodic") = false)
      .def(py::init([](const TColgp_Array2OfPnt& poles, const TColStd_Array2OfReal& w, const TColStd_Array1OfReal& uk,
                       const TColStd_Array1OfReal& vk, const TColStd_Array1OfInteger& um,
                       const TColStd_Array1OfInteger& vm, int ud, int vd, bool up,
                       bool vp) { return new Geom_BSplineSurface(poles, w, uk, vk, um, vm, ud, vd, up, vp); }),
           py::arg("Poles"), py::arg("Weights"), py::arg("UKnots"), py::arg("VKnots"), py::arg("UMults"),
           py::arg("VMults"), py::arg("UDegree"), py::arg("VDegree"), py::arg("UPeriodic") = false,
           py::arg("VPeriodic") = false)
      .def("ExchangeUV", [](Geom_BSplineSurface& s) { s.ExchangeUV(); })
      .def(
          "IncreaseDegree", [](Geom_BSplineSurface& s, int ud, int vd) { s.IncreaseDegree(ud, vd); },
          py::arg("UDegree"), py::arg("VDegree"))
      .def(
          "Segment",
          [](Geom_BSplineSurface& s, double u1, double u2, double v1, double v2, double eu, double ev) {
            s.Segment(u1, u2, v1, v2, eu, ev);
          },
          py::arg("U1"), py::arg("U2"), py::arg("V1"), py::arg("V2"), py::arg("theUTolerance") = 0.0,
          py::arg("theVTolerance") = 0.0)
      .def(
          "SetPole", [](Geom_BSplineSurface& s, int u, int v, const gp_Pnt& p) { s.SetPole(u, v, p); },
          py::arg("UIndex"), py::arg("VIndex"), py::arg("P"))
      .def(
          "SetPole", [](Geom_BSplineSurface& s, int u, int v, const gp_Pnt& p, double w) { s.SetPole(u, v, p, w); },
          py::arg("UIndex"), py::arg("VIndex"), py::arg("P"), py::arg("Weight"))
      .def(
          "SetWeight", [](Geom_BSplineSurface& s, int u, int v, double w) { s.SetWeight(u, v, w); }, py::arg("UIndex"),
          py::arg("VIndex"), py::arg("Weight"))
      .def("IsURational", [](const Geom_BSplineSurface& s) { return s.IsURational(); })
      .def("IsVRational", [](const Geom_BSplineSurface& s) { return s.IsVRational(); })
      .def("UDegree", [](const Geom_BSplineSurface& s) { return s.UDegree(); })
      .def("VDegree", [](const Geom_BSplineSurface& s) { return s.VDegree(); })
      .def("NbUPoles", [](const Geom_BSplineSurface& s) { return s.NbUPoles(); })
      .def("NbVPoles", [](const Geom_BSplineSurface& s) { return s.NbVPoles(); })
      .def("NbUKnots", [](const Geom_BSplineSurface& s) { return s.NbUKnots(); })
      .def("NbVKnots", [](const Geom_BSplineSurface& s) { return s.NbVKnots(); })
      .def("FirstUKnotIndex", [](const Geom_BSplineSurface& s) { return s.FirstUKnotIndex(); })
      .def("LastUKnotIndex", [](const Geom_BSplineSurface& s) { return s.LastUKnotIndex(); })
      .def("FirstVKnotIndex", [](const Geom_BSplineSurface& s) { return s.FirstVKnotIndex(); })
      .def("LastVKnotIndex", [](const Geom_BSplineSurface& s) { return s.LastVKnotIndex(); })
      .def(
          "UKnot",
          [](const Geom_BSplineSurface& s, int i) {
            check_index(i, 1, s.NbUKnots());
            return s.UKnot(i);
          },
          py::arg("UIndex"))
      .def(
          "VKnot",
          [](const Geom_BSplineSurface& s, int i) {
            check_index(i, 1, s.NbVKnots());
            return s.VKnot(i);
          },
          py::arg("VIndex"))
      .def("UKnots", [](const Geom_BSplineSurface& s) { return copy_of(s.UKnots()); })
      .def("VKnots", [](const Geom_BSplineSurface& s) { return copy_of(s.VKnots()); })
      .def(
          "UMultiplicity",
          [](const Geom_BSplineSurface& s, int i) {
            check_index(i, 1, s.NbUKnots());
            return s.UMultiplicity(i);
          },
          py::arg("UIndex"))
      .def(
          "VMultiplicity",
          [](const Geom_BSplineSurface& s, int i) {
            check_index(i, 1, s.NbVKnots());
            return s.VMultiplicity(i);
          },
          py::arg("VIndex"))
      .def("UMultiplicities", [](const Geom_BSplineSurface& s) { return copy_of(s.UMultiplicities()); })
      .def("VMultiplicities", [](const Geom_BSplineSurface& s) { return copy_of(s.VMultiplicities()); })
      .def(
          "Pole",
          [](const Geom_BSplineSurface& s, int u, int v) {
            check_index(u, 1, s.NbUPoles(), "UIndex out of range");
            check_index(v, 1, s.NbVPoles(), "VIndex out of range");
            return s.Pole(u, v);
          },
          py::arg("UIndex"), py::arg("VIndex"))
      .def(
          "Poles", [](const Geom_BSplineSurface& s, TColgp_Array2OfPnt& p) { s.Poles(p); }, py::arg("P"))
      .def("Poles", [](const Geom_BSplineSurface& s) { return copy_of(s.Poles()); })
      .def(
          "Weight",
          [](const Geom_BSplineSurface& s, int u, int v) {
            check_index(u, 1, s.NbUPoles(), "UIndex out of range");
            check_index(v, 1, s.NbVPoles(), "VIndex out of range");
            return s.Weight(u, v);
          },
          py::arg("UIndex"), py::arg("VIndex"))
      .def(
          "Weights", [](const Geom_BSplineSurface& s, TColStd_Array2OfReal& w) { s.Weights(w); }, py::arg("W"))
      .def("Weights",
           [](const Geom_BSplineSurface& s) -> py::object {
             const TColStd_Array2OfReal* w = s.Weights();  // null for a non-rational surface: OCP hands back None
             return w == nullptr ? py::none() : py::cast(TColStd_Array2OfReal(*w));
           })
      .def_static("MaxDegree_s", []() { return Geom_BSplineSurface::MaxDegree(); });

  py::class_<Geom_BezierSurface, H<Geom_BezierSurface>, Geom_BoundedSurface>(m, "Geom_BezierSurface")
      .def(py::init([](const TColgp_Array2OfPnt& poles) { return new Geom_BezierSurface(poles); }),
           py::arg("SurfacePoles"))
      .def(py::init([](const TColgp_Array2OfPnt& poles, const TColStd_Array2OfReal& w) {
             return new Geom_BezierSurface(poles, w);
           }),
           py::arg("SurfacePoles"), py::arg("PoleWeights"))
      .def("ExchangeUV", [](Geom_BezierSurface& s) { s.ExchangeUV(); })
      .def(
          "Increase", [](Geom_BezierSurface& s, int ud, int vd) { s.Increase(ud, vd); }, py::arg("UDeg"),
          py::arg("VDeg"))
      .def(
          "Segment",
          [](Geom_BezierSurface& s, double u1, double u2, double v1, double v2) { s.Segment(u1, u2, v1, v2); },
          py::arg("U1"), py::arg("U2"), py::arg("V1"), py::arg("V2"))
      .def(
          "SetPole", [](Geom_BezierSurface& s, int u, int v, const gp_Pnt& p) { s.SetPole(u, v, p); },
          py::arg("UIndex"), py::arg("VIndex"), py::arg("P"))
      .def(
          "SetPole", [](Geom_BezierSurface& s, int u, int v, const gp_Pnt& p, double w) { s.SetPole(u, v, p, w); },
          py::arg("UIndex"), py::arg("VIndex"), py::arg("P"), py::arg("Weight"))
      .def(
          "SetWeight", [](Geom_BezierSurface& s, int u, int v, double w) { s.SetWeight(u, v, w); }, py::arg("UIndex"),
          py::arg("VIndex"), py::arg("Weight"))
      .def("IsURational", [](const Geom_BezierSurface& s) { return s.IsURational(); })
      .def("IsVRational", [](const Geom_BezierSurface& s) { return s.IsVRational(); })
      .def("UDegree", [](const Geom_BezierSurface& s) { return s.UDegree(); })
      .def("VDegree", [](const Geom_BezierSurface& s) { return s.VDegree(); })
      .def("NbUPoles", [](const Geom_BezierSurface& s) { return s.NbUPoles(); })
      .def("NbVPoles", [](const Geom_BezierSurface& s) { return s.NbVPoles(); })
      .def(
          "Pole",
          [](const Geom_BezierSurface& s, int u, int v) {
            check_index(u, 1, s.NbUPoles(), "UIndex out of range");
            check_index(v, 1, s.NbVPoles(), "VIndex out of range");
            return s.Pole(u, v);
          },
          py::arg("UIndex"), py::arg("VIndex"))
      .def(
          "Poles", [](const Geom_BezierSurface& s, TColgp_Array2OfPnt& p) { s.Poles(p); }, py::arg("P"))
      .def("Poles", [](const Geom_BezierSurface& s) { return copy_of(s.Poles()); })
      .def(
          "Weight",
          [](const Geom_BezierSurface& s, int u, int v) {
            check_index(u, 1, s.NbUPoles(), "UIndex out of range");
            check_index(v, 1, s.NbVPoles(), "VIndex out of range");
            return s.Weight(u, v);
          },
          py::arg("UIndex"), py::arg("VIndex"))
      .def(
          "Weights", [](const Geom_BezierSurface& s, TColStd_Array2OfReal& w) { s.Weights(w); }, py::arg("W"))
      .def("Weights",
           [](const Geom_BezierSurface& s) -> py::object {
             const TColStd_Array2OfReal* w = s.Weights();  // null for a non-rational surface: OCP hands back None
             return w == nullptr ? py::none() : py::cast(TColStd_Array2OfReal(*w));
           })
      .def_static("MaxDegree_s", []() { return Geom_BezierSurface::MaxDegree(); });

  py::class_<Geom_ElementarySurface, H<Geom_ElementarySurface>, Geom_Surface>(m, "Geom_ElementarySurface")
      .def(
          "SetAxis", [](Geom_ElementarySurface& s, const gp_Ax1& a) { s.SetAxis(a); }, py::arg("theA1"))
      .def(
          "SetLocation", [](Geom_ElementarySurface& s, const gp_Pnt& p) { s.SetLocation(p); }, py::arg("theLoc"))
      .def(
          "SetPosition", [](Geom_ElementarySurface& s, const gp_Ax3& a) { s.SetPosition(a); }, py::arg("theAx3"))
      .def("Axis", [](const Geom_ElementarySurface& s) { return s.Axis(); })
      .def("Location", [](const Geom_ElementarySurface& s) { return s.Location(); })
      .def("Position", [](const Geom_ElementarySurface& s) { return s.Position(); });

  py::class_<Geom_Plane, H<Geom_Plane>, Geom_ElementarySurface>(m, "Geom_Plane")
      .def(py::init([](const gp_Ax3& a) { return new Geom_Plane(a); }), py::arg("A3"))
      .def(py::init([](const gp_Pln& p) { return new Geom_Plane(p); }), py::arg("Pl"))
      .def(py::init([](const gp_Pnt& p, const gp_Dir& d) { return new Geom_Plane(p, d); }), py::arg("P"), py::arg("V"))
      .def(py::init([](double a, double b, double c, double d) { return new Geom_Plane(a, b, c, d); }), py::arg("A"),
           py::arg("B"), py::arg("C"), py::arg("D"))
      .def(
          "SetPln", [](Geom_Plane& p, const gp_Pln& v) { p.SetPln(v); }, py::arg("Pl"))
      .def("Pln", [](const Geom_Plane& p) { return p.Pln(); })
      .def("Coefficients", [](const Geom_Plane& p) {
        double a = 0.0, b = 0.0, c = 0.0, d = 0.0;
        p.Coefficients(a, b, c, d);
        return py::make_tuple(a, b, c, d);
      });

  // ---- Geom2d_Curve (what BRep_Tool.CurveOnSurface_s hands back; the concrete 2d curves come back as this type) --
  py::class_<Geom2d_Curve, H<Geom2d_Curve>>(m, "Geom2d_Curve")
      .def("Reverse", [](Geom2d_Curve& c) { c.Reverse(); })
      .def(
          "ReversedParameter", [](const Geom2d_Curve& c, double u) { return c.ReversedParameter(u); }, py::arg("U"))
      .def("FirstParameter", [](const Geom2d_Curve& c) { return c.FirstParameter(); })
      .def("LastParameter", [](const Geom2d_Curve& c) { return c.LastParameter(); })
      .def("IsClosed", [](const Geom2d_Curve& c) { return c.IsClosed(); })
      .def("IsPeriodic", [](const Geom2d_Curve& c) { return c.IsPeriodic(); })
      .def("Period", [](const Geom2d_Curve& c) { return c.Period(); })
      .def("Continuity", [](const Geom2d_Curve& c) { return c.Continuity(); })
      .def(
          "IsCN", [](const Geom2d_Curve& c, int n) { return c.IsCN(n); }, py::arg("N"))
      .def(
          "D0", [](const Geom2d_Curve& c, double u, gp_Pnt2d& p) { c.D0(u, p); }, py::arg("U"), py::arg("P"))
      .def(
          "D1", [](const Geom2d_Curve& c, double u, gp_Pnt2d& p, gp_Vec2d& v) { c.D1(u, p, v); }, py::arg("U"),
          py::arg("P"), py::arg("V1"))
      .def(
          "DN", [](const Geom2d_Curve& c, double u, int n) { return c.DN(u, n); }, py::arg("U"), py::arg("N"))
      .def("Value", [](const Geom2d_Curve& c, double u) { return c.Value(u); }, py::arg("U"));

  // ---- BRepAdaptor_Curve / BRepAdaptor_Surface -------------------------------------------------------------------
  py::class_<BRepAdaptor_Curve>(m, "BRepAdaptor_Curve")
      .def(py::init<>())
      .def(py::init<const TopoDS_Edge&>(), py::arg("E"))
      .def(py::init<const TopoDS_Edge&, const TopoDS_Face&>(), py::arg("E"), py::arg("F"))
      .def("Reset", [](BRepAdaptor_Curve& a) { a.Reset(); })
      .def(
          "Initialize", [](BRepAdaptor_Curve& a, const TopoDS_Edge& e) { a.Initialize(e); }, py::arg("E"))
      .def(
          "Initialize", [](BRepAdaptor_Curve& a, const TopoDS_Edge& e, const TopoDS_Face& f) { a.Initialize(e, f); },
          py::arg("E"), py::arg("F"))
      .def("Is3DCurve", [](const BRepAdaptor_Curve& a) { return a.Is3DCurve(); })
      .def("IsCurveOnSurface", [](const BRepAdaptor_Curve& a) { return a.IsCurveOnSurface(); })
      .def("Tolerance", [](const BRepAdaptor_Curve& a) { return a.Tolerance(); })
      .def("FirstParameter", [](const BRepAdaptor_Curve& a) { return a.FirstParameter(); })
      .def("LastParameter", [](const BRepAdaptor_Curve& a) { return a.LastParameter(); })
      .def("Continuity", [](const BRepAdaptor_Curve& a) { return a.Continuity(); })
      .def(
          "NbIntervals", [](const BRepAdaptor_Curve& a, GeomAbs_Shape s) { return a.NbIntervals(s); }, py::arg("S"))
      .def("IsClosed", [](const BRepAdaptor_Curve& a) { return a.IsClosed(); })
      .def("IsPeriodic", [](const BRepAdaptor_Curve& a) { return a.IsPeriodic(); })
      .def("Period", [](const BRepAdaptor_Curve& a) { return a.Period(); })
      .def(
          "Value", [](const BRepAdaptor_Curve& a, double u) { return a.Value(u); }, py::arg("U"))
      .def(
          "D0", [](const BRepAdaptor_Curve& a, double u, gp_Pnt& p) { a.D0(u, p); }, py::arg("U"), py::arg("P"))
      .def(
          "D1", [](const BRepAdaptor_Curve& a, double u, gp_Pnt& p, gp_Vec& v) { a.D1(u, p, v); }, py::arg("U"),
          py::arg("P"), py::arg("V"))
      .def(
          "D2", [](const BRepAdaptor_Curve& a, double u, gp_Pnt& p, gp_Vec& v1, gp_Vec& v2) { a.D2(u, p, v1, v2); },
          py::arg("U"), py::arg("P"), py::arg("V1"), py::arg("V2"))
      .def(
          "D3",
          [](const BRepAdaptor_Curve& a, double u, gp_Pnt& p, gp_Vec& v1, gp_Vec& v2, gp_Vec& v3) {
            a.D3(u, p, v1, v2, v3);
          },
          py::arg("U"), py::arg("P"), py::arg("V1"), py::arg("V2"), py::arg("V3"))
      .def(
          "DN", [](const BRepAdaptor_Curve& a, double u, int n) { return a.DN(u, n); }, py::arg("U"), py::arg("N"))
      .def(
          "Resolution", [](const BRepAdaptor_Curve& a, double r3d) { return a.Resolution(r3d); }, py::arg("R3d"))
      .def("GetType", [](const BRepAdaptor_Curve& a) { return a.GetType(); })
      .def("Line", [](const BRepAdaptor_Curve& a) { return a.Line(); })
      .def("Circle", [](const BRepAdaptor_Curve& a) { return a.Circle(); })
      .def("Ellipse", [](const BRepAdaptor_Curve& a) { return a.Ellipse(); })
      .def("Hyperbola", [](const BRepAdaptor_Curve& a) { return a.Hyperbola(); })
      .def("Parabola", [](const BRepAdaptor_Curve& a) { return a.Parabola(); })
      .def("Degree", [](const BRepAdaptor_Curve& a) { return a.Degree(); })
      .def("IsRational", [](const BRepAdaptor_Curve& a) { return a.IsRational(); })
      .def("NbPoles", [](const BRepAdaptor_Curve& a) { return a.NbPoles(); })
      .def("NbKnots", [](const BRepAdaptor_Curve& a) { return a.NbKnots(); })
      .def("Bezier", [](const BRepAdaptor_Curve& a) { return a.Bezier(); })
      .def("BSpline", [](const BRepAdaptor_Curve& a) { return a.BSpline(); })
      .def("Trsf", [](const BRepAdaptor_Curve& a) { return a.Trsf(); })
      .def("Edge", [](const BRepAdaptor_Curve& a) { return a.Edge(); });

  py::class_<BRepAdaptor_Surface>(m, "BRepAdaptor_Surface")
      .def(py::init<>())
      .def(py::init<const TopoDS_Face&, bool>(), py::arg("F"), py::arg("R") = true)
      .def(
          "Initialize", [](BRepAdaptor_Surface& a, const TopoDS_Face& f, bool r) { a.Initialize(f, r); }, py::arg("F"),
          py::arg("Restriction") = true)
      .def("Tolerance", [](const BRepAdaptor_Surface& a) { return a.Tolerance(); })
      .def("FirstUParameter", [](const BRepAdaptor_Surface& a) { return a.FirstUParameter(); })
      .def("LastUParameter", [](const BRepAdaptor_Surface& a) { return a.LastUParameter(); })
      .def("FirstVParameter", [](const BRepAdaptor_Surface& a) { return a.FirstVParameter(); })
      .def("LastVParameter", [](const BRepAdaptor_Surface& a) { return a.LastVParameter(); })
      .def("UContinuity", [](const BRepAdaptor_Surface& a) { return a.UContinuity(); })
      .def("VContinuity", [](const BRepAdaptor_Surface& a) { return a.VContinuity(); })
      .def(
          "NbUIntervals", [](const BRepAdaptor_Surface& a, GeomAbs_Shape s) { return a.NbUIntervals(s); },
          py::arg("theSh"))
      .def(
          "NbVIntervals", [](const BRepAdaptor_Surface& a, GeomAbs_Shape s) { return a.NbVIntervals(s); },
          py::arg("theSh"))
      .def("IsUClosed", [](const BRepAdaptor_Surface& a) { return a.IsUClosed(); })
      .def("IsVClosed", [](const BRepAdaptor_Surface& a) { return a.IsVClosed(); })
      .def("IsUPeriodic", [](const BRepAdaptor_Surface& a) { return a.IsUPeriodic(); })
      .def("UPeriod", [](const BRepAdaptor_Surface& a) { return a.UPeriod(); })
      .def("IsVPeriodic", [](const BRepAdaptor_Surface& a) { return a.IsVPeriodic(); })
      .def("VPeriod", [](const BRepAdaptor_Surface& a) { return a.VPeriod(); })
      .def(
          "Value", [](const BRepAdaptor_Surface& a, double u, double v) { return a.Value(u, v); }, py::arg("U"),
          py::arg("V"))
      .def(
          "D0", [](const BRepAdaptor_Surface& a, double u, double v, gp_Pnt& p) { a.D0(u, v, p); }, py::arg("U"),
          py::arg("V"), py::arg("P"))
      .def(
          "D1",
          [](const BRepAdaptor_Surface& a, double u, double v, gp_Pnt& p, gp_Vec& d1u, gp_Vec& d1v) {
            a.D1(u, v, p, d1u, d1v);
          },
          py::arg("U"), py::arg("V"), py::arg("P"), py::arg("D1U"), py::arg("D1V"))
      .def(
          "D2",
          [](const BRepAdaptor_Surface& a, double u, double v, gp_Pnt& p, gp_Vec& d1u, gp_Vec& d1v, gp_Vec& d2u,
             gp_Vec& d2v, gp_Vec& d2uv) { a.D2(u, v, p, d1u, d1v, d2u, d2v, d2uv); },
          py::arg("U"), py::arg("V"), py::arg("P"), py::arg("D1U"), py::arg("D1V"), py::arg("D2U"), py::arg("D2V"),
          py::arg("D2UV"))
      .def(
          "DN", [](const BRepAdaptor_Surface& a, double u, double v, int nu, int nv) { return a.DN(u, v, nu, nv); },
          py::arg("U"), py::arg("V"), py::arg("Nu"), py::arg("Nv"))
      .def(
          "UResolution", [](const BRepAdaptor_Surface& a, double r) { return a.UResolution(r); }, py::arg("theR3d"))
      .def(
          "VResolution", [](const BRepAdaptor_Surface& a, double r) { return a.VResolution(r); }, py::arg("theR3d"))
      .def("GetType", [](const BRepAdaptor_Surface& a) { return a.GetType(); })
      .def("Plane", [](const BRepAdaptor_Surface& a) { return a.Plane(); })
      .def("Cylinder", [](const BRepAdaptor_Surface& a) { return a.Cylinder(); })
      .def("Cone", [](const BRepAdaptor_Surface& a) { return a.Cone(); })
      .def("Sphere", [](const BRepAdaptor_Surface& a) { return a.Sphere(); })
      .def("Torus", [](const BRepAdaptor_Surface& a) { return a.Torus(); })
      .def("UDegree", [](const BRepAdaptor_Surface& a) { return a.UDegree(); })
      .def("NbUPoles", [](const BRepAdaptor_Surface& a) { return a.NbUPoles(); })
      .def("VDegree", [](const BRepAdaptor_Surface& a) { return a.VDegree(); })
      .def("NbVPoles", [](const BRepAdaptor_Surface& a) { return a.NbVPoles(); })
      .def("NbUKnots", [](const BRepAdaptor_Surface& a) { return a.NbUKnots(); })
      .def("NbVKnots", [](const BRepAdaptor_Surface& a) { return a.NbVKnots(); })
      .def("IsURational", [](const BRepAdaptor_Surface& a) { return a.IsURational(); })
      .def("IsVRational", [](const BRepAdaptor_Surface& a) { return a.IsVRational(); })
      .def("Bezier", [](const BRepAdaptor_Surface& a) { return a.Bezier(); })
      .def("BSpline", [](const BRepAdaptor_Surface& a) { return a.BSpline(); })
      .def("AxeOfRevolution", [](const BRepAdaptor_Surface& a) { return a.AxeOfRevolution(); })
      .def("Direction", [](const BRepAdaptor_Surface& a) { return a.Direction(); })
      .def("OffsetValue", [](const BRepAdaptor_Surface& a) { return a.OffsetValue(); })
      .def("Trsf", [](const BRepAdaptor_Surface& a) { return a.Trsf(); })
      .def("Face", [](const BRepAdaptor_Surface& a) { return a.Face(); });

  // ---- properties: GProp_GProps, BRepGProp ------------------------------------------------------------------------
  py::class_<GProp_GProps>(m, "GProp_GProps")
      .def(py::init<>())
      .def(py::init<const gp_Pnt&>(), py::arg("SystemLocation"))
      .def(
          "Add", [](GProp_GProps& g, const GProp_GProps& other, double density) { g.Add(other, density); },
          py::arg("Item"), py::arg("Density") = 1.0)
      .def("Mass", [](const GProp_GProps& g) { return g.Mass(); })
      .def("CentreOfMass", [](const GProp_GProps& g) { return g.CentreOfMass(); })
      .def(
          "MomentOfInertia", [](const GProp_GProps& g, const gp_Ax1& a) { return g.MomentOfInertia(a); }, py::arg("A"))
      .def(
          "RadiusOfGyration", [](const GProp_GProps& g, const gp_Ax1& a) { return g.RadiusOfGyration(a); },
          py::arg("A"))
      .def("StaticMoments", [](const GProp_GProps& g) {
        double ix = 0.0, iy = 0.0, iz = 0.0;
        g.StaticMoments(ix, iy, iz);
        return py::make_tuple(ix, iy, iz);
      });

  py::class_<BRepGProp>(m, "BRepGProp")
      .def_static(
          "LinearProperties_s",
          [](const TopoDS_Shape& s, GProp_GProps& p, bool skip, bool tri) {
            BRepGProp::LinearProperties(s, p, skip, tri);
          },
          py::arg("S"), py::arg("LProps"), py::arg("SkipShared") = false, py::arg("UseTriangulation") = false)
      // the Eps overloads come first: a Python float must not be taken for the bool of the other overload
      .def_static(
          "SurfaceProperties_s",
          [](const TopoDS_Shape& s, GProp_GProps& p, double eps, bool skip) {
            return BRepGProp::SurfaceProperties(s, p, eps, skip);
          },
          py::arg("S"), py::arg("SProps"), py::arg("Eps"), py::arg("SkipShared") = false)
      .def_static(
          "SurfaceProperties_s",
          [](const TopoDS_Shape& s, GProp_GProps& p, bool skip, bool tri) {
            BRepGProp::SurfaceProperties(s, p, skip, tri);
          },
          py::arg("S"), py::arg("SProps"), py::arg("SkipShared") = false, py::arg("UseTriangulation") = false)
      .def_static(
          "VolumeProperties_s",
          [](const TopoDS_Shape& s, GProp_GProps& p, double eps, bool onlyClosed, bool skip) {
            return BRepGProp::VolumeProperties(s, p, eps, onlyClosed, skip);
          },
          py::arg("S"), py::arg("VProps"), py::arg("Eps"), py::arg("OnlyClosed") = false, py::arg("SkipShared") = false)
      .def_static(
          "VolumeProperties_s",
          [](const TopoDS_Shape& s, GProp_GProps& p, bool onlyClosed, bool skip, bool tri) {
            BRepGProp::VolumeProperties(s, p, onlyClosed, skip, tri);
          },
          py::arg("S"), py::arg("VProps"), py::arg("OnlyClosed") = false, py::arg("SkipShared") = false,
          py::arg("UseTriangulation") = false)
      .def_static(
          "VolumePropertiesGK_s",
          [](const TopoDS_Shape& s, GProp_GProps& p, double eps, bool onlyClosed, bool useSpan, bool cg, bool ifl,
             bool skip) { return BRepGProp::VolumePropertiesGK(s, p, eps, onlyClosed, useSpan, cg, ifl, skip); },
          py::arg("S"), py::arg("VProps"), py::arg("Eps") = 0.001, py::arg("OnlyClosed") = false,
          py::arg("IsUseSpan") = false, py::arg("CGFlag") = false, py::arg("IFlag") = false,
          py::arg("SkipShared") = false)
      .def_static(
          "VolumePropertiesGK_s",
          [](const TopoDS_Shape& s, GProp_GProps& p, const gp_Pln& pln, double eps, bool onlyClosed, bool useSpan,
             bool cg, bool ifl,
             bool skip) { return BRepGProp::VolumePropertiesGK(s, p, pln, eps, onlyClosed, useSpan, cg, ifl, skip); },
          py::arg("S"), py::arg("VProps"), py::arg("thePln"), py::arg("Eps") = 0.001, py::arg("OnlyClosed") = false,
          py::arg("IsUseSpan") = false, py::arg("CGFlag") = false, py::arg("IFlag") = false,
          py::arg("SkipShared") = false);

  // ---- Bnd_Box / BRepBndLib -----------------------------------------------------------------------------------------
  py::class_<Bnd_Box>(m, "Bnd_Box")
      .def(py::init<>())
      .def(py::init<const gp_Pnt&, const gp_Pnt&>(), py::arg("theMin"), py::arg("theMax"))
      .def("SetWhole", [](Bnd_Box& b) { b.SetWhole(); })
      .def("SetVoid", [](Bnd_Box& b) { b.SetVoid(); })
      .def(
          "Set", [](Bnd_Box& b, const gp_Pnt& p) { b.Set(p); }, py::arg("P"))
      .def(
          "Set", [](Bnd_Box& b, const gp_Pnt& p, const gp_Dir& d) { b.Set(p, d); }, py::arg("P"), py::arg("D"))
      .def(
          "Update",
          [](Bnd_Box& b, double x0, double y0, double z0, double x1, double y1, double z1) {
            b.Update(x0, y0, z0, x1, y1, z1);
          },
          py::arg("aXmin"), py::arg("aYmin"), py::arg("aZmin"), py::arg("aXmax"), py::arg("aYmax"), py::arg("aZmax"))
      .def(
          "Update", [](Bnd_Box& b, double x, double y, double z) { b.Update(x, y, z); }, py::arg("X"), py::arg("Y"),
          py::arg("Z"))
      .def("GetGap", [](const Bnd_Box& b) { return b.GetGap(); })
      .def(
          "SetGap", [](Bnd_Box& b, double tol) { b.SetGap(tol); }, py::arg("Tol"))
      .def(
          "Enlarge", [](Bnd_Box& b, double tol) { b.Enlarge(tol); }, py::arg("Tol"))
      .def("CornerMin", [](const Bnd_Box& b) { return b.CornerMin(); })
      .def("CornerMax", [](const Bnd_Box& b) { return b.CornerMax(); })
      .def("IsOpen", [](const Bnd_Box& b) { return b.IsOpen(); })
      .def("IsWhole", [](const Bnd_Box& b) { return b.IsWhole(); })
      .def("IsVoid", [](const Bnd_Box& b) { return b.IsVoid(); })
      .def(
          "IsXThin", [](const Bnd_Box& b, double t) { return b.IsXThin(t); }, py::arg("tol"))
      .def(
          "IsYThin", [](const Bnd_Box& b, double t) { return b.IsYThin(t); }, py::arg("tol"))
      .def(
          "IsZThin", [](const Bnd_Box& b, double t) { return b.IsZThin(t); }, py::arg("tol"))
      .def(
          "IsThin", [](const Bnd_Box& b, double t) { return b.IsThin(t); }, py::arg("tol"))
      .def(
          "Transformed", [](const Bnd_Box& b, const gp_Trsf& t) { return b.Transformed(t); }, py::arg("T"))
      .def(
          "Add", [](Bnd_Box& b, const Bnd_Box& other) { b.Add(other); }, py::arg("Other"))
      .def(
          "Add", [](Bnd_Box& b, const gp_Pnt& p) { b.Add(p); }, py::arg("P"))
      .def(
          "IsOut", [](const Bnd_Box& b, const gp_Pnt& p) { return b.IsOut(p); }, py::arg("P"))
      .def(
          "IsOut", [](const Bnd_Box& b, const Bnd_Box& other) { return b.IsOut(other); }, py::arg("Other"))
      .def(
          "Distance", [](const Bnd_Box& b, const Bnd_Box& other) { return b.Distance(other); }, py::arg("Other"))
      .def("SquareExtent", [](const Bnd_Box& b) { return b.SquareExtent(); })
      .def("Get", [](const Bnd_Box& b) {
        double x0 = 0.0, y0 = 0.0, z0 = 0.0, x1 = 0.0, y1 = 0.0, z1 = 0.0;
        b.Get(x0, y0, z0, x1, y1, z1);
        return py::make_tuple(x0, y0, z0, x1, y1, z1);
      });

  py::class_<BRepBndLib>(m, "BRepBndLib")
      .def_static(
          "Add_s", [](const TopoDS_Shape& s, Bnd_Box& b, bool tri) { BRepBndLib::Add(s, b, tri); }, py::arg("S"),
          py::arg("B"), py::arg("useTriangulation") = true)
      .def_static(
          "AddClose_s", [](const TopoDS_Shape& s, Bnd_Box& b) { BRepBndLib::AddClose(s, b); }, py::arg("S"),
          py::arg("B"))
      .def_static(
          "AddOptimal_s",
          [](const TopoDS_Shape& s, Bnd_Box& b, bool tri, bool tol) { BRepBndLib::AddOptimal(s, b, tri, tol); },
          py::arg("S"), py::arg("B"), py::arg("useTriangulation") = true, py::arg("useShapeTolerance") = false);

  // ---- classifiers -------------------------------------------------------------------------------------------------
  py::class_<BRepClass3d_SClassifier>(m, "BRepClass3d_SClassifier")
      .def(py::init<>())
      .def("Rejected", [](const BRepClass3d_SClassifier& c) { return c.Rejected(); })
      .def("State", [](const BRepClass3d_SClassifier& c) { return c.State(); })
      .def("IsOnAFace", [](const BRepClass3d_SClassifier& c) { return c.IsOnAFace(); })
      .def("Face", [](const BRepClass3d_SClassifier& c) { return c.Face(); });
  py::class_<BRepClass3d_SolidClassifier, BRepClass3d_SClassifier>(m, "BRepClass3d_SolidClassifier")
      .def(py::init<>())
      .def(py::init<const TopoDS_Shape&>(), py::arg("S"))
      .def(py::init<const TopoDS_Shape&, const gp_Pnt&, double>(), py::arg("S"), py::arg("P"), py::arg("Tol"))
      .def(
          "Load", [](BRepClass3d_SolidClassifier& c, const TopoDS_Shape& s) { c.Load(s); }, py::arg("S"))
      .def(
          "Perform", [](BRepClass3d_SolidClassifier& c, const gp_Pnt& p, double tol) { c.Perform(p, tol); },
          py::arg("P"), py::arg("Tol"))
      .def(
          "PerformInfinitePoint", [](BRepClass3d_SolidClassifier& c, double tol) { c.PerformInfinitePoint(tol); },
          py::arg("Tol"));

  py::class_<BRepClass_FClassifier>(m, "BRepClass_FClassifier")
      .def(py::init<>())
      .def("State", [](const BRepClass_FClassifier& c) { return c.State(); })
      .def("Rejected", [](const BRepClass_FClassifier& c) { return c.Rejected(); })
      .def("NoWires", [](const BRepClass_FClassifier& c) { return c.NoWires(); })
      .def("EdgeParameter", [](const BRepClass_FClassifier& c) { return c.EdgeParameter(); });
  py::class_<BRepClass_FaceClassifier, BRepClass_FClassifier>(m, "BRepClass_FaceClassifier")
      .def(py::init<>())
      .def(py::init<const TopoDS_Face&, const gp_Pnt2d&, double, bool, double>(), py::arg("theF"), py::arg("theP"),
           py::arg("theTol"), py::arg("theUseBndBox") = false, py::arg("theGapCheckTol") = 0.1)
      .def(py::init<const TopoDS_Face&, const gp_Pnt&, double, bool, double>(), py::arg("theF"), py::arg("theP"),
           py::arg("theTol"), py::arg("theUseBndBox") = false, py::arg("theGapCheckTol") = 0.1)
      .def(
          "Perform",
          [](BRepClass_FaceClassifier& c, const TopoDS_Face& f, const gp_Pnt2d& p, double tol, bool bb, double gap) {
            c.Perform(f, p, tol, bb, gap);
          },
          py::arg("theF"), py::arg("theP"), py::arg("theTol"), py::arg("theUseBndBox") = false,
          py::arg("theGapCheckTol") = 0.1)
      .def(
          "Perform",
          [](BRepClass_FaceClassifier& c, const TopoDS_Face& f, const gp_Pnt& p, double tol, bool bb, double gap) {
            c.Perform(f, p, tol, bb, gap);
          },
          py::arg("theF"), py::arg("theP"), py::arg("theTol"), py::arg("theUseBndBox") = false,
          py::arg("theGapCheckTol") = 0.1);

  // ---- BRepExtrema_DistShapeShape
  // ------------------------------------------------------------------------------------
  py::class_<BRepExtrema_DistShapeShape>(m, "BRepExtrema_DistShapeShape")
      .def(py::init<>())
      .def(py::init<const TopoDS_Shape&, const TopoDS_Shape&>(), py::arg("Shape1"), py::arg("Shape2"))
      .def(py::init<const TopoDS_Shape&, const TopoDS_Shape&, double>(), py::arg("Shape1"), py::arg("Shape2"),
           py::arg("theDeflection"))
      .def(
          "SetDeflection", [](BRepExtrema_DistShapeShape& d, double v) { d.SetDeflection(v); },
          py::arg("theDeflection"))
      .def(
          "LoadS1", [](BRepExtrema_DistShapeShape& d, const TopoDS_Shape& s) { d.LoadS1(s); }, py::arg("Shape1"))
      .def(
          "LoadS2", [](BRepExtrema_DistShapeShape& d, const TopoDS_Shape& s) { d.LoadS2(s); }, py::arg("Shape1"))
      .def("Perform", [](BRepExtrema_DistShapeShape& d) { return d.Perform(); })
      .def("IsDone", [](const BRepExtrema_DistShapeShape& d) { return d.IsDone(); })
      .def("NbSolution", [](const BRepExtrema_DistShapeShape& d) { return d.NbSolution(); })
      .def("Value", [](const BRepExtrema_DistShapeShape& d) { return d.Value(); })
      .def("InnerSolution", [](const BRepExtrema_DistShapeShape& d) { return d.InnerSolution(); })
      .def(
          "PointOnShape1",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            return d.PointOnShape1(n);
          },
          py::arg("N"))
      .def(
          "PointOnShape2",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            return d.PointOnShape2(n);
          },
          py::arg("N"))
      .def(
          "SupportTypeShape1",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            return d.SupportTypeShape1(n);
          },
          py::arg("N"))
      .def(
          "SupportTypeShape2",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            return d.SupportTypeShape2(n);
          },
          py::arg("N"))
      .def(
          "SupportOnShape1",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            return d.SupportOnShape1(n);
          },
          py::arg("N"))
      .def(
          "SupportOnShape2",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            return d.SupportOnShape2(n);
          },
          py::arg("N"))
      .def(
          "ParOnEdgeS1",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            double t = 0.0;
            d.ParOnEdgeS1(n, t);
            return py::make_tuple(t);
          },
          py::arg("N"))
      .def(
          "ParOnEdgeS2",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            double t = 0.0;
            d.ParOnEdgeS2(n, t);
            return py::make_tuple(t);
          },
          py::arg("N"))
      .def(
          "ParOnFaceS1",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            double u = 0.0, v = 0.0;
            d.ParOnFaceS1(n, u, v);
            return py::make_tuple(u, v);
          },
          py::arg("N"))
      .def(
          "ParOnFaceS2",
          [](const BRepExtrema_DistShapeShape& d, int n) {
            check_index(n, 1, d.NbSolution(), "solution index out of range");
            double u = 0.0, v = 0.0;
            d.ParOnFaceS2(n, u, v);
            return py::make_tuple(u, v);
          },
          py::arg("N"));

  // ---- BRepLProp_SLProps --------------------------------------------------------------------------------------------
  py::class_<BRepLProp_SLProps>(m, "BRepLProp_SLProps")
      .def(py::init<const BRepAdaptor_Surface&, double, double, int, double>(), py::arg("S"), py::arg("U"),
           py::arg("V"), py::arg("N"), py::arg("Resolution"))
      .def(py::init<const BRepAdaptor_Surface&, int, double>(), py::arg("S"), py::arg("N"), py::arg("Resolution"))
      .def(py::init<int, double>(), py::arg("N"), py::arg("Resolution"))
      .def(
          "SetSurface", [](BRepLProp_SLProps& p, const BRepAdaptor_Surface& s) { p.SetSurface(s); }, py::arg("S"))
      .def(
          "SetParameters", [](BRepLProp_SLProps& p, double u, double v) { p.SetParameters(u, v); }, py::arg("U"),
          py::arg("V"))
      .def("Value", [](const BRepLProp_SLProps& p) { return p.Value(); })
      .def("D1U", [](BRepLProp_SLProps& p) { return p.D1U(); })
      .def("D1V", [](BRepLProp_SLProps& p) { return p.D1V(); })
      .def("D2U", [](BRepLProp_SLProps& p) { return p.D2U(); })
      .def("D2V", [](BRepLProp_SLProps& p) { return p.D2V(); })
      .def("DUV", [](BRepLProp_SLProps& p) { return p.DUV(); })
      .def("IsTangentUDefined", [](BRepLProp_SLProps& p) { return p.IsTangentUDefined(); })
      .def(
          "TangentU", [](BRepLProp_SLProps& p, gp_Dir& d) { p.TangentU(d); }, py::arg("D"))
      .def("IsTangentVDefined", [](BRepLProp_SLProps& p) { return p.IsTangentVDefined(); })
      .def(
          "TangentV", [](BRepLProp_SLProps& p, gp_Dir& d) { p.TangentV(d); }, py::arg("D"))
      .def("IsNormalDefined", [](BRepLProp_SLProps& p) { return p.IsNormalDefined(); })
      .def("Normal", [](BRepLProp_SLProps& p) { return p.Normal(); })
      .def("IsCurvatureDefined", [](BRepLProp_SLProps& p) { return p.IsCurvatureDefined(); })
      .def("IsUmbilic", [](BRepLProp_SLProps& p) { return p.IsUmbilic(); })
      .def("MaxCurvature", [](BRepLProp_SLProps& p) { return p.MaxCurvature(); })
      .def("MinCurvature", [](BRepLProp_SLProps& p) { return p.MinCurvature(); })
      .def(
          "CurvatureDirections", [](BRepLProp_SLProps& p, gp_Dir& mx, gp_Dir& mn) { p.CurvatureDirections(mx, mn); },
          py::arg("MaxD"), py::arg("MinD"))
      .def("MeanCurvature", [](BRepLProp_SLProps& p) { return p.MeanCurvature(); })
      .def("GaussianCurvature", [](BRepLProp_SLProps& p) { return p.GaussianCurvature(); });

  // ---- GCPnts -------------------------------------------------------------------------------------------------------
  py::class_<GCPnts_QuasiUniformDeflection>(m, "GCPnts_QuasiUniformDeflection")
      .def(py::init<>())
      .def(py::init([](const BRepAdaptor_Curve& c, double defl, GeomAbs_Shape cont) {
             return new GCPnts_QuasiUniformDeflection(c, defl, cont);
           }),
           py::arg("theC"), py::arg("theDeflection"), py::arg("theContinuity") = GeomAbs_C1)
      .def(py::init([](const BRepAdaptor_Curve& c, double defl, double u1, double u2, GeomAbs_Shape cont) {
             return new GCPnts_QuasiUniformDeflection(c, defl, u1, u2, cont);
           }),
           py::arg("theC"), py::arg("theDeflection"), py::arg("theU1"), py::arg("theU2"),
           py::arg("theContinuity") = GeomAbs_C1)
      .def(
          "Initialize",
          [](GCPnts_QuasiUniformDeflection& g, const BRepAdaptor_Curve& c, double defl, GeomAbs_Shape cont) {
            g.Initialize(c, defl, cont);
          },
          py::arg("theC"), py::arg("theDeflection"), py::arg("theContinuity") = GeomAbs_C1)
      .def(
          "Initialize",
          [](GCPnts_QuasiUniformDeflection& g, const BRepAdaptor_Curve& c, double defl, double u1, double u2,
             GeomAbs_Shape cont) { g.Initialize(c, defl, u1, u2, cont); },
          py::arg("theC"), py::arg("theDeflection"), py::arg("theU1"), py::arg("theU2"),
          py::arg("theContinuity") = GeomAbs_C1)
      .def("IsDone", [](const GCPnts_QuasiUniformDeflection& g) { return g.IsDone(); })
      .def("NbPoints", [](const GCPnts_QuasiUniformDeflection& g) { return g.NbPoints(); })
      .def(
          "Parameter",
          [](const GCPnts_QuasiUniformDeflection& g, int i) {
            check_index(i, 1, g.NbPoints());
            return g.Parameter(i);
          },
          py::arg("Index"))
      .def(
          "Value",
          [](const GCPnts_QuasiUniformDeflection& g, int i) {
            check_index(i, 1, g.NbPoints());
            return g.Value(i);
          },
          py::arg("Index"))
      .def("Deflection", [](const GCPnts_QuasiUniformDeflection& g) { return g.Deflection(); });

  py::class_<GCPnts_TangentialDeflection>(m, "GCPnts_TangentialDeflection")
      .def(py::init<>())
      .def(py::init([](const BRepAdaptor_Curve& c, double ang, double curv, int minPts, double utol, double minLen) {
             return new GCPnts_TangentialDeflection(c, ang, curv, minPts, utol, minLen);
           }),
           py::arg("theC"), py::arg("theAngularDeflection"), py::arg("theCurvatureDeflection"),
           py::arg("theMinimumOfPoints") = 2, py::arg("theUTol") = 1.0e-9, py::arg("theMinLen") = 1.0e-7)
      .def(py::init([](const BRepAdaptor_Curve& c, double first, double last, double ang, double curv, int minPts,
                       double utol, double minLen) {
             return new GCPnts_TangentialDeflection(c, first, last, ang, curv, minPts, utol, minLen);
           }),
           py::arg("theC"), py::arg("theFirstParameter"), py::arg("theLastParameter"), py::arg("theAngularDeflection"),
           py::arg("theCurvatureDeflection"), py::arg("theMinimumOfPoints") = 2, py::arg("theUTol") = 1.0e-9,
           py::arg("theMinLen") = 1.0e-7)
      .def(
          "Initialize",
          [](GCPnts_TangentialDeflection& g, const BRepAdaptor_Curve& c, double ang, double curv, int minPts,
             double utol, double minLen) { g.Initialize(c, ang, curv, minPts, utol, minLen); },
          py::arg("theC"), py::arg("theAngularDeflection"), py::arg("theCurvatureDeflection"),
          py::arg("theMinimumOfPoints") = 2, py::arg("theUTol") = 1.0e-9, py::arg("theMinLen") = 1.0e-7)
      .def(
          "Initialize",
          [](GCPnts_TangentialDeflection& g, const BRepAdaptor_Curve& c, double first, double last, double ang,
             double curv, int minPts, double utol,
             double minLen) { g.Initialize(c, first, last, ang, curv, minPts, utol, minLen); },
          py::arg("theC"), py::arg("theFirstParameter"), py::arg("theLastParameter"), py::arg("theAngularDeflection"),
          py::arg("theCurvatureDeflection"), py::arg("theMinimumOfPoints") = 2, py::arg("theUTol") = 1.0e-9,
          py::arg("theMinLen") = 1.0e-7)
      .def(
          "AddPoint",
          [](GCPnts_TangentialDeflection& g, const gp_Pnt& p, double u, bool replace) {
            return g.AddPoint(p, u, replace);
          },
          py::arg("thePnt"), py::arg("theParam"), py::arg("theIsReplace") = true)
      .def("NbPoints", [](const GCPnts_TangentialDeflection& g) { return g.NbPoints(); })
      .def(
          "Parameter",
          [](const GCPnts_TangentialDeflection& g, int i) {
            check_index(i, 1, g.NbPoints());
            return g.Parameter(i);
          },
          py::arg("I"))
      .def(
          "Value",
          [](const GCPnts_TangentialDeflection& g, int i) {
            check_index(i, 1, g.NbPoints());
            return g.Value(i);
          },
          py::arg("I"));

  // ---- GeomAPI_Interpolate / GeomAPI_ProjectPointOnSurf / GeomConvert
  // ------------------------------------------------
  py::class_<GeomAPI_Interpolate>(m, "GeomAPI_Interpolate")
      .def(py::init([](const H<TColgp_HArray1OfPnt>& pts, bool periodic, double tol) {
             return new GeomAPI_Interpolate(pts, periodic, tol);
           }),
           py::arg("Points").none(false), py::arg("PeriodicFlag"), py::arg("Tolerance"))
      .def(
          "Load", [](GeomAPI_Interpolate& g, const gp_Vec& a, const gp_Vec& b, bool scale) { g.Load(a, b, scale); },
          py::arg("InitialTangent"), py::arg("FinalTangent"), py::arg("Scale") = true)
      .def("Perform", [](GeomAPI_Interpolate& g) { g.Perform(); })
      .def("IsDone", [](const GeomAPI_Interpolate& g) { return g.IsDone(); })
      .def("Curve", [](const GeomAPI_Interpolate& g) { return g.Curve(); });

  py::class_<GeomAPI_ProjectPointOnSurf>(m, "GeomAPI_ProjectPointOnSurf")
      .def(py::init<>())
      .def(py::init([](const gp_Pnt& p, const H<Geom_Surface>& s) { return new GeomAPI_ProjectPointOnSurf(p, s); }),
           py::arg("P"), py::arg("Surface").none(false))
      .def(py::init([](const gp_Pnt& p, const H<Geom_Surface>& s, double tol) {
             return new GeomAPI_ProjectPointOnSurf(p, s, tol);
           }),
           py::arg("P"), py::arg("Surface").none(false), py::arg("Tolerance"))
      .def(py::init([](const gp_Pnt& p, const H<Geom_Surface>& s, double u0, double u1, double v0, double v1) {
             return new GeomAPI_ProjectPointOnSurf(p, s, u0, u1, v0, v1);
           }),
           py::arg("P"), py::arg("Surface").none(false), py::arg("Umin"), py::arg("Usup"), py::arg("Vmin"),
           py::arg("Vsup"))
      .def(
          "Init", [](GeomAPI_ProjectPointOnSurf& g, const gp_Pnt& p, const H<Geom_Surface>& s) { g.Init(p, s); },
          py::arg("P"), py::arg("Surface").none(false))
      .def(
          "Init",
          [](GeomAPI_ProjectPointOnSurf& g, const gp_Pnt& p, const H<Geom_Surface>& s, double tol) {
            g.Init(p, s, tol);
          },
          py::arg("P"), py::arg("Surface").none(false), py::arg("Tolerance"))
      .def(
          "Perform", [](GeomAPI_ProjectPointOnSurf& g, const gp_Pnt& p) { g.Perform(p); }, py::arg("P"))
      .def("IsDone", [](const GeomAPI_ProjectPointOnSurf& g) { return g.IsDone(); })
      .def("NbPoints", [](const GeomAPI_ProjectPointOnSurf& g) { return g.NbPoints(); })
      .def(
          "Point",
          [](const GeomAPI_ProjectPointOnSurf& g, int i) {
            check_index(i, 1, g.NbPoints());
            return g.Point(i);
          },
          py::arg("Index"))
      .def(
          "Distance",
          [](const GeomAPI_ProjectPointOnSurf& g, int i) {
            check_index(i, 1, g.NbPoints());
            return g.Distance(i);
          },
          py::arg("Index"))
      .def(
          "Parameters",
          [](const GeomAPI_ProjectPointOnSurf& g, int i) {
            check_index(i, 1, g.NbPoints());
            double u = 0.0, v = 0.0;
            g.Parameters(i, u, v);
            return py::make_tuple(u, v);
          },
          py::arg("Index"))
      .def("NearestPoint",
           [](const GeomAPI_ProjectPointOnSurf& g) {
             if (g.NbPoints() < 1)
               throw StdFail_NotDone("GeomAPI_ProjectPointOnSurf::NearestPoint");
             return g.NearestPoint();
           })
      .def("LowerDistance",
           [](const GeomAPI_ProjectPointOnSurf& g) {
             if (g.NbPoints() < 1)
               throw StdFail_NotDone("GeomAPI_ProjectPointOnSurf::LowerDistance");
             return g.LowerDistance();
           })
      .def("LowerDistanceParameters", [](const GeomAPI_ProjectPointOnSurf& g) {
        if (g.NbPoints() < 1)
          throw StdFail_NotDone("GeomAPI_ProjectPointOnSurf::LowerDistanceParameters");
        double u = 0.0, v = 0.0;
        g.LowerDistanceParameters(u, v);
        return py::make_tuple(u, v);
      });

  py::class_<GeomConvert>(m, "GeomConvert")
      .def_static(
          "CurveToBSplineCurve_s", [](const H<Geom_Curve>& c) { return GeomConvert::CurveToBSplineCurve(c); },
          py::arg("C").none(false))
      .def_static(
          "SurfaceToBSplineSurface_s", [](const H<Geom_Surface>& s) { return GeomConvert::SurfaceToBSplineSurface(s); },
          py::arg("S").none(false));

  // ---- Poly_Triangle / Poly_Triangulation
  // -----------------------------------------------------------------------------
  py::class_<Poly_Triangle>(m, "Poly_Triangle")
      .def(py::init<>())
      .def(py::init<int, int, int>(), py::arg("theN1"), py::arg("theN2"), py::arg("theN3"))
      .def(
          "Set", [](Poly_Triangle& t, int a, int b, int c) { t.Set(a, b, c); }, py::arg("theN1"), py::arg("theN2"),
          py::arg("theN3"))
      .def(
          "Set",
          [](Poly_Triangle& t, int i, int node) {
            check_index(i, 1, 3);
            t.Set(i, node);
          },
          py::arg("theIndex"), py::arg("theNode"))
      .def(
          "Value",
          [](const Poly_Triangle& t, int i) {
            check_index(i, 1, 3);
            return t.Value(i);
          },
          py::arg("theIndex"))
      .def("Get", [](const Poly_Triangle& t) {
        int a = 0, b = 0, c = 0;
        t.Get(a, b, c);
        return py::make_tuple(a, b, c);
      });

  py::class_<Poly_Triangulation, H<Poly_Triangulation>>(m, "Poly_Triangulation")
      .def(py::init([]() { return new Poly_Triangulation(); }))
      .def(py::init([](int nodes, int tris, bool uv, bool normals) {
             return new Poly_Triangulation(nodes, tris, uv, normals);
           }),
           py::arg("theNbNodes"), py::arg("theNbTriangles"), py::arg("theHasUVNodes"), py::arg("theHasNormals") = false)
      .def("Copy", [](const Poly_Triangulation& t) { return t.Copy(); })
      .def("Deflection", [](const Poly_Triangulation& t) { return t.Deflection(); })
      .def(
          "Deflection", [](Poly_Triangulation& t, double d) { t.Deflection(d); }, py::arg("theDeflection"))
      .def("Clear", [](Poly_Triangulation& t) { t.Clear(); })
      .def("HasGeometry", [](const Poly_Triangulation& t) { return t.HasGeometry(); })
      .def("NbNodes", [](const Poly_Triangulation& t) { return t.NbNodes(); })
      .def("NbTriangles", [](const Poly_Triangulation& t) { return t.NbTriangles(); })
      .def("HasUVNodes", [](const Poly_Triangulation& t) { return t.HasUVNodes(); })
      .def("HasNormals", [](const Poly_Triangulation& t) { return t.HasNormals(); })
      .def(
          "Node",
          [](const Poly_Triangulation& t, int i) {
            check_index(i, 1, t.NbNodes());
            return t.Node(i);
          },
          py::arg("theIndex"))
      .def(
          "SetNode",
          [](Poly_Triangulation& t, int i, const gp_Pnt& p) {
            check_index(i, 1, t.NbNodes());
            t.SetNode(i, p);
          },
          py::arg("theIndex"), py::arg("thePnt"))
      .def(
          "UVNode",
          [](const Poly_Triangulation& t, int i) {
            check_index(i, 1, t.NbNodes());
            return t.UVNode(i);
          },
          py::arg("theIndex"))
      .def(
          "SetUVNode",
          [](Poly_Triangulation& t, int i, const gp_Pnt2d& p) {
            check_index(i, 1, t.NbNodes());
            t.SetUVNode(i, p);
          },
          py::arg("theIndex"), py::arg("thePnt"))
      .def(
          "Triangle",
          [](const Poly_Triangulation& t, int i) {
            check_index(i, 1, t.NbTriangles());
            return t.Triangle(i);
          },
          py::arg("theIndex"))
      .def(
          "SetTriangle",
          [](Poly_Triangulation& t, int i, const Poly_Triangle& tri) {
            check_index(i, 1, t.NbTriangles());
            t.SetTriangle(i, tri);
          },
          py::arg("theIndex"), py::arg("theTriangle"))
      .def(
          "Normal",
          [](const Poly_Triangulation& t, int i) {
            check_index(i, 1, t.NbNodes());
            if (!t.HasNormals())
              throw Standard_NullObject("Poly_Triangulation::Normal: no normals");
            return t.Normal(i);
          },
          py::arg("theIndex"))
      .def(
          "SetNormal",
          [](Poly_Triangulation& t, int i, const gp_Dir& d) {
            check_index(i, 1, t.NbNodes());
            t.SetNormal(i, d);
          },
          py::arg("theIndex"), py::arg("theNormal"))
      .def("AddNormals", [](Poly_Triangulation& t) { t.AddNormals(); })
      .def("RemoveNormals", [](Poly_Triangulation& t) { t.RemoveNormals(); })
      .def("AddUVNodes", [](Poly_Triangulation& t) { t.AddUVNodes(); })
      .def("RemoveUVNodes", [](Poly_Triangulation& t) { t.RemoveUVNodes(); })
      .def("ComputeNormals", [](Poly_Triangulation& t) { t.ComputeNormals(); });

  // ---- ShapeAnalysis_ShapeTolerance
  // ----------------------------------------------------------------------------------
  py::class_<ShapeAnalysis_ShapeTolerance>(m, "ShapeAnalysis_ShapeTolerance")
      .def(py::init<>())
      .def(
          "Tolerance",
          [](ShapeAnalysis_ShapeTolerance& a, const TopoDS_Shape& s, int mode, TopAbs_ShapeEnum t) {
            return a.Tolerance(s, mode, t);
          },
          py::arg("shape"), py::arg("mode"), py::arg("type") = TopAbs_SHAPE)
      .def("InitTolerance", [](ShapeAnalysis_ShapeTolerance& a) { a.InitTolerance(); })
      .def(
          "AddTolerance",
          [](ShapeAnalysis_ShapeTolerance& a, const TopoDS_Shape& s, TopAbs_ShapeEnum t) { a.AddTolerance(s, t); },
          py::arg("shape"), py::arg("type") = TopAbs_SHAPE)
      .def(
          "GlobalTolerance", [](const ShapeAnalysis_ShapeTolerance& a, int mode) { return a.GlobalTolerance(mode); },
          py::arg("mode"));

  // ---- BRepTools (the stream Write_s/Read_s are added by the step file on this same class)
  // -------------------------------
  py::class_<BRepTools>(m, "BRepTools")
      .def_static(
          "OuterWire_s", [](const TopoDS_Face& f) { return BRepTools::OuterWire(f); }, py::arg("F"))
      .def_static(
          "UVBounds_s",
          [](const TopoDS_Face& f) {
            double u0 = 0.0, u1 = 0.0, v0 = 0.0, v1 = 0.0;
            BRepTools::UVBounds(f, u0, u1, v0, v1);
            return py::make_tuple(u0, u1, v0, v1);
          },
          py::arg("F"))
      .def_static(
          "UVBounds_s",
          [](const TopoDS_Face& f, const TopoDS_Wire& w) {
            double u0 = 0.0, u1 = 0.0, v0 = 0.0, v1 = 0.0;
            BRepTools::UVBounds(f, w, u0, u1, v0, v1);
            return py::make_tuple(u0, u1, v0, v1);
          },
          py::arg("F"), py::arg("W"))
      .def_static(
          "UVBounds_s",
          [](const TopoDS_Face& f, const TopoDS_Edge& e) {
            double u0 = 0.0, u1 = 0.0, v0 = 0.0, v1 = 0.0;
            BRepTools::UVBounds(f, e, u0, u1, v0, v1);
            return py::make_tuple(u0, u1, v0, v1);
          },
          py::arg("F"), py::arg("E"))
      .def_static(
          "Clean_s", [](const TopoDS_Shape& s, bool force) { BRepTools::Clean(s, force); }, py::arg("theShape"),
          py::arg("theForce") = false);

  py::class_<BRepTools_WireExplorer>(m, "BRepTools_WireExplorer")
      .def(py::init<>())
      .def(py::init<const TopoDS_Wire&>(), py::arg("W"))
      .def(py::init<const TopoDS_Wire&, const TopoDS_Face&>(), py::arg("W"), py::arg("F"))
      .def(
          "Init", [](BRepTools_WireExplorer& e, const TopoDS_Wire& w) { e.Init(w); }, py::arg("W"))
      .def(
          "Init", [](BRepTools_WireExplorer& e, const TopoDS_Wire& w, const TopoDS_Face& f) { e.Init(w, f); },
          py::arg("W"), py::arg("F"))
      .def(
          "Init",
          [](BRepTools_WireExplorer& e, const TopoDS_Wire& w, const TopoDS_Face& f, double u0, double u1, double v0,
             double v1) { e.Init(w, f, u0, u1, v0, v1); },
          py::arg("W"), py::arg("F"), py::arg("UMin"), py::arg("UMax"), py::arg("VMin"), py::arg("VMax"))
      .def("More", [](const BRepTools_WireExplorer& e) { return e.More(); })
      .def("Next", [](BRepTools_WireExplorer& e) { e.Next(); })
      .def("Current", [](const BRepTools_WireExplorer& e) { return e.Current(); })
      .def("Orientation", [](const BRepTools_WireExplorer& e) { return e.Orientation(); })
      .def("CurrentVertex", [](const BRepTools_WireExplorer& e) { return e.CurrentVertex(); })
      .def("Clear", [](BRepTools_WireExplorer& e) { e.Clear(); });

  // ---- BRepCheck ---------------------------------------------------------------------------------------------------
  py::class_<BRepCheck_Analyzer>(m, "BRepCheck_Analyzer")
      .def(py::init<const TopoDS_Shape&, bool, bool, bool>(), py::arg("S"), py::arg("GeomControls") = true,
           py::arg("theIsParallel") = false, py::arg("theIsExact") = false)
      .def(
          "Init", [](BRepCheck_Analyzer& a, const TopoDS_Shape& s, bool geom) { a.Init(s, geom); }, py::arg("S"),
          py::arg("GeomControls") = true)
      .def(
          "SetExactMethod", [](BRepCheck_Analyzer& a, bool v) { a.SetExactMethod(v); }, py::arg("theIsExact"))
      .def("IsExactMethod", [](BRepCheck_Analyzer& a) { return a.IsExactMethod(); })
      .def(
          "SetParallel", [](BRepCheck_Analyzer& a, bool v) { a.SetParallel(v); }, py::arg("theIsParallel"))
      .def("IsParallel", [](BRepCheck_Analyzer& a) { return a.IsParallel(); })
      .def(
          "IsValid", [](const BRepCheck_Analyzer& a, const TopoDS_Shape& s) { return a.IsValid(s); }, py::arg("S"))
      .def("IsValid", [](const BRepCheck_Analyzer& a) { return a.IsValid(); });

  py::class_<BRepCheck_Result, H<BRepCheck_Result>>(m, "BRepCheck_Result")
      .def("Minimum", [](BRepCheck_Result& r) { r.Minimum(); })
      .def("Blind", [](BRepCheck_Result& r) { r.Blind(); })
      .def("InContext", [](BRepCheck_Result& r, const TopoDS_Shape& s) { r.InContext(s); }, py::arg("ContextShape"));
  py::class_<BRepCheck_Shell, H<BRepCheck_Shell>, BRepCheck_Result>(m, "BRepCheck_Shell")
      .def(py::init([](const TopoDS_Shell& s) { return new BRepCheck_Shell(s); }), py::arg("S"))
      .def(
          "Closed", [](BRepCheck_Shell& c, bool update) { return c.Closed(update); }, py::arg("Update") = false)
      .def(
          "Orientation", [](BRepCheck_Shell& c, bool update) { return c.Orientation(update); },
          py::arg("Update") = false)
      .def("SetUnorientable", [](BRepCheck_Shell& c) { c.SetUnorientable(); })
      .def("IsUnorientable", [](const BRepCheck_Shell& c) { return c.IsUnorientable(); });
}

}  // namespace scad::pybind::occt
