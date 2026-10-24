#include "scad/ops/geometry/wires.hpp"

#include <TopoDS.hxx>

#include "internal.hpp"

namespace scad {

Wire make_wire_from_edges_rwire(const std::vector<Edge>& edges, const OptionalString& tag_prefix) {
  using namespace geometry_detail;
  static constexpr const char* kOp = "make_wire_from_edges_rwire";
  static const ErrorSpec kSpec{kOp,
                               "Failed to assemble a wire from the input edges.",
                               {"The edge list is empty.", "One or more items are invalid edges.",
                                "The edges do not connect into a valid wire chain."},
                               {"Pass a non-empty list of Edge objects.",
                                "Ensure consecutive edges share matching endpoints.",
                                "Inspect the edge order if the wire should form a closed loop."}};
  return guarded(kSpec, [&] {
    if (edges.empty()) throw ValueError("The edge list cannot be empty");
    std::vector<TopoDS_Edge> raw;
    raw.reserve(edges.size());
    for (const Edge& edge : edges) raw.push_back(TopoDS::Edge(edge.wrapped()));

    FinalizeSpec spec = derived_spec(record_for(kOp, [&] {
      OpParams params(kOp, derived_labels("wire"));
      params.integer("edge_count", static_cast<std::int64_t>(edges.size()));
      for (const Edge& edge : edges) params.input(edge, "edge");
      return params.take();
    }));
    Wire wire = finalize_derived(Wire(kernel::make_wire_from_edges(raw)), std::move(spec));
    wire = Wire(copy_exact_topology_identity_tags(std::move(wire), std::vector<Shape>(edges.begin(), edges.end()), kOp));
    return with_shape_prefix(std::move(wire), tag_prefix, kOp);
  });
}

}  // namespace scad
