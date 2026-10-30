// Damped Gauss-Newton / Levenberg-Marquardt on a System, and the rank of its
// Jacobian (the degrees-of-freedom measure).
#pragma once

#include <cstddef>
#include <limits>
#include <vector>

#include "system.hpp"

namespace scad::sketch_solver {

struct SolveOutcome {
  bool converged = false;
  std::vector<double> x;
  int iterations = 0;
  double residual_inf = std::numeric_limits<double>::infinity();
  double residual_l2 = std::numeric_limits<double>::infinity();
};

// Singular values below this fraction of the largest (of the row-normalised
// Jacobian) count as zero when ranking.  Redundant constraints sit near 1e-15,
// independent ones above 1e-3, so the choice has a wide margin; SolveSpace uses
// 1e-4 on Gaussian pivots.
inline constexpr double kRankTolerance = 1e-6;

// Minimise |residual| over the unknowns from x0.  `converged` means every
// listed residual is within `tolerance`.  The unknowns the active equations do
// not touch never move (minimum-norm steps).
SolveOutcome solve_equations(const System& system, const std::vector<std::size_t>& active, std::vector<double> x0,
                             double tolerance, int max_iterations);

// Rank of the row-normalised Jacobian of the active equations at x.
int jacobian_rank(const System& system, const std::vector<std::size_t>& active, const std::vector<double>& x);

double max_abs(const std::vector<double>& values);
double l2_norm(const std::vector<double>& values);

}  // namespace scad::sketch_solver
