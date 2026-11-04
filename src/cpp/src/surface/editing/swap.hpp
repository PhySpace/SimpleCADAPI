// Rebuilding a face or an edge on new geometry with the SAME parametrisation: the topology is copied by
// BRepTools_Modifier, the face's pcurves (its trimming in (u, v)) are kept, its 3D edge curves and vertices are
// recomputed on the new surface.  The history (old -> new for the face, every edge and vertex) is what the
// recorded TopoDelta is made from.  Not installed.
#pragma once

#include <BRepTools_History.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>

namespace scad::surface::editing {

struct Swapped {
  TopoDS_Shape shape;
  BRepTools_History history;
};

// `surface` replaces the face's surface; it is in the representation frame `location` (absolute, as
// BRep_Tool::Surface(face, location) answers) and must be parametrised like the old one over the face's (u, v) loops.
// ValueError when the rebuilt face is not valid.
Swapped swap_face_surface(const TopoDS_Face& face, const Handle(Geom_Surface) & surface,
                          const TopLoc_Location& location);

// `curve` replaces the edge's 3D curve over the same parameter range (representation frame `location`).  Pcurves the
// edge had on faces of another shape are not carried: the result is a free edge.
Swapped swap_edge_curve(const TopoDS_Edge& edge, const Handle(Geom_Curve) & curve, const TopLoc_Location& location);

}  // namespace scad::surface::editing
