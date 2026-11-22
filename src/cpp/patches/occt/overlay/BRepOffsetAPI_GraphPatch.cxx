// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#include <BRepOffsetAPI_GraphPatch.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Curve2d.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepLib.hxx>
#include <Geom2d_BezierCurve.hxx>
#include <Geom_BezierSurface.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <math.hxx>
#include <math_Jacobi.hxx>
#include <math_Recipes.hxx>
#include <math_SVD.hxx>
#include <memory>
#include <array>
#include <vector>
#include <algorithm>
#include <cmath>

namespace
{
constexpr int N = 8, n = N + 1, samples = 2 * N + 1, dim = n * n;
using Basis = std::array<double, n>;
using Row   = std::array<double, dim>;

void require(bool b)
{
  if (!b)
    throw Standard_ConstructionError("GraphPatch: outside graph or fit domain");
}

double binom(int a, int b)
{
  double c = 1;
  for (int j = 1; j <= b; ++j)
    c = c * (a - j + 1) / j;
  return c;
}

Basis basis(double t, int d)
{
  Basis b{};
  int   m = N - d;
  for (int j = 0; j <= m; ++j)
  {
    double f = binom(m, j) * pow(t, j) * pow(1 - t, m - j);
    for (int k = 0; k <= d; ++k)
      b[j + k] += f * ((d - k) % 2 ? -1 : 1) * binom(d, k)
                  * (d == 0   ? 1
                     : d == 1 ? N
                              : N * (N - 1));
  }
  return b;
}

Row row(double u, double v, int du, int dv)
{
  Row  r;
  auto a = basis(u, du), b = basis(v, dv);
  for (int i = 0; i < n; ++i)
    for (int j = 0; j < n; ++j)
      r[n * i + j] = a[i] * b[j];
  return r;
}

struct Jet
{
  gp_Pnt p;
  double z[6];
};

Jet jet(const BRepAdaptor_Curve2d& c,
        const BRepAdaptor_Surface& surf,
        double                     t,
        const gp_Trsf&             inv,
        int                        order)
{
  auto   uv = c.Value(c.FirstParameter() * (1 - t) + c.LastParameter() * t);
  gp_Vec u, v, uu, vv, uvv;
  Jet    s{};
  if (order == 0)
    s.p = surf.Value(uv.X(), uv.Y());
  else if (order == 1)
    surf.D1(uv.X(), uv.Y(), s.p, u, v);
  else
    surf.D2(uv.X(), uv.Y(), s.p, u, v, uu, vv, uvv);
  s.p.Transform(inv);
  s.z[0] = s.p.Z();
  if (order == 0)
    return s;
  u.Transform(inv);
  v.Transform(inv);
  double det = u.X() * v.Y() - u.Y() * v.X();
  require(std::abs(det) > 1e-9 * u.Magnitude() * v.Magnitude());
  double a = v.Y() / det, b = -u.Y() / det, cx = -v.X() / det, d = u.X() / det;
  s.z[1] = a * u.Z() + b * v.Z();
  s.z[2] = cx * u.Z() + d * v.Z();
  if (order == 1)
    return s;
  auto h = [&](gp_Vec w) {
    w.Transform(inv);
    return w.Z() - w.X() * s.z[1] - w.Y() * s.z[2];
  };
  double A = h(uu), B = h(uvv), C = h(vv);
  s.z[3] = a * a * A + 2 * a * b * B + b * b * C;
  s.z[4] = a * cx * A + (a * d + b * cx) * B + b * d * C;
  s.z[5] = cx * cx * A + 2 * cx * d * B + d * d * C;
  return s;
}

gp_Trsf plane(int count, const TopoDS_Edge* edges)
{
  std::vector<gp_XYZ> pts;
  gp_XYZ              center;
  for (int i = 0; i < count; ++i)
  {
    BRepAdaptor_Curve c(edges[i]);
    for (int j = 0; j < 9; ++j)
    {
      double t = j / 8.;
      pts.push_back(c.Value((1 - t) * c.FirstParameter() + t * c.LastParameter()).XYZ());
      center += pts.back();
    }
  }
  center /= double(pts.size());
  math_Matrix m(1, 3, 1, 3, 0.);
  for (auto p : pts)
  {
    p -= center;
    for (int a = 1; a <= 3; ++a)
      for (int b = 1; b <= 3; ++b)
        m(a, b) += p.Coord(a) * p.Coord(b);
  }
  math_Jacobi eig(m);
  require(eig.IsDone());
  std::array<int, 3> indices{1, 2, 3};
  std::sort(indices.begin(), indices.end(), [&](int a, int b) {
    return eig.Value(a) > eig.Value(b);
  });
  require(eig.Value(indices[1]) > 1e-12 * eig.Value(indices[0]));
  auto axis = [&](int i) {
    auto& v = eig.Vectors();
    return gp_XYZ(v(1, i), v(2, i), v(3, i));
  };
  auto    x = axis(indices[0]), y = axis(indices[1]), z = x.Crossed(y);
  gp_Trsf f;
  f.SetValues(x.X(),
              y.X(),
              z.X(),
              center.X(),
              x.Y(),
              y.Y(),
              z.Y(),
              center.Y(),
              x.Z(),
              y.Z(),
              z.Z(),
              center.Z());
  return f;
}

math_Vector solve(const std::vector<Row>& rows, const std::vector<double>& values)
{
  int         m = std::max(dim, int(rows.size()));
  math_Matrix A(1, m, 1, dim, 0.), V(1, dim, 1, dim);
  math_Vector W(1, dim), b(1, m, 0.), x(1, dim);
  for (size_t i = 0; i < rows.size(); ++i)
  {
    b(1 + i) = values[i];
    for (int j = 0; j < dim; ++j)
      A(i + 1, j + 1) = rows[i][j];
  }
  require(SVD_Decompose(A, W, V) == 0);
  double           eps = W(W.Max()) * 1e-11;
  std::vector<int> null;
  for (int i = 1; i <= dim; ++i)
    if (W(i) <= eps)
    {
      W(i) = 0.;
      null.push_back(i);
    }
  SVD_Solve(A, W, V, b, x);
  // Remaining freedom minimizes the integrated squared Hessian in the exact
  // null space, so fairing cannot trade away any accepted boundary constraint.
  if (!null.empty())
  {
    int         q = int(null.size());
    math_Matrix D(1, 3 * n * n, 1, q);
    math_Vector rhs(1, 3 * n * n), delta(1, q), t(1, n), w(1, n);
    math::GaussPoints(n, t);
    math::GaussWeights(n, w);
    int i = 0;
    for (int a = 1; a <= n; ++a)
      for (int b_ = 1; b_ <= n; ++b_)
        for (int k = 0; k <= 2; ++k)
        {
          auto r = row((t(a) + 1) / 2, (t(b_) + 1) / 2, 2 - k, k);
          ++i;
          double weight = sqrt(w(a) * w(b_) * (k == 1 ? 2. : 1.));
          rhs(i)        = 0;
          for (int j = 0; j < dim; ++j)
            rhs(i) -= weight * r[j] * x(j + 1);
          for (int c = 0; c < q; ++c)
          {
            double sum = 0;
            for (int j = 0; j < dim; ++j)
              sum += r[j] * V(j + 1, null[c]);
            D(i, c + 1) = sum * weight;
          }
        }
    math_SVD svd(D);
    require(svd.IsDone());
    svd.Solve(rhs, delta, 1e-11);
    for (int j = 1; j <= dim; ++j)
      for (int c = 0; c < q; ++c)
        x(j) += V(j, null[c]) * delta(c + 1);
  }
  for (size_t i = 0; i < rows.size(); ++i)
  {
    double err = -values[i];
    for (int j = 0; j < dim; ++j)
      err += rows[i][j] * x(j + 1);
    require(std::abs(err) <= 1e-5);
  }
  return x;
}

// bench/solvers.py: rectangular, affine-projection branch. Unlike the general
// loop it interpolates the entire height/normal-derivative trace with nine data
// per side and retains a natural (untrimmed) domain. Cache only the fixed linear
// map, NOT pole heights, inputs, faces or mutable OCCT geometry.
struct RectangleMap
{
  double             w, h;
  std::array<int, 4> orders;
  math_Matrix        transform;

