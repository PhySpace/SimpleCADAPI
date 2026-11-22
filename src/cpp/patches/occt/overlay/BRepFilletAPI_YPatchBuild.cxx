// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
// Construction of the Y transition (see BRepFilletAPI_YPatch.hxx).
#include <BRepFilletAPI_YPatch.hxx>
#include <BRepFilletAPI_YPatchGeom.hxx>

#include <BOPAlgo_CheckerSI.hxx>
#include <BOPDS_DS.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepLib.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <Geom2d_Line.hxx>
#include <Geom_ElementarySurface.hxx>
#include <Geom_SurfaceOfRevolution.hxx>
#include <NCollection_DataMap.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <ShapeFix_Face.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <BRepTools_ReShape.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopTools_MapOfOrientedShape.hxx>
#include <TopoDS_Wire.hxx>
#include <BRepTools.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <string>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GCE2d_MakeSegment.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <functional>
#include <GeomLProp_SLProps.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <Standard_Failure.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <math_Gauss.hxx>

#include <algorithm>
#include <array>
#include <cmath>
#include <memory>
#include <cstdio>
#include <vector>

namespace
{
using namespace YPatch;
using V   = gp_XYZ;
using Row = std::vector<V>;
using Net = std::vector<Row>;

constexpr int    n  = 23; // collocation nodes per direction
constexpr double pi = 3.14159265358979323846;

void require(bool ok, const char* what)
{
  if (!ok)
    throw Standard_Failure(what);
}

// Cubic collocation: not-a-knot for the preliminary jets, clamped Hermite for the final
// tensor product (the construction validated by BRepFilletAPI_TangentY).
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
    require(lu.IsDone(), "YPatch: singular collocation");
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
            b[i] = (l ? (t[j] - k[i]) / l * b[i] : 0) + (r ? (k[i + d + 1] - t[j]) / r * b[i + 1] : 0);
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

std::vector<double> nodes()
{
  std::vector<double> t(n);
  for (int i = 0; i < n; ++i)
    t[i] = (1 - std::cos(pi * i / (n - 1))) / 2;
  return t;
}

//! Four-sided G1 ribbon: reference positions ref[i][j] at (t[i], t[j]) and the target normal
//! of each side (u=0, u=1 along v; v=0, v=1 along u).  Cross-boundary derivatives are
//! projected into the target tangent planes; corner twists are averaged.
Handle(Geom_BSplineSurface) ribbon(const std::vector<double>& t,
                                   const Net&                 ref,
                                   const std::array<Row, 4>&  normal,
                                   const V&                   seam0,
                                   const V&                   seam1)
{
  Spline basic(t, false), herm(t, true);
  Net    der(4, Row(n)), along(n, Row(n + 2)), dv(2);
  for (int j = 0; j < n; ++j)
  {
    Row col(n);
    for (int i = 0; i < n; ++i)
      col[i] = ref[i][j];
    auto p = basic.fit(col), q = basic.fit(ref[j]);
    for (int s = 0; s < 4; ++s)
    {
      V v = basic.jet(s < 2 ? p : q, s % 2), N = normal[s][j];
      der[s][j] = v - N * v.Dot(N);
    }
  }
  // the v = 1 side is shared with the other ribbon: use the seam's exact end derivatives so
  // that both ribbons interpolate the same seam curve
  der[0][n - 1] = seam0;
  der[1][n - 1] = seam1;
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
  return new Geom_BSplineSurface(poles, knots, knots, mult, mult, 3, 3);
}

gp_Vec unit(const gp_Vec& v)
{
  const double m = v.Magnitude();
  require(m > 1e-14, "YPatch: degenerate direction");
  return v / m;
}

// 3D vector a expressed in the uv tangent basis of S at uv (least squares).
gp_Vec2d toUV(const Support& S, const gp_Pnt2d& uv, const gp_Vec& a)
{
  gp_Pnt p;
  gp_Vec du, dv;
  S.s.D1(uv.X(), uv.Y(), p, du, dv);
  const double g11 = du.Dot(du), g12 = du.Dot(dv), g22 = dv.Dot(dv);
  const double b1 = a.Dot(du), b2 = a.Dot(dv), det = g11 * g22 - g12 * g12;
  require(std::abs(det) > 1e-20, "YPatch: singular surface metric");
  return gp_Vec2d((g22 * b1 - g12 * b2) / det, (g11 * b2 - g12 * b1) / det);
}

double cross2(const gp_XY& a, const gp_XY& b)
{
  return a.X() * b.Y() - a.Y() * b.X();
}

//! Everything computed for one junction.
struct Work
{
  const BRepFilletAPI_YPatch::Junction& j;
  Support                               T, A, B;
  Rail                                  ri, ro;
  Band                                  bi, bo;
  double                                l1 = 0, l2 = 0;
  std::vector<double>                   t;
  std::vector<Ball>                     in, out; // at the u nodes
  Handle(Geom_BSplineSurface)           rib[2];  // 0: convex side (B), 1: concave side (A)
  Net                                   refs[2];  // their collocation data
  std::array<Row, 4>                    nrms[2];
  V                                     seam0, seam1;
  Handle(Geom_Surface)                  bandSurf[2]; // the band each ribbon was fitted to (if refitted)
  gp_Pnt2d                              keepOutT, keepOutA, keepOutB;
  std::vector<TopoDS_Edge>              cuts;
  std::vector<TopoDS_Face>              fillers, fillerOf; // margin mode: strip faces and their supports

  explicit Work(const BRepFilletAPI_YPatch::Junction& jj)
      : j(jj),
        T(jj.Common),
        A(jj.Concave2),
        B(jj.Convex2),
        ri(jj.Concave, jj.Vertex),
        ro(jj.Convex, jj.Vertex),
        bi{ri, T, A, jj.RConcave, +1.},
        bo{ro, T, B, jj.RConvex, -1.},
        t(nodes())
  {
  }

  // P*: the first crossing, from V, of the two contact curves on T.
  void Split()
  {
    const int         N = 128;
    std::vector<Ball> I(N + 1), O(N + 1);
    for (int k = 0; k <= N; ++k)
    {
      require(bi.Solve(double(k) / N, I[k], k ? &I[k - 1] : nullptr), "YPatch: concave ball");
      require(bo.Solve(double(k) / N, O[k], k ? &O[k - 1] : nullptr), "YPatch: convex ball");
    }
    double best = 1e300;
    for (int a = 0; a < N; ++a)
      for (int b = 0; b < N; ++b)
      {
        const gp_XY p = I[a].uvT.XY(), r = I[a + 1].uvT.XY() - p;
        const gp_XY q = O[b].uvT.XY(), s = O[b + 1].uvT.XY() - q;
        const double d = cross2(r, s);
        if (std::abs(d) < 1e-300)
          continue;
        const double x = cross2(q - p, s) / d, y = cross2(q - p, r) / d;
        if (x < 0 || x > 1 || y < 0 || y > 1)
          continue;
        const double key = a + x + b + y;
        if (key < best)
        {
          best = key;
          l1   = (a + x) / N;
          l2   = (b + y) / N;
        }
      }
    require(best < 1e299, "YPatch: the bands do not cross within the edges");
    // Newton on (l1, l2): equal contacts on T.
    Ball a = I[std::min(N, int(l1 * N))], b = O[std::min(N, int(l2 * N))];
    for (int it = 0; it < 40; ++it)
    {
      Ball a0, b0;
      require(bi.Solve(l1, a0, &a) && bo.Solve(l2, b0, &b), "YPatch: split balls");
      a = a0;
      b = b0;
      const gp_XY g = a.uvT.XY() - b.uvT.XY();
      if (a.pT.Distance(b.pT) < 1e-10 * (1 + bi.r))
        break;
      const double h = 1e-7;
      Ball         a1, b1;
      require(bi.Solve(l1 + h, a1, &a) && bo.Solve(l2 + h, b1, &b), "YPatch: split jacobian");
      const gp_XY ja = (a1.uvT.XY() - a.uvT.XY()) / h, jb = (b1.uvT.XY() - b.uvT.XY()) / -h;
      const double det = cross2(ja, jb);
      require(std::abs(det) > 1e-300, "YPatch: tangent contact curves at P*");
      l1 -= cross2(g, jb) / det;
      l2 -= cross2(ja, g) / det;
      require(l1 > 0 && l1 <= 1 && l2 > 0 && l2 <= 1, "YPatch: P* outside the edges");
    }
    require(a.pT.Distance(b.pT) < 1e-8 * (1 + bi.r), "YPatch: P* did not converge");
  }

