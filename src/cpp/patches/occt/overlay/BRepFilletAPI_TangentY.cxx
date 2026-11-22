// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#include <BRepFilletAPI_TangentY.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepLib.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BOPAlgo_CheckerSI.hxx>
#include <BOPDS_DS.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Geom_BSplineSurface.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <math_Gauss.hxx>
#include <algorithm>
#include <cmath>
#include <vector>

namespace
{
using V             = gp_XYZ;
using Row           = std::vector<V>;
using Net           = std::vector<Row>;
constexpr int    n  = 23;
constexpr double pi = 3.14159265358979323846;

void require(bool ok)
{
  if (!ok)
    throw Standard_ConstructionError("TangentY: inadmissible geometry");
}

double sinc(double x)
{
  return std::abs(x) < 1e-12 ? 1 : std::sin(x) / x;
}

// Cubic collocation: not-a-knot for the preliminary jets, clamped Hermite
// for the final tensor product. Include endpoint rows in the same factorization.
struct Spline
{
  std::vector<double> t, k;
  bool                clamped;
  math_Gauss          lu;

  Spline(const std::vector<double>& nodes, bool clamp)
      : t(nodes),
        k(4, 0.),
        clamped(clamp),
        lu(matrix())
  {
    require(lu.IsDone());
  }

  math_Matrix matrix()
  {
    for (int j = clamped ? 1 : 2; j < n - (clamped ? 1 : 2); ++j)
      k.push_back(t[j]);
    k.insert(k.end(), 4, 1.);
    int         m = int(k.size()) - 4;
    math_Matrix a(1, m, 1, m, 0.);
    for (int j = 0; j < n; ++j)
    {
      std::vector<double> b(k.size(), 0.);
      if (j == n - 1)
        b[m - 1] = 1.;
      else
      {
        for (int i = 0; i < m + 3; ++i)
          b[i] = t[j] >= k[i] && t[j] < k[i + 1];
        for (int d = 1; d <= 3; ++d)
          for (int i = 0; i < m + 3 - d; ++i)
          {
            double l = k[i + d] - k[i], r = k[i + d + 1] - k[i + 1];
            b[i] =
              (l ? (t[j] - k[i]) / l * b[i] : 0) + (r ? (k[i + d + 1] - t[j]) / r * b[i + 1] : 0);
          }
      }
      for (int i = 0; i < m; ++i)
        a(j + 1, i + 1) = b[i];
    }
    if (clamped)
    {
      a(n + 1, 1)     = -3 / k[4];
      a(n + 1, 2)     = -a(n + 1, 1);
      a(n + 2, m)     = 3 / (1 - k[m - 1]);
      a(n + 2, m - 1) = -a(n + 2, m);
    }
    return a;
  }

  Row fit(const Row& values, const V& a = {}, const V& b = {}) const
  {
    int m = int(k.size()) - 4;
    Row p(m);
    for (int c = 1; c <= 3; ++c)
    {
      math_Vector x(1, m);
      for (int i = 0; i < n; ++i)
        x(i + 1) = values[i].Coord(c);
      if (clamped)
      {
        x(n + 1) = a.Coord(c);
        x(n + 2) = b.Coord(c);
      }
      lu.Solve(x);
      for (int i = 0; i < m; ++i)
        p[i].SetCoord(c, x(i + 1));
    }
    return p;
  }

  V jet(const Row& p, int end) const
  {
    int m = int(p.size());
    return end ? (p[m - 1] - p[m - 2]) * (3 / (1 - k[m - 1])) : (p[1] - p[0]) * (3 / k[4]);
  }
};

struct Layout
{
  double R, r, h, B, alpha;

  Layout(double R_, double r_, double h_)
      : R(R_),
        r(r_),
        h(h_),
        B(2 * sqrt(R * r)),
        alpha(atan2(B, R - r))
  {
  }

