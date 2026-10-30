#include "newton.hpp"

#include <algorithm>
#include <cmath>

namespace scad::sketch_solver {

namespace {

// Once the residual is this small further iterations only chase rounding noise.
constexpr double kExactResidual = 1e-13;
// Extra iterations after reaching `tolerance`, to land on the exact root.
constexpr int kPolishIterations = 3;
// Relative singular-value cutoff of the step's pseudo-inverse.
constexpr double kStepTruncation = 1e-9;
constexpr int kDampingAttempts = 14;
constexpr int kMaxStalls = 6;

bool all_finite(const std::vector<double>& values) {
  return std::all_of(values.begin(), values.end(), [](double v) { return std::isfinite(v); });
}

// The (damped) pseudo-inverse step  -V diag(s / (s^2 + lambda)) U^T r.
std::vector<double> newton_step(const Svd& d, const std::vector<double>& r, double lambda, int unknowns) {
  std::vector<double> step(static_cast<std::size_t>(unknowns), 0.0);
  if (d.s.empty())
    return step;
  const double cutoff = kStepTruncation * d.s.front();
  for (std::size_t k = 0; k < d.s.size(); ++k) {
    const double sigma = d.s[k];
    if (!(sigma > cutoff))
      continue;
    double projection = 0.0;
    const int col = static_cast<int>(k);
    for (int i = 0; i < d.u.rows(); ++i)
      projection += d.u(i, col) * r[static_cast<std::size_t>(i)];
    const double factor = -sigma / (sigma * sigma + lambda) * projection;
    for (int j = 0; j < d.v.rows(); ++j)
      step[static_cast<std::size_t>(j)] += factor * d.v(j, col);
  }
  return step;
}

}  // namespace

double max_abs(const std::vector<double>& values) {
  double largest = 0.0;
  for (const double v : values)
    largest = std::max(largest, std::abs(v));
  return largest;
}

double l2_norm(const std::vector<double>& values) {
  double sum = 0.0;
  for (const double v : values)
    sum += v * v;
  return std::sqrt(sum);
}

SolveOutcome solve_equations(const System& system, const std::vector<std::size_t>& active, std::vector<double> x0,
                             double tolerance, int max_iterations) {
  SolveOutcome out;
  out.x = std::move(x0);
  const int unknowns = system.params.unknown_count();

  std::vector<double> r;
  system.evaluate(active, out.x, r, nullptr);
  if (!all_finite(r))
    return out;  // the start is already degenerate
  double inf = max_abs(r);
  double l2 = l2_norm(r);

  int polish_left = kPolishIterations;
  int stalls = 0;
  Matrix jacobian;
  for (int iteration = 0; iteration < max_iterations; ++iteration) {
    if (inf <= kExactResidual)
      break;
    if (inf <= tolerance && polish_left-- <= 0)
      break;
    if (unknowns == 0 || active.empty())
      break;

    system.evaluate(active, out.x, r, &jacobian);
    const Svd decomposition = svd(jacobian);
    const double sigma_max = decomposition.s.empty() ? 0.0 : decomposition.s.front();

    bool accepted = false;
    std::vector<double> candidate;
    std::vector<double> candidate_r;
    for (int attempt = 0; attempt < kDampingAttempts && !accepted; ++attempt) {
      const double lambda = attempt == 0 ? 0.0 : sigma_max * sigma_max * 1e-10 * std::pow(10.0, attempt - 1);
      const std::vector<double> step = newton_step(decomposition, r, lambda, unknowns);
      candidate = out.x;
      for (std::size_t i = 0; i < candidate.size(); ++i)
        candidate[i] += step[i];
      system.evaluate(active, candidate, candidate_r, nullptr);
      if (!all_finite(candidate_r))
        continue;
      if (l2_norm(candidate_r) < l2)
        accepted = true;
    }
    if (!accepted)
      break;

    ++out.iterations;
    const double new_l2 = l2_norm(candidate_r);
    stalls = (l2 - new_l2) < 1e-3 * l2 ? stalls + 1 : 0;
    out.x = std::move(candidate);
    r = std::move(candidate_r);
    l2 = new_l2;
    inf = max_abs(r);
    if (stalls >= kMaxStalls && inf > tolerance)
      break;
  }

  out.residual_inf = inf;
  out.residual_l2 = l2;
  out.converged = inf <= tolerance;
  return out;
}

int jacobian_rank(const System& system, const std::vector<std::size_t>& active, const std::vector<double>& x) {
  if (active.empty() || system.params.unknown_count() == 0)
    return 0;
  std::vector<double> r;
  Matrix jacobian;
  system.evaluate(active, x, r, &jacobian);
  return normalized_rank(std::move(jacobian), kRankTolerance);
}

}  // namespace scad::sketch_solver