  // Sections at the u nodes (u=0: V, u=1: P*).
  void Sections()
  {
    in.resize(n);
    out.resize(n);
    for (int i = 0; i < n; ++i)
    {
      require(bi.Solve(t[i] * l1, in[i], i ? &in[i - 1] : nullptr), "YPatch: ribbon ball (concave)");
      require(bo.Solve(t[i] * l2, out[i], i ? &out[i - 1] : nullptr), "YPatch: ribbon ball (convex)");
    }
  }

  void Ribbons()
  {
    const gp_Pnt   v   = ri.P(0);
    const gp_Pnt2d uvV = ri.UV(T.face, 0), uvS = in[n - 1].uvT;
    const gp_Pnt   pS  = T.P(uvS);
    const double   L   = v.Distance(pS);
    // seam on T: cubic Hermite in uv, leaving V along the bisector of the two edges and
    // reaching P* along the bisector of the two contact curves.
    auto contactTangent = [&](const Band& band, double l, const Ball& seed) {
      Ball a, b;
      require(band.Solve(l - 1e-6, a, &seed) && band.Solve(l, b, &seed), "YPatch: contact tangent");
      return unit(gp_Vec(a.pT, b.pT));
    };
    const gp_Vec t0 = unit(ri.T(0) + ro.T(0)) * L;
    const gp_Vec t1 = unit(contactTangent(bi, l1, in[n - 1]) + contactTangent(bo, l2, out[n - 1])) * L;
    const gp_Vec2d d0 = toUV(T, uvV, t0), d1 = toUV(T, uvS, t1);
    auto seam = [&](double u, gp_Vec* der) {
      const double h00 = 2 * u * u * u - 3 * u * u + 1, h10 = u * u * u - 2 * u * u + u;
      const double h01 = -2 * u * u * u + 3 * u * u, h11 = u * u * u - u * u;
      const gp_XY  uv  = uvV.XY() * h00 + d0.XY() * h10 + uvS.XY() * h01 + d1.XY() * h11;
      if (der)
      {
        const double g00 = 6 * u * u - 6 * u, g10 = 3 * u * u - 4 * u + 1, g01 = -6 * u * u + 6 * u,
                     g11 = 3 * u * u - 2 * u;
        const gp_XY d = uvV.XY() * g00 + d0.XY() * g10 + uvS.XY() * g01 + d1.XY() * g11;
        gp_Pnt      p;
        gp_Vec      du, dv;
        T.s.D1(uv.X(), uv.Y(), p, du, dv);
        *der = du * d.X() + dv * d.Y();
      }
      return gp_Pnt2d(uv);
    };
    const gp_Vec nV = unit(A.N(ri.UV(A.face, 0)) + B.N(ro.UV(B.face, 0)));
    const double rr = 0.5 * (bi.r + bo.r);
    std::vector<gp_Pnt> q(n);
    std::vector<gp_Vec> N(n), Qd(n);
    gp_Vec              qd0, qd1;
    seam(0., &qd0);
    seam(1., &qd1);
    for (int i = 0; i < n; ++i)
    {
      gp_Vec         d;
      const gp_Pnt2d uv = seam(t[i], &d);
      q[i]              = T.P(uv);
      const double u = t[i], dz = rr * (1 - u * u) / 2;
      gp_Vec       w = nV * dz + T.N(uv) * (rr * u * u);
      const gp_Vec e = unit(d);
      N[i]           = unit(w - e * w.Dot(e));
      Qd[i]          = d;
    }
    q[0]     = v;
    q[n - 1] = pS;
    for (int k = 0; k < 2; ++k)
    {
      const Support&           X  = k ? A : B;
      const std::vector<Ball>& bs = k ? in : out;
      const gp_Pnt             c1 = bs[n - 1].c;
      Net                      ref(n, Row(n));
      std::array<Row, 4>       nrm{Row(n), Row(n), Row(n), Row(n)};
      for (int i = 0; i < n; ++i)
      {
        const gp_Pnt p  = bs[i].pX;
        const gp_Vec ns = X.N(bs[i].uvX);
        const gp_Vec D(p, q[i]);
        gp_Pnt       m = gp_Pnt((p.XYZ() + q[i].XYZ()) / 2);
        double       w = std::sqrt(.5);
        bool         exact = false; // the circular section exists (tangent lines meet ahead)
        if (D.Magnitude() > 1e-12 && ns.Crossed(D).Magnitude() > 1e-9 * D.Magnitude())
        {
          const gp_Vec pl = unit(ns.Crossed(D));
          gp_Vec       tp = unit(pl.Crossed(ns));
          if (tp.Dot(D) < 0)
            tp.Reverse();
          gp_Vec nq = N[i] - pl * N[i].Dot(pl);
          if (nq.Magnitude() > 1e-9)
          {
            gp_Vec tq = unit(pl.Crossed(nq));
            if (tq.Dot(D) > 0)
              tq.Reverse();
            // p + a tp = q + b tq
            const double c = tp.Dot(tq), det = c * c - 1;
            if (std::abs(det) > 1e-8)
            {
              const double a = (D.Dot(tq) * c - D.Dot(tp)) / det, b = (D.Dot(tq) - c * D.Dot(tp)) / det;
              if (a > 0 && b > 0)
              {
                m             = p.Translated(tp * a);
                const gp_Vec e1(m, p), e2(m, q[i]);
                if (e1.Magnitude() > 1e-12 && e2.Magnitude() > 1e-12)
                {
                  w     = std::sin(e1.Angle(e2) / 2);
                  exact = true;
                }
              }
            }
          }
        }
        // Cubic section: leaves p inside the support, arrives at q straight across the seam
        // (the two ribbons arrive from opposite sides).  Near the bands it blends into the
        // exact circular section, which the band end requires.
        gp_Vec tp = D - ns * D.Dot(ns), tq = N[i].Crossed(Qd[i]);
        const bool cubic = tp.Magnitude() > 1e-12 && tq.Magnitude() > 1e-12;
        if (cubic)
        {
          tp.Normalize();
          tq.Normalize();
          if (tq.Dot(D) < 0)
            tq.Reverse();
        }
        const double th    = cubic ? std::min(tp.Angle(tq), 2.5) : 0.;
        const double alpha = th > 1e-4 ? 4. / 3. * std::tan(th / 4) * D.Magnitude() / (2 * std::sin(th / 2))
                                       : D.Magnitude() / 3;
        const double u = t[i], s = !exact ? 0. : u <= .6 ? 0. : u >= 1. ? 1. : [](double x) {
          return x * x * (3 - 2 * x);
        }((u - .6) / .4);
        require(cubic || exact, "YPatch: degenerate ribbon section");
        for (int jj = 0; jj < n; ++jj)
        {
          const double vv = t[jj], a = (1 - vv) * (1 - vv), b = 2 * w * vv * (1 - vv), c = vv * vv;
          const V      con = (p.XYZ() * a + m.XYZ() * b + q[i].XYZ() * c) / (a + b + c);
          V            cub = con;
          if (cubic)
          {
            const double o = 1 - vv;
            cub = p.XYZ() * (o * o * o) + (p.XYZ() + tp.XYZ() * alpha) * (3 * o * o * vv)
                  + (q[i].XYZ() - tq.XYZ() * alpha) * (3 * o * vv * vv) + q[i].XYZ() * (vv * vv * vv);
          }
          ref[i][jj] = cub * (1 - s) + con * s;
        }
        require(i < n - 1 || exact, "YPatch: no circular section at the band end");
        nrm[2][i] = ns.XYZ();
        nrm[3][i] = N[i].XYZ();
      }
      // u = 0 lies on the support, u = 1 on the band.
      for (int jj = 0; jj < n; ++jj)
      {
        const gp_Pnt2d uv = X.UVNear(gp_Pnt(ref[0][jj]), bs[0].uvX);
        ref[0][jj]        = X.P(uv).XYZ();
        nrm[0][jj]        = X.N(uv).XYZ();
        nrm[1][jj]        = unit(gp_Vec(c1, gp_Pnt(ref[n - 1][jj]))).XYZ();
      }
      rib[k]  = ribbon(t, ref, nrm, qd0.XYZ(), qd1.XYZ());
      refs[k] = ref;
      nrms[k] = nrm;
      seam0   = qd0.XYZ();
      seam1   = qd1.XYZ();
    }
  }

  // Edges that cut V's wedge out of T, A and B; interior points of the removed pieces.

