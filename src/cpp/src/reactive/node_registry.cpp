#include "scad/reactive/node_registry.hpp"

#include <mutex>
#include <unordered_map>

namespace scad::reactive {

namespace {

struct Registry {
  std::mutex mutex;
  std::unordered_map<std::string, std::unordered_map<std::string, NodePtr>> graphs;
};

Registry& registry() {
  static Registry instance;
  return instance;
}

}  // namespace

void register_node(const NodePtr& node) {
  Registry& r = registry();
  const std::lock_guard lock(r.mutex);
  r.graphs[node->graph_id][node->node_id] = node;
}

NodePtr find_registered_node(std::string_view graph_id, std::string_view node_id) {
  Registry& r = registry();
  const std::lock_guard lock(r.mutex);
  const auto graph = r.graphs.find(std::string(graph_id));
  if (graph == r.graphs.end()) return nullptr;
  const auto found = graph->second.find(std::string(node_id));
  return found == graph->second.end() ? nullptr : found->second;
}

void forget_graph_nodes(std::string_view graph_id) {
  Registry& r = registry();
  const std::lock_guard lock(r.mutex);
  r.graphs.erase(std::string(graph_id));
}

}  // namespace scad::reactive
