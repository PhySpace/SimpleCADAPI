// Small dense linear algebra for the sketch solver: a row-major matrix, a
// one-sided Jacobi singular value decomposition, and the numerical rank.
//
// Sketch systems are tens to a few hundred unknowns, so an O(m n^2) Jacobi SVD
// is cheap, needs no pivoting heuristics, and gives the minimum-norm
// least-squares step and the rank from the same factorization.
#pragma once

#include <cstddef>
#include <vector>

namespace scad::sketch_solver {

class Matrix {
 public:
  Matrix() = default;
  Matrix(int rows, int cols) : rows_(rows), cols_(cols), a_(static_cast<std::size_t>(rows) * static_cast<std::size_t>(cols), 0.0) {}

  int rows() const noexcept { return rows_; }
  int cols() const noexcept { return cols_; }
  double& operator()(int r, int c) { return a_[index(r, c)]; }
  double operator()(int r, int c) const { return a_[index(r, c)]; }
  double* row(int r) { return a_.data() + index(r, 0); }
  const double* row(int r) const { return a_.data() + index(r, 0); }

 private:
  std::size_t index(int r, int c) const {
    return static_cast<std::size_t>(r) * static_cast<std::size_t>(cols_) + static_cast<std::size_t>(c);
  }
  int rows_ = 0;
  int cols_ = 0;
  std::vector<double> a_;
};

// A = U diag(s) V^T with k = min(rows, cols) singular values in descending
// order.  U is rows x k, V is cols x k; a zero singular value has a zero column.
struct Svd {
  std::vector<double> s;
  Matrix u;
  Matrix v;
};

Svd svd(const Matrix& a);

// Number of singular values above `relative_tolerance * s_max`.
int numerical_rank(const Svd& decomposition, double relative_tolerance);

// Rank of `a` after scaling every non-zero row to unit length (so constraints
// of different units weigh the same), the quantity DOF is counted with.
int normalized_rank(Matrix a, double relative_tolerance);

}  // namespace scad::sketch_solver