  // The standard algorithm ends each band on its own (possibly approximated) spine: refit the
  // ribbons' band-side row (u = 1) to the band end it actually built.  The other three sides,
  // which the cuts already use, keep their data.
  void FitBandEnds(const TopoDS_Shape& filleted)
  {
    TopTools_IndexedDataMapOfShapeListOfShape ef;
    TopExp::MapShapesAndAncestors(filleted, TopAbs_EDGE, TopAbs_FACE, ef);
    const gp_Pnt split = in[n - 1].pT;
    for (int k = 0; k < 2; ++k)
    {
      const gp_Pnt foot = (k ? in : out)[n - 1].pX;
      TopoDS_Edge  best;
      TopoDS_Face  band;
      double       bulge = 0;
      for (int i = 1; i <= ef.Extent(); ++i)
      {
        if (ef(i).Extent() != 1)
          continue;
        const TopoDS_Edge e = TopoDS::Edge(ef.FindKey(i));
        BRepAdaptor_Curve c(e);
        const gp_Pnt      a = c.Value(c.FirstParameter()), z = c.Value(c.LastParameter());
        const bool        fits = (a.Distance(foot) < 1e-3 && z.Distance(split) < 1e-3)
                          || (z.Distance(foot) < 1e-3 && a.Distance(split) < 1e-3);
        const gp_Pnt      m = c.Value((c.FirstParameter() + c.LastParameter()) / 2);
        const double      b = m.Distance(gp_Pnt((a.XYZ() + z.XYZ()) / 2));
        if (fits && b > bulge)
        {
          bulge = b;
          best  = e;
          band  = TopoDS::Face(ef(i).First());
        }
      }
      if (best.IsNull())
        continue;
      // node positions by arc length, from the support (v = 0) to the seam (v = 1)
      Net&                ref = refs[k];
      std::vector<double> s(n, 0.);
      for (int j = 1; j < n; ++j)
        s[j] = s[j - 1] + (ref[n - 1][j] - ref[n - 1][j - 1]).Modulus();
      BRepAdaptor_Curve c(best);
      const bool        forward = c.Value(c.FirstParameter()).Distance(foot) < c.Value(c.LastParameter()).Distance(foot);
      const double      length  = GCPnts_AbscissaPoint::Length(c);
      Handle(Geom_Surface) surf = BRep_Tool::Surface(band);
      for (int j = 1; j < n - 1; ++j)
      {
        const double             d = length * s[j] / s[n - 1];
        GCPnts_AbscissaPoint     ap(c, forward ? d : -d, forward ? c.FirstParameter() : c.LastParameter());
        require(ap.IsDone(), "YPatch: band end abscissa");
        const gp_Pnt             p = c.Value(ap.Parameter());
        GeomAPI_ProjectPointOnSurf pr(p, surf);
        require(pr.NbPoints() > 0, "YPatch: band end normal");
        double u, v;
        pr.LowerDistanceParameters(u, v);
        GeomLProp_SLProps lp(surf, u, v, 1, 1e-12);
        require(lp.IsNormalDefined(), "YPatch: band end normal");
        ref[n - 1][j]  = p.XYZ();
        nrms[k][1][j]  = lp.Normal().XYZ();
      }
      rib[k]      = ribbon(t, ref, nrms[k], seam0, seam1);
      bandSurf[k] = surf;
    }
  }

  // margin = false: A and B are cut along the ribbons' support boundaries.  That free edge
  // continues the band's own contact line, tangentially: when the standard algorithm ends
  // the band on an approximated spine, its end can slide along it.  margin = true: A and B
  // are cut a little further from the edge, so the band end meets its free boundary
  // transversally; the strip between the contact line and the cut is given back as a
  // `filler` face on the support's own surface.
  void Cuts(bool margin)
  {
    cuts.clear();
    fillers.clear();
    fillerOf.clear();
    auto onFace = [](const Support& S, const Handle(Geom2d_Curve)& c) {
      TopoDS_Edge e = BRepBuilderAPI_MakeEdge(c, BRep_Tool::Surface(S.face)).Edge();
      BRepLib::BuildCurves3d(e);
      return e;
    };
    auto segment = [&](const Support& S, const gp_Pnt2d& a, const gp_Pnt2d& b) {
      return onFace(S, GCE2d_MakeSegment(a, b).Value());
    };
    auto through = [&](const Support& S, const std::vector<gp_Pnt2d>& pts) {
      Handle(TColgp_HArray1OfPnt2d) h = new TColgp_HArray1OfPnt2d(1, int(pts.size()));
      for (std::size_t i = 0; i < pts.size(); ++i)
        h->SetValue(int(i) + 1, pts[i]);
      Geom2dAPI_Interpolate ip(h, Standard_False, 1e-12);
      ip.Perform();
      require(ip.IsDone(), "YPatch: margin curve");
      Handle(Geom2d_Curve) c = ip.Curve();
      return onFace(S, c);
    };
    auto iso = [](const Handle(Geom_Curve)& c) {
      return BRepBuilderAPI_MakeEdge(c).Edge();
    };
    const Ball& a = in[n - 1];
    const Ball& b = out[n - 1];
    // Each band ends at a free-boundary vertex whose two free edges hold its end section:
    // the standard algorithm cuts the supports there.
    cuts.push_back(segment(T, ri.UV(T.face, l1), a.uvT));
    cuts.push_back(segment(T, ro.UV(T.face, l2), b.uvT));
    if (!margin)
    {
      cuts.push_back(segment(A, ri.UV(A.face, l1), a.uvX));
      cuts.push_back(segment(B, ro.UV(B.face, l2), b.uvX));
      // ribbon boundaries on the supports: v = 0 (contact curve) and u = 0 (back to V)
      cuts.push_back(iso(rib[1]->VIso(0.)));
      cuts.push_back(iso(rib[1]->UIso(0.)));
      cuts.push_back(iso(rib[0]->VIso(0.)));
      cuts.push_back(iso(rib[0]->UIso(0.)));
    }
    else
      for (int k = 0; k < 2; ++k)
      {
        const Support&           X    = k ? A : B;
        const Rail&              rail = k ? ri : ro;
        const double             l = k ? l1 : l2, d = 0.1 * (k ? bi.r : bo.r);
        const std::vector<Ball>& bs   = k ? in : out;
        Handle(Geom_Curve)       C    = rib[k]->VIso(0.);
        const int                m    = 33;
        std::vector<gp_Pnt2d>    c(m), o(m);
        for (int i = 0; i < m; ++i)
        {
          const double u = double(i) / (m - 1);
          c[i]           = X.UVNear(C->Value(u), bs[std::min(n - 1, int(u * (n - 1)))].uvX);
          gp_XY  away    = c[i].XY() - rail.UV(X.face, u * l).XY();
          gp_Pnt p;
          gp_Vec du, dv;
          X.s.D1(c[i].X(), c[i].Y(), p, du, dv);
          const double s = (du * away.X() + dv * away.Y()).Magnitude();
          require(s > 1e-12, "YPatch: margin direction");
          o[i] = gp_Pnt2d(c[i].XY() + away * (d / s));
        }
        // the cuts: section line beyond the band end, the offset of the contact line, the
        // line from V beyond the ribbon's foot
        cuts.push_back(segment(X, rail.UV(X.face, l), o[m - 1]));
        cuts.push_back(through(X, o));
        cuts.push_back(iso(rib[k]->UIso(0.))); // the ribbon's foot, V to the contact line
        cuts.push_back(segment(X, c[0], o[0]));
        // the strip between the contact line and the cut, on X's surface
        BRepBuilderAPI_MakeWire mw;
        mw.Add(through(X, c));
        mw.Add(segment(X, c[m - 1], o[m - 1]));
        mw.Add(cuts[cuts.size() - 3]);
        mw.Add(segment(X, o[0], c[0]));
        require(mw.IsDone(), "YPatch: margin wire");
        TopoDS_Face f = BRepBuilderAPI_MakeFace(BRep_Tool::Surface(X.face), mw.Wire(), Standard_True).Face();
        ShapeFix_Face fix(f);
        fix.Perform();
        fillers.push_back(fix.Face());
        fillerOf.push_back(X.face);
      }
    Ball m1, m2;
    require(bi.Solve(l1 / 2, m1, &in[n / 2]) && bo.Solve(l2 / 2, m2, &out[n / 2]), "YPatch: probe");
    keepOutT = gp_Pnt2d((ri.UV(T.face, l1 / 2).XY() + ro.UV(T.face, l2 / 2).XY()) / 2);
    keepOutA = gp_Pnt2d((ri.UV(A.face, l1 / 2).XY() + m1.uvX.XY()) / 2);
    keepOutB = gp_Pnt2d((ro.UV(B.face, l2 / 2).XY() + m2.uvX.XY()) / 2);
  }
};

// Largest angle between the unit normals of s1 at (u1, v1) and s2 at (u2, v2) on sampled
// matching boundary parameters, ignoring orientation.
double boundaryAngle(const Handle(Geom_Surface)& s,
                     bool                         alongU,
                     double                       fixed,
                     const std::function<gp_Vec(const gp_Pnt&)>& target)
{
  double worst = 0;
  for (int i = 0; i <= 100; ++i)
  {
    const double      x = i / 100., u = alongU ? x : fixed, v = alongU ? fixed : x;
    GeomLProp_SLProps pr(s, u, v, 1, 1e-12);
    if (!pr.IsNormalDefined())
      continue;
    const gp_Vec a(pr.Normal()), b = target(pr.Value());
    if (b.Magnitude() < 1e-12)
      continue;
    const double ang = std::min(a.Angle(b), pi - a.Angle(b));
#ifdef YPATCH_TRACE
    if (ang > 1e-3)
      std::printf("  angle %.4f deg at %s=%.3f\n", ang * 180 / pi, alongU ? "u" : "v", x);
#endif
    worst = std::max(worst, ang);
  }
  return worst;
}

gp_Pnt midPoint(const TopoDS_Edge& e)
{
  BRepAdaptor_Curve c(e);
  return c.Value((c.FirstParameter() + c.LastParameter()) / 2);
}

bool inFace(const TopoDS_Face& f, const gp_Pnt2d& uv)
{
  BRepClass_FaceClassifier c(f, uv, 1e-7);
  return c.State() == TopAbs_IN;
}

} // namespace

