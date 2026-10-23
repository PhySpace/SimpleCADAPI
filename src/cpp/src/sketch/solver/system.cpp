#include "system.hpp"

#include <algorithm>

#include "scad/core/error.hpp"

namespace scad::sketch_solver {

Dual Env::operator()(int param) const {
  const Param& p = table_[param];
  if (p.unknown < 0) return Dual(p.value);
  auto found = std::find(slots_->begin(), slots_->end(), p.unknown);
  if (found == slots_->end()) {
    if (writable_ == nullptr) throw RuntimeError("sketch solver: equation touched an unregistered unknown");
    if (static_cast<int>(writable_->size()) >= kSlots) {
      throw ValueError("A sketch constraint involves more unknowns than the native solver supports (" +
                       std::to_string(kSlots) + ")");
    }
    writable_->push_back(p.unknown);
    found = slots_->end() - 1;
  }
  Dual d(x_[p.unknown]);
  d.g[static_cast<std::size_t>(found - slots_->begin())] = 1.0;
  return d;
}

int ParamTable::add(double value, bool fixed) {
  Param p;
  p.value = value;
  p.fixed = fixed;
  params_.push_back(p);
  return static_cast<int>(params_.size()) - 1;
}

Pt ParamTable::add_point(double x, double y, bool fixed) {
  const int px = add(x, fixed);
  const int py = add(y, fixed);
  return {px, py};
}

void ParamTable::assign_unknowns() {
  unknown_count_ = 0;
  for (Param& p : params_) p.unknown = p.fixed ? -1 : unknown_count_++;
}

std::vector<double> ParamTable::initial_unknowns() const {
  std::vector<double> x(static_cast<std::size_t>(unknown_count_), 0.0);
  for (const Param& p : params_) {
    if (p.unknown >= 0) x[static_cast<std::size_t>(p.unknown)] = p.value;
  }
  return x;
}

void System::begin_block(std::string constraint_id) {
  Block block;
  block.constraint_id = std::move(constraint_id);
  block.first = equations.size();
  blocks.push_back(std::move(block));
}

void System::add_equation(Residual fn) {
  if (blocks.empty()) begin_block("");
  Equation eq;
  eq.fn = std::move(fn);
  equations.push_back(std::move(eq));
  ++blocks.back().count;
}

void System::finalize() {
  params.assign_unknowns();
  const std::vector<double> x = params.initial_unknowns();
  for (Equation& eq : equations) {
    eq.slots.clear();
    const Env env(params, x.data(), eq.slots);
    (void)eq.fn(env);
  }
}

void System::evaluate(const std::vector<std::size_t>& active, const std::vector<double>& x,
                      std::vector<double>& residual, Matrix* jacobian) const {
  residual.assign(active.size(), 0.0);
  if (jacobian != nullptr) *jacobian = Matrix(static_cast<int>(active.size()), params.unknown_count());
  for (std::size_t row = 0; row < active.size(); ++row) {
    const Equation& eq = equations[active[row]];
    const Env env(params, x.data(), static_cast<const std::vector<int>&>(eq.slots));
    const Dual value = eq.fn(env);
    residual[row] = value.v;
    if (jacobian != nullptr) {
      for (std::size_t s = 0; s < eq.slots.size(); ++s) {
        (*jacobian)(static_cast<int>(row), eq.slots[s]) = value.g[s];
      }
    }
  }
}

std::vector<std::size_t> System::active_equations(const std::vector<bool>& block_enabled) const {
  std::vector<std::size_t> active;
  for (std::size_t b = 0; b < blocks.size(); ++b) {
    const Block& block = blocks[b];
    const bool on = block.constraint_id.empty() || (b < block_enabled.size() && block_enabled[b]);
    if (!on) continue;
    for (std::size_t i = 0; i < block.count; ++i) active.push_back(block.first + i);
  }
  return active;
}

}  // namespace scad::sketch_solver
