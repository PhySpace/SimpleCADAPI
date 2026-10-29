// Construction: booleans, shape builders, primitives, fillets, transform/copy, meshing, HLR, shape upgrade.
#include <BOPAlgo_GlueEnum.hxx>
#include <BRepAlgoAPI_Algo.hxx>
#include <StlAPI_Writer.hxx>
#include <BRepAlgoAPI_BooleanOperation.hxx>
#include <BRepAlgoAPI_BuilderAlgo.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepBuilderAPI_Command.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeShape.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_ModifyShape.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepFilletAPI_LocalOperation.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeSweep.hxx>
#include <GeomAbs_Shape.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <HLRAlgo_Projector.hxx>
#include <HLRBRep_Algo.hxx>
#include <HLRBRep_HLRToShape.hxx>
#include <HLRBRep_InternalAlgo.hxx>
#include <ShapeUpgrade_ShapeDivide.hxx>
#include <ShapeUpgrade_ShapeDivideContinuity.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Elips.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Torus.hxx>
#include <gp_Sphere.hxx>
#include <gp_Cone.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

#include "occt.hpp"

namespace scad::pybind::occt {

namespace {

template <class Op>
void boolean_class(py::module_& m, const char* name) {
  py::class_<Op, BRepAlgoAPI_BooleanOperation>(m, name)
      .def(py::init<>())
      .def(py::init<const TopoDS_Shape&, const TopoDS_Shape&>(), py::arg("S1"), py::arg("S2"));
}

}  // namespace

void bind_algo(py::module_& m) {
  py::enum_<BOPAlgo_GlueEnum>(m, "BOPAlgo_GlueEnum")
      .value("BOPAlgo_GlueOff", BOPAlgo_GlueOff)
      .value("BOPAlgo_GlueShift", BOPAlgo_GlueShift)
      .value("BOPAlgo_GlueFull", BOPAlgo_GlueFull)
      .export_values();
  py::class_<StlAPI_Writer>(m, "StlAPI_Writer")
      .def(py::init<>())
      .def(
          "Write",
          [](StlAPI_Writer& w, const TopoDS_Shape& shape, const std::string& path) {
            return w.Write(shape, path.c_str());
          },
          py::arg("theShape"), py::arg("theFileName"));

  // ---- the builder chain: command -> make-shape -> modify-shape ---------------------------------------------
  py::class_<BRepBuilderAPI_Command>(m, "BRepBuilderAPI_Command").def("IsDone", &BRepBuilderAPI_Command::IsDone);

  py::class_<BRepBuilderAPI_MakeShape, BRepBuilderAPI_Command>(m, "BRepBuilderAPI_MakeShape")
      .def("Build", [](BRepBuilderAPI_MakeShape& op) { op.Build(); })
      .def("Shape", [](BRepBuilderAPI_MakeShape& op) { return op.Shape(); })
      .def("Generated", [](BRepBuilderAPI_MakeShape& op, const TopoDS_Shape& s) { return op.Generated(s); })
      .def("Modified", [](BRepBuilderAPI_MakeShape& op, const TopoDS_Shape& s) { return op.Modified(s); })
      .def("IsDeleted", [](BRepBuilderAPI_MakeShape& op, const TopoDS_Shape& s) { return op.IsDeleted(s); });

  py::class_<BRepBuilderAPI_ModifyShape, BRepBuilderAPI_MakeShape>(m, "BRepBuilderAPI_ModifyShape")
      .def("ModifiedShape", [](BRepBuilderAPI_ModifyShape& op, const TopoDS_Shape& s) { return op.ModifiedShape(s); });

  py::class_<BRepBuilderAPI_Transform, BRepBuilderAPI_ModifyShape>(m, "BRepBuilderAPI_Transform")
      .def(py::init<const gp_Trsf&>())
      .def(py::init<const TopoDS_Shape&, const gp_Trsf&, bool, bool>(), py::arg("S"), py::arg("T"),
           py::arg("Copy") = false, py::arg("CopyMesh") = false)
      .def(
          "Perform",
          [](BRepBuilderAPI_Transform& t, const TopoDS_Shape& s, bool copy, bool copyMesh) {
            t.Perform(s, copy, copyMesh);
          },
          py::arg("S"), py::arg("Copy") = false, py::arg("CopyMesh") = false);

  py::class_<BRepBuilderAPI_Copy, BRepBuilderAPI_ModifyShape>(m, "BRepBuilderAPI_Copy")
      .def(py::init<>())
      .def(py::init<const TopoDS_Shape&, bool, bool>(), py::arg("S"), py::arg("copyGeom") = true,
           py::arg("copyMesh") = false)
      .def(
          "Perform",
          [](BRepBuilderAPI_Copy& c, const TopoDS_Shape& s, bool copyGeom, bool copyMesh) {
            c.Perform(s, copyGeom, copyMesh);
          },
          py::arg("S"), py::arg("copyGeom") = true, py::arg("copyMesh") = false);

  py::class_<BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeShape>(m, "BRepBuilderAPI_MakeVertex")
      .def(py::init<const gp_Pnt&>())
      .def("Vertex", [](BRepBuilderAPI_MakeVertex& v) { return v.Vertex(); });

  py::class_<BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeShape>(m, "BRepBuilderAPI_MakeEdge")
      .def(py::init<>())
      .def(py::init<const TopoDS_Vertex&, const TopoDS_Vertex&>())
      .def(py::init<const gp_Pnt&, const gp_Pnt&>())
      .def(py::init<const gp_Lin&, double, double>())
      .def(py::init<const gp_Circ&>())
      .def(py::init<const gp_Circ&, double, double>())
      .def(py::init<const gp_Elips&>())
      .def(py::init<const gp_Elips&, double, double>())
      .def(py::init<const opencascade::handle<Geom_Curve>&>())
      .def(py::init<const opencascade::handle<Geom_Curve>&, double, double>())
      .def(py::init<const opencascade::handle<Geom_Curve>&, const gp_Pnt&, const gp_Pnt&>())
      .def(py::init<const opencascade::handle<Geom_Curve>&, const TopoDS_Vertex&, const TopoDS_Vertex&>())
      .def("Edge", [](BRepBuilderAPI_MakeEdge& e) { return e.Edge(); })
      .def("Vertex1", [](const BRepBuilderAPI_MakeEdge& e) { return e.Vertex1(); })
      .def("Vertex2", [](const BRepBuilderAPI_MakeEdge& e) { return e.Vertex2(); })
      .def("Error", [](const BRepBuilderAPI_MakeEdge& e) { return static_cast<int>(e.Error()); });

  py::class_<BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeShape>(m, "BRepBuilderAPI_MakeWire")
      .def(py::init<>())
      .def(py::init<const TopoDS_Edge&>())
      .def(py::init<const TopoDS_Edge&, const TopoDS_Edge&>())
      .def(py::init<const TopoDS_Wire&>())
      .def("Add", [](BRepBuilderAPI_MakeWire& w, const TopoDS_Edge& e) { w.Add(e); })
      .def("Add", [](BRepBuilderAPI_MakeWire& w, const TopoDS_Wire& other) { w.Add(other); })
      .def("Wire", [](BRepBuilderAPI_MakeWire& w) { return w.Wire(); })
      .def("Edge", [](const BRepBuilderAPI_MakeWire& w) { return w.Edge(); })
      .def("Vertex", [](const BRepBuilderAPI_MakeWire& w) { return w.Vertex(); })
      .def("Error", [](const BRepBuilderAPI_MakeWire& w) { return static_cast<int>(w.Error()); });

  py::class_<BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeShape>(m, "BRepBuilderAPI_MakeFace")
      .def(py::init<>())
      .def(py::init<const TopoDS_Face&>())
      .def(py::init<const gp_Pln&>())
      .def(py::init<const gp_Cylinder&, double, double, double, double>(), py::arg("C"), py::arg("UMin"),
           py::arg("UMax"), py::arg("VMin"), py::arg("VMax"))
      .def(py::init<const gp_Cone&, double, double, double, double>(), py::arg("C"), py::arg("UMin"), py::arg("UMax"),
           py::arg("VMin"), py::arg("VMax"))
      .def(py::init<const gp_Sphere&, double, double, double, double>(), py::arg("C"), py::arg("UMin"), py::arg("UMax"),
           py::arg("VMin"), py::arg("VMax"))
      .def(py::init<const gp_Torus&, double, double, double, double>(), py::arg("C"), py::arg("UMin"), py::arg("UMax"),
           py::arg("VMin"), py::arg("VMax"))
      .def(py::init<const gp_Pln&, double, double, double, double>(), py::arg("P"), py::arg("UMin"), py::arg("UMax"),
           py::arg("VMin"), py::arg("VMax"))
      .def(py::init<const opencascade::handle<Geom_Surface>&, double, double, double, double, double>(), py::arg("S"),
           py::arg("UMin"), py::arg("UMax"), py::arg("VMin"), py::arg("VMax"), py::arg("TolDegen"))
      .def(py::init<const TopoDS_Wire&, bool>(), py::arg("W"), py::arg("OnlyPlane") = false)
      .def(py::init<const opencascade::handle<Geom_Surface>&, double>(), py::arg("S"), py::arg("TolDegen"))
      .def(py::init<const opencascade::handle<Geom_Surface>&, const TopoDS_Wire&, bool>(), py::arg("S"), py::arg("W"),
           py::arg("Inside") = true)
      .def(py::init<const TopoDS_Face&, const TopoDS_Wire&>())
      .def("Add", [](BRepBuilderAPI_MakeFace& f, const TopoDS_Wire& w) { f.Add(w); })
      .def("Face", [](BRepBuilderAPI_MakeFace& f) { return f.Face(); })
      .def("Error", [](const BRepBuilderAPI_MakeFace& f) { return static_cast<int>(f.Error()); });

  py::class_<BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeShape>(m, "BRepBuilderAPI_MakeSolid")
      .def(py::init<>())
      .def(py::init<const TopoDS_Shell&>())
      .def(py::init<const TopoDS_Solid&>())
      .def("Add", [](BRepBuilderAPI_MakeSolid& s, const TopoDS_Shell& shell) { s.Add(shell); })
      .def("Solid", [](BRepBuilderAPI_MakeSolid& s) { return s.Solid(); });

  // ---- booleans -----------------------------------------------------------------------------------------------
  // BRepAlgoAPI_Algo (protected destructor) is not a Python class: its methods are the builder's own here.
  py::class_<BRepAlgoAPI_BuilderAlgo, BRepBuilderAPI_MakeShape>(m, "BRepAlgoAPI_BuilderAlgo")
      .def("SetRunParallel", [](BRepAlgoAPI_BuilderAlgo& a, bool v) { a.SetRunParallel(v); })
      .def("RunParallel", [](const BRepAlgoAPI_BuilderAlgo& a) { return a.RunParallel(); })
      .def("SetFuzzyValue", [](BRepAlgoAPI_BuilderAlgo& a, double v) { a.SetFuzzyValue(v); })
      .def("FuzzyValue", [](const BRepAlgoAPI_BuilderAlgo& a) { return a.FuzzyValue(); })
      .def("SetUseOBB", [](BRepAlgoAPI_BuilderAlgo& a, bool v) { a.SetUseOBB(v); })
      .def("SetNonDestructive", [](BRepAlgoAPI_BuilderAlgo& a, bool v) { a.SetNonDestructive(v); })
      .def("SetGlue", [](BRepAlgoAPI_BuilderAlgo& a, BOPAlgo_GlueEnum g) { a.SetGlue(g); })
      .def("SetArguments", [](BRepAlgoAPI_BuilderAlgo& a, const TopTools_ListOfShape& l) { a.SetArguments(l); })
      .def("Arguments", [](const BRepAlgoAPI_BuilderAlgo& a) { return a.Arguments(); })
      .def("SetToFillHistory", [](BRepAlgoAPI_BuilderAlgo& a, bool v) { a.SetToFillHistory(v); })
      .def("HasHistory", [](const BRepAlgoAPI_BuilderAlgo& a) { return a.HasHistory(); })
      .def(
          "SimplifyResult",
          [](BRepAlgoAPI_BuilderAlgo& a, bool unifyEdges, bool unifyFaces, double angTol) {
            a.SimplifyResult(unifyEdges, unifyFaces, angTol);
          },
          py::arg("theUnifyEdges") = true, py::arg("theUnifyFaces") = true, py::arg("theAngularTol") = 1e-12)
      .def("Build", [](BRepAlgoAPI_BuilderAlgo& a) { a.Build(); })
      .def("IsDeleted", [](BRepAlgoAPI_BuilderAlgo& a, const TopoDS_Shape& s) { return a.IsDeleted(s); })
      .def("Modified", [](BRepAlgoAPI_BuilderAlgo& a, const TopoDS_Shape& s) { return a.Modified(s); })
      .def("Generated", [](BRepAlgoAPI_BuilderAlgo& a, const TopoDS_Shape& s) { return a.Generated(s); })
      .def("HasModified", [](const BRepAlgoAPI_BuilderAlgo& a) { return a.HasModified(); })
      .def("HasGenerated", [](const BRepAlgoAPI_BuilderAlgo& a) { return a.HasGenerated(); })
      .def("HasDeleted", [](const BRepAlgoAPI_BuilderAlgo& a) { return a.HasDeleted(); });

  py::class_<BRepAlgoAPI_BooleanOperation, BRepAlgoAPI_BuilderAlgo>(m, "BRepAlgoAPI_BooleanOperation")
      .def("SetTools", [](BRepAlgoAPI_BooleanOperation& a, const TopTools_ListOfShape& l) { a.SetTools(l); })
      .def("Tools", [](const BRepAlgoAPI_BooleanOperation& a) { return a.Tools(); })
      .def("Shape1", [](const BRepAlgoAPI_BooleanOperation& a) { return a.Shape1(); })
      .def("Shape2", [](const BRepAlgoAPI_BooleanOperation& a) { return a.Shape2(); })
      .def("Build", [](BRepAlgoAPI_BooleanOperation& a) { a.Build(); });
  boolean_class<BRepAlgoAPI_Common>(m, "BRepAlgoAPI_Common");
  boolean_class<BRepAlgoAPI_Cut>(m, "BRepAlgoAPI_Cut");
  boolean_class<BRepAlgoAPI_Fuse>(m, "BRepAlgoAPI_Fuse");

  py::class_<BRepAlgoAPI_Section, BRepAlgoAPI_BooleanOperation>(m, "BRepAlgoAPI_Section")
      .def(py::init<>())
      .def(py::init<const TopoDS_Shape&, const TopoDS_Shape&, bool>(), py::arg("S1"), py::arg("S2"),
           py::arg("PerformNow") = true)
      .def(py::init<const TopoDS_Shape&, const gp_Pln&, bool>(), py::arg("S1"), py::arg("Pl"),
           py::arg("PerformNow") = true)
      .def("Build", [](BRepAlgoAPI_Section& s) { s.Build(); })
      .def("Init1", [](BRepAlgoAPI_Section& s, const TopoDS_Shape& v) { s.Init1(v); })
      .def("Init2", [](BRepAlgoAPI_Section& s, const TopoDS_Shape& v) { s.Init2(v); })
      .def("Init1", [](BRepAlgoAPI_Section& s, const gp_Pln& v) { s.Init1(v); })
      .def("Approximation", [](BRepAlgoAPI_Section& s, bool v) { s.Approximation(v); })
      .def("ComputePCurveOn1", [](BRepAlgoAPI_Section& s, bool v) { s.ComputePCurveOn1(v); })
      .def("ComputePCurveOn2", [](BRepAlgoAPI_Section& s, bool v) { s.ComputePCurveOn2(v); });

  // ---- primitives, fillets, mesh --------------------------------------------------------------------------------
  py::class_<BRepPrimAPI_MakeBox, BRepBuilderAPI_MakeShape>(m, "BRepPrimAPI_MakeBox")
      .def(py::init<double, double, double>())
      .def(py::init<const gp_Pnt&, double, double, double>())
      .def(py::init<const gp_Pnt&, const gp_Pnt&>())
      .def(py::init<const gp_Ax2&, double, double, double>())
      .def("Shell", [](BRepPrimAPI_MakeBox& b) { return b.Shell(); })
      .def("Solid", [](BRepPrimAPI_MakeBox& b) { return b.Solid(); });

  py::class_<BRepPrimAPI_MakeCylinder, BRepBuilderAPI_MakeShape>(m, "BRepPrimAPI_MakeCylinder")
      .def(py::init<double, double>())
      .def(py::init<double, double, double>())
      .def(py::init<const gp_Ax2&, double, double>())
      .def(py::init<const gp_Ax2&, double, double, double>())
      .def("Shell", [](BRepPrimAPI_MakeCylinder& c) { return c.Shell(); })
      .def("Solid", [](BRepPrimAPI_MakeCylinder& c) { return c.Solid(); });

  py::class_<BRepPrimAPI_MakeSphere, BRepBuilderAPI_MakeShape>(m, "BRepPrimAPI_MakeSphere")
      .def(py::init<double>())
      .def(py::init<const gp_Pnt&, double>())
      .def(py::init<const gp_Ax2&, double>())
      .def("Shell", [](BRepPrimAPI_MakeSphere& s) { return s.Shell(); })
      .def("Solid", [](BRepPrimAPI_MakeSphere& s) { return s.Solid(); });

  py::class_<BRepPrimAPI_MakeSweep, BRepBuilderAPI_MakeShape>(m, "BRepPrimAPI_MakeSweep")
      .def("FirstShape", [](BRepPrimAPI_MakeSweep& s) { return s.FirstShape(); })
      .def("LastShape", [](BRepPrimAPI_MakeSweep& s) { return s.LastShape(); });

  py::class_<BRepPrimAPI_MakePrism, BRepPrimAPI_MakeSweep>(m, "BRepPrimAPI_MakePrism")
      .def(py::init<const TopoDS_Shape&, const gp_Vec&, bool, bool>(), py::arg("S"), py::arg("V"),
           py::arg("Copy") = false, py::arg("Canonize") = true);

  py::class_<BRepFilletAPI_LocalOperation, BRepBuilderAPI_MakeShape>(m, "BRepFilletAPI_LocalOperation");
  py::class_<BRepFilletAPI_MakeFillet, BRepFilletAPI_LocalOperation>(m, "BRepFilletAPI_MakeFillet")
      .def(py::init<const TopoDS_Shape&>())
      .def("Add", [](BRepFilletAPI_MakeFillet& f, double radius, const TopoDS_Edge& e) { f.Add(radius, e); })
      .def("Add", [](BRepFilletAPI_MakeFillet& f, double r1, double r2, const TopoDS_Edge& e) { f.Add(r1, r2, e); })
      .def("NbContours", [](const BRepFilletAPI_MakeFillet& f) { return f.NbContours(); })
      .def("Build", [](BRepFilletAPI_MakeFillet& f) { f.Build(); });

  py::class_<BRepMesh_IncrementalMesh>(m, "BRepMesh_IncrementalMesh")
      .def(py::init<>())
      .def(py::init<const TopoDS_Shape&, double, bool, double, bool>(), py::arg("theShape"),
           py::arg("theLinDeflection"), py::arg("isRelative") = false, py::arg("theAngDeflection") = 0.5,
           py::arg("isInParallel") = false)
      .def("Perform", [](BRepMesh_IncrementalMesh& mesh) { mesh.Perform(); })
      .def("IsDone", [](const BRepMesh_IncrementalMesh& mesh) { return mesh.IsDone(); })
      .def("Shape", [](const BRepMesh_IncrementalMesh& mesh) { return mesh.Shape(); })
      .def("IsModified", [](const BRepMesh_IncrementalMesh& mesh) { return mesh.IsModified(); })
      .def("GetStatusFlags", [](const BRepMesh_IncrementalMesh& mesh) { return mesh.GetStatusFlags(); });

  // ---- hidden-line removal ------------------------------------------------------------------------------------
  py::class_<HLRAlgo_Projector>(m, "HLRAlgo_Projector")
      .def(py::init<>())
      .def(py::init<const gp_Ax2&>())
      .def(py::init<const gp_Ax2&, double>());

  py::class_<HLRBRep_InternalAlgo, opencascade::handle<HLRBRep_InternalAlgo>>(m, "HLRBRep_InternalAlgo")
      .def("Projector", [](HLRBRep_InternalAlgo& a, const HLRAlgo_Projector& p) { a.Projector(p); })
      .def("Update", [](HLRBRep_InternalAlgo& a) { a.Update(); })
      .def("Hide", [](HLRBRep_InternalAlgo& a) { a.Hide(); });
  py::class_<HLRBRep_Algo, opencascade::handle<HLRBRep_Algo>, HLRBRep_InternalAlgo>(m, "HLRBRep_Algo")
      .def(py::init<>())
      .def(
          "Add", [](HLRBRep_Algo& a, const TopoDS_Shape& s, int nbIso) { a.Add(s, nbIso); }, py::arg("S"),
          py::arg("nbIso") = 0);

  py::class_<HLRBRep_HLRToShape>(m, "HLRBRep_HLRToShape")
      .def(py::init<const opencascade::handle<HLRBRep_Algo>&>())
      .def("VCompound", [](HLRBRep_HLRToShape& h) { return h.VCompound(); })
      .def("Rg1LineVCompound", [](HLRBRep_HLRToShape& h) { return h.Rg1LineVCompound(); })
      .def("RgNLineVCompound", [](HLRBRep_HLRToShape& h) { return h.RgNLineVCompound(); })
      .def("OutLineVCompound", [](HLRBRep_HLRToShape& h) { return h.OutLineVCompound(); })
      .def("IsoLineVCompound", [](HLRBRep_HLRToShape& h) { return h.IsoLineVCompound(); })
      .def("HCompound", [](HLRBRep_HLRToShape& h) { return h.HCompound(); })
      .def("Rg1LineHCompound", [](HLRBRep_HLRToShape& h) { return h.Rg1LineHCompound(); })
      .def("RgNLineHCompound", [](HLRBRep_HLRToShape& h) { return h.RgNLineHCompound(); })
      .def("OutLineHCompound", [](HLRBRep_HLRToShape& h) { return h.OutLineHCompound(); })
      .def("IsoLineHCompound", [](HLRBRep_HLRToShape& h) { return h.IsoLineHCompound(); });

  // ---- shape upgrade ------------------------------------------------------------------------------------------
  py::class_<ShapeUpgrade_ShapeDivide>(m, "ShapeUpgrade_ShapeDivide")
      .def(
          "Perform", [](ShapeUpgrade_ShapeDivide& d, bool newContext) { return d.Perform(newContext); },
          py::arg("newContext") = true)
      .def("Result", [](const ShapeUpgrade_ShapeDivide& d) { return d.Result(); });
  py::class_<ShapeUpgrade_ShapeDivideContinuity, ShapeUpgrade_ShapeDivide>(m, "ShapeUpgrade_ShapeDivideContinuity")
      .def(py::init<const TopoDS_Shape&>())
      .def("SetTolerance", [](ShapeUpgrade_ShapeDivideContinuity& d, double t) { d.SetTolerance(t); })
      .def(
          "SetBoundaryCriterion",
          [](ShapeUpgrade_ShapeDivideContinuity& d, GeomAbs_Shape c) { d.SetBoundaryCriterion(c); },
          py::arg("Criterion") = GeomAbs_C1)
      .def(
          "SetPCurveCriterion", [](ShapeUpgrade_ShapeDivideContinuity& d, GeomAbs_Shape c) { d.SetPCurveCriterion(c); },
          py::arg("Criterion") = GeomAbs_C1)
      .def(
          "SetSurfaceCriterion",
          [](ShapeUpgrade_ShapeDivideContinuity& d, GeomAbs_Shape c) { d.SetSurfaceCriterion(c); },
          py::arg("Criterion") = GeomAbs_C1);
}

}  // namespace scad::pybind::occt