// The Y patch on a shape whose periodic supports have their seams clear of the bands.
static Standard_Boolean performOn(const TopoDS_Shape&                                 theShape,
                                  const TopTools_DataMapOfShapeReal&                  theRadii,
                                  TopoDS_Shape&                                       theResult,
                                  Handle(BRepTools_History)&                          theHistory,
                                  NCollection_Vector<BRepFilletAPI_YPatch::Junction>& theReport)
{
  using Junction = BRepFilletAPI_YPatch::Junction;
  try
  {
    NCollection_Vector<Junction> js = BRepFilletAPI_YPatch::Detect(theShape, theRadii);
    if (js.IsEmpty())
      return Standard_False;
    std::vector<std::unique_ptr<Work>> works;
    for (const Junction& j : js)
    {
      works.push_back(std::make_unique<Work>(j));
      Work& w = *works.back();
      w.Split();
      w.Sections();
      w.Ribbons();
    }
    auto attempt = [&](const bool margin) -> bool {
      try
      {
    // 1. Cut each wedge out of the boundary.
    BRepAlgoAPI_Splitter split;
    TopTools_ListOfShape args, tools;
    args.Append(theShape);
    for (auto& w : works)
      w->Cuts(margin);
    for (auto& w : works)
      for (auto& e : w->cuts)
        tools.Append(e);
    split.SetArguments(args);
    split.SetTools(tools);
    split.SetFuzzyValue(1e-6);
    split.Build();
    require(split.IsDone() && !split.HasErrors(), "YPatch: splitting the supports failed");
    auto image = [&](const TopoDS_Shape& s) {
      TopTools_ListOfShape l = split.Modified(s);
      if (l.IsEmpty() && !split.IsDeleted(s))
        l.Append(s);
      return l;
    };
    TopTools_MapOfShape drop;
    for (auto& w : works)
    {
      const std::pair<const Support*, gp_Pnt2d> probes[] = {{&w->T, w->keepOutT}, {&w->A, w->keepOutA}, {&w->B, w->keepOutB}};
      for (const auto& pr : probes)
      {
        int                        hits = 0;
        const TopTools_ListOfShape pieces = image(pr.first->face);
        for (TopTools_ListOfShape::Iterator it(pieces); it.More(); it.Next())
          if (inFace(TopoDS::Face(it.Value()), pr.second))
          {
            drop.Add(it.Value());
            ++hits;
          }
#ifdef YPATCH_TRACE
        std::printf("YPatch: support pieces %d, wedge hits %d\n", pieces.Extent(), hits);
#endif
        require(hits == 1, "YPatch: the wedge was not cut out of a support");
      }
    }
    BRep_Builder b;
    TopoDS_Shell shell;
    b.MakeShell(shell);
    for (TopExp_Explorer ex(split.Shape(), TopAbs_FACE); ex.More(); ex.Next())
      if (!drop.Contains(ex.Current()))
        b.Add(shell, ex.Current());
    // 2. Standard fillet of everything else on the open shell, in two passes: the convex band
    // ends of the junctions go second.  A single run that ends two bands at the same
    // free-boundary vertex (P*) is numerically marginal for the standard algorithm.
#ifdef YPATCH_TRACE
    BRepTools::Write(shell, "trace-shell.brep");
#endif
    TopTools_MapOfShape late; // pieces of the junctions' convex edges
    for (auto& w : works)
    {
      const TopTools_ListOfShape pieces = image(w->j.Convex);
      for (TopTools_ListOfShape::Iterator p(pieces); p.More(); p.Next())
        late.Add(p.Value());
    }
    // the requested pieces still bounding two faces, as instances of `of`
    struct Seed
    {
      TopoDS_Shape input; // requested edge
      TopoDS_Edge  piece; // its piece in the open shell
      double       r;
    };
    std::vector<Seed> seeds[2];
    {
      TopTools_IndexedDataMapOfShapeListOfShape ef;
      TopExp::MapShapesAndAncestors(shell, TopAbs_EDGE, TopAbs_FACE, ef);
      for (TopTools_DataMapOfShapeReal::Iterator it(theRadii); it.More(); it.Next())
      {
        const TopTools_ListOfShape pieces = image(it.Key());
        for (TopTools_ListOfShape::Iterator p(pieces); p.More(); p.Next())
        {
          const int index = ef.FindIndex(p.Value());
          if (index == 0 || ef(index).Extent() != 2)
            continue;
          const TopoDS_Edge piece = TopoDS::Edge(ef.FindKey(index)); // the shell's own instance
          // late when its tangent chain holds a convex junction edge (the chain moves as one)
          bool isLate = late.Contains(piece);
          if (!isLate)
          {
            BRepFilletAPI_MakeFillet probe(shell);
            probe.Add(it.Value(), piece);
            for (int ie = 1; probe.NbContours() > 0 && ie <= probe.NbEdges(1) && !isLate; ++ie)
              isLate = late.Contains(probe.Edge(1, ie));
          }
          seeds[isLate ? 1 : 0].push_back({it.Key(), piece, it.Value()});
        }
      }
    }
    std::unique_ptr<BRepFilletAPI_MakeFillet> pass[2];
    TopTools_IndexedMapOfShape                kept[2]; // sub-shapes of each pass's result
    TopoDS_Shape                              current = shell;
    // the images of s (a sub-shape of the input of pass k) in its result
    auto passImage = [&](int k, const TopoDS_Shape& s) {
      if (!pass[k])
      {
        TopTools_ListOfShape l;
        l.Append(s);
        return l;
      }
      TopTools_ListOfShape l = pass[k]->Modified(s); // IsDeleted answers for faces only
      if (l.IsEmpty() && kept[k].Contains(s))
        l.Append(s);
      return l;
    };
    for (int k = 0; k < 2; ++k)
    {
      if (seeds[k].empty())
        continue;
      pass[k] = std::make_unique<BRepFilletAPI_MakeFillet>(current);
      TopTools_IndexedDataMapOfShapeListOfShape ef;
      TopExp::MapShapesAndAncestors(current, TopAbs_EDGE, TopAbs_FACE, ef);
      for (Seed& s : seeds[k])
      {
        TopoDS_Edge e = s.piece;
        if (k == 1 && pass[0])
        {
          const TopTools_ListOfShape now = passImage(0, e);
          require(now.Extent() == 1, "YPatch: a convex band edge was changed by the first pass");
          e = TopoDS::Edge(now.First());
        }
        const int index = ef.FindIndex(e);
        require(index != 0 && ef(index).Extent() == 2, "YPatch: a fillet edge is not between two faces");
        s.piece = TopoDS::Edge(ef.FindKey(index));
      }
      // Tangent propagation is not symmetric on a cut shell (from one piece the chain may stop
      // at a vertex it crosses from the other side), and an edge in two contours gets two
      // bands.  Seed the longest chains first and skip seeds already covered.
      std::vector<std::pair<int, std::size_t>> order; // (chain length, seed)
      for (std::size_t i = 0; i < seeds[k].size(); ++i)
      {
        BRepFilletAPI_MakeFillet probe(current);
        probe.Add(seeds[k][i].r, seeds[k][i].piece);
        order.emplace_back(probe.NbContours() ? probe.NbEdges(1) : 0, i);
      }
      std::stable_sort(order.begin(), order.end(), [](const auto& a, const auto& b) { return a.first > b.first; });
      for (const auto& o : order)
      {
        const Seed& s = seeds[k][o.second];
        if (pass[k]->Contour(s.piece) == 0)
          pass[k]->Add(s.r, s.piece);
      }
#ifdef YPATCH_TRACE
      for (int ic = 1; ic <= pass[k]->NbContours(); ++ic)
        for (int ie = 1; ie <= pass[k]->NbEdges(ic); ++ie)
        {
          const gp_Pnt m = midPoint(pass[k]->Edge(ic, ie));
          std::printf("YPatch: pass %d contour %d edge (%.3f %.3f %.3f)\n", k, ic, m.X(), m.Y(), m.Z());
        }
#endif
      pass[k]->Build();
#ifdef YPATCH_TRACE
      if (!pass[k]->IsDone())
        std::printf("YPatch: pass %d: contours %d faulty contours %d faulty vertices %d\n", k, pass[k]->NbContours(),
                    pass[k]->NbFaultyContours(), pass[k]->NbFaultyVertices());
#endif
      require(pass[k]->IsDone(), "YPatch: the standard fillet of the remaining edges failed");
      current = pass[k]->Shape();
      TopExp::MapShapes(current, kept[k]);
    }
    for (auto& w : works)
    {
      w->bandSurf[0].Nullify();
      w->bandSurf[1].Nullify();
      w->FitBandEnds(current);
    }
    // 3. The free boundary must be exactly the ribbons' outline.  A free edge away from every
    // ribbon is a remnant of a cut the standard algorithm left in a support's wire (seen for
    // small radii): drop it from its wire; validity is checked on the final solid.
    std::vector<TopoDS_Face> ribbons;
    for (auto& w : works)
      for (int k = 0; k < 2; ++k)
        ribbons.push_back(BRepBuilderAPI_MakeFace(w->rib[k], 1e-7).Face());
    Handle(BRepTools_ReShape) reshape = new BRepTools_ReShape();
    TopoDS_Shape              filleted = current;
    {
      TopTools_IndexedDataMapOfShapeListOfShape fe;
      TopExp::MapShapesAndAncestors(filleted, TopAbs_EDGE, TopAbs_FACE, fe);
      TopTools_MapOfShape stray;
      for (int i = 1; i <= fe.Extent(); ++i)
      {
        if (fe(i).Extent() != 1)
          continue;
        const gp_Pnt p     = midPoint(TopoDS::Edge(fe.FindKey(i)));
        bool         onRib = false;
        for (auto& w : works)
          for (int k = 0; k < 2 && !onRib; ++k)
          {
            GeomAPI_ProjectPointOnSurf pr(p, w->rib[k]);
            onRib = pr.NbPoints() > 0 && pr.LowerDistance() < 1e-4;
          }
        for (auto& w : works)
          for (std::size_t k = 0; k < w->fillers.size() && !onRib; ++k)
          {
            BRepExtrema_DistShapeShape dist(BRepBuilderAPI_MakeVertex(p).Vertex(), w->fillers[k]);
            onRib = dist.IsDone() && dist.Value() < 1e-4;
          }
        if (!onRib)
        {
#ifdef YPATCH_TRACE
          std::printf("YPatch: stray free edge at (%.4f %.4f %.4f)\n", p.X(), p.Y(), p.Z());
#endif
          stray.Add(fe.FindKey(i));
        }
      }
      // Also seen on a periodic support cut by the wedge: a wire holding the same edge twice
      // with the same orientation (only a seam may appear twice, and then reversed).
      TopTools_IndexedMapOfShape faces;
      for (TopTools_MapOfShape::Iterator it(stray); it.More(); it.Next())
        faces.Add(fe.FindFromKey(it.Value()).First());
      for (TopExp_Explorer fx(filleted, TopAbs_FACE); fx.More(); fx.Next())
        for (TopoDS_Iterator wi(fx.Current()); wi.More(); wi.Next())
        {
          TopTools_MapOfOrientedShape seen;
          for (TopoDS_Iterator ei(wi.Value()); ei.More(); ei.Next())
            if (!seen.Add(ei.Value()))
              faces.Add(fx.Current());
        }
      BRep_Builder bb;
      for (int i = 1; i <= faces.Extent(); ++i)
      {
        const TopoDS_Face f  = TopoDS::Face(faces(i));
        TopoDS_Face       f2 = TopoDS::Face(f.EmptyCopied());
        for (TopoDS_Iterator wi(f); wi.More(); wi.Next())
        {
          TopoDS_Wire                 w2 = TopoDS::Wire(wi.Value().EmptyCopied());
          TopTools_MapOfOrientedShape seen;
          for (TopoDS_Iterator ei(wi.Value()); ei.More(); ei.Next())
            if (!stray.Contains(ei.Value()) && seen.Add(ei.Value()))
              bb.Add(w2, ei.Value());
          w2.Closed(BRep_Tool::IsClosed(w2));
          bb.Add(f2, w2);
        }
#ifdef YPATCH_TRACE
        std::printf("YPatch: rebuilt the wires of a support face\n");
#endif
        reshape->Replace(f, f2);
      }
      if (!faces.IsEmpty())
        filleted = reshape->Apply(filleted);
    }
    // 4. Close with the ribbons.  The standard algorithm ends a band on an approximated spine
    // (e.g. an ellipse on an inclined face): its end section may then differ from the exact
    // one by a few 1e-4 r.  Sew tight first, then once with a tolerance bounded by the radii.
    double rmax = 0;
    for (auto& w : works)
      rmax = std::max({rmax, w->bi.r, w->bo.r});
    std::unique_ptr<BRepBuilderAPI_Sewing> sewing;
    for (const double tol : {1e-5, 1e-4 * std::max(1., rmax)})
    {
      sewing = std::make_unique<BRepBuilderAPI_Sewing>(tol);
      sewing->Add(filleted);
      for (const TopoDS_Face& f : ribbons)
        sewing->Add(f);
      for (auto& w : works)
        for (const TopoDS_Face& f : w->fillers)
          sewing->Add(f);
      sewing->Perform();
      if (sewing->NbFreeEdges() == 0 && sewing->NbMultipleEdges() == 0)
        break;
    }
    BRepBuilderAPI_Sewing& sew  = *sewing;
    TopoDS_Shape           sewn = sew.SewedShape();
#ifdef YPATCH_TRACE
    BRepTools::Write(current, "trace-fillet.brep");
    for (std::size_t i = 0; i < works.size(); ++i)
      for (int k = 0; k < 2; ++k)
        BRepTools::Write(BRepBuilderAPI_MakeFace(works[i]->rib[k], 1e-7).Face(), ("trace-rib" + std::to_string(k) + ".brep").c_str());
    for (int i = 1; i <= sew.NbFreeEdges(); ++i)
    {
      BRepAdaptor_Curve c(sew.FreeEdge(i));
      gp_Pnt a = c.Value(c.FirstParameter()), m = c.Value((c.FirstParameter() + c.LastParameter()) / 2), z = c.Value(c.LastParameter());
      std::printf("free (%.4f %.4f %.4f) (%.4f %.4f %.4f) (%.4f %.4f %.4f)\n", a.X(), a.Y(), a.Z(), m.X(), m.Y(), m.Z(), z.X(), z.Y(), z.Z());
    }
#endif
    require(sew.NbFreeEdges() == 0 && sew.NbMultipleEdges() == 0, "YPatch: ribbons do not close the shell");
    TopExp_Explorer sh(sewn, TopAbs_SHELL);
    require(sh.More(), "YPatch: no shell");
    TopoDS_Shell closed = TopoDS::Shell(sh.Current());
    sh.Next();
    require(!sh.More(), "YPatch: several shells");
    TopoDS_Solid solid = BRepBuilderAPI_MakeSolid(closed).Solid();
    require(BRepLib::OrientClosedSolid(solid), "YPatch: cannot orient the solid");
#ifdef YPATCH_TRACE
    BRepTools::Write(solid, "trace-solid.brep");
#endif
    require(BRepCheck_Analyzer(solid).IsValid(), "YPatch: invalid result");
    BOPAlgo_CheckerSI si;
    si.SetLevelOfCheck(5);
    si.AddArgument(solid);
    si.Perform();
    require(!si.HasErrors() && si.DS().Interferences().IsEmpty(), "YPatch: self-interference");
    // 4. Continuity gate and report.
    theReport.Clear();
    for (auto& w : works)
    {
      Junction j  = w->j;
      j.Split     = w->in[n - 1].pT;
      const auto& R0 = w->rib[0];
      const auto& R1 = w->rib[1];
      j.SeamAngle    = boundaryAngle(R0, true, 1., [&](const gp_Pnt& p) {
        GeomAPI_ProjectPointOnSurf pr(p, R1);
        double                     u, v;
        pr.LowerDistanceParameters(u, v);
        GeomLProp_SLProps lp(R1, u, v, 1, 1e-12);
        return lp.IsNormalDefined() ? gp_Vec(lp.Normal()) : gp_Vec();
      });
      double band = 0;
      for (int k = 0; k < 2; ++k)
      {
        const Support& X  = k ? w->A : w->B;
        const gp_Pnt   c1 = (k ? w->in : w->out)[n - 1].c;
        const Handle(Geom_Surface)& bs = w->bandSurf[k];
        band = std::max(band, boundaryAngle(w->rib[k], false, 1., [&](const gp_Pnt& p) {
          if (bs.IsNull())
            return gp_Vec(c1, p);
          GeomAPI_ProjectPointOnSurf pr(p, bs);
          double                     u, v;
          pr.LowerDistanceParameters(u, v);
          GeomLProp_SLProps lp(bs, u, v, 1, 1e-12);
          return lp.IsNormalDefined() ? gp_Vec(lp.Normal()) : gp_Vec();
        }));
        band = std::max(band, boundaryAngle(w->rib[k], true, 0., [&](const gp_Pnt& p) { return X.N(X.UV(p)); }));
      }
      j.BandAngle = band;
      theReport.Append(j);
    }
    // 5. History: splitter, then fillet, then sewing.
    Handle(BRepTools_History) h = new BRepTools_History();
    TopTools_IndexedMapOfShape inputs;
    TopExp::MapShapes(theShape, TopAbs_FACE, inputs);
    TopExp::MapShapes(theShape, TopAbs_EDGE, inputs);
    TopExp::MapShapes(theShape, TopAbs_VERTEX, inputs);
    TopTools_IndexedMapOfShape outputs;
    TopExp::MapShapes(solid, outputs);
    auto after = [&](const TopoDS_Shape& x) {
      const TopoDS_Shape y = reshape->Value(x);
      return sew.IsModifiedSubShape(y) ? sew.ModifiedSubShape(y) : y; // (IsModified knows added shapes only)
    };
    // through both passes, the stray-edge cleanup and the sewing, into the solid
    auto finalOf = [&](const TopoDS_Shape& s, int from, TopTools_ListOfShape& to) {
      TopTools_ListOfShape mids;
      mids.Append(s);
      for (int k = from; k < 2; ++k)
      {
        TopTools_ListOfShape next;
        for (TopTools_ListOfShape::Iterator it(mids); it.More(); it.Next())
        {
          TopTools_ListOfShape l = passImage(k, it.Value());
          next.Append(l);
        }
        mids = next;
      }
      for (TopTools_ListOfShape::Iterator it(mids); it.More(); it.Next())
      {
        TopoDS_Shape r = after(it.Value());
        if (outputs.Contains(r))
          to.Append(r);
      }
    };
    for (int i = 1; i <= inputs.Extent(); ++i)
    {
      const TopoDS_Shape&        s = inputs(i);
      TopTools_ListOfShape       result;
      const TopTools_ListOfShape pieces = image(s);
      for (TopTools_ListOfShape::Iterator it(pieces); it.More(); it.Next())
        finalOf(it.Value(), 0, result);
      if (result.IsEmpty())
        h->Remove(s);
      else if (!(result.Extent() == 1 && result.First().IsSame(s)))
        for (TopTools_ListOfShape::Iterator it(result); it.More(); it.Next())
          h->AddModified(s, it.Value());
    }
    // Bands: every edge of every contour (a seed drags its tangent chain along), credited to
    // the input edge it comes from.
    for (int k = 0; k < 2; ++k)
    {
      if (!pass[k])
        continue;
      // the input edge of each edge of this pass's input
      NCollection_DataMap<TopoDS_Shape, TopoDS_Shape, TopTools_ShapeMapHasher> origin;
      TopTools_IndexedMapOfShape                                               inputEdges;
      TopExp::MapShapes(theShape, TopAbs_EDGE, inputEdges);
      for (int i = 1; i <= inputEdges.Extent(); ++i)
      {
        TopTools_ListOfShape       mids;
        const TopTools_ListOfShape pieces = image(inputEdges(i));
        for (TopTools_ListOfShape::Iterator it(pieces); it.More(); it.Next())
        {
          if (k == 0)
            mids.Append(it.Value());
          else
          {
            TopTools_ListOfShape l = passImage(0, it.Value());
            mids.Append(l);
          }
        }
        for (TopTools_ListOfShape::Iterator it(mids); it.More(); it.Next())
          origin.Bind(it.Value().Oriented(TopAbs_FORWARD), inputEdges(i));
      }
      for (int ic = 1; ic <= pass[k]->NbContours(); ++ic)
        for (int ie = 1; ie <= pass[k]->NbEdges(ic); ++ie)
        {
          const TopoDS_Edge& e   = pass[k]->Edge(ic, ie);
          const TopoDS_Shape key = e.Oriented(TopAbs_FORWARD);
          if (!origin.IsBound(key))
            continue;
          for (TopTools_ListOfShape::Iterator g(pass[k]->Generated(e)); g.More(); g.Next())
          {
            TopTools_ListOfShape result;
            finalOf(g.Value(), k + 1, result);
            for (TopTools_ListOfShape::Iterator it(result); it.More(); it.Next())
              h->AddGenerated(origin(key), it.Value());
          }
        }
    }
    for (std::size_t w = 0; w < works.size(); ++w)
      for (int k = 0; k < 2; ++k)
      {
        TopoDS_Shape r = ribbons[2 * w + k];
        r              = sew.IsModifiedSubShape(r) ? sew.ModifiedSubShape(r) : r;
        h->AddGenerated(k ? works[w]->j.Concave : works[w]->j.Convex, r);
      }
    for (auto& w : works)
      for (std::size_t k = 0; k < w->fillers.size(); ++k)
      {
        TopoDS_Shape r = w->fillers[k];
        r              = sew.IsModifiedSubShape(r) ? sew.ModifiedSubShape(r) : r;
        h->AddModified(w->fillerOf[k], r);
      }
        theResult  = solid;
        theHistory = h;
        return true;
      }
      catch (const Standard_Failure& ex)
      {
#ifdef YPATCH_TRACE
        std::printf("YPatch (margin %d): %s\n", int(margin), ex.GetMessageString());
#endif
        (void)ex;
        return false;
      }
    };
    // the direct cut first, then the cut with a margin on the supports
    return attempt(false) || attempt(true);
  }
  catch (const Standard_Failure& ex)
  {
#ifdef YPATCH_TRACE
    std::printf("YPatch: %s\n", ex.GetMessageString());
#endif
    (void)ex;
    return Standard_False;
  }
}

