// Session: variables, change-impact queries.
#include <algorithm>
#include <cmath>
#include <unordered_set>

#include "scad/core/error.hpp"
#include "scad/reactive/session.hpp"

namespace scad::reactive {

void Session::declare_var(const std::shared_ptr<const Var>& var) {
  if (!var)
    throw TypeError("declare_var needs a Var");
  if (var_index_.emplace(var->name(), vars_.size()).second)
    vars_.push_back(var);
}

bool Session::has_var(std::string_view name) const noexcept {
  return var_index_.find(std::string(name)) != var_index_.end();
}

std::vector<ParamSpec> Session::parameters() const {
  std::vector<ParamSpec> specs;
  specs.reserve(vars_.size());
  for (const std::shared_ptr<const Var>& var : vars_) {
    ParamSpec spec = var->param_spec();
    spec.default_value = Value(var_value(var->name()));
    specs.push_back(std::move(spec));
  }
  return specs;
}

double Session::var_value(std::string_view name) const {
  const auto found = var_index_.find(std::string(name));
  if (found == var_index_.end())
    throw KeyError("unknown variable '" + std::string(name) + "'");
  const auto edit = bindings_.find(name);
  return edit != bindings_.end() ? edit->second : vars_[found->second]->default_value();
}

void Session::check_var_value(const Var& var, double value) const {
  if (!std::isfinite(value))
    throw ValueError("Binding '" + var.name() + "' must be finite");
  if (var.unit())
    var.unit()->to_canonical(value);  // out-of-range values fail here, not in the middle of a recompute
}

void Session::set_var(std::string_view name, double value) {
  set_vars({{std::string(name), value}});
}

void Session::set_vars(const std::vector<std::pair<std::string, double>>& values) {
  for (const auto& [name, value] : values) {
    const auto found = var_index_.find(name);
    if (found == var_index_.end()) {
      throw KeyError("unknown variable '" + name + "'; known variables: " + [this] {
        std::string list;
        for (const auto& v : vars_)
          list += (list.empty() ? "" : ", ") + v->name();
        return list.empty() ? std::string("(none)") : list;
      }());
    }
    check_var_value(*vars_[found->second], value);
  }
  std::vector<std::string> changed;
  for (const auto& [name, value] : values) {
    if (var_value(name) == value)
      continue;
    bindings_[name] = value;
    changed.push_back(name);
  }
  if (!changed.empty())
    mark_dirty(affected_nodes(changed));
}

void Session::reset_var(std::string_view name) {
  if (!has_var(name))
    throw KeyError("unknown variable '" + std::string(name) + "'");
  const auto edit = bindings_.find(name);
  if (edit == bindings_.end())
    return;
  bindings_.erase(edit);
  mark_dirty(affected_nodes(std::string(name)));
}

void Session::reset_vars() {
  std::vector<std::string> names;
  for (const auto& entry : bindings_)
    names.push_back(entry.first);
  bindings_.clear();
  if (!names.empty())
    mark_dirty(affected_nodes(names));
}

// ---------------------------------------------------------------------------
// Impact
// ---------------------------------------------------------------------------

std::vector<std::string> Session::nodes_using(std::string_view var_name) const {
  const auto found = users_.find(std::string(var_name));
  if (found == users_.end())
    return {};
  std::unordered_set<std::string> wanted(found->second.begin(), found->second.end());
  std::vector<std::string> out;
  for (const NodePtr& node : graph_.nodes()) {
    if (wanted.count(node->node_id) != 0)
      out.push_back(node->node_id);
  }
  return out;
}

std::vector<std::string> Session::downstream_closure(const std::vector<std::string>& seeds) const {
  std::unordered_set<std::string> reached(seeds.begin(), seeds.end());
  std::vector<std::string> stack(seeds.begin(), seeds.end());
  while (!stack.empty()) {
    const std::string id = std::move(stack.back());
    stack.pop_back();
    for (const std::string& next : graph_.downstream_nodes(id)) {
      if (reached.insert(next).second)
        stack.push_back(next);
    }
  }
  std::vector<std::string> out;
  for (const NodePtr& node : graph_.nodes()) {
    if (reached.count(node->node_id) != 0)
      out.push_back(node->node_id);
  }
  return out;
}

std::vector<std::string> Session::affected_nodes(std::string_view var_name) const {
  return affected_nodes(std::vector<std::string>{std::string(var_name)});
}

std::vector<std::string> Session::affected_nodes(const std::vector<std::string>& var_names) const {
  std::vector<std::string> seeds;
  for (const std::string& name : var_names) {
    if (!has_var(name))
      throw KeyError("unknown variable '" + name + "'");
    const auto found = users_.find(name);
    if (found != users_.end())
      seeds.insert(seeds.end(), found->second.begin(), found->second.end());
  }
  return downstream_closure(seeds);
}

std::vector<std::string> Session::vars_affecting(std::string_view node_id) const {
  const NodePtr start = graph_.get_node(node_id);
  if (!start)
    throw KeyError("unknown node id '" + std::string(node_id) + "'");
  std::unordered_set<std::string> seen;
  std::unordered_set<std::string> names;
  std::vector<NodePtr> stack{start};
  while (!stack.empty()) {
    const NodePtr node = std::move(stack.back());
    stack.pop_back();
    if (!seen.insert(node->node_id).second)
      continue;
    for (const std::string& name : state_of(node->node_id).var_names)
      names.insert(name);
    for (const NodePtr& input : node->inputs)
      stack.push_back(input);
  }
  std::vector<std::string> out;  // in the order the variables were first used
  for (const auto& var : vars_) {
    if (names.count(var->name()) != 0)
      out.push_back(var->name());
  }
  return out;
}

}  // namespace scad::reactive
