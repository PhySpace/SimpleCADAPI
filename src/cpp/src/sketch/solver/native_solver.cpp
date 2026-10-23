#include "scad/sketch/native_solver.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

#include "model.hpp"
#include "newton.hpp"
#include "results.hpp"
#include "scad/sketch/sketch.hpp"

namespace scad {

namespace {

using namespace sketch_solver;  // NOLINT(google-build-using-namespace): this file is the solver's front door

// SolveSpace's result codes, which the sketch evidence persists.
constexpr int kResultOkay = 0;
constexpr int kResultInconsistent = 1;
constexpr int kResultDidntConverge = 2;
constexpr int kResultRedundantOkay = 5;

// Naming constraints one by one is a series of solves; past this many it costs
// more than it tells.
constexpr std::size_t kMaxNamedConstraints = 400;

// A constraint is blamed when adding it (in document order) to the constraints
// accepted so far leaves a system that no longer converges: the later of two
// conflicting constraints, like the failing-constraint list of the py-slvs backend.
std::vector<std::string> blame_by_incremental_consistency(const System& system, const std::vector<double>& x0,
                                                          const SketchSolverOptions& options) {
  std::vector<bool> enabled(system.blocks.size(), false);
  std::size_t explicit_blocks = 0;
  for (const Block& block : system.blocks) explicit_blocks += block.constraint_id.empty() ? 0 : 1;
  if (explicit_blocks > kMaxNamedConstraints) return {};

  std::vector<std::string> failed;
  std::vector<double> accepted = x0;
  for (std::size_t b = 0; b < system.blocks.size(); ++b) {
    const Block& block = system.blocks[b];
    if (block.constraint_id.empty() || block.count == 0) continue;
    enabled[b] = true;
    const SolveOutcome outcome = solve_equations(system, system.active_equations(enabled), accepted,
                                                 options.tolerance, options.max_iterations);
    if (outcome.converged) {
      accepted = outcome.x;
    } else {
      enabled[b] = false;
      failed.push_back(block.constraint_id);
    }
  }
  return failed;
}

// Full-rank failure: every constraint still violated at the last iterate.
std::vector<std::string> blame_by_residual(const System& system, const std::vector<double>& x, double tolerance) {
  std::vector<std::string> failed;
  for (const Block& block : system.blocks) {
    if (block.constraint_id.empty() || block.count == 0) continue;
    std::vector<std::size_t> rows;
    for (std::size_t i = 0; i < block.count; ++i) rows.push_back(block.first + i);
    std::vector<double> residual;
    system.evaluate(rows, x, residual, nullptr);
    if (max_abs(residual) > tolerance || !std::all_of(residual.begin(), residual.end(), [](double v) { return std::isfinite(v); })) {
      failed.push_back(block.constraint_id);
    }
  }
  return failed;
}

std::string failure_message(int code) {
  return code == kResultInconsistent ? "Sketch constraints are inconsistent." : "Sketch solver did not converge.";
}

}  // namespace

SketchSolveResult NativeSketchSolverBackend::solve(const Sketch& sketch, const SketchSolverOptions& options) const {
  const Model model(sketch);
  const System& system = model.system;
  const std::vector<bool> all_enabled(system.blocks.size(), true);
  const std::vector<std::size_t> active = system.active_equations(all_enabled);
  const std::vector<double> x0 = system.params.initial_unknowns();

  const SolveOutcome outcome = solve_equations(system, active, x0, options.tolerance, options.max_iterations);
  const int rank = jacobian_rank(system, active, outcome.x);
  const bool rank_deficient = rank < static_cast<int>(active.size());

  SketchSolveResult result;
  result.sketch_id = sketch.sketch_id();
  result.backend = name();
  result.backend_version = version();
  result.iterations = outcome.iterations;

  if (outcome.converged) {
    result.backend_status_code = rank_deficient ? kResultRedundantOkay : kResultOkay;
    result.dof = std::max(0, system.params.unknown_count() - rank);
    result.status = result.dof > 0 ? "underconstrained" : "solved";
    result.residual_norm = outcome.residual_l2;
    if (rank_deficient) {
      result.diagnostics.push_back(
          {std::nullopt, "warning", "redundant_constraints", "Sketch has redundant but consistent constraints.", std::nullopt});
    }
    if (result.dof > 0) {
      result.diagnostics.push_back({std::nullopt, "warning", "underconstrained",
                                    "Sketch has " + std::to_string(result.dof) + " remaining DOF.", std::nullopt});
    }
    SolvedGeometry solved = assemble_solution(model, outcome.x);
    add_measurements(model, solved);
    result.solved_points = std::move(solved.points);
    result.solved_scalars = std::move(solved.scalars);
    result.solved_entities = std::move(solved.entities);
    return result;
  }

  // A failed solve leaves the geometry where the document put it, like py-slvs.
  const int code = rank_deficient ? kResultInconsistent : kResultDidntConverge;
  result.backend_status_code = code;
  result.status = code == kResultInconsistent ? "conflicting" : "failed";
  result.dof = 0;
  result.residual_norm = std::numeric_limits<double>::infinity();
  const std::vector<std::string> failed = code == kResultInconsistent
                                              ? blame_by_incremental_consistency(system, x0, options)
                                              : blame_by_residual(system, outcome.x, options.tolerance);
  const std::string legacy_code = code == kResultInconsistent ? "residual_too_large" : "did_not_converge";
  if (failed.empty()) {
    result.diagnostics.push_back({std::nullopt, "error", legacy_code, failure_message(code), std::nullopt});
  }
  for (const std::string& constraint_id : failed) {
    result.diagnostics.push_back({constraint_id, "error", legacy_code, failure_message(code), std::nullopt});
  }
  SolvedGeometry solved = assemble_solution(model, x0);
  add_measurements(model, solved);
  result.solved_points = std::move(solved.points);
  result.solved_scalars = std::move(solved.scalars);
  result.solved_entities = std::move(solved.entities);
  return result;
}

std::shared_ptr<SketchSolverBackend> make_native_sketch_solver_backend() {
  return std::make_shared<NativeSketchSolverBackend>();
}

}  // namespace scad