namespace
{
// The standard algorithm mishandles a band that starts on a free boundary (as the Y cut makes
// it) and runs across, or ends on, the seam of a periodic support: it builds a piece of the
// band twice.  Such supports are first re-seated: the face is rebuilt on its surface turned
// about its own axis, so that the seam lies where no selected edge passes.  The point set of
// every face is unchanged.
struct Reseated
{
  TopoDS_Shape                shape;
  TopTools_DataMapOfShapeReal radii;
  Handle(BRepTools_History)   history;
};

// S turned by phi about its axis such that S'(u, v) = S(u + phi, v); null when S is not a
// surface of revolution about a fixed axis.
Handle(Geom_Surface) turned(const Handle(Geom_Surface)& S, const double phi)
{
  gp_Ax1 axis;
  if (Handle(Geom_ElementarySurface) e = Handle(Geom_ElementarySurface)::DownCast(S))
    axis = e->Position().Axis();
  else if (Handle(Geom_SurfaceOfRevolution) r = Handle(Geom_SurfaceOfRevolution)::DownCast(S))
    axis = r->Axis();
  else
    return Handle(Geom_Surface)();
  for (const double sign : {1., -1.})
  {
    Handle(Geom_Surface) T = Handle(Geom_Surface)::DownCast(S->Rotated(axis, sign * phi));
    if (T->Value(0.3, 0.37).Distance(S->Value(0.3 + phi, 0.37)) < 1e-9
        && T->Value(1.7, 0.37).Distance(S->Value(1.7 + phi, 0.37)) < 1e-9)
      return T;
  }
  return Handle(Geom_Surface)();
}

// One edge of a re-seated face, in its wire orientation.
struct Use
{
  TopoDS_Edge          edge;
  Handle(Geom2d_Curve) pc; // on the turned surface
  double               f = 0, l = 0;

