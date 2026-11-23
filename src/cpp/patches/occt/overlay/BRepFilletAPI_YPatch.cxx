// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#include <BRepFilletAPI_YPatch.hxx>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Tool.hxx>
#include <ChFi3d.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom_Surface.hxx>
#include <ShapeAnalysis_Surface.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <math_Gauss.hxx>
#include <math_Matrix.hxx>
#include <math_Vector.hxx>

#include <algorithm>
#include <cmath>
#include <functional>
#include <vector>

#include <BRepFilletAPI_YPatchGeom.hxx>

namespace YPatch
{

Support::Support(const TopoDS_Face& f)
    : face(f),
      s(f, Standard_False),
      sign(f.Orientation() == TopAbs_REVERSED ? -1. : 1.),
      proj(new ShapeAnalysis_Surface(BRep_Tool::Surface(f)))
{
}

gp_Pnt Support::P(const gp_Pnt2d& uv) const
{
  return s.Value(uv.X(), uv.Y());
}

gp_Vec Support::N(const gp_Pnt2d& uv) const
{
  gp_Pnt p;
  gp_Vec du, dv;
  s.D1(uv.X(), uv.Y(), p, du, dv);
  gp_Vec       n = du.Crossed(dv);
  const double m = n.Magnitude();
  if (m < 1e-14)
    throw Standard_Failure("YPatch: singular support normal");
  return n * (sign / m);
}

gp_Pnt2d Support::UV(const gp_Pnt& p) const
{
  return proj->ValueOfUV(p, 1e-9);
}

gp_Pnt2d Support::UVNear(const gp_Pnt& p, const gp_Pnt2d& seed) const
{
  return proj->NextValueOfUV(seed, p, 1e-9);
}

Rail::Rail(const TopoDS_Edge& e, const TopoDS_Vertex& v)
    : edge(e),
      c(e)
{
  TopoDS_Vertex v1, v2;
  TopExp::Vertices(e, v1, v2);
  first = c.FirstParameter();
  last  = c.LastParameter();
  if (v.IsSame(v2) && !v.IsSame(v1))
    std::swap(first, last);
}

double Rail::Param(double lambda) const
{
  return first + lambda * (last - first);
}

gp_Pnt Rail::P(double lambda) const
{
  return c.Value(Param(lambda));
}

gp_Vec Rail::T(double lambda) const
{
  gp_Pnt p;
  gp_Vec d;
  c.D1(Param(lambda), p, d);
  if (last < first)
    d.Reverse();
  return d.Normalized();
}

gp_Pnt2d Rail::UV(const TopoDS_Face& f, double lambda) const
{
  double f1, l1;
  auto   pc = BRep_Tool::CurveOnSurface(edge, f, f1, l1);
  if (pc.IsNull())
    throw Standard_Failure("YPatch: edge without pcurve");
  return pc->Value(Param(lambda));
}

// The rolling ball of radius r between T and X whose centre lies in the normal plane of
// the rail at lambda.  sigma = +1: concave (ball outside), -1: convex (ball inside).
bool Band::Solve(double lambda, Ball& b, const Ball* seed) const
{
  const gp_Pnt e = rail.P(lambda);
  const gp_Vec t = rail.T(lambda);
  math_Vector  x(1, 4);
  if (seed != nullptr)
  {
    x(1) = seed->uvT.X();
    x(2) = seed->uvT.Y();
    x(3) = seed->uvX.X();
    x(4) = seed->uvX.Y();
  }
  else
  {
    const gp_Pnt2d a = rail.UV(T.face, lambda), c = rail.UV(X.face, lambda);
    gp_Vec         nT = T.N(a), nX = X.N(c);
    gp_Vec         dT = nX - nT * nX.Dot(nT), dX = nT - nX * nT.Dot(nX);
    if (dT.Magnitude() < 1e-9 || dX.Magnitude() < 1e-9)
      return false;
    const gp_Pnt2d a2 = T.UVNear(e.Translated(dT.Normalized() * (sigma * r)), a);
    const gp_Pnt2d c2 = X.UVNear(e.Translated(dX.Normalized() * (sigma * r)), c);
    x(1)              = a2.X();
    x(2)              = a2.Y();
    x(3)              = c2.X();
    x(4)              = c2.Y();
  }
  auto residual = [&](const math_Vector& y, math_Vector& f) {
    const gp_Pnt2d a(y(1), y(2)), c(y(3), y(4));
    const gp_XYZ   cT = T.P(a).XYZ() + T.N(a).XYZ() * (sigma * r);
    const gp_XYZ   cX = X.P(c).XYZ() + X.N(c).XYZ() * (sigma * r);
    const gp_XYZ   d  = cT - cX;
    f(1)              = d.X();
    f(2)              = d.Y();
    f(3)              = d.Z();
    f(4)              = (cT - e.XYZ()).Dot(t.XYZ());
  };
  math_Vector f(1, 4), g(1, 4);
  for (int it = 0; it < 60; ++it)
  {
    residual(x, f);
    if (f.Norm() < 1e-11 * (1 + r))
    {
      const gp_Pnt2d a(x(1), x(2)), c(x(3), x(4));
      b.lambda = lambda;
      b.uvT    = a;
      b.uvX    = c;
      b.pT     = T.P(a);
      b.pX     = X.P(c);
      b.c      = gp_Pnt(b.pT.XYZ() + T.N(a).XYZ() * (sigma * r));
      return true;
    }
    math_Matrix j(1, 4, 1, 4);
    for (int k = 1; k <= 4; ++k)
    {
      math_Vector y = x;
      const double h = 1e-7 * (1 + std::abs(x(k)));
      y(k) += h;
      residual(y, g);
      for (int i = 1; i <= 4; ++i)
        j(i, k) = (g(i) - f(i)) / h;
    }
    math_Gauss lu(j);
    if (!lu.IsDone())
      return false;
    math_Vector dx(1, 4);
    lu.Solve(-f, dx);
    double step = 1.;
    const double cap = 0.5 * r;
    // limit the 3D displacement of either contact to half a radius per iteration
    for (int k = 0; k < 2; ++k)
    {
      const Support& s  = k ? X : T;
      const gp_Pnt2d p0(x(1 + 2 * k), x(2 + 2 * k));
      const gp_Pnt2d p1(x(1 + 2 * k) + dx(1 + 2 * k), x(2 + 2 * k) + dx(2 + 2 * k));
      const double   m = s.P(p0).Distance(s.P(p1));
      if (m > cap)
        step = std::min(step, cap / m);
    }
    x += dx * step;
  }
  return false;
}

double angle(const gp_Vec& a, const gp_Vec& b)
{
  return a.Angle(b);
}

} // namespace YPatch

