// gp_*, the topology enums, TopLoc_Location, TopoDS_*, TopExp, TopTools_*, Precision, BRep_Tool, BRep_Builder.
#include <BRepAdaptor_Curve.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <GeomAbs_Shape.hxx>
#include <Poly_Triangulation.hxx>
#include <Precision.hxx>
#include <Standard_Version.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopAbs_State.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_FormatVersion.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListIteratorOfListOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Builder.hxx>
#include <TopoDS_CompSolid.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Elips.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <gp_XYZ.hxx>

#include "occt.hpp"

namespace scad::pybind::occt {

namespace {

template <class T>
py::tuple coord3(const T& v) {
  return py::make_tuple(v.X(), v.Y(), v.Z());
}

// A TopoDS_Shape as the Python class of its type (OCP hands the most derived class back from TopoDS.*_s casts and
// from explorers only as TopoDS_Shape; callers cast explicitly).
template <class Cls>
void shape_members(Cls& cls) {
  cls.def("IsNull", &TopoDS_Shape::IsNull)
      .def("Nullify", &TopoDS_Shape::Nullify)
      .def("ShapeType", &TopoDS_Shape::ShapeType)
      .def("Orientation", [](const TopoDS_Shape& s) { return s.Orientation(); })
      .def("Orientation", [](TopoDS_Shape& s, TopAbs_Orientation o) { s.Orientation(o); })
      .def("Location", [](const TopoDS_Shape& s) { return s.Location(); })
      .def(
          "Location", [](TopoDS_Shape& s, const TopLoc_Location& l, bool raise) { s.Location(l, raise); },
          py::arg("Loc"), py::arg("theRaiseExc") = true)
      .def(
          "Located", [](const TopoDS_Shape& s, const TopLoc_Location& l, bool raise) { return s.Located(l, raise); },
          py::arg("theLoc"), py::arg("theRaiseExc") = true)
      .def(
          "Moved", [](const TopoDS_Shape& s, const TopLoc_Location& l, bool raise) { return s.Moved(l, raise); },
          py::arg("thePosition"), py::arg("theRaiseExc") = true)
      .def("Oriented", &TopoDS_Shape::Oriented)
      .def("Reversed", &TopoDS_Shape::Reversed)
      .def("Reverse", &TopoDS_Shape::Reverse)
      .def("Complemented", &TopoDS_Shape::Complemented)
      .def("Complement", &TopoDS_Shape::Complement)
      .def("EmptyCopied", &TopoDS_Shape::EmptyCopied)
      .def("IsSame", &TopoDS_Shape::IsSame)
      .def("IsEqual", &TopoDS_Shape::IsEqual)
      .def("IsPartner", &TopoDS_Shape::IsPartner)
      .def("Free", [](const TopoDS_Shape& s) { return s.Free(); })
      .def("Closed", [](const TopoDS_Shape& s) { return s.Closed(); })
      .def("Closed", [](TopoDS_Shape& s, bool v) { s.Closed(v); })
      .def("Convex", [](const TopoDS_Shape& s) { return s.Convex(); })
      .def("Checked", [](const TopoDS_Shape& s) { return s.Checked(); })
      .def("Infinite", [](const TopoDS_Shape& s) { return s.Infinite(); })
      .def("Modified", [](const TopoDS_Shape& s) { return s.Modified(); })
      .def("Orientable", [](const TopoDS_Shape& s) { return s.Orientable(); })
      .def(
          "HashCode",
          [](const TopoDS_Shape& s, int upper) {
            return static_cast<long>(std::hash<TopoDS_Shape>{}(s) % static_cast<std::size_t>(upper));
          },
          py::arg("theUpperBound") = 2147483647)
      .def(
          "__eq__", [](const TopoDS_Shape& a, const TopoDS_Shape& b) { return a.IsEqual(b); }, py::is_operator())
      .def("__hash__", [](const TopoDS_Shape& s) { return std::hash<TopoDS_Shape>{}(s); });
}

template <class Sub>
void sub_shape(py::module_& m, const char* name) {
  py::class_<Sub, TopoDS_Shape>(m, name).def(py::init<>());
}

}  // namespace

void bind_core(py::module_& m) {
  m.attr("OCC_VERSION_COMPLETE") =
      OCC_VERSION_COMPLETE;  // "7.9.3": what OCP calls its version, minus its own build number
  // ---- enums -------------------------------------------------------------------------------------------------
  py::enum_<TopAbs_ShapeEnum>(m, "TopAbs_ShapeEnum")
      .value("TopAbs_COMPOUND", TopAbs_COMPOUND)
      .value("TopAbs_COMPSOLID", TopAbs_COMPSOLID)
      .value("TopAbs_SOLID", TopAbs_SOLID)
      .value("TopAbs_SHELL", TopAbs_SHELL)
      .value("TopAbs_FACE", TopAbs_FACE)
      .value("TopAbs_WIRE", TopAbs_WIRE)
      .value("TopAbs_EDGE", TopAbs_EDGE)
      .value("TopAbs_VERTEX", TopAbs_VERTEX)
      .value("TopAbs_SHAPE", TopAbs_SHAPE)
      .export_values();
  py::enum_<TopAbs_Orientation>(m, "TopAbs_Orientation")
      .value("TopAbs_FORWARD", TopAbs_FORWARD)
      .value("TopAbs_REVERSED", TopAbs_REVERSED)
      .value("TopAbs_INTERNAL", TopAbs_INTERNAL)
      .value("TopAbs_EXTERNAL", TopAbs_EXTERNAL)
      .export_values();
  py::enum_<TopAbs_State>(m, "TopAbs_State")
      .value("TopAbs_IN", TopAbs_IN)
      .value("TopAbs_OUT", TopAbs_OUT)
      .value("TopAbs_ON", TopAbs_ON)
      .value("TopAbs_UNKNOWN", TopAbs_UNKNOWN)
      .export_values();
  py::enum_<GeomAbs_Shape>(m, "GeomAbs_Shape")
      .value("GeomAbs_C0", GeomAbs_C0)
      .value("GeomAbs_G1", GeomAbs_G1)
      .value("GeomAbs_C1", GeomAbs_C1)
      .value("GeomAbs_G2", GeomAbs_G2)
      .value("GeomAbs_C2", GeomAbs_C2)
      .value("GeomAbs_C3", GeomAbs_C3)
      .value("GeomAbs_CN", GeomAbs_CN)
      .export_values();
  py::enum_<TopTools_FormatVersion>(m, "TopTools_FormatVersion")
      .value("TopTools_FormatVersion_VERSION_1", TopTools_FormatVersion_VERSION_1)
      .value("TopTools_FormatVersion_VERSION_2", TopTools_FormatVersion_VERSION_2)
      .value("TopTools_FormatVersion_VERSION_3", TopTools_FormatVersion_VERSION_3)
      .export_values();

  // ---- gp ----------------------------------------------------------------------------------------------------
  py::class_<gp_XYZ>(m, "gp_XYZ")
      .def(py::init<>())
      .def(py::init<double, double, double>())
      .def("X", &gp_XYZ::X)
      .def("Y", &gp_XYZ::Y)
      .def("Z", &gp_XYZ::Z)
      .def("Coord", [](const gp_XYZ& v) { return coord3(v); });

  py::class_<gp_Pnt2d>(m, "gp_Pnt2d")
      .def(py::init<>())
      .def(py::init<double, double>())
      .def("X", &gp_Pnt2d::X)
      .def("Y", &gp_Pnt2d::Y)
      .def("Coord", [](const gp_Pnt2d& p) { return py::make_tuple(p.X(), p.Y()); })
      .def("Distance", &gp_Pnt2d::Distance);

  py::class_<gp_Pnt>(m, "gp_Pnt")
      .def(py::init<>())
      .def(py::init<double, double, double>(), py::arg("Xp"), py::arg("Yp"), py::arg("Zp"))
      .def("X", &gp_Pnt::X)
      .def("Y", &gp_Pnt::Y)
      .def("Z", &gp_Pnt::Z)
      .def("SetX", &gp_Pnt::SetX)
      .def("SetY", &gp_Pnt::SetY)
      .def("SetZ", &gp_Pnt::SetZ)
      .def("SetCoord", [](gp_Pnt& p, double x, double y, double z) { p.SetCoord(x, y, z); })
      .def("Coord", [](const gp_Pnt& p) { return coord3(p); })
      .def("XYZ", [](const gp_Pnt& p) { return p.XYZ(); })
      .def("Distance", &gp_Pnt::Distance)
      .def("SquareDistance", &gp_Pnt::SquareDistance)
      .def("IsEqual", &gp_Pnt::IsEqual)
      .def("Translate", [](gp_Pnt& p, const gp_Vec& v) { p.Translate(v); })
      .def("Translated", [](const gp_Pnt& p, const gp_Vec& v) { return p.Translated(v); })
      .def("Transform", &gp_Pnt::Transform)
      .def("Transformed", &gp_Pnt::Transformed)
      .def("__repr__", [](const gp_Pnt& p) {
        return "gp_Pnt(" + std::to_string(p.X()) + ", " + std::to_string(p.Y()) + ", " + std::to_string(p.Z()) + ")";
      });

  py::class_<gp_Vec>(m, "gp_Vec")
      .def(py::init<>())
      .def(py::init<double, double, double>())
      .def(py::init<const gp_Pnt&, const gp_Pnt&>())
      .def(py::init<const gp_Dir&>())
      .def("X", &gp_Vec::X)
      .def("Y", &gp_Vec::Y)
      .def("Z", &gp_Vec::Z)
      .def("SetCoord", [](gp_Vec& v, double x, double y, double z) { v.SetCoord(x, y, z); })
      .def("Coord", [](const gp_Vec& v) { return coord3(v); })
      .def("Magnitude", &gp_Vec::Magnitude)
      .def("SquareMagnitude", &gp_Vec::SquareMagnitude)
      .def("Normalize", &gp_Vec::Normalize)
      .def("Normalized", &gp_Vec::Normalized)
      .def("Multiplied", [](const gp_Vec& v, double s) { return v.Multiplied(s); })
      .def("Multiply", [](gp_Vec& v, double s) { v.Multiply(s); })
      .def("Scaled", [](const gp_Vec& v, double s) { return v.Multiplied(s); })
      .def("Added", [](const gp_Vec& v, const gp_Vec& o) { return v.Added(o); })
      .def("Subtracted", [](const gp_Vec& v, const gp_Vec& o) { return v.Subtracted(o); })
      .def("Dot", &gp_Vec::Dot)
      .def("Crossed", [](const gp_Vec& v, const gp_Vec& o) { return v.Crossed(o); })
      .def("Reverse", &gp_Vec::Reverse)
      .def("Reversed", &gp_Vec::Reversed)
      .def("Angle", &gp_Vec::Angle)
      .def("IsParallel", &gp_Vec::IsParallel)
      .def("Transform", &gp_Vec::Transform)
      .def("Transformed", &gp_Vec::Transformed);

  py::class_<gp_Dir>(m, "gp_Dir")
      .def(py::init<>())
      .def(py::init<double, double, double>())
      .def(py::init<const gp_Vec&>())
      .def("X", &gp_Dir::X)
      .def("Y", &gp_Dir::Y)
      .def("Z", &gp_Dir::Z)
      .def("Coord", [](const gp_Dir& d) { return coord3(d); })
      .def("Reverse", &gp_Dir::Reverse)
      .def("Reversed", &gp_Dir::Reversed)
      .def("Dot", &gp_Dir::Dot)
      .def("Crossed", [](const gp_Dir& d, const gp_Dir& o) { return d.Crossed(o); })
      .def("Angle", &gp_Dir::Angle)
      .def("IsParallel", &gp_Dir::IsParallel)
      .def("Transform", &gp_Dir::Transform)
      .def("Transformed", &gp_Dir::Transformed);

  py::class_<gp_Ax1>(m, "gp_Ax1")
      .def(py::init<>())
      .def(py::init<const gp_Pnt&, const gp_Dir&>())
      .def("Location", [](const gp_Ax1& a) { return a.Location(); })
      .def("Direction", [](const gp_Ax1& a) { return a.Direction(); });

  py::class_<gp_Ax2>(m, "gp_Ax2")
      .def(py::init<>())
      .def(py::init<const gp_Pnt&, const gp_Dir&>())
      .def(py::init<const gp_Pnt&, const gp_Dir&, const gp_Dir&>())
      .def("Location", [](const gp_Ax2& a) { return a.Location(); })
      .def("Direction", [](const gp_Ax2& a) { return a.Direction(); })
      .def("XDirection", [](const gp_Ax2& a) { return a.XDirection(); })
      .def("YDirection", [](const gp_Ax2& a) { return a.YDirection(); })
      .def("Axis", [](const gp_Ax2& a) { return a.Axis(); });

  py::class_<gp_Ax3>(m, "gp_Ax3")
      .def(py::init<>())
      .def(py::init<const gp_Pnt&, const gp_Dir&>())
      .def(py::init<const gp_Pnt&, const gp_Dir&, const gp_Dir&>())
      .def("Location", [](const gp_Ax3& a) { return a.Location(); })
      .def("Direction", [](const gp_Ax3& a) { return a.Direction(); })
      .def("XDirection", [](const gp_Ax3& a) { return a.XDirection(); })
      .def("YDirection", [](const gp_Ax3& a) { return a.YDirection(); })
      .def("Axis", [](const gp_Ax3& a) { return a.Axis(); });

  py::class_<gp_Trsf>(m, "gp_Trsf")
      .def(py::init<>())
      .def("SetRotation", [](gp_Trsf& t, const gp_Ax1& a, double angle) { t.SetRotation(a, angle); })
      .def("SetTranslation", [](gp_Trsf& t, const gp_Vec& v) { t.SetTranslation(v); })
      .def("SetScale", [](gp_Trsf& t, const gp_Pnt& p, double s) { t.SetScale(p, s); })
      .def("SetMirror", [](gp_Trsf& t, const gp_Ax1& a) { t.SetMirror(a); })
      .def("SetValues", [](gp_Trsf& t, double a11, double a12, double a13, double a14, double a21, double a22,
                           double a23, double a24, double a31, double a32, double a33,
                           double a34) { t.SetValues(a11, a12, a13, a14, a21, a22, a23, a24, a31, a32, a33, a34); })
      .def("TranslationPart", [](const gp_Trsf& t) { return t.TranslationPart(); })
      .def("Value", [](const gp_Trsf& t, int r, int c) { return t.Value(r, c); })
      .def("ScaleFactor", &gp_Trsf::ScaleFactor)
      .def("Inverted", &gp_Trsf::Inverted)
      .def("Multiplied", [](const gp_Trsf& t, const gp_Trsf& o) { return t.Multiplied(o); })
      .def("IsNegative", &gp_Trsf::IsNegative);

  py::class_<gp_Pln>(m, "gp_Pln")
      .def(py::init<>())
      .def(py::init<const gp_Pnt&, const gp_Dir&>())
      .def(py::init<const gp_Ax3&>())
      .def("Axis", [](const gp_Pln& p) { return p.Axis(); })
      .def("Location", [](const gp_Pln& p) { return p.Location(); })
      .def("Position", [](const gp_Pln& p) { return p.Position(); })
      .def("Distance", [](const gp_Pln& p, const gp_Pnt& q) { return p.Distance(q); });

  py::class_<gp_Lin>(m, "gp_Lin")
      .def(py::init<>())
      .def(py::init<const gp_Pnt&, const gp_Dir&>())
      .def("Direction", [](const gp_Lin& l) { return l.Direction(); })
      .def("Location", [](const gp_Lin& l) { return l.Location(); });

  py::class_<gp_Circ>(m, "gp_Circ")
      .def(py::init<>())
      .def(py::init<const gp_Ax2&, double>())
      .def("Axis", [](const gp_Circ& c) { return c.Axis(); })
      .def("Location", [](const gp_Circ& c) { return c.Location(); })
      .def("Position", [](const gp_Circ& c) { return c.Position(); })
      .def("Radius", &gp_Circ::Radius)
      .def("XAxis", [](const gp_Circ& c) { return c.XAxis(); })
      .def("YAxis", [](const gp_Circ& c) { return c.YAxis(); });

  py::class_<gp_Elips>(m, "gp_Elips")
      .def(py::init<>())
      .def(py::init<const gp_Ax2&, double, double>())
      .def("Axis", [](const gp_Elips& e) { return e.Axis(); })
      .def("Location", [](const gp_Elips& e) { return e.Location(); })
      .def("Position", [](const gp_Elips& e) { return e.Position(); })
      .def("MajorRadius", &gp_Elips::MajorRadius)
      .def("MinorRadius", &gp_Elips::MinorRadius)
      .def("XAxis", [](const gp_Elips& e) { return e.XAxis(); })
      .def("YAxis", [](const gp_Elips& e) { return e.YAxis(); });

  py::class_<gp_Cylinder>(m, "gp_Cylinder")
      .def(py::init<>())
      .def(py::init<const gp_Ax3&, double>())
      .def("Axis", [](const gp_Cylinder& c) { return c.Axis(); })
      .def("Location", [](const gp_Cylinder& c) { return c.Location(); })
      .def("Position", [](const gp_Cylinder& c) { return c.Position(); })
      .def("Radius", &gp_Cylinder::Radius);

  // ---- TopLoc / TopoDS ---------------------------------------------------------------------------------------
  py::class_<TopLoc_Location>(m, "TopLoc_Location")
      .def(py::init<>())
      .def(py::init<const gp_Trsf&>())
      .def("IsIdentity", &TopLoc_Location::IsIdentity)
      .def("Transformation", [](const TopLoc_Location& l) { return l.Transformation(); })
      .def("Inverted", &TopLoc_Location::Inverted)
      .def("Multiplied", &TopLoc_Location::Multiplied)
      .def("IsEqual", &TopLoc_Location::IsEqual);

  py::class_<TopoDS_Shape> shape(m, "TopoDS_Shape");
  shape.def(py::init<>());
  shape_members(shape);
  sub_shape<TopoDS_Vertex>(m, "TopoDS_Vertex");
  sub_shape<TopoDS_Edge>(m, "TopoDS_Edge");
  sub_shape<TopoDS_Wire>(m, "TopoDS_Wire");
  sub_shape<TopoDS_Face>(m, "TopoDS_Face");
  sub_shape<TopoDS_Shell>(m, "TopoDS_Shell");
  sub_shape<TopoDS_Solid>(m, "TopoDS_Solid");
  sub_shape<TopoDS_CompSolid>(m, "TopoDS_CompSolid");
  sub_shape<TopoDS_Compound>(m, "TopoDS_Compound");

  // `TopoDS.Face_s(shape)`: the shape as its own type.
  struct TopoDSCasts {};  // `TopoDS` is a namespace in OCCT; OCP presents its casts as a class
  py::class_<TopoDSCasts>(m, "TopoDS")
      .def_static("Vertex_s", [](const TopoDS_Shape& s) { return TopoDS::Vertex(s); })
      .def_static("Edge_s", [](const TopoDS_Shape& s) { return TopoDS::Edge(s); })
      .def_static("Wire_s", [](const TopoDS_Shape& s) { return TopoDS::Wire(s); })
      .def_static("Face_s", [](const TopoDS_Shape& s) { return TopoDS::Face(s); })
      .def_static("Shell_s", [](const TopoDS_Shape& s) { return TopoDS::Shell(s); })
      .def_static("Solid_s", [](const TopoDS_Shape& s) { return TopoDS::Solid(s); })
      .def_static("CompSolid_s", [](const TopoDS_Shape& s) { return TopoDS::CompSolid(s); })
      .def_static("Compound_s", [](const TopoDS_Shape& s) { return TopoDS::Compound(s); });

  py::class_<TopoDS_Builder>(m, "TopoDS_Builder")
      .def(py::init<>())
      .def("MakeCompound", [](const TopoDS_Builder& b, TopoDS_Compound& c) { b.MakeCompound(c); })
      .def("MakeCompSolid", [](const TopoDS_Builder& b, TopoDS_CompSolid& c) { b.MakeCompSolid(c); })
      .def("MakeSolid", [](const TopoDS_Builder& b, TopoDS_Solid& s) { b.MakeSolid(s); })
      .def("MakeShell", [](const TopoDS_Builder& b, TopoDS_Shell& s) { b.MakeShell(s); })
      .def("MakeWire", [](const TopoDS_Builder& b, TopoDS_Wire& w) { b.MakeWire(w); })
      .def("Add", [](const TopoDS_Builder& b, TopoDS_Shape& whole, const TopoDS_Shape& part) { b.Add(whole, part); })
      .def("Remove",
           [](const TopoDS_Builder& b, TopoDS_Shape& whole, const TopoDS_Shape& part) { b.Remove(whole, part); });

  // ---- TopExp / TopTools -------------------------------------------------------------------------------------
  py::class_<TopTools_ListOfShape>(m, "TopTools_ListOfShape")
      .def(py::init<>())
      .def("Append", [](TopTools_ListOfShape& l, const TopoDS_Shape& s) { l.Append(s); })
      .def("Prepend", [](TopTools_ListOfShape& l, const TopoDS_Shape& s) { l.Prepend(s); })
      .def("Extent", [](const TopTools_ListOfShape& l) { return l.Extent(); })
      .def("Size", [](const TopTools_ListOfShape& l) { return l.Size(); })
      .def("IsEmpty", [](const TopTools_ListOfShape& l) { return l.IsEmpty(); })
      .def("Clear", [](TopTools_ListOfShape& l) { l.Clear(); })
      .def("First", [](const TopTools_ListOfShape& l) { return l.First(); })
      .def("Last", [](const TopTools_ListOfShape& l) { return l.Last(); })
      .def("__len__", [](const TopTools_ListOfShape& l) { return l.Extent(); })
      .def("__iter__", [](const TopTools_ListOfShape& l) {
        py::list items;
        for (TopTools_ListIteratorOfListOfShape it(l); it.More(); it.Next())
          items.append(it.Value());
        return py::iter(items);
      });

  py::class_<TopTools_IndexedMapOfShape>(m, "TopTools_IndexedMapOfShape")
      .def(py::init<>())
      .def("Add", [](TopTools_IndexedMapOfShape& map, const TopoDS_Shape& s) { return map.Add(s); })
      .def("Contains", [](const TopTools_IndexedMapOfShape& map, const TopoDS_Shape& s) { return map.Contains(s); })
      .def("FindIndex", [](const TopTools_IndexedMapOfShape& map, const TopoDS_Shape& s) { return map.FindIndex(s); })
      .def("FindKey", [](const TopTools_IndexedMapOfShape& map, int i) { return map.FindKey(i); })
      .def("Extent", [](const TopTools_IndexedMapOfShape& map) { return map.Extent(); })
      .def("Size", [](const TopTools_IndexedMapOfShape& map) { return map.Size(); })
      .def("Clear", [](TopTools_IndexedMapOfShape& map) { map.Clear(); })
      .def("__len__", [](const TopTools_IndexedMapOfShape& map) { return map.Extent(); });

  py::class_<TopExp>(m, "TopExp")
      .def_static("MapShapes_s", [](const TopoDS_Shape& s, TopAbs_ShapeEnum t,
                                    TopTools_IndexedMapOfShape& map) { TopExp::MapShapes(s, t, map); })
      .def_static("MapShapes_s",
                  [](const TopoDS_Shape& s, TopTools_IndexedMapOfShape& map) { TopExp::MapShapes(s, map); })
      .def_static(
          "FirstVertex_s", [](const TopoDS_Edge& e, bool cumOri) { return TopExp::FirstVertex(e, cumOri); },
          py::arg("E"), py::arg("CumOri") = false)
      .def_static(
          "LastVertex_s", [](const TopoDS_Edge& e, bool cumOri) { return TopExp::LastVertex(e, cumOri); }, py::arg("E"),
          py::arg("CumOri") = false)
      .def_static(
          "Vertices_s",
          [](const TopoDS_Edge& e, TopoDS_Vertex& v1, TopoDS_Vertex& v2, bool cumOri) {
            TopExp::Vertices(e, v1, v2, cumOri);
          },
          py::arg("E"), py::arg("Vfirst"), py::arg("Vlast"), py::arg("CumOri") = false);

  py::class_<TopExp_Explorer>(m, "TopExp_Explorer")
      .def(py::init<>())
      .def(py::init<const TopoDS_Shape&, TopAbs_ShapeEnum, TopAbs_ShapeEnum>(), py::arg("S"), py::arg("ToFind"),
           py::arg("ToAvoid") = TopAbs_SHAPE)
      .def(
          "Init",
          [](TopExp_Explorer& e, const TopoDS_Shape& s, TopAbs_ShapeEnum find, TopAbs_ShapeEnum avoid) {
            e.Init(s, find, avoid);
          },
          py::arg("S"), py::arg("ToFind"), py::arg("ToAvoid") = TopAbs_SHAPE)
      .def("More", &TopExp_Explorer::More)
      .def("Next", &TopExp_Explorer::Next)
      .def("Current", [](const TopExp_Explorer& e) { return e.Current(); })
      .def("Value", [](const TopExp_Explorer& e) { return e.Current(); })
      .def("Depth", &TopExp_Explorer::Depth)
      .def("ReInit", &TopExp_Explorer::ReInit)
      .def("Clear", &TopExp_Explorer::Clear);

  // ---- Precision / BRep ---------------------------------------------------------------------------------------
  py::class_<Precision>(m, "Precision")
      .def_static("Confusion_s", []() { return Precision::Confusion(); })
      .def_static("Angular_s", []() { return Precision::Angular(); })
      .def_static("Approximation_s", []() { return Precision::Approximation(); })
      .def_static("Intersection_s", []() { return Precision::Intersection(); })
      .def_static("PConfusion_s", []() { return Precision::PConfusion(); })
      .def_static("Infinite_s", []() { return Precision::Infinite(); })
      .def_static("IsInfinite_s", [](double v) { return Precision::IsInfinite(v); });

  py::class_<BRep_Builder, TopoDS_Builder>(m, "BRep_Builder")
      .def(py::init<>())
      .def("MakeEdge", [](const BRep_Builder& b, TopoDS_Edge& e) { b.MakeEdge(e); })
      .def("MakeFace", [](const BRep_Builder& b, TopoDS_Face& f) { b.MakeFace(f); })
      .def("MakeVertex", [](const BRep_Builder& b, TopoDS_Vertex& v) { b.MakeVertex(v); })
      .def("MakeVertex",
           [](const BRep_Builder& b, TopoDS_Vertex& v, const gp_Pnt& p, double tol) { b.MakeVertex(v, p, tol); })
      .def("Degenerated", [](const BRep_Builder& b, const TopoDS_Edge& e, bool d) { b.Degenerated(e, d); })
      .def("UpdateVertex", [](const BRep_Builder& b, const TopoDS_Vertex& v, const gp_Pnt& p,
                              double tol) { b.UpdateVertex(v, p, tol); })
      .def("UpdateEdge", [](const BRep_Builder& b, const TopoDS_Edge& e, double tol) { b.UpdateEdge(e, tol); })
      .def("UpdateFace", [](const BRep_Builder& b, const TopoDS_Face& f, double tol) { b.UpdateFace(f, tol); });

  py::class_<BRep_Tool>(m, "BRep_Tool")
      .def_static("Pnt_s", [](const TopoDS_Vertex& v) { return BRep_Tool::Pnt(v); })
      .def_static("Tolerance_s", [](const TopoDS_Vertex& v) { return BRep_Tool::Tolerance(v); })
      .def_static("Tolerance_s", [](const TopoDS_Edge& e) { return BRep_Tool::Tolerance(e); })
      .def_static("Tolerance_s", [](const TopoDS_Face& f) { return BRep_Tool::Tolerance(f); })
      .def_static("Degenerated_s", [](const TopoDS_Edge& e) { return BRep_Tool::Degenerated(e); })
      .def_static("IsClosed_s", [](const TopoDS_Shape& s) { return BRep_Tool::IsClosed(s); })
      .def_static("IsClosed_s", [](const TopoDS_Edge& e, const TopoDS_Face& f) { return BRep_Tool::IsClosed(e, f); })
      .def_static("Range_s",
                  [](const TopoDS_Edge& e, const TopoDS_Face& f) {
                    double a = 0.0, b = 0.0;
                    BRep_Tool::Range(e, f, a, b);
                    return py::make_tuple(a, b);
                  })
      .def_static("Range_s",
                  [](const TopoDS_Edge& e) {
                    double a = 0.0, b = 0.0;
                    BRep_Tool::Range(e, a, b);
                    return py::make_tuple(a, b);
                  })
      .def_static("Surface_s", [](const TopoDS_Face& f) { return BRep_Tool::Surface(f); })
      // OCP returns the curve alone: the parameter range is read with Range_s
      .def_static(
          "Curve_s",
          [](const TopoDS_Edge& e, double, double) {
            double a = 0.0, b = 0.0;
            return BRep_Tool::Curve(e, a, b);
          },
          py::arg("E"), py::arg("First") = 0.0, py::arg("Last") = 0.0)
      .def_static(
          "CurveOnSurface_s",
          [](const TopoDS_Edge& e, const TopoDS_Face& f, double, double) {
            double a = 0.0, b = 0.0;
            return BRep_Tool::CurveOnSurface(e, f, a, b);
          },
          py::arg("E"), py::arg("F"), py::arg("First") = 0.0, py::arg("Last") = 0.0)
      .def_static("Continuity_s", [](const TopoDS_Edge& e, const TopoDS_Face& f1,
                                     const TopoDS_Face& f2) { return BRep_Tool::Continuity(e, f1, f2); })
      .def_static("Triangulation_s",
                  [](const TopoDS_Face& f, TopLoc_Location& loc) { return BRep_Tool::Triangulation(f, loc); })
      .def_static("Triangulation_s", [](const TopoDS_Face& f, TopLoc_Location& loc, int purpose) {
        return BRep_Tool::Triangulation(f, loc, static_cast<Poly_MeshPurpose>(purpose));
      });
}

}  // namespace scad::pybind::occt