  V pos(int side, double u, double v) const
  {
    double f = u * u, dz = r * (1 - f) / 2, w = sqrt(.5);
    V      q(B * u, -R + r * f, h);
    V p = side ? V(R * sin(alpha * u), -R * cos(alpha * u), h + r) : V(B * u, -R, h - r), m = p;
    double term = 2 * (R * alpha * sinc(alpha * u) - B) / B
                  - (.5 * R * alpha * alpha * pow(sinc(alpha * u / 2), 2) - r) / r;
    m.SetZ(h - dz * (side ? term : 1));
    double a = (1 - v) * (1 - v), b = 2 * w * v * (1 - v), c = v * v;
    return (p * a + m * b + q * c) / (a + b + c);
  }

  V normal(int k, int side, double t) const
  {
    if (side == 0)
      return {0, -1, 0};
    if (side == 2)
      return k ? V(sin(alpha * t), -cos(alpha * t), 0) : V(0, -1, 0);
    if (side == 3)
    {
      double dz = r * (1 - t * t) / 2;
      return V(2 * r * t * dz / B, -dz, r * t * t).Normalized();
    }
    V d = pos(k, 1, t) - V(B, -R + r, h + (k ? r : -r));
    return (d * (k ? -1 : 1)).Normalized();
  }

  TopoDS_Face ribbon(int k) const
  {
    std::vector<double> t(n);
    for (int i = 0; i < n; ++i)
      t[i] = (1 - cos(pi * i / (n - 1))) / 2;
    Spline basic(t, false), herm(t, true);
    Net    ref(n, Row(n)), der(4, Row(n)), along(n, Row(n + 2)), dv(2);
    for (int i = 0; i < n; ++i)
      for (int j = 0; j < n; ++j)
        ref[i][j] = pos(k, t[i], t[j]);
    for (int j = 0; j < n; ++j)
    {
      Row col(n);
      for (int i = 0; i < n; ++i)
        col[i] = ref[i][j];
      auto p = basic.fit(col), q = basic.fit(ref[j]);
      for (int s = 0; s < 4; ++s)
      {
        V v = basic.jet(s < 2 ? p : q, s % 2), N = normal(k, s, t[j]);
        der[s][j] = v - N * v.Dot(N);
      }
    }
    for (int j = 0; j < n; ++j)
    {
      Row col(n);
      for (int i = 0; i < n; ++i)
        col[i] = ref[i][j];
      along[j] = herm.fit(col, der[0][j], der[1][j]);
    }
    for (int end = 0; end < 2; ++end)
    {
      auto d = basic.fit(der[2 + end]);
      V    tw[2];
      for (int j = 0; j < 2; ++j)
        tw[j] = (basic.jet(basic.fit(der[j]), end) + basic.jet(d, j)) * .5;
      dv[end] = herm.fit(der[2 + end], tw[0], tw[1]);
    }
    TColgp_Array2OfPnt poles(1, n + 2, 1, n + 2);
    for (int i = 0; i < n + 2; ++i)
    {
      Row col(n);
      for (int j = 0; j < n; ++j)
        col[j] = along[j][i];
      auto p = herm.fit(col, dv[0][i], dv[1][i]);
      for (int j = 0; j < n + 2; ++j)
        poles(i + 1, j + 1) = gp_Pnt(p[j]);
    }
    TColStd_Array1OfReal    knots(1, n);
    TColStd_Array1OfInteger mult(1, n);
    for (int i = 0; i < n; ++i)
    {
      knots(i + 1) = t[i];
      mult(i + 1)  = i == 0 || i == n - 1 ? 4 : 1;
    }
    return BRepBuilderAPI_MakeFace(new Geom_BSplineSurface(poles, knots, knots, mult, mult, 3, 3),
                                   1e-8)
      .Face();
  }
};

TopoDS_Edge line(V a, V b)
{
  return BRepBuilderAPI_MakeEdge(gp_Pnt(a), gp_Pnt(b)).Edge();
}

TopoDS_Edge arc(V a, V m, V b)
{
  return BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(gp_Pnt(a), gp_Pnt(m), gp_Pnt(b)).Value())
    .Edge();
}

