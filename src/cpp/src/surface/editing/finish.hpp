// How every edit ends: rebuild the shape on the edited geometry, derive the TopoDelta from the rebuild's history,
// record the operation and apply the tag prefix.  Not installed.
#pragma once

#include <string>

#include <BRepTools_History.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/core/error.hpp"
#include "scad/core/value.hpp"
#include "scad/surface/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad::surface::editing {

// `curve` / `surface` is in the representation frame `location` of the source and keeps its parametrisation.
// `params` are the recorded parameters (tag_prefix is added here).
Edge finish_edge(const Edge& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                 const Handle(Geom_Curve) & curve, const TopLoc_Location& location);
Face finish_face(const Face& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                 const Handle(Geom_Surface) & surface, const TopLoc_Location& location);

// A result that some kernel builder made (the explicit conversions): `history` maps source -> result.
Edge finish_built_edge(const Edge& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                       const TopoDS_Shape& built, const BRepTools_History& history);
Face finish_built_face(const Face& source, const std::string& op, Value params, const TagPrefix& tag_prefix,
                       const TopoDS_Shape& built, const BRepTools_History& history);

// The operator's error contract around `body` (every failure leaves as the operation's scad::Error).
template <class F>
decltype(auto) edit_scope(const ErrorSpec& spec, F&& body) {
  return guarded(spec, [&]() -> decltype(auto) { return occt_guard(body); });
}

}  // namespace scad::surface::editing
