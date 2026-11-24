// yfillet IN.brep x y z r [x y z r ...]: BRepFilletAPI_MakeFillet with SetYPatch on the edges
// nearest to the given points; reports the Y junctions and writes yfillet-out.brep.
#include "cases.hxx"
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRep_Builder.hxx>
#include <BinTools.hxx>
int main(int argc, char** argv)
{
  BRep_Builder b;
  TopoDS_Shape s;
  if (argc < 6 || !(BRepTools::Read(s, argv[1], b) || BinTools::Read(s, argv[1])))  // text or binary
    return 2;
  BRepFilletAPI_MakeFillet f(s);
  f.SetYPatch(Standard_True);
  for (int a = 2; a + 3 < argc; a += 4)
    f.Add(atof(argv[a + 3]), edge_at(s, gp_Pnt(atof(argv[a]), atof(argv[a + 1]), atof(argv[a + 2]))));
  f.Build();
  std::printf("done %d y-patches %d\n", f.IsDone(), f.IsDone() ? f.NbYPatches() : 0);
  for (int i = 1; f.IsDone() && i <= f.NbYPatches(); ++i)
  {
    const auto& j = f.YPatchJunction(i);
    std::printf("  P*(%.4f %.4f %.4f) seam %.2e deg band %.2e deg\n", j.Split.X(), j.Split.Y(), j.Split.Z(),
                j.SeamAngle * 180 / M_PI, j.BandAngle * 180 / M_PI);
  }
  if (f.IsDone())
  {
    std::printf("valid %d si %d faces %d\n", valid(f.Shape()), si_count(f.Shape()), count(f.Shape(), TopAbs_FACE));
    BRepTools::Write(f.Shape(), "yfillet-out.brep");
    // history as a caller sees it: every input face is kept, modified or deleted; every selected edge generates
    TopTools_IndexedMapOfShape out;
    TopExp::MapShapes(f.Shape(), out);
    int k = 0;
    for (TopExp_Explorer ex(s, TopAbs_FACE); ex.More(); ex.Next(), ++k)
    {
      const TopTools_ListOfShape& m = f.Modified(ex.Current());
      int inside = 0;
      for (TopTools_ListOfShape::Iterator it(m); it.More(); it.Next())
        inside += out.Contains(it.Value());
      std::printf("  face %d: modified %d (in result %d) deleted %d kept %d\n", k, m.Extent(), inside,
                  (int)f.IsDeleted(ex.Current()), (int)out.Contains(ex.Current()));
    }
    for (int a = 2; a + 3 < argc; a += 4)
    {
      const TopoDS_Edge e = edge_at(s, gp_Pnt(atof(argv[a]), atof(argv[a + 1]), atof(argv[a + 2])));
      const TopTools_ListOfShape& g = f.Generated(e);
      int inside = 0;
      for (TopTools_ListOfShape::Iterator it(g); it.More(); it.Next())
        inside += out.Contains(it.Value());
      std::printf("  edge %d: generated %d (in result %d)\n", a / 4, g.Extent(), inside);
    }
  }
  return f.IsDone() ? 0 : 1;
}