TopoDS_Face cap(std::initializer_list<TopoDS_Edge> edges)
{
  BRepBuilderAPI_MakeWire w;
  for (auto& e : edges)
    w.Add(e);
  return BRepBuilderAPI_MakeFace(w.Wire(), true).Face();
}

TopoDS_Shape strip(const TopoDS_Edge& e, V d)
{
  return BRepPrimAPI_MakePrism(e, gp_Vec(d)).Shape();
}

gp_Pnt at(const BRepAdaptor_Curve& c, double t)
{
  return c.Value((1 - t) * c.FirstParameter() + t * c.LastParameter());
}

TopoDS_Solid build(const Layout& g)
{
  double R = g.R, r = g.r, h = g.h, L = 3 * R, H = 2 * h, B = g.B, alpha = g.alpha;
  auto   circ = [](double rad, double a, double b, double z) {
    auto p = [&](double t) { return V(rad * sin(t), -rad * cos(t), z); };
    return arc(p(a), p((a + b) / 2), p(b));
  };
  auto band = [&](int k, V d = V()) {
    return arc(g.pos(k, 1, 0) + d, g.pos(k, 1, .5) + d, g.pos(k, 1, 1) + d);
  };
  auto tor  = BRepPrimAPI_MakeRevol(band(1), gp_Ax1(gp_Pnt(), gp_Dir(0, 0, 1)), pi - alpha).Shape();
  auto clip = BRepPrimAPI_MakeBox(gp_Pnt(-2 * R, -2 * R, -H), 6 * R, 3 * R, 4 * H).Shape();
  auto clipped = BRepAlgoAPI_Common(tor, clip).Shape();
  TopExp_Explorer ex(clipped, TopAbs_FACE);
  require(ex.More());
  auto face = TopoDS::Face(ex.Current());
  ex.Next();
  require(!ex.More());
  TopoDS_Edge cut;
  for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next())
  {
    auto              e = TopoDS::Edge(it.Current());
    BRepAdaptor_Curve c(e);
    if (std::abs(at(c, .17).Y() - R) < 1e-6 && std::abs(at(c, .5).Y() - R) < 1e-6
        && std::abs(at(c, .83).Y() - R) < 1e-6)
    {
      require(cut.IsNull());
      cut = e;
    }
  }
  require(!cut.IsNull());
  double                X = sqrt((R + r) * (R + r) - R * R), omega = pi - atan2(X, R);
  BRepBuilderAPI_Sewing sew(2e-5);
  sew.Add(g.ribbon(0));
  sew.Add(g.ribbon(1));
  sew.Add(face);
  sew.Add(strip(band(0), {L - B, 0, 0}));
  sew.Add(strip(circ(R, pi, 2 * pi, 0), {0, 0, H}));
  sew.Add(strip(circ(R, 0, pi, h + r), {0, 0, H - h - r}));
  sew.Add(cap({circ(R, 0, pi, H), circ(R, pi, 2 * pi, H)}));
  sew.Add(cap({circ(R, pi, 2 * pi, 0),
               line({0, -R, 0}, {L, -R, 0}),
               line({L, -R, 0}, {L, R, 0}),
               line({L, R, 0}, {0, R, 0})}));
  sew.Add(cap({circ(R + r, alpha, omega, h),
               line({X, R, h}, {L, R, h}),
               line({L, R, h}, {L, -R + r, h}),
               line({L, -R + r, h}, {B, -R + r, h})}));
  sew.Add(strip(line({0, -R, 0}, {L, -R, 0}), {0, 0, h - r}));
  sew.Add(cap({line({0, R, 0}, {L, R, 0}),
               line({L, R, 0}, {L, R, h}),
               line({L, R, h}, {X, R, h}),
               cut,
               line({0, R, h + r}, {0, R, 0})}));
  sew.Add(cap({line({L, -R, 0}, {L, R, 0}),
               line({L, R, 0}, {L, R, h}),
               line({L, R, h}, {L, -R + r, h}),
               band(0, {L - B, 0, 0}),
               line({L, -R, h - r}, {L, -R, 0})}));
  sew.Perform();
  require(!sew.NbFreeEdges() && !sew.NbMultipleEdges()
          && sew.SewedShape().ShapeType() == TopAbs_SHELL);
  auto solid = BRepBuilderAPI_MakeSolid(TopoDS::Shell(sew.SewedShape())).Solid();
  require(BRepLib::OrientClosedSolid(solid) && BRepCheck_Analyzer(solid).IsValid());
  BOPAlgo_CheckerSI si;
  si.SetLevelOfCheck(5);
  si.AddArgument(solid);
  si.Perform();
  require(!si.HasErrors() && si.DS().Interferences().IsEmpty());
  return solid;
}
} // namespace

