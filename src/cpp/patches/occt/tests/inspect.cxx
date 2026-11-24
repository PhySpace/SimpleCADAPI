#include "fixtures.hxx"
#include <BRep_Builder.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <cstdlib>
void dump(const char* tag, int nf, const TopoDS_Edge& e)
{
  BRepAdaptor_Curve c(e);
  double            f = c.FirstParameter(), l = c.LastParameter();
  gp_Pnt            a = c.Value(f), m = c.Value((f + l) / 2), z = c.Value(l);
  std::printf("%s n%d type %d (%.4f %.4f %.4f) (%.4f %.4f %.4f) (%.4f %.4f %.4f)\n", tag, nf, (int)c.GetType(),
              a.X(), a.Y(), a.Z(), m.X(), m.Y(), m.Z(), z.X(), z.Y(), z.Z());
}
int main(int argc, char** argv)
{
  BRep_Builder b;
  TopoDS_Shape s;
  BRepTools::Read(s, argv[1], b);
  TopTools_IndexedDataMapOfShapeListOfShape ef;
  TopExp::MapShapesAndAncestors(s, TopAbs_EDGE, TopAbs_FACE, ef);
  std::printf("faces %d\n", count(s, TopAbs_FACE));
  int k = 0;
  for (TopExp_Explorer ex(s, TopAbs_FACE); ex.More(); ex.Next())
  {
    BRepAdaptor_Surface su(TopoDS::Face(ex.Current()));
    std::printf(" face %d type %d edges %d\n", ++k, (int)su.GetType(), count(ex.Current(), TopAbs_EDGE));
    if (argc > 3 && std::atoi(argv[3]) == k) // inspect <file> x <k>: the edges of face k
      for (TopExp_Explorer e(ex.Current(), TopAbs_EDGE); e.More(); e.Next())
      {
        const TopoDS_Edge edge = TopoDS::Edge(e.Current());
        dump("  in-face", ef.FindFromKey(edge).Extent(), edge);
        double f, l; // the pcurve in this face, in wire orientation
        Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(edge, TopoDS::Face(ex.Current()), f, l);
        if (!pc.IsNull())
        {
          gp_Pnt2d a = pc->Value(edge.Orientation() == TopAbs_REVERSED ? l : f);
          gp_Pnt2d z = pc->Value(edge.Orientation() == TopAbs_REVERSED ? f : l);
          std::printf("    uv (%.4f %.4f) -> (%.4f %.4f) orient %d\n", a.X(), a.Y(), z.X(), z.Y(), (int)edge.Orientation());
        }
      }
  }
  for (int i = 1; i <= ef.Extent(); ++i)
    if (ef(i).Extent() == 1 || argc > 2)
      dump(ef(i).Extent() == 1 ? "free" : "edge", ef(i).Extent(), TopoDS::Edge(ef.FindKey(i)));
}
