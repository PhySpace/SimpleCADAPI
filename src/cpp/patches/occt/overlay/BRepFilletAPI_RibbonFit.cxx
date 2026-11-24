// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#include <BRepFilletAPI_RibbonFit.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <Geom_BSplineSurface.hxx>
#include <math_Gauss.hxx>
#include <array>
#include <vector>
#include <cmath>

bool BRepFilletAPI_RibbonFit::TryBuild(const void*  ctx,
                                       Position     pos,
                                       Normal       normal,
                                       TopoDS_Face& result,
                                       int          n,
                                       double       tol,
                                       double       angleTol)
{
  if (!pos || !normal || n < 5 || n > 41 || !(tol > 0 && angleTol > 0 && angleTol < 1.57))
    return false;
  try
  {
    std::vector<double> k(4, 0.);
    for (int j = 2; j < n - 2; ++j)
      k.push_back(double(j) / (n - 1));
    k.insert(k.end(), 4, 1.);
    auto basis = [&](double t) {
      std::vector<double> b(n + 3, 0.);
      if (t == 1)
        b[n - 1] = 1;
      else
      {
        for (int i = 0; i < n + 3; ++i)
          b[i] = t >= k[i] && t < k[i + 1];
        for (int d = 1; d <= 3; ++d)
          for (int i = 0; i < n + 3 - d; ++i)
          {
            double l = k[i + d] - k[i], r = k[i + d + 1] - k[i + 1];
            b[i] = (l ? (t - k[i]) * b[i] / l : 0) + (r ? (k[i + d + 1] - t) * b[i + 1] / r : 0);
          }
      }
      return b;
    };
    math_Matrix A(1, n, 1, n);
    for (int i = 0; i < n; ++i)
    {
      auto b = basis(double(i) / (n - 1));
      for (int j = 0; j < n; ++j)
        A(i + 1, j + 1) = b[j];
    }
    math_Gauss interp(A);
    if (!interp.IsDone())
      return false;
    std::vector<gp_XYZ> poles(n * n);
    auto                id = [&](int i, int j) { return i * n + j; };
    for (int i = 0; i < n; ++i)
      for (int j = 0; j < n; ++j)
        poles[id(i, j)] = pos(ctx, double(i) / (n - 1), double(j) / (n - 1)).XYZ();
    for (int axis = 0; axis < 2; ++axis)
      for (int j = 0; j < n; ++j)
        for (int c = 1; c <= 3; ++c)
        {
          math_Vector x(1, n);
          for (int i = 0; i < n; ++i)
            x(i + 1) = poles[axis ? id(j, i) : id(i, j)].Coord(c);
          interp.Solve(x);
          for (int i = 0; i < n; ++i)
            poles[axis ? id(j, i) : id(i, j)].SetCoord(c, x(i + 1));
        }
    // Same regularized LS as ribbon_net.fit: the four twists are shared unknowns.
    // Each scalar residual has at most four 3-vector coefficients; form its sparse
    // outer product directly. Ridge term .002^2 keeps the normal equations SPD.
    int              variables = 0;
    std::vector<int> inner(n * n, -1);
    for (int i = 1; i < n - 1; ++i)
      for (int j = 1; j < n - 1; ++j)
        if (i == 1 || i == n - 2 || j == 1 || j == n - 2)
        {
          inner[id(i, j)] = variables;
          variables += 3;
        }
    math_Matrix Q(1, variables, 1, variables, 0.);
    math_Vector rhs(1, variables, 0.);
    for (int i = 1; i <= variables; ++i)
      Q(i, i) = .002 * .002;
    for (int side = 0; side < 4; ++side)
      for (int it = 0; it < 4 * n; ++it)
      {
        double                 t   = double(it) / (4 * n - 1);
        gp_XYZ                 N   = normal(ctx, side, t).XYZ().Normalized();
        auto                   b   = basis(t);
        double                 err = 0;
        std::array<int, 12>    key;
        std::array<double, 12> value;
        int                    used = 0;
        for (int j = 0; j < n; ++j)
          if (b[j])
          {
            int in = side == 0   ? id(1, j)
                     : side == 1 ? id(n - 2, j)
                     : side == 2 ? id(j, 1)
                                 : id(j, n - 2),
                e  = side == 0   ? id(0, j)
                     : side == 1 ? id(n - 1, j)
                     : side == 2 ? id(j, 0)
                                 : id(j, n - 1);
            err += b[j] * N.Dot(poles[in] - poles[e]);
            if (inner[in] >= 0)
              for (int c = 1; c <= 3; ++c)
              {
                key[used]     = inner[in] + c;
                value[used++] = b[j] * N.Coord(c);
              }
          }
        for (int i = 0; i < used; ++i)
        {
          rhs(key[i]) -= err * value[i];
          for (int j = 0; j < used; ++j)
            Q(key[i], key[j]) += value[i] * value[j];
        }
      }
    math_Gauss fit(Q);
    if (!fit.IsDone())
      return false;
    fit.Solve(rhs);
    TColgp_Array2OfPnt p(1, n, 1, n);
    for (int i = 0; i < n; ++i)
      for (int j = 0; j < n; ++j)
      {
        auto ij = id(i, j);
        if (inner[ij] >= 0)
          for (int c = 1; c <= 3; ++c)
            poles[ij].SetCoord(c, poles[ij].Coord(c) + rhs(inner[ij] + c));
        p(i + 1, j + 1) = gp_Pnt(poles[ij]);
      }
    TColStd_Array1OfReal    knots(1, n - 2);
    TColStd_Array1OfInteger mult(1, n - 2);
    for (int i = 1; i <= n - 2; ++i)
    {
      knots(i) = i == 1 ? 0 : i == n - 2 ? 1 : double(i) / (n - 1);
      mult(i)  = i == 1 || i == n - 2 ? 4 : 1;
    }
    Handle(Geom_BSplineSurface) surf = new Geom_BSplineSurface(p, knots, knots, mult, mult, 3, 3);
    for (int side = 0; side < 4; ++side)
      for (int j = 0; j <= 4 * n; ++j)
      {
        double t = double(j) / (4 * n), u = side < 2 ? side : t, v = side < 2 ? t : side - 2;
        gp_Vec a, b;
        gp_Pnt s;
        surf->D1(u, v, s, a, b);
        if (!(s.Distance(pos(ctx, u, v)) <= tol
              && std::abs(a.Crossed(b).Normalized().Dot(normal(ctx, side, t).Normalized()))
                   >= std::cos(angleTol)))
          return false;
      }
    auto face = BRepBuilderAPI_MakeFace(surf, 1e-8).Face();
    if (!BRepCheck_Analyzer(face).IsValid())
      return false;
    result = face;
    return true;
  }
  catch (const Standard_Failure&)
  {
    return false;
  }
}
