// The in-house sketch solver: the default backend.
//
// Damped Gauss-Newton on analytic (forward-mode autodiff) Jacobians, minimum-norm
// steps from a Jacobi SVD, DOF counted as unknowns minus the rank of the
// row-normalised Jacobian.  No third-party solver, deterministic, single threaded.
// docs/sketch-solver.md has the equation catalogue and the differences from py-slvs.
#pragma once

#include <memory>
#include <string>

#include "scad/sketch/solver.hpp"

namespace scad {

class NativeSketchSolverBackend final : public SketchSolverBackend {
 public:
  std::string name() const override { return kNativeBackendName; }
  std::string version() const override { return "1.0.0"; }
  SketchSolveResult solve(const Sketch& sketch, const SketchSolverOptions& options) const override;
};

std::shared_ptr<SketchSolverBackend> make_native_sketch_solver_backend();

}  // namespace scad