bool BRepFilletAPI_TangentY::TryBuild(const TopoDS_Solid& s,
                                      const TopoDS_Edge&  e1,
                                      const TopoDS_Edge&  e2,
                                      double              r,
                                      TopoDS_Solid&       out)
{
  try
  {
    if (s.IsNull() || e1.IsNull() || e2.IsNull() || !std::isfinite(r) || r <= 0)
      return false;
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(s, TopAbs_EDGE, edges);
    if (!edges.Contains(e1) || !edges.Contains(e2))
      return false;
    BRepAdaptor_Curve c1(e1), c2(e2);
    auto&             c = c1.GetType() == GeomAbs_Circle ? c1 : c2;
    auto&             l = c1.GetType() == GeomAbs_Circle ? c2 : c1;
    if (c.GetType() != GeomAbs_Circle || l.GetType() != GeomAbs_Line)
      return false;
    auto   circle = c.Circle();
    double R = circle.Radius(), h = circle.Location().Z();
    if (!(r < std::min(h, R)))
      return false;
    auto ends = [](const BRepAdaptor_Curve& e, gp_Pnt a, gp_Pnt b) {
      return (at(e, 0).Distance(a) < 1e-7 && at(e, 1).Distance(b) < 1e-7)
             || (at(e, 0).Distance(b) < 1e-7 && at(e, 1).Distance(a) < 1e-7);
    };
    if (!ends(l, {0, -R, h}, {3 * R, -R, h}) || !ends(c, {0, -R, h}, {0, R, h})
        || at(c, .5).Distance({R, 0, h}) > 1e-7
        || std::abs(c.LastParameter() - c.FirstParameter() - pi) > 1e-9)
      return false;
    // Seed tests alone would erase extra cuts/bosses. Require the complete material
    // domain in BOTH directions and only the expected analytic support faces.
    int planes = 0, cyl = 0;
    for (TopExp_Explorer it(s, TopAbs_FACE); it.More(); it.Next())
    {
      BRepAdaptor_Surface surf(TopoDS::Face(it.Current()));
      if (surf.GetType() == GeomAbs_Cylinder)
        ++cyl;
      else if (surf.GetType() == GeomAbs_Plane)
        ++planes;
      else
        return false;
    }
    if (planes != 6 || cyl != 1 || !BRepCheck_Analyzer(s).IsValid())
      return false;
    auto cylinder =
      BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(), gp_Dir(0, 0, 1), gp_Dir(-1, 0, 0)), R, 2 * h)
        .Shape();
    auto             box = BRepPrimAPI_MakeBox(gp_Pnt(0, -R, 0), 3 * R, 2 * R, h).Shape();
    BRepAlgoAPI_Fuse fuse(cylinder, box);
    fuse.SimplifyResult();
    if (!fuse.IsDone())
      return false;
    for (int i = 0; i < 2; ++i)
    {
      BRepAlgoAPI_Cut      op;
      TopTools_ListOfShape a, b;
      a.Append(i ? fuse.Shape() : s);
      b.Append(i ? s : fuse.Shape());
      op.SetNonDestructive(true);
      op.SetArguments(a);
      op.SetTools(b);
      op.Build();
      if (!op.IsDone() || op.HasWarnings() || TopExp_Explorer(op.Shape(), TopAbs_SOLID).More())
        return false;
    }
    out = build(Layout(R, r, h));
    return true;
  }
  catch (const Standard_Failure&)
  {
    return false;
  }
}
