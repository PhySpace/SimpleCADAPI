// tracked_cut / tracked_union / tracked_intersect / track_union_history.
//
// A boolean's history is asked of the faces of every input; what a face became
// (modified, generated edges, deleted) is only reported when it lands in the
// result, so the filter is a hash lookup into the result, not a search.
#include <TopAbs_ShapeEnum.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/booleans.hpp"
#include "scad/kernel/cast.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

namespace {

TrackedBooleanResult to_boolean_result(std::optional<Solid> solid, tracking::DeltaBuilder&& builder) {
  tracking::Finished finished = std::move(builder).finish();
  return TrackedBooleanResult{std::move(solid), std::move(finished.delta), std::move(finished.delta_entries)};
}

// Face history of one input of a boolean.
void query_input_faces(tracking::HistorySource& history, const Solid& input, std::string_view origin_role,
                       kernel::SubShapeIndex& in_result, tracking::DeltaBuilder& delta) {
  tracking::QuerySpec spec;
  spec.origin_role = origin_role;
  spec.kind = Kind::Face;
  spec.result = &in_result;
  spec.project_source_tags = true;
  tracking::query_sub_shape_history(history, input.wrapped(), TopAbs_FACE, spec, delta.witnesses);
}

std::string input_role(std::size_t index) {
  if (index == 0) return "body";
  if (index == 1) return "tool";
  return "tool_" + std::to_string(index);
}

// body op tool, with history.  `Solid(result)` of the Python SDK is the first
// solid of the kernel's answer (empty when there is none); the history filter
// is the whole answer.
TrackedBooleanResult track_boolean(kernel::BooleanOp op, const Solid& body, const Solid& tool, const char* failure) {
  return occt_guard([&] {
    kernel::BooleanOptions options;
    options.fill_history = true;
    const kernel::BooleanResult run = kernel::run_boolean(op, body.wrapped(), {tool.wrapped()}, options);
    if (!run.done) throw ValueError(failure);

    tracking::DeltaBuilder delta;
    if (tracking::history_wanted()) {
      tracking::RetainedHistory history(*run.history);
      kernel::SubShapeIndex in_result(run.shape);
      query_input_faces(history, body, "body", in_result, delta);
      query_input_faces(history, tool, "tool", in_result, delta);
    }
    // Section edges are reported even when face history is not wanted.
    delta.section_edge_ids.reserve(run.section_edges.size());
    for (const TopoDS_Shape& edge : run.section_edges) delta.section_edge_ids.push_back(kernel_topo_id(edge));

    std::optional<Solid> solid;
    TopoDS_Solid first;
    if (kernel::first_solid(run.shape, first)) solid.emplace(first);
    return to_boolean_result(std::move(solid), std::move(delta));
  });
}

}  // namespace

TrackedBooleanResult tracked_cut(const Solid& body, const Solid& tool) {
  return track_boolean(kernel::BooleanOp::Cut, body, tool, "Boolean cut failed: OCC build did not complete");
}

TrackedBooleanResult tracked_intersect(const Solid& body, const Solid& tool) {
  return track_boolean(kernel::BooleanOp::Common, body, tool,
                       "Boolean intersect failed: OCC build did not complete");
}

TrackedBooleanResult tracked_union(const Solid& body, const Solid& tool, bool glue, double tol) {
  return occt_guard([&] {
    const kernel::FuseHistoryResult fused =
        kernel::fuse_shapes_with_history({body.wrapped(), tool.wrapped()}, glue, tol, /*clean=*/false);
    const std::vector<TopoDS_Solid> solids = kernel::solids_of(fused.shape);
    if (solids.size() != 1) throw ValueError("Boolean union did not produce exactly one solid");
    return track_union_history({body, tool}, Solid(solids.front()), *fused.history, fused.section_edges);
  });
}

TrackedBooleanResult track_union_history(const std::vector<Solid>& solids, const Solid& result_solid,
                                         const BRepTools_History& history,
                                         const std::vector<TopoDS_Shape>& section_edges) {
  if (solids.size() < 2) throw ValueError("Union history tracking requires at least two solids");

  return occt_guard([&] {
    tracking::DeltaBuilder delta;
    kernel::SubShapeIndex in_result(result_solid.wrapped());

    if (tracking::history_wanted()) {
      tracking::RetainedHistory retained(history);
      for (std::size_t i = 0; i < solids.size(); ++i) {
        query_input_faces(retained, solids[i], input_role(i), in_result, delta);
      }
    }

    // The section edges that survive into the result, each once.
    TopTools_IndexedMapOfShape seen;
    for (const TopoDS_Shape& edge : section_edges) {
      if (!in_result.contains(edge)) continue;
      const int before = seen.Extent();
      seen.Add(edge);
      if (seen.Extent() > before) delta.section_edge_ids.push_back(kernel_topo_id(edge));
    }
    return to_boolean_result(result_solid, std::move(delta));
  });
}

}  // namespace scad