  static int size(const std::array<int, 4>& k) { return n * (4 + k[0] + k[1] + k[2] + k[3]); }

  RectangleMap(double W, double H, const std::array<int, 4>& K)
      : w(W),
        h(H),
        orders(K),
        transform(1, dim, 1, size(K))
  {
    const int   m = size(K), p = std::max(m, dim);
    math_Matrix U(1, p, 1, dim, 0.), V(1, dim, 1, dim);
    math_Vector S(1, dim);
    int         i = 0;
    for (int side = 0; side < 4; ++side)
      for (int j = 0; j < n; ++j)
      {
        double t = double(j) / N,
               u = side == 1   ? 1
                   : side == 3 ? 0
                               : t,
               v = side == 0   ? 0
                   : side == 2 ? 1
                               : t;
        for (int d = 0; d <= K[side]; ++d)
        {
          auto r = row(u, v, side % 2 ? d : 0, side % 2 ? 0 : d);
          ++i;
          for (int a = 0; a < dim; ++a)
            U(i, a + 1) = r[a];
        }
      }
    require(SVD_Decompose(U, S, V) == 0);
    double           cut = S(S.Max()) * 1e-12;
    std::vector<int> null;
    for (int a = 1; a <= dim; ++a)
      if (S(a) <= cut)
        null.push_back(a);
    for (int a = 1; a <= dim; ++a)
      for (int b = 1; b <= m; ++b)
      {
        double v = 0;
        for (int k = 1; k <= dim; ++k)
          if (S(k) > cut)
            v += V(a, k) * U(b, k) / S(k);
        transform(a, b) = v;
      }
    if (null.empty())
      return;
    math_Vector t(1, n), weights(1, n);
    math::GaussPoints(n, t);
    math::GaussWeights(n, weights);
    math_Matrix D(1, 3 * n * n, 1, dim), Z(1, dim, 1, int(null.size()));
    for (int j = 1; j <= dim; ++j)
      for (size_t c = 0; c < null.size(); ++c)
        Z(j, c + 1) = V(j, null[c]);
    i = 0;
    for (int a = 1; a <= n; ++a)
      for (int b = 1; b <= n; ++b)
        for (int k = 0; k <= 2; ++k)
        {
          auto r = row((1 + t(a)) / 2, (1 + t(b)) / 2, 2 - k, k);
          ++i;
          double factor =
            sqrt(weights(a) * weights(b) * (k == 1 ? 2 : 1)) / (pow(w, 2 - k) * pow(h, k));
          for (int j = 0; j < dim; ++j)
            D(i, j + 1) = factor * r[j];
        }
    math_Matrix dz = D * Z;
    math_SVD    fair(dz);
    require(fair.IsDone());
    math_Matrix inv(1, int(null.size()), 1, 3 * n * n);
    fair.PseudoInverse(inv, 1e-11);
    transform -= Z * (inv * (D * transform));
  }
};

bool rectangle(const std::vector<std::array<Jet, samples>>& ss,
               const int*                                   orders,
               double                                       xmin,
               double                                       ymin,
               double                                       w,
               double                                       h,
               const gp_Trsf&                               f,
               TopoDS_Face&                                 out)
{
  if (ss.size() != 4 || w <= 1e-7 || h <= 1e-7)
    return false;
  std::array<int, 4>  index{-1, -1, -1, -1}, K{};
  std::array<bool, 4> rev{};
  for (int i = 0; i < 4; ++i)
  {
    const auto& p   = ss[i];
    auto        mid = p[N].p;
    auto        u = (mid.X() - xmin) / w, v = (mid.Y() - ymin) / h;
    int         side = std::abs(v) < 1e-9       ? 0
                       : std::abs(u - 1) < 1e-9 ? 1
                       : std::abs(v - 1) < 1e-9 ? 2
                       : std::abs(u) < 1e-9     ? 3
                                                : -1;
    if (side < 0 || index[side] != -1)
      return false;
    // Keep the contract for ordered loops even on the rectangular fast path.
    if (i)
    {
      auto& prev = ss[i - 1];
      if (std::min({prev.front().p.Distance(p.front().p),
                    prev.front().p.Distance(p.back().p),
                    prev.back().p.Distance(p.front().p),
                    prev.back().p.Distance(p.back().p)})
          > 1e-6)
        return false;
    }
    index[side] = i;
    K[side]     = orders[i];
    rev[side]   = side % 2 ? p.front().p.Y() > p.back().p.Y() : p.front().p.X() > p.back().p.X();
    for (int j = 0; j < samples; ++j)
    {
      const auto& s = p[rev[side] ? samples - 1 - j : j];
      double      t = double(j) / (samples - 1);
      double      x = xmin
                 + w
                     * (side == 1   ? 1
                        : side == 3 ? 0
                                    : t),
             y = ymin
                 + h
                     * (side == 0   ? 0
                        : side == 2 ? 1
                                    : t);
      if (std::hypot(x - s.p.X(), y - s.p.Y()) > 1e-8)
        return false;
    }
  }
  thread_local std::unique_ptr<RectangleMap> cache;
  if (!cache || cache->w != w || cache->h != h || cache->orders != K)
    cache = std::make_unique<RectangleMap>(w, h, K);
  math_Vector b(1, RectangleMap::size(K));
  int         i = 0;
  for (int side = 0; side < 4; ++side)
    for (int j = 0; j < n; ++j)
    {
      const auto& s = ss[index[side]][2 * (rev[side] ? N - j : j)];
      b(++i)        = s.z[0];
      if (K[side] >= 1)
        b(++i) = side % 2 ? w * s.z[1] : h * s.z[2];
      if (K[side] >= 2)
        b(++i) = side % 2 ? w * w * s.z[3] : h * h * s.z[5];
    }
  math_Vector x = cache->transform * b;
  // Validate the full requested jet, including midpoints not used in the solve.
  for (int side = 0; side < 4; ++side)
    for (const auto& s : ss[index[side]])
    {
      const int du[] = {0, 1, 0, 2, 1, 0}, dv[] = {0, 0, 1, 0, 1, 2};
      for (int k = 0; k < 6; ++k)
        if (du[k] + dv[k] <= K[side])
        {
          auto   r   = row((s.p.X() - xmin) / w, (s.p.Y() - ymin) / h, du[k], dv[k]);
          double err = -s.z[k] * pow(w, du[k]) * pow(h, dv[k]);
          for (int j = 0; j < dim; ++j)
            err += r[j] * x(j + 1);
          require(std::abs(err) <= 1e-6);
        }
    }
  TColgp_Array2OfPnt p(1, n, 1, n);
  for (int a = 0; a < n; ++a)
    for (int b_ = 0; b_ < n; ++b_)
      p(a + 1, b_ + 1) =
        gp_Pnt(xmin + w * a / N, ymin + h * b_ / N, x(1 + n * a + b_)).Transformed(f);
  auto face = BRepBuilderAPI_MakeFace(new Geom_BezierSurface(p), 1e-7).Face();
  require(BRepCheck_Analyzer(face).IsValid());
  out = face;
  return true;
}
} // namespace

