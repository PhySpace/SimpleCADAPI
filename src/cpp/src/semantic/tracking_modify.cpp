// modification_delta: the history of the builders that finish through finish_solid (affine transforms, offset,
// draft), which used to record no topology delta at all.
#include <set>
#include <string>

#include <TopAbs_ShapeEnum.hxx>

#include "scad/kernel/membership.hpp"
#include "scad/semantic/tracking.hpp"
#include "tracking_detail.hpp"

namespace scad {

TopoDelta modification_delta(const BRepTools_History& history, const TopoDS_Shape& input, const TopoDS_Shape& result,
                             std::string_view modified_derivation, bool generated_faces_continue) {
  if (!tracking::history_wanted())
    return {};
  tracking::RetainedHistory source(history);
  kernel::SubShapeIndex in_result(result);
  tracking::DeltaBuilder delta;
  for (const auto& [type, kind] : {std::pair{TopAbs_FACE, Kind::Face}, std::pair{TopAbs_EDGE, Kind::Edge}}) {
    tracking::QuerySpec spec;
    spec.origin_role = "body";
    spec.kind = kind;
    spec.result = &in_result;
    spec.modified_derivation = modified_derivation;
    const std::size_t begin = delta.witnesses.size();
    tracking::query_sub_shape_history(source, input, type, spec, delta.witnesses);
    if (!generated_faces_continue || kind != Kind::Face)
      continue;
    // An input face that only generated faces (no preserved / modified image) moved: its generated face is it.
    std::set<std::string> kept;
    for (std::size_t i = begin; i < delta.witnesses.size(); ++i) {
      const tracking::Witness& w = delta.witnesses[i];
      if (w.event == TopoEvent::Preserved || w.event == TopoEvent::Modified)
        kept.insert(w.input_topo_id);
    }
    for (std::size_t i = begin; i < delta.witnesses.size(); ++i) {
      tracking::Witness& w = delta.witnesses[i];
      if (w.event == TopoEvent::Generated && w.kind == Kind::Face && kept.count(w.input_topo_id) == 0) {
        w.event = TopoEvent::Modified;
        w.derivation = "continuation";
      }
    }
  }
  return std::move(delta).finish().delta;
}

}  // namespace scad
