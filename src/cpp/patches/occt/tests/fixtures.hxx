#pragma once
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BOPAlgo_CheckerSI.hxx>
#include <BOPDS_DS.hxx>
#include <BRepTools.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <functional>
#include <string>
#include <vector>
#include <cstdio>

inline TopoDS_Shape fuse(const TopoDS_Shape& a, const TopoDS_Shape& b) {
  BRepAlgoAPI_Fuse f(a, b); f.SimplifyResult(); return f.Shape();
}
// The research sample: post radius R (height 2h) flush with the plate side, plate 3R x 2R x h.
inline TopoDS_Shape plate_post(double R = 50, double h = 40) {
  auto c = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(), gp_Dir(0, 0, 1), gp_Dir(-1, 0, 0)), R, 2 * h).Shape();
  auto b = BRepPrimAPI_MakeBox(gp_Pnt(0, -R, 0), 3 * R, 2 * R, h).Shape();
  return fuse(c, b);
}
inline gp_Pnt mid(const TopoDS_Edge& e) {
  BRepAdaptor_Curve c(e); return c.Value((c.FirstParameter() + c.LastParameter()) / 2);
}
inline std::vector<TopoDS_Edge> edges_where(const TopoDS_Shape& s, std::function<bool(const TopoDS_Edge&)> f) {
  TopTools_IndexedMapOfShape m; TopExp::MapShapes(s, TopAbs_EDGE, m); std::vector<TopoDS_Edge> out;
  for (int i = 1; i <= m.Extent(); ++i) if (f(TopoDS::Edge(m(i)))) out.push_back(TopoDS::Edge(m(i)));
  return out;
}
inline int si_count(const TopoDS_Shape& s) {
  BOPAlgo_CheckerSI c; c.SetLevelOfCheck(5); c.AddArgument(s); c.Perform();
  if (c.HasErrors()) return -1;
  return c.DS().Interferences().Extent();
}
inline bool valid(const TopoDS_Shape& s) { return !s.IsNull() && BRepCheck_Analyzer(s).IsValid(); }
inline int count(const TopoDS_Shape& s, TopAbs_ShapeEnum t) { TopTools_IndexedMapOfShape m; TopExp::MapShapes(s, t, m); return m.Extent(); }
