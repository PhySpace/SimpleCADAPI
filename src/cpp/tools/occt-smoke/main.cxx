#include <BRepFilletAPI_RibbonFit.hxx>
#include <BRepFilletAPI_TangentY.hxx>
#include <BRepOffsetAPI_GraphPatch.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRepTools.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Pln.hxx>
#include <vector>

int main() {
  const auto support = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(), gp_Dir(0, 0, 1)), 0., 60., 0., 40.).Face();
  std::vector<TopoDS_Edge> edges;
  for (BRepTools_WireExplorer it(BRepTools::OuterWire(support)); it.More(); it.Next()) edges.push_back(it.Current());
  const std::vector<TopoDS_Face> supports(edges.size(), support);
  const std::vector<int> orders(edges.size(), 2);
  TopoDS_Face patch;
  if (edges.size() != 4 || !BRepOffsetAPI_GraphPatch::TryBuild(4, edges.data(), supports.data(), orders.data(), patch)
      || !BRepCheck_Analyzer(patch).IsValid()) return 1;
  auto p = [](const void*, double u, double v) { return gp_Pnt(2*u, 3*v, 5*u*v); };
  auto n = [](const void*, int side, double t) {
    const double u = side < 2 ? side : t, v = side < 2 ? t : side - 2;
    return gp_Vec(-15*v, -10*u, 6);
  };
  if (!BRepFilletAPI_RibbonFit::TryBuild(nullptr, p, n, patch)) return 2;
  TopoDS_Solid out;
  return BRepFilletAPI_TangentY::TryBuild(TopoDS_Solid(), edges[0], edges[1], 5., out) ? 3 : 0;
}