  gp_Pnt2d Start() const { return pc->Value(edge.Orientation() == TopAbs_REVERSED ? l : f); }

  gp_Pnt2d End() const { return pc->Value(edge.Orientation() == TopAbs_REVERSED ? f : l); }
};

bool reseat(const TopoDS_Shape& input, const TopTools_DataMapOfShapeReal& radii, Reseated& out)
{
  TopTools_IndexedMapOfShape selectedVertices;
  for (TopTools_DataMapOfShapeReal::Iterator it(radii); it.More(); it.Next())
    TopExp::MapShapes(it.Key(), TopAbs_VERTEX, selectedVertices);
  // the faces to re-seat and the parameter of their new seam
  std::vector<std::pair<TopoDS_Face, double>> todo;
  TopTools_IndexedMapOfShape                  faces;
  TopExp::MapShapes(input, TopAbs_FACE, faces);
  for (int i = 1; i <= faces.Extent(); ++i)
  {
    const TopoDS_Face          F = TopoDS::Face(faces(i));
    const Handle(Geom_Surface) S = BRep_Tool::Surface(F);
    if (S.IsNull() || !S->IsUPeriodic())
      continue;
    bool touched = false;
    for (TopExp_Explorer ex(F, TopAbs_EDGE); ex.More() && !touched; ex.Next())
      if (BRep_Tool::IsClosed(TopoDS::Edge(ex.Current()), F))
        for (TopExp_Explorer vx(ex.Current(), TopAbs_VERTEX); vx.More(); vx.Next())
          touched = touched || selectedVertices.Contains(vx.Current());
    if (!touched)
      continue;
    // the parameters covered by the selected edges on F, in bins of the period
    const double      P  = S->UPeriod();
    const int         nb = 720;
    std::vector<bool> covered(nb, false);
    auto              bin = [&](double u) {
      double x = std::fmod(u, P);
      if (x < 0)
        x += P;
      return std::min(nb - 1, int(x / P * nb));
    };
    for (TopExp_Explorer ex(F, TopAbs_EDGE); ex.More(); ex.Next())
    {
      if (!radii.IsBound(ex.Current()))
        continue;
      double               f, l;
      Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(TopoDS::Edge(ex.Current()), F, f, l);
      if (pc.IsNull())
        continue;
      for (int k = 0; k < 64; ++k)
      {
        const double a = pc->Value(f + (l - f) * k / 64).X(), b = pc->Value(f + (l - f) * (k + 1) / 64).X();
        const int    steps = 1 + int(std::abs(b - a) / P * nb);
        for (int s = 0; s <= steps; ++s)
          covered[bin(a + (b - a) * s / steps)] = true;
      }
    }
    // the middle of the largest free run (circular)
    int bestStart = -1, bestLen = 0;
    for (int s = 0; s < nb; ++s)
    {
      if (covered[s] || !covered[(s + nb - 1) % nb])
        continue;
      int len = 0;
      while (len < nb && !covered[(s + len) % nb])
        ++len;
      if (len > bestLen)
      {
        bestLen   = len;
        bestStart = s;
      }
    }
    if (bestStart < 0 || bestLen < 4)
      continue;
    todo.emplace_back(F, (bestStart + bestLen / 2. + 0.5) / nb * P);
  }
  if (todo.empty())
    return false;
  // 1. split each face along its new seam line
  BRepAlgoAPI_Splitter     split;
  TopTools_ListOfShape     args, tools;
  std::vector<TopoDS_Edge> rulings;
  args.Append(input);
  for (auto& item : todo)
  {
    const TopoDS_Face& F   = item.first;
    const double       phi = item.second;
    double             umin, umax, vmin, vmax;
    BRepTools::UVBounds(F, umin, umax, vmin, vmax);
    const double P = BRep_Tool::Surface(F)->UPeriod();
    double       u = phi + P * std::floor((umin - phi) / P);
    if (u < umin)
      u += P;
    Handle(Geom2d_Curve) line = new Geom2d_Line(gp_Pnt2d(u, 0.), gp_Dir2d(0., 1.));
    TopoDS_Edge          e    = BRepBuilderAPI_MakeEdge(line, BRep_Tool::Surface(F), vmin, vmax).Edge();
    BRepLib::BuildCurves3d(e);
    rulings.push_back(e);
    tools.Append(e);
  }
  split.SetArguments(args);
  split.SetTools(tools);
  split.Build();
  if (!split.IsDone() || split.HasErrors())
    return false;
  // 2. a copy: re-binding pcurves must not touch the input's edges
  BRepBuilderAPI_Copy       copy(split.Shape(), Standard_True, Standard_False);
  TopTools_ListOfShape      copied;
  copied.Append(split.Shape());
  Handle(BRepTools_History) hc = new BRepTools_History(copied, copy);
  auto copyOf = [&](const TopoDS_Shape& s) { // (Copy::Modified throws for a foreign shape)
    const TopTools_ListOfShape& l = hc->Modified(s);
    return l.IsEmpty() ? s : l.First();
  };
  auto image = [&](const TopoDS_Shape& s) { // input -> split -> copy
    TopTools_ListOfShape l;
    if (split.IsDeleted(s))
      return l;
    TopTools_ListOfShape pieces = split.Modified(s);
    if (pieces.IsEmpty())
      pieces.Append(s);
    for (TopTools_ListOfShape::Iterator it(pieces); it.More(); it.Next())
      l.Append(copyOf(it.Value()));
    return l;
  };
  Handle(BRepTools_ReShape) rs = new BRepTools_ReShape();
  BRep_Builder              bb;
  TopTools_MapOfShape       seamVertices; // the old seams' vertices, in the copy
  for (std::size_t t = 0; t < todo.size(); ++t)
  {
    const TopoDS_Face&         F   = todo[t].first;
    const double               phi = todo[t].second;
    const Handle(Geom_Surface) S   = BRep_Tool::Surface(F);
    const Handle(Geom_Surface) S2  = turned(S, phi);
    if (S2.IsNull())
      return false;
    const double        P = S->UPeriod();
    TopTools_MapOfShape oldSeams, newSeams;
    for (TopExp_Explorer ex(F, TopAbs_EDGE); ex.More(); ex.Next())
      if (BRep_Tool::IsClosed(TopoDS::Edge(ex.Current()), F))
      {
        const TopTools_ListOfShape l = image(ex.Current());
        for (TopTools_ListOfShape::Iterator it(l); it.More(); it.Next())
        {
          oldSeams.Add(it.Value());
          for (TopExp_Explorer vx(it.Value(), TopAbs_VERTEX); vx.More(); vx.Next())
            seamVertices.Add(vx.Current());
        }
      }
    {
      const TopTools_ListOfShape l = split.Modified(rulings[t]);
      for (TopTools_ListOfShape::Iterator it(l); it.More(); it.Next())
        newSeams.Add(copyOf(it.Value()));
    }
    const TopTools_ListOfShape pieces = image(F);
    if (pieces.Extent() < 2)
      return false;
    // an old seam piece becomes interior only where the pieces meet across it (it is used
    // twice); used once, it is a boundary that merely lay on the old seam line
    NCollection_DataMap<TopoDS_Shape, int, TopTools_ShapeMapHasher> seamUses;
    for (TopTools_ListOfShape::Iterator pit(pieces); pit.More(); pit.Next())
      for (TopExp_Explorer ex(pit.Value(), TopAbs_EDGE); ex.More(); ex.Next())
        if (oldSeams.Contains(ex.Current()))
        {
          const TopoDS_Shape key = ex.Current().Oriented(TopAbs_FORWARD);
          if (!seamUses.IsBound(key))
            seamUses.Bind(key, 0);
          seamUses(key) += 1;
        }
    std::vector<Use>                                                                  uses;
    NCollection_DataMap<TopoDS_Shape, Handle(Geom2d_Curve), TopTools_ShapeMapHasher> seamF, seamR;
    for (TopTools_ListOfShape::Iterator pit(pieces); pit.More(); pit.Next())
    {
      const TopoDS_Face p = TopoDS::Face(pit.Value().Oriented(TopAbs_FORWARD));
      double            umin, umax, vmin, vmax;
      BRepTools::UVBounds(p, umin, umax, vmin, vmax);
      double side = std::fmod((umin + umax) / 2 - phi, P); // the piece's place on the turned surface
      if (side < 0)
        side += P;
      for (TopExp_Explorer ex(p, TopAbs_EDGE); ex.More(); ex.Next())
      {
        const TopoDS_Edge e = TopoDS::Edge(ex.Current());
        if (oldSeams.Contains(e) && seamUses(e.Oriented(TopAbs_FORWARD)) > 1)
          continue;
        Use use;
        use.edge                = e;
        Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(e, p, use.f, use.l);
        if (pc.IsNull())
          return false;
        double shift = -phi;
        if (newSeams.Contains(e)) // u' = 0 next to the piece at the start of the period, else u' = P
          shift += (side < P / 2 ? 0. : P) - P * std::round((pc->Value(use.f).X() - phi) / P);
        else
          shift -= P * std::floor((pc->Value((use.f + use.l) / 2).X() - phi) / P);
        use.pc = Handle(Geom2d_Curve)::DownCast(pc->Translated(gp_Vec2d(shift, 0.)));
        if (newSeams.Contains(e))
          (e.Orientation() == TopAbs_REVERSED ? seamR : seamF).Bind(e.Oriented(TopAbs_FORWARD), use.pc);
        uses.push_back(use);
      }
    }
    // re-bind the pcurves on the turned surface
    for (const Use& use : uses)
    {
      const TopoDS_Shape key = use.edge.Oriented(TopAbs_FORWARD);
      if (newSeams.Contains(use.edge))
      {
        if (!seamF.IsBound(key) || !seamR.IsBound(key))
          return false;
        bb.UpdateEdge(TopoDS::Edge(key), seamF(key), seamR(key), S2, TopLoc_Location(),
                      BRep_Tool::Tolerance(use.edge));
      }
      else
        bb.UpdateEdge(use.edge, use.pc, S2, TopLoc_Location(), BRep_Tool::Tolerance(use.edge));
    }
    // chain the uses into closed wires by their uv ends
    TopoDS_Face F2;
    bb.MakeFace(F2, S2, BRep_Tool::Tolerance(F));
    const double      tol = 1e-6 * (1 + P);
    std::vector<bool> used(uses.size(), false);
    for (std::size_t start = 0; start < uses.size(); ++start)
    {
      if (used[start])
        continue;
      TopoDS_Wire w;
      bb.MakeWire(w);
      std::size_t cur = start;
      while (true)
      {
        used[cur] = true;
        bb.Add(w, uses[cur].edge);
        const gp_Pnt2d end  = uses[cur].End();
        std::size_t    next = uses.size();
        double         best = tol;
        for (std::size_t k = 0; k < uses.size(); ++k)
          if (!used[k] && uses[k].Start().Distance(end) < best)
          {
            best = uses[k].Start().Distance(end);
            next = k;
          }
        if (next == uses.size())
        {
          if (uses[start].Start().Distance(end) > tol)
          {
#ifdef YPATCH_TRACE
            std::printf("YPatch: re-seat open loop at (%g %g)\n", end.X(), end.Y());
#endif
            return false; // an open loop
          }
          break;
        }
        cur = next;
      }
      w.Closed(Standard_True);
      bb.Add(F2, w);
    }
    if (!BRepCheck_Analyzer(F2).IsValid())
    {
#ifdef YPATCH_TRACE
      std::printf("YPatch: re-seated face invalid\n");
#endif
      return false;
    }
    bool first = true;
    for (TopTools_ListOfShape::Iterator pit(pieces); pit.More(); pit.Next())
    {
      if (first)
        rs->Replace(pit.Value(), F2.Oriented(pit.Value().Orientation()));
      else
        rs->Remove(pit.Value());
      first = false;
    }
  }
  // With the old seam gone, its vertices split curves for nothing (a band then starts on a
  // free boundary and crosses one, which the standard algorithm handles badly for small
  // radii): merge the edges through them, and only through them.
  const TopoDS_Shape           reshaped = rs->Apply(copy.Shape());
  ShapeUpgrade_UnifySameDomain usd(reshaped, Standard_True, Standard_False, Standard_False);
  {
    TopTools_IndexedMapOfShape verts;
    TopExp::MapShapes(reshaped, TopAbs_VERTEX, verts);
    for (int i = 1; i <= verts.Extent(); ++i)
      if (!seamVertices.Contains(verts(i)))
        usd.KeepShape(verts(i));
  }
  usd.Build();
  out.shape                     = usd.Shape();
  Handle(BRepTools_History) hu = usd.History();
  if (!BRepCheck_Analyzer(out.shape).IsValid())
    return false;
  // The history, sub-shape by sub-shape: split, copy, replacement, edge merging.  (Chained Merge calls
  // drop the copy of every shape the splitter left alone.)
  TopTools_IndexedMapOfShape outs;
  for (const TopAbs_ShapeEnum t : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX})
    TopExp::MapShapes(out.shape, t, outs);
  auto through = [&](const TopoDS_Shape& s) {
    TopTools_ListOfShape result;
    if (split.IsDeleted(s))
      return result;
    TopTools_ListOfShape pieces = split.Modified(s);
    if (pieces.IsEmpty())
      pieces.Append(s);
    TopTools_MapOfShape seen;
    for (TopTools_ListOfShape::Iterator it(pieces); it.More(); it.Next())
    {
      const TopoDS_Shape z = rs->Value(copyOf(it.Value()));
      if (z.IsNull() || hu->IsRemoved(z))
        continue;
      TopTools_ListOfShape merged = hu->Modified(z);
      if (merged.IsEmpty())
        merged.Append(z);
      for (TopTools_ListOfShape::Iterator m(merged); m.More(); m.Next())
        if (outs.Contains(m.Value()) && seen.Add(m.Value()))
          result.Append(m.Value());
    }
    return result;
  };
  TopTools_IndexedMapOfShape inputs;
  for (const TopAbs_ShapeEnum t : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX})
    TopExp::MapShapes(input, t, inputs);
  out.history = new BRepTools_History();
  for (int i = 1; i <= inputs.Extent(); ++i)
  {
    const TopTools_ListOfShape images = through(inputs(i));
    if (images.IsEmpty())
      out.history->Remove(inputs(i));
    else if (!(images.Extent() == 1 && images.First().IsSame(inputs(i))))
      for (TopTools_ListOfShape::Iterator it(images); it.More(); it.Next())
        out.history->AddModified(inputs(i), it.Value());
  }
  out.radii.Clear();
  for (TopTools_DataMapOfShapeReal::Iterator it(radii); it.More(); it.Next())
  {
    const TopTools_ListOfShape images = through(it.Key());
    if (images.IsEmpty())
      return false;
    for (TopTools_ListOfShape::Iterator e(images); e.More(); e.Next())
      out.radii.Bind(e.Value(), it.Value());
  }
  return true;
}
} // namespace

