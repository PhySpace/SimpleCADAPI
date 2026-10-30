// The nonlinear system a sketch lowers to: parameters (some unknown, some
// constant), residual equations grouped by the constraint that produced them,
// and the machinery to evaluate residuals and the Jacobian.
#pragma once

#include <cstddef>
#include <functional>
#include <string>
#include <vector>

#include "dense.hpp"
#include "dual.hpp"

namespace scad::sketch_solver {

// A named scalar of the system: a point coordinate, a circle radius, a helper.
struct Param {
  double value = 0.0;  // initial value (and the constant, when fixed)
  bool fixed = false;
  int unknown = -1;  // index into the solution vector, -1 for a constant
};

// A 2D point as two parameter ids.
struct Pt {
  int x = -1;
  int y = -1;
};

// A 2D vector of Duals, with the handful of operations the equations use.
struct V2 {
  Dual x;
  Dual y;
};
inline V2 operator+(const V2& a, const V2& b) {
  return {a.x + b.x, a.y + b.y};
}
inline V2 operator-(const V2& a, const V2& b) {
  return {a.x - b.x, a.y - b.y};
}
inline V2 operator*(const V2& a, double s) {
  return {a.x * s, a.y * s};
}
inline Dual dot(const V2& a, const V2& b) {
  return a.x * b.x + a.y * b.y;
}
inline Dual cross(const V2& a, const V2& b) {
  return a.x * b.y - a.y * b.x;
}
inline Dual length(const V2& a) {
  return sqrt(dot(a, a));
}

class ParamTable;

// Evaluation context handed to an equation's closure.  `(id)` returns the
// parameter as a Dual: a variable on its own slot when unknown, else a constant.
class Env {
 public:
  // Discovery: unknowns the closure touches are appended to `slots`.
  Env(const ParamTable& table, const double* x, std::vector<int>& slots)
      : table_(table), x_(x), slots_(&slots), writable_(&slots) {}
  // Evaluation: `slots` was filled by discovery.
  Env(const ParamTable& table, const double* x, const std::vector<int>& slots) : table_(table), x_(x), slots_(&slots) {}
  Dual operator()(int param) const;
  V2 operator()(const Pt& p) const { return {(*this)(p.x), (*this)(p.y)}; }

 private:
  const ParamTable& table_;
  const double* x_;
  const std::vector<int>* slots_;
  std::vector<int>* writable_ = nullptr;
};

class ParamTable {
 public:
  int add(double value, bool fixed = false);
  Pt add_point(double x, double y, bool fixed = false);
  Param& operator[](int id) { return params_[static_cast<std::size_t>(id)]; }
  const Param& operator[](int id) const { return params_[static_cast<std::size_t>(id)]; }
  std::size_t size() const noexcept { return params_.size(); }

  // Give every non-fixed parameter a position in the solution vector.
  void assign_unknowns();
  int unknown_count() const noexcept { return unknown_count_; }
  std::vector<double> initial_unknowns() const;

 private:
  std::vector<Param> params_;
  int unknown_count_ = 0;
};

using Residual = std::function<Dual(const Env&)>;

struct Equation {
  Residual fn;
  std::vector<int> slots;  // unknown indices this equation depends on
};

// The equations one constraint (or the implicit rules of an entity) produced.
struct Block {
  std::string constraint_id;  // empty: implicit (an arc's equal-radius rule)
  std::size_t first = 0;
  std::size_t count = 0;
};

class System {
 public:
  ParamTable params;
  std::vector<Equation> equations;
  std::vector<Block> blocks;

  // Start a block; equations added until the next call belong to it.
  void begin_block(std::string constraint_id);
  void add_equation(Residual fn);

  // After lowering: assign unknown indices and discover each equation's support.
  void finalize();

  // Residuals of the listed equations at x, and optionally the Jacobian.
  void evaluate(const std::vector<std::size_t>& active, const std::vector<double>& x, std::vector<double>& residual,
                Matrix* jacobian) const;

  // Equation indices of the implicit blocks plus the listed explicit ones.
  std::vector<std::size_t> active_equations(const std::vector<bool>& block_enabled) const;
};

}  // namespace scad::sketch_solver
