// fixsmall <in.brep> <tol>: merge edges shorter than tol (ShapeFix_Wireframe), then validity and SI.
#include "fixtures.hxx"
#include <BRep_Builder.hxx>
#include <ShapeFix_Wireframe.hxx>
int main(int, char** argv)
{
  BRep_Builder b;
  TopoDS_Shape s;
  BRepTools::Read(s, argv[1], b);
  std::printf("before: valid %d si %d edges %d\n", valid(s), si_count(s), count(s, TopAbs_EDGE));
  ShapeFix_Wireframe fix(s);
  fix.SetPrecision(atof(argv[2]));
  fix.SetMaxTolerance(atof(argv[2]));
  fix.ModeDropSmallEdges() = Standard_True;
  fix.FixSmallEdges();
  const TopoDS_Shape r = fix.Shape();
  std::printf("after: valid %d si %d edges %d\n", valid(r), si_count(r), count(r, TopAbs_EDGE));
}