// input -> h1 -> h2, for the faces, edges and vertices of `input`.  (BRepTools_History::Merge
// does not carry a shape generated, in h2, from a modified image of an input shape.)
static Handle(BRepTools_History) compose(const TopoDS_Shape&              input,
                                         const Handle(BRepTools_History)& h1,
                                         const Handle(BRepTools_History)& h2,
                                         const TopoDS_Shape&              result)
{
  TopTools_IndexedMapOfShape inputs, outputs;
  for (const TopAbs_ShapeEnum t : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX})
  {
    TopExp::MapShapes(input, t, inputs);
    TopExp::MapShapes(result, t, outputs);
  }
  auto images = [](const Handle(BRepTools_History)& h, const TopoDS_Shape& s) {
    TopTools_ListOfShape l;
    if (h->IsRemoved(s))
      return l;
    l = h->Modified(s);
    if (l.IsEmpty())
      l.Append(s);
    return l;
  };
  Handle(BRepTools_History) out = new BRepTools_History();
  for (int i = 1; i <= inputs.Extent(); ++i)
  {
    const TopoDS_Shape&  s = inputs(i);
    TopTools_ListOfShape modified, generated;
    const TopTools_ListOfShape mids = images(h1, s);
    for (TopTools_ListOfShape::Iterator m(mids); m.More(); m.Next())
    {
      const TopTools_ListOfShape fin = images(h2, m.Value());
      for (TopTools_ListOfShape::Iterator f(fin); f.More(); f.Next())
        if (outputs.Contains(f.Value()))
          modified.Append(f.Value());
      for (TopTools_ListOfShape::Iterator g(h2->Generated(m.Value())); g.More(); g.Next())
        if (outputs.Contains(g.Value()))
          generated.Append(g.Value());
    }
    if (modified.IsEmpty())
      out->Remove(s);
    else if (!(modified.Extent() == 1 && modified.First().IsSame(s)))
      for (TopTools_ListOfShape::Iterator f(modified); f.More(); f.Next())
        out->AddModified(s, f.Value());
    for (TopTools_ListOfShape::Iterator g(generated); g.More(); g.Next())
      out->AddGenerated(s, g.Value());
  }
  return out;
}

Standard_Boolean BRepFilletAPI_YPatch::Perform(const TopoDS_Shape&               theShape,
                                               const TopTools_DataMapOfShapeReal& theRadii,
                                               TopoDS_Shape&                      theResult,
                                               Handle(BRepTools_History)&         theHistory,
                                               NCollection_Vector<Junction>&      theReport)
{
  try
  {
    Reseated r;
    if (!Detect(theShape, theRadii).IsEmpty() && reseat(theShape, theRadii, r))
    {
      TopoDS_Shape                 result;
      Handle(BRepTools_History)    h;
      NCollection_Vector<Junction> report;
#ifdef YPATCH_TRACE
      std::printf("YPatch: periodic supports re-seated\n");
#endif
      if (performOn(r.shape, r.radii, result, h, report))
      {
        theResult  = result;
        theHistory = compose(theShape, r.history, h, result);
        theReport  = report;
        return Standard_True;
      }
    }
  }
  catch (const Standard_Failure& ex)
  {
#ifdef YPATCH_TRACE
    std::printf("YPatch: re-seat: %s\n", ex.GetMessageString());
#endif
    (void)ex;
  }
  return performOn(theShape, theRadii, theResult, theHistory, theReport);
}
