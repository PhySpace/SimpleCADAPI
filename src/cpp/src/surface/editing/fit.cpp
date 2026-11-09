// Least-squares fitting with fixed parameters; see fit.hpp.  The basis functions are the Cox-de Boor recursion
// (The NURBS Book, A2.1 / A2.2); the normal equations are solved by Gaussian elimination with partial pivoting.
#include "fit.hpp"

#include <algorithm>
#include <cmath>

#include "scad/core/error.hpp"

namespace scad::surface::editing {

namespace {

// The knot span index of `u` (flat knots, n + 1 poles).
int find_span(int n, int degree, double u, const std::vector<double>& flat) {
  if (u >= flat[static_cast<std::size_t>(n + 1)])
    return n;
  if (u <= flat[static_cast<std::size_t>(degree)])
    return degree;
  int low = degree, high = n + 1;
  int mid = (low + high) / 2;
  while (u < flat[static_cast<std::size_t>(mid)] || u >= flat[static_cast<std::size_t>(mid + 1)]) {
    if (u < flat[static_cast<std::size_t>(mid)])
      high = mid;
    else
      low = mid;
    mid = (low + high) / 2;
  }
  return mid;
}

// The degree + 1 non-zero basis functions at `u` in span `span`.
std::vector<double> basis(int span, double u, int degree, const std::vector<double>& flat) {
  std::vector<double> values(static_cast<std::size_t>(degree + 1), 0.0), left(values.size()), right(values.size());
  values[0] = 1.0;
  for (int j = 1; j <= degree; ++j) {
    left[static_cast<std::size_t>(j)] = u - flat[static_cast<std::size_t>(span + 1 - j)];
    right[static_cast<std::size_t>(j)] = flat[static_cast<std::size_t>(span + j)] - u;
    double saved = 0.0;
    for (int r = 0; r < j; ++r) {
      const double denominator = right[static_cast<std::size_t>(r + 1)] + left[static_cast<std::size_t>(j - r)];
      const double temp = values[static_cast<std::size_t>(r)] / denominator;
      values[static_cast<std::size_t>(r)] = saved + right[static_cast<std::size_t>(r + 1)] * temp;
      saved = left[static_cast<std::size_t>(j - r)] * temp;
    }
    values[static_cast<std::size_t>(j)] = saved;
  }
  return values;
}

// Solve A x = b for three right-hand sides at once (A is size x size, row-major).
std::vector<gp_XYZ> solve(std::vector<double> a, std::vector<gp_XYZ> b, int size) {
  const auto at = [&](int r, int c) -> double& { return a[static_cast<std::size_t>(r * size + c)]; };
  for (int col = 0; col < size; ++col) {
    int pivot = col;
    for (int r = col + 1; r < size; ++r)
      if (std::abs(at(r, col)) > std::abs(at(pivot, col)))
        pivot = r;
    if (std::abs(at(pivot, col)) < 1e-14)
      throw ValueError("the fit is under-determined: use fewer poles or more samples");
    if (pivot != col) {
      for (int c = 0; c < size; ++c)
        std::swap(at(col, c), at(pivot, c));
      std::swap(b[static_cast<std::size_t>(col)], b[static_cast<std::size_t>(pivot)]);
    }
    for (int r = col + 1; r < size; ++r) {
      const double factor = at(r, col) / at(col, col);
      if (factor == 0.0)
        continue;
      for (int c = col; c < size; ++c)
        at(r, c) -= factor * at(col, c);
      b[static_cast<std::size_t>(r)] -= b[static_cast<std::size_t>(col)] * factor;
    }
  }
  std::vector<gp_XYZ> x(static_cast<std::size_t>(size));
  for (int r = size - 1; r >= 0; --r) {
    gp_XYZ sum = b[static_cast<std::size_t>(r)];
    for (int c = r + 1; c < size; ++c)
      sum -= x[static_cast<std::size_t>(c)] * at(r, c);
    x[static_cast<std::size_t>(r)] = sum / at(r, r);
  }
  return x;
}

}  // namespace

KnotVector uniform_clamped_knots(double first, double last, int poles, int degree) {
  KnotVector out;
  const int interior = poles - degree - 1;
  out.knots.push_back(first);
  out.multiplicities.push_back(degree + 1);
  for (int j = 1; j <= interior; ++j) {
    out.knots.push_back(first + (last - first) * j / (interior + 1));
    out.multiplicities.push_back(1);
  }
  out.knots.push_back(last);
  out.multiplicities.push_back(degree + 1);
  for (std::size_t i = 0; i < out.knots.size(); ++i)
    for (int m = 0; m < out.multiplicities[i]; ++m)
      out.flat.push_back(out.knots[i]);
  return out;
}

std::vector<gp_XYZ> fit_poles(const std::vector<double>& parameters, const std::vector<gp_XYZ>& values,
                              const KnotVector& knots, int degree, int poles) {
  const int n = poles - 1;
  std::vector<gp_XYZ> out(static_cast<std::size_t>(poles));
  out.front() = values.front();
  out.back() = values.back();
  const int unknowns = poles - 2;
  if (unknowns <= 0)
    return out;
  std::vector<double> normal(static_cast<std::size_t>(unknowns * unknowns), 0.0);
  std::vector<gp_XYZ> rhs(static_cast<std::size_t>(unknowns), gp_XYZ(0, 0, 0));
  for (std::size_t k = 0; k < parameters.size(); ++k) {
    const double u = parameters[k];
    const int span = find_span(n, degree, u, knots.flat);
    const std::vector<double> nb = basis(span, u, degree, knots.flat);
    // Row k of the basis matrix: N_i(u) for i = span - degree .. span.
    gp_XYZ residual = values[k];
    for (int r = 0; r <= degree; ++r) {
      const int i = span - degree + r;
      if (i == 0)
        residual -= out.front() * nb[static_cast<std::size_t>(r)];
      else if (i == n)
        residual -= out.back() * nb[static_cast<std::size_t>(r)];
    }
    for (int r = 0; r <= degree; ++r) {
      const int i = span - degree + r;
      if (i <= 0 || i >= n)
        continue;
      rhs[static_cast<std::size_t>(i - 1)] += residual * nb[static_cast<std::size_t>(r)];
      for (int c = 0; c <= degree; ++c) {
        const int j = span - degree + c;
        if (j <= 0 || j >= n)
          continue;
        normal[static_cast<std::size_t>((i - 1) * unknowns + (j - 1))] +=
            nb[static_cast<std::size_t>(r)] * nb[static_cast<std::size_t>(c)];
      }
    }
  }
  const std::vector<gp_XYZ> interior = solve(std::move(normal), std::move(rhs), unknowns);
  for (int i = 0; i < unknowns; ++i)
    out[static_cast<std::size_t>(i + 1)] = interior[static_cast<std::size_t>(i)];
  return out;
}

TColStd_Array1OfReal knot_array(const KnotVector& knots) {
  TColStd_Array1OfReal out(1, static_cast<int>(knots.knots.size()));
  for (std::size_t i = 0; i < knots.knots.size(); ++i)
    out.SetValue(static_cast<int>(i) + 1, knots.knots[i]);
  return out;
}

TColStd_Array1OfInteger multiplicity_array(const KnotVector& knots) {
  TColStd_Array1OfInteger out(1, static_cast<int>(knots.multiplicities.size()));
  for (std::size_t i = 0; i < knots.multiplicities.size(); ++i)
    out.SetValue(static_cast<int>(i) + 1, knots.multiplicities[i]);
  return out;
}

std::vector<double> even_parameters(double first, double last, int count) {
  std::vector<double> out;
  out.reserve(static_cast<std::size_t>(count));
  for (int i = 0; i < count; ++i)
    out.push_back(i == count - 1 ? last : first + (last - first) * i / (count - 1));
  return out;
}

}  // namespace scad::surface::editing
