// sidetail <file.brep>: the self-interferences (level 5), with where they are.
#include "fixtures.hxx"
#include <BRep_Builder.hxx>
#include <BOPDS_Interf.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <BRepAdaptor_Surface.hxx>
static gp_Pnt where(const TopoDS_Shape& s)
{
  GProp_GProps g;
  if (s.ShapeType() == TopAbs_FACE)
    BRepGProp::SurfaceProperties(s, g);
  else if (s.ShapeType() == TopAbs_EDGE)
    BRepGProp::LinearProperties(s, g);
  else
    return BRep_Tool::Pnt(TopoDS::Vertex(s));
  return g.CentreOfMass();
}
int main(int, char** argv)
{
  BRep_Builder b;
  TopoDS_Shape s;
  BRepTools::Read(s, argv[1], b);
  BOPAlgo_CheckerSI c;
  c.SetLevelOfCheck(5);
  c.AddArgument(s);
  c.Perform();
  const BOPDS_DS& ds = c.DS();
  for (BOPDS_MapIteratorOfMapOfPair it(ds.Interferences()); it.More(); it.Next())
  {
    int i1, i2;
    it.Value().Indices(i1, i2);
    const TopoDS_Shape &a = ds.Shape(i1), &z = ds.Shape(i2);
    gp_Pnt pa = where(a), pz = where(z);
    std::printf("%d/%d types %d %d at (%.3f %.3f %.3f) / (%.3f %.3f %.3f)\n", i1, i2, (int)a.ShapeType(), (int)z.ShapeType(),
                pa.X(), pa.Y(), pa.Z(), pz.X(), pz.Y(), pz.Z());
    if (a.ShapeType() == TopAbs_FACE)
      std::printf("   face types %d %d\n", (int)BRepAdaptor_Surface(TopoDS::Face(a)).GetType(),
                  z.ShapeType() == TopAbs_FACE ? (int)BRepAdaptor_Surface(TopoDS::Face(z)).GetType() : -1);
  }
}
