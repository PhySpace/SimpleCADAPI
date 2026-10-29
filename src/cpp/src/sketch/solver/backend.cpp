// The backend registry: port of simplecadapi/sketch_solver/backend.py.
#include <algorithm>
#include <map>
#include <mutex>

#include "scad/core/error.hpp"
#include "scad/sketch/native_solver.hpp"
#include "scad/sketch/solver.hpp"

namespace scad {

namespace {

struct Registry {
  std::mutex mutex;
  std::map<std::string, std::shared_ptr<SketchSolverBackend>> backends;
  std::string default_name = kNativeBackendName;
};

Registry& registry() {
  static Registry instance;
  return instance;
}

std::string trimmed(std::string text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos)
    return {};
  const auto last = text.find_last_not_of(" \t\r\n");
  return text.substr(first, last - first + 1);
}

// Callers hold the lock.
void ensure_builtin(Registry& r, const std::string& name) {
  if (name == kNativeBackendName && r.backends.count(name) == 0)
    r.backends[name] = make_native_sketch_solver_backend();
}

void register_locked(Registry& r, std::shared_ptr<SketchSolverBackend> backend, bool replace) {
  if (!backend)
    throw ValueError("A sketch solver backend requires a non-empty name");
  const std::string name = trimmed(backend->name());
  if (name.empty())
    throw ValueError("A sketch solver backend requires a non-empty name");
  if (r.backends.count(name) != 0 && !replace) {
    throw ValueError("Sketch solver backend '" + name + "' is already registered");
  }
  r.backends[name] = std::move(backend);
}

std::shared_ptr<SketchSolverBackend> get_locked(Registry& r, const std::string& name) {
  ensure_builtin(r, name);
  const auto found = r.backends.find(name);
  if (found != r.backends.end())
    return found->second;
  std::string available;
  for (const auto& entry : r.backends)
    available += (available.empty() ? "" : ", ") + entry.first;
  throw ValueError("Unknown sketch solver backend '" + name +
                   "'; registered backends: " + (available.empty() ? "none" : available));
}

}  // namespace

void register_sketch_solver_backend(std::shared_ptr<SketchSolverBackend> backend, bool replace) {
  Registry& r = registry();
  const std::lock_guard<std::mutex> lock(r.mutex);
  register_locked(r, std::move(backend), replace);
}

std::shared_ptr<SketchSolverBackend> get_sketch_solver_backend(const std::optional<std::string>& name) {
  Registry& r = registry();
  const std::lock_guard<std::mutex> lock(r.mutex);
  return get_locked(r, name && !name->empty() ? *name : r.default_name);
}

std::shared_ptr<SketchSolverBackend> get_default_sketch_solver_backend() {
  return get_sketch_solver_backend(std::nullopt);
}

std::vector<std::string> registered_sketch_solver_backends() {
  Registry& r = registry();
  const std::lock_guard<std::mutex> lock(r.mutex);
  ensure_builtin(r, kNativeBackendName);
  std::vector<std::string> names;
  for (const auto& entry : r.backends)
    names.push_back(entry.first);
  return names;
}

void set_default_sketch_solver_backend(const std::string& name) {
  Registry& r = registry();
  const std::lock_guard<std::mutex> lock(r.mutex);
  r.default_name = get_locked(r, name)->name();
}

void set_default_sketch_solver_backend(std::shared_ptr<SketchSolverBackend> backend) {
  Registry& r = registry();
  const std::lock_guard<std::mutex> lock(r.mutex);
  const std::string name = backend ? backend->name() : std::string();
  register_locked(r, std::move(backend), /*replace=*/true);
  r.default_name = name;
}

ScopedSketchSolverBackend::ScopedSketchSolverBackend(const std::string& name)
    : previous_(get_default_sketch_solver_backend()->name()) {
  set_default_sketch_solver_backend(name);
}

ScopedSketchSolverBackend::ScopedSketchSolverBackend(std::shared_ptr<SketchSolverBackend> backend)
    : previous_(get_default_sketch_solver_backend()->name()) {
  set_default_sketch_solver_backend(std::move(backend));
}

ScopedSketchSolverBackend::~ScopedSketchSolverBackend() {
  try {
    set_default_sketch_solver_backend(previous_);
  } catch (const ValueError&) {
    // get_locked throws ValueError for a name that is no longer registered.  The previous default was
    // registered when we captured it, and a destructor must not throw: the default stays as it is.
    return;
  }
}

}  // namespace scad
