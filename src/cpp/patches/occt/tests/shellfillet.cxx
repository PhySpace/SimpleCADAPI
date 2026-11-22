// Standard fillet of chosen edges of a BREP shape (solid or open shell):
//   shellfillet <file.brep> x y z r [x y z r ...]
// Each edge is the two-face edge whose midpoint is nearest to (x y z).  Writes
// shellfillet-out.brep.  YP_PARAMS="tang tesp t2d tapp3d tolapp2d fleche" sets SetParams;
// YP_FIX=1 runs ShapeFix_Face on every invalid face of the result first.
#include "fixtures.hxx"
#include <BRep_Builder.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <ChFi3d.hxx>
#include <ShapeBuild_ReShape.hxx>
#include <ShapeFix_Face.hxx>
#include <ShapeFix_Wire.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <cstdio>
#include <cstdlib>

int main(int argc, char** argv)
{
  BRep_Builder b;
  TopoDS_Shape s;
  BRepTools::Read(s, argv[1], b);
  TopTools_IndexedDataMapOfShapeListOfShape ef;
  TopExp::MapShapesAndAncestors(s, TopAbs_EDGE, TopAbs_FACE, ef);
  BRepFilletAPI_MakeFillet f(s);
  if (const char* p = std::getenv("YP_PARAMS"))
  {
    double a[6];
    std::sscanf(p, "%lf %lf %lf %lf %lf %lf", a, a + 1, a + 2, a + 3, a + 4, a + 5);
    f.SetParams(a[0], a[1], a[2], a[3], a[4], a[5]);
  }
  for (int a = 2; a + 3 < argc; a += 4)
  {
    gp_Pnt p(std::atof(argv[a]), std::atof(argv[a + 1]), std::atof(argv[a + 2]));
    double best = 1e9;
    int    bi   = 0;
    for (int i = 1; i <= ef.Extent(); ++i)
    {
      if (ef(i).Extent() != 2)
        continue;
      double d = mid(TopoDS::Edge(ef.FindKey(i))).Distance(p);
      if (d < best)
      {
        best = d;
        bi   = i;
      }
    }
    auto e = TopoDS::Edge(ef.FindKey(bi));
    auto m = mid(e);
    std::printf("edge %d mid (%.3f %.3f %.3f) d %.3g conc %d\n", bi, m.X(), m.Y(), m.Z(), best,
                (int)ChFi3d::DefineConnectType(e, TopoDS::Face(ef(bi).First()), TopoDS::Face(ef(bi).Last()), 1e-5, true));
    f.Add(std::atof(argv[a + 3]), e);
  }
  try
  {
    f.Build();
    std::printf("done %d\n", f.IsDone());
    if (!f.IsDone())
    {
      std::printf("faulty contours %d vertices %d\n", f.NbFaultyContours(), f.NbFaultyVertices());
      for (int i = 1; i <= f.NbFaultyVertices(); ++i)
      {
        auto p = BRep_Tool::Pnt(f.FaultyVertex(i));
        std::printf(" faulty vertex (%.3f %.3f %.3f)\n", p.X(), p.Y(), p.Z());
      }
      return 1;
    }
    TopoDS_Shape out = f.Shape();
    if (std::getenv("YP_FIX"))
    {
      Handle(ShapeBuild_ReShape) rs = new ShapeBuild_ReShape();
      for (TopExp_Explorer ex(out, TopAbs_FACE); ex.More(); ex.Next())
        if (!BRepCheck_Analyzer(ex.Current()).IsValid())
        {
          const TopoDS_Face face = TopoDS::Face(ex.Current());
          for (TopoDS_Iterator wi(face); wi.More(); wi.Next())
          {
            ShapeFix_Wire fw(TopoDS::Wire(wi.Value()), face, 1e-7);
            fw.SetContext(rs);
            const bool shifted = fw.FixShifted();
            std::printf("FixShifted %d\n", (int)shifted);
            if (shifted)
              rs->Replace(wi.Value(), fw.Wire());
          }
        }
      out = rs->Apply(out);
    }
    BRepTools::Write(out, "shellfillet-out.brep");
    // the standard algorithm's history on this input
    TopTools_IndexedMapOfShape outFaces;
    TopExp::MapShapes(f.Shape(), TopAbs_FACE, outFaces);
    int k = 0;
    for (TopExp_Explorer ex(s, TopAbs_FACE); ex.More(); ex.Next())
    {
      int in = 0;
      for (TopTools_ListOfShape::Iterator it(f.Modified(ex.Current())); it.More(); it.Next())
        in += outFaces.Contains(it.Value());
      std::printf("face %d: modified %d (in result %d) deleted %d kept %d\n", ++k, f.Modified(ex.Current()).Extent(), in,
                  (int)f.IsDeleted(ex.Current()), (int)outFaces.Contains(ex.Current()));
    }
    for (int c = 1; c <= f.NbContours(); ++c)
      for (int i = 1; i <= f.NbEdges(c); ++i)
        std::printf("contour %d edge %d: generated %d\n", c, i, f.Generated(f.Edge(c, i)).Extent());
  }
  catch (Standard_Failure& e)
  {
    std::printf("throw %s\n", e.GetMessageString());
    return 1;
  }
  return 0;
}
