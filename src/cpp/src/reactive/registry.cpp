#include "scad/reactive/registry.hpp"

#include "internal.hpp"
#include "scad/core/error.hpp"

namespace scad::reactive {

ExecutorRegistry::ExecutorRegistry(bool builtins) {
  if (builtins) detail::register_selection_executors(*this);
}

ExecutorRegistry& ExecutorRegistry::global() {
  static ExecutorRegistry registry;
  return registry;
}

void ExecutorRegistry::add(std::string op, Executor executor) {
  if (!executor) throw ValueError("executor for '" + op + "' is empty");
  const std::lock_guard lock(mutex_);
  const auto [position, inserted] = table_.emplace(std::move(op), std::move(executor));
  if (!inserted) throw ValueError("an executor for operation '" + position->first + "' is already registered");
}

void ExecutorRegistry::replace(std::string op, Executor executor) {
  if (!executor) throw ValueError("executor for '" + op + "' is empty");
  const std::lock_guard lock(mutex_);
  table_.insert_or_assign(std::move(op), std::move(executor));
}

bool ExecutorRegistry::remove(std::string_view op) {
  const std::lock_guard lock(mutex_);
  const auto found = table_.find(op);
  if (found == table_.end()) return false;
  table_.erase(found);
  return true;
}

bool ExecutorRegistry::contains(std::string_view op) const {
  const std::lock_guard lock(mutex_);
  return table_.find(op) != table_.end();
}

Executor ExecutorRegistry::find(std::string_view op) const {
  const std::lock_guard lock(mutex_);
  const auto found = table_.find(op);
  return found == table_.end() ? Executor{} : found->second;
}

std::vector<std::string> ExecutorRegistry::operations() const {
  const std::lock_guard lock(mutex_);
  std::vector<std::string> out;
  out.reserve(table_.size());
  for (const auto& entry : table_) out.push_back(entry.first);
  return out;
}

void register_executor(std::string op, Executor executor) {
  ExecutorRegistry::global().add(std::move(op), std::move(executor));
}

}  // namespace scad::reactive