bool BRepOffsetAPI_GraphPatch::TryBuild(int                count,
                                        const TopoDS_Edge* es,
                                        const TopoDS_Face* fs,
                                        const int*         orders,
                                        TopoDS_Face&       out,
                                        const gp_Trsf*     frame)
{
  try
  {
    if (count < 3 || count > 64 || !es || !fs || !orders)
      return false;
    for (int i = 0; i < count; ++i)
    {
      if (es[i].IsNull() || fs[i].IsNull() || orders[i] < 0 || orders[i] > 2)
        return false;
      TopTools_IndexedMapOfShape m;
      TopExp::MapShapes(fs[i], TopAbs_EDGE, m);
      if (!m.Contains(es[i]))
        return false;
    }
    gp_Trsf f = frame ? *frame : plane(count, es);
    require(!f.IsNegative() && std::abs(f.ScaleFactor() - 1) < 1e-12);
    auto                                  inv = f.Inverted();
    std::vector<std::array<Jet, samples>> ss(count);
    double                                xmin = 1e100, ymin = 1e100, xmax = -1e100, ymax = -1e100;
    for (int i = 0; i < count; ++i)
    {
      BRepAdaptor_Curve2d c(es[i], fs[i]);
      BRepAdaptor_Surface surf(fs[i]);
      for (int j = 0; j < samples; ++j)
      {
        auto s   = jet(c, surf, double(j) / (samples - 1), inv, orders[i]);
        ss[i][j] = s;
        xmin     = std::min(xmin, s.p.X());
        ymin     = std::min(ymin, s.p.Y());
        xmax     = std::max(xmax, s.p.X());
        ymax     = std::max(ymax, s.p.Y());
      }
    }
    if (rectangle(ss, orders, xmin, ymin, xmax - xmin, ymax - ymin, f, out))
      return true;
    double L = std::max(xmax - xmin, ymax - ymin) * 1.05;
    require(L > 1e-7);
    xmin -= .025 * L;
    ymin -= .025 * L;
    math_Matrix B(1, samples, 1, n);
    for (int j = 0; j < samples; ++j)
    {
      auto b = basis(double(j) / (samples - 1), 0);
      for (int k = 0; k < n; ++k)
        B(j + 1, k + 1) = b[k];
    }
    math_SVD trim(B);
    require(trim.IsDone());
    std::vector<Row>                        A;
    std::vector<double>                     rhs;
    std::vector<Handle(Geom2d_BezierCurve)> curves;
    gp_Pnt2d                                start, last;
    const int                               du[] = {0, 1, 0, 2, 1, 0}, dv[] = {0, 0, 1, 0, 1, 2};
    for (int i = 0; i < count; ++i)
    {
      TColgp_Array1OfPnt2d p(1, n);
      math_Vector          bx(1, samples), by(1, samples), x(1, n), y(1, n);
      for (int j = 0; j < samples; ++j)
      {
        auto&  s = ss[i][j];
        double u = (s.p.X() - xmin) / L, v = (s.p.Y() - ymin) / L;
        bx(j + 1) = u;
        by(j + 1) = v;
        for (int k = 0; k < 6; ++k)
          if (du[k] + dv[k] <= orders[i])
          {
            A.push_back(row(u, v, du[k], dv[k]));
            rhs.push_back(s.z[k] * pow(L, du[k] + dv[k]));
          }
      }
      trim.Solve(bx, x);
      trim.Solve(by, y);
      for (int k = 1; k <= n; ++k)
        p(k) = {x(k), y(k)};
      Handle(Geom2d_BezierCurve) c = new Geom2d_BezierCurve(p);
      for (int j = 0; j < samples; ++j)
        require(c->Value(double(j) / (samples - 1)).Distance({bx(j + 1), by(j + 1)}) * L <= 1e-7);
      if (!i)
      {
        auto nextDist = [&](gp_Pnt2d pt) {
          return std::min(
            pt.Distance({(ss[1][0].p.X() - xmin) / L, (ss[1][0].p.Y() - ymin) / L}),
            pt.Distance({(ss[1].back().p.X() - xmin) / L, (ss[1].back().p.Y() - ymin) / L}));
        };
        if (nextDist(c->StartPoint()) < nextDist(c->EndPoint()))
          c->Reverse();
        start = c->StartPoint();
      }
      else
      {
        if (last.Distance(c->EndPoint()) < last.Distance(c->StartPoint()))
          c->Reverse();
        require(last.Distance(c->StartPoint()) * L <= 1e-6);
      }
      last = c->EndPoint();
      curves.push_back(c);
    }
    require(start.Distance(last) * L <= 1e-6);
    auto               z = solve(A, rhs);
    TColgp_Array2OfPnt poles(1, n, 1, n);
    for (int i = 0; i < n; ++i)
      for (int j = 0; j < n; ++j)
        poles(i + 1, j + 1) =
          gp_Pnt(xmin + L * i / N, ymin + L * j / N, z(1 + i * n + j)).Transformed(f);
    Handle(Geom_BezierSurface) base = new Geom_BezierSurface(poles);
    BRepBuilderAPI_MakeWire    wire;
    for (auto& c : curves)
      wire.Add(BRepBuilderAPI_MakeEdge(c, base).Edge());
    auto face = BRepBuilderAPI_MakeFace(base, wire.Wire(), true).Face();
    require(BRepLib::BuildCurves3d(face, 1e-8) && BRepCheck_Analyzer(face).IsValid());
    out = face;
    return true;
  }
  catch (const Standard_Failure&)
  {
    return false;
  }
}