using namespace YPatch;

NCollection_Vector<BRepFilletAPI_YPatch::Junction> BRepFilletAPI_YPatch::Detect(
  const TopoDS_Shape&               theShape,
  const TopTools_DataMapOfShapeReal& theRadii)
{
  NCollection_Vector<Junction>              out;
  TopTools_IndexedDataMapOfShapeListOfShape ef, ve;
  TopExp::MapShapesAndAncestors(theShape, TopAbs_EDGE, TopAbs_FACE, ef);
  TopExp::MapShapesAndAncestors(theShape, TopAbs_VERTEX, TopAbs_EDGE, ve);
  auto faces = [&](const TopoDS_Edge& e, TopoDS_Face& f1, TopoDS_Face& f2) {
    if (!ef.Contains(e))
      return false;
    const TopTools_ListOfShape& l = ef.FindFromKey(e);
    if (l.Extent() != 2)
      return false;
    f1 = TopoDS::Face(l.First());
    f2 = TopoDS::Face(l.Last());
    return !f1.IsSame(f2);
  };
  for (int iv = 1; iv <= ve.Extent(); ++iv)
  {
    const TopoDS_Vertex v = TopoDS::Vertex(ve.FindKey(iv));
    std::vector<TopoDS_Edge> concave, convex;
    for (TopTools_ListOfShape::Iterator it(ve(iv)); it.More(); it.Next())
    {
      const TopoDS_Edge e = TopoDS::Edge(it.Value());
      if (!theRadii.IsBound(e) || BRep_Tool::Degenerated(e))
        continue;
      TopoDS_Face f1, f2;
      if (!faces(e, f1, f2))
        continue;
      const ChFiDS_TypeOfConcavity k = ChFi3d::DefineConnectType(e, f1, f2, 1.e-5, Standard_True);
      auto& bucket = k == ChFiDS_Concave ? concave : convex;
      if (k != ChFiDS_Concave && k != ChFiDS_Convex)
        continue;
      if (std::none_of(bucket.begin(), bucket.end(), [&](const TopoDS_Edge& x) { return x.IsSame(e); }))
        bucket.push_back(e);
    }
    for (const auto& ein : concave)
      for (const auto& eout : convex)
      {
        if (ein.IsSame(eout))
          continue;
        TopoDS_Face a1, a2, b1, b2;
        faces(ein, a1, a2);
        faces(eout, b1, b2);
        TopoDS_Face T, A, B;
        if (a1.IsSame(b1) || a1.IsSame(b2))
        {
          T = a1;
          A = a2;
        }
        else if (a2.IsSame(b1) || a2.IsSame(b2))
        {
          T = a2;
          A = a1;
        }
        else
          continue;
        B = b1.IsSame(T) ? b2 : b1;
        if (A.IsSame(B))
          continue;
        // A and B must meet at V along an unselected edge.
        bool adjacent = false;
        for (TopTools_ListOfShape::Iterator it(ve(iv)); it.More() && !adjacent; it.Next())
        {
          const TopoDS_Edge es = TopoDS::Edge(it.Value());
          TopoDS_Face       f1, f2;
          if (es.IsSame(ein) || es.IsSame(eout) || theRadii.IsBound(es) || !faces(es, f1, f2))
            continue;
          adjacent = (f1.IsSame(A) && f2.IsSame(B)) || (f1.IsSame(B) && f2.IsSame(A));
        }
        if (!adjacent)
          continue;
        Support sa(A), sb(B);
        Rail    ra(ein, v), rb(eout, v);
        const double ang = angle(sa.N(ra.UV(A, 0)), sb.N(rb.UV(B, 0)));
        if (ang > MaxSupportAngle())
          continue;
        Junction j;
        j.Vertex       = v;
        j.Concave      = ein;
        j.Convex       = eout;
        j.Common       = T;
        j.Concave2     = A;
        j.Convex2      = B;
        j.RConcave     = theRadii.Find(ein);
        j.RConvex      = theRadii.Find(eout);
        j.SupportAngle = ang;
        out.Append(j);
      }
  }
  return out;
}
