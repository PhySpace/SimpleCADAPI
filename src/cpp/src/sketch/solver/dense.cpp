#include "dense.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace scad::sketch_solver {

namespace {

constexpr int kMaxSweeps = 60;
constexpr double kRotationThreshold = 1e-15;

Matrix transposed(const Matrix& a) {
  Matrix t(a.cols(), a.rows());
  for (int r = 0; r < a.rows(); ++r) {
    for (int c = 0; c < a.cols(); ++c) t(c, r) = a(r, c);
  }
  return t;
}

// Hestenes: rotate column pairs of W (starting as `a`) until they are mutually
// orthogonal; V accumulates the rotations.  Requires cols <= rows for the
// result to be the thin SVD; the caller transposes otherwise.
Svd hestenes(const Matrix& a) {
  const int p = a.rows();
  const int q = a.cols();
  Matrix w = a;
  Matrix v(q, q);
  for (int i = 0; i < q; ++i) v(i, i) = 1.0;

  for (int sweep = 0; sweep < kMaxSweeps; ++sweep) {
    bool rotated = false;
    for (int i = 0; i < q - 1; ++i) {
      for (int j = i + 1; j < q; ++j) {
        double alpha = 0.0;
        double beta = 0.0;
        double gamma = 0.0;
        for (int r = 0; r < p; ++r) {
          const double wi = w(r, i);
          const double wj = w(r, j);
          alpha += wi * wi;
          beta += wj * wj;
          gamma += wi * wj;
        }
        if (gamma == 0.0 || std::abs(gamma) <= kRotationThreshold * std::sqrt(alpha * beta)) continue;
        rotated = true;
        const double zeta = (beta - alpha) / (2.0 * gamma);
        const double t = (zeta >= 0.0 ? 1.0 : -1.0) / (std::abs(zeta) + std::sqrt(1.0 + zeta * zeta));
        const double c = 1.0 / std::sqrt(1.0 + t * t);
        const double s = c * t;
        for (int r = 0; r < p; ++r) {
          const double wi = w(r, i);
          const double wj = w(r, j);
          w(r, i) = c * wi - s * wj;
          w(r, j) = s * wi + c * wj;
        }
        for (int r = 0; r < q; ++r) {
          const double vi = v(r, i);
          const double vj = v(r, j);
          v(r, i) = c * vi - s * vj;
          v(r, j) = s * vi + c * vj;
        }
      }
    }
    if (!rotated) break;
  }

  std::vector<double> norms(static_cast<std::size_t>(q), 0.0);
  for (int j = 0; j < q; ++j) {
    double sum = 0.0;
    for (int r = 0; r < p; ++r) sum += w(r, j) * w(r, j);
    norms[static_cast<std::size_t>(j)] = std::sqrt(sum);
  }
  std::vector<int> order(static_cast<std::size_t>(q));
  std::iota(order.begin(), order.end(), 0);
  std::stable_sort(order.begin(), order.end(), [&norms](int x, int y) {
    return norms[static_cast<std::size_t>(x)] > norms[static_cast<std::size_t>(y)];
  });

  Svd out;
  out.s.resize(static_cast<std::size_t>(q));
  out.u = Matrix(p, q);
  out.v = Matrix(q, q);
  for (int k = 0; k < q; ++k) {
    const int j = order[static_cast<std::size_t>(k)];
    const double sigma = norms[static_cast<std::size_t>(j)];
    out.s[static_cast<std::size_t>(k)] = sigma;
    for (int r = 0; r < q; ++r) out.v(r, k) = v(r, j);
    if (sigma > 0.0) {
      for (int r = 0; r < p; ++r) out.u(r, k) = w(r, j) / sigma;
    }
  }
  return out;
}

}  // namespace

Svd svd(const Matrix& a) {
  if (a.rows() == 0 || a.cols() == 0) {
    Svd empty;
    empty.u = Matrix(a.rows(), 0);
    empty.v = Matrix(a.cols(), 0);
    return empty;
  }
  if (a.cols() <= a.rows()) return hestenes(a);
  // A^T = U' S V'^T  =>  A = V' S U'^T.
  Svd t = hestenes(transposed(a));
  Svd out;
  out.s = std::move(t.s);
  out.u = std::move(t.v);
  out.v = std::move(t.u);
  return out;
}

int numerical_rank(const Svd& decomposition, double relative_tolerance) {
  if (decomposition.s.empty()) return 0;
  const double largest = decomposition.s.front();
  if (!(largest > 0.0)) return 0;
  int rank = 0;
  for (const double sigma : decomposition.s) {
    if (sigma > relative_tolerance * largest) ++rank;
  }
  return rank;
}

int normalized_rank(Matrix a, double relative_tolerance) {
  for (int r = 0; r < a.rows(); ++r) {
    double sum = 0.0;
    for (int c = 0; c < a.cols(); ++c) sum += a(r, c) * a(r, c);
    const double norm = std::sqrt(sum);
    if (norm < 1e-12) {
      for (int c = 0; c < a.cols(); ++c) a(r, c) = 0.0;
      continue;
    }
    for (int c = 0; c < a.cols(); ++c) a(r, c) /= norm;
  }
  return numerical_rank(svd(a), relative_tolerance);
}

}  // namespace scad::sketch_solver
