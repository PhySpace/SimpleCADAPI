// How a shape remembers which recorded operation produced it.
//
// The recorder writes these keys into the shape's runtime state (the names are
// the Python SDK's: "graph.node_id", "graph.output_slot", "topo.ref"), so an
// operator, the tracker or the query layer can ask a shape where it came from
// without a reference to the session.
#pragma once

#include <optional>
#include <string>

#include "scad/core/value.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive {

// The operation output a shape is.
struct Lineage {
  std::string graph_id;
  std::string node_id;
  int output_slot = 0;

  bool operator==(const Lineage&) const = default;
};

// The lineage of a recorded output (a root).  nullopt for a shape no session
// has recorded, and for sub-shapes of one (see topo_ref_of).
std::optional<Lineage> lineage_of(const Shape& shape);
void set_lineage(Shape shape, const Lineage& lineage, std::string_view op);
// A node that only re-attributes a shape (a tag assignment: attach_semantic_graph_node) keeps naming what the
// shape contains after the nodes that made it: the first lineage the shape had becomes its topology owner, which
// topo_ref_of uses in place of the node it is now attributed to.
void keep_topology_owner(Shape shape);

// The durable reference of a sub-shape of a recorded output: the output's
// graph, node and slot with the sub-shape's kind and topo id.  Read from the
// "topo.ref" runtime key when a session stamped it (Session::Options::
// attach_topology_refs); otherwise derived on demand by climbing the sub-shape's
// known containment parents to the recorded output, which costs nothing at
// recording time.  nullopt for a shape that is not part of a recorded output.
// (A handle made with Shape::sub carries no parent links: stamp it, or keep
// the handle you enumerated it from.)
std::optional<TopoRef> topo_ref_of(const Shape& shape);
void set_topo_ref(Shape shape, const TopoRef& ref);

}  // namespace scad::reactive
