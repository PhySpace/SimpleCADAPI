#include "fixtures.hxx"
#include <BRep_Builder.hxx>
#include <BRepCheck_Result.hxx>
#include <BRepCheck_ListOfStatus.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
int main(int argc, char** argv) {
  BRep_Builder b; TopoDS_Shape s; BRepTools::Read(s, argv[1], b);
  BRepCheck_Analyzer an(s);
  std::printf("valid %d\n", an.IsValid());
  for (auto t : {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_WIRE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID}) {
    TopTools_IndexedMapOfShape m; TopExp::MapShapes(s, t, m);
    for (int i = 1; i <= m.Extent(); ++i) {
      auto r = an.Result(m(i)); if (r.IsNull()) continue;
      for (BRepCheck_ListIteratorOfListOfStatus it(r->Status()); it.More(); it.Next())
        if (it.Value() != BRepCheck_NoError) {
          gp_Pnt p; if (t == TopAbs_EDGE) p = mid(TopoDS::Edge(m(i))); else if (t == TopAbs_VERTEX) p = BRep_Tool::Pnt(TopoDS::Vertex(m(i))); else { GProp_GProps g; BRepGProp::LinearProperties(m(i), g); p = g.CentreOfMass(); }
          std::printf("type %d #%d status %d at (%.3f %.3f %.3f)\n", (int)t, i, (int)it.Value(), p.X(), p.Y(), p.Z()); }
      // context statuses (edge in face etc.)
      if (t == TopAbs_EDGE || t == TopAbs_WIRE) {
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(s, TopAbs_FACE, fm);
        for (int k = 1; k <= fm.Extent(); ++k) { r->InitContextIterator(); for (; r->MoreShapeInContext(); r->NextShapeInContext()) {
          for (BRepCheck_ListIteratorOfListOfStatus it(r->StatusOnShape()); it.More(); it.Next()) if (it.Value() != BRepCheck_NoError) { gp_Pnt p = t == TopAbs_EDGE ? mid(TopoDS::Edge(m(i))) : gp_Pnt(); std::printf("type %d #%d context status %d at (%.3f %.3f %.3f)\n", (int)t, i, (int)it.Value(), p.X(), p.Y(), p.Z()); } } break; }
      }
    }
  }
}
