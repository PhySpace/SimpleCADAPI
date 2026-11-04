// The common tail of the edit operators; see finish.hpp.
#include "finish.hpp"

#include <BRepTools_History.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

#include "../finalize.hpp"
#include "scad/semantic/tracking.hpp"
#include "swap.hpp"

namespace scad::surface::editing {

namespace {

template <class T>
T finish(const T& source, const std::string& op, Value params, const TagPrefix& tag_prefix, const TopoDS_Shape& built,
         const BRepTools_History& history, TopAbs_ShapeEnum type, const char* what) {
  TopoDS_Shape single;
  for (TopExp_Explorer it(built, type); it.More(); it.Next()) {
    if (!single.IsNull())
      throw ValueError(std::string("the rebuild produced more than one ") + what);
    single = it.Current();
  }
  if (single.IsNull())
    throw ValueError(std::string("the rebuild produced no ") + what);
  TopoDelta delta = modification_delta(history, source.wrapped(), single, "continuation");
  params.set("tag_prefix", tag_prefix ? Value(*tag_prefix) : Value());
  detail::OperationRecord record{.op = op, .params = std::move(params), .inputs = {{source, what}}};
  return detail::finalize_surface_output(
      T(single),
      detail::EditOutput{
          .record = std::move(record), .tag_prefix = tag_prefix, .source = source, .delta = std::move(delta)});
}

}  // namespace

Edge finish_edge(const Edge& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                 const Handle(Geom_Curve) & curve, const TopLoc_Location& location) {
  const Swapped swapped = swap_edge_curve(TopoDS::Edge(source.wrapped()), curve, location);
  return finish(source, op, std::move(params), tag_prefix, swapped.shape, swapped.history, TopAbs_EDGE, "edge");
}

Face finish_face(const Face& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                 const Handle(Geom_Surface) & surface, const TopLoc_Location& location) {
  const Swapped swapped = swap_face_surface(TopoDS::Face(source.wrapped()), surface, location);
  return finish(source, op, std::move(params), tag_prefix, swapped.shape, swapped.history, TopAbs_FACE, "face");
}

Edge finish_built_edge(const Edge& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                       const TopoDS_Shape& built, const BRepTools_History& history) {
  return finish(source, op, std::move(params), tag_prefix, built, history, TopAbs_EDGE, "edge");
}

Face finish_built_face(const Face& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                       const TopoDS_Shape& built, const BRepTools_History& history) {
  return finish(source, op, std::move(params), tag_prefix, built, history, TopAbs_FACE, "face");
}

}  // namespace scad::surface::editing
