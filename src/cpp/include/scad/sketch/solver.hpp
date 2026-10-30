// The solver boundary: port of simplecadapi/sketch_solver/backend.py.
//
// A backend turns a declarative Sketch into a SketchSolveResult.  The default is
// the in-house native solver (scad/sketch/native_solver.hpp); other backends (a
// wrapper around libslvs, a test double, a Python object) register under their
// own name.  A backend never invokes another one behind the caller's back.
#pragma once

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "scad/core/tolerance.hpp"
#include "scad/sketch/types.hpp"

namespace scad {

class Sketch;

struct SketchSolverOptions {
  double tolerance = tol::kSketchSolveResidual;
  int max_iterations = 80;
};

class SketchSolverBackend {
 public:
  virtual ~SketchSolverBackend() = default;
  // Stable identifier persisted in solve evidence.
  virtual std::string name() const = 0;
  virtual std::string version() const = 0;
  // Solve without mutating the sketch.
  virtual SketchSolveResult solve(const Sketch& sketch, const SketchSolverOptions& options) const = 0;
};

// The name of the backend used when none is asked for.
inline constexpr const char* kNativeBackendName = "scad-native";

// ValueError when `backend` is empty or the name is already taken (unless `replace`).
void register_sketch_solver_backend(std::shared_ptr<SketchSolverBackend> backend, bool replace = false);

// Omitted name selects the process default.  ValueError for an unknown name,
// listing the registered ones.
std::shared_ptr<SketchSolverBackend> get_sketch_solver_backend(const std::optional<std::string>& name = std::nullopt);
std::shared_ptr<SketchSolverBackend> get_default_sketch_solver_backend();
std::vector<std::string> registered_sketch_solver_backends();

void set_default_sketch_solver_backend(const std::string& name);
// Registers (replacing) and selects.
void set_default_sketch_solver_backend(std::shared_ptr<SketchSolverBackend> backend);

// `with sketch_solver_backend(...)`: select for the lifetime of the object,
// restore the previous default afterwards.
class ScopedSketchSolverBackend {
 public:
  explicit ScopedSketchSolverBackend(const std::string& name);
  explicit ScopedSketchSolverBackend(std::shared_ptr<SketchSolverBackend> backend);
  ~ScopedSketchSolverBackend();
  ScopedSketchSolverBackend(const ScopedSketchSolverBackend&) = delete;
  ScopedSketchSolverBackend& operator=(const ScopedSketchSolverBackend&) = delete;

 private:
  std::string previous_;
};

}  // namespace scad
