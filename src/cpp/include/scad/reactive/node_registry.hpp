// A process-wide table of recorded nodes by (graph id, node id).
//
// A notebook cell records into a session of its own and hands its values to the cells
// below it; those values remember only the id of the node that produced them.  A session
// created with `shared_lineage` finds the node a foreign value came from here and adopts
// it (with everything upstream), as the Python SDK does with the node object the value
// carried.  Ids are namespaced per cell, so a re-run of a cell replaces its entries.
#pragma once

#include <string>
#include <string_view>

#include "scad/reactive/graph.hpp"

namespace scad::reactive {

void register_node(const NodePtr& node);
// nullptr when the node was never registered (or the graph was forgotten).
NodePtr find_registered_node(std::string_view graph_id, std::string_view node_id);
void forget_graph_nodes(std::string_view graph_id);

}  // namespace scad::reactive
