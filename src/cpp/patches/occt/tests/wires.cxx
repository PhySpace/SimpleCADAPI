// wires <file.brep> <face index>: the wires of a face, edge by edge (3D ends, orientation).
#include "fixtures.hxx"
#include <BRep_Builder.hxx>
#include <TopoDS_Iterator.hxx>
#include <cstdlib>
int main(int argc, char** argv)
{
  BRep_Builder b;
  TopoDS_Shape s;
  BRepTools::Read(s, argv[1], b);
  int k = 0;
  for (TopExp_Explorer ex(s, TopAbs_FACE); ex.More(); ex.Next())
  {
    if (++k != std::atoi(argv[2]))
      continue;
    int w = 0;
    for (TopoDS_Iterator wi(ex.Current()); wi.More(); wi.Next())
    {
      std::printf("wire %d closed %d\n", ++w, (int)BRep_Tool::IsClosed(wi.Value()));
      for (TopoDS_Iterator ei(wi.Value()); ei.More(); ei.Next())
      {
        BRepAdaptor_Curve c(TopoDS::Edge(ei.Value()));
        const bool        rev = ei.Value().Orientation() == TopAbs_REVERSED;
        gp_Pnt a = c.Value(rev ? c.LastParameter() : c.FirstParameter()), z = c.Value(rev ? c.FirstParameter() : c.LastParameter());
        std::printf("  %p o%d (%.3f %.3f %.3f)->(%.3f %.3f %.3f)\n", (void*)ei.Value().TShape().get(), (int)ei.Value().Orientation(), a.X(), a.Y(), a.Z(), z.X(), z.Y(), z.Z());
      }
    }
  }
}
